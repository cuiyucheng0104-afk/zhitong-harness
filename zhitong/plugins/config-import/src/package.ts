/**
 * Reading and validating a customer config package (`zhitong.config.json`,
 * alone or inside a `.zip`). Validation messages name field paths only, never
 * values, so secrets cannot leak through errors. The format is documented in
 * `zhitong/CONFIG-PACKAGE.md`.
 * @module @zhitong/config-import/package
 */

import { readFile, stat } from 'node:fs/promises'
import { unzipSync } from 'fflate'

/** Format tag every package carries. */
export const PACKAGE_FORMAT = 'zhitong.config/1'

/** File name of the package document, standalone or inside the zip. */
export const PACKAGE_FILENAME = 'zhitong.config.json'

/** Validated TOS section. */
export interface TosSection {
  readonly endpoint: string
  readonly region: string
  readonly bucket: string
  readonly prefix: string
  readonly accessKeyId: string
  readonly secretAccessKey: string
}

/** Validated SSH host (applied by the zt-volc work order; validated here). */
export interface SshHost {
  readonly alias: string
  readonly host: string
  readonly port: number
  readonly user: string
  readonly privateKey?: string
}

/** Validated package. */
export interface ConfigPackage {
  readonly company: { readonly name: string }
  readonly tos: TosSection
  readonly ssh?: { readonly hosts: readonly SshHost[] }
  readonly volc?: { readonly profile: string; readonly region?: string }
}

/** A package that cannot be read or does not validate; `problems` lists field paths and rules. */
export class PackageError extends Error {
  override readonly name = 'PackageError'

  /**
   * @param message - summary.
   * @param problems - one line per violated rule, naming the field path.
   */
  constructor(message: string, readonly problems: readonly string[] = []) {
    super(problems.length === 0 ? message : `${message}：\n- ${problems.join('\n- ')}`)
  }
}

/**
 * Read the package document from a `.json` file or a `.zip` that contains
 * exactly one `zhitong.config.json` (at the root or one directory down).
 * @param filePath - absolute path of the package.
 * @param maxBytes - upper bound for the file and for the extracted document.
 * @returns the document text.
 * @throws PackageError when the file is missing, too large, or the zip layout is wrong.
 */
export async function readPackageText(filePath: string, maxBytes: number): Promise<string> {
  let size: number
  try {
    size = (await stat(filePath)).size
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') throw new PackageError(`找不到配置包 ${filePath}`)
    throw error
  }
  if (size > maxBytes) throw new PackageError(`配置包 ${size} 字节，超过上限 ${maxBytes} 字节`)
  const bytes = await readFile(filePath)
  if (!filePath.toLowerCase().endsWith('.zip')) return new TextDecoder('utf-8', { fatal: false }).decode(bytes)
  let entries: Record<string, Uint8Array>
  try {
    entries = unzipSync(bytes, {
      filter: file => isPackageEntry(file.name) && file.originalSize <= maxBytes,
    })
  } catch {
    // fflate reports corrupt archives with its own message; the archive name is the useful part.
    throw new PackageError(`${filePath} 不是有效的 zip 文件`)
  }
  const names = Object.keys(entries)
  if (names.length === 0) throw new PackageError(`zip 里没有 ${PACKAGE_FILENAME}（或该文件超过 ${maxBytes} 字节）`)
  if (names.length > 1) throw new PackageError(`zip 里有多个 ${PACKAGE_FILENAME}：${names.join('，')}`)
  return new TextDecoder('utf-8').decode(entries[names[0]!])
}

function isPackageEntry(name: string): boolean {
  const parts = name.split('/').filter(part => part !== '')
  return parts.length >= 1 && parts.length <= 2 && parts.at(-1) === PACKAGE_FILENAME && !parts.some(part => part === '__MACOSX')
}

/**
 * Parse and validate the package document.
 * @param text - document text.
 * @returns the validated package.
 * @throws PackageError listing every violated rule.
 */
