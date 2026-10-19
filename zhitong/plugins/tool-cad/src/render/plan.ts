/**
 * Render planning: turn a target (frame overview, grid cell, rectangle, point
 * neighbourhood, text id, or entity handle) into a world rectangle, a scale,
 * and an optional grid, and refuse regions too large for a readable image.
 *
 * - Overview (`frame` alone): the whole frame at the default size with a
 *   lettered grid (`gridLongSide` cells along the longer side, square-ish
 *   cells) and room for the grid labels.
 * - Zoom (any other target): the region fits the default size; when the
 *   median text would be smaller than `minTextPx` the scale grows until the
 *   hard size limit. A zoom region larger than `maxZoomFraction` of its frame
 *   is refused, because a near-whole-frame image at high resolution is the
 *   expensive case this tool avoids.
 * @module @zhitong/tool-cad/render/plan
 */
import type { Rect } from '../core/geometry.ts'
import { boundsOf, expandRect, normalizeRect } from '../core/geometry.ts'
import type { BuiltScene } from '../core/sceneBuilder.ts'
import { estimateWidth } from '../core/textQuery.ts'
import type { DocFrame } from '../documents.ts'
import type { GridSpec } from './raster.ts'
import { gridColumnName } from './raster.ts'

/** Target arguments (exactly one target; `cell` requires `frame`). */
export interface TargetArgs {
  frame?: string
  cell?: string
  rect?: { x1: number; y1: number; x2: number; y2: number }
  around?: { x: number; y: number; r: number }
  textId?: number
  handle?: string
}

/** Size limits. */
export interface PlanLimits {
  maxPx: number
  hardMaxPx: number
  minTextPx: number
  gridLongSide: number
  maxZoomFraction: number
}

/** A planned render. */
export interface RenderPlan {
  kind: 'overview' | 'zoom'
  /** Frame the region belongs to, when known. */
  frame: DocFrame | null
  cell: string | null
  /** Requested region (before label padding). */
  region: Rect
  /** Region actually mapped onto the image. */
  imageRect: Rect
  scale: number
  grid: GridSpec | null
  warnings: string[]
}

const LABEL_PAD_PX = 36

/**
 * Grid dimensions for a frame.
 * @param frame - frame rectangle.
 * @param longSide - cells along the longer side.
 * @returns columns and rows.
 */
export function gridFor(frame: Rect, longSide: number): { cols: number; rows: number } {
  const w = frame.x2 - frame.x1
  const h = frame.y2 - frame.y1
  if (w >= h) return { cols: longSide, rows: Math.max(1, Math.round(longSide * h / Math.max(w, 1e-9))) }
  return { cols: Math.max(1, Math.round(longSide * w / Math.max(h, 1e-9))), rows: longSide }
}

/**
 * World rectangle of one grid cell, grown by 5% on every side for overlap.
 * @param frame - frame rectangle.
 * @param cell - cell name such as `C3`.
 * @param longSide - cells along the longer side.
 * @returns the cell rectangle.
 * @throws when the cell name is malformed or outside the grid.
 */
export function cellRect(frame: Rect, cell: string, longSide: number): Rect {
  const m = /^([A-Za-z])(\d{1,2})$/.exec(cell.trim())
  const { cols, rows } = gridFor(frame, longSide)
  if (m === null) throw new Error(`格子名 ${cell} 不合法；应为字母列加数字行，如 C3`)
  const col = m[1]!.toUpperCase().charCodeAt(0) - 65
  const row = Number(m[2]) - 1
  if (col < 0 || col >= cols || row < 0 || row >= rows) {
    throw new Error(`格子 ${cell} 超出网格（列 A–${gridColumnName(cols - 1)}，行 1–${rows}）`)
  }
  const cw = (frame.x2 - frame.x1) / cols
  const ch = (frame.y2 - frame.y1) / rows
  const r = { x1: frame.x1 + col * cw, x2: frame.x1 + (col + 1) * cw, y2: frame.y2 - row * ch, y1: frame.y2 - (row + 1) * ch }
  return expandRect(r, Math.max(cw, ch) * 0.05)
}

function area(r: Rect): number {
  return Math.max(0, r.x2 - r.x1) * Math.max(0, r.y2 - r.y1)
}

function handleRegion(scene: BuiltScene, handle: string): Rect | null {
  const pts: number[] = []
  let pad = 0
  for (const t of scene.texts) {
    if (t.handle !== handle) continue
    pts.push(t.x, t.y, t.x + estimateWidth(t.str, t.h), t.y + t.h)
    pad = Math.max(pad, t.h * 4)
  }
  for (const i of scene.inserts) if (i.handle === handle) pts.push(i.x, i.y)
  for (const p of scene.polys) if (p.handle === handle) pts.push(...p.pts)
  if (pts.length === 0) return null
  const b = boundsOf(pts)
  const size = Math.max(b.x2 - b.x1, b.y2 - b.y1)
  return expandRect(b, Math.max(pad, size * 0.25, 1))
}

