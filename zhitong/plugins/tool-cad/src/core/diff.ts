/**
 * Segment-level drawing comparison. Never matches by DXF handle: segment
 * endpoints are quantized to `eps`, ordered canonically, and compared as keys.
 * Colors follow the DWG Compare convention: only-old green (removed),
 * only-new red (added), shared grey.
 *
 * Automatic registration: segments are signed by quantized length and
 * direction; matching signatures vote for a translation and the mode wins.
 * Fewer than 100 votes, or a zero offset, means no registration. Only
 * translation is handled (no rotation or scale).
 *
 * Source: tiangong-cad-viewer `src/diff.ts`. Local changes: the quantization
 * tolerance is a parameter (plugin Config, scaled by the drawing unit) instead
 * of a module constant; strict typing.
 * @module @zhitong/tool-cad/core/diff
 */
import type { BuiltScene, LayerGeom } from './sceneBuilder.ts'

/** Result of {@link diffScenes}. */
export interface DiffResult {
  /** Pseudo-scene with up to three layers: `不变(共有)`, `删除(仅旧图)`, `新增(仅新图)`. */
  scene: BuiltScene
  counts: { added: number; removed: number; unchanged: number }
  /** Translation applied to the new drawing, when registration found one. */
  offset?: { dx: number; dy: number; votes: number }
}

type Seg = [number, number, number, number]

function segKey(eps: number, x1: number, y1: number, x2: number, y2: number): string {
  const a = [Math.round(x1 / eps), Math.round(y1 / eps)] as const
  const b = [Math.round(x2 / eps), Math.round(y2 / eps)] as const
  const flip = a[0] > b[0] || (a[0] === b[0] && a[1] > b[1])
  const [p, q] = flip ? [b, a] : [a, b]
  return `${p[0]},${p[1]},${q[0]},${q[1]}`
}

function collectKeys(s: Pick<BuiltScene, 'layers'>, eps: number): Map<string, Seg> {
  const m = new Map<string, Seg>()
  for (const l of s.layers) {
    const p = l.positions
    for (let i = 0; i + 5 < p.length; i += 6) {
      m.set(segKey(eps, p[i]!, p[i + 1]!, p[i + 3]!, p[i + 4]!), [p[i]!, p[i + 1]!, p[i + 3]!, p[i + 4]!])
    }
  }
  return m
}

function estimateOffset(oldScene: BuiltScene, newScene: BuiltScene): { dx: number; dy: number; votes: number } | null {
  const sigOf = (x1: number, y1: number, x2: number, y2: number): string | null => {
    const len = Math.hypot(x2 - x1, y2 - y1)
    if (len < 50) return null
    let ang = Math.atan2(y2 - y1, x2 - x1)
    if (ang < 0) ang += Math.PI
    return `${Math.round(len / 4)}|${Math.round((ang * 180) / Math.PI / 2)}`
  }
  const canon = (x1: number, y1: number, x2: number, y2: number): [number, number] =>
    x1 > x2 || (x1 === x2 && y1 > y2) ? [x2, y2] : [x1, y1]

  const oldMap = new Map<string, Array<[number, number]>>()
  for (const l of oldScene.layers) {
    const p = l.positions
    for (let i = 0; i + 5 < p.length; i += 6) {
      const sig = sigOf(p[i]!, p[i + 1]!, p[i + 3]!, p[i + 4]!)
      if (sig === null) continue
      let arr = oldMap.get(sig)
      if (arr === undefined) { arr = []; oldMap.set(sig, arr) }
      if (arr.length < 40) arr.push(canon(p[i]!, p[i + 1]!, p[i + 3]!, p[i + 4]!))
    }
  }
  const votes = new Map<string, number>()
  let sampled = 0
  for (const l of newScene.layers) {
    const p = l.positions
    for (let i = 0; i + 5 < p.length; i += 6) {
      if (sampled > 30000) break
      const sig = sigOf(p[i]!, p[i + 1]!, p[i + 3]!, p[i + 4]!)
      if (sig === null) continue
      const cands = oldMap.get(sig)
      if (cands === undefined) continue
      sampled++
      const [nx, ny] = canon(p[i]!, p[i + 1]!, p[i + 3]!, p[i + 4]!)
      for (const [ox, oy] of cands) {
        const key = `${Math.round(ox - nx)},${Math.round(oy - ny)}`
        votes.set(key, (votes.get(key) ?? 0) + 1)
      }
    }
  }
  let best: string | null = null
  let bestN = 0
  for (const [k, n] of votes) if (n > bestN) { best = k; bestN = n }
  if (best === null || bestN < 100) return null
  const [dx, dy] = best.split(',').map(Number) as [number, number]
  if (dx === 0 && dy === 0) return null
  return { dx, dy, votes: bestN }
}

