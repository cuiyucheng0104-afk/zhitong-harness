/**
 * `config_import`: validate a customer config package and apply it. Access
 * keys go to the credential store under the configured references; the TOS
 * connection fields and those references go to the `zhitong-tool-tos` entry
 * of the active profile patch through `ctx.configEditor`, which reloads the
 * TOS tools. The `volc` and `ssh` sections go to the zt-volc settings file and
 * the OpenSSH config (`remote.ts`). Results and errors never contain secret values.
 * @module @zhitong/config-import
 */

import { homedir } from 'node:os'
import { isAbsolute, join } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import z from '@deepseek-ai/schemastery'
import type {} from '@deepseek-ai/dsh-config-editor'
import { credentialRef } from '@deepseek-ai/dsh-credentials'
import type {} from '@deepseek-ai/dsh-credentials'
import { dshHomePath } from '@deepseek-ai/dsh-home-paths'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { PACKAGE_FILENAME, PackageError, parsePackage, readPackageText } from './package.ts'
import type { ConfigPackage } from './package.ts'
import { applyRemoteSections } from './remote.ts'
import type { RemoteResult, RemoteTargets } from './remote.ts'

export { PACKAGE_FILENAME, PACKAGE_FORMAT, PackageError, parsePackage, readPackageText } from './package.ts'
export type { ConfigPackage, SshHost, TosSection } from './package.ts'
export { SSH_BLOCK_BEGIN, SSH_BLOCK_END, mergeSshConfig, renderSshBlock, volcSettingsDocument } from './remote.ts'
export type { RemoteResult, RemoteTargets } from './remote.ts'

export const name = 'zhitong-config-import'
export const inject = ['tools']

/** Configuration for the import tool. */
export interface Config {
  /** Loader entry id of the TOS tools whose config receives the connection fields. */
  tosEntryId?: string
  /** Credential reference that stores the TOS access key id; written into the TOS entry too. */
  accessKeyIdRef?: string
  /** Credential reference that stores the TOS secret access key; written into the TOS entry too. */
  secretAccessKeyRef?: string
  /** Upper bound in bytes for the package file and the extracted document. */
  maxPackageBytes?: number
  /** zt-volc settings file (names only); empty uses `$DSH_HOME/zhitong/volc.config.json`, which zt-volc reads when `ZT_VOLC_CONFIG` is unset. */
  volcConfigPath?: string
  /** OpenSSH client configuration receiving the managed `Host` block; empty uses `~/.ssh/config`. */
  sshConfigPath?: string
  /** Directory for the hosts' private key files; empty uses `~/.ssh/zhitong`. */
  sshKeyDir?: string
}

/** Runtime configuration schema. */
export const Config: z<Config> = z.object({
  tosEntryId: z.string().default('zhitong-tool-tos'),
  accessKeyIdRef: z.string().default('ZT_TOS_ACCESS_KEY_ID'),
  secretAccessKeyRef: z.string().default('ZT_TOS_SECRET_ACCESS_KEY'),
  maxPackageBytes: z.natural().min(1).default(1024 * 1024),
  volcConfigPath: z.string().default(''),
  sshConfigPath: z.string().default(''),
  sshKeyDir: z.string().default(''),
})

/**
 * Resolve where the `volc` and `ssh` sections are written.
 * @param config - validated plugin config.
 * @param home - user home directory.
 * @returns absolute destinations.
 */
export function resolveRemoteTargets(config: Config, home: string = homedir()): RemoteTargets {
  return {
    volcConfigPath: config.volcConfigPath || dshHomePath('zhitong', 'volc.config.json'),
    sshConfigPath: config.sshConfigPath || join(home, '.ssh', 'config'),
    sshKeyDir: config.sshKeyDir || join(home, '.ssh', 'zhitong'),
  }
}

/**
 * Register `config_import`.
 * @param ctx - plugin context.
 * @param config - validated plugin config.
 */
