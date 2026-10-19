/**
 * Text filtering and line grouping. Filters select texts by frame, layer,
 * substring, regular expression, rectangle, and height. Grouping joins
 * fragments that share a rotation and baseline and sit within about one text
 * height of each other into one line, so a title split into several TEXT
 * entities reads as one row.
 *
 * Text widths are estimated (CJK 1.0 h, other characters 0.6 h) because
 * alignment and font metrics are not available.
 * @module @zhitong/tool-cad/core/textQuery
 */
import type { Rect } from './geometry.ts'
import { inRect } from './geometry.ts'
import type { TextItem } from './sceneBuilder.ts'

/** Text selection criteria; all given criteria must hold. */
export interface TextFilter {
  /** Region, such as a frame rectangle. */
  rect?: Rect
  /** Exact layer names. */
  layers?: ReadonlySet<string>
  /** Case-insensitive substring. */
  query?: string
  regex?: RegExp
  minHeight?: number
}

const CJK = /[　-〿㐀-鿿豈-﫿＀-￯]/u

/**
 * Estimated text width.
 * @param str - text.
 * @param h - text height.
 * @returns width in drawing units.
 */
export function estimateWidth(str: string, h: number): number {
  let w = 0
  for (const ch of str) w += CJK.test(ch) ? h : h * 0.6
  return w
}

/**
 * Indices of texts that match every given criterion.
 * @param texts - scene texts.
 * @param filter - criteria.
 * @returns matching indices in scene order.
 */
export function filterTexts(texts: readonly TextItem[], filter: TextFilter): number[] {
  const query = filter.query?.toLowerCase()
  const out: number[] = []
  for (let i = 0; i < texts.length; i++) {
    const t = texts[i]!
    if (filter.rect !== undefined && !inRect(filter.rect, t.x, t.y)) continue
    if (filter.layers !== undefined && !filter.layers.has(t.layer)) continue
    if (filter.minHeight !== undefined && t.h < filter.minHeight) continue
    if (query !== undefined && query !== '' && !t.str.toLowerCase().includes(query)) continue
    if (filter.regex !== undefined && !filter.regex.test(t.str)) continue
    out.push(i)
  }
  return out
}

/** One grouped line. */
export interface TextLine {
  str: string
  /** Anchor of the first fragment. */
  x: number
  y: number
  /** Largest fragment height. */
  h: number
  rot: number
  layer: string
  /** Scene indices of the fragments, in reading order. */
  ids: number[]
}

/**
 * Group fragments into lines. Fragments merge when their rotations differ by
 * less than 0.02 rad, their baselines are within 0.6 h, and the gap from the
 * previous fragment's estimated end is below 1.2 h (overlap allowed).
 * @param texts - scene texts.
 * @param indices - fragments to group.
 * @returns lines ordered top to bottom, then left to right.
 */
export function groupLines(texts: readonly TextItem[], indices: readonly number[]): TextLine[] {
  const items = indices.map((i) => {
    const t = texts[i]!
    const cos = Math.cos(-t.rot)
    const sin = Math.sin(-t.rot)
    // Coordinates in the text's own frame: u along the baseline, v across it.
    return { i, t, u: t.x * cos - t.y * sin, v: t.x * sin + t.y * cos }
  })
  items.sort((a, b) => a.t.rot - b.t.rot || b.v - a.v || a.u - b.u)
  const lines: Array<{ members: typeof items; rot: number; v: number; h: number; start: number; end: number }> = []
  for (const it of items) {
    const width = estimateWidth(it.t.str, it.t.h)
    let target: (typeof lines)[number] | undefined
    for (let k = lines.length - 1; k >= 0 && k >= lines.length - 64; k--) {
      const line = lines[k]!
      if (Math.abs(line.rot - it.t.rot) >= 0.02) continue
      const h = Math.max(line.h, it.t.h)
      if (Math.abs(line.v - it.v) > 0.6 * h) continue
      const gap = Math.max(it.u - line.end, line.start - (it.u + width))
      if (gap > 1.2 * h) continue
      target = line
      break
    }
    if (target === undefined) {
      lines.push({ members: [it], rot: it.t.rot, v: it.v, h: it.t.h, start: it.u, end: it.u + width })
    } else {
      target.members.push(it)
      target.h = Math.max(target.h, it.t.h)
      target.start = Math.min(target.start, it.u)
      target.end = Math.max(target.end, it.u + width)
    }
  }
  const out: TextLine[] = lines.map((line) => {
    const members = [...line.members].sort((a, b) => a.u - b.u)
    let str = ''
    for (const m of members) {
      const prev = str.at(-1)
      const next = m.t.str[0]
      const glue = str === '' || (prev !== undefined && next !== undefined && CJK.test(prev) && CJK.test(next)) ? '' : ' '
      str += glue + m.t.str
    }
    const first = members[0]!.t
    return { str, x: first.x, y: first.y, h: line.h, rot: line.rot, layer: first.layer, ids: members.map(m => m.i) }
  })
  return out.sort((a, b) => b.y - a.y || a.x - b.x)
}
