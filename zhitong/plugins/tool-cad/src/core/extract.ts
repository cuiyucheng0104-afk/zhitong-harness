/**
 * Recognition and export helpers ("vector first"):
 * - text extraction with coordinates to CSV;
 * - block counting by INSERT name, optionally grouped by frame (`vector_rule`);
 * - table extraction: line clustering rebuilds the grid, texts fall into cells;
 * - block counts to the unified takeoff schema (`统一算量产物schema_v1`).
 *
 * Source: tiangong-cad-viewer `src/extract.ts`. Local changes: the browser-only
 * `downloadFile` is removed; frames are any labelled rectangle; strict typing.
 * @module @zhitong/tool-cad/core/extract
 */
import { pointFrame } from './frames.ts'
import type { BuiltScene, TextItem } from './sceneBuilder.ts'

/** Unit metadata every export carries. */
export interface UnitMeta {
  /** `mm`, `cm`, `m`, or `in`. */
  unit: string
  insunits: number | null
  confirmed: boolean
  confirmedAt: string | null
  /** `$INSUNITS`, `人工确认`, or `尺寸比对`. */
  method: string
}

/** A rectangle with a display label, used to group results by frame. */
export interface LabelledRect {
  label: string
  x1: number
  y1: number
  x2: number
  y2: number
}

/**
 * CSV comment line carrying unit metadata.
 * @param u - unit metadata.
 * @returns the `# unit=…` line.
 */
export const unitCsvHeader = (u: UnitMeta): string =>
  `# unit=${u.unit} insunits=${u.insunits ?? 'null'} confirmed=${u.confirmed} method=${u.method}`

/**
 * Quote one CSV field when needed.
 * @param s - field value.
 * @returns the escaped field.
 */
export const csvEsc = (s: string): string => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s)

/**
 * Texts to CSV: a unit comment line, then `文字,X,Y,字高,图层,图框`.
 * @param texts - texts to export.
 * @param unit - unit metadata.
 * @param frames - frames used to label each row.
 * @returns CSV text.
 */
export function textsToCsv(texts: readonly TextItem[], unit: UnitMeta, frames: readonly LabelledRect[] = []): string {
  const rows = [unitCsvHeader(unit), '文字,X,Y,字高,图层,图框']
  for (const t of texts) {
    const f = frames.length > 0 ? pointFrame(frames, t.x, t.y) : null
    rows.push(`${csvEsc(t.str)},${t.x.toFixed(1)},${t.y.toFixed(1)},${t.h.toFixed(1)},${csvEsc(t.layer)},${f !== null ? csvEsc(f.label) : ''}`)
  }
  return rows.join('\n')
}

/** Count of one block name. */
export interface BlockCount {
  name: string
  count: number
  layers: string[]
  /** Count per frame label; `框外` collects references outside every frame. Empty without frames. */
  perFrame: Record<string, number>
}

/**
 * Count INSERT references by block name. Anonymous blocks (`*…`) are skipped.
 * @param scene - built scene.
 * @param frames - frames for per-frame grouping.
 * @returns counts sorted descending.
 */
export function countBlocks(scene: Pick<BuiltScene, 'inserts'>, frames: readonly LabelledRect[] = []): BlockCount[] {
  const map = new Map<string, { count: number; layers: Set<string>; perFrame: Record<string, number> }>()
  for (const ins of scene.inserts) {
    if (ins.name.startsWith('*')) continue
    let e = map.get(ins.name)
    if (e === undefined) { e = { count: 0, layers: new Set(), perFrame: {} }; map.set(ins.name, e) }
    e.count++
    e.layers.add(ins.layer)
    if (frames.length > 0) {
      const f = pointFrame(frames, ins.x, ins.y)
      const key = f !== null ? f.label : '框外'
      e.perFrame[key] = (e.perFrame[key] ?? 0) + 1
    }
  }
  return [...map.entries()]
    .map(([name, v]) => ({ name, count: v.count, layers: [...v.layers], perFrame: v.perFrame }))
    .sort((a, b) => b.count - a.count)
}

