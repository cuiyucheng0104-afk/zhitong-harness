/**
 * TOS file channel for 智通数工AI: `tos_ls`, `tos_stat`, `tos_pull`, and
 * `tos_push` over the company prefix of one Volcengine TOS bucket, with a
 * local mirror under the cache root (default `~/zhitong`). Paths the model
 * passes are relative to the company prefix. Credentials are resolved from
 * `ctx.credentials` on every call through the configured references, so a key
 * imported or rotated by `config_import` applies to the next call.
 * @module @zhitong/tool-tos
 */

import { lstat } from 'node:fs/promises'
import { basename, isAbsolute } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import { credentialRef } from '@deepseek-ai/dsh-credentials'
import type {} from '@deepseek-ai/dsh-credentials'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { Config, resolveSpec } from './config.ts'
import type { ToolTosSpec } from './config.ts'
import { Mirror, hashFile, isContentMd5, sameContent } from './mirror.ts'
import type { PullOutcome } from './mirror.ts'
import { PathError, extensionOf, fromKey, parseRemotePath, relFromMirror, toKey } from './paths.ts'
import type { RemotePath } from './paths.ts'
import { LocalDirectoryStore } from './store-local.ts'
import { TosObjectStore } from './store-tos.ts'
import type { ObjectInfo, ObjectStore } from './types.ts'

export { Config, resolveSpec } from './config.ts'
export type { BackendKind, EvictionPolicy, ToolTosSpec } from './config.ts'
export type { ObjectInfo, ObjectStore } from './types.ts'

export const name = 'zhitong-tool-tos'
export const inject = ['tools']

const FILE_INFO = {
  type: 'object',
  additionalProperties: false,
  properties: {
    path: { type: 'string', required: true, description: '相对公司前缀的路径' },
    size: { type: 'integer', required: true },
    modified: { type: 'string', required: true },
    cached: { type: 'boolean', required: true, description: '本机镜像里有与桶内一致的副本' },
  },
} as const

const PULL_ITEM = {
  type: 'object',
  additionalProperties: false,
  properties: {
    path: { type: 'string', required: true },
    local: { type: 'string', required: true },
    status: { type: 'string', required: true, enum: ['downloaded', 'deduplicated', 'cached', 'conflict', 'cache-full'] },
    size: { type: 'integer', required: true },
    message: { type: 'string' },
  },
} as const

/**
 * Register the four TOS tools.
 * @param ctx - plugin context.
 * @param config - validated plugin config.
 */
