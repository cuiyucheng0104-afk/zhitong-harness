/**
 * DXF entities to per-layer batched line segments plus texts, block
 * references, closed polygons, dimension samples, and the layer table.
 *
 * - INSERT blocks expand recursively (2D affine transform, depth ≤ 8); entities on layer `0` inside a block inherit the host layer.
 * - LWPOLYLINE/POLYLINE bulges become arcs; ARC/CIRCLE/ELLIPSE/SPLINE are discretized; SOLID/3DFACE draw their outline.
 * - DIMENSION renders through its anonymous `*D…` block.
 * - Paper-space entities are skipped and counted.
 * - TEXT/MTEXT/ATTRIB keep their insertion point; horizontal and vertical alignment and MTEXT wrapping are not applied.
 *
 * Source: tiangong-cad-viewer `src/engine/sceneBuilder.ts`. Local changes:
 * snap-point collection removed; texts, inserts, and polygons carry the
 * handle of the top-level entity that produced them; inserts carry depth,
 * parent block, and rotation; dimension samples, the layer table, `$ACADVER`, and
 * `$DWGCODEPAGE` are collected; the bounding box also covers text insertion
 * points. {@link SCENE_VERSION} changed accordingly.
 * @module @zhitong/tool-cad/core/sceneBuilder
 */
import { aciToRgb } from './aci.ts'
import type { HatchLayerGeom } from './hatchParser.ts'

/** Scene builder version; part of the parse cache key, so a change invalidates cached scenes. */
export const SCENE_VERSION = 's7.2-zt1'

/** Line segments of one layer. */
export interface LayerGeom {
  name: string
  /** xyz × 2 × segCount; z is always 0. */
  positions: Float32Array
  /** rgb × 2 × segCount, channels in 0..1. */
  colors: Float32Array
  segCount: number
}

/** One text fragment in world coordinates. */
export interface TextItem {
  x: number
  y: number
  /** Text height in drawing units (block scale applied). */
  h: number
  /** Rotation in radians. */
  rot: number
  str: string
  layer: string
  rgb: number
  /** Handle of the top-level entity: the text itself, or the INSERT/DIMENSION that contains it. */
  handle: string
  /** Innermost block name when the text comes from a block, otherwise null. */
  block: string | null
}

/** One block reference in world coordinates (every nesting depth). */
export interface InsertItem {
  name: string
  x: number
  y: number
  layer: string
  /** Handle of the top-level entity that produced this reference. */
  handle: string
  /** 0 for a top-level INSERT, 1 for one inside a block, and so on. */
  depth: number
  /** Name of the block that contains this reference, or null at top level. Anonymous parents (`*D…`, `*U…`) mark dimension and dynamic-block internals. */
  parent: string | null
  /** World rotation in radians. */
  rot: number
}

/** One closed LWPOLYLINE/POLYLINE in world coordinates (chord approximation, flat xy). */
export interface PolyItem {
  pts: number[]
  layer: string
  handle: string
}

/** A dimension's measured value next to the value it displays, used as unit evidence. */
export interface DimensionSample {
  /** `actualMeasurement` (group 42) in drawing units. */
  measured: number
  /** Number shown on the drawing (override text or the anonymous block's text). */
  shown: number
  x: number
  y: number
  handle: string
}

/** One LAYER table record. */
export interface LayerInfo {
  name: string
  color: number
  frozen: boolean
  /** False when the layer is switched off (negative color). */
  visible: boolean
}

/** Build statistics. */
export interface SceneStats {
  entityCount: number
  segCount: number
  /** Skipped entity counts by reason (`paperspace`, `INSERT?<missing block>`, entity type). */
  skipped: Record<string, number>
  parseMs: number
  buildMs: number
}

/** DXF header variables this plugin reads. */
export interface SceneHeader {
  /** `$INSUNITS`: 0 unspecified, 1 inch, 4 mm, 5 cm, 6 m. */
  insunits: number | null
  /** `$MEASUREMENT`: 0 imperial, 1 metric. */
  measurement: number | null
  acadver: string | null
  codepage: string | null
}

/** Headless scene of one drawing. */
export interface BuiltScene {
  layers: LayerGeom[]
  hatches: HatchLayerGeom[]
  texts: TextItem[]
  inserts: InsertItem[]
  header: SceneHeader
  polys: PolyItem[]
  dims: DimensionSample[]
  layerTable: LayerInfo[]
  bbox: { minX: number; minY: number; maxX: number; maxY: number }
  stats: SceneStats
}

