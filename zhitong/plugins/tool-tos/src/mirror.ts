/**
 * Local mirror of the bucket under the cache root, with a tracking index.
 *
 * The index (`<cacheRoot>/.zhitong-cache/index.json`) records, per relative
 * path, the remote entity tag and the size, modification time, and SHA-256 of
 * the local copy. A local file whose size or modification time differs from
 * its entry, or that has no entry, may hold user edits: pulls never replace
 * or evict it unless the caller passes `overwrite`, except when its content
 * equals the remote object, in which case it is adopted. Index updates run
 * under a cross-process file lock; transfers run outside it.
 * @module @zhitong/tool-tos/mirror
 */

import { createHash, randomUUID } from 'node:crypto'
import { createReadStream } from 'node:fs'
import { copyFile, lstat, mkdir, readFile, rename, rm, stat } from 'node:fs/promises'
import path from 'node:path'
import type { PlatformPath } from 'node:path'
import { withFileLock, writeFileAtomic } from '@deepseek-ai/dsh-atomic-write'
import type { ToolTosSpec } from './config.ts'
import { CACHE_STATE_DIR, mirrorPath } from './paths.ts'
import type { ObjectInfo, ObjectStore } from './types.ts'

/** One tracked mirror file. */
export interface MirrorEntry {
  /** Remote entity tag the local copy was taken from. */
  etag: string
  /** Remote version id the local copy was taken from, when the bucket keeps versions. */
  versionId?: string
  size: number
  sha256: string
  /** Local modification time recorded right after the copy was written. */
  mtimeMs: number
  /** Last pull, push, or cache hit, in epoch milliseconds; drives LRU eviction. */
  lastAccess: number
}

interface MirrorIndex {
  version: 1
  entries: Record<string, MirrorEntry>
}

/** How a local mirror file relates to its index entry. */
export type LocalState = 'absent' | 'tracked' | 'modified' | 'untracked' | 'not-a-file'

/** Outcome of pulling one file. */
export interface PullOutcome {
  /** Relative path. */
  readonly path: string
  /** Absolute mirror path. */
  readonly local: string
  /**
   * `downloaded` fetched the object; `deduplicated` copied identical content
   * already in the mirror; `cached` kept an up-to-date local copy;
   * `conflict` left a locally modified file in place; `cache-full` skipped the
   * file because the cache bound could not be met.
   */
  readonly status: 'downloaded' | 'deduplicated' | 'cached' | 'conflict' | 'cache-full'
  readonly size: number
  /** Explanation for `conflict` and `cache-full`. */
  readonly message?: string
}

/** File digests computed in one pass. */
export interface Digests {
  readonly md5: string
  readonly sha256: string
  readonly size: number
}

/**
 * Hash a file with MD5 and SHA-256 in one streamed pass.
 * @param filePath - file to hash.
 * @returns both digests and the byte count.
 */
export async function hashFile(filePath: string): Promise<Digests> {
  const md5 = createHash('md5')
  const sha256 = createHash('sha256')
  let size = 0
  for await (const chunk of createReadStream(filePath)) {
    const buffer = chunk as Buffer
    md5.update(buffer)
    sha256.update(buffer)
    size += buffer.length
  }
  return { md5: md5.digest('hex'), sha256: sha256.digest('hex'), size }
}

/**
 * Whether local digests equal a remote object's content. A single-part
 * upload's entity tag is the MD5 of its content; multipart tags contain `-`
 * and are not comparable, so the SHA-256 metadata decides then.
 * @param remote - remote metadata.
 * @param local - local digests.
 * @returns true when the content is known to be identical.
 */
export function sameContent(remote: ObjectInfo, local: Digests): boolean {
  if (remote.size !== local.size) return false
  if (remote.sha256 !== undefined) return remote.sha256 === local.sha256
  return isContentMd5(remote.etag) && remote.etag === local.md5
}

/**
 * Whether an entity tag is a plain content MD5.
 * @param etag - unquoted entity tag.
 * @returns true for 32 hex digits.
 */
export function isContentMd5(etag: string): boolean {
  return /^[0-9a-f]{32}$/iu.test(etag)
}

/** The bucket mirror and its index. */
export class Mirror {
  private readonly stateDir: string
  private readonly indexPath: string

