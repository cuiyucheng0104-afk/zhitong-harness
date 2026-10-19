/**
 * DXF text → scene → heuristics, on the synthetic sample plan: scene summary
 * ranges, sniffing and decoding, sheets and title block, text grouping,
 * labels, table location, unit evidence, and the binary cache round trip.
 */
import DxfParser from 'dxf-parser'
import { describe, expect, it } from 'vitest'
import { decodeDxf, expandUnicodeEscapes, sniffFormat } from '../src/convert/sniff.ts'
import { parseHatches } from '../src/core/hatchParser.ts'
import { countLabels } from '../src/core/labels.ts'
import type { BuiltScene, DxfDocument } from '../src/core/sceneBuilder.ts'
import { buildScene } from '../src/core/sceneBuilder.ts'
import { detectSheets, guessFloor, parseNumeral, readTitleBlock } from '../src/core/sheets.ts'
import { locateTables } from '../src/core/tables.ts'
import { filterTexts, groupLines } from '../src/core/textQuery.ts'
import { deriveUnit, unitEvidence } from '../src/core/unit.ts'
import { deserializeScene, serializeScene } from '../src/store/sceneCache.ts'
import { PLAN, samplePlanDxf } from './sample-plan.ts'
import { emptyScene, textItem } from './support.ts'

function sceneOf(text: string): BuiltScene {
  const dxf = new DxfParser().parseSync(text) as DxfDocument
  const layers = dxf.tables?.layer?.layers ?? {}
  return buildScene(dxf, 0, parseHatches(text, n => layers[n]?.color ?? 0xffffff).layers)
}

const TITLE_OPTIONS = {
  fieldLabels: ['工程名称', '图名', '比例', '日期'],
  numberPattern: /^(?:建施|结施|[A-Z]{1,3})[-－—]?\d{1,3}(?:[-－—.]\d{1,3})?[A-Za-z]?$/u,
}

describe('sample plan scene', () => {
  const scene = sceneOf(samplePlanDxf(4))

  it('summarizes within the expected ranges', () => {
    expect(scene.header).toMatchObject({ insunits: 4, acadver: 'AC1015' })
    expect(scene.stats.entityCount).toBeGreaterThanOrEqual(80)
    expect(scene.stats.entityCount).toBeLessThan(200)
    expect(scene.texts.some(t => t.str === '一层平面图')).toBe(true)
    expect(scene.texts.filter(t => /[一-鿿]/u.test(t.str)).length).toBeGreaterThanOrEqual(10)
    expect(scene.layers.map(l => l.name)).toEqual(expect.arrayContaining(['TK', 'WALL', 'TABLE', 'DIM']))
    expect(scene.hatches).toHaveLength(1)
    expect(scene.dims).toHaveLength(6)
    expect(scene.dims.every(d => d.shown === d.measured)).toBe(true)
    expect(scene.layerTable.find(l => l.name === 'HIDDEN_NOTE')).toMatchObject({ frozen: true })
  })

  it('records nested inserts with depth and the top-level handle', () => {
    const windows = scene.inserts.filter(i => i.name === 'C1518')
    expect(windows).toHaveLength(PLAN.windowsTop + PLAN.windowsNested)
    const nested = windows.find(i => i.depth === 1)!
    const unit = scene.inserts.find(i => i.name === 'UNIT')!
    expect(nested.handle).toBe(unit.handle)
    expect(nested.x).toBe(36000)
  })

  it('detects the A1 sheet border at 1:100 and drops the inner border', () => {
    const sheets = detectSheets(scene, 1)
    expect(sheets).toHaveLength(1)
    expect(sheets[0]).toMatchObject({ ...PLAN.sheet, paper: 'A1', scale: 100, lengthened: false })
    expect(detectSheets(scene, 1000)).toEqual([])
  })

  it('reads the title block', () => {
    const tb = readTitleBlock(scene, PLAN.sheet, TITLE_OPTIONS)
    expect(tb.name?.value).toBe('一层平面图')
    expect(tb.scale).toMatchObject({ value: '1:100', denominator: 100 })
    expect(tb.number?.value).toBe('建施-03')
    expect(tb.floor).toMatchObject({ label: '1F', confidence: 'high' })
    expect(tb.fields['工程名称']?.value).toBe('某小区一期 1#楼')
    expect(scene.texts[tb.name!.textId]!.str).toBe('一层平面图')
  })

  it('locates the door/window schedule and extracts its cells', () => {
    const tables = locateTables(scene, [{ kind: '门窗表', titles: ['门窗表'], headers: ['设计编号', '洞口尺寸', '数量', '图集', '备注'] }], null, 3)
    expect(tables).toHaveLength(1)
    const t = tables[0]!
    expect(t.title).toBe('门窗表')
    expect(t.rect.x1).toBeCloseTo(PLAN.table.x1)
    expect(t.rect.x2).toBeCloseTo(PLAN.table.x2)
    expect(t.rect.y1).toBeCloseTo(PLAN.table.y1)
    expect(t.table?.rows).toEqual([
      ['设计编号', '洞口尺寸', '数量', '图集', '备注'],
      ['M1021', '1000×2100', '3', '12J609', ''],
      ['C1518', '1500×1800', '2', '', '断桥铝'],
    ])
  })

  it('counts door and window labels', () => {
    const labels = countLabels(scene.texts, filterTexts(scene.texts, { layers: new Set(['WINDOW_TEXT']) }), /^(?:M|C)\d{2,4}$/u, [])
    expect(labels.map(l => [l.label, l.count])).toEqual([['M1021', 3], ['C1518', 2]])
  })

  it('confirms millimetres from $INSUNITS and reports dimension evidence', () => {
    expect(deriveUnit(scene)).toMatchObject({ status: 'confirmed', unit: 'mm', method: '$INSUNITS' })
    const ev = unitEvidence(scene)
    expect(ev).toMatchObject({ dimensionSamples: 6, ratioMedian: 1, ratioAgreement: 1, suggestion: 'mm' })
    const bare = sceneOf(samplePlanDxf())
    expect(deriveUnit(bare)).toMatchObject({ status: 'unconfirmed', method: '待确认' })
  })

  it('round-trips through the binary cache', () => {
    const meta = { sha256: 'a'.repeat(64), format: 'dxf' as const, encoding: 'utf-8', escapes: 0, converter: null, hatchCount: 1, hatchSkipped: 0 }
    const back = deserializeScene(serializeScene({ meta, scene }))!
    expect(back.meta).toEqual(meta)
    expect(back.scene.texts).toEqual(scene.texts)
    expect(back.scene.layers.map(l => [l.name, l.segCount])).toEqual(scene.layers.map(l => [l.name, l.segCount]))
    expect(Array.from(back.scene.layers[0]!.positions)).toEqual(Array.from(scene.layers[0]!.positions))
    expect(back.scene.hatches[0]!.triCount).toBe(scene.hatches[0]!.triCount)
    expect(deserializeScene(Buffer.from('not a cache'))).toBeNull()
  })
})

