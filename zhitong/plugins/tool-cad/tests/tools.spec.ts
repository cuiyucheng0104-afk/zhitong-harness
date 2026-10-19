/**
 * Tool-level behavior through the tool registry with the local subprocess
 * provider, on the synthetic plan stored under a directory whose name holds
 * Chinese characters and spaces.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { createCanvas, loadImage } from '@napi-rs/canvas'
import type { Context } from '@deepseek-ai/cordis'
import { afterEach, describe, expect, it } from 'vitest'
import * as ToolCad from '../src/index.ts'
import type { Config } from '../src/index.ts'
import { PLAN, samplePlanDxf } from './sample-plan.ts'
import { call, tempDir, text, toolContext, valueOf } from './support.ts'

const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => {
  while (cleanups.length > 0) await cleanups.pop()!()
})

async function context(): Promise<Context> {
  const ctx = await toolContext()
  cleanups.push(() => ctx.fiber.dispose())
  return ctx
}

async function setup(options: { insunits?: number; config?: Partial<Config> } = {}): Promise<{ ctx: Context; dir: string; file: string }> {
  const tmp = tempDir('cad')
  cleanups.push(tmp.cleanup)
  const dir = join(tmp.path, '项目 图纸', '一期')
  mkdirSync(dir, { recursive: true })
  const file = join(dir, '一层 平面图.dxf')
  writeFileSync(file, samplePlanDxf(options.insunits))
  const ctx = await context()
  await ctx.plugin(ToolCad, { ...options.config })
  return { ctx, dir, file }
}

interface Open { doc: string; format: string; encoding: string; unit: { status: string; unit: string; evidence: string }; frames: { ids: string[] }; cache: { hit: boolean; path: string | null }; counts: { texts: number } }
interface Frames { frames: Array<{ id: string; kind: string; paper: string | null; name: { value: string; ref: string } | null; number: { value: string } | null; scale: { value: string } | null; floor: string | null; area_m2: number | null }> }
interface TextRows { total: number; truncated: boolean; file: string | null; rows: Array<{ id: string; ids?: string[]; text: string; frame: string | null; handle: string }> }
interface Render { path: string; image_size: [number, number]; world_rect: { x1: number; y1: number; x2: number; y2: number }; px_per_unit: number; grid: { cols: number; rows: number } | null; labels: Array<{ n: number; id: string; text: string }>; hidden_layers: string[]; stats: { texts_boxed: number; texts_shx: number; texts_font: number } }

async function nonWhiteRatio(path: string): Promise<{ width: number; height: number; ratio: number }> {
  const img = await loadImage(readFileSync(path))
  const canvas = createCanvas(img.width, img.height)
  const g = canvas.getContext('2d')
  g.drawImage(img, 0, 0)
  const data = g.getImageData(0, 0, img.width, img.height).data
  let ink = 0
  for (let i = 0; i < data.length; i += 4) if (data[i]! < 240 || data[i + 1]! < 240 || data[i + 2]! < 240) ink++
  return { width: img.width, height: img.height, ratio: ink / (img.width * img.height) }
}

describe('cad_open', () => {
  it('opens a DXF under a Chinese path with spaces and reuses the cache on reopen', async () => {
    const { ctx, dir, file } = await setup({ insunits: 4 })
    const first = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    expect(first).toMatchObject({ format: 'dxf', encoding: 'utf-8', unit: { status: 'confirmed', unit: 'mm' }, cache: { hit: false } })
    expect(first.frames.ids).toEqual(['S1', 'F1'])
    expect(first.cache.path).toContain(join(dir, '.cache'))
    expect(existsSync(first.cache.path!)).toBe(true)
    const second = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    expect(second.doc).toBe(first.doc)
    expect(second.cache.hit).toBe(true)
    expect(second.counts.texts).toBe(first.counts.texts)
  })

  it('rejects relative and missing paths', async () => {
    const { ctx, dir } = await setup()
    expect(text(await call(ctx, 'cad_open', { path: 'a.dxf' }))).toContain('绝对路径')
    expect(text(await call(ctx, 'cad_open', { path: join(dir, '没有.dxf') }))).toContain('文件不存在')
  })

  it('fails a DWG with an explicit message when dwg2dxf is configured but absent', async () => {
    const { ctx, dir } = await setup({ config: { dwg2dxfPath: '/nonexistent/dwg2dxf' } })
    const dwg = join(dir, '假.dxf')
    writeFileSync(dwg, Buffer.concat([Buffer.from('AC1018', 'latin1'), Buffer.alloc(64)]))
    const result = await call(ctx, 'cad_open', { path: dwg })
    expect(result.isError).toBe(true)
    expect(text(result)).toContain('dwg2dxf')
  })
})

describe('reading tools', () => {
  it('lists frames with title-block guesses', async () => {
    const { ctx, file } = await setup({ insunits: 4 })
    const { doc } = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    const { frames } = valueOf<Frames>(await call(ctx, 'cad_frames', { doc }))
    expect(frames.map(f => [f.id, f.kind])).toEqual([['S1', 'sheet'], ['F1', 'cluster']])
    expect(frames[0]).toMatchObject({ paper: 'A1', floor: '1F', name: { value: '一层平面图' }, number: { value: '建施-03' }, scale: { value: '1:100' } })
    expect(frames[0]!.area_m2).toBeCloseTo(84.1 * 59.4, 0)
    expect(frames[1]).toMatchObject({ floor: '2F', name: { value: '二层平面图' } })
  })

  it('searches texts by frame, layer, and regex, spilling past the limit', async () => {
    const { ctx, file } = await setup({ insunits: 4 })
    const { doc } = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    const plans = valueOf<TextRows>(await call(ctx, 'cad_text_search', { doc, regex: '平面图$' }))
    expect(plans.rows.map(r => [r.text, r.frame])).toEqual([['一层平面图', 'S1'], ['二层平面图', 'F1']])
    const labels = valueOf<TextRows>(await call(ctx, 'cad_text_search', { doc, frame: 'S1', layers: ['WINDOW_TEXT'], limit: 2 }))
    expect(labels).toMatchObject({ total: 5, truncated: true })
    expect(labels.rows).toHaveLength(2)
    expect(readFileSync(labels.file!, 'utf8').trim().split('\n')).toHaveLength(6)
    const bad = await call(ctx, 'cad_text_search', { doc, regex: '(' })
    expect(bad.isError).toBe(true)
  })

  it('counts blocks and door/window labels per frame', async () => {
    const { ctx, file } = await setup({ insunits: 4 })
    const { doc } = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    const v = valueOf<{ blocks: Array<{ name: string; count: number; nested: number; per_frame: Record<string, number> }>; labels: Array<{ label: string; count: number }>; file: string; needs_manual: boolean }>(
      await call(ctx, 'cad_blocks', { doc }),
    )
    expect(v.blocks.find(b => b.name === 'M1021')).toMatchObject({ count: PLAN.doors, nested: 0, per_frame: { S1: 3 } })
    expect(v.blocks.find(b => b.name === 'C1518')).toMatchObject({ count: 3, nested: 1 })
    expect(v.labels.map(l => [l.label, l.count])).toEqual([['M1021', 3], ['C1518', 2]])
    expect(v.needs_manual).toBe(true)
    expect(readFileSync(v.file, 'utf8')).toContain('M1021')
  })

  it('reports layers with frozen state and samples', async () => {
    const { ctx, file } = await setup({ insunits: 4 })
    const { doc } = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    const v = valueOf<{ layers: Array<{ name: string; frozen: boolean; texts: number; samples: string[] }> }>(await call(ctx, 'cad_layers', { doc }))
    expect(v.layers.find(l => l.name === 'HIDDEN_NOTE')).toMatchObject({ frozen: true, texts: 1, samples: ['冻结图层说明'] })
  })
})

describe('unit gate', () => {
  it('refuses room areas until the unit is confirmed, then answers', async () => {
    const { ctx, file } = await setup()
    const opened = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    expect(opened.unit.status).toBe('unconfirmed')
    const refused = await call(ctx, 'cad_rooms', { doc: opened.doc })
    expect(refused.isError).toBe(true)
    expect(text(refused)).toContain('单位未确认')
    expect(text(refused)).toContain('指向 mm')
    expect((await call(ctx, 'cad_set_unit', { doc: opened.doc, unit: 'mm' })).isError).toBe(true)
    const set = valueOf<{ status: string; method: string }>(await call(ctx, 'cad_set_unit', { doc: opened.doc, verify: true }))
    expect(set).toMatchObject({ status: 'confirmed', method: '尺寸比对' })
    const rooms = valueOf<{ matched: number; rooms: Array<{ label: string; text_m2: number | null; geom_m2: number; diff_pct: number | null }> }>(await call(ctx, 'cad_rooms', { doc: opened.doc }))
    expect(rooms.matched).toBe(2)
    expect(rooms.rooms).toEqual(expect.arrayContaining([
      expect.objectContaining({ label: PLAN.room1.name, text_m2: 30, geom_m2: 30, diff_pct: 0 }),
      expect.objectContaining({ label: PLAN.room2.name, text_m2: 19.5, geom_m2: 20, diff_pct: 2.56 }),
    ]))
    // The confirmation persists across sessions for the same file.
    const ctx2 = await context()
    await ctx2.plugin(ToolCad, {})
    expect(valueOf<Open>(await call(ctx2, 'cad_open', { path: file })).unit).toMatchObject({ status: 'confirmed', unit: 'mm' })
  })
})

describe('cad_table and cad_diff', () => {
  it('finds the door/window schedule and writes CSV', async () => {
    const { ctx, file } = await setup({ insunits: 4 })
    const { doc } = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    const v = valueOf<{ tables: Array<{ kind: string | null; title: string | null; n_rows: number; n_cols: number; rows: string[][]; csv: string | null }> }>(await call(ctx, 'cad_table', { doc, frame: 'S1' }))
    expect(v.tables).toHaveLength(1)
    expect(v.tables[0]).toMatchObject({ kind: '门窗表', title: '门窗表', n_rows: 3, n_cols: 5 })
    expect(readFileSync(v.tables[0]!.csv!, 'utf8')).toContain('C1518,1500×1800,2,,断桥铝')
    const byRect = valueOf<{ tables: Array<{ n_rows: number }> }>(await call(ctx, 'cad_table', { doc, rect: PLAN.table }))
    expect(byRect.tables[0]!.n_rows).toBe(3)
  })

  it('compares two revisions', async () => {
    const { ctx, dir, file } = await setup({ insunits: 4 })
    const revised = join(dir, '一层 平面图 v2.dxf')
    writeFileSync(revised, samplePlanDxf(4).replace('建施-03', '建施-03A'))
    const a = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    const b = valueOf<Open>(await call(ctx, 'cad_open', { path: revised }))
    const v = valueOf<{ segments: { added: number; removed: number }; texts_added: Array<{ text: string }>; texts_removed: Array<{ text: string }>; image: { path: string } | null }>(
      await call(ctx, 'cad_diff', { old_doc: a.doc, new_doc: b.doc, render: true }),
    )
    expect(v.segments).toMatchObject({ added: 0, removed: 0 })
    expect(v.texts_added).toEqual([{ text: '建施-03A', count: 1 }])
    expect(v.texts_removed).toEqual([{ text: '建施-03', count: 1 }])
    expect(existsSync(v.image!.path)).toBe(true)
  })
})

describe('cad_render', () => {
  it('renders a frame overview with a grid, then zooms into a cell', async () => {
    const { ctx, file } = await setup({ insunits: 4 })
    const { doc } = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    const overview = valueOf<Render>(await call(ctx, 'cad_render', { doc, frame: 'S1' }))
    expect(Math.max(...overview.image_size)).toBeLessThanOrEqual(1600)
    expect(overview.grid).toMatchObject({ cols: 8, rows: 6 })
    expect(overview.hidden_layers).toContain('HIDDEN_NOTE')
    expect(overview.stats.texts_boxed).toBeGreaterThan(5)
    const img = await nonWhiteRatio(overview.path)
    expect([img.width, img.height]).toEqual(overview.image_size)
    expect(img.ratio).toBeGreaterThan(0.002)
    expect(img.ratio).toBeLessThan(0.5)
    // Pixel ↔ world mapping round trip for the sheet's top-left corner.
    const s = overview.px_per_unit
    expect((PLAN.sheet.x1 - overview.world_rect.x1) * s).toBeGreaterThan(0)
    expect((overview.world_rect.y2 - PLAN.sheet.y2) * s).toBeGreaterThan(0)

    const zoom = valueOf<Render>(await call(ctx, 'cad_render', { doc, frame: 'S1', cell: 'G6' }))
    expect(zoom.grid).toBeNull()
    expect(zoom.stats.texts_shx + zoom.stats.texts_font).toBeGreaterThan(0)
    expect((await nonWhiteRatio(zoom.path)).ratio).toBeGreaterThan(0.001)
  })

  it('numbers text boxes in ids mode and maps numbers to text ids', async () => {
    const { ctx, file } = await setup({ insunits: 4 })
    const { doc } = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    const v = valueOf<Render>(await call(ctx, 'cad_render', { doc, rect: PLAN.table, text: 'ids' }))
    expect(v.labels.length).toBeGreaterThanOrEqual(12)
    expect(v.labels[0]).toMatchObject({ n: 1, text: '门窗表' })
    expect(v.labels.every(l => /^T\d+$/.test(l.id))).toBe(true)
  })

  it('refuses whole-drawing and oversized zoom renders', async () => {
    const { ctx, file } = await setup({ insunits: 4 })
    const { doc } = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    const none = await call(ctx, 'cad_render', { doc })
    expect(none.isError).toBe(true)
    expect(text(none)).toContain('cad_frames')
    const big = await call(ctx, 'cad_render', { doc, rect: PLAN.sheet })
    expect(big.isError).toBe(true)
    expect(text(big)).toContain('cell')
    expect((await call(ctx, 'cad_render', { doc, frame: 'S1', cell: 'Z9' })).isError).toBe(true)
  })

  it('zooms around a text id and a handle', async () => {
    const { ctx, file } = await setup({ insunits: 4 })
    const { doc } = valueOf<Open>(await call(ctx, 'cad_open', { path: file }))
    const hit = valueOf<TextRows>(await call(ctx, 'cad_text_search', { doc, query: '厨房' })).rows[0]!
    const byText = valueOf<Render>(await call(ctx, 'cad_render', { doc, text_id: hit.id }))
    expect(byText.world_rect.x1).toBeLessThan(18000)
    expect(byText.world_rect.x2).toBeGreaterThan(18000)
    const byHandle = valueOf<Render>(await call(ctx, 'cad_render', { doc, handle: hit.handle }))
    expect(existsSync(byHandle.path)).toBe(true)
  })
})

describe('plugin lifecycle', () => {
  it('unregisters every tool when the plugin is disposed', async () => {
    const ctx = await context()
    const fiber = await ctx.plugin(ToolCad, {})
    const names = ['cad_open', 'cad_layers', 'cad_frames', 'cad_text_search', 'cad_blocks', 'cad_render', 'cad_set_unit', 'cad_rooms', 'cad_table', 'cad_diff']
    for (const n of names) expect(ctx.tools.get(n)).toBeDefined()
    await fiber.dispose()
    for (const n of names) expect(ctx.tools.get(n)).toBeUndefined()
  })

  it('fails loud at load when a font file is missing', () => {
    expect(() => ToolCad.resolveSpec({ fallbackFont: '/nonexistent/font.otf' })).toThrow('字体文件不存在')
  })
})
