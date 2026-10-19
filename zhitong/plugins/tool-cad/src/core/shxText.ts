/**
 * SHX stroke-font text engine: SHX font → `@mlightcad/shx-parser`
 * `getCharShape(code, height)` stroke polylines → rotated and translated to
 * the text anchor → world-coordinate segments.
 *
 * Fallback rule: a text uses SHX only when every character has a glyph; any
 * missing glyph returns null so the caller draws the whole text with a normal
 * font (no holes). The bundled KST32B is a unifont indexed by Unicode and
 * lacks many simplified-only code points (for example 图门开电标卫详).
 * Bigfonts (gbcbig, hztxt) are indexed by GB2312 and need a Unicode→GB table
 * that is not implemented.
 *
 * Source: tiangong-cad-viewer `src/shxText.ts`. Local changes: the parser is
 * imported from its ES build (the package's `main` CommonJS build exports
 * nothing under Node ESM); strict typing.
 * @module @zhitong/tool-cad/core/shxText
 */
import { ShxFont } from '@mlightcad/shx-parser/dist/index.es.js'

/** The text fields the engine reads. */
export interface ShxTextInput {
  x: number
  y: number
  h: number
  rot: number
  str: string
}

/** One loaded font. */
export interface ShxFontInfo {
  name: string
  type: string
}

/** Stroke text engine over one or more SHX fonts, queried in load order. */
export class ShxTextEngine {
  private fonts: Array<{ name: string; type: string; font: ShxFont }> = []

  /**
   * Load an SHX font (appended; lookups follow load order).
   * @param name - display name.
   * @param data - font file bytes.
   * @returns the font name and its SHX type.
   */
  loadFont(name: string, data: ArrayBuffer): ShxFontInfo {
    const font = new ShxFont(data)
    const type = String(font.fontData.header.fontType)
    this.fonts.push({ name, type, font })
    return { name, type }
  }

  /** Loaded fonts. */
  get loaded(): ShxFontInfo[] {
    return this.fonts.map(({ name, type }) => ({ name, type }))
  }

  /** Whether any font is loaded. */
  get hasFonts(): boolean {
    return this.fonts.length > 0
  }

  private hasChar(code: number): boolean {
    for (const f of this.fonts) if (f.font.hasChar(code)) return true
    return false
  }

  private glyph(code: number, size: number): ReturnType<ShxFont['getCharShape']> {
    for (const f of this.fonts) {
      const s = f.font.getCharShape(code, size)
      if (s !== undefined) return s
    }
    return undefined
  }

  /**
   * Text to world-coordinate segments (flat x1,y1,x2,y2).
   * @param t - text anchor, height, rotation, and string.
   * @returns segments, or null when a glyph is missing or no font is loaded.
   */
  textSegments(t: ShxTextInput): number[] | null {
    if (this.fonts.length === 0 || t.str === '') return null
    for (const ch of t.str) {
      if (ch === ' ' || ch === '\t') continue
      if (!this.hasChar(ch.codePointAt(0)!)) return null
    }
    const cos = Math.cos(t.rot)
    const sin = Math.sin(t.rot)
    const segs: number[] = []
    let penX = 0
    for (const ch of t.str) {
      const s = this.glyph(ch.codePointAt(0)!, t.h)
      if (s === undefined) { penX += t.h * 0.5; continue }
      for (const pl of s.polylines) {
        for (let i = 0; i + 1 < pl.length; i++) {
          const p = pl[i]!
          const q = pl[i + 1]!
          const lx1 = penX + p.x
          const ly1 = p.y
          const lx2 = penX + q.x
          const ly2 = q.y
          segs.push(
            t.x + lx1 * cos - ly1 * sin, t.y + lx1 * sin + ly1 * cos,
            t.x + lx2 * cos - ly2 * sin, t.y + lx2 * sin + ly2 * cos,
          )
        }
      }
      penX += s.lastPoint?.x ?? t.h
    }
    return segs
  }
}
