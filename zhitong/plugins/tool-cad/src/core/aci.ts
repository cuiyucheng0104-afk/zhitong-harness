/**
 * AutoCAD ACI color index to RGB. Indices 1-9 and 250-255 are exact standard
 * values; 10-249 follow the HSV pattern approximately.
 *
 * Source: tiangong-cad-viewer `src/engine/aci.ts` (logic unchanged).
 * @module @zhitong/tool-cad/core/aci
 */

const STD: Readonly<Record<number, number>> = {
  1: 0xff0000, 2: 0xffff00, 3: 0x00ff00, 4: 0x00ffff, 5: 0x0000ff,
  6: 0xff00ff, 7: 0xffffff, 8: 0x808080, 9: 0xc0c0c0,
  250: 0x333333, 251: 0x505050, 252: 0x696969, 253: 0x828282, 254: 0xbebebe, 255: 0xffffff,
}

const SHADE_VALUE = [1, 1, 0.8, 0.8, 0.6, 0.6, 0.5, 0.5, 0.35, 0.35] as const

function hsv(h: number, s: number, v: number): number {
  const f = (n: number): number => {
    const k = (n + h / 60) % 6
    return v - v * s * Math.max(0, Math.min(k, 4 - k, 1))
  }
  return (Math.round(f(5) * 255) << 16) | (Math.round(f(3) * 255) << 8) | Math.round(f(1) * 255)
}

/**
 * Convert an ACI color index to a 24-bit RGB integer.
 * @param index - ACI index; values outside 1-255 map to white.
 * @returns the RGB value as `0xRRGGBB`.
 */
export function aciToRgb(index: number): number {
  const exact = STD[index]
  if (exact !== undefined) return exact
  if (index >= 10 && index <= 249) {
    const i = index - 10
    const hue = Math.floor(i / 10) * 15
    const shade = i % 10
    const v = SHADE_VALUE[shade] ?? 1
    const s = shade % 2 === 0 ? 1 : 0.45
    return hsv(hue, s, v)
  }
  return 0xffffff
}
