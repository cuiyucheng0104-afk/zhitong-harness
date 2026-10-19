/**
 * Binary parse cache. One file per source drawing, named
 * `<sha256>-<SCENE_VERSION>.scene`, so a changed drawing or a changed scene
 * builder misses the cache. Layout: the 8-byte magic `ZTCADSC1`, a uint32
 * little-endian JSON length, the JSON document (scene with typed arrays
 * replaced by indices, plus conversion metadata), zero padding to a 4-byte
 * boundary, then every Float32Array in index order.
 * @module @zhitong/tool-cad/store/sceneCache
 */
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { HatchLayerGeom } from '../core/hatchParser.ts'
import type { BuiltScene, LayerGeom } from '../core/sceneBuilder.ts'
import { SCENE_VERSION } from '../core/sceneBuilder.ts'

/** Conversion facts stored with the scene. */
export interface CacheMeta {
  sha256: string
  format: 'dwg' | 'dxf'
  encoding: string
  /** `\U+XXXX` escapes expanded while decoding. */
  escapes: number
  converter: { path: string; version: string | null } | null
  hatchCount: number
  hatchSkipped: number
}

/** A cached scene with its metadata. */
export interface CachedScene {
  meta: CacheMeta
  scene: BuiltScene
}

const MAGIC = Buffer.from('ZTCADSC1', 'latin1')

/**
 * Cache file path for a drawing.
 * @param dir - cache directory.
 * @param sha256 - drawing content hash.
 * @returns the path.
 */
export function cachePath(dir: string, sha256: string): string {
  return join(dir, `${sha256}-${SCENE_VERSION}.scene`)
}

/**
 * Serialize a scene and its metadata.
 * @param entry - scene and metadata.
 * @returns the cache file bytes.
 */
export function serializeScene(entry: CachedScene): Buffer {
  const arrays: Float32Array[] = []
  const ref = (a: Float32Array): number => { arrays.push(a); return arrays.length - 1 }
  const doc = {
    version: SCENE_VERSION,
    meta: entry.meta,
    scene: {
      ...entry.scene,
      layers: entry.scene.layers.map(l => ({ name: l.name, segCount: l.segCount, positions: ref(l.positions), colors: ref(l.colors) })),
      hatches: entry.scene.hatches.map(h => ({ name: h.name, triCount: h.triCount, positions: ref(h.positions), colors: ref(h.colors) })),
    },
    lengths: [] as number[],
  }
  doc.lengths = arrays.map(a => a.length)
  const json = Buffer.from(JSON.stringify(doc), 'utf8')
  const head = Buffer.alloc(12)
  MAGIC.copy(head, 0)
  head.writeUInt32LE(json.length, 8)
  const pad = Buffer.alloc((4 - ((12 + json.length) % 4)) % 4)
  const bodies = arrays.map(a => Buffer.from(a.buffer, a.byteOffset, a.byteLength))
  return Buffer.concat([head, json, pad, ...bodies])
}

interface StoredLayer { name: string; segCount: number; positions: number; colors: number }
interface StoredHatch { name: string; triCount: number; positions: number; colors: number }

/**
 * Deserialize cache bytes.
 * @param buf - cache file bytes.
 * @returns the entry, or null when the magic or scene version does not match.
 */
export function deserializeScene(buf: Buffer): CachedScene | null {
  if (buf.length < 12 || !buf.subarray(0, 8).equals(MAGIC)) return null
  const jsonLength = buf.readUInt32LE(8)
  const doc = JSON.parse(buf.subarray(12, 12 + jsonLength).toString('utf8')) as {
    version: string
    meta: CacheMeta
    scene: Omit<BuiltScene, 'layers' | 'hatches'> & { layers: StoredLayer[]; hatches: StoredHatch[] }
    lengths: number[]
  }
  if (doc.version !== SCENE_VERSION) return null
  let offset = 12 + jsonLength
  offset += (4 - (offset % 4)) % 4
  const arrays = doc.lengths.map((length) => {
    const bytes = buf.subarray(offset, offset + length * 4)
    offset += length * 4
    const copy = new Float32Array(length)
    new Uint8Array(copy.buffer).set(bytes)
    return copy
  })
  const at = (i: number): Float32Array => arrays[i]!
  const layers: LayerGeom[] = doc.scene.layers.map(l => ({ name: l.name, segCount: l.segCount, positions: at(l.positions), colors: at(l.colors) }))
  const hatches: HatchLayerGeom[] = doc.scene.hatches.map(h => ({ name: h.name, triCount: h.triCount, positions: at(h.positions), colors: at(h.colors) }))
  return { meta: doc.meta, scene: { ...doc.scene, layers, hatches } }
}

/**
 * Read a cache entry.
 * @param dir - cache directory.
 * @param sha256 - drawing content hash.
 * @returns the entry, or null on a miss or an unreadable file.
 */
export async function readSceneCache(dir: string, sha256: string): Promise<CachedScene | null> {
  let buf: Buffer
  try {
    buf = await readFile(cachePath(dir, sha256))
  } catch (error) {
    // A missing cache file is an ordinary miss.
    void error
    return null
  }
  try {
    return deserializeScene(buf)
  } catch (error) {
    // A truncated or foreign file is treated as a miss and rebuilt by the caller.
    void error
    return null
  }
}

/**
 * Write a cache entry atomically (temporary file, then rename).
 * @param dir - cache directory, created when missing.
 * @param entry - scene and metadata.
 * @returns the cache file path.
 */
export async function writeSceneCache(dir: string, entry: CachedScene): Promise<string> {
  await mkdir(dir, { recursive: true })
  const path = cachePath(dir, entry.meta.sha256)
  const tmp = `${path}.${process.pid}.${Date.now()}.tmp`
  await writeFile(tmp, serializeScene(entry))
  await rename(tmp, path)
  return path
}
