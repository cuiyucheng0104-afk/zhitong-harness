/**
 * Local-directory object store: a directory laid out like the bucket, where
 * the key `a/b/c.pdf` is the file `<root>/a/b/c.pdf`. It serves offline
 * development and the plugin tests. Entity tags are content MD5 (matching a
 * single-part TOS upload) and SHA-256 metadata lives in a sidecar map under
 * `<root>/.zhitong-store/`.
 * @module @zhitong/tool-tos/store-local
 */

import { createHash } from 'node:crypto'
import { createReadStream } from 'node:fs'
import { copyFile, mkdir, readdir, readFile, stat } from 'node:fs/promises'
import { dirname, join, sep } from 'node:path'
import { writeFileAtomic } from '@deepseek-ai/dsh-atomic-write'
import type { ListPage, ListRequest, ObjectInfo, ObjectStore, PutResult } from './types.ts'

const STORE_STATE_DIR = '.zhitong-store'

/** Object store over a local directory. */
export class LocalDirectoryStore implements ObjectStore {
  readonly label: string

  /**
   * @param root - absolute directory that plays the bucket.
   */
  constructor(private readonly root: string) {
    this.label = `local://${root}`
  }

  async list(request: ListRequest, signal: AbortSignal): Promise<ListPage> {
    signal.throwIfAborted()
    const all = await this.walk(request.prefix, request.delimited)
    const start = request.continuation === undefined ? 0 : Number.parseInt(request.continuation, 10)
    const page = all.slice(start, start + request.limit)
    const dirs: string[] = []
    const files: ObjectInfo[] = []
    for (const entry of page) {
      if (entry.endsWith('/')) dirs.push(entry)
      else {
        const info = await this.stat(entry, signal)
        if (info !== undefined) files.push(info)
      }
    }
    const end = start + page.length
    return { dirs, files, ...end < all.length ? { next: String(end) } : {} }
  }

  async stat(key: string, signal: AbortSignal): Promise<ObjectInfo | undefined> {
    signal.throwIfAborted()
    const file = this.fileFor(key)
    let info
    try {
      info = await stat(file)
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return undefined
      throw error
    }
    if (!info.isFile()) return undefined
    const meta = await this.readMeta()
    const sha256 = meta[key]
    return {
      key,
      size: info.size,
      modified: info.mtime.toISOString(),
      etag: await md5File(file),
      ...sha256 !== undefined ? { sha256 } : {},
    }
  }

  async download(key: string, filePath: string, signal: AbortSignal): Promise<void> {
    signal.throwIfAborted()
    await copyFile(this.fileFor(key), filePath)
  }

  async upload(key: string, filePath: string, sha256: string, signal: AbortSignal): Promise<PutResult> {
    signal.throwIfAborted()
    const target = this.fileFor(key)
    await mkdir(dirname(target), { recursive: true })
    await copyFile(filePath, target)
    const meta = await this.readMeta()
    meta[key] = sha256
    await writeFileAtomic(this.metaPath(), `${JSON.stringify(meta, null, 2)}\n`, { mode: 0o600 })
    return { etag: await md5File(target) }
  }

  private fileFor(key: string): string {
    return join(this.root, ...key.split('/'))
  }

  private metaPath(): string {
    return join(this.root, STORE_STATE_DIR, 'meta.json')
  }

  private async readMeta(): Promise<Record<string, string>> {
    try {
      return JSON.parse(await readFile(this.metaPath(), 'utf8')) as Record<string, string>
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return {}
      throw error
    }
  }

  /** Sorted keys below `prefix`: immediate dirs (with `/`) and files when delimited, every file otherwise. */
  private async walk(prefix: string, delimited: boolean): Promise<string[]> {
    const dirKey = prefix === '' || prefix.endsWith('/') ? prefix : prefix.slice(0, prefix.lastIndexOf('/') + 1)
    const base = join(this.root, ...dirKey.split('/').filter(part => part !== ''))
    const out: string[] = []
    const visit = async (dir: string, keyPrefix: string): Promise<void> => {
      let entries
      try {
        entries = await readdir(dir, { withFileTypes: true })
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT' || (error as NodeJS.ErrnoException).code === 'ENOTDIR') return
        throw error
      }
      for (const entry of entries) {
        if (keyPrefix === '' && entry.name === STORE_STATE_DIR) continue
        const key = `${keyPrefix}${entry.name}`
        if (entry.isDirectory()) {
          if (delimited) out.push(`${key}/`)
          else await visit(`${dir}${sep}${entry.name}`, `${key}/`)
        } else if (entry.isFile()) {
          out.push(key)
        }
      }
    }
    await visit(base, dirKey)
    return out.filter(key => key.startsWith(prefix)).sort()
  }
}

/**
 * MD5 hex digest of a file, streamed.
 * @param filePath - file to hash.
 * @returns the digest.
 */
async function md5File(filePath: string): Promise<string> {
  const hash = createHash('md5')
  for await (const chunk of createReadStream(filePath)) hash.update(chunk as Buffer)
  return hash.digest('hex')
}
