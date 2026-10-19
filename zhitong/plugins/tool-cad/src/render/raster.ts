/**
 * Headless rasterization of a scene region with `@napi-rs/canvas` (Skia).
 *
 * World → pixel: `px = (x − rect.x1) · s`, `py = (rect.y2 − y) · s`, with `s`
 * pixels per drawing unit (Y flips because world Y points up). The background
 * is white; near-white entity colors become dark grey and other light colors
 * are darkened so they stay visible. Segments and fill triangles outside the
 * rectangle are culled.
 *
 * Text modes: `draw` strokes SHX glyphs when the SHX fonts cover the whole
 * text and otherwise fills it with the fallback font; `boxes` draws each text
 * as an empty box of its estimated extent; `ids` adds a small number per box
 * that maps to a text id; `none` skips texts. Texts smaller than the drop size
 * are not drawn. Linetypes, lineweights, and text alignment are not applied.
 * @module @zhitong/tool-cad/render/raster
 */
import { createCanvas, GlobalFonts } from '@napi-rs/canvas'
import type { SKRSContext2D } from '@napi-rs/canvas'
import type { Rect } from '../core/geometry.ts'
import type { BuiltScene } from '../core/sceneBuilder.ts'
import type { ShxTextEngine } from '../core/shxText.ts'
import { estimateWidth } from '../core/textQuery.ts'

/** How texts are drawn. */
export type TextMode = 'draw' | 'boxes' | 'ids' | 'none'

/** Grid overlay: `cols` × `rows` equal cells over `rect`, columns lettered A… left to right, rows numbered 1… top to bottom. */
export interface GridSpec {
  rect: Rect
  cols: number
  rows: number
}

/** One render job. */
export interface RenderJob {
  scene: BuiltScene
  /** World rectangle mapped onto the whole image. */
  rect: Rect
  /** Pixels per drawing unit. */
  scale: number
  /** Layers to draw; null draws every layer not in `hidden`. */
  only: ReadonlySet<string> | null
  hidden: ReadonlySet<string>
  textMode: TextMode
  grid: GridSpec | null
  /** Rectangles outlined in red (for example a zoom target inside an overview). */
  highlights: readonly Rect[]
  dropTextPx: number
  maxLabels: number
  shx: ShxTextEngine
  fontFamily: string
}

/** Render output. */
export interface RenderResult {
  png: Buffer
  width: number
  height: number
  stats: {
    segments: number
    triangles: number
    textsShx: number
    textsFont: number
    textsBoxed: number
    /** Texts skipped because they would be smaller than the drop size. */
    textsDropped: number
  }
  /** Numbered boxes (`ids` mode): number on the image → scene text index. */
  labels: Array<{ n: number; textId: number }>
  /** Median drawn text height in pixels, or null when no text was in view. */
  medianTextPx: number | null
}

/**
 * Register a font file under a family name once per process.
 * @param path - font file.
 * @param family - family alias.
 * @throws when Skia cannot load the file.
 */
export function registerFont(path: string, family: string): void {
  if (GlobalFonts.has(family)) return
  const key = GlobalFonts.registerFromPath(path, family)
  if (key === null) throw new Error(`tool-cad: 无法加载字体 ${path}`)
}

function cssColor(r: number, g: number, b: number): string {
  if (r > 0.85 && g > 0.85 && b > 0.85) return '#202020'
  const lum = 0.299 * r + 0.587 * g + 0.114 * b
  const k = lum > 0.55 ? 0.55 / lum : 1
  const c = (v: number): string => Math.round(Math.min(1, v * k) * 255).toString(16).padStart(2, '0')
  return `#${c(r)}${c(g)}${c(b)}`
}

function rgbColor(rgb: number): string {
  return cssColor(((rgb >> 16) & 255) / 255, ((rgb >> 8) & 255) / 255, (rgb & 255) / 255)
}

/**
 * Column letters for a grid index (A … Z).
 * @param i - zero-based column.
 * @returns the letter.
 */
export function gridColumnName(i: number): string {
  return String.fromCharCode(65 + i)
}

/**
 * Render one region to PNG.
 * @param job - scene, region, scale, filters, text mode, and overlays.
 * @returns PNG bytes, size, statistics, and the label table.
 */
