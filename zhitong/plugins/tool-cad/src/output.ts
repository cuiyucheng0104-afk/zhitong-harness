/** Output helpers: result files beside the parse cache, TSV formatting, and coordinate rounding. @module @zhitong/tool-cad/output */

import { createHash } from 'node:crypto'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { UnitName } from './core/unit.ts'
import { coordDecimals } from './core/unit.ts'

/**
 * Short stable hash of a JSON-serializable value, used in output file names.
 * @param value - value to hash.
 * @returns eight hex characters.
 */
export function shortHash(value: unknown): string {
  return createHash('sha256').update(JSON.stringify(value) ?? '').digest('hex').slice(0, 8)
}

/**
 * Write one result file under `<cacheDir>/<sub>/`.
 * @param cacheDir - document cache directory.
 * @param sub - subdirectory (`out` or `render`).
 * @param name - file name.
 * @param data - content; strings are written as UTF-8.
 * @returns the absolute file path.
 */
export async function writeResultFile(cacheDir: string, sub: 'out' | 'render', name: string, data: string | Buffer): Promise<string> {
  const dir = join(cacheDir, sub)
  await mkdir(dir, { recursive: true })
  const path = join(dir, name)
  await writeFile(path, data)
  return path
}

/**
 * Coordinate rounding for a unit (1 mm resolution).
 * @param unit - drawing unit.
 * @returns a rounding function.
 */
export function rounder(unit: UnitName): (v: number) => number {
  const d = coordDecimals(unit)
  const k = 10 ** d
  return (v: number) => Math.round(v * k) / k
}

/**
 * Escape one TSV field (tabs and newlines become spaces).
 * @param v - field value.
 * @returns the field text.
 */
export function tsvField(v: string | number | boolean | null): string {
  if (v === null) return ''
  return String(v).replace(/[\t\r\n]+/g, ' ')
}

/**
 * TSV table with a header row.
 * @param header - column names.
 * @param rows - rows of fields.
 * @returns TSV text.
 */
export function toTsv(header: readonly string[], rows: ReadonlyArray<ReadonlyArray<string | number | boolean | null>>): string {
  return [header.join('\t'), ...rows.map(r => r.map(tsvField).join('\t'))].join('\n')
}
