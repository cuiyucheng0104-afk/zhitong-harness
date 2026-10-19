/**
 * Applying the `ssh` and `volc` sections of a config package for the zt-volc
 * skill. Only names reach the zt-volc settings file (`volc.profile`,
 * `volc.region`, `ssh.hosts[].alias`); SSH connection fields go into one
 * managed block at the top of the OpenSSH config, and private keys into
 * owner-only files. The `ve` access keys are not part of the package: the user
 * creates the `ve` profile with `ve configure set` (zhitong/CONFIG-PACKAGE.md).
 * @module @zhitong/config-import/remote
 */

import { readFile, realpath } from 'node:fs/promises'
import { join } from 'node:path'
import { writeFileAtomic } from '@deepseek-ai/dsh-atomic-write'
import { PACKAGE_FORMAT } from './package.ts'
import type { ConfigPackage } from './package.ts'

/** Resolved destinations of the remote-access sections. */
export interface RemoteTargets {
  /** zt-volc settings file read through `ZT_VOLC_CONFIG` or its default location. */
  readonly volcConfigPath: string
  /** OpenSSH client configuration receiving the managed `Host` block. */
  readonly sshConfigPath: string
  /** Directory receiving one private key file per host alias. */
  readonly sshKeyDir: string
}

/** What the import wrote for the remote-access sections. */
export interface RemoteResult {
  /** zt-volc settings file, or `''` when the package has neither `volc` nor `ssh`. */
  readonly volcConfig: string
  /** OpenSSH configuration that received the managed block, or `''` without `ssh`. */
  readonly sshConfig: string
  /** Host aliases written into the managed block. */
  readonly sshHosts: readonly string[]
  /** Private key files written, one per host that carries `privateKey`. */
  readonly sshKeys: readonly string[]
}

/** First line of the managed OpenSSH block. */
export const SSH_BLOCK_BEGIN = '# >>> zhitong config-import（由 config_import 生成；重新导入时整块替换，不要在块内手改）>>>'
/** Last line of the managed OpenSSH block. */
export const SSH_BLOCK_END = '# <<< zhitong config-import <<<'

/**
 * The zt-volc settings document: the package's JSON form reduced to names.
 * @param pkg - validated package.
 * @returns document without hosts, users, ports or keys.
 */
export function volcSettingsDocument(pkg: ConfigPackage): Record<string, unknown> {
  return {
    format: PACKAGE_FORMAT,
    company: { name: pkg.company.name },
    ...pkg.volc !== undefined ? { volc: { profile: pkg.volc.profile, ...pkg.volc.region !== undefined ? { region: pkg.volc.region } : {} } } : {},
    ...pkg.ssh !== undefined ? { ssh: { hosts: pkg.ssh.hosts.map(host => ({ alias: host.alias })) } } : {},
  }
}

/**
 * Render the managed OpenSSH block.
 * @param hosts - validated hosts.
 * @param keyPath - key file path for one alias.
 * @returns block text ending with a newline.
 */
export function renderSshBlock(hosts: NonNullable<ConfigPackage['ssh']>['hosts'], keyPath: (alias: string) => string): string {
  const lines = [SSH_BLOCK_BEGIN]
  for (const host of hosts) {
    lines.push(`Host ${host.alias}`, `  HostName ${host.host}`, `  Port ${host.port}`, `  User ${host.user}`)
    // OpenSSH on every platform accepts forward slashes; quoting keeps spaces in the home path intact.
    if (host.privateKey !== undefined) lines.push(`  IdentityFile "${keyPath(host.alias).replaceAll('\\', '/')}"`, '  IdentitiesOnly yes')
  }
  lines.push(SSH_BLOCK_END)
  return `${lines.join('\n')}\n`
}

/**
 * Replace the managed block in an OpenSSH configuration, or put it first.
 * The block goes first because OpenSSH keeps the first value it reads for each
 * option, so a later `Host *` section cannot override the imported settings.
 * @param current - existing configuration text (empty when the file is absent).
 * @param block - output of {@link renderSshBlock}.
 * @returns new configuration text.
 * @throws Error when the existing text has a begin marker without its end marker.
 */
export function mergeSshConfig(current: string, block: string): string {
  const normalized = current.replace(/\r\n/gu, '\n')
  const begin = normalized.indexOf(SSH_BLOCK_BEGIN)
  if (begin >= 0) {
    const end = normalized.indexOf(SSH_BLOCK_END, begin)
    if (end < 0) throw new Error(`OpenSSH 配置里只有受管块的开头标记，没有结尾标记「${SSH_BLOCK_END}」；请手工修好后重新导入`)
    const after = normalized.slice(end + SSH_BLOCK_END.length).replace(/^\n/u, '')
    return `${normalized.slice(0, begin)}${block}${after}`
  }
  if (normalized.trim() === '') return block
  return `${block}\n${normalized}`
}

/**
 * Write the zt-volc settings file, the private keys and the managed OpenSSH block.
 * @param pkg - validated package.
 * @param targets - resolved destinations.
 * @returns what was written; sections absent from the package write nothing.
 */
export async function applyRemoteSections(pkg: ConfigPackage, targets: RemoteTargets): Promise<RemoteResult> {
  let volcConfig = ''
  if (pkg.volc !== undefined || pkg.ssh !== undefined) {
    await writeFileAtomic(targets.volcConfigPath, `${JSON.stringify(volcSettingsDocument(pkg), null, 2)}\n`, { mode: 0o600, dirMode: 0o700 })
    volcConfig = targets.volcConfigPath
  }
  if (pkg.ssh === undefined) return { volcConfig, sshConfig: '', sshHosts: [], sshKeys: [] }

  const keyPath = (alias: string): string => join(targets.sshKeyDir, alias)
  const sshKeys: string[] = []
  for (const host of pkg.ssh.hosts) {
    if (host.privateKey === undefined) continue
    // OpenSSH rejects a key without a final newline on some versions.
    const key = host.privateKey.endsWith('\n') ? host.privateKey : `${host.privateKey}\n`
    await writeFileAtomic(keyPath(host.alias), key, { mode: 0o600, dirMode: 0o700 })
    sshKeys.push(keyPath(host.alias))
  }
  // A symlinked config (dotfile managers) is updated at its target so the link survives the atomic rename.
  let configFile = targets.sshConfigPath
  let current = ''
  try {
    configFile = await realpath(targets.sshConfigPath)
    current = await readFile(configFile, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  await writeFileAtomic(configFile, mergeSshConfig(current, renderSshBlock(pkg.ssh.hosts, keyPath)), { mode: 0o600, dirMode: 0o700 })
  return { volcConfig, sshConfig: targets.sshConfigPath, sshHosts: pkg.ssh.hosts.map(host => host.alias), sshKeys }
}