/**
 * Controlled vocabulary (substring match, first hit wins). Block names outside
 * it are not exported and stay for manual review.
 */
const CATEGORY_KEYWORDS: ReadonlyArray<readonly [string, string]> = [
  ['门', '门'], ['窗', '窗'], ['柱', '柱'], ['梁', '梁'], ['墙', '墙'],
  ['板', '板'], ['桩', '基础'], ['楼梯', '楼梯'], ['砌体', '砌体'], ['钢筋', '钢筋'],
]

/** One `RecognitionItem` of the unified takeoff schema. */
export interface RecognitionItem {
  sourcePath: 'cad'
  sourceRef: { file: string; location: string; rawExcerpt: string }
  componentCategory: string
  detection: { detector: 'vector_rule'; confidence: number; layer: string; bbox: null; polyline: null }
  rawMeasures: { lengthMm: null; areaMm2: null; heightMm: null; count: number }
  params: { frameId?: string }
  gbCodeHint: null
}

/** Unified takeoff schema envelope. */
export interface RecognitionEnvelope {
  meta: UnitMeta & { file: string; generatedBy: string; schemaBody: string }
  items: RecognitionItem[]
}

/**
 * Block counts to the unified takeoff schema; one item per frame when frames were used.
 * @param counts - block counts.
 * @param file - source file name.
 * @param unit - unit metadata.
 * @returns the envelope.
 */
export function blocksToSchema(counts: readonly BlockCount[], file: string, unit: UnitMeta): RecognitionEnvelope {
  const items: RecognitionItem[] = []
  const item = (b: BlockCount, category: string, location: string, count: number, frameId?: string): RecognitionItem => ({
    sourcePath: 'cad',
    sourceRef: { file, location, rawExcerpt: b.name },
    componentCategory: category,
    detection: { detector: 'vector_rule', confidence: 1.0, layer: b.layers[0] ?? '0', bbox: null, polyline: null },
    rawMeasures: { lengthMm: null, areaMm2: null, heightMm: null, count },
    params: frameId !== undefined ? { frameId } : {},
    gbCodeHint: null,
  })
  for (const b of counts) {
    const hit = CATEGORY_KEYWORDS.find(([kw]) => b.name.includes(kw))
    if (hit === undefined) continue
    const frameKeys = Object.keys(b.perFrame)
    if (frameKeys.length > 1 || (frameKeys.length === 1 && frameKeys[0] !== '框外')) {
      for (const [frameLabel, n] of Object.entries(b.perFrame)) {
        items.push(item(b, hit[1], `block:${b.name} frame:${frameLabel}`, n, frameLabel))
      }
    } else {
      items.push(item(b, hit[1], `block:${b.name}`, b.count))
    }
  }
  return {
    meta: { file, ...unit, generatedBy: '@zhitong/tool-cad', schemaBody: 'items = RecognitionItem[] (统一算量产物schema_v1)' },
    items,
  }
}

/** Table rebuilt from line grid and texts. */
export interface TableResult {
  rows: string[][]
  nRows: number
  nCols: number
  hLines: number
  vLines: number
}

/**
 * Rebuild a table inside a rectangle: collect horizontal and vertical segments,
 * cluster their coordinates, keep the dominant span group (so one unrelated
 * long line cannot lift the baseline), then drop texts into cells (several
 * fragments in one cell join with a space). Only `scene.layers` segments are
 * read; tables drawn with SOLID or HATCH lines are not found.
 * @param scene - built scene.
 * @param rect - search rectangle in world coordinates (corners in any order).
 * @returns the table, or null when no grid was found.
 */
