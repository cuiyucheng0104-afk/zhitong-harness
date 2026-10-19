import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { physicalPath } from '../src/config.ts'

const roots: string[] = []
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true })
})

describe('physicalPath (Desktop asar layout)', () => {
  it('maps an archived file to its unpacked twin', () => {
    const root = mkdtempSync(join(tmpdir(), 'tool-cad-asar-'))
    roots.push(root)
    const inside = join('dsh', 'node_modules', '@zhitong', 'tool-cad', 'bin', 'darwin-arm64', 'dwg2dxf')
    mkdirSync(join(root, 'app.asar.unpacked', inside, '..'), { recursive: true })
    writeFileSync(join(root, 'app.asar.unpacked', inside), '')
    expect(physicalPath(join(root, 'app.asar', inside))).toBe(join(root, 'app.asar.unpacked', inside))
  })

  it('keeps archived paths without an unpacked twin and paths outside an archive', () => {
    const root = mkdtempSync(join(tmpdir(), 'tool-cad-asar-'))
    roots.push(root)
    const archived = join(root, 'app.asar', 'dsh', 'assets', 'fonts', 'kst32b.shx')
    expect(physicalPath(archived)).toBe(archived)
    const plain = join(root, 'assets', 'fonts', 'kst32b.shx')
    expect(physicalPath(plain)).toBe(plain)
  })
})
