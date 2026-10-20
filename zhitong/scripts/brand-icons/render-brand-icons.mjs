#!/usr/bin/env node
/**
 * Render every 智通数工AI icon from `zhitong/brand/brand-mark.svg`.
 *
 * The brand mark is a 64-unit rounded square (gradient fill, white cross, green ticks). This script places it on
 * each platform's canvas and writes:
 *
 * - `zhitong/brand/icon-macos.svg` and `icon-windows.svg`: the 1024 px platform sources.
 *   macOS follows Apple's app icon grid: an 824 px rounded square centered on a transparent 1024 px canvas
 *   (100 px margins), corner radius 185.4 px, with a soft drop shadow inside the margin. Windows keeps the brand
 *   mark's own corner radius on a 960 px square with 32 px margins, without a shadow.
 * - `zhitong/brand/icons/`: `icon-<n>.png` (Windows variant, 16–1024), `icon-macos-1024.png`, `icon.icns`
 *   (macOS variant, 16–1024 including @2x), `icon.ico` (16–256) and `tray.ico` (the Windows tray sizes
 *   16, 20, 24, 32, 40, 48, 64).
 * - `zhitong/portal/site/public/`: `favicon.svg`, `favicon.ico` (16, 32, 48) and `apple-touch-icon.png`
 *   (180 px, opaque full-bleed square; iOS applies its own mask).
 *
 * ICO entries below 256 px are 32-bit DIBs and the 256 px entry is PNG, the layout Windows Explorer, the
 * Electron window icon and the NSIS installer compiler all read. ICNS entries are PNG streams.
 *
 * Usage (from this directory): `npm ci && npm run render`. Rerun after changing the brand mark; commit the outputs.
 */

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import sharp from 'sharp'

const ZHITONG = resolve(import.meta.dirname, '..', '..')
const BRAND = join(ZHITONG, 'brand')
const ICONS = join(BRAND, 'icons')
const SITE_PUBLIC = join(ZHITONG, 'portal', 'site', 'public')

/** Brand mark coordinate system and the corner radius it declares. */
const MARK_UNITS = 64
const MARK_RADIUS = 'rx="17"'

/** Apple app icon grid on a 1024 px canvas. */
const MACOS = { canvas: 1024, body: 824, radius: 185.4 }
/** Windows full-bleed tile: brand radius, 32 px margin on 1024. */
const WINDOWS = { canvas: 1024, body: 960 }

const PNG_SIZES = [16, 32, 48, 64, 128, 256, 512, 1024]
const ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
const TRAY_SIZES = [16, 20, 24, 32, 40, 48, 64]
const FAVICON_SIZES = [16, 32, 48]

/** ICNS element types and the pixel edge each one holds. */
const ICNS_TYPES = [
  ['icp4', 16], ['icp5', 32], ['icp6', 64], ['ic07', 128], ['ic08', 256], ['ic09', 512], ['ic10', 1024],
  ['ic11', 32], ['ic12', 64], ['ic13', 256], ['ic14', 512],
]

/**
 * Split the brand mark into its definitions and drawing, with the corner radius made replaceable.
 * @param {string} source - Contents of brand-mark.svg.
 * @returns {(radius: number) => string} Inner SVG markup in 64-unit coordinates for a given corner radius.
 */
function brandMarkBody(source) {
  const match = /^<svg[^>]*viewBox="0 0 64 64"[^>]*>([\s\S]*)<\/svg>\s*$/u.exec(source.trim())
  if (match === null) throw new Error('brand-mark.svg: expected one <svg viewBox="0 0 64 64"> element')
  const inner = match[1]
  if (inner.split(MARK_RADIUS).length !== 2) throw new Error(`brand-mark.svg: expected exactly one ${MARK_RADIUS}`)
  return radius => inner.replace(MARK_RADIUS, `rx="${String(radius)}"`)
}

/**
 * Wrap the brand mark on a square canvas.
 * @param {(radius: number) => string} body - Brand mark markup factory.
 * @param {{ canvas: number, body: number, radius: number, shadow: boolean }} layout - Pixel geometry.
 * @returns {string} Standalone SVG document.
 */