export function extractTable(scene: Pick<BuiltScene, 'layers' | 'texts'>, rect: { x1: number; y1: number; x2: number; y2: number }): TableResult | null {
  const minX = Math.min(rect.x1, rect.x2)
  const maxX = Math.max(rect.x1, rect.x2)
  const minY = Math.min(rect.y1, rect.y2)
  const maxY = Math.max(rect.y1, rect.y2)
  const W = maxX - minX
  const H = maxY - minY
  if (W <= 0 || H <= 0) return null
  const axisTol = Math.max(W, H) * 0.002

  const hSegs: Array<{ y: number; x1: number; x2: number }> = []
  const vSegs: Array<{ x: number; y1: number; y2: number }> = []
  for (const l of scene.layers) {
    const p = l.positions
    for (let i = 0; i + 5 < p.length; i += 6) {
      const x1 = p[i]!
      const y1 = p[i + 1]!
      const x2 = p[i + 3]!
      const y2 = p[i + 4]!
      if (x1 < minX - axisTol || x1 > maxX + axisTol || x2 < minX - axisTol || x2 > maxX + axisTol) continue
      if (y1 < minY - axisTol || y1 > maxY + axisTol || y2 < minY - axisTol || y2 > maxY + axisTol) continue
      if (Math.abs(y1 - y2) < axisTol && Math.abs(x2 - x1) > axisTol * 8) hSegs.push({ y: (y1 + y2) / 2, x1: Math.min(x1, x2), x2: Math.max(x1, x2) })
      else if (Math.abs(x1 - x2) < axisTol && Math.abs(y2 - y1) > axisTol * 8) vSegs.push({ x: (x1 + x2) / 2, y1: Math.min(y1, y2), y2: Math.max(y1, y2) })
    }
  }
  if (hSegs.length < 2 || vSegs.length < 2) return null

  type Line = { v: number; span: number }
  const clusterLines = (vals: Line[], tol: number): Line[] => {
    const sorted = [...vals].sort((a, b) => a.v - b.v)
    const out: Line[] = []
    let group: Line[] = []
    const flush = (): void => {
      if (group.length === 0) return
      out.push({ v: group.reduce((s, g) => s + g.v, 0) / group.length, span: Math.max(...group.map(g => g.span)) })
      group = []
    }
    for (const g of sorted) {
      const last = group[group.length - 1]
      if (last !== undefined && g.v - last.v > tol) flush()
      group.push(g)
    }
    flush()
    return out
  }
  const adaptive = (cs: Line[]): number[] => {
    if (cs.length === 0) return []
    let best: Line[] = []
    const total = (g: Line[]): number => g.reduce((s, x) => s + x.span, 0)
    for (const c of cs) {
      const group = cs.filter(o => o.span >= c.span * 0.75 && o.span <= c.span * 1.33)
      if (group.length > best.length || (group.length === best.length && total(group) > total(best))) best = group
    }
    return best.map(c => c.v)
  }
  const tol = Math.max(W, H) * 0.004
  const ys = adaptive(clusterLines(hSegs.map(s => ({ v: s.y, span: s.x2 - s.x1 })), tol)).reverse()
  const xs = adaptive(clusterLines(vSegs.map(s => ({ v: s.x, span: s.y2 - s.y1 })), tol))
  if (ys.length < 2 || xs.length < 2) return null

  const nRows = ys.length - 1
  const nCols = xs.length - 1
  const cells: string[][][] = Array.from({ length: nRows }, () => Array.from({ length: nCols }, () => []))
  const within = scene.texts
    .filter(t => t.x >= minX && t.x <= maxX && t.y >= minY && t.y <= maxY)
    .sort((a, b) => b.y - a.y || a.x - b.x)
  for (const t of within) {
    let ri = -1
    let ci = -1
    for (let i = 0; i < nRows; i++) if (t.y <= ys[i]! && t.y >= ys[i + 1]!) { ri = i; break }
    for (let j = 0; j < nCols; j++) if (t.x >= xs[j]! && t.x <= xs[j + 1]!) { ci = j; break }
    if (ri >= 0 && ci >= 0) cells[ri]![ci]!.push(t.str)
  }
  const rows = cells.map(r => r.map(c => c.join(' ')))
  return { rows, nRows, nCols, hLines: ys.length, vLines: xs.length }
}

/**
 * Table to CSV.
 * @param t - table.
 * @returns CSV text.
 */
export function tableToCsv(t: TableResult): string {
  return t.rows.map(r => r.map(csvEsc).join(',')).join('\n')
}
