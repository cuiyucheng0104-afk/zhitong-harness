/**
 * Open drawings of one plugin instance: path → (conversion) → DXF text →
 * scene, with the binary parse cache, the persisted unit state, and lazily
 * computed frames. Documents are addressed by a `doc` id derived from the
 * content hash, so reopening the same file yields the same id.
 * @module @zhitong/tool-cad/documents
 */
import { createHash } from 'node:crypto'
import { createReadStream } from 'node:fs'
import { mkdir, open, readFile, rename, stat, writeFile } from 'node:fs/promises'
import { dirname, isAbsolute, join } from 'node:path'
import type { SubprocessRuntime } from '@deepseek-ai/dsh-subprocess'
import DxfParser from 'dxf-parser'
import type { ToolCadSpec } from './config.ts'
import type { Dwg2DxfBinary } from './convert/dwg2dxf.ts'
import { convertDwg, readDwg2dxfVersion, resolveDwg2dxf } from './convert/dwg2dxf.ts'
import { decodeDxf, sniffFormat } from './convert/sniff.ts'
import { detectFrames } from './core/frames.ts'
import { estimateWidth } from './core/textQuery.ts'
import type { Rect } from './core/geometry.ts'
import { parseHatches } from './core/hatchParser.ts'
import type { BuiltScene, DxfDocument } from './core/sceneBuilder.ts'
import { buildScene } from './core/sceneBuilder.ts'
import type { SheetBorder } from './core/sheets.ts'
import { detectSheets } from './core/sheets.ts'
import type { UnitName, UnitState } from './core/unit.ts'
import { deriveUnit, MM_PER_UNIT } from './core/unit.ts'
import type { CacheMeta } from './store/sceneCache.ts'
import { cachePath, readSceneCache, writeSceneCache } from './store/sceneCache.ts'

/** One navigable region of a drawing. */
export interface DocFrame extends Rect {
  /** `S<n>` sheet border, `F<n>` drawing cluster (grown to the texts within the title margin), `W1` whole extent when nothing else was found. */
  id: string
  kind: 'sheet' | 'cluster' | 'extent'
  /** Paper size and implied scale for sheet borders. */
  sheet: Pick<SheetBorder, 'paper' | 'scale' | 'lengthened' | 'handle'> | null
}

/** Frame detection outcome for one unit. */
export interface DocFrames {
  unit: UnitName
  frames: DocFrame[]
  warnings: string[]
}

/** One open drawing. */
export interface CadDoc {
  id: string
  path: string
  meta: CacheMeta
  scene: BuiltScene
  cacheDir: string
  unit: UnitState
  /** Cache read/write facts of the open call that produced this document. */
  cache: { hit: boolean; path: string | null }
  warnings: string[]
  framesFor: DocFrames | null
}

/**
 * Validated unit record read from disk.
 * @param raw - parsed JSON.
 * @returns the unit state, or null when the record is malformed.
 */
function unitFromJson(raw: unknown): UnitState | null {
  if (typeof raw !== 'object' || raw === null) return null
  const r = raw as Record<string, unknown>
  const units: readonly string[] = ['mm', 'cm', 'm', 'in']
  const methods: readonly string[] = ['$INSUNITS', '人工确认', '尺寸比对', '待确认']
  if (r.status !== 'confirmed' && r.status !== 'unconfirmed') return null
  if (typeof r.unit !== 'string' || !units.includes(r.unit)) return null
  if (typeof r.method !== 'string' || !methods.includes(r.method)) return null
  return {
    status: r.status,
    unit: r.unit as UnitName,
    method: r.method as UnitState['method'],
    confirmedAt: typeof r.confirmedAt === 'string' ? r.confirmedAt : null,
    basis: typeof r.basis === 'string' ? r.basis : null,
  }
}

async function sha256File(path: string, signal: AbortSignal): Promise<string> {
  const hash = createHash('sha256')
  for await (const chunk of createReadStream(path, { signal })) hash.update(chunk as Buffer)
  return hash.digest('hex')
}

async function readHead(path: string): Promise<Uint8Array> {
  const fh = await open(path, 'r')
  try {
    const buf = Buffer.alloc(32)
    const { bytesRead } = await fh.read(buf, 0, 32, 0)
    return buf.subarray(0, bytesRead)
  } finally {
    await fh.close()
  }
}

/** Registry of open drawings. */
export class CadDocuments {
  private readonly docs = new Map<string, CadDoc>()
  private converter: Promise<Dwg2DxfBinary> | null = null

  constructor(private readonly spec: ToolCadSpec, private readonly subprocess: () => SubprocessRuntime) {}

  /**
   * An open document.
   * @param id - document id from `cad_open`.
   * @returns the document.
   * @throws when the id is not open in this session.
   */
  get(id: string): CadDoc {
    const doc = this.docs.get(id)
    if (doc === undefined) {
      const open = [...this.docs.keys()]
      throw new Error(`图纸 ${id} 未打开${open.length > 0 ? `（已打开：${open.join('、')}）` : ''}。请先用 cad_open 打开图纸文件`)
    }
    return doc
  }

