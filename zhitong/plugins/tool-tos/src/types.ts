/** Object-store types shared by the TOS and local-directory backends. @module @zhitong/tool-tos/types */

/** One stored object as the backend reports it. Keys are full bucket keys, `/`-separated. */
export interface ObjectInfo {
  /** Full bucket key, including the company prefix. */
  readonly key: string
  /** Size in bytes. */
  readonly size: number
  /** Last-modified time as an ISO-8601 string. */
  readonly modified: string
  /** Entity tag without surrounding quotes; a single-part upload's tag is the content MD5 in hex. */
  readonly etag: string
  /** Version id when the bucket keeps versions. */
  readonly versionId?: string
  /** SHA-256 hex digest recorded in object metadata by `tos_push`, when present. */
  readonly sha256?: string
}

/** One page of a delimiter listing. */
export interface ListPage {
  /** Full keys of the immediate sub-directories (common prefixes), each ending in `/`. */
  readonly dirs: readonly string[]
  /** Objects directly under the listed prefix (or every object below it for a recursive listing). */
  readonly files: readonly ObjectInfo[]
  /** Opaque continuation token for the next page; absent on the last page. */
  readonly next?: string
}

/** Listing request. */
export interface ListRequest {
  /** Full key prefix; empty lists the bucket root. */
  readonly prefix: string
  /** Group by `/` into `dirs` (true) or return every object below the prefix (false). */
  readonly delimited: boolean
  /** Maximum number of `dirs` plus `files` in this page. */
  readonly limit: number
  /** Continuation token from the previous page. */
  readonly continuation?: string
}

/** Result of one upload. */
export interface PutResult {
  /** Entity tag the store reported, without quotes; empty when the store reports none. */
  readonly etag: string
  /** Version id of the new object version, when the bucket keeps versions. */
  readonly versionId?: string
}

/**
 * The object-store operations the tools need. Implementations throw on
 * transport and authorization failures and return `undefined` from `stat`
 * only when the key does not exist.
 */
export interface ObjectStore {
  /** Human-readable location used in tool results, such as `tos://bucket`. */
  readonly label: string
  /**
   * List one page under a prefix.
   * @param request - prefix, grouping, page size, and continuation.
   * @param signal - cancellation for the request.
   * @returns the page.
   */
  list(request: ListRequest, signal: AbortSignal): Promise<ListPage>
  /**
   * Read one object's metadata.
   * @param key - full bucket key.
   * @param signal - cancellation for the request.
   * @returns the metadata, or `undefined` when the key does not exist.
   */
  stat(key: string, signal: AbortSignal): Promise<ObjectInfo | undefined>
  /**
   * Download one object to a local file, replacing it.
   * @param key - full bucket key.
   * @param filePath - absolute destination path; its directory exists.
   * @param signal - cancellation for the request.
   */
  download(key: string, filePath: string, signal: AbortSignal): Promise<void>
  /**
   * Upload one local file as an object.
   * @param key - full bucket key.
   * @param filePath - absolute source path.
   * @param sha256 - hex digest stored as object metadata.
   * @param signal - cancellation for the request.
   * @returns the stored version's tag and id.
   */
  upload(key: string, filePath: string, sha256: string, signal: AbortSignal): Promise<PutResult>
}