  /**
   * @param spec - resolved plugin settings (cache root, bound, eviction policy).
   * @param platform - path implementation used to map relative paths.
   * @param now - clock for access times.
   */
  constructor(
    private readonly spec: ToolTosSpec,
    private readonly platform: PlatformPath = path,
    private readonly now: () => number = Date.now,
  ) {
    this.stateDir = path.join(spec.cacheRoot, CACHE_STATE_DIR)
    this.indexPath = path.join(this.stateDir, 'index.json')
  }

  /**
   * Absolute mirror path of a relative path.
   * @param rel - normalized relative path.
   * @returns the absolute path.
   */
  pathOf(rel: string): string {
    return mirrorPath(this.spec.cacheRoot, rel, this.platform)
  }

  /**
   * Read the index entry and classify the local file.
   * @param rel - normalized relative path.
   * @returns the entry (if any) and the local state.
   */
  async inspect(rel: string): Promise<{ entry: MirrorEntry | undefined; state: LocalState }> {
    const entry = (await this.readIndex()).entries[rel]
    return { entry, state: await this.classify(this.pathOf(rel), entry) }
  }

  /**
   * Read every index entry.
   * @returns entries keyed by relative path.
   */
  async entries(): Promise<Readonly<Record<string, MirrorEntry>>> {
    return (await this.readIndex()).entries
  }

  /**
   * Bring one remote object into the mirror.
   * @param store - object store to download from.
   * @param rel - normalized relative path of the object.
   * @param remote - the object's current metadata.
   * @param options - pull options.
   * @param options.overwrite - replace a locally modified file.
   * @param options.protect - relative paths that eviction must keep (files pulled earlier in the same call).
   * @param signal - cancellation.
   * @returns what happened to the file.
   */
  async pull(
    store: ObjectStore,
    rel: string,
    remote: ObjectInfo,
    options: { overwrite: boolean; protect: ReadonlySet<string> },
    signal: AbortSignal,
  ): Promise<PullOutcome> {
    const local = this.pathOf(rel)
    const { entry, state } = await this.inspect(rel)
    const base = { path: rel, local, size: remote.size }
    if (state === 'not-a-file') {
      return { ...base, status: 'conflict', message: '本机同名路径是目录，未覆盖' }
    }
    if (state === 'tracked' && entry !== undefined && entry.etag === remote.etag) {
      await this.touch(rel)
      return { ...base, status: 'cached' }
    }
    if (state === 'modified' || state === 'untracked') {
      const digests = await hashFile(local)
      if (sameContent(remote, digests)) {
        await this.record(rel, remote, digests.sha256)
        return { ...base, status: 'cached' }
      }
      if (!options.overwrite) {
        return {
          ...base,
          status: 'conflict',
          message: state === 'modified'
            ? '本机文件在拉取后被修改过且未推送；未覆盖。要保留修改请先 tos_push，要放弃修改请带 overwrite 重新拉取'
            : '本机已有同名文件且内容与桶内不同；未覆盖。确认可以覆盖时带 overwrite 重新拉取',
        }
      }
    }
    const reclaimed = state === 'tracked' && entry !== undefined ? entry.size : 0
    if (!await this.makeRoom(remote.size - reclaimed, new Set([...options.protect, rel]))) {
      return {
        ...base,
        status: 'cache-full',
        message: `本机缓存上限 ${this.spec.cacheMaxBytes} 字节不足以放下此文件；可提高 cacheMaxBytes 或清理缓存`,
      }
    }
    await mkdir(path.join(this.stateDir, 'tmp'), { recursive: true })
    const tmp = path.join(this.stateDir, 'tmp', randomUUID())
    try {
      const donor = remote.sha256 === undefined ? undefined : await this.findIdentical(remote.sha256)
      if (donor !== undefined) await copyFile(donor, tmp)
      else await store.download(remote.key, tmp, signal)
      const digests = await hashFile(tmp)
      if (digests.size !== remote.size
        || (remote.sha256 !== undefined && remote.sha256 !== digests.sha256)
        || (remote.sha256 === undefined && isContentMd5(remote.etag) && remote.etag !== digests.md5)) {
        throw new Error(`下载校验失败：${rel} 的大小或摘要与桶内对象不一致`)
      }
      await mkdir(path.dirname(local), { recursive: true })
      await rename(tmp, local)
      await this.record(rel, remote, digests.sha256)
      return { ...base, status: donor !== undefined ? 'deduplicated' : 'downloaded' }
    } finally {
      await rm(tmp, { force: true })
    }
  }