  /**
   * Cache directory for a drawing.
   * @param path - drawing path.
   * @returns the configured directory, or `<drawing directory>/.cache`.
   */
  cacheDirFor(path: string): string {
    return this.spec.cacheDir ?? join(dirname(path), '.cache')
  }

  private async locateConverter(signal: AbortSignal): Promise<Dwg2DxfBinary> {
    if (this.converter === null) {
      const subprocess = this.subprocess()
      this.converter = (async () => {
        const found = await resolveDwg2dxf({
          configPath: this.spec.dwg2dxfPath,
          envPath: process.env.DWG2DXF_BIN,
          bundledRoot: this.spec.bundledBinRoot,
          platform: process.platform,
          arch: process.arch,
          subprocess,
          signal,
        })
        return { ...found, version: await readDwg2dxfVersion(found.path, subprocess, signal) }
      })()
      this.converter.catch(() => { this.converter = null })
    }
    return this.converter
  }

  /**
   * Open a drawing, reusing the parse cache unless forced.
   * @param path - absolute path of a DWG or DXF file.
   * @param force - rebuild the scene even when a cache entry exists.
   * @param signal - cancellation.
   * @returns the open document.
   */
  async open(path: string, force: boolean, signal: AbortSignal): Promise<CadDoc> {
    if (!isAbsolute(path)) throw new Error(`cad_open 需要绝对路径：${path}`)
    let size: number
    try {
      const info = await stat(path)
      if (!info.isFile()) throw new Error(`不是文件：${path}`)
      size = info.size
    } catch (error) {
      if (error instanceof Error && 'code' in error && error.code === 'ENOENT') throw new Error(`文件不存在：${path}`, { cause: error })
      throw error
    }
    const format = sniffFormat(await readHead(path))
    if (format === 'dxf-binary') throw new Error('这是二进制 DXF，暂不支持；请在 CAD 软件里另存为 ASCII DXF 或 DWG')
    const limit = format === 'dwg' ? this.spec.maxDwgBytes : this.spec.maxDxfBytes
    if (size > limit) throw new Error(`${format.toUpperCase()} 文件 ${Math.round(size / 1048576)} MB，超过上限 ${Math.round(limit / 1048576)} MB；请拆分图纸后再打开`)
    const sha256 = await sha256File(path, signal)
    const cacheDir = this.cacheDirFor(path)
    const warnings: string[] = []

    let entry = force ? null : await readSceneCache(cacheDir, sha256)
    const hit = entry !== null
    let written: string | null = hit ? cachePath(cacheDir, sha256) : null
    if (entry === null) {
      let bytes: Buffer
      let converter: CacheMeta['converter'] = null
      if (format === 'dwg') {
        const bin = await this.locateConverter(signal)
        bytes = await convertDwg({
          bin: bin.path,
          input: path,
          timeoutMs: this.spec.dwg2dxfTimeoutMs,
          maxDxfBytes: this.spec.maxDxfBytes,
          subprocess: this.subprocess(),
          signal,
        })
        converter = { path: bin.path, version: bin.version }
      } else {
        bytes = await readFile(path)
      }
      const decoded = decodeDxf(bytes)
      const t0 = performance.now()
      let dxf: DxfDocument | null
      try {
        dxf = new DxfParser().parseSync(decoded.text) as DxfDocument | null
      } catch (error) {
        throw new Error(`DXF 解析失败：${error instanceof Error ? error.message : String(error)}`, { cause: error })
      }
      if (dxf === null) throw new Error('DXF 解析失败：文件里没有可识别的 DXF 段')
      const parseMs = performance.now() - t0
      const layerRecords = dxf.tables?.layer?.layers ?? {}
      const layerRgb = (name: string): number => {
        const color = layerRecords[name]?.color
        return typeof color === 'number' ? color : 0xffffff
      }
      const hatch = parseHatches(decoded.text, layerRgb)
      const scene = buildScene(dxf, parseMs, hatch.layers)
      entry = {
        meta: { sha256, format, encoding: decoded.encoding, escapes: decoded.escapes, converter, hatchCount: hatch.count, hatchSkipped: hatch.skippedPaths },
        scene,
      }
      try {
        written = await writeSceneCache(cacheDir, entry)
      } catch (error) {
        written = null
        warnings.push(`解析缓存写入失败（${cacheDir}）：${error instanceof Error ? error.message : String(error)}；下次打开会重新解析`)
      }
    }

    const unit = (await this.readUnit(cacheDir, sha256)) ?? deriveUnit(entry.scene)
    const doc: CadDoc = {
      id: `d${sha256.slice(0, 12)}`,
      path,
      meta: entry.meta,
      scene: entry.scene,
      cacheDir,
      unit,
      cache: { hit, path: written },
      warnings,
      framesFor: null,
    }
    this.docs.set(doc.id, doc)
    return doc
  }

