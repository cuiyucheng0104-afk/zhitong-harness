/**
 * Sheet borders and title-block heuristics.
 *
 * Sheet borders: closed axis-aligned rectangles (including those inside frame
 * blocks) whose short side equals an A0–A4 paper short side times a common
 * drawing scale, with a long/short ratio between 1.38 and 3.6 (standard and
 * lengthened sheets). Rectangles nested inside another candidate are dropped,
 * so the trimmed outer border wins over the inner border.
 *
 * Title block: within a frame (plus a margin for drawing clusters), texts are
 * matched against drawing-name endings (`平面图`, `详图` …), scale notation
 * (`1:N`), drawing-number labels (`图号`) and number patterns, and floor
 * expressions (`三层`, `2~5层`, `标准层`, `屋顶`). Labelled title-block fields
 * (`工程名称`, `比例` …) take the nearest text to the right or below.
 * Everything here is a convention-based guess; results carry confidence and the
 * source text handles.
 * @module @zhitong/tool-cad/core/sheets
 */
import type { Rect } from './geometry.ts'
import { inRect } from './geometry.ts'
import type { BuiltScene, TextItem } from './sceneBuilder.ts'
import { estimateWidth, groupLines } from './textQuery.ts'

/** Paper short and long sides in millimetres. */
const PAPER: ReadonlyArray<readonly [string, number, number]> = [
  ['A0', 841, 1189], ['A1', 594, 841], ['A2', 420, 594], ['A3', 297, 420], ['A4', 210, 297],
]

/** Drawing scales tried when matching paper sizes. */
const SCALES = [1, 2, 5, 10, 20, 25, 30, 40, 50, 60, 75, 80, 100, 120, 125, 150, 200, 250, 300, 400, 500, 600, 750, 800, 1000, 1500, 2000, 2500, 5000] as const

/** One detected sheet border. */
export interface SheetBorder extends Rect {
  paper: string
  /** Scale N of 1:N implied by the border size (paper millimetres × N = drawing millimetres). */
  scale: number
  lengthened: boolean
  handle: string
}

/**
 * Detect sheet borders among closed polygons.
 * @param scene - built scene.
 * @param mmPerUnit - millimetres per drawing unit.
 * @returns outermost matching borders, top-to-bottom then left-to-right.
 */
export function detectSheets(scene: Pick<BuiltScene, 'polys'>, mmPerUnit: number): SheetBorder[] {
  const found: SheetBorder[] = []
  for (const poly of scene.polys) {
    const pts = poly.pts
    let n = pts.length / 2
    if (n === 5 && pts[0] === pts[8] && pts[1] === pts[9]) n = 4
    if (n !== 4) continue
    const xs = [pts[0]!, pts[2]!, pts[4]!, pts[6]!]
    const ys = [pts[1]!, pts[3]!, pts[5]!, pts[7]!]
    const x1 = Math.min(...xs)
    const x2 = Math.max(...xs)
    const y1 = Math.min(...ys)
    const y2 = Math.max(...ys)
    const w = x2 - x1
    const h = y2 - y1
    if (w <= 0 || h <= 0) continue
    const tol = Math.max(w, h) * 0.002
    const axisAligned = xs.every(x => Math.abs(x - x1) < tol || Math.abs(x - x2) < tol)
      && ys.every(y => Math.abs(y - y1) < tol || Math.abs(y - y2) < tol)
    if (!axisAligned) continue
    const shortMm = Math.min(w, h) * mmPerUnit
    const longMm = Math.max(w, h) * mmPerUnit
    const ratio = longMm / shortMm
    if (ratio < 1.38 || ratio > 3.6) continue
    let match: { paper: string; scale: number; lengthened: boolean } | null = null
    for (const [paper, shortSide, longSide] of PAPER) {
      for (const scale of SCALES) {
        if (Math.abs(shortMm / (shortSide * scale) - 1) > 0.01) continue
        const longPaper = longMm / scale
        match = { paper, scale, lengthened: longPaper > longSide * 1.02 }
        break
      }
      if (match !== null) break
    }
    if (match === null) continue
    found.push({ x1, y1, x2, y2, ...match, handle: poly.handle })
  }
  const outer = found.filter(s => !found.some(o => o !== s
    && o.x1 <= s.x1 && o.y1 <= s.y1 && o.x2 >= s.x2 && o.y2 >= s.y2
    && (o.x2 - o.x1) * (o.y2 - o.y1) > (s.x2 - s.x1) * (s.y2 - s.y1)))
  const unique: SheetBorder[] = []
  for (const s of outer) {
    if (!unique.some(u => Math.abs(u.x1 - s.x1) < 1e-6 && Math.abs(u.y1 - s.y1) < 1e-6 && Math.abs(u.x2 - s.x2) < 1e-6 && Math.abs(u.y2 - s.y2) < 1e-6)) unique.push(s)
  }
  return unique.sort((a, b) => b.y2 - a.y2 || a.x1 - b.x1)
}