export function apply(ctx: Context, config: Config): void {
  const spec = resolveSpec(config)
  const mirror = new Mirror(spec)
  const bucket = spec.connection.kind === 'tos' ? spec.connection.bucket : undefined
  const location = { ...bucket !== undefined ? { bucket } : {}, prefix: spec.prefix }

  const openStore = async (): Promise<ObjectStore> => {
    const connection = spec.connection
    switch (connection.kind) {
      case 'local':
        return new LocalDirectoryStore(connection.root)
      case 'unconfigured':
        throw new Error(`TOS 尚未配置（缺少 ${connection.missing.join('、')}）。请让用户提供公司配置包并调用 config_import 导入`)
      case 'tos': {
        const credentials = ctx.get('credentials')
        if (credentials === undefined) throw new Error('当前 profile 没有凭据存储，无法读取 TOS 密钥')
        const [accessKeyId, secretAccessKey] = await Promise.all([
          credentials.resolve(credentialRef(connection.accessKeyIdRef)),
          credentials.resolve(credentialRef(connection.secretAccessKeyRef)),
        ])
        if (accessKeyId === undefined || secretAccessKey === undefined) {
          throw new Error('凭据存储里没有 TOS 访问密钥。请让用户提供公司配置包并调用 config_import 导入')
        }
        return new TosObjectStore(connection, { accessKeyId: accessKeyId.value, secretAccessKey: secretAccessKey.value })
      }
    }
  }

  const parse = (input: string): RemotePath => {
    try {
      return parseRemotePath(input, location)
    } catch (error) {
      if (error instanceof PathError) throw new Error(error.message)
      throw error
    }
  }

  ctx.tools.register(defineTool({
    name: 'tos_ls',
    description: '列出公司 TOS 桶里的目录与文件。路径相对公司前缀，例如 `项目/` 或 `项目/2026-007-某工程/资料/`；空字符串是前缀根。'
      + '默认只列一层；`recursive` 列出其下全部文件。结果分页，`next` 非空时把它作为 `continuation` 再调一次。'
      + '`cached` 表示本机镜像已有一致副本，可以直接读本机路径。',
    parameters: {
      path: { type: 'string', required: true, description: '目录路径，相对公司前缀' },
      recursive: { type: 'boolean', description: '列出其下全部文件（不分目录）' },
      limit: { type: 'integer', description: `本页最多条目数，上限 ${spec.maxListEntries}` },
      continuation: { type: 'string', description: '上一页返回的 next' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string', required: true },
          location: { type: 'string', required: true },
          dirs: { type: 'array', required: true, items: { type: 'string' } },
          files: { type: 'array', required: true, items: FILE_INFO },
          next: { type: 'string' },
        },
      },
      render: (_args, value) => [{ type: 'text', text: renderListing(value) }],
    },
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const target = parse(args.path)
      const limit = Math.min(Math.max(1, args.limit ?? spec.maxListEntries), spec.maxListEntries)
      const store = await openStore()
      const page = await store.list({
        prefix: toKey(spec.prefix, target.rel, true),
        delimited: args.recursive !== true,
        limit,
        ...args.continuation !== undefined ? { continuation: args.continuation } : {},
      }, exec.signal)
      const entries = await mirror.entries()
      const files = page.files.map((file) => {
        const rel = fromKey(spec.prefix, file.key)
        return { path: rel, size: file.size, modified: file.modified, cached: entries[rel]?.etag === file.etag }
      })
      const dirPath = target.rel === '' ? '' : `${target.rel}/`
      if (page.dirs.length === 0 && files.length === 0 && !target.directory && target.rel !== '') {
        const single = await store.stat(toKey(spec.prefix, target.rel, false), exec.signal)
        if (single !== undefined) {
          return {
            path: target.rel,
            location: describeLocation(store, spec),
            dirs: [],
            files: [{ path: target.rel, size: single.size, modified: single.modified, cached: entries[target.rel]?.etag === single.etag }],
          }
        }
      }
      return {
        path: dirPath,
        location: describeLocation(store, spec),
        dirs: page.dirs.map(dir => fromKey(spec.prefix, dir)),
        files,
        ...page.next !== undefined ? { next: page.next } : {},
      }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'tos_stat',
    description: '查看桶内一个文件的元数据（大小、修改时间、版本）以及本机镜像副本的状态：'
      + '`current` 与桶内一致，`stale` 桶内已更新，`modified` 本机改过未推送，`untracked` 本机有同名文件但不是拉取来的，`absent` 本机没有。',
    parameters: {
      path: { type: 'string', required: true, description: '文件路径，相对公司前缀' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string', required: true },
          exists: { type: 'boolean', required: true },
          size: { type: 'integer' },
          modified: { type: 'string' },
          etag: { type: 'string' },
          versionId: { type: 'string' },
          sha256: { type: 'string' },
          local: { type: 'string', required: true, description: '本机镜像路径' },
          localState: { type: 'string', required: true, enum: ['current', 'stale', 'modified', 'untracked', 'absent', 'not-a-file'] },
        },
      },
      render: (_args, value) => [{ type: 'text', text: renderStat(value) }],
    },
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      const target = parse(args.path)
      if (target.directory) throw new Error('tos_stat 需要文件路径；列目录请用 tos_ls')
      const store = await openStore()
      const remote = await store.stat(toKey(spec.prefix, target.rel, false), exec.signal)
      const { entry, state } = await mirror.inspect(target.rel)
      const localState: 'current' | 'stale' | Exclude<typeof state, 'tracked'> = state === 'tracked'
        ? (remote !== undefined && entry?.etag === remote.etag ? 'current' : 'stale')
        : state
      return {
        path: target.rel,
        exists: remote !== undefined,
        ...remote !== undefined ? {
          size: remote.size,
          modified: remote.modified,
          etag: remote.etag,
          ...remote.versionId !== undefined ? { versionId: remote.versionId } : {},
          ...remote.sha256 !== undefined ? { sha256: remote.sha256 } : {},
        } : {},
        local: mirror.pathOf(target.rel),
        localState,
      }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'tos_pull',
    description: '把桶内文件拉到本机镜像（与桶同构），返回本机路径，之后用本机路径读取。'
      + '路径以 `/` 结尾时拉取整个目录（含子目录），此时默认跳过图纸与压缩包等大文件'
      + `（${[...spec.noAutoPullExtensions].join(' ')}），需要时带 \`include_drawings\` 或直接点名文件。`
      + '本机副本已与桶内一致时不重复下载；本机改过未推送的文件不会被覆盖（状态 conflict），确认放弃修改时带 `overwrite`。',
    parameters: {
      path: { type: 'string', required: true, description: '文件或目录路径，相对公司前缀；目录以 / 结尾' },
      include_drawings: { type: 'boolean', description: '目录拉取时也拉图纸与压缩包' },
      overwrite: { type: 'boolean', description: '覆盖本机改过的同名文件' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string', required: true },
          items: { type: 'array', required: true, items: PULL_ITEM },
          skipped: { type: 'array', required: true, items: { type: 'string' }, description: '目录拉取时按扩展名跳过的文件' },
          truncated: { type: 'boolean', required: true, description: '文件数超过单次上限，只拉了前一部分' },
        },
      },
      render: (_args, value) => [{ type: 'text', text: renderPull(value) }],
    },
    async execute(args, exec) {
      const target = parse(args.path)
      const store = await openStore()
      const overwrite = args.overwrite === true
      if (!target.directory) {
        const remote = await store.stat(toKey(spec.prefix, target.rel, false), exec.signal)
        if (remote === undefined) throw new Error(`桶内没有文件 ${target.rel}；目录请以 / 结尾`)
        const outcome = await mirror.pull(store, target.rel, remote, { overwrite, protect: new Set() }, exec.signal)
        return { path: target.rel, items: [pullItem(outcome)], skipped: [], truncated: false }
      }
      const wanted: ObjectInfo[] = []
      const skipped: string[] = []
      let continuation: string | undefined
      let truncated = false
      do {
        const page = await store.list({
          prefix: toKey(spec.prefix, target.rel, true),
          delimited: false,
          limit: 1000,
          ...continuation !== undefined ? { continuation } : {},
        }, exec.signal)
        for (const file of page.files) {
          const rel = fromKey(spec.prefix, file.key)
          if (args.include_drawings !== true && spec.noAutoPullExtensions.has(extensionOf(rel))) skipped.push(rel)
          else if (wanted.length < spec.maxPullFiles) wanted.push(file)
          else truncated = true
        }
        continuation = page.next
      } while (continuation !== undefined && !truncated)
      const items: PullOutcome[] = []
      const protect = new Set<string>()
      for (const file of wanted) {
        exec.signal.throwIfAborted()
        const rel = fromKey(spec.prefix, file.key)
        const outcome = await mirror.pull(store, rel, file, { overwrite, protect }, exec.signal)
        protect.add(rel)
        items.push(outcome)
      }
      return { path: target.rel === '' ? '' : `${target.rel}/`, items: items.map(pullItem), skipped, truncated }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'tos_push',
    description: '把本机文件上传到桶内并回读校验。`local_path` 是本机绝对路径；'
      + '文件在本机镜像里时可省略 `path`（上传回同一位置），否则 `path` 给出桶内目标（以 / 结尾表示放进该目录，文件名不变）。'
      + '桶开了版本控制：覆盖不会丢旧版本，结果里的 `replaced` 是被覆盖的版本；`remoteChangedSincePull` 为 true 说明别人在你拉取后改过，需要告诉用户。',
    parameters: {
      local_path: { type: 'string', required: true, description: '本机文件绝对路径' },
      path: { type: 'string', description: '桶内目标路径，相对公司前缀' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          path: { type: 'string', required: true },
          size: { type: 'integer', required: true },
          sha256: { type: 'string', required: true },
          status: { type: 'string', required: true, enum: ['uploaded', 'unchanged'] },
          etag: { type: 'string', required: true },
          versionId: { type: 'string' },
          verified: { type: 'boolean', required: true },
          replaced: {
            required: true,
            oneOf: [
              { type: 'null' },
              {
                type: 'object',
                additionalProperties: false,
                properties: {
                  etag: { type: 'string', required: true },
                  modified: { type: 'string', required: true },
                  versionId: { type: 'string' },
                },
              },
            ],
          },
          remoteChangedSincePull: { type: 'boolean', required: true },
        },
      },
      render: (_args, value) => [{ type: 'text', text: renderPush(value) }],
    },
    async execute(args, exec) {
      if (!isAbsolute(args.local_path)) throw new Error('local_path 必须是本机绝对路径')
      const info = await lstat(args.local_path).catch((error: NodeJS.ErrnoException) => {
        if (error.code === 'ENOENT') throw new Error(`本机没有文件 ${args.local_path}`)
        throw error
      })
      if (!info.isFile()) throw new Error(`${args.local_path} 不是普通文件`)
      if (info.size > spec.maxPushBytes) {
        throw new Error(`文件 ${info.size} 字节，超过单次上传上限 ${spec.maxPushBytes} 字节`)
      }
      const mirrored = relFromMirror(spec.cacheRoot, args.local_path)
      let rel: string
      if (args.path === undefined) {
        if (mirrored === undefined) throw new Error('文件不在本机镜像里，需要用 path 指定桶内目标')
        rel = parse(mirrored).rel
      } else {
        const target = parse(args.path)
        rel = target.directory ? [target.rel, basename(args.local_path)].filter(part => part !== '').join('/') : target.rel
      }
      if (rel === '') throw new Error('桶内目标路径为空')
      const key = toKey(spec.prefix, rel, false)
      const store = await openStore()
      const digests = await hashFile(args.local_path)
      const before = await store.stat(key, exec.signal)
      const { entry } = await mirror.inspect(rel)
      const remoteChangedSincePull = before !== undefined && entry !== undefined && entry.etag !== before.etag
      const trackLocal = mirrored === rel
      const replaced = before === undefined
        ? null
        : { etag: before.etag, modified: before.modified, ...before.versionId !== undefined ? { versionId: before.versionId } : {} }
      if (before !== undefined && sameContent(before, digests)) {
        if (trackLocal) await mirror.record(rel, before, digests.sha256)
        return {
          path: rel,
          size: digests.size,
          sha256: digests.sha256,
          status: 'unchanged' as const,
          etag: before.etag,
          ...before.versionId !== undefined ? { versionId: before.versionId } : {},
          verified: true,
          replaced: null,
          remoteChangedSincePull: false,
        }
      }
      const put = await store.upload(key, args.local_path, digests.sha256, exec.signal)
      const after = await store.stat(key, exec.signal)
      if (after === undefined || after.size !== digests.size
        || (after.sha256 !== undefined && after.sha256 !== digests.sha256)
        || (isContentMd5(after.etag) && after.etag !== digests.md5)
        || (after.sha256 === undefined && !isContentMd5(after.etag))) {
        throw new Error(`上传后回读校验失败：${rel}（桶内大小或摘要与本机不一致）。旧版本仍在版本历史里，请重试上传`)
      }
      if (trackLocal) await mirror.record(rel, after, digests.sha256)
      return {
        path: rel,
        size: digests.size,
        sha256: digests.sha256,
        status: 'uploaded' as const,
        etag: after.etag !== '' ? after.etag : put.etag,
        ...(after.versionId ?? put.versionId) !== undefined ? { versionId: (after.versionId ?? put.versionId)! } : {},
        verified: true,
        replaced,
        remoteChangedSincePull,
      }
    },
  }))
}

