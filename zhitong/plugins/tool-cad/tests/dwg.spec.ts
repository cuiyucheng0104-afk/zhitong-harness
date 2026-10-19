/**
 * DWG conversion through the subprocess service. The real-converter case runs
 * when dwg2dxf is reachable (Config path, `DWG2DXF_BIN`, the package `bin/`,
 * or PATH) and is skipped with the reason otherwise. Stand-in converters
 * (POSIX shell scripts) cover the ASCII temporary name, non-zero exit, and
 * timeout termination on every POSIX host.
 */
import { execFileSync } from 'node:child_process'
import { chmodSync, copyFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Context } from '@deepseek-ai/cordis'
import { afterEach, describe, expect, it } from 'vitest'
import * as ToolCad from '../src/index.ts'
import type { Config } from '../src/index.ts'
import { samplePlanDxf } from './sample-plan.ts'
import { call, tempDir, text, toolContext, valueOf } from './support.ts'

const FIXTURE = fileURLToPath(new URL('./fixtures/fixture_t3.dwg', import.meta.url))
const BUNDLED = fileURLToPath(new URL(`../bin/${process.platform}-${process.arch}/${process.platform === 'win32' ? 'dwg2dxf.exe' : 'dwg2dxf'}`, import.meta.url))
const POSIX = process.platform !== 'win32'

function onPath(): boolean {
  try {
    execFileSync(POSIX ? 'which' : 'where', ['dwg2dxf'], { stdio: 'ignore' })
    return true
  } catch (error) {
    // Not on PATH.
    void error
    return false
  }
}

const REAL = (process.env.DWG2DXF_BIN !== undefined && existsSync(process.env.DWG2DXF_BIN)) || existsSync(BUNDLED) || onPath()

const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => {
  while (cleanups.length > 0) await cleanups.pop()!()
})

async function mount(config: Partial<Config>): Promise<{ ctx: Context; dir: string }> {
  const tmp = tempDir('dwg')
  cleanups.push(tmp.cleanup)
  const dir = join(tmp.path, '图纸 目录')
  mkdirSync(dir, { recursive: true })
  const ctx = await toolContext()
  cleanups.push(() => ctx.fiber.dispose())
  await ctx.plugin(ToolCad, config)
  return { ctx, dir }
}

interface Open { doc: string; format: string; encoding: string; converter: { path: string; version: string | null } | null; counts: { entities: number; texts: number; layers: number }; codepage: string | null; unit: { status: string; evidence: string }; warnings: string[] }

describe.skipIf(!REAL)('real dwg2dxf (LibreDWG)', () => {
  it('converts the Tianzheng T3 fixture from a Chinese path with spaces', async () => {
    const { ctx, dir } = await mount({})
    const target = join(dir, '天正 样图 T3.dwg')
    copyFileSync(FIXTURE, target)
    const v = valueOf<Open>(await call(ctx, 'cad_open', { path: target }))
    expect(v.format).toBe('dwg')
    expect(v.converter?.version).toMatch(/0\.1[34]/u)
    // Ranges leave room for LibreDWG 0.13.4 versus 0.14 output differences.
    expect(v.counts.entities).toBeGreaterThanOrEqual(300)
    expect(v.counts.layers).toBeGreaterThanOrEqual(3)
    // LibreDWG 0.14 yields 125 texts (76 TEXT, 49 dimension MTEXT), 19 of them Chinese, and 49 dimensions.
    expect(v.counts.texts).toBeGreaterThanOrEqual(100)
    expect(v.counts.texts).toBeLessThanOrEqual(400)
    expect(v.codepage).toBe('ANSI_936')
    const cjk = valueOf<{ total: number; rows: Array<{ text: string }> }>(await call(ctx, 'cad_text_search', { doc: v.doc, regex: '[\\u4e00-\\u9fff]', limit: 50 }))
    expect(cjk.total).toBeGreaterThanOrEqual(10)
    expect(cjk.rows.every(r => !r.text.includes('\uFFFD'))).toBe(true)
    expect(v.unit).toMatchObject({ status: 'unconfirmed' })
    expect(valueOf<{ method: string; unit: string }>(await call(ctx, 'cad_set_unit', { doc: v.doc, verify: true }))).toMatchObject({ method: '尺寸比对', unit: 'mm' })
    const frames = valueOf<{ frames: Array<{ id: string }> }>(await call(ctx, 'cad_frames', { doc: v.doc }))
    expect(frames.frames.length).toBeGreaterThanOrEqual(1)
    const overview = valueOf<{ path: string }>(await call(ctx, 'cad_render', { doc: v.doc, frame: frames.frames[0]!.id }))
    expect(existsSync(overview.path)).toBe(true)
  })
})

describe.skipIf(!POSIX)('stand-in converters', () => {
  function script(dir: string, name: string, body: string): string {
    const path = join(dir, name)
    writeFileSync(path, `#!/bin/sh\nif [ "$1" = "--version" ]; then echo "dwg2dxf 0.0-test"; exit 0; fi\n${body}\n`)
    chmodSync(path, 0o755)
    return path
  }

  it('passes an ASCII temporary copy and reads the converted DXF', async () => {
    const bins = tempDir('bin')
    cleanups.push(bins.cleanup)
    const dxf = join(bins.path, 'converted.dxf')
    writeFileSync(dxf, samplePlanDxf(4))
    const bin = script(bins.path, 'dwg2dxf', `case "$4" in */in.dwg) ;; *) echo "bad input $4" >&2; exit 3 ;; esac\ncp "${dxf}" "$3"`)
    const { ctx, dir } = await mount({ dwg2dxfPath: bin })
    const target = join(dir, '一层 平面图.dwg')
    copyFileSync(FIXTURE, target)
    const v = valueOf<Open>(await call(ctx, 'cad_open', { path: target }))
    expect(v).toMatchObject({ format: 'dwg', converter: { path: bin, version: 'dwg2dxf 0.0-test' } })
    expect(v.counts.texts).toBeGreaterThan(10)
  })

  it('reports a non-zero exit with the stderr tail', async () => {
    const bins = tempDir('bin')
    cleanups.push(bins.cleanup)
    const bin = script(bins.path, 'dwg2dxf', 'echo "ERROR: unsupported DWG version" >&2\nexit 2')
    const { ctx, dir } = await mount({ dwg2dxfPath: bin })
    const target = join(dir, 'x.dwg')
    copyFileSync(FIXTURE, target)
    const result = await call(ctx, 'cad_open', { path: target })
    expect(result.isError).toBe(true)
    expect(text(result)).toContain('exit=2')
    expect(text(result)).toContain('unsupported DWG version')
  })

  it('terminates a converter that exceeds the time limit', async () => {
    const bins = tempDir('bin')
    cleanups.push(bins.cleanup)
    const bin = script(bins.path, 'dwg2dxf', 'sleep 30')
    const { ctx, dir } = await mount({ dwg2dxfPath: bin, dwg2dxfTimeoutMs: 1000 })
    const target = join(dir, 'slow.dwg')
    copyFileSync(FIXTURE, target)
    const started = Date.now()
    const result = await call(ctx, 'cad_open', { path: target })
    expect(result.isError).toBe(true)
    expect(text(result)).toContain('秒未完成')
    expect(Date.now() - started).toBeLessThan(15_000)
  })
})