describe('sniffing and decoding', () => {
  it('trusts the header over the extension', () => {
    expect(sniffFormat(Buffer.from('AC1021\0\0\0\0\0\0', 'latin1'))).toBe('dwg')
    expect(sniffFormat(Buffer.from('  0\nSECTION\n', 'latin1'))).toBe('dxf')
    expect(sniffFormat(Buffer.from('AutoCAD Binary DXF\r\n\x1a\0', 'latin1'))).toBe('dxf-binary')
  })

  it('decodes UTF-8, falls back to GBK, and expands escapes', () => {
    expect(decodeDxf(Buffer.from('  1\n一层平面图\n', 'utf8'))).toMatchObject({ text: '  1\n一层平面图\n', encoding: 'utf-8' })
    const gbk = Buffer.from([0x20, 0x31, 0x0a, 0xd2, 0xbb, 0xb2, 0xe3, 0x0a])
    expect(decodeDxf(gbk)).toMatchObject({ text: ' 1\n一层\n', encoding: 'gbk' })
    expect(decodeDxf(Buffer.from('ABC', 'latin1')).encoding).toBe('ascii')
    // GBK bytes written one escape per byte (LibreDWG 0.14 code-page names), and a real code point.
    expect(expandUnicodeEscapes('\\U+00D0\\U+00C2\\U+00BF\\U+00E9-A')).toEqual({ text: '新块-A', count: 4 })
    expect(expandUnicodeEscapes('\\U+03A618mm').text).toBe('Φ18mm')
  })
})

describe('text helpers', () => {
  it('groups fragments on one baseline into a line', () => {
    const texts = [textItem('二', 1000, 0, '0', 500), textItem('层平面图', 1550, 10, '0', 500), textItem('1:100', 5000, 0, '0', 300), textItem('其他', 1000, -3000)]
    const lines = groupLines(texts, [0, 1, 2, 3])
    expect(lines.map(l => l.str)).toEqual(['二层平面图', '1:100', '其他'])
    expect(lines[0]!.ids).toEqual([0, 1])
  })

  it('parses numerals and floor names', () => {
    expect(parseNumeral('十二')).toBe(12)
    expect(parseNumeral('二十')).toBe(20)
    expect(parseNumeral('7')).toBe(7)
    expect(guessFloor('地下一层平面图')).toMatchObject({ label: 'B1', confidence: 'high' })
    expect(guessFloor('二~五层平面图')?.label).toBe('2F~5F')
    expect(guessFloor('标准层平面图')?.label).toBe('标准层')
    expect(guessFloor('屋顶平面图')?.label).toBe('RF')
    expect(guessFloor('3F 平面')?.label).toBe('3F')
    expect(guessFloor('楼梯详图')).toBeNull()
  })

  it('reads a title-block number from the 图号 label', () => {
    const scene = emptyScene({ texts: [textItem('图号', 0, 0, '0', 300), textItem('JS-01', 1500, 0, '0', 300)] })
    expect(readTitleBlock(scene, { x1: -1000, y1: -1000, x2: 5000, y2: 1000 }, TITLE_OPTIONS).number?.value).toBe('JS-01')
  })
})