  /**
   * Record that the local file at `rel` now equals the given remote version.
   * @param rel - normalized relative path.
   * @param remote - remote metadata the local copy matches.
   * @param sha256 - SHA-256 of the local copy.
   */
  async record(rel: string, remote: Pick<ObjectInfo, 'etag' | 'size' | 'versionId'>, sha256: string): Promise<void> {
    const info = await stat(this.pathOf(rel))
    await this.mutate((index) => {
      index.entries[rel] = {
        etag: remote.etag,
        ...remote.versionId !== undefined ? { versionId: remote.versionId } : {},
        size: remote.size,
        sha256,
        mtimeMs: info.mtimeMs,
        lastAccess: this.now(),
      }
    })
  }

  private async touch(rel: string): Promise<void> {
    await this.mutate((index) => {
      const entry = index.entries[rel]
      if (entry !== undefined) entry.lastAccess = this.now()
    })
  }

  /** Path of an unmodified tracked file whose content has this SHA-256. */
  private async findIdentical(sha256: string): Promise<string | undefined> {
    for (const [rel, entry] of Object.entries((await this.readIndex()).entries)) {
      if (entry.sha256 !== sha256) continue
      const local = this.pathOf(rel)
      if (await this.classify(local, entry) === 'tracked') return local
    }
    return undefined
  }

  /**
   * Ensure `bytes` more fit under the bound, evicting least-recently-used
   * unmodified tracked files when the policy allows.
   * @returns whether the bytes fit.
   */
  private async makeRoom(bytes: number, protect: ReadonlySet<string>): Promise<boolean> {
    return await this.mutate(async (index) => {
      let total = Object.values(index.entries).reduce((sum, entry) => sum + entry.size, 0)
      if (total + bytes <= this.spec.cacheMaxBytes) return true
      if (this.spec.eviction === 'none') return false
      const candidates = Object.entries(index.entries)
        .filter(([rel]) => !protect.has(rel))
        .sort(([, a], [, b]) => a.lastAccess - b.lastAccess)
      for (const [rel, entry] of candidates) {
        if (total + bytes <= this.spec.cacheMaxBytes) break
        const local = this.pathOf(rel)
        const state = await this.classify(local, entry)
        if (state === 'modified' || state === 'not-a-file') continue
        if (state === 'tracked') await rm(local, { force: true })
        Reflect.deleteProperty(index.entries, rel)
        total -= entry.size
      }
      return total + bytes <= this.spec.cacheMaxBytes
    })
  }

  private async classify(local: string, entry: MirrorEntry | undefined): Promise<LocalState> {
    let info
    try {
      info = await lstat(local)
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return 'absent'
      throw error
    }
    if (!info.isFile()) return 'not-a-file'
    if (entry === undefined) return 'untracked'
    return info.size === entry.size && info.mtimeMs === entry.mtimeMs ? 'tracked' : 'modified'
  }

  private async readIndex(): Promise<MirrorIndex> {
    let text: string
    try {
      text = await readFile(this.indexPath, 'utf8')
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return { version: 1, entries: {} }
      throw error
    }
    const parsed = JSON.parse(text) as Partial<MirrorIndex>
    if (parsed.version !== 1 || typeof parsed.entries !== 'object' || parsed.entries === null) {
      throw new Error(`缓存索引 ${this.indexPath} 格式不认识；删除该文件后重新拉取即可重建`)
    }
    return parsed as MirrorIndex
  }

  private async mutate<T>(change: (index: MirrorIndex) => T | Promise<T>): Promise<T> {
    await mkdir(this.stateDir, { recursive: true })
    return await withFileLock(this.indexPath, async () => {
      const index = await this.readIndex()
      const result = await change(index)
      await writeFileAtomic(this.indexPath, `${JSON.stringify(index, null, 2)}\n`, { mode: 0o600 })
      return result
    })
  }
}
