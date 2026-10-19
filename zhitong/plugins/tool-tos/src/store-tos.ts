/**
 * Volcengine TOS object store over the official `@volcengine/tos-sdk`. The SDK
 * is imported on first use so profiles that never reach TOS do not load it.
 * Credentials are passed in per operation by the caller, which resolves them
 * from the credential store each time.
 * @module @zhitong/tool-tos/store-tos
 */

import type { TosClient as TosClientType } from '@volcengine/tos-sdk'
import type { TosConnection } from './config.ts'
import type { ListPage, ListRequest, ObjectInfo, ObjectStore, PutResult } from './types.ts'

/** Access key pair resolved from the credential store. */
export interface TosCredentials {
  readonly accessKeyId: string
  readonly secretAccessKey: string
}

/** Metadata key `tos_push` writes; TOS returns it as the `x-tos-meta-sha256` header. */
const SHA256_META = 'sha256'

/** TOS store bound to one connection and credential pair. */
export class TosObjectStore implements ObjectStore {
  readonly label: string
  private client: Promise<TosClientType> | undefined

  /**
   * @param connection - endpoint, region, and bucket.
   * @param credentials - access key pair for this operation.
   */
  constructor(private readonly connection: TosConnection, private readonly credentials: TosCredentials) {
    this.label = `tos://${connection.bucket}`
  }

  async list(request: ListRequest, signal: AbortSignal): Promise<ListPage> {
    signal.throwIfAborted()
    const client = await this.sdk()
    const { data } = await client.listObjectsType2({
      prefix: request.prefix,
      maxKeys: request.limit,
      listOnlyOnce: true,
      ...request.delimited ? { delimiter: '/' } : {},
      ...request.continuation !== undefined ? { continuationToken: request.continuation } : {},
    })
    return {
      dirs: (data.CommonPrefixes ?? []).map(entry => entry.Prefix),
      files: (data.Contents ?? [])
        .filter(item => !item.Key.endsWith('/'))
        .map(item => ({ key: item.Key, size: item.Size, modified: item.LastModified, etag: unquote(item.ETag) })),
      ...data.IsTruncated && data.NextContinuationToken !== undefined ? { next: data.NextContinuationToken } : {},
    }
  }

  async stat(key: string, signal: AbortSignal): Promise<ObjectInfo | undefined> {
    signal.throwIfAborted()
    const client = await this.sdk()
    try {
      const { data } = await client.headObject({ key })
      const sha256 = data[`x-tos-meta-${SHA256_META}`]
      const versionId = data['x-tos-version-id']
      return {
        key,
        size: Number(data['content-length']),
        modified: new Date(data['last-modified']).toISOString(),
        etag: unquote(data.etag),
        ...typeof versionId === 'string' && versionId !== '' ? { versionId } : {},
        ...typeof sha256 === 'string' && sha256 !== '' ? { sha256 } : {},
      }
    } catch (error) {
      if (isNotFound(error)) return undefined
      throw error
    }
  }

  async download(key: string, filePath: string, signal: AbortSignal): Promise<void> {
    signal.throwIfAborted()
    const client = await this.sdk()
    await client.getObjectToFile({ key, filePath })
  }

  async upload(key: string, filePath: string, sha256: string, signal: AbortSignal): Promise<PutResult> {
    signal.throwIfAborted()
    const client = await this.sdk()
    const { headers, data } = await client.putObjectFromFile({ key, filePath, meta: { [SHA256_META]: sha256 } })
    const etag = (headers as Record<string, string | undefined>)['etag']
    const versionId = data['x-tos-version-id']
    return {
      etag: etag === undefined ? '' : unquote(etag),
      ...versionId !== undefined && versionId !== '' ? { versionId } : {},
    }
  }

  private sdk(): Promise<TosClientType> {
    this.client ??= import('@volcengine/tos-sdk').then(({ TosClient }) => new TosClient({
      accessKeyId: this.credentials.accessKeyId,
      accessKeySecret: this.credentials.secretAccessKey,
      region: this.connection.region,
      endpoint: this.connection.endpoint,
      bucket: this.connection.bucket,
    }))
    return this.client
  }
}

function unquote(etag: string): string {
  return etag.replace(/^"|"$/gu, '')
}

function isNotFound(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { statusCode?: unknown }).statusCode === 404
}
