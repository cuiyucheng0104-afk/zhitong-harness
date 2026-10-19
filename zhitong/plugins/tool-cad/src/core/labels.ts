/**
 * Door and window label counting: texts that match an opening-number pattern
 * (`M1021`, `C1518`, `FM甲1022` …) are counted per label and per frame. This
 * is the text-based cross-check of block counting; labels drawn inside a block
 * count once per block reference. Codes listed inside a door/window schedule
 * are excluded and reported separately.
 * @module @zhitong/tool-cad/core/labels
 */
import type { LabelledRect } from './extract.ts'
import { pointFrame } from './frames.ts'
import type { Rect } from './geometry.ts'
import { inRect } from './geometry.ts'
import type { TextItem } from './sceneBuilder.ts'

/** Count of one label. */
export interface LabelCount {
  label: string
  count: number
  /** Count per frame label; `框外` collects texts outside every frame. Empty without frames. */
  perFrame: Record<string, number>
  /** Scene text indices of every counted occurrence. */
  ids: number[]
  /** Occurrences excluded because they sit inside a schedule table. */
  inTables: number
}

/**
 * Count texts matching the label pattern.
 * @param texts - scene texts.
 * @param indices - candidate indices (already filtered by frame or layer).
 * @param pattern - label pattern, tested against the trimmed text with spaces removed.
 * @param frames - frames for per-frame grouping.
 * @param tables - schedule-table rectangles; labels inside them are listed codes, not openings, and are excluded.
 * @returns counts sorted by count descending, then label.
 */
export function countLabels(
  texts: readonly TextItem[], indices: readonly number[], pattern: RegExp, frames: readonly LabelledRect[], tables: readonly Rect[] = [],
): LabelCount[] {
  const map = new Map<string, LabelCount>()
  for (const i of indices) {
    const t = texts[i]!
    const label = t.str.replace(/\s/g, '')
    if (!pattern.test(label)) continue
    let entry = map.get(label)
    if (entry === undefined) { entry = { label, count: 0, perFrame: {}, ids: [], inTables: 0 }; map.set(label, entry) }
    if (tables.some(r => inRect(r, t.x, t.y))) { entry.inTables++; continue }
    entry.count++
    entry.ids.push(i)
    if (frames.length > 0) {
      const f = pointFrame(frames, t.x, t.y)
      const key = f !== null ? f.label : '框外'
      entry.perFrame[key] = (entry.perFrame[key] ?? 0) + 1
    }
  }
  return [...map.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}
