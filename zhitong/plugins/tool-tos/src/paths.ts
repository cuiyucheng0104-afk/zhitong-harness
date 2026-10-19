/**
 * Mapping between model-facing paths, bucket keys, and mirror files.
 *
 * A model-facing path is relative to the company prefix, `/`-separated, such
 * as `项目/2026-007-某工程/资料/合同.pdf`; a trailing `/` names a directory.
 * The mirror keeps the same tree under the cache root.
 * @module @zhitong/tool-tos/paths
 */

import path from 'node:path'
import type { PlatformPath } from 'node:path'

/** A parsed model-facing path. */
export interface RemotePath {
  /** Normalized relative path without leading or trailing `/`; empty for the prefix root. */
  readonly rel: string
  /** Whether the caller named a directory (trailing `/` or the root). */
  readonly directory: boolean
}

/** A path the tools refuse, with the reason shown to the model. */
export class PathError extends Error {
  override readonly name = 'PathError'
}

const WINDOWS_FORBIDDEN = /[<>:"|?*\u0000-\u001f]/u
const WINDOWS_RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$/iu

/**
 * Parse a model-facing path. Backslashes are accepted as separators; `.`
 * segments are dropped; `..` segments and absolute paths are refused. A
 * `tos://<bucket>/<prefix>/...` URI is accepted when it names the configured
 * bucket and prefix.
 * @param input - the path the model passed.
 * @param location - configured bucket and prefix for URI stripping.
 * @param location.bucket - configured bucket, when the backend has one.
 * @param location.prefix - configured company prefix.
 * @returns the normalized path.
 * @throws PathError when the path escapes the prefix or names another bucket.
 */
export function parseRemotePath(input: string, location: { bucket?: string; prefix: string }): RemotePath {
  let raw = input.trim()
  if (raw.startsWith('tos://')) {
    const withoutScheme = raw.slice('tos://'.length)
    const [bucket = '', ...rest] = withoutScheme.split('/')
    if (location.bucket === undefined || bucket !== location.bucket) {
      throw new PathError(`路径指向的桶 ${JSON.stringify(bucket)} 不是当前配置的桶`)
    }
    const after = rest.join('/')
    const prefix = location.prefix === '' ? '' : `${location.prefix}/`
    if (prefix !== '' && !(after === location.prefix || after.startsWith(prefix))) {
      throw new PathError(`路径不在公司前缀 ${location.prefix}/ 之下`)
    }
    raw = after === location.prefix ? '' : after.slice(prefix.length)
    if (raw === '') return { rel: '', directory: true }
  }
  if (raw.startsWith('/') || raw.startsWith('\\') || /^[a-zA-Z]:/u.test(raw)) {
    throw new PathError(`需要相对公司前缀的路径，不要用绝对路径：${input}`)
  }
  const directory = raw === '' || raw === '.' || /[\\/]$/u.test(raw)
  const segments = raw.split(/[\\/]+/u).filter(segment => segment !== '' && segment !== '.')
  if (segments.includes('..')) throw new PathError(`路径不能包含 ..：${input}`)
  return { rel: segments.join('/'), directory: directory || segments.length === 0 }
}

/**
 * Join the company prefix and a relative path into a bucket key.
 * @param prefix - company prefix without slashes at either end.
 * @param rel - normalized relative path.
 * @param directory - append `/` for a directory prefix.
 * @returns the full key.
 */
export function toKey(prefix: string, rel: string, directory: boolean): string {
  const joined = [prefix, rel].filter(part => part !== '').join('/')
  return directory && joined !== '' ? `${joined}/` : joined
}

/**
 * Strip the company prefix from a bucket key.
 * @param prefix - company prefix without slashes at either end.
 * @param key - full key below the prefix.
 * @returns the relative path, keeping a trailing `/` for directories.
 */
export function fromKey(prefix: string, key: string): string {
  if (prefix === '') return key
  return key.startsWith(`${prefix}/`) ? key.slice(prefix.length + 1) : key
}

/**
 * Map a relative path to its mirror file. Segments that the target platform
 * cannot store are refused instead of being renamed, so a mirror path always
 * maps back to exactly one key.
 * @param cacheRoot - absolute mirror root.
 * @param rel - normalized relative path of a file.
 * @param platform - path implementation of the host (`path.win32` on Windows).
 * @returns the absolute mirror path.
 * @throws PathError when a segment is not storable on the platform.
 */
export function mirrorPath(cacheRoot: string, rel: string, platform: PlatformPath = path): string {
  const segments = rel.split('/')
  if (segments[0] === CACHE_STATE_DIR) {
    throw new PathError(`${CACHE_STATE_DIR}/ 是本机缓存的保留目录，不能作为桶内路径`)
  }
  if (platform.sep === '\\') {
    for (const segment of segments) {
      if (WINDOWS_FORBIDDEN.test(segment) || WINDOWS_RESERVED.test(segment) || /[. ]$/u.test(segment)) {
        throw new PathError(`文件名 ${JSON.stringify(segment)} 在 Windows 上无法保存；请先在桶里改名`)
      }
    }
  }
  return platform.join(cacheRoot, ...segments)
}

/**
 * Map a local file inside the mirror back to its relative path.
 * @param cacheRoot - absolute mirror root.
 * @param filePath - absolute local path.
 * @param platform - path implementation of the host.
 * @returns the relative path, or `undefined` when the file is outside the mirror.
 */
export function relFromMirror(cacheRoot: string, filePath: string, platform: PlatformPath = path): string | undefined {
  const relative = platform.relative(cacheRoot, filePath)
  if (relative === '' || relative.startsWith('..') || platform.isAbsolute(relative)) return undefined
  const rel = relative.split(platform.sep).join('/')
  return rel.startsWith(`${CACHE_STATE_DIR}/`) ? undefined : rel
}

/** Directory under the cache root that holds the index and temporary downloads. */
export const CACHE_STATE_DIR = '.zhitong-cache'

/**
 * Lower-case extension of a path, including the dot.
 * @param rel - relative path.
 * @returns the extension, or an empty string.
 */
export function extensionOf(rel: string): string {
  return path.posix.extname(rel).toLowerCase()
}