export function renderRegion(job: RenderJob): RenderResult {
  const { rect, scale: s } = job
  const width = Math.max(1, Math.round((rect.x2 - rect.x1) * s))
  const height = Math.max(1, Math.round((rect.y2 - rect.y1) * s))
  const canvas = createCanvas(width, height)
  const ctx = canvas.getContext('2d')
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)
  const px = (x: number): number => (x - rect.x1) * s
  const py = (y: number): number => (rect.y2 - y) * s
  const visible = (layer: string): boolean => (job.only !== null ? job.only.has(layer) : !job.hidden.has(layer))

  let triangles = 0
  ctx.globalAlpha = 0.25
  for (const h of job.scene.hatches) {
    if (!visible(h.name)) continue
    const p = h.positions
    const c = h.colors
    for (let i = 0; i + 8 < p.length; i += 9) {
      const xs = [p[i]!, p[i + 3]!, p[i + 6]!]
      const ys = [p[i + 1]!, p[i + 4]!, p[i + 7]!]
      if (Math.max(...xs) < rect.x1 || Math.min(...xs) > rect.x2 || Math.max(...ys) < rect.y1 || Math.min(...ys) > rect.y2) continue
      ctx.fillStyle = cssColor(c[i]!, c[i + 1]!, c[i + 2]!)
      ctx.beginPath()
      ctx.moveTo(px(xs[0]!), py(ys[0]!))
      ctx.lineTo(px(xs[1]!), py(ys[1]!))
      ctx.lineTo(px(xs[2]!), py(ys[2]!))
      ctx.closePath()
      ctx.fill()
      triangles++
    }
  }
  ctx.globalAlpha = 1

  const byColor = new Map<string, number[]>()
  let segments = 0
  for (const l of job.scene.layers) {
    if (!visible(l.name)) continue
    const p = l.positions
    const c = l.colors
    for (let i = 0; i + 5 < p.length; i += 6) {
      const x1 = p[i]!
      const y1 = p[i + 1]!
      const x2 = p[i + 3]!
      const y2 = p[i + 4]!
      if ((x1 < rect.x1 && x2 < rect.x1) || (x1 > rect.x2 && x2 > rect.x2) || (y1 < rect.y1 && y2 < rect.y1) || (y1 > rect.y2 && y2 > rect.y2)) continue
      const key = cssColor(c[i]!, c[i + 1]!, c[i + 2]!)
      let list = byColor.get(key)
      if (list === undefined) { list = []; byColor.set(key, list) }
      list.push(px(x1), py(y1), px(x2), py(y2))
      segments++
    }
  }
  ctx.lineWidth = 1
  ctx.lineCap = 'round'
  for (const [color, list] of byColor) strokeSegments(ctx, color, list)

  const stats = { segments, triangles, textsShx: 0, textsFont: 0, textsBoxed: 0, textsDropped: 0 }
  const labels: RenderResult['labels'] = []
  const heights: number[] = []
  if (job.textMode !== 'none') {
    const inView: number[] = []
    const texts = job.scene.texts
    for (let i = 0; i < texts.length; i++) {
      const t = texts[i]!
      if (!visible(t.layer)) continue
      const w = estimateWidth(t.str, t.h)
      const reach = Math.max(w, t.h)
      if (t.x + reach < rect.x1 || t.x - reach > rect.x2 || t.y + reach < rect.y1 || t.y - reach > rect.y2) continue
      if (t.h * s < job.dropTextPx) { stats.textsDropped++; continue }
      inView.push(i)
      heights.push(t.h * s)
    }
    inView.sort((a, b) => texts[b]!.y - texts[a]!.y || texts[a]!.x - texts[b]!.x)
    const shxByColor = new Map<string, number[]>()
    for (const i of inView) {
      const t = texts[i]!
      const color = rgbColor(t.rgb)
      if (job.textMode === 'draw') {
        const segs = job.shx.textSegments(t)
        if (segs !== null) {
          let list = shxByColor.get(color)
          if (list === undefined) { list = []; shxByColor.set(color, list) }
          for (let k = 0; k + 3 < segs.length; k += 4) list.push(px(segs[k]!), py(segs[k + 1]!), px(segs[k + 2]!), py(segs[k + 3]!))
          stats.textsShx++
        } else {
          ctx.save()
          ctx.translate(px(t.x), py(t.y))
          ctx.rotate(-t.rot)
          ctx.fillStyle = color
          ctx.font = `${Math.max(1, t.h * s).toFixed(1)}px "${job.fontFamily}"`
          ctx.textBaseline = 'alphabetic'
          ctx.fillText(t.str, 0, 0)
          ctx.restore()
          stats.textsFont++
        }
        continue
      }
      const w = estimateWidth(t.str, t.h) * s
      const h = t.h * s
      ctx.save()
      ctx.translate(px(t.x), py(t.y))
      ctx.rotate(-t.rot)
      ctx.strokeStyle = '#3b7dd8'
      ctx.lineWidth = 1
      ctx.strokeRect(0, -h, w, h)
      ctx.restore()
      stats.textsBoxed++
      if (job.textMode === 'ids' && labels.length < job.maxLabels) {
        const n = labels.length + 1
        labels.push({ n, textId: i })
        drawTag(ctx, String(n), px(t.x), py(t.y) - h, '#c0392b', job.fontFamily)
      }
    }
    for (const [color, list] of shxByColor) strokeSegments(ctx, color, list)
  }

  for (const r of job.highlights) {
    ctx.strokeStyle = '#e53935'
    ctx.lineWidth = 2
    ctx.strokeRect(px(r.x1), py(r.y2), (r.x2 - r.x1) * s, (r.y2 - r.y1) * s)
  }

  if (job.grid !== null) drawGrid(ctx, job.grid, px, py, s, job.fontFamily)

  heights.sort((a, b) => a - b)
  return {
    png: canvas.toBuffer('image/png'),
    width,
    height,
    stats,
    labels,
    medianTextPx: heights.length > 0 ? heights[Math.floor(heights.length / 2)]! : null,
  }
}