export function apply(ctx: Context, config: Config): void {
  const tosEntryId = config.tosEntryId ?? 'zhitong-tool-tos'
  const accessKeyIdRef = credentialRef(config.accessKeyIdRef ?? 'ZT_TOS_ACCESS_KEY_ID')
  const secretAccessKeyRef = credentialRef(config.secretAccessKeyRef ?? 'ZT_TOS_SECRET_ACCESS_KEY')
  const maxPackageBytes = config.maxPackageBytes ?? 1024 * 1024
  const remoteTargets = resolveRemoteTargets(config)

  ctx.tools.register(defineTool({
    name: 'config_import',
    description: `导入公司配置包（${PACKAGE_FILENAME}，或含它的 .zip）：校验格式，把 TOS 访问密钥存进本机凭据存储，`
      + '把桶的 endpoint/region/bucket/公司前缀写进当前 profile，之后 tos_* 工具即可使用；'
      + '包里有 ssh、volc 段时，SSH 主机写进 ~/.ssh/config 的受管块，火山 profile 名与主机别名写进 zt-volc 读取的设置文件。'
      + '用户把配置包拖进对话或给出路径时调用；`dry_run` 只校验不写入。结果不含密钥，也不要向用户复述密钥。',
    parameters: {
      path: { type: 'string', required: true, description: '配置包的本机绝对路径（.json 或 .zip）' },
      dry_run: { type: 'boolean', description: '只校验，不写入' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          applied: { type: 'boolean', required: true },
          company: { type: 'string', required: true },
          tos: {
            type: 'object',
            required: true,
            additionalProperties: false,
            properties: {
              endpoint: { type: 'string', required: true },
              region: { type: 'string', required: true },
              bucket: { type: 'string', required: true },
              prefix: { type: 'string', required: true },
            },
          },
          storedCredentials: { type: 'array', required: true, items: { type: 'string' }, description: '写入的凭据引用名（不含值）' },
          volcProfile: { type: 'string', required: true, description: '配置包里的 ve profile 名；没有 volc 段时为空' },
          volcConfig: { type: 'string', required: true, description: '写入的 zt-volc 设置文件；未写入时为空' },
          sshConfig: { type: 'string', required: true, description: '写入受管块的 OpenSSH 配置文件；未写入时为空' },
          sshHosts: { type: 'array', required: true, items: { type: 'string' }, description: '配置包里的 SSH 主机别名' },
        },
      },
      render: (_args, value) => [{ type: 'text', text: renderImport(value) }],
    },
    async execute(args) {
      if (!isAbsolute(args.path)) throw new Error('path 必须是配置包的本机绝对路径')
      let pkg: ConfigPackage
      try {
        pkg = parsePackage(await readPackageText(args.path, maxPackageBytes))
      } catch (error) {
        if (error instanceof PackageError) throw new Error(error.message)
        throw error
      }
      const summary = {
        company: pkg.company.name,
        tos: { endpoint: pkg.tos.endpoint, region: pkg.tos.region, bucket: pkg.tos.bucket, prefix: pkg.tos.prefix },
        volcProfile: pkg.volc?.profile ?? '',
        sshHosts: pkg.ssh?.hosts.map(host => host.alias) ?? [],
      }
      if (args.dry_run === true) return { applied: false, ...summary, storedCredentials: [], volcConfig: '', sshConfig: '' }

      const credentials = ctx.get('credentials')
      if (credentials === undefined) throw new Error('当前 profile 没有凭据存储，无法保存密钥')
      const editor = ctx.get('configEditor')
      if (editor === undefined) throw new Error('当前 profile 不支持保存插件配置（缺少 config-editor），无法写入 TOS 设置')
      const entry = editor.entries().find(row => row.options.id === tosEntryId)
      if (entry === undefined) throw new Error(`当前 profile 里没有 id 为 ${tosEntryId} 的 TOS 插件条目；请确认已启用智通数工AI bundle`)

      await credentials.set(accessKeyIdRef, pkg.tos.accessKeyId)
      await credentials.set(secretAccessKeyRef, pkg.tos.secretAccessKey)
      try {
        await editor.edit(entry, current => ({
          ...current,
          backend: 'tos',
          endpoint: pkg.tos.endpoint,
          region: pkg.tos.region,
          bucket: pkg.tos.bucket,
          prefix: pkg.tos.prefix,
          accessKeyIdRef,
          secretAccessKeyRef,
        }))
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error)
        throw new Error(`TOS 访问密钥已存入凭据存储，但 TOS 设置未能写入 profile：${reason}`)
      }
      let remote: RemoteResult
      try {
        remote = await applyRemoteSections(pkg, remoteTargets)
      } catch (error) {
        const reason = error instanceof Error ? error.message : String(error)
        throw new Error(`TOS 设置已导入，但 ssh / volc 段未能写入：${reason}`)
      }
      return {
        applied: true, ...summary, storedCredentials: [accessKeyIdRef, secretAccessKeyRef],
        volcConfig: remote.volcConfig, sshConfig: remote.sshConfig,
      }
    },
  }))
}

interface ImportValue {
  applied: boolean
  company: string
  tos: { endpoint: string; region: string; bucket: string; prefix: string }
  storedCredentials: readonly string[]
  volcProfile: string
  volcConfig: string
  sshConfig: string
  sshHosts: readonly string[]
}

function renderImport(value: ImportValue): string {
  const target = `tos://${value.tos.bucket}/${value.tos.prefix === '' ? '' : `${value.tos.prefix}/`}（${value.tos.endpoint}，${value.tos.region}）`
  const lines = [value.applied
    ? `已导入「${value.company}」的配置包：${target}。密钥已存入本机凭据存储（${value.storedCredentials.join('、')}），TOS 工具已按新设置重新加载。`
    : `配置包校验通过（未写入）：「${value.company}」，${target}。`]
  if (value.sshHosts.length > 0) {
    lines.push(value.applied
      ? `SSH 主机 ${value.sshHosts.join('、')} 已写入 ${value.sshConfig} 的受管块（私钥文件仅本人可读）。`
      : `SSH 主机 ${value.sshHosts.join('、')} 校验通过。`)
  }
  if (value.volcProfile !== '') {
    lines.push(`火山引擎 ve profile 名「${value.volcProfile}」${value.applied ? `已写入 zt-volc 设置 ${value.volcConfig}` : '校验通过'}；`
      + `配置包不含 ve 的密钥，请用户在自己的终端运行 ve configure set --profile ${value.volcProfile} 建立该 profile。`)
  } else if (value.applied && value.volcConfig !== '') {
    lines.push(`主机别名已写入 zt-volc 设置 ${value.volcConfig}。`)
  }
  return lines.join('\n')
}
