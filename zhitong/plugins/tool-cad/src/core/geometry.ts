/** Planar geometry helpers shared by the extraction modules. @module @zhitong/tool-cad/core/geometry */

/** Axis-aligned world rectangle with `x1 ≤ x2` and `y1 ≤ y2`. */
export type Rect = {
  x1: number
  y1: number
  x2: number
  y2: number
}

/**
 * Polygon area by the shoelace formula.
 * @param pts - flat xy coordinates.
 * @returns the unsigned area in squared drawing units.
 */
export function shoelace(pts: readonly number[]): number {
  let a = 0
  const n = pts.length / 2
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n
    a += pts[i * 2]! * pts[j * 2 + 1]! - pts[j * 2]! * pts[i * 2 + 1]!
  }
  return Math.abs(a) / 2
}

/**
 * Even-odd point-in-polygon test.
 * @param pts - flat xy coordinates.
 * @param x - point X.
 * @param y - point Y.
 * @returns whether the point is inside.
 */
export function pointInPoly(pts: readonly number[], x: number, y: number): boolean {
  let inside = false
  const n = pts.length / 2
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = pts[i * 2]!
    const yi = pts[i * 2 + 1]!
    const xj = pts[j * 2]!
    const yj = pts[j * 2 + 1]!
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
  }
  return inside
}

/**
 * Bounding rectangle of flat xy coordinates.
 * @param pts - flat xy coordinates (at least one point).
 * @returns the bounding rectangle.
 */
export function boundsOf(pts: readonly number[]): Rect {
  let x1 = Infinity
  let y1 = Infinity
  let x2 = -Infinity
  let y2 = -Infinity
  for (let i = 0; i + 1 < pts.length; i += 2) {
    const x = pts[i]!
    const y = pts[i + 1]!
    if (x < x1) x1 = x
    if (x > x2) x2 = x
    if (y < y1) y1 = y
    if (y > y2) y2 = y
  }
  return { x1, y1, x2, y2 }
}

/**
 * Normalize two corners into a rectangle.
 * @param r - corners in any order.
 * @returns the normalized rectangle.
 */
export function normalizeRect(r: Rect): Rect {
  return { x1: Math.min(r.x1, r.x2), y1: Math.min(r.y1, r.y2), x2: Math.max(r.x1, r.x2), y2: Math.max(r.y1, r.y2) }
}

/**
 * Whether a point lies inside a rectangle (edges included).
 * @param r - rectangle.
 * @param x - point X.
 * @param y - point Y.
 * @returns the containment fact.
 */
export function inRect(r: Rect, x: number, y: number): boolean {
  return x >= r.x1 && x <= r.x2 && y >= r.y1 && y <= r.y2
}

/**
 * Grow a rectangle by a margin on every side.
 * @param r - rectangle.
 * @param margin - margin in drawing units.
 * @returns the grown rectangle.
 */
export function expandRect(r: Rect, margin: number): Rect {
  return { x1: r.x1 - margin, y1: r.y1 - margin, x2: r.x2 + margin, y2: r.y2 + margin }
}