/**
 * Strip TEXT/MTEXT control codes: `%%c`→Ø, `%%d`→°, `%%p`→±, `\P` paragraph
 * breaks become spaces, `\f…;` style codes and braces are removed.
 * @param s - raw text value.
 * @returns cleaned text, trimmed.
 */
export function cleanDxfText(s: string | undefined): string {
  if (s === undefined || s === '') return ''
  return s
    .replace(/%%[cC]/g, 'Ø').replace(/%%[dD]/g, '°').replace(/%%[pP]/g, '±')
    .replace(/\\P/g, ' ')
    .replace(/\\[A-Za-z][^;\\{}]*;/g, '')
    .replace(/[{}]/g, '')
    .trim()
}

type Mat = [number, number, number, number, number, number]
const IDENT: Mat = [1, 0, 0, 1, 0, 0]
const mul = (m: Mat, n: Mat): Mat => [
  m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
  m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
  m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5],
]
const apply = (m: Mat, x: number, y: number): [number, number] =>
  [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]]

/**
 * One dxf-parser entity or block. dxf-parser publishes per-entity interfaces
 * but its entity union omits fields read here on every entity (`inPaperSpace`,
 * `colorIndex`, `bulge`, `shape`, SPLINE knots), and the parsed object graph is
 * untyped JSON-like data; narrowing every access would duplicate its parser.
 */
type RawEntity = Record<string, any>

/** Parsed DXF document as returned by `DxfParser.parseSync`. */
export interface DxfDocument {
  header?: Record<string, unknown>
  tables?: { layer?: { layers?: Record<string, RawEntity> } }
  blocks?: Record<string, RawEntity>
  entities?: RawEntity[]
}

interface Bucket { pos: number[]; col: number[] }

const NUMERIC_TEXT = /^\d+(?:\.\d+)?$/

/**
 * Build the headless scene.
 * @param dxf - parsed DXF document.
 * @param parseMs - time spent parsing, recorded in stats.
 * @param hatches - triangulated top-level HATCH fills from {@link parseHatches}.
 * @returns the scene.
 */