function describeLocation(store: ObjectStore, spec: ToolTosSpec): string {
  return spec.prefix === '' ? `${store.label}/` : `${store.label}/${spec.prefix}/`
}

function pullItem(outcome: PullOutcome) {
  return {
    path: outcome.path,
    local: outcome.local,
    status: outcome.status,
    size: outcome.size,
    ...outcome.message !== undefined ? { message: outcome.message } : {},
  }
}

interface ListingValue {
  path: string
  location: string
  dirs: readonly string[]
  files: ReadonlyArray<{ path: string; size: number; modified: string; cached: boolean }>
  next?: string
}

function renderListing(value: ListingValue): string {
  const lines = [`${value.location}${value.path}：${value.dirs.length} 个目录，${value.files.length} 个文件`]
  for (const dir of value.dirs) lines.push(`[目录] ${dir}`)
  for (const file of value.files) {
    lines.push(`${file.path}  ${formatBytes(file.size)}  ${file.modified}${file.cached ? '  [本机已有]' : ''}`)
  }
  if (value.dirs.length === 0 && value.files.length === 0) lines.push('（空）')
  if (value.next !== undefined) lines.push(`还有更多，下一页 continuation=${value.next}`)
  return lines.join('\n')
}

interface StatValue {
  path: string
  exists: boolean
  size?: number
  modified?: string
  versionId?: string
  local: string
  localState: string
}

