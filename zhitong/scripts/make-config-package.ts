#!/usr/bin/env -S pnpm exec tsx
/**
 * Build one customer's config package (`zhitong.config.json` inside a zip) for 智通数工AI.
 *
 *   pnpm exec tsx zhitong/scripts/make-config-package.ts --company <公司名> --bucket <桶> --prefix <前缀>
 *       --out <目录> [--endpoint tos-cn-beijing.volces.com] [--region cn-beijing] [--comment <备注>]
 *       [--skip-probe] [--expect-prefix-only]
 *
 * The access key pair comes from the environment only: `ZT_PKG_ACCESS_KEY_ID` and `ZT_PKG_SECRET_ACCESS_KEY`
 * (never from arguments, so it stays out of shell history and process listings). The document is validated
 * with the same parser `config_import` uses, so a package this script writes imports cleanly.
 *
 * Unless `--skip-probe`, the key is exercised against the bucket before anything is written: list the prefix,
 * put/head/delete a probe object under it, and with `--expect-prefix-only` also confirm that listing the bucket
 * root is denied (the policy is scoped to the prefix). A failed probe writes no package and exits 2.
 *
 * Output: `<out>/<公司名>/zhitong.config.json` (mode 0600) and `<out>/<公司名>-zhitong-config-<YYYYMMDD>.zip`.
 * The summary printed to stdout never contains the key.
 */