/**
 * Compare two scenes segment by segment.
 * @param oldScene - previous drawing.
 * @param newScene - current drawing.
 * @param eps - quantization tolerance in drawing units.
 * @returns counts, the registration offset, and a three-layer pseudo-scene.
 */
export function diffScenes(oldScene: BuiltScene, newScene: BuiltScene, eps: number): DiffResult {
  const off = estimateOffset(oldScene, newScene)
  let alignedNew: Pick<BuiltScene, 'layers'> = newScene
  if (off !== null) {
    alignedNew = {
      layers: newScene.layers.map((l) => {
        const p = new Float32Array(l.positions)
        for (let i = 0; i + 1 < p.length; i += 3) { p[i] = p[i]! + off.dx; p[i + 1] = p[i + 1]! + off.dy }
        return { ...l, positions: p }
      }),
    }
  }
  const oldMap = collectKeys(oldScene, eps)
  const newMap = collectKeys(alignedNew, eps)

  const buckets: Record<'added' | 'removed' | 'unchanged', number[]> = { added: [], removed: [], unchanged: [] }
  for (const [k, seg] of newMap) {
    if (oldMap.has(k)) buckets.unchanged.push(...seg)
    else buckets.added.push(...seg)
  }
  for (const [k, seg] of oldMap) {
    if (!newMap.has(k)) buckets.removed.push(...seg)
  }

  const mkLayer = (name: string, xy: number[], rgb: number): LayerGeom => {
    const n = xy.length / 4
    const positions = new Float32Array(n * 6)
    const colors = new Float32Array(n * 6)
    const r = ((rgb >> 16) & 255) / 255
    const g = ((rgb >> 8) & 255) / 255
    const b = (rgb & 255) / 255
    for (let i = 0; i < n; i++) {
      positions.set([xy[i * 4]!, xy[i * 4 + 1]!, 0, xy[i * 4 + 2]!, xy[i * 4 + 3]!, 0], i * 6)
      colors.set([r, g, b, r, g, b], i * 6)
    }
    return { name, positions, colors, segCount: n }
  }

  const layers = [
    mkLayer('不变(共有)', buckets.unchanged, 0x4a4a52),
    mkLayer('删除(仅旧图)', buckets.removed, 0x2ecc71),
    mkLayer('新增(仅新图)', buckets.added, 0xff4d4d),
  ].filter(l => l.segCount > 0)

  const nb = off !== null
    ? { minX: newScene.bbox.minX + off.dx, minY: newScene.bbox.minY + off.dy, maxX: newScene.bbox.maxX + off.dx, maxY: newScene.bbox.maxY + off.dy }
    : newScene.bbox
  const bbox = {
    minX: Math.min(oldScene.bbox.minX, nb.minX),
    minY: Math.min(oldScene.bbox.minY, nb.minY),
    maxX: Math.max(oldScene.bbox.maxX, nb.maxX),
    maxY: Math.max(oldScene.bbox.maxY, nb.maxY),
  }
  const counts = { added: buckets.added.length / 4, removed: buckets.removed.length / 4, unchanged: buckets.unchanged.length / 4 }
  const total = counts.added + counts.removed + counts.unchanged
  const scene: BuiltScene = {
    layers,
    hatches: [],
    texts: [],
    inserts: [],
    polys: [],
    dims: [],
    layerTable: [],
    header: { insunits: null, measurement: null, acadver: null, codepage: null },
    bbox,
    stats: { entityCount: total, segCount: total, skipped: {}, parseMs: 0, buildMs: 0 },
  }
  return off !== null ? { scene, counts, offset: off } : { scene, counts }
}