  private unitPath(cacheDir: string, sha256: string): string {
    return join(cacheDir, `${sha256}.unit.json`)
  }

  private async readUnit(cacheDir: string, sha256: string): Promise<UnitState | null> {
    let text: string
    try {
      text = await readFile(this.unitPath(cacheDir, sha256), 'utf8')
    } catch (error) {
      // No unit record yet: the header decides.
      void error
      return null
    }
    try {
      return unitFromJson(JSON.parse(text))
    } catch (error) {
      // A corrupt record is ignored; the header decides and the next confirmation rewrites it.
      void error
      return null
    }
  }

  /**
   * Record a unit decision for a document and persist it next to the parse cache.
   * @param doc - open document.
   * @param unit - new unit state.
   * @returns a warning when the record could not be written, otherwise null.
   */
  async setUnit(doc: CadDoc, unit: UnitState): Promise<string | null> {
    doc.unit = unit
    doc.framesFor = null
    try {
      await mkdir(doc.cacheDir, { recursive: true })
      const target = this.unitPath(doc.cacheDir, doc.meta.sha256)
      const tmp = `${target}.${process.pid}.tmp`
      await writeFile(tmp, `${JSON.stringify(unit, null, 2)}\n`, 'utf8')
      await rename(tmp, target)
      return null
    } catch (error) {
      return `单位记录写入失败：${error instanceof Error ? error.message : String(error)}；本次会话内有效`
    }
  }

  /**
   * Frames of a document under its current unit.
   * @param doc - open document.
   * @returns sheet borders, drawing clusters outside every sheet, or the whole extent.
   */
  frames(doc: CadDoc): DocFrames {
    if (doc.framesFor !== null && doc.framesFor.unit === doc.unit.unit) return doc.framesFor
    const mmPerUnit = MM_PER_UNIT[doc.unit.unit]
    const warnings: string[] = []
    const sheets = detectSheets(doc.scene, mmPerUnit)
    const detection = detectFrames(doc.scene, { ...this.spec.frames, layerHint: this.spec.frames.layerHint, mmPerUnit })
    if (detection.capped) warnings.push(`聚类取点达到上限 ${this.spec.frames.pointCap}，其余图层未参与图框聚类`)
    if (detection.allLayersFallback && detection.frames.length > 0) warnings.push('没有墙/轴/柱类图层，图框聚类改用全部图层')
    const frames: DocFrame[] = sheets.map((s, i) => ({
      id: `S${i + 1}`, kind: 'sheet', x1: s.x1, y1: s.y1, x2: s.x2, y2: s.y2,
      sheet: { paper: s.paper, scale: s.scale, lengthened: s.lengthened, handle: s.handle },
    }))
    let n = 0
    for (const f of detection.frames) {
      const cx = (f.x1 + f.x2) / 2
      const cy = (f.y1 + f.y2) / 2
      if (sheets.some(s => cx >= s.x1 && cx <= s.x2 && cy >= s.y1 && cy <= s.y2)) continue
      n++
      // Titles and notes sit around a plan; texts within the title margin extend the cluster.
      const margin = Math.max(f.x2 - f.x1, f.y2 - f.y1) * this.spec.title.marginRatio
      let { x1, y1, x2, y2 } = f
      for (const t of doc.scene.texts) {
        if (t.x < f.x1 - margin || t.x > f.x2 + margin || t.y < f.y1 - margin || t.y > f.y2 + margin) continue
        x1 = Math.min(x1, t.x)
        y1 = Math.min(y1, t.y)
        x2 = Math.max(x2, t.x + estimateWidth(t.str, t.h))
        y2 = Math.max(y2, t.y + t.h)
      }
      frames.push({ id: `F${n}`, kind: 'cluster', x1, y1, x2, y2, sheet: null })
    }
    if (frames.length === 0) {
      const b = doc.scene.bbox
      frames.push({ id: 'W1', kind: 'extent', x1: b.minX, y1: b.minY, x2: b.maxX, y2: b.maxY, sheet: null })
    }
    doc.framesFor = { unit: doc.unit.unit, frames, warnings }
    return doc.framesFor
  }

  /**
   * One frame by id.
   * @param doc - open document.
   * @param id - frame id from `cad_frames`.
   * @returns the frame.
   * @throws when the id is unknown.
   */
  frame(doc: CadDoc, id: string): DocFrame {
    const { frames } = this.frames(doc)
    const found = frames.find(f => f.id === id)
    if (found === undefined) throw new Error(`图框 ${id} 不存在；可用：${frames.map(f => f.id).join('、')}`)
    return found
  }

  /** Every open document (for disposal and tests). */
  list(): CadDoc[] {
    return [...this.docs.values()]
  }
}