import { createRequire } from 'node:module'
import { chmodSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { parseArgs } from 'node:util'

const ZHITONG = resolve(import.meta.dirname, '..')
const requireFromConfigImport = createRequire(join(ZHITONG, 'plugins', 'config-import', 'package.json'))
const requireFromToolTos = createRequire(join(ZHITONG, 'plugins', 'tool-tos', 'package.json'))

/** Fields the operator supplies; the key pair is read from the environment. */
export interface PackageRequest {
  readonly company: string
  readonly bucket: string
  readonly prefix: string
  readonly endpoint: string
  readonly region: string
  readonly comment?: string
}

/** Sanitize a company name into a file-system safe stem. */
export function fileStem(company: string): string {
  return company.replace(/[\s/\\:*?"<>|]+/gu, '').trim() || 'customer'
}

/**
 * Build the package document.
 * @param request - connection fields.
 * @param accessKeyId - key id.
 * @param secretAccessKey - secret.
 * @returns JSON text, validated with the `config_import` parser.
 */
export async function buildDocument(request: PackageRequest, accessKeyId: string, secretAccessKey: string): Promise<string> {
  const { parsePackage } = await import(join(ZHITONG, 'plugins', 'config-import', 'src', 'package.ts')) as {
    parsePackage: (text: string) => unknown
  }
  const document = {
    format: 'zhitong.config/1',
    ...request.comment !== undefined ? { comment: request.comment } : {},
    company: { name: request.company },
    tos: {
      endpoint: request.endpoint,
      region: request.region,
      bucket: request.bucket,
      prefix: request.prefix,
      accessKeyId,
      secretAccessKey,
    },
  }
  const text = `${JSON.stringify(document, null, 2)}\n`
  parsePackage(text)
  return text
}

/** Zip bytes holding `<stem>/zhitong.config.json`, the layout `config_import` accepts. */
export function zipDocument(stem: string, text: string): Uint8Array {
  const { zipSync, strToU8 } = requireFromConfigImport('fflate') as typeof import('fflate')
  return zipSync({ [`${stem}/zhitong.config.json`]: strToU8(text) }, { level: 6 })
}

interface ProbeResult {
  readonly listed: number
  readonly rootDenied: boolean | undefined
}

/**
 * Exercise the key against the bucket: list the prefix, put/head/delete a probe object, optionally
 * confirm the bucket root is not listable.
 * @param request - connection fields.
 * @param accessKeyId - key id.
 * @param secretAccessKey - secret.
 * @param expectPrefixOnly - also require that listing the bucket root fails with 403.
 * @returns what was observed.
 * @throws Error naming the failing step; the message never includes the key.
 */
export async function probeBucket(
  request: PackageRequest, accessKeyId: string, secretAccessKey: string, expectPrefixOnly: boolean,
): Promise<ProbeResult> {
  const { TosClient } = requireFromToolTos('@volcengine/tos-sdk') as typeof import('@volcengine/tos-sdk')
  const client = new TosClient({
    accessKeyId, accessKeySecret: secretAccessKey, region: request.region, endpoint: request.endpoint, bucket: request.bucket,
  })
  const prefix = request.prefix === '' ? '' : `${request.prefix}/`
  const step = async <T>(name: string, run: () => Promise<T>): Promise<T> => {
    try {
      return await run()
    } catch (error) {
      throw new Error(`探测失败：${name}：${describe(error)}`)
    }
  }
  const { data } = await step('列出前缀', () => client.listObjectsType2({ prefix, maxKeys: 5, listOnlyOnce: true }))
  const listed = (data.Contents ?? []).length + (data.CommonPrefixes ?? []).length
  const key = `${prefix}.zhitong-config-probe-${Date.now()}`
  await step('写入探测对象', () => client.putObject({ key, body: Buffer.from('zhitong config probe\n') }))
  await step('读取探测对象', () => client.headObject({ key }))
  await step('删除探测对象', () => client.deleteObject({ key }))
  let rootDenied: boolean | undefined
  if (expectPrefixOnly && request.prefix !== '') {
    try {
      await client.listObjectsType2({ prefix: '', maxKeys: 1, listOnlyOnce: true })
      rootDenied = false
    } catch (error) {
      if (statusOf(error) !== 403) throw new Error(`探测失败：列出桶根：${describe(error)}`)
      rootDenied = true
    }
    if (!rootDenied) throw new Error('探测失败：这把密钥能列出桶根目录，策略没有限制到前缀（--expect-prefix-only）')
  }
  return { listed, rootDenied }
}

function statusOf(error: unknown): number | undefined {
  return typeof error === 'object' && error !== null && typeof (error as { statusCode?: unknown }).statusCode === 'number'
    ? (error as { statusCode: number }).statusCode
    : undefined
}

function describe(error: unknown): string {
  const status = statusOf(error)
  const code = typeof error === 'object' && error !== null && typeof (error as { code?: unknown }).code === 'string'
    ? (error as { code: string }).code
    : undefined
  if (status !== undefined || code !== undefined) return [status === undefined ? '' : `HTTP ${status}`, code ?? ''].filter(Boolean).join(' ')
  return error instanceof Error ? error.message : String(error)
}

async function main(): Promise<void> {
  const { values } = parseArgs({
    options: {
      company: { type: 'string' },
      bucket: { type: 'string' },
      prefix: { type: 'string' },
      out: { type: 'string' },
      endpoint: { type: 'string', default: 'tos-cn-beijing.volces.com' },
      region: { type: 'string', default: 'cn-beijing' },
      comment: { type: 'string' },
      'skip-probe': { type: 'boolean', default: false },
      'expect-prefix-only': { type: 'boolean', default: false },
    },
    allowPositionals: false,
  })
  if (values.company === undefined || values.bucket === undefined || values.prefix === undefined || values.out === undefined) {
    throw new Error('usage: --company <公司名> --bucket <桶> --prefix <前缀> --out <目录> [--endpoint] [--region] [--comment] [--skip-probe] [--expect-prefix-only]')
  }
  const accessKeyId = process.env['ZT_PKG_ACCESS_KEY_ID']?.trim() ?? ''
  const secretAccessKey = process.env['ZT_PKG_SECRET_ACCESS_KEY']?.trim() ?? ''
  if (accessKeyId === '' || secretAccessKey === '') {
    throw new Error('环境变量 ZT_PKG_ACCESS_KEY_ID 与 ZT_PKG_SECRET_ACCESS_KEY 必须都设置（不要作为命令行参数传入）')
  }
  const request: PackageRequest = {
    company: values.company,
    bucket: values.bucket,
    prefix: values.prefix.split('/').filter(part => part !== '').join('/'),
    endpoint: values.endpoint,
    region: values.region,
    ...values.comment !== undefined ? { comment: values.comment } : {},
  }
  const text = await buildDocument(request, accessKeyId, secretAccessKey)
  if (!values['skip-probe']) {
    const probe = await probeBucket(request, accessKeyId, secretAccessKey, values['expect-prefix-only'])
    console.log(`探测通过：tos://${request.bucket}/${request.prefix}/ 可列出（当前 ${probe.listed} 项）、可写、可读、可删`
      + (probe.rootDenied === true ? '；桶根目录已拒绝（策略限制在前缀内）' : ''))
  } else {
    console.log('已跳过连桶探测（--skip-probe）')
  }
  const stem = fileStem(request.company)
  const out = resolve(values.out)
  const directory = join(out, stem)
  mkdirSync(directory, { recursive: true })
  const jsonPath = join(directory, 'zhitong.config.json')
  const date = new Date().toISOString().slice(0, 10).replaceAll('-', '')
  const zipPath = join(out, `${stem}-zhitong-config-${date}.zip`)
  if (existsSync(zipPath)) throw new Error(`${zipPath} 已存在；换一个 --out 目录或删掉旧包`)
  writeFileSync(jsonPath, text, { mode: 0o600 })
  chmodSync(jsonPath, 0o600)
  writeFileSync(zipPath, zipDocument(stem, text), { mode: 0o600 })
  chmodSync(zipPath, 0o600)
  console.log(`配置包：${zipPath}`)
  console.log(`明文文档：${jsonPath}（发给客户后删除）`)
  console.log(`公司：${request.company}；桶：${request.bucket}；前缀：${request.prefix || '(桶根)'}；AK 末四位：${accessKeyId.slice(-4)}`)
}

if (import.meta.main) {
  main().catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error))
    process.exit(2)
  })
}
