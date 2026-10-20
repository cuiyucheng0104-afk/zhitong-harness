/**
 * Reading packed npm tarballs and the order file that accompanies them.
 *
 * The release steps after pack treat a directory of tarballs as the unit of
 * work, so they read what a tarball declares rather than what the checkout
 * currently says.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { list } from 'tar'

/** Name of the file recording the order in which a packed family uploads. */
export const PUBLISH_ORDER_FILE = 'publish-order.txt'

/** What a packed tarball calls itself. */
export interface PackedIdentity {
  /** Package name from the packed manifest. */
  readonly name: string
  /** Package version from the packed manifest. */
  readonly version: string
}

/**
 * List a tarball's members.
 * @param tarball - absolute tarball path.
 * @returns Every path inside the archive.
 */
export function tarballFiles(tarball: string): string[] {
  // node-tar, not the system tar: Windows' bsdtar skips members whose names its console code page cannot
  // encode (zhitong increment: the bundle carries Chinese-named skill files) and exits non-zero.
  const files: string[] = []
  list({ file: tarball, sync: true, onReadEntry: entry => { files.push(entry.path) } })
  return files
}

/**
 * Read one member's bytes from a tarball.
 * @param tarball - Absolute tarball path.
 * @param member - Member path as the archive names it.
 * @returns The member's content.
 */
function tarballMember(tarball: string, member: string): Buffer {
  const chunks: Buffer[] = []
  let found = false
  list({
    file: tarball,
    sync: true,
    onReadEntry: entry => {
      if (entry.path !== member) return
      found = true
      entry.on('data', chunk => { chunks.push(chunk) })
    },
  })
  if (!found) throw new Error(`${tarball} has no ${member}`)
  return Buffer.concat(chunks)
}

/**
 * Read the manifest contained in a packed tarball, without consulting the checkout.
 * @param tarball - Absolute tarball path.
 * @returns The packed package.json object.
 */
export function packedManifest(tarball: string): Record<string, unknown> {
  const manifest: unknown = JSON.parse(tarballMember(tarball, 'package/package.json').toString('utf8'))
  if (manifest === null || typeof manifest !== 'object' || Array.isArray(manifest)) throw new Error(`${tarball} has no manifest`)
  return manifest as Record<string, unknown>
}

/**
 * Read a packed tarball's own identity.
 * @param tarball - Absolute tarball path.
 * @returns The name and version the tarball declares.
 */
export function packedIdentity(tarball: string): PackedIdentity {
  const { name, version } = packedManifest(tarball)
  if (typeof name !== 'string' || typeof version !== 'string') throw new Error(`${tarball} manifest lacks name/version`)
  return { name, version }
}

/**
 * Read a packed directory's upload order.
 * @param directory - absolute path of a pack output directory.
 * @returns Tarball filenames in upload order.
 */
export function readPublishOrder(directory: string): string[] {
  return readFileSync(join(directory, PUBLISH_ORDER_FILE), 'utf8').split('\n').filter(line => line !== '')
}