export function buildScene(dxf: DxfDocument, parseMs: number, hatches: HatchLayerGeom[] = []): BuiltScene {
  const hdr = dxf.header ?? {}
  const num = (v: unknown): number | null => (typeof v === 'number' ? v : null)
  const str = (v: unknown): string | null => (typeof v === 'string' ? v : null)
  const header: SceneHeader = {
    insunits: num(hdr.$INSUNITS),
    measurement: num(hdr.$MEASUREMENT),
    acadver: str(hdr.$ACADVER),
    codepage: str(hdr.$DWGCODEPAGE),
  }
  const t0 = performance.now()
  const buckets = new Map<string, Bucket>()
  const skipped: Record<string, number> = {}
  const skip = (key: string): void => { skipped[key] = (skipped[key] ?? 0) + 1 }
  const texts: TextItem[] = []
  const inserts: InsertItem[] = []
  const polys: PolyItem[] = []
  const dims: DimensionSample[] = []
  let entityCount = 0
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity

  const layerRecords = dxf.tables?.layer?.layers ?? {}
  const layerTable: LayerInfo[] = Object.values(layerRecords).map(l => ({
    name: String(l.name),
    color: typeof l.color === 'number' ? l.color : 0xffffff,
    frozen: l.frozen === true,
    visible: l.visible !== false,
  }))
  const layerRgb = (name: string): number => {
    const l = layerRecords[name]
    return typeof l?.color === 'number' ? l.color : 0xffffff
  }

  const bucket = (layer: string): Bucket => {
    let b = buckets.get(layer)
    if (b === undefined) { b = { pos: [], col: [] }; buckets.set(layer, b) }
    return b
  }

  const seg = (b: Bucket, x1: number, y1: number, x2: number, y2: number, rgb: number): void => {
    b.pos.push(x1, y1, 0, x2, y2, 0)
    const r = ((rgb >> 16) & 255) / 255
    const g = ((rgb >> 8) & 255) / 255
    const bl = (rgb & 255) / 255
    b.col.push(r, g, bl, r, g, bl)
    if (x1 < minX) minX = x1
    if (x1 > maxX) maxX = x1
    if (y1 < minY) minY = y1
    if (y1 > maxY) maxY = y1
    if (x2 < minX) minX = x2
    if (x2 > maxX) maxX = x2
    if (y2 < minY) minY = y2
    if (y2 > maxY) maxY = y2
  }

  /** 0 = ByBlock (host color), 256 or missing = ByLayer, 1-255 = ACI. */
  const resolveRgb = (e: RawEntity, effLayer: string, blockRgb: number | null): number => {
    const ci = e.colorIndex
    if (ci === 0) return blockRgb ?? layerRgb(effLayer)
    if (typeof ci === 'number' && ci >= 1 && ci <= 255) return aciToRgb(ci)
    return layerRgb(effLayer)
  }

  const polylineWithBulge = (b: Bucket, verts: RawEntity[], closed: boolean, m: Mat, rgb: number): void => {
    const n = verts.length
    if (n < 2) return
    const last = closed ? n : n - 1
    for (let i = 0; i < last; i++) {
      const v1 = verts[i]!
      const v2 = verts[(i + 1) % n]!
      const bulge = typeof v1.bulge === 'number' ? v1.bulge : 0
      if (bulge === 0) {
        const [x1, y1] = apply(m, v1.x, v1.y)
        const [x2, y2] = apply(m, v2.x, v2.y)
        seg(b, x1, y1, x2, y2, rgb)
      } else {
        const theta = 4 * Math.atan(bulge)
        const dx = v2.x - v1.x
        const dy = v2.y - v1.y
        const d = Math.hypot(dx, dy)
        if (d < 1e-12) continue
        const r = d / (2 * Math.sin(Math.abs(theta) / 2))
        const mx = (v1.x + v2.x) / 2
        const my = (v1.y + v2.y) / 2
        const h = Math.sqrt(Math.max(0, r * r - (d / 2) * (d / 2))) * Math.sign(bulge) * (Math.abs(theta) > Math.PI ? -1 : 1)
        const cx = mx - (dy / d) * h
        const cy = my + (dx / d) * h
        const a1 = Math.atan2(v1.y - cy, v1.x - cx)
        const steps = Math.max(4, Math.ceil(Math.abs(theta) / (Math.PI / 36)))
        let [px, py] = apply(m, v1.x, v1.y)
        for (let s = 1; s <= steps; s++) {
          const a = a1 + (theta * s) / steps
          const [qx, qy] = apply(m, cx + r * Math.cos(a), cy + r * Math.sin(a))
          seg(b, px, py, qx, qy, rgb)
          px = qx
          py = qy
        }
      }
    }
  }

  const arcSegs = (b: Bucket, cx: number, cy: number, r: number, a1: number, a2: number, m: Mat, rgb: number): void => {
    let sweep = a2 - a1
    if (sweep <= 0) sweep += Math.PI * 2
    const steps = Math.max(8, Math.ceil(sweep / (Math.PI / 36)))
    let [px, py] = apply(m, cx + r * Math.cos(a1), cy + r * Math.sin(a1))
    for (let s = 1; s <= steps; s++) {
      const a = a1 + (sweep * s) / steps
      const [qx, qy] = apply(m, cx + r * Math.cos(a), cy + r * Math.sin(a))
      seg(b, px, py, qx, qy, rgb)
      px = qx
      py = qy
    }
  }

  /** Uniform B-spline de Boor sampling, or fit points when present. */
  const splinePoints = (e: RawEntity): Array<[number, number]> => {
    const fit: RawEntity[] | undefined = e.fitPoints
    if (fit !== undefined && fit.length >= 2) return fit.map(p => [p.x, p.y])
    const cps: RawEntity[] | undefined = e.controlPoints
    if (cps === undefined || cps.length < 2) return []
    const k: number = e.degreeOfSplineCurve ?? 3
    const knots: number[] = e.knotValues ?? []
    if (knots.length < cps.length + k + 1) return cps.map(p => [p.x, p.y])
    const n = cps.length - 1
    const tMin = knots[k]!
    const tMax = knots[n + 1]!
    const out: Array<[number, number]> = []
    const N = Math.max(16, cps.length * 6)
    for (let i = 0; i <= N; i++) {
      const t = tMin + ((tMax - tMin) * i) / N
      let span = k
      while (span < n && knots[span + 1]! <= t) span++
      const d: Array<[number, number]> = []
      for (let j = 0; j <= k; j++) {
        const p = cps[span - k + j]!
        d.push([p.x, p.y])
      }
      for (let rLev = 1; rLev <= k; rLev++) {
        for (let j = k; j >= rLev; j--) {
          const i2 = span - k + j
          const denom = knots[i2 + k - rLev + 1]! - knots[i2]!
          const alpha = denom === 0 ? 0 : (t - knots[i2]!) / denom
          const prev = d[j - 1]!
          const curr = d[j]!
          d[j] = [(1 - alpha) * prev[0] + alpha * curr[0], (1 - alpha) * prev[1] + alpha * curr[1]]
        }
      }
      out.push(d[k]!)
    }
    return out
  }

  /** The number a DIMENSION displays: its override text, or the first numeric text in its anonymous block. */
  const dimensionShown = (e: RawEntity): number | null => {
    const override = cleanDxfText(typeof e.text === 'string' ? e.text : '')
    if (override !== '' && override !== '<>' && NUMERIC_TEXT.test(override)) return Number(override)
    const block = typeof e.block === 'string' ? dxf.blocks?.[e.block] : undefined
    for (const inner of (block?.entities ?? []) as RawEntity[]) {
      if (inner.type !== 'TEXT' && inner.type !== 'MTEXT') continue
      const value = cleanDxfText(inner.text)
      if (NUMERIC_TEXT.test(value)) return Number(value)
    }
    return null
  }

  const walk = (
    entities: RawEntity[], m: Mat, effLayerFromHost: string | null, blockRgb: number | null, depth: number,
    topHandle: string | null, blockName: string | null,
  ): void => {
    if (depth > 8) return
    for (const e of entities) {
      if (e.inPaperSpace === true) { skip('paperspace'); continue }
      const effLayer: string = e.layer === '0' && effLayerFromHost !== null ? effLayerFromHost : (e.layer ?? '0')
      const rgb = resolveRgb(e, effLayer, blockRgb)
      const handle: string = topHandle ?? (typeof e.handle === 'string' ? e.handle : '')
      const b = bucket(effLayer)
      entityCount++
      switch (e.type) {
        case 'LINE': {
          const v: RawEntity[] | undefined = e.vertices
          if (v !== undefined && v.length >= 2) {
            const [x1, y1] = apply(m, v[0]!.x, v[0]!.y)
            const [x2, y2] = apply(m, v[1]!.x, v[1]!.y)
            seg(b, x1, y1, x2, y2, rgb)
          }
          break
        }
        case 'LWPOLYLINE':
        case 'POLYLINE': {
          const closed = e.shape === true || e.closed === true
          const verts: RawEntity[] | undefined = e.vertices
          if (verts !== undefined && verts.length > 0) {
            polylineWithBulge(b, verts, closed, m, rgb)
            if (closed && verts.length >= 3 && polys.length < 30_000) {
              const flat: number[] = []
              for (const v of verts) {
                const [wx, wy] = apply(m, v.x, v.y)
                flat.push(wx, wy)
              }
              polys.push({ pts: flat, layer: effLayer, handle })
            }
          }
          break
        }
        case 'ARC':
          // dxf-parser already converts ARC angles to radians.
          arcSegs(b, e.center.x, e.center.y, e.radius, e.startAngle, e.endAngle, m, rgb)
          break
        case 'CIRCLE':
          arcSegs(b, e.center.x, e.center.y, e.radius, 0, Math.PI * 2, m, rgb)
          break
        case 'ELLIPSE': {
          const c = e.center
          const mj = e.majorAxisEndPoint
          const rx = Math.hypot(mj.x, mj.y)
          const ry = rx * e.axisRatio
          const rot = Math.atan2(mj.y, mj.x)
          const a1: number = e.startAngle ?? 0
          const a2: number = e.endAngle ?? Math.PI * 2
          let sweep = a2 - a1
          if (sweep <= 0) sweep += Math.PI * 2
          const steps = Math.max(16, Math.ceil(sweep / (Math.PI / 36)))
          const pt = (a: number): [number, number] => {
            const ex = rx * Math.cos(a)
            const ey = ry * Math.sin(a)
            return apply(m, c.x + ex * Math.cos(rot) - ey * Math.sin(rot), c.y + ex * Math.sin(rot) + ey * Math.cos(rot))
          }
          let [px, py] = pt(a1)
          for (let s = 1; s <= steps; s++) {
            const [qx, qy] = pt(a1 + (sweep * s) / steps)
            seg(b, px, py, qx, qy, rgb)
            px = qx
            py = qy
          }
          break
        }
        case 'SPLINE': {
          const pts = splinePoints(e)
          for (let i = 0; i + 1 < pts.length; i++) {
            const [x1, y1] = apply(m, pts[i]![0], pts[i]![1])
            const [x2, y2] = apply(m, pts[i + 1]![0], pts[i + 1]![1])
            seg(b, x1, y1, x2, y2, rgb)
          }
          break
        }
        case 'SOLID':
        case '3DFACE': {
          const v: RawEntity[] | undefined = e.points ?? e.corners ?? e.vertices
          if (v !== undefined && v.length >= 3) {
            const order = v.length === 4 ? [0, 1, 2, 3, 0] : [0, 1, 2, 0]
            for (let i = 0; i + 1 < order.length; i++) {
              const p = v[order[i]!]
              const q = v[order[i + 1]!]
              if (p === undefined || q === undefined) continue
              const [x1, y1] = apply(m, p.x, p.y)
              const [x2, y2] = apply(m, q.x, q.y)
              seg(b, x1, y1, x2, y2, rgb)
            }
          }
          break
        }
        case 'INSERT': {
          const name: string = e.name ?? '?'
          const [ix, iy] = apply(m, e.position?.x ?? 0, e.position?.y ?? 0)
          const rot = ((e.rotation ?? 0) * Math.PI) / 180
          if (inserts.length < 500_000) {
            inserts.push({ name, x: ix, y: iy, layer: effLayer, handle, depth, parent: blockName, rot: rot + Math.atan2(m[1], m[0]) })
          }
          const block = dxf.blocks?.[name]
          if (block?.entities === undefined) { skip(`INSERT?${name}`); break }
          const bp = block.position ?? { x: 0, y: 0 }
          const sx: number = e.xScale ?? 1
          const sy: number = e.yScale ?? 1
          const cos = Math.cos(rot)
          const sin = Math.sin(rot)
          const local: Mat = mul(
            [cos * sx, sin * sx, -sin * sy, cos * sy, e.position?.x ?? 0, e.position?.y ?? 0],
            [1, 0, 0, 1, -bp.x, -bp.y],
          )
          walk(block.entities, mul(m, local), effLayer, rgb, depth + 1, handle, name)
          break
        }
        case 'DIMENSION': {
          if (depth === 0 && typeof e.actualMeasurement === 'number' && dims.length < 2000) {
            const shown = dimensionShown(e)
            const at = e.middleOfText ?? e.anchorPoint
            if (shown !== null && at !== undefined) {
              const [dx, dy] = apply(m, at.x, at.y)
              dims.push({ measured: e.actualMeasurement, shown, x: dx, y: dy, handle })
            }
          }
          const block = typeof e.block === 'string' ? dxf.blocks?.[e.block] : undefined
          if (block?.entities !== undefined) walk(block.entities, m, effLayer, rgb, depth + 1, handle, e.block)
          else skip('DIMENSION')
          break
        }
        case 'TEXT':
        case 'MTEXT':
        case 'ATTRIB': {
          const p = e.startPoint ?? e.position
          const text = cleanDxfText(e.text)
          if (p !== undefined && text !== '') {
            const [x, y] = apply(m, p.x, p.y)
            const scl = Math.hypot(m[0], m[1]) || 1
            const mrot = Math.atan2(m[1], m[0])
            texts.push({
              x,
              y,
              h: (e.textHeight ?? e.height ?? 2.5) * scl,
              rot: (((e.rotation ?? 0) * Math.PI) / 180) + mrot,
              str: text,
              layer: effLayer,
              rgb,
              handle,
              block: blockName,
            })
          }
          break
        }
        default:
          // ATTDEF (invisible definitions), POINT, SEQEND, VIEWPORT, proxy entities, and any other type are counted only.
          skip(typeof e.type === 'string' ? e.type : '?')
      }
    }
  }

  walk(dxf.entities ?? [], IDENT, null, null, 0, null, null)

  const layers: LayerGeom[] = []
  let segCount = 0
  for (const [name, b] of buckets) {
    if (b.pos.length === 0) continue
    const sc = b.pos.length / 6
    segCount += sc
    layers.push({ name, positions: new Float32Array(b.pos), colors: new Float32Array(b.col), segCount: sc })
  }
  layers.sort((a, b2) => a.name.localeCompare(b2.name, 'zh'))

  for (const t of texts) {
    if (t.x < minX) minX = t.x
    if (t.x > maxX) maxX = t.x
    if (t.y < minY) minY = t.y
    if (t.y > maxY) maxY = t.y
  }
  if (!Number.isFinite(minX)) { minX = 0; minY = 0; maxX = 1; maxY = 1 }
  return {
    layers,
    hatches,
    texts,
    inserts,
    header,
    polys,
    dims,
    layerTable,
    bbox: { minX, minY, maxX, maxY },
    stats: { entityCount, segCount, skipped, parseMs, buildMs: performance.now() - t0 },
  }
}