export function parsePackage(text: string): ConfigPackage {
  let raw: unknown
  try {
    raw = JSON.parse(text.replace(/^﻿/u, ''))
  } catch (error) {
    // V8 messages quote document text; report only the position so no secret is echoed.
    const position = /position (\d+)/u.exec(String(error))?.[1]
    throw new PackageError(`${PACKAGE_FILENAME} 不是合法 JSON${position !== undefined ? `（位置 ${position} 附近）` : ''}`)
  }
  const problems: string[] = []
  const root = objectAt(raw, '', problems)
  if (root === undefined) throw new PackageError('配置包校验失败', problems)
  if (root['format'] !== PACKAGE_FORMAT) problems.push(`format 必须是 "${PACKAGE_FORMAT}"`)
  allowOnly(root, '', ['format', 'company', 'tos', 'ssh', 'volc', 'comment'], problems)

  const company = objectAt(root['company'], 'company', problems)
  const companyName = company === undefined ? '' : text1(company, 'company', 'name', problems)
  if (company !== undefined) allowOnly(company, 'company', ['name'], problems)

  const tosRaw = objectAt(root['tos'], 'tos', problems)
  let tos: TosSection | undefined
  if (tosRaw !== undefined) {
    allowOnly(tosRaw, 'tos', ['endpoint', 'region', 'bucket', 'prefix', 'accessKeyId', 'secretAccessKey'], problems)
    const endpoint = text1(tosRaw, 'tos', 'endpoint', problems)
    if (endpoint !== '' && !/^[a-z0-9.-]+(:\d+)?$/iu.test(endpoint)) problems.push('tos.endpoint 只写主机名（如 tos-cn-beijing.volces.com），不带 https:// 与路径')
    const region = text1(tosRaw, 'tos', 'region', problems)
    const bucket = text1(tosRaw, 'tos', 'bucket', problems)
    if (bucket !== '' && !/^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/u.test(bucket)) problems.push('tos.bucket 只能含小写字母、数字与 -，长度 3–63')
    const prefixRaw = tosRaw['prefix']
    let prefix = ''
    if (prefixRaw !== undefined) {
      if (typeof prefixRaw !== 'string') problems.push('tos.prefix 必须是字符串')
      else {
        prefix = prefixRaw.split('/').filter(part => part !== '').join('/')
        if (prefix.split('/').some(part => part === '..' || part === '.' || /[\\\u0000-\u001f]/u.test(part))) {
          problems.push('tos.prefix 不能含 . 或 .. 段、反斜杠与控制字符')
        }
      }
    }
    const accessKeyId = secret(tosRaw, 'tos', 'accessKeyId', problems)
    const secretAccessKey = secret(tosRaw, 'tos', 'secretAccessKey', problems)
    tos = { endpoint, region, bucket, prefix, accessKeyId, secretAccessKey }
  }

  let ssh: ConfigPackage['ssh']
  if (root['ssh'] !== undefined) {
    const sshRaw = objectAt(root['ssh'], 'ssh', problems)
    if (sshRaw !== undefined) {
      allowOnly(sshRaw, 'ssh', ['hosts'], problems)
      const hostsRaw = sshRaw['hosts']
      if (!Array.isArray(hostsRaw)) problems.push('ssh.hosts 必须是数组')
      else {
        const hosts: SshHost[] = []
        const aliases = new Set<string>()
        hostsRaw.forEach((item: unknown, index: number) => {
          const at = `ssh.hosts[${index}]`
          const host = objectAt(item, at, problems)
          if (host === undefined) return
          allowOnly(host, at, ['alias', 'host', 'port', 'user', 'privateKey'], problems)
          const alias = text1(host, at, 'alias', problems)
          if (alias !== '' && !/^[A-Za-z0-9][A-Za-z0-9_-]*$/u.test(alias)) problems.push(`${at}.alias 只能含字母、数字、_ 与 -`)
          if (aliases.has(alias)) problems.push(`${at}.alias 与前面的主机重复`)
          aliases.add(alias)
          const port = host['port'] ?? 22
          if (typeof port !== 'number' || !Number.isInteger(port) || port < 1 || port > 65535) problems.push(`${at}.port 必须是 1–65535 的整数`)
          const privateKey = host['privateKey'] === undefined ? undefined : secret(host, at, 'privateKey', problems, false)
          hosts.push({
            alias,
            host: text1(host, at, 'host', problems),
            port: typeof port === 'number' ? port : 22,
            user: text1(host, at, 'user', problems),
            ...privateKey !== undefined ? { privateKey } : {},
          })
        })
        ssh = { hosts }
      }
    }
  }

  let volc: ConfigPackage['volc']
  if (root['volc'] !== undefined) {
    const volcRaw = objectAt(root['volc'], 'volc', problems)
    if (volcRaw !== undefined) {
      allowOnly(volcRaw, 'volc', ['profile', 'region'], problems)
      const profile = text1(volcRaw, 'volc', 'profile', problems)
      const region = volcRaw['region']
      if (region !== undefined && typeof region !== 'string') problems.push('volc.region 必须是字符串')
      volc = { profile, ...typeof region === 'string' ? { region } : {} }
    }
  }

  if (problems.length > 0 || tos === undefined) throw new PackageError('配置包校验失败', problems)
  return { company: { name: companyName }, tos, ...ssh !== undefined ? { ssh } : {}, ...volc !== undefined ? { volc } : {} }
}

function objectAt(value: unknown, at: string, problems: string[]): Record<string, unknown> | undefined {
  if (typeof value === 'object' && value !== null && !Array.isArray(value)) return value as Record<string, unknown>
  problems.push(at === '' ? '顶层必须是 JSON 对象' : `${at} 必须是对象`)
  return undefined
}

function allowOnly(object: Record<string, unknown>, at: string, keys: readonly string[], problems: string[]): void {
  for (const key of Object.keys(object)) {
    if (!keys.includes(key)) problems.push(`${at === '' ? '' : `${at}.`}${key} 不是认识的字段`)
  }
}

function text1(object: Record<string, unknown>, at: string, key: string, problems: string[]): string {
  const value = object[key]
  if (typeof value !== 'string' || value.trim() === '') {
    problems.push(`${at}.${key} 必须是非空字符串`)
    return ''
  }
  return value.trim()
}

function secret(object: Record<string, unknown>, at: string, key: string, problems: string[], trim = true): string {
  const value = object[key]
  if (typeof value !== 'string' || value.trim() === '') {
    problems.push(`${at}.${key} 必须是非空字符串（密钥）`)
    return ''
  }
  // Access keys are trimmed against copy-paste whitespace; PEM keys keep their trailing newline.
  return trim ? value.trim() : value
}