/**
 * Plan one render.
 * @param scene - document scene.
 * @param frames - document frames.
 * @param args - target arguments.
 * @param limits - size limits (already reflecting a per-call `max_px`).
 * @returns the plan.
 * @throws when the target is missing, ambiguous, unknown, or too large for a zoom.
 */
export function planRender(scene: BuiltScene, frames: readonly DocFrame[], args: TargetArgs, limits: PlanLimits): RenderPlan {
  const targets = [args.rect, args.around, args.textId, args.handle].filter(v => v !== undefined).length + (args.cell !== undefined ? 1 : 0)
  if (targets > 1) throw new Error('一次只能指定一个目标：frame（可加 cell）、rect、around、text_id、handle 之一')
  if (targets === 0 && args.frame === undefined) {
    throw new Error(`没有指定出图目标。整张图不出高分辨率图：先用 cad_frames 列图框，再用 frame 出单个图框的总览（可用：${frames.map(f => f.id).join('、')}）`)
  }
  const findFrame = (id: string): DocFrame => {
    const f = frames.find(x => x.id === id)
    if (f === undefined) throw new Error(`图框 ${id} 不存在；可用：${frames.map(x => x.id).join('、')}`)
    return f
  }
  const warnings: string[] = []

  if (targets === 0) {
    const frame = findFrame(args.frame!)
    const { cols, rows } = gridFor(frame, limits.gridLongSide)
    const long = Math.max(frame.x2 - frame.x1, frame.y2 - frame.y1, 1e-9)
    const scale = (limits.maxPx - 2 * LABEL_PAD_PX) / long
    return {
      kind: 'overview',
      frame,
      cell: null,
      region: { x1: frame.x1, y1: frame.y1, x2: frame.x2, y2: frame.y2 },
      imageRect: expandRect(frame, LABEL_PAD_PX / scale),
      scale,
      grid: { rect: { x1: frame.x1, y1: frame.y1, x2: frame.x2, y2: frame.y2 }, cols, rows },
      warnings,
    }
  }

  let region: Rect
  let frame: DocFrame | null = args.frame !== undefined ? findFrame(args.frame) : null
  if (args.cell !== undefined) {
    if (frame === null) throw new Error('cell 需要同时给出 frame（格子编号属于某个图框的总览网格）')
    region = cellRect(frame, args.cell, limits.gridLongSide)
  } else if (args.rect !== undefined) {
    region = normalizeRect(args.rect)
  } else if (args.around !== undefined) {
    if (!(args.around.r > 0)) throw new Error('around.r 必须大于 0')
    region = { x1: args.around.x - args.around.r, y1: args.around.y - args.around.r, x2: args.around.x + args.around.r, y2: args.around.y + args.around.r }
  } else if (args.textId !== undefined) {
    const t = scene.texts[args.textId]
    if (t === undefined) throw new Error(`文字 T${args.textId} 不存在`)
    const half = Math.max(estimateWidth(t.str, t.h) * 1.5, t.h * 15)
    region = { x1: t.x - half, y1: t.y - half, x2: t.x + half, y2: t.y + half }
  } else {
    const found = handleRegion(scene, args.handle!)
    if (found === null) throw new Error(`句柄 ${args.handle} 没有对应的文字、块引用或闭合多段线`)
    region = found
  }
  if (area(region) <= 0) throw new Error('出图范围面积为 0')

  if (frame === null) {
    const cx = (region.x1 + region.x2) / 2
    const cy = (region.y1 + region.y2) / 2
    frame = frames.find(f => cx >= f.x1 && cx <= f.x2 && cy >= f.y1 && cy <= f.y2) ?? null
  }
  const base = frame ?? { x1: scene.bbox.minX, y1: scene.bbox.minY, x2: scene.bbox.maxX, y2: scene.bbox.maxY }
  const fraction = area(region) / Math.max(area(base), 1e-9)
  if (fraction > limits.maxZoomFraction) {
    throw new Error(`局部范围占${frame !== null ? `图框 ${frame.id}` : '整张图'}的 ${(fraction * 100).toFixed(0)}%，超过上限 ${(limits.maxZoomFraction * 100).toFixed(0)}%。`
      + `${frame !== null ? `先出 frame=${frame.id} 的总览，再用 cell 指定格子放大，` : ''}或把 rect/around 缩小`)
  }

  const long = Math.max(region.x2 - region.x1, region.y2 - region.y1)
  const fit = limits.maxPx / long
  const inRegion = scene.texts.filter(t => t.x >= region.x1 && t.x <= region.x2 && t.y >= region.y1 && t.y <= region.y2).map(t => t.h).sort((a, b) => a - b)
  let scale = fit
  if (inRegion.length > 0) {
    const median = inRegion[Math.floor(inRegion.length / 2)]!
    const need = limits.minTextPx / median
    if (need > fit) {
      scale = Math.min(need, limits.hardMaxPx / long)
      if (scale < need) warnings.push(`该范围内文字中位高度只能放大到约 ${(median * scale).toFixed(0)} px（目标 ${limits.minTextPx} px）；读小字请换更小的范围`)
    }
  }
  return { kind: 'zoom', frame, cell: args.cell?.toUpperCase() ?? null, region, imageRect: region, scale, grid: null, warnings }
}
