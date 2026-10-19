/**
 * Table auto-location. A header row is a set of texts on one baseline that
 * contains at least `minHeaderHits` distinct header words of a table kind
 * (door/window schedule: `编号`, `洞口尺寸`, `数量` …). From the header the
 * table width comes from the longest horizontal line near the header that
 * spans it; the bottom follows horizontal lines of similar span downwards until
 * the vertical gap exceeds the expected row spacing. The located rectangle goes
 * to {@link extractTable}. A title text (`门窗表` …) near the top is reported
 * when present.
 * @module @zhitong/tool-cad/core/tables
 */
import type { TableResult } from './extract.ts'
import { extractTable } from './extract.ts'
import type { Rect } from './geometry.ts'
import { inRect } from './geometry.ts'
import type { BuiltScene } from './sceneBuilder.ts'
import { estimateWidth } from './textQuery.ts'

/** Keywords of one table kind. */
export interface TableKind {
  kind: string
  titles: readonly string[]
  headers: readonly string[]
}

/** One located table. */
export interface LocatedTable {
  kind: string
  title: string | null
  rect: Rect
  /** Header words found, in reading order. */
  headerWords: string[]
  /** Scene index of the first header text. */
  headerTextId: number
  table: TableResult | null
}

const normalize = (s: string): string => s.replace(/[\s()（）:：]/g, '')

interface HSeg { y: number; x1: number; x2: number }

function horizontalSegments(scene: Pick<BuiltScene, 'layers'>, region: Rect | null): HSeg[] {
  const out: HSeg[] = []
  for (const l of scene.layers) {
    const p = l.positions
    for (let i = 0; i + 5 < p.length; i += 6) {
      const x1 = p[i]!
      const y1 = p[i + 1]!
      const x2 = p[i + 3]!
      const y2 = p[i + 4]!
      const len = Math.abs(x2 - x1)
      if (len === 0 || Math.abs(y2 - y1) > len * 0.002) continue
      if (region !== null && (!inRect(region, x1, y1) || !inRect(region, x2, y2))) continue
      out.push({ y: (y1 + y2) / 2, x1: Math.min(x1, x2), x2: Math.max(x1, x2) })
    }
  }
  return out
}

/**
 * Locate tables of the given kinds.
 * @param scene - built scene.
 * @param kinds - table kinds with title and header keywords.
 * @param region - search region (a frame), or null for the whole drawing.
 * @param minHeaderHits - distinct header words a header row needs.
 * @returns located tables, top to bottom.
 */
export function locateTables(scene: Pick<BuiltScene, 'layers' | 'texts'>, kinds: readonly TableKind[], region: Rect | null, minHeaderHits: number): LocatedTable[] {
  const texts = scene.texts
  const segs = horizontalSegments(scene, region)
  const results: LocatedTable[] = []
  for (const kind of kinds) {
    const headerWords = kind.headers.map(normalize)
    const hits: Array<{ i: number; word: string }> = []
    for (let i = 0; i < texts.length; i++) {
      const t = texts[i]!
      if (region !== null && !inRect(region, t.x, t.y)) continue
      const s = normalize(t.str)
      if (s.length > 12) continue
      const word = headerWords.find(w => s === w || (s.startsWith(w) && s.length <= w.length + 4))
      if (word !== undefined) hits.push({ i, word })
    }
    hits.sort((a, b) => texts[b.i]!.y - texts[a.i]!.y || texts[a.i]!.x - texts[b.i]!.x)
    const used = new Set<number>()
    for (const seed of hits) {
      if (used.has(seed.i)) continue
      const s = texts[seed.i]!
      const row = hits.filter(o => !used.has(o.i) && Math.abs(texts[o.i]!.y - s.y) < 1.5 * Math.max(s.h, texts[o.i]!.h))
      const distinct = new Set(row.map(o => o.word))
      if (distinct.size < minHeaderHits) continue
      for (const o of row) used.add(o.i)
      const rowTexts = row.map(o => texts[o.i]!)
      const h = Math.max(...rowTexts.map(t => t.h))
      const hx1 = Math.min(...rowTexts.map(t => t.x))
      const hx2 = Math.max(...rowTexts.map(t => t.x + estimateWidth(t.str, t.h)))
      const hy = rowTexts.reduce((sum, t) => sum + t.y, 0) / rowTexts.length

      const spanning = segs.filter(g => Math.abs(g.y - hy) < 4 * h && g.x1 <= hx1 + h && g.x2 >= hx2 - h)
      const widest = spanning.reduce<HSeg | null>((best, g) => (best === null || g.x2 - g.x1 > best.x2 - best.x1 ? g : best), null)
      const x1 = widest !== null ? widest.x1 : hx1 - 2 * h
      const x2 = widest !== null ? widest.x2 : hx2 + 2 * h
      const width = x2 - x1
      const similar = segs
        .filter(g => g.x2 - g.x1 >= width * 0.6 && g.x1 >= x1 - width * 0.05 && g.x2 <= x2 + width * 0.05)
        .map(g => g.y)
        .sort((a, b) => b - a)
      const above = similar.filter(y => y >= hy && y - hy < 4 * h)
      const top = above.length > 0 ? Math.max(...above) : hy + 2 * h
      let bottom = hy - 2 * h
      let last = hy
      for (const y of similar) {
        if (y >= hy) continue
        if (last - y > 6 * h) break
        bottom = y
        last = y
      }
      const rect: Rect = { x1, y1: bottom, x2, y2: top }
      const pad = h * 0.5
      const table = extractTable(scene, { x1: x1 - pad, y1: bottom - pad, x2: x2 + pad, y2: top + pad })
      const titleWords = kind.titles.map(normalize)
      let title: string | null = null
      for (const t of texts) {
        if (t.y < top - h || t.y > top + 8 * h || t.x < x1 - width * 0.2 || t.x > x2) continue
        const n = normalize(t.str)
        if (titleWords.some(w => n.includes(w))) { title = t.str; break }
      }
      results.push({
        kind: kind.kind,
        title,
        rect,
        headerWords: [...rowTexts].sort((a, b) => a.x - b.x).map(t => t.str),
        headerTextId: seed.i,
        table,
      })
    }
  }
  return results.sort((a, b) => b.rect.y2 - a.rect.y2 || a.rect.x1 - b.rect.x1)
}
