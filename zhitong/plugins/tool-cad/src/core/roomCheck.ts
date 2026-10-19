/**
 * Two-way room area check: the area written as text inside a room (m²)
 * against the geometric area of the smallest closed polygon that contains the
 * room-name anchor. Differences above a threshold go to a review list; neither
 * value is trusted silently.
 *
 * Anchors are texts on the anchor layers (Tianzheng `TXTROOM` by default) that
 * do not start with a digit or parenthesis and are at most `maxLabelLength`
 * characters long. Area texts match `^\d{1,4}\.\d{1,2}(㎡|m²|M2)?$`. When
 * conversion lost the area texts, only the geometric area is reported
 * (`textM2 = null`).
 *
 * Source: tiangong-cad-viewer `src/roomCheck.ts`. Local changes: anchor layers,
 * area range, and label length are parameters (plugin Config); the polygon
 * handle is reported.
 * @module @zhitong/tool-cad/core/roomCheck
 */
import { pointInPoly, shoelace } from './geometry.ts'
import type { BuiltScene } from './sceneBuilder.ts'

/** One matched room. */
export interface RoomCheckItem {
  /** Room name text. */
  label: string
  /** Area stated by text inside the polygon, or null when none was found. */
  textM2: number | null
  geomM2: number
  /** |geom − text| / text × 100, or null without a text area. */
  diffPct: number | null
  x: number
  y: number
  layer: string
  /** Handle of the polygon's top-level entity. */
  polyHandle: string
  /** Handle of the anchor text's top-level entity. */
  textHandle: string
}

/** Matching criteria. */
export interface RoomCriteria {
  anchorLayers: readonly string[]
  minAreaM2: number
  maxAreaM2: number
  maxLabelLength: number
}

const AREA_TEXT = /^(\d{1,4}\.\d{1,2})\s*(㎡|m²|M2)?$/

/**
 * Match room-name anchors to the smallest containing polygon and compare areas.
 * @param scene - built scene.
 * @param unitScale - millimetres per drawing unit (1 for mm, 1000 for m); the caller confirms the unit.
 * @param criteria - matching criteria.
 * @returns rooms sorted by `diffPct` descending, null last.
 */
export function checkRooms(scene: BuiltScene, unitScale: number, criteria: RoomCriteria): RoomCheckItem[] {
  const anchors = new Set(criteria.anchorLayers)
  const roomNames = scene.texts.filter(t =>
    anchors.has(t.layer) && !/^[\d(（]/.test(t.str) && t.str.length <= criteria.maxLabelLength)
  const areaTexts = scene.texts
    .map((t) => {
      const m = AREA_TEXT.exec(t.str)
      return m === null ? null : { t, val: Number.parseFloat(m[1]!) }
    })
    .filter((x): x is NonNullable<typeof x> => x !== null && x.val >= criteria.minAreaM2 && x.val <= criteria.maxAreaM2)
  if (roomNames.length === 0 || scene.polys.length === 0) return []

  const mm2PerM2 = 1e6 / (unitScale * unitScale)
  const polyInfo = scene.polys.map((p) => {
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    for (let i = 0; i + 1 < p.pts.length; i += 2) {
      const x = p.pts[i]!
      const y = p.pts[i + 1]!
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y
    }
    return { minX, minY, maxX, maxY, areaM2: shoelace(p.pts) / mm2PerM2 }
  })

  const out: RoomCheckItem[] = []
  const seen = new Set<number>()
  for (const t of roomNames) {
    let best: { pi: number; areaM2: number } | null = null
    for (let pi = 0; pi < scene.polys.length; pi++) {
      const info = polyInfo[pi]!
      if (info.areaM2 < criteria.minAreaM2 || info.areaM2 > criteria.maxAreaM2) continue
      if (t.x < info.minX || t.x > info.maxX || t.y < info.minY || t.y > info.maxY) continue
      if (!pointInPoly(scene.polys[pi]!.pts, t.x, t.y)) continue
      if (best === null || info.areaM2 < best.areaM2) best = { pi, areaM2: info.areaM2 }
    }
    if (best === null || seen.has(best.pi)) continue
    seen.add(best.pi)
    let textM2: number | null = null
    const info = polyInfo[best.pi]!
    const poly = scene.polys[best.pi]!
    for (const { t: at, val } of areaTexts) {
      if (at.x < info.minX || at.x > info.maxX || at.y < info.minY || at.y > info.maxY) continue
      if (pointInPoly(poly.pts, at.x, at.y)) { textM2 = val; break }
    }
    const diffPct = textM2 !== null ? Number(((Math.abs(best.areaM2 - textM2) / textM2) * 100).toFixed(2)) : null
    out.push({
      label: t.str,
      textM2,
      geomM2: Number(best.areaM2.toFixed(2)),
      diffPct,
      x: t.x,
      y: t.y,
      layer: t.layer,
      polyHandle: poly.handle,
      textHandle: t.handle,
    })
  }
  return out.sort((a, b) => (b.diffPct ?? -1) - (a.diffPct ?? -1))
}
