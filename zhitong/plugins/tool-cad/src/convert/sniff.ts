/**
 * Format and encoding sniffing. Extensions lie in both directions (a `.dxf`
 * that is really an AC1021 DWG has been seen), so only the file header
 * decides. DXF text is decoded as strict UTF-8 first and falls back to GBK:
 * old drawings are GBK (`$DWGCODEPAGE=ANSI_936`) while dwg2dxf writes AC1021+
 * drawings as UTF-8, and decoding everything as GBK garbles UTF-8 Chinese.
 *
 * Source: tiangong-cad-viewer `tools/convert.mjs` and `electron/main.cjs`
 * (`sniffIsDwg`, `transcodeToUtf8`/`decodeDxf`); binary DXF detection added.
 * @module @zhitong/tool-cad/convert/sniff
 */

/** Sniffed file format. */
export type SniffedFormat = 'dwg' | 'dxf' | 'dxf-binary'

/** Encoding used to decode DXF text. */
export type DxfEncoding = 'ascii' | 'utf-8' | 'gbk'

const BINARY_DXF = 'AutoCAD Binary DXF'

/**
 * Sniff the format from the first bytes of a file.
 * @param head - at least the first 22 bytes.
 * @returns `dwg` for an `AC10xx` header, `dxf-binary` for binary DXF, otherwise `dxf`.
 */
export function sniffFormat(head: Uint8Array): SniffedFormat {
  const latin = Buffer.from(head.subarray(0, 22)).toString('latin1')
  if (latin.startsWith(BINARY_DXF)) return 'dxf-binary'
  if (latin.startsWith('AC10') && head[5] !== 0x0a && !latin.startsWith('AC101\n')) return 'dwg'
  return 'dxf'
}

/**
 * Decode DXF bytes, then expand `\U+XXXX` escapes (see {@link expandUnicodeEscapes}).
 * @param buf - DXF file bytes.
 * @returns the text, the encoding that decoded the bytes, and the number of escapes expanded.
 */
export function decodeDxf(buf: Uint8Array): { text: string; encoding: DxfEncoding; escapes: number } {
  let ascii = true
  for (let i = 0; i < buf.length; i++) if (buf[i]! > 0x7f) { ascii = false; break }
  let text: string
  let encoding: DxfEncoding
  if (ascii) {
    text = Buffer.from(buf).toString('latin1')
    encoding = 'ascii'
  } else {
    try {
      text = new TextDecoder('utf-8', { fatal: true }).decode(buf)
      encoding = 'utf-8'
    } catch (error) {
      // A strict UTF-8 failure is the signal for a GBK (ANSI_936) drawing; the error itself carries nothing else.
      void error
      text = new TextDecoder('gbk').decode(buf)
      encoding = 'gbk'
    }
  }
  const expanded = expandUnicodeEscapes(text)
  return { text: expanded.text, encoding, escapes: expanded.count }
}

const ESCAPE_RUN = /(?:\\U\+[0-9A-Fa-f]{4})+/g
const ESCAPE = /\\U\+([0-9A-Fa-f]{4})/g
const STRICT_GBK = new TextDecoder('gbk', { fatal: true })

/**
 * Expand DXF `\U+XXXX` escapes. LibreDWG 0.14 writes code-page names (layer,
 * linetype, block) of GBK drawings as one escape per GBK byte (`\U+00D0\U+00C2`
 * for 新); a run of escapes that are all bytes 0x80–0xFF and decode as strict
 * GBK is therefore decoded as GBK bytes. Every other escape is a Unicode code
 * point (`\U+03A6` → Φ).
 * @param text - decoded DXF text.
 * @returns the expanded text and the number of escapes replaced.
 */
export function expandUnicodeEscapes(text: string): { text: string; count: number } {
  let count = 0
  const out = text.replace(ESCAPE_RUN, (run) => {
    const codes = [...run.matchAll(ESCAPE)].map(m => Number.parseInt(m[1]!, 16))
    count += codes.length
    if (codes.length % 2 === 0 && codes.every(c => c >= 0x80 && c <= 0xff)) {
      try {
        return STRICT_GBK.decode(Uint8Array.from(codes))
      } catch (error) {
        // Not a GBK byte sequence: fall through to code-point expansion below.
        void error
      }
    }
    return String.fromCodePoint(...codes)
  })
  return { text: out, count }
}
