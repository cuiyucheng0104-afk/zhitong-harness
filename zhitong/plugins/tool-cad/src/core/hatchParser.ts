/**
 * Minimal solid-fill HATCH parser. dxf-parser 1.1.2 does not parse HATCH, so
 * the ENTITIES section is scanned group code by group code:
 * - polyline boundaries (flag & 2): 10/20 vertices plus 42 bulge arcs;
 * - edge boundaries: 72=1 lines, 72=2 arcs; ellipse and spline edges are skipped and counted;
 * - several loops: the external loop is the outer ring, the rest become earcut holes;
 * - every hatch is treated as a solid fill (patterns are not drawn).
 *
 * Only top-level HATCH entities are read; HATCH inside blocks is not expanded.
 *
 * Source: tiangong-cad-viewer `src/engine/hatchParser.ts` (logic unchanged; strict typing added).
 * @module @zhitong/tool-cad/core/hatchParser
 */
import earcut from 'earcut'
import { aciToRgb } from './aci.ts'

/** Triangulated fill geometry of one layer. */
export interface HatchLayerGeom {
  name: string
  /** xyz × 3 × triCount. */
  positions: Float32Array
  /** rgb × 3 × triCount, channels in 0..1. */
  colors: Float32Array
  triCount: number
}

/** Result of {@link parseHatches}. */
export interface HatchResult {
  layers: HatchLayerGeom[]
  /** HATCH entities that produced at least one ring. */
  count: number
  /** Boundary paths or edges that could not be used. */
  skippedPaths: number
}

interface Ring { flat: number[]; external: boolean }
interface OpenRing { pts: number[]; bulges: number[]; external: boolean; polyline: boolean }
interface Edge { x1?: number; y1?: number; cx?: number; cy?: number; r?: number; a1?: number; a2?: number; ccw?: number }

function bulgeArc(x1: number, y1: number, x2: number, y2: number, bulge: number, out: number[]): void {
  const theta = 4 * Math.atan(bulge)
  const dx = x2 - x1
  const dy = y2 - y1
  const d = Math.hypot(dx, dy)
  if (d < 1e-12) return
  const r = d / (2 * Math.sin(Math.abs(theta) / 2))
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  const h = Math.sqrt(Math.max(0, r * r - (d / 2) ** 2)) * Math.sign(bulge) * (Math.abs(theta) > Math.PI ? -1 : 1)
  const cx = mx - (dy / d) * h
  const cy = my + (dx / d) * h
  const a1 = Math.atan2(y1 - cy, x1 - cx)
  const steps = Math.max(4, Math.ceil(Math.abs(theta) / (Math.PI / 24)))
  for (let s = 1; s < steps; s++) {
    const a = a1 + (theta * s) / steps
    out.push(cx + r * Math.cos(a), cy + r * Math.sin(a))
  }
}

/**
 * Scan the ENTITIES section of DXF text for solid HATCH fills.
 * @param dxfText - complete DXF text.
 * @param layerRgb - layer color lookup used when the hatch has no ACI color.
 * @returns per-layer triangles and counts.
 */
