/**
 * Drawing-cluster detection ("图框" in the source viewer): the criteria match
 * the quantity-takeoff Python scripts 03/06 — sort points by X, split columns
 * at gaps larger than `gap`, split each column by Y with the same gap, and keep
 * cells whose bounding box exceeds `minAreaM2` with at least `minPts` points.
 * Points are segment endpoints of wall/axis/column layers, or of every layer
 * when no layer name matches.
 *
 * Source: tiangong-cad-viewer `src/frames.ts`. Local changes: the criteria are
 * parameters (plugin Config) instead of module constants, and area uses the
 * drawing unit scale instead of assuming millimetres.
 * @module @zhitong/tool-cad/core/frames
 */
import type { BuiltScene } from './sceneBuilder.ts'

/** One detected drawing cluster. */
export interface Frame {
  id: number
  /** Display label; `图框N` from detection. */
  label: string
  x1: number
  y1: number
  x2: number
  y2: number
}

/** Clustering criteria. */
export interface FrameCriteria {
  /** Empty gap that separates two drawings, in millimetres. */
  gapMm: number
  /** Minimum cluster bounding-box area in square metres. */
  minAreaM2: number
  /** Minimum number of endpoints in a cluster. */
  minPts: number
  /** Layer-name pattern selecting the point source. */
  layerHint: RegExp
  /** Maximum endpoints sampled; later layers are ignored once reached. */
  pointCap: number
  /** Millimetres per drawing unit. */
  mmPerUnit: number
}

/** Result of {@link detectFrames}. */
export interface FrameDetection {
  frames: Frame[]
  /** True when no layer matched `layerHint` and every layer was used. */
  allLayersFallback: boolean
  /** True when `pointCap` was reached and remaining endpoints were ignored. */
  capped: boolean
}

const cluster = (vals: number[], gap: number): Array<[number, number]> => {
  if (vals.length === 0) return []
  const sorted = [...vals].sort((a, b) => a - b)
  const out: Array<[number, number]> = []
  let start = sorted[0]!
  let last = sorted[0]!
  for (let i = 1; i < sorted.length; i++) {
    const v = sorted[i]!
    if (v - last > gap) { out.push([start, last]); start = v }
    last = v
  }
  out.push([start, last])
  return out
}

/**
 * Detect drawing clusters.
 * @param scene - built scene.
 * @param criteria - clustering criteria.
 * @returns clusters in column-then-row order, plus fallback and cap flags.
 */
export function detectFrames(scene: BuiltScene, criteria: FrameCriteria): FrameDetection {
  let layers = scene.layers.filter(l => criteria.layerHint.test(l.name))
  const allLayersFallback = layers.length === 0
  if (allLayersFallback) layers = scene.layers
  const pts: Array<[number, number]> = []
  let capped = false
  for (const l of layers) {
    const p = l.positions
    for (let i = 0; i + 5 < p.length; i += 6) {
      if (pts.length >= criteria.pointCap) { capped = true; break }
      pts.push([p[i]!, p[i + 1]!], [p[i + 3]!, p[i + 4]!])
    }
  }
  if (pts.length < criteria.minPts) return { frames: [], allLayersFallback, capped }

  const gap = criteria.gapMm / criteria.mmPerUnit
  const m2PerUnit2 = (criteria.mmPerUnit / 1000) ** 2
  const frames: Frame[] = []
  let id = 1
  for (const [xa, xb] of cluster(pts.map(p => p[0]), gap)) {
    const colPts = pts.filter(p => p[0] >= xa && p[0] <= xb)
    for (const [ya, yb] of cluster(colPts.map(p => p[1]), gap)) {
      const cellPts = colPts.filter(p => p[1] >= ya && p[1] <= yb)
      const areaM2 = (xb - xa) * (yb - ya) * m2PerUnit2
      if (areaM2 > criteria.minAreaM2 && cellPts.length >= criteria.minPts) {
        frames.push({ id, label: `图框${id}`, x1: xa, y1: ya, x2: xb, y2: yb })
        id++
      }
    }
  }
  return { frames, allLayersFallback, capped }
}

/**
 * Find the frame containing a point.
 * @param frames - candidate frames.
 * @param x - world X.
 * @param y - world Y.
 * @returns the first containing frame, or null.
 */
export function pointFrame<F extends { x1: number; y1: number; x2: number; y2: number }>(frames: readonly F[], x: number, y: number): F | null {
  for (const f of frames) {
    if (x >= f.x1 && x <= f.x2 && y >= f.y1 && y <= f.y2) return f
  }
  return null
}