function renderStat(value: StatValue): string {
  const remote = value.exists
    ? `桶内：${formatBytes(value.size ?? 0)}，修改于 ${value.modified ?? ''}${value.versionId !== undefined ? `，版本 ${value.versionId}` : ''}`
    : '桶内：不存在'
  return `${value.path}\n${remote}\n本机：${value.local}（${value.localState}）`
}

interface PullValue {
  path: string
  items: ReadonlyArray<{ path: string; local: string; status: string; size: number; message?: string }>
  skipped: readonly string[]
  truncated: boolean
}

function renderPull(value: PullValue): string {
  const counts = new Map<string, number>()
  for (const item of value.items) counts.set(item.status, (counts.get(item.status) ?? 0) + 1)
  const summary = [...counts].map(([status, count]) => `${status} ${count}`).join('，')
  const lines = [`拉取 ${value.path || '（前缀根）'}：${summary || '没有文件'}`]
  for (const item of value.items) {
    lines.push(`${item.status}  ${item.local}${item.message !== undefined ? `  —— ${item.message}` : ''}`)
  }
  if (value.skipped.length > 0) lines.push(`按扩展名跳过 ${value.skipped.length} 个文件（需要时点名拉取或带 include_drawings）：${value.skipped.join('，')}`)
  if (value.truncated) lines.push('文件数超过单次上限，只拉了前一部分；请缩小目录范围后继续')
  return lines.join('\n')
}

interface PushValue {
  path: string
  size: number
  status: string
  versionId?: string
  replaced: { versionId?: string; modified: string } | null
  remoteChangedSincePull: boolean
}

function renderPush(value: PushValue): string {
  const lines = [value.status === 'unchanged'
    ? `${value.path} 与桶内内容相同，未重复上传`
    : `已上传 ${value.path}（${formatBytes(value.size)}），回读校验通过${value.versionId !== undefined ? `，新版本 ${value.versionId}` : ''}`]
  if (value.replaced !== null) {
    lines.push(`覆盖了 ${value.replaced.modified} 的旧版本${value.replaced.versionId !== undefined ? ` ${value.replaced.versionId}` : ''}，可从版本历史恢复`)
  }
  if (value.remoteChangedSincePull) lines.push('注意：你拉取之后桶内这个文件被别人改过，本次上传覆盖了那次修改；请告诉用户')
  return lines.join('\n')
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GiB`
}
