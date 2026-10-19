/** Plugin configuration and its resolution into a runtime spec. @module @zhitong/tool-tos/config */

import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import z from '@deepseek-ai/schemastery'

/** Which object store the tools talk to. */
export type BackendKind = 'tos' | 'local'

/** Cache eviction policy once `cacheMaxBytes` would be exceeded. */
export type EvictionPolicy = 'lru' | 'none'

/** Configuration for the TOS tools. `config_import` writes the connection fields from a customer config package. */
export interface Config {
  /** `tos` talks to Volcengine TOS; `local` serves a local directory laid out like the bucket (offline development and tests). */
  backend?: BackendKind
  /** TOS endpoint host, such as `tos-cn-beijing.volces.com`. Required for `tos`. */
  endpoint?: string
  /** TOS region, such as `cn-beijing`. Required for `tos`. */
  region?: string
  /** Bucket name. Required for `tos`. */
  bucket?: string
  /** Company prefix inside the bucket, without leading or trailing `/`; every tool path is relative to it. */
  prefix?: string
  /** Root directory served by the `local` backend. Required for `local`. */
  localRoot?: string
  /** Credential reference holding the access key id. */
  accessKeyIdRef?: string
  /** Credential reference holding the secret access key. */
  secretAccessKeyRef?: string
  /** Local mirror root; defaults to `~/zhitong` (Windows `%USERPROFILE%\zhitong`). */
  cacheRoot?: string
  /** Upper bound in bytes for files the mirror tracks. */
  cacheMaxBytes?: number
  /** What a pull does when the bound would be exceeded: evict least-recently-used tracked files, or skip the file. */
  eviction?: EvictionPolicy
  /** Lower-case extensions that directory pulls skip unless the call opts in; explicitly named files are always pulled. */
  noAutoPullExtensions?: string[]
  /** Maximum entries one `tos_ls` page returns. */
  maxListEntries?: number
  /** Maximum files one `tos_pull` call transfers. */
  maxPullFiles?: number
  /** Maximum bytes of one file `tos_push` uploads in a single request (TOS single-PUT limit is 5 GiB). */
  maxPushBytes?: number
}

/** Runtime configuration schema. */
export const Config: z<Config> = z.object({
  backend: z.union([z.const('tos'), z.const('local')]).default('tos'),
  endpoint: z.string(),
  region: z.string(),
  bucket: z.string(),
  prefix: z.string().default(''),
  localRoot: z.string(),
  accessKeyIdRef: z.string().default('ZT_TOS_ACCESS_KEY_ID'),
  secretAccessKeyRef: z.string().default('ZT_TOS_SECRET_ACCESS_KEY'),
  cacheRoot: z.string(),
  cacheMaxBytes: z.natural().min(1).default(20 * 1024 ** 3),
  eviction: z.union([z.const('lru'), z.const('none')]).default('lru'),
  noAutoPullExtensions: z.array(z.string()).default(['.dwg', '.dxf', '.rvt', '.skp', '.3dm', '.ifc', '.nwd', '.zip', '.rar', '.7z']),
  maxListEntries: z.natural().min(1).default(200),
  maxPullFiles: z.natural().min(1).default(200),
  maxPushBytes: z.natural().min(1).default(5 * 1024 ** 3),
})

/** Connection settings for the TOS backend. */
export interface TosConnection {
  readonly kind: 'tos'
  readonly endpoint: string
  readonly region: string
  readonly bucket: string
  readonly accessKeyIdRef: string
  readonly secretAccessKeyRef: string
}

/** Settings for the local-directory backend. */
export interface LocalConnection {
  readonly kind: 'local'
  readonly root: string
}

/** Fully resolved runtime settings. */
export interface ToolTosSpec {
  /** Backend settings, or the reason the backend is not usable yet. */
  readonly connection: TosConnection | LocalConnection | { readonly kind: 'unconfigured'; readonly missing: readonly string[] }
  /** Company prefix without leading or trailing `/`; empty for the bucket root. */
  readonly prefix: string
  readonly cacheRoot: string
  readonly cacheMaxBytes: number
  readonly eviction: EvictionPolicy
  /** Lower-case extensions including the dot. */
  readonly noAutoPullExtensions: ReadonlySet<string>
  readonly maxListEntries: number
  readonly maxPullFiles: number
  readonly maxPushBytes: number
}

/**
 * Resolve plugin config into runtime settings. A `tos` backend with missing
 * connection fields resolves to `unconfigured` instead of failing load, so the
 * profile starts before a config package is imported; every tool then fails
 * with an instruction to run `config_import`.
 * @param config - validated plugin config.
 * @returns the runtime spec.
 */
export function resolveSpec(config: Config): ToolTosSpec {
  const backend = config.backend ?? 'tos'
  let connection: ToolTosSpec['connection']
  if (backend === 'local') {
    if (config.localRoot === undefined || config.localRoot === '') {
      throw new Error('tool-tos: backend "local" requires localRoot')
    }
    connection = { kind: 'local', root: resolve(config.localRoot) }
  } else {
    const missing = (['endpoint', 'region', 'bucket'] as const).filter(field => (config[field] ?? '') === '')
    connection = missing.length > 0
      ? { kind: 'unconfigured', missing }
      : {
          kind: 'tos',
          endpoint: config.endpoint!,
          region: config.region!,
          bucket: config.bucket!,
          accessKeyIdRef: config.accessKeyIdRef ?? 'ZT_TOS_ACCESS_KEY_ID',
          secretAccessKeyRef: config.secretAccessKeyRef ?? 'ZT_TOS_SECRET_ACCESS_KEY',
        }
  }
  return {
    connection,
    prefix: (config.prefix ?? '').split('/').filter(part => part !== '').join('/'),
    cacheRoot: resolve(config.cacheRoot ?? join(homedir(), 'zhitong')),
    cacheMaxBytes: config.cacheMaxBytes ?? 20 * 1024 ** 3,
    eviction: config.eviction ?? 'lru',
    noAutoPullExtensions: new Set((config.noAutoPullExtensions ?? []).map(ext => normalizeExtension(ext))),
    maxListEntries: config.maxListEntries ?? 200,
    maxPullFiles: config.maxPullFiles ?? 200,
    maxPushBytes: config.maxPushBytes ?? 5 * 1024 ** 3,
  }
}

function normalizeExtension(ext: string): string {
  const lower = ext.trim().toLowerCase()
  return lower.startsWith('.') ? lower : `.${lower}`
}