/** One title-block value with its source. */
export interface TitleValue {
  value: string
  /** Index of the first source text in `scene.texts`. */
  textId: number
  handle: string
}

/** Floor guess. */
export interface FloorGuess {
  /** Normalized label: `1F`, `2F~5F`, `B1`, `RF`, `标准层`, `夹层`. */
  label: string
  confidence: 'high' | 'medium' | 'low'
  from: string
}

/** Title-block reading of one frame. */
export interface TitleBlock {
  name: TitleValue | null
  number: TitleValue | null
  scale: (TitleValue & { denominator: number }) | null
  floor: FloorGuess | null
  /** Labelled fields such as `工程名称`, `日期`. */
  fields: Record<string, TitleValue>
}

/** Title-block matching options. */
export interface TitleOptions {
  /** Labels whose right/below neighbour is read as a field value. */
  fieldLabels: readonly string[]
  /** Drawing-number pattern used when no `图号` label is found. */
  numberPattern: RegExp
}

const DRAWING_NAME = /(平面图|立面图|剖面图|详图|大样图?|节点图|节点|总平面图|总图|布置图|系统图|示意图|配筋图|模板图|结构图|展开图|分格图|轴测图|做法表|设计说明|施工说明|目录)\s*$/u
const SCALE_TEXT = /1\s*[:：]\s*(\d{1,5})(?!\d)/u
const NUMBER_LABEL = /^图\s*号\s*[:：]?\s*(.*)$/u

const CN_DIGITS: Readonly<Record<string, number>> = { 零: 0, 〇: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 }

/**
 * Parse an Arabic or Chinese numeral up to 999.
 * @param s - numeral text.
 * @returns the value, or null.
 */
export function parseNumeral(s: string): number | null {
  if (/^\d+$/.test(s)) return Number(s)
  let total = 0
  let current = 0
  let seen = false
  for (const ch of s) {
    const digit = CN_DIGITS[ch]
    if (digit !== undefined) { current = digit; seen = true; continue }
    if (ch === '十') { total += (current === 0 ? 1 : current) * 10; current = 0; seen = true; continue }
    if (ch === '百') { total += (current === 0 ? 1 : current) * 100; current = 0; seen = true; continue }
    return null
  }
  return seen ? total + current : null
}

/**
 * Guess the floor from a drawing name.
 * @param name - drawing name text.
 * @returns the floor guess, or null.
 */
export function guessFloor(name: string): FloorGuess | null {
  const plan = name.includes('平面')
  const confidence = plan ? 'high' : 'medium'
  const num = '([一二三四五六七八九十百两〇\\d]+)'
  const under = new RegExp(`(?:地下|负)${num}层`, 'u').exec(name)
  if (under !== null) {
    const n = parseNumeral(under[1]!)
    if (n !== null) return { label: `B${n}`, confidence, from: under[0] }
  }
  const range = new RegExp(`${num}\\s*(?:[~～\\-—至到]|层\\s*[~～\\-—至到])\\s*${num}\\s*层`, 'u').exec(name)
  if (range !== null) {
    const a = parseNumeral(range[1]!)
    const b = parseNumeral(range[2]!)
    if (a !== null && b !== null) return { label: `${a}F~${b}F`, confidence, from: range[0] }
  }
  if (/标准层/u.test(name)) return { label: '标准层', confidence, from: '标准层' }
  if (/屋顶|屋面/u.test(name)) return { label: 'RF', confidence, from: /屋顶|屋面/u.exec(name)![0] }
  if (/首层|底层/u.test(name)) return { label: '1F', confidence, from: /首层|底层/u.exec(name)![0] }
  if (/夹层/u.test(name)) return { label: '夹层', confidence, from: '夹层' }
  const single = new RegExp(`${num}\\s*层`, 'u').exec(name)
  if (single !== null) {
    const n = parseNumeral(single[1]!)
    if (n !== null) return { label: `${n}F`, confidence, from: single[0] }
  }
  const f = /(?:^|[^A-Za-z])(\d{1,3})F(?![A-Za-z])/u.exec(name)
  if (f !== null) return { label: `${Number(f[1])}F`, confidence: 'low', from: f[0].trim() }
  return null
}