export function parseHatches(dxfText: string, layerRgb: (name: string) => number): HatchResult {
  const lines = dxfText.split(/\r?\n/)
  const line = (k: number): string => (lines[k] ?? '').trim()
  let start = -1
  for (let k = 1; k < lines.length; k++) {
    if (line(k) === 'ENTITIES' && line(k - 1) === '2') { start = k + 1; break }
  }
  if (start < 0) return { layers: [], count: 0, skippedPaths: 0 }

  const buckets = new Map<string, { pos: number[]; col: number[] }>()
  let count = 0
  let skippedPaths = 0

  let i = start
  const N = lines.length
  while (i < N - 1) {
    if (line(i) === '0' && line(i + 1) === 'ENDSEC') break
    if (line(i) === '0' && line(i + 1) === 'HATCH') {
      i += 2
      let layer = '0'
      let ci: number | null = null
      const rings: Ring[] = []
      let cur: OpenRing | null = null
      let edgeType = 0
      let edge: Edge = {}
      let inBoundary = false

      const flushRing = (): void => {
        if (cur === null) return
        const flat: number[] = []
        const n = cur.pts.length / 2
        for (let v = 0; v < n; v++) {
          const x1 = cur.pts[v * 2]!
          const y1 = cur.pts[v * 2 + 1]!
          flat.push(x1, y1)
          const b = cur.bulges[v] ?? 0
          if (b !== 0) {
            const w = (v + 1) % n
            bulgeArc(x1, y1, cur.pts[w * 2]!, cur.pts[w * 2 + 1]!, b, flat)
          }
        }
        if (flat.length >= 6) rings.push({ flat, external: cur.external })
        else skippedPaths++
        cur = null
      }
      const flushEdge = (): void => {
        if (cur === null || edgeType === 0) return
        if (edgeType === 1 && edge.x1 !== undefined && edge.y1 !== undefined) {
          cur.pts.push(edge.x1, edge.y1)
          cur.bulges.push(0)
        } else if (edgeType === 2 && edge.cx !== undefined && edge.cy !== undefined && edge.r !== undefined) {
          const ccw = (edge.ccw ?? 1) !== 0
          const a1 = ((edge.a1 ?? 0) * Math.PI) / 180
          let a2 = ((edge.a2 ?? 360) * Math.PI) / 180
          if (ccw) { while (a2 <= a1) a2 += Math.PI * 2 } else { while (a2 >= a1) a2 -= Math.PI * 2 }
          const steps = Math.max(6, Math.ceil(Math.abs(a2 - a1) / (Math.PI / 24)))
          for (let s = 0; s < steps; s++) {
            const a = a1 + ((a2 - a1) * s) / steps
            cur.pts.push(edge.cx + edge.r * Math.cos(a), edge.cy + edge.r * Math.sin(a))
            cur.bulges.push(0)
          }
        } else if (edgeType > 2) {
          skippedPaths++
        }
        edge = {}
        edgeType = 0
      }

      while (i < N - 1) {
        const code = line(i)
        if (code === '0') break
        const val = line(i + 1)
        i += 2
        const open = cur as OpenRing | null
        switch (code) {
          case '8': layer = val; break
          case '62': ci = Number.parseInt(val, 10); break
          case '92': {
            flushEdge()
            flushRing()
            const flag = Number.parseInt(val, 10)
            cur = { pts: [], bulges: [], external: (flag & 1) !== 0, polyline: (flag & 2) !== 0 }
            inBoundary = true
            break
          }
          case '72':
            if (open !== null && !open.polyline && inBoundary) { flushEdge(); edgeType = Number.parseInt(val, 10) }
            break
          case '10':
            if (open === null || !inBoundary) break
            if (open.polyline) { open.pts.push(Number.parseFloat(val), 0); open.bulges.push(0) }
            else if (edgeType === 1) edge.x1 = Number.parseFloat(val)
            else if (edgeType === 2) edge.cx = Number.parseFloat(val)
            break
          case '20':
            if (open === null || !inBoundary) break
            if (open.polyline) open.pts[open.pts.length - 1] = Number.parseFloat(val)
            else if (edgeType === 1) edge.y1 = Number.parseFloat(val)
            else if (edgeType === 2) edge.cy = Number.parseFloat(val)
            break
          case '40': if (edgeType === 2) edge.r = Number.parseFloat(val); break
          case '50': if (edgeType === 2) edge.a1 = Number.parseFloat(val); break
          case '51': if (edgeType === 2) edge.a2 = Number.parseFloat(val); break
          case '73': if (open !== null && !open.polyline && edgeType === 2) edge.ccw = Number.parseInt(val, 10); break
          case '42': if (open?.polyline === true && open.bulges.length > 0) open.bulges[open.bulges.length - 1] = Number.parseFloat(val); break
          case '75': flushEdge(); flushRing(); inBoundary = false; break
          default: break
        }
      }
      flushEdge()
      flushRing()

      if (rings.length > 0) {
        count++
        const outer = rings.find(r => r.external) ?? rings[0]!
        const holes = rings.filter(r => r !== outer)
        const data: number[] = [...outer.flat]
        const holeIdx: number[] = []
        for (const h of holes) { holeIdx.push(data.length / 2); data.push(...h.flat) }
        let tri: number[]
        try {
          tri = earcut(data, holeIdx.length > 0 ? holeIdx : undefined)
        } catch (error) {
          // A degenerate ring makes earcut throw; the hatch is counted as skipped instead of failing the drawing.
          void error
          tri = []
          skippedPaths++
        }
        if (tri.length > 0) {
          const rgb = ci !== null && ci >= 1 && ci <= 255 ? aciToRgb(ci) : layerRgb(layer)
          const r = ((rgb >> 16) & 255) / 255
          const g = ((rgb >> 8) & 255) / 255
          const b = (rgb & 255) / 255
          let bucket = buckets.get(layer)
          if (bucket === undefined) { bucket = { pos: [], col: [] }; buckets.set(layer, bucket) }
          for (const idx of tri) {
            bucket.pos.push(data[idx * 2]!, data[idx * 2 + 1]!, 0)
            bucket.col.push(r, g, b)
          }
        }
      }
    } else {
      i += 2
    }
  }

  const layers: HatchLayerGeom[] = []
  for (const [name, b] of buckets) {
    layers.push({ name, positions: new Float32Array(b.pos), colors: new Float32Array(b.col), triCount: b.pos.length / 9 })
  }
  return { layers, count, skippedPaths }
}