function platformSvg(body, layout) {
  const scale = layout.body / MARK_UNITS
  const offset = (layout.canvas - layout.body) / 2
  const shadow = layout.shadow
    ? '<defs><filter id="shadow" x="-10%" y="-10%" width="120%" height="125%">'
      + '<feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#0b347d" flood-opacity="0.28"/></filter></defs>'
    : ''
  // The filter sits outside the scaled group so its offsets and blur are in canvas pixels.
  const mark = `<g transform="translate(${offset} ${offset}) scale(${scale})">${body(layout.radius / scale)}</g>`
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${layout.canvas}" height="${layout.canvas}" viewBox="0 0 ${
    layout.canvas} ${layout.canvas}">${shadow}${layout.shadow ? `<g filter="url(#shadow)">${mark}</g>` : mark}</svg>\n`
}

/**
 * Rasterize an SVG to a square PNG.
 * @param {string} svg - SVG document.
 * @param {number} size - Output edge in pixels.
 * @param {{ flatten?: string }} [options] - Background colour for an opaque result.
 * @returns {Promise<Buffer>} PNG bytes.
 */
async function png(svg, size, options = {}) {
  // Render at a density that makes the SVG's own size match the target, so small sizes are drawn, not downscaled.
  const width = Number(/width="(\d+)"/u.exec(svg)?.[1])
  let image = sharp(Buffer.from(svg), { density: Math.max(1, (72 * size) / width) }).resize(size, size)
  if (options.flatten !== undefined) image = image.flatten({ background: options.flatten })
  return image.png({ compressionLevel: 9 }).toBuffer()
}

/**
 * Encode one ICO image as a 32-bit bottom-up DIB with an all-zero AND mask.
 * @param {string} svg - SVG document.
 * @param {number} size - Edge in pixels (below 256).
 * @returns {Promise<Buffer>} DIB bytes.
 */
async function dib(svg, size) {
  const rgba = await sharp(await png(svg, size)).ensureAlpha().raw().toBuffer()
  const header = Buffer.alloc(40)
  header.writeUInt32LE(40, 0)
  header.writeInt32LE(size, 4)
  header.writeInt32LE(size * 2, 8) // XOR bitmap plus AND mask
  header.writeUInt16LE(1, 12)
  header.writeUInt16LE(32, 14)
  header.writeUInt32LE(size * size * 4, 20)
  const pixels = Buffer.alloc(size * size * 4)
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const from = (y * size + x) * 4
      const to = ((size - 1 - y) * size + x) * 4
      pixels[to] = rgba[from + 2]
      pixels[to + 1] = rgba[from + 1]
      pixels[to + 2] = rgba[from]
      pixels[to + 3] = rgba[from + 3]
    }
  }
  const maskRow = Math.ceil(size / 32) * 4
  return Buffer.concat([header, pixels, Buffer.alloc(maskRow * size)])
}

/**
 * Build a multi-size ICO file.
 * @param {string} svg - SVG document.
 * @param {number[]} sizes - Edges to include, at most 256.
 * @returns {Promise<Buffer>} ICO bytes.
 */
async function ico(svg, sizes) {
  const images = await Promise.all(sizes.map(size => (size >= 256 ? png(svg, size) : dib(svg, size))))
  const directory = Buffer.alloc(6 + 16 * sizes.length)
  directory.writeUInt16LE(0, 0)
  directory.writeUInt16LE(1, 2)
  directory.writeUInt16LE(sizes.length, 4)
  let offset = directory.length
  sizes.forEach((size, index) => {
    const entry = 6 + 16 * index
    directory.writeUInt8(size >= 256 ? 0 : size, entry)
    directory.writeUInt8(size >= 256 ? 0 : size, entry + 1)
    directory.writeUInt16LE(1, entry + 4)
    directory.writeUInt16LE(32, entry + 6)
    directory.writeUInt32LE(images[index].length, entry + 8)
    directory.writeUInt32LE(offset, entry + 12)
    offset += images[index].length
  })
  return Buffer.concat([directory, ...images])
}

/**
 * Build an ICNS file from PNG elements.
 * @param {string} svg - SVG document.
 * @returns {Promise<Buffer>} ICNS bytes.
 */
async function icns(svg) {
  const cache = new Map()
  const elements = []
  for (const [type, size] of ICNS_TYPES) {
    if (!cache.has(size)) cache.set(size, await png(svg, size))
    const data = cache.get(size)
    const header = Buffer.alloc(8)
    header.write(type, 0, 'ascii')
    header.writeUInt32BE(data.length + 8, 4)
    elements.push(header, data)
  }
  const body = Buffer.concat(elements)
  const header = Buffer.alloc(8)
  header.write('icns', 0, 'ascii')
  header.writeUInt32BE(body.length + 8, 4)
  return Buffer.concat([header, body])
}

/**
 * Write one output and report it.
 * @param {string} path - Destination.
 * @param {string | Buffer} data - Contents.
 */
function emit(path, data) {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, data)
  console.info(`wrote ${path.slice(ZHITONG.length + 1)} (${String(data.length)} bytes)`)
}

const source = readFileSync(join(BRAND, 'brand-mark.svg'), 'utf8')
const body = brandMarkBody(source)
const macos = platformSvg(body, { ...MACOS, shadow: true })
const windows = platformSvg(body, { ...WINDOWS, radius: (17 * WINDOWS.body) / MARK_UNITS, shadow: false })
// Apple touch icons are opaque squares; iOS rounds the corners.
const touch = platformSvg(body, { canvas: 1024, body: 1024, radius: 0, shadow: false })

emit(join(BRAND, 'icon-macos.svg'), macos)
emit(join(BRAND, 'icon-windows.svg'), windows)
for (const size of PNG_SIZES) emit(join(ICONS, `icon-${String(size)}.png`), await png(windows, size))
emit(join(ICONS, 'icon-macos-1024.png'), await png(macos, 1024))
emit(join(ICONS, 'icon.icns'), await icns(macos))
emit(join(ICONS, 'icon.ico'), await ico(windows, ICO_SIZES))
emit(join(ICONS, 'tray.ico'), await ico(windows, TRAY_SIZES))
emit(join(SITE_PUBLIC, 'favicon.svg'), source)
emit(join(SITE_PUBLIC, 'favicon.ico'), await ico(windows, FAVICON_SIZES))
emit(join(SITE_PUBLIC, 'apple-touch-icon.png'), await png(touch, 180, { flatten: '#0666f5' }))
