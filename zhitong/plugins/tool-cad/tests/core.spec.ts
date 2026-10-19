/**
 * Synthetic-scene cases migrated from tiangong-cad-viewer `tests/unit.test.mts`
 * (ShxTextEngine, aciToRgb, cleanDxfText, detectFrames/pointFrame,
 * checkRooms, countBlocks/blocksToSchema, diffScenes). The ReviewStore cases
 * are not migrated because the review store is not part of this plugin.
 * Frame and room criteria are passed explicitly with the source defaults.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { aciToRgb } from '../src/core/aci.ts'
import { diffScenes } from '../src/core/diff.ts'
import type { LabelledRect, UnitMeta } from '../src/core/extract.ts'
import { blocksToSchema, countBlocks } from '../src/core/extract.ts'
import type { FrameCriteria } from '../src/core/frames.ts'
import { detectFrames, pointFrame } from '../src/core/frames.ts'
import { checkRooms } from '../src/core/roomCheck.ts'
import { cleanDxfText } from '../src/core/sceneBuilder.ts'
import { ShxTextEngine } from '../src/core/shxText.ts'
import { emptyScene, makeLayer, textItem } from './support.ts'

const UNIT_MM: UnitMeta = { unit: 'mm', insunits: 4, confirmed: true, confirmedAt: '2026-01-01T00:00:00Z', method: '$INSUNITS' }
const FRAMES: FrameCriteria = { gapMm: 30000, minAreaM2: 50, minPts: 30, layerHint: /WALL|墙|轴|AXIS|DOTE|COLUMN|柱/i, pointCap: 300_000, mmPerUnit: 1 }
const ROOMS = { anchorLayers: ['TXTROOM'], minAreaM2: 1, maxAreaM2: 2000, maxLabelLength: 12 }
const KST32B = fileURLToPath(new URL('../assets/fonts/kst32b.shx', import.meta.url))

describe('ShxTextEngine', () => {
  it('loads KST32B, falls back on missing glyphs, and lays out strokes', () => {
    const engine = new ShxTextEngine()
    expect(engine.textSegments({ x: 0, y: 0, h: 300, rot: 0, str: '楼梯' })).toBeNull()

    const buf = readFileSync(KST32B)
    const info = engine.loadFont('kst32b', buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength))
    expect(info.type).toBe('unifont')

    const t = { x: 10000, y: 20000, h: 300, rot: 0, str: '楼梯A1' }
    const segs = engine.textSegments(t)!
    expect(segs.length).toBeGreaterThan(40)
    let minX = 1e9
    let maxX = -1e9
    let minY = 1e9
    let maxY = -1e9
    for (let i = 0; i + 3 < segs.length; i += 4) {
      minX = Math.min(minX, segs[i]!, segs[i + 2]!)
      maxX = Math.max(maxX, segs[i]!, segs[i + 2]!)
      minY = Math.min(minY, segs[i + 1]!, segs[i + 3]!)
      maxY = Math.max(maxY, segs[i + 1]!, segs[i + 3]!)
    }
    expect(Math.abs(minX - t.x)).toBeLessThan(t.h)
    expect(maxY - minY).toBeLessThanOrEqual(t.h * 1.2)
    expect(maxY - minY).toBeGreaterThan(t.h * 0.3)
    expect(maxX - minX).toBeGreaterThan(t.h * 2)

    // KST32B lacks the simplified-only 图, so the whole text falls back.
    expect(engine.textSegments({ x: 0, y: 0, h: 300, rot: 0, str: '楼梯详图' })).toBeNull()

    const rot = engine.textSegments({ x: 0, y: 0, h: 300, rot: Math.PI / 2, str: 'A1' })!
    let rMinX = 1e9
    let rMaxX = -1e9
    let rMinY = 1e9
    let rMaxY = -1e9
    for (let i = 0; i + 3 < rot.length; i += 4) {
      rMinX = Math.min(rMinX, rot[i]!, rot[i + 2]!)
      rMaxX = Math.max(rMaxX, rot[i]!, rot[i + 2]!)
      rMinY = Math.min(rMinY, rot[i + 1]!, rot[i + 3]!)
      rMaxY = Math.max(rMaxY, rot[i + 1]!, rot[i + 3]!)
    }
    expect(rMaxY - rMinY).toBeGreaterThan(rMaxX - rMinX)
  })
})

describe('aciToRgb and cleanDxfText', () => {
  it('maps standard ACI indices exactly', () => {
    expect(aciToRgb(1)).toBe(0xff0000)
    expect(aciToRgb(7)).toBe(0xffffff)
    expect(aciToRgb(256)).toBe(0xffffff)
  })

  it('strips MTEXT control codes', () => {
    expect(cleanDxfText('%%c150')).toBe('Ø150')
    expect(cleanDxfText('第一行\\P第二行')).toBe('第一行 第二行')
    expect(cleanDxfText('{\\f宋体;正常文字}')).toBe('正常文字')
  })
})

describe('detectFrames and pointFrame', () => {
  it('splits two drawings separated by more than the 30 m gap', () => {
    const segsA: Array<[number, number, number, number]> = []
    const segsB: Array<[number, number, number, number]> = []
    for (let i = 0; i < 20; i++) {
      const x = i * 1000
      const y = (i % 5) * 4000
      segsA.push([x, y, x + 50, y + 50])
      segsB.push([x + 60000, y, x + 60050, y + 50])
    }
    const scene = emptyScene({ layers: [makeLayer('WALL', [...segsA, ...segsB])] })
    const { frames } = detectFrames(scene, FRAMES)
    expect(frames).toHaveLength(2)
    expect([frames[0]!.x1, frames[0]!.x2, frames[0]!.y1, frames[0]!.y2]).toEqual([0, 19050, 0, 16050])
    expect([frames[1]!.x1, frames[1]!.x2, frames[1]!.y1, frames[1]!.y2]).toEqual([60000, 79050, 0, 16050])
    expect(pointFrame(frames, 5000, 5000)?.id).toBe(frames[0]!.id)
    expect(pointFrame(frames, 65000, 5000)?.id).toBe(frames[1]!.id)
    expect(pointFrame(frames, 40000, 5000)).toBeNull()
  })

  it('yields no frame below MIN_PTS', () => {
    const scene = emptyScene({ layers: [makeLayer('WALL', [[0, 0, 100, 0]])] })
    expect(detectFrames(scene, FRAMES).frames).toEqual([])
  })

  it('scales the gap and area by the drawing unit', () => {
    const segs: Array<[number, number, number, number]> = []
    for (let i = 0; i < 20; i++) segs.push([i, (i % 5) * 4, i + 0.05, (i % 5) * 4 + 0.05], [i + 60, (i % 5) * 4, i + 60.05, (i % 5) * 4 + 0.05])
    const scene = emptyScene({ layers: [makeLayer('WALL', segs)] })
    expect(detectFrames(scene, { ...FRAMES, mmPerUnit: 1000 }).frames).toHaveLength(2)
  })
})

describe('checkRooms', () => {
  it('agrees when the text area equals the polygon area', () => {
    const square = [0, 0, 10000, 0, 10000, 10000, 0, 10000]
    const scene = emptyScene({
      polys: [{ pts: square, layer: 'WALL', handle: 'P1' }],
      texts: [textItem('厨房', 5000, 5000, 'TXTROOM'), textItem('100.00', 5000, 6000, 'PUB_TEXT', 250)],
    })
    const res = checkRooms(scene, 1, ROOMS)
    expect(res).toHaveLength(1)
    expect(res[0]).toMatchObject({ label: '厨房', geomM2: 100, textM2: 100, diffPct: 0, polyHandle: 'P1' })
  })

  it('falls back to the geometric area when the area text is missing', () => {
    const rect = [0, 0, 8000, 0, 8000, 6000, 0, 6000]
    const scene = emptyScene({ polys: [{ pts: rect, layer: 'WALL', handle: 'P1' }], texts: [textItem('开水间', 4000, 3000, 'TXTROOM')] })
    const res = checkRooms(scene, 1, ROOMS)
    expect(res).toHaveLength(1)
    expect(res[0]).toMatchObject({ geomM2: 48, textM2: null, diffPct: null })
  })

  it('uses the configured anchor layers', () => {
    const rect = [0, 0, 8000, 0, 8000, 6000, 0, 6000]
    const scene = emptyScene({ polys: [{ pts: rect, layer: 'WALL', handle: 'P1' }], texts: [textItem('开水间', 4000, 3000, 'ROOM_NAME')] })
    expect(checkRooms(scene, 1, ROOMS)).toEqual([])
    expect(checkRooms(scene, 1, { ...ROOMS, anchorLayers: ['ROOM_NAME'] })).toHaveLength(1)
  })
})

describe('countBlocks and blocksToSchema', () => {
  it('maps the vocabulary, groups by frame, and skips anonymous blocks', () => {
    const ins = (name: string, x: number, y: number, layer: string) => ({ name, x, y, layer, handle: 'H', depth: 0, parent: null, rot: 0 })
    const scene = emptyScene({
      inserts: [ins('防火门', 100, 100, 'DOOR'), ins('防火门', 65000, 100, 'DOOR'), ins('窗A', 100, 200, 'WIN'), ins('*U1', 0, 0, '0')],
    })
    const frames: LabelledRect[] = [
      { label: '1F', x1: 0, y1: 0, x2: 20000, y2: 20000 },
      { label: '2F', x1: 60000, y1: 0, x2: 80000, y2: 20000 },
    ]
    const counts = countBlocks(scene, frames)
    expect(counts).toHaveLength(2)
    const door = counts.find(c => c.name === '防火门')!
    expect(door.count).toBe(2)
    expect(door.perFrame).toEqual({ '1F': 1, '2F': 1 })

    const schema = blocksToSchema(counts, 'test.dxf', UNIT_MM)
    expect(schema.meta.unit).toBe('mm')
    expect(schema.meta.file).toBe('test.dxf')
    const doorItems = schema.items.filter(it => it.sourceRef.rawExcerpt === '防火门')
    expect(doorItems).toHaveLength(2)
    expect(doorItems[0]!.componentCategory).toBe('门')
    expect(doorItems.reduce((s, it) => s + it.rawMeasures.count, 0)).toBe(2)
    expect(schema.items.find(it => it.sourceRef.rawExcerpt === '窗A')!.componentCategory).toBe('窗')

    const countsNoFrame = countBlocks(scene)
    expect(countsNoFrame.find(c => c.name === '防火门')!.perFrame).toEqual({})
    const doorNF = blocksToSchema(countsNoFrame, 'test.dxf', UNIT_MM).items.find(it => it.sourceRef.rawExcerpt === '防火门')!
    expect(doorNF.rawMeasures.count).toBe(2)
    expect(doorNF.params.frameId).toBeUndefined()
  })
})

describe('diffScenes', () => {
  it('classifies added, removed, and unchanged segments by quantized geometry', () => {
    const shared: [number, number, number, number] = [0, 0, 1000, 0]
    const oldScene = emptyScene({ layers: [makeLayer('0', [shared, [0, 0, 0, 1000]])] })
    const newScene = emptyScene({ layers: [makeLayer('0', [shared, [2000, 0, 3000, 0]])] })
    const result = diffScenes(oldScene, newScene, 1)
    expect(result.counts).toEqual({ unchanged: 1, removed: 1, added: 1 })
    expect(result.offset).toBeUndefined()
    expect(result.scene.layers).toHaveLength(3)
  })
})