function strokeSegments(ctx: SKRSContext2D, color: string, list: readonly number[]): void {
  ctx.strokeStyle = color
  ctx.beginPath()
  for (let k = 0; k + 3 < list.length; k += 4) {
    ctx.moveTo(list[k]!, list[k + 1]!)
    ctx.lineTo(list[k + 2]!, list[k + 3]!)
  }
  ctx.stroke()
}

function drawTag(ctx: SKRSContext2D, text: string, x: number, y: number, color: string, family: string): void {
  ctx.font = `bold 12px "${family}"`
  const w = ctx.measureText(text).width + 4
  ctx.fillStyle = 'rgba(255,255,255,0.85)'
  ctx.fillRect(x, y - 13, w, 13)
  ctx.fillStyle = color
  ctx.textBaseline = 'alphabetic'
  ctx.fillText(text, x + 2, y - 2)
}

function drawGrid(ctx: SKRSContext2D, grid: GridSpec, px: (x: number) => number, py: (y: number) => number, s: number, family: string): void {
  const { rect, cols, rows } = grid
  const cw = (rect.x2 - rect.x1) / cols
  const ch = (rect.y2 - rect.y1) / rows
  ctx.save()
  ctx.strokeStyle = 'rgba(30,136,229,0.55)'
  ctx.lineWidth = 1
  ctx.setLineDash([6, 4])
  ctx.beginPath()
  for (let c = 0; c <= cols; c++) {
    const x = px(rect.x1 + c * cw)
    ctx.moveTo(x, py(rect.y2))
    ctx.lineTo(x, py(rect.y1))
  }
  for (let r = 0; r <= rows; r++) {
    const y = py(rect.y2 - r * ch)
    ctx.moveTo(px(rect.x1), y)
    ctx.lineTo(px(rect.x2), y)
  }
  ctx.stroke()
  ctx.setLineDash([])
  const size = Math.max(12, Math.min(20, Math.min(cw, ch) * s * 0.12))
  ctx.font = `bold ${size.toFixed(0)}px "${family}"`
  ctx.fillStyle = '#1565c0'
  ctx.textBaseline = 'alphabetic'
  for (let c = 0; c < cols; c++) {
    const name = gridColumnName(c)
    const x = px(rect.x1 + (c + 0.5) * cw) - size * 0.3
    ctx.fillText(name, x, Math.max(size, py(rect.y2) - 4))
    ctx.fillText(name, x, py(rect.y1) + size + 2)
  }
  for (let r = 0; r < rows; r++) {
    const y = py(rect.y2 - (r + 0.5) * ch) + size * 0.35
    const label = String(r + 1)
    ctx.fillText(label, Math.max(2, px(rect.x1) - size * 1.2), y)
    ctx.fillText(label, px(rect.x2) + 4, y)
  }
  ctx.restore()
}