/** Nearest text to the right on the same row, or else just below, of an anchor. */
function neighbourOf(texts: readonly TextItem[], candidates: readonly number[], anchor: number): number | null {
  const a = texts[anchor]!
  const aEnd = a.x + estimateWidth(a.str, a.h)
  let best: { i: number; d: number } | null = null
  for (const i of candidates) {
    if (i === anchor) continue
    const t = texts[i]!
    const h = Math.max(a.h, t.h)
    const right = Math.abs(t.y - a.y) < 0.8 * h && t.x > a.x && t.x - aEnd < 12 * h
    const below = t.y < a.y && a.y - t.y < 3 * h && Math.abs(t.x - a.x) < 6 * h
    if (!right && !below) continue
    const d = right ? t.x - aEnd : (a.y - t.y) * 4 + Math.abs(t.x - a.x)
    if (best === null || d < best.d) best = { i, d }
  }
  return best?.i ?? null
}

/**
 * Read the title block of one frame.
 * @param scene - built scene.
 * @param region - frame rectangle, already grown by any search margin.
 * @param options - field labels and number pattern.
 * @returns the title-block reading.
 */
export function readTitleBlock(scene: Pick<BuiltScene, 'texts'>, region: Rect, options: TitleOptions): TitleBlock {
  const texts = scene.texts
  const inside: number[] = []
  for (let i = 0; i < texts.length; i++) if (inRect(region, texts[i]!.x, texts[i]!.y)) inside.push(i)
  const value = (i: number, v?: string): TitleValue => ({ value: v ?? texts[i]!.str, textId: i, handle: texts[i]!.handle })

  const lines = groupLines(texts, inside).filter(l => l.str.length <= 40)
  let name: TitleValue | null = null
  let nameH = 0
  for (const line of lines) {
    const stripped = line.str.replace(SCALE_TEXT, '').replace(/[\s:：]+$/u, '').trim()
    if (!DRAWING_NAME.test(stripped)) continue
    if (line.h > nameH) { name = value(line.ids[0]!, stripped); nameH = line.h }
  }

  const fields: Record<string, TitleValue> = {}
  const labelSet = new Set(options.fieldLabels.map(l => l.replace(/\s/g, '')))
  for (const i of inside) {
    const raw = texts[i]!.str.replace(/\s/g, '')
    const m = /^(.+?)[:：]?$/u.exec(raw)
    const label = m?.[1] ?? raw
    if (!labelSet.has(label) || fields[label] !== undefined) continue
    const inline = /^[^:：]+[:：](.+)$/u.exec(texts[i]!.str)
    if (inline !== null && inline[1]!.trim() !== '') { fields[label] = value(i, inline[1]!.trim()); continue }
    const n = neighbourOf(texts, inside, i)
    if (n !== null && !labelSet.has(texts[n]!.str.replace(/[\s:：]/g, ''))) fields[label] = value(n)
  }

  let scale: TitleBlock['scale'] = null
  const scaleField = fields['比例']
  const scaleFromField = scaleField !== undefined ? SCALE_TEXT.exec(scaleField.value) : null
  if (scaleField !== undefined && scaleFromField !== null) {
    scale = { ...scaleField, value: `1:${scaleFromField[1]}`, denominator: Number(scaleFromField[1]) }
  } else {
    let bestD = Infinity
    const ref = name !== null ? texts[name.textId]! : null
    for (const i of inside) {
      const m = SCALE_TEXT.exec(texts[i]!.str)
      if (m === null) continue
      const t = texts[i]!
      const d = ref !== null ? Math.hypot(t.x - ref.x, t.y - ref.y) : -t.h
      if (d < bestD) { bestD = d; scale = { ...value(i, `1:${m[1]}`), denominator: Number(m[1]) } }
    }
  }

  let number: TitleValue | null = null
  for (const i of inside) {
    const m = NUMBER_LABEL.exec(texts[i]!.str.trim())
    if (m === null) continue
    if (m[1]!.trim() !== '') { number = value(i, m[1]!.trim()); break }
    const n = neighbourOf(texts, inside, i)
    if (n !== null) { number = value(n); break }
  }
  if (number === null) {
    let bestH = 0
    for (const i of inside) {
      const t = texts[i]!
      if (options.numberPattern.test(t.str.trim()) && t.h > bestH) { number = value(i, t.str.trim()); bestH = t.h }
    }
  }

  return { name, number, scale, floor: name !== null ? guessFloor(name.value) : null, fields }
}
