/** Plugin configuration and its resolution into a runtime spec. @module @zhitong/tool-cad/config */

import { existsSync } from 'node:fs'
import { sep } from 'node:path'
import { fileURLToPath } from 'node:url'
import z from '@deepseek-ai/schemastery'
import type { TableKind } from './core/tables.ts'

/** One configured table kind (mutable form of {@link TableKind} for the config schema). */
export interface TableKindConfig {
  kind: string
  titles: string[]
  headers: string[]
}

/**
 * Map a path inside an Electron `app.asar` archive to its `app.asar.unpacked` twin when that twin exists.
 * The Desktop installer unpacks this package's `assets/` and `bin/`: the canvas font loader and the
 * dwg2dxf child process need physical files, and the archive is readable only through Electron's `fs`.
 * @param path - Absolute path.
 * @returns The unpacked path, or `path` unchanged outside an archive or without an unpacked twin.
 */
export function physicalPath(path: string): string {
  const marker = `${sep}app.asar${sep}`
  const index = path.lastIndexOf(marker)
  if (index < 0) return path
  const unpacked = `${path.slice(0, index)}${sep}app.asar.unpacked${sep}${path.slice(index + marker.length)}`
  return existsSync(unpacked) ? unpacked : path
}

/** Package root (`src/` and the bundled `lib/` both sit one level below it). */
export const PACKAGE_ROOT = fileURLToPath(new URL('..', import.meta.url))
const BUNDLED_SHX = physicalPath(fileURLToPath(new URL('../assets/fonts/kst32b.shx', import.meta.url)))
const BUNDLED_FONT = physicalPath(fileURLToPath(new URL('../assets/fonts/NotoSansSC-Regular-GB2312.otf', import.meta.url)))
const BUNDLED_BIN = physicalPath(fileURLToPath(new URL('../bin', import.meta.url)))

/** Configuration of the CAD tools. Every criterion of the heuristics is a field so drawings from other design institutes can be tuned without code changes. */
export interface Config {
  /** Absolute path of the dwg2dxf executable; empty searches `DWG2DXF_BIN`, the package `bin/<platform>-<arch>/`, then PATH. */
  dwg2dxfPath?: string
  /** dwg2dxf time limit per conversion. */
  dwg2dxfTimeoutMs?: number
  /** Largest DWG accepted. */
  maxDwgBytes?: number
  /** Largest DXF (read directly or produced by conversion) accepted. */
  maxDxfBytes?: number
  /** Parse cache, unit records, renders, and exported files; empty uses `<drawing directory>/.cache/`. */
  cacheDir?: string
  /** SHX stroke fonts tried in order for drawn text; defaults to the bundled KST32B. */
  shxFonts?: string[]
  /** Font for texts the SHX fonts cannot cover; defaults to the bundled Noto Sans SC subset. */
  fallbackFont?: string
  /** Drawing-cluster gap in millimetres (source scripts 03/06: 30 m). */
  frameGapMm?: number
  /** Minimum drawing-cluster area in m². */
  frameMinAreaM2?: number
  /** Minimum endpoints in a drawing cluster. */
  frameMinPts?: number
  /** Layer-name pattern selecting cluster points (case-insensitive). */
  frameLayerPattern?: string
  /** Maximum endpoints sampled for clustering. */
  framePointCap?: number
  /** Title-block search margin around a drawing cluster, as a fraction of its larger side. */
  titleMarginRatio?: number
  /** Title-block labels whose neighbour text is read as the value. */
  titleFieldLabels?: string[]
  /** Drawing-number pattern used when no `图号` label is found. */
  drawingNumberPattern?: string
  /** Door/window label pattern for `cad_blocks` label counting. */
  openingLabelPattern?: string
  /** Layers holding room-name anchors (Tianzheng `TXTROOM`). */
  roomAnchorLayers?: string[]
  /** Smallest room area in m² for both polygons and area texts. */
  roomMinAreaM2?: number
  /** Largest room area in m² for both polygons and area texts. */
  roomMaxAreaM2?: number
  /** Longest room-name text accepted as an anchor. */
  roomMaxLabelLength?: number
  /** Drawing-comparison quantization in millimetres. */
  diffEpsMm?: number
  /** Default rows returned by list tools. */
  listLimit?: number
  /** Largest `limit` a call may request. */
  listMaxLimit?: number
  /** Table kinds for automatic table location. */
  tableKinds?: TableKindConfig[]
  /** Distinct header words a header row needs. */
  tableMinHeaderHits?: number
  /** Default longest image side in pixels. */
  renderMaxPx?: number
  /** Largest `max_px` a call may request. */
  renderHardMaxPx?: number
  /** Target text height in pixels for zoom renders. */
  renderMinTextPx?: number
  /** Texts smaller than this many pixels are not drawn. */
  renderDropTextPx?: number
  /** Grid cells along the longer side of an overview. */
  gridLongSide?: number
  /** Largest zoom region as a fraction of its frame's area. */
  renderMaxZoomFraction?: number
  /** Most numbered text boxes on one image. */
  renderMaxLabels?: number
}

const DEFAULT_TABLE_KINDS: TableKindConfig[] = [
  {
    kind: '门窗表',
    titles: ['门窗表', '门窗统计表', '门窗明细表', '门窗一览表', '门窗数量表'],
    headers: ['编号', '设计编号', '门窗编号', '类型', '类别', '名称', '洞口尺寸', '宽', '高', '宽度', '高度', '数量', '樘数', '总数', '图集', '图集名称', '选用型号', '参考图集', '备注'],
  },
  {
    kind: '材料表',
    titles: ['材料表', '主要材料表', '设备材料表', '材料统计表', '主要设备材料表', '材料明细表'],
    headers: ['序号', '材料', '材料名称', '名称', '规格', '型号', '规格型号', '单位', '数量', '材质', '备注'],
  },
]

/** Runtime configuration schema. */
export const Config: z<Config> = z.object({
  dwg2dxfPath: z.string().default(''),
  dwg2dxfTimeoutMs: z.natural().min(1000).default(180_000),
  maxDwgBytes: z.natural().min(1).default(200 * 1024 * 1024),
  maxDxfBytes: z.natural().min(1).default(400 * 1024 * 1024),
  cacheDir: z.string().default(''),
  shxFonts: z.array(z.string()).default([BUNDLED_SHX]),
  fallbackFont: z.string().default(BUNDLED_FONT),
  frameGapMm: z.number().min(1).default(30_000),
  frameMinAreaM2: z.number().min(0).default(50),
  frameMinPts: z.natural().min(1).default(30),
  frameLayerPattern: z.string().default('WALL|墙|轴|AXIS|DOTE|COLUMN|柱'),
  framePointCap: z.natural().min(1).default(300_000),
  titleMarginRatio: z.number().min(0).max(1).default(0.15),
  titleFieldLabels: z.array(z.string()).default(['工程名称', '项目名称', '子项名称', '子项', '图名', '比例', '日期', '专业', '阶段', '设计阶段', '版本', '版次', '设计', '校对', '审核', '审定', '工程编号', '项目编号']),
  drawingNumberPattern: z.string().default('^(?:建施|结施|水施|电施|暖施|设施|总施|装施|景施|[A-Z]{1,3})[-－—]?\\d{1,3}(?:[-－—.]\\d{1,3})?[A-Za-z]?$'),
  openingLabelPattern: z.string().default('^(?:FM|FC|MLC|TLM|LMC|JLM|BYC|MC|LM|JM|GC|YC|TC|DK|M|C)[甲乙丙]?[A-Z]?-?\\d{2,4}[A-Za-z]?(?:-\\d{1,2})?$'),
  roomAnchorLayers: z.array(z.string()).default(['TXTROOM']),
  roomMinAreaM2: z.number().min(0).default(1),
  roomMaxAreaM2: z.number().min(0).default(2000),
  roomMaxLabelLength: z.natural().min(1).default(12),
  diffEpsMm: z.number().min(0.001).default(1),
  listLimit: z.natural().min(1).default(100),
  listMaxLimit: z.natural().min(1).default(1000),
  tableKinds: z.array(z.object({
    kind: z.string().required(),
    titles: z.array(z.string()).required(),
    headers: z.array(z.string()).required(),
  })).default(DEFAULT_TABLE_KINDS),
  tableMinHeaderHits: z.natural().min(2).default(3),
  renderMaxPx: z.natural().min(200).default(1600),
  renderHardMaxPx: z.natural().min(200).default(2400),
  renderMinTextPx: z.number().min(4).default(14),
  renderDropTextPx: z.number().min(0).default(3),
  gridLongSide: z.natural().min(2).max(26).default(8),
  renderMaxZoomFraction: z.number().min(0.01).max(1).default(0.25),
  renderMaxLabels: z.natural().min(1).default(120),
})

/** Fully resolved runtime settings. */
export interface ToolCadSpec {
  readonly dwg2dxfPath: string | undefined
  readonly bundledBinRoot: string
  readonly dwg2dxfTimeoutMs: number
  readonly maxDwgBytes: number
  readonly maxDxfBytes: number
  readonly cacheDir: string | undefined
  readonly shxFonts: readonly string[]
  readonly fallbackFont: string
  readonly frames: { readonly gapMm: number; readonly minAreaM2: number; readonly minPts: number; readonly layerHint: RegExp; readonly pointCap: number }
  readonly title: { readonly marginRatio: number; readonly fieldLabels: readonly string[]; readonly numberPattern: RegExp }
  readonly openingLabel: RegExp
  readonly rooms: { readonly anchorLayers: readonly string[]; readonly minAreaM2: number; readonly maxAreaM2: number; readonly maxLabelLength: number }
  readonly diffEpsMm: number
  readonly listLimit: number
  readonly listMaxLimit: number
  readonly tableKinds: readonly TableKind[]
  readonly tableMinHeaderHits: number
  readonly render: {
    readonly maxPx: number
    readonly hardMaxPx: number
    readonly minTextPx: number
    readonly dropTextPx: number
    readonly gridLongSide: number
    readonly maxZoomFraction: number
    readonly maxLabels: number
  }
}

function pattern(source: string, flags: string, field: string): RegExp {
  try {
    return new RegExp(source, flags)
  } catch (error) {
    throw new Error(`tool-cad: ${field} 不是合法的正则表达式：${error instanceof Error ? error.message : String(error)}`, { cause: error })
  }
}

/**
 * Resolve plugin config into runtime settings. Font files must exist, and
 * patterns must compile, so misconfiguration fails when the plugin loads.
 * @param config - validated plugin config.
 * @returns the runtime spec.
 * @throws when a font file is missing, a pattern is invalid, or a size pair is inconsistent.
 */
export function resolveSpec(config: Config): ToolCadSpec {
  const shxFonts = config.shxFonts ?? [BUNDLED_SHX]
  const fallbackFont = config.fallbackFont ?? BUNDLED_FONT
  for (const font of [...shxFonts, fallbackFont]) {
    if (!existsSync(font)) throw new Error(`tool-cad: 字体文件不存在：${font}`)
  }
  const maxPx = config.renderMaxPx ?? 1600
  const hardMaxPx = config.renderHardMaxPx ?? 2400
  if (maxPx > hardMaxPx) throw new Error(`tool-cad: renderMaxPx (${maxPx}) 不能大于 renderHardMaxPx (${hardMaxPx})`)
  const listLimit = config.listLimit ?? 100
  const listMaxLimit = config.listMaxLimit ?? 1000
  if (listLimit > listMaxLimit) throw new Error(`tool-cad: listLimit (${listLimit}) 不能大于 listMaxLimit (${listMaxLimit})`)
  const dwg2dxfPath = config.dwg2dxfPath ?? ''
  const cacheDir = config.cacheDir ?? ''
  return {
    dwg2dxfPath: dwg2dxfPath === '' ? undefined : dwg2dxfPath,
    bundledBinRoot: BUNDLED_BIN,
    dwg2dxfTimeoutMs: config.dwg2dxfTimeoutMs ?? 180_000,
    maxDwgBytes: config.maxDwgBytes ?? 200 * 1024 * 1024,
    maxDxfBytes: config.maxDxfBytes ?? 400 * 1024 * 1024,
    cacheDir: cacheDir === '' ? undefined : cacheDir,
    shxFonts,
    fallbackFont,
    frames: {
      gapMm: config.frameGapMm ?? 30_000,
      minAreaM2: config.frameMinAreaM2 ?? 50,
      minPts: config.frameMinPts ?? 30,
      layerHint: pattern(config.frameLayerPattern ?? 'WALL|墙|轴|AXIS|DOTE|COLUMN|柱', 'iu', 'frameLayerPattern'),
      pointCap: config.framePointCap ?? 300_000,
    },
    title: {
      marginRatio: config.titleMarginRatio ?? 0.15,
      fieldLabels: config.titleFieldLabels ?? [],
      numberPattern: pattern(config.drawingNumberPattern ?? '^$', 'u', 'drawingNumberPattern'),
    },
    openingLabel: pattern(config.openingLabelPattern ?? '^$', 'u', 'openingLabelPattern'),
    rooms: {
      anchorLayers: config.roomAnchorLayers ?? ['TXTROOM'],
      minAreaM2: config.roomMinAreaM2 ?? 1,
      maxAreaM2: config.roomMaxAreaM2 ?? 2000,
      maxLabelLength: config.roomMaxLabelLength ?? 12,
    },
    diffEpsMm: config.diffEpsMm ?? 1,
    listLimit,
    listMaxLimit,
    tableKinds: config.tableKinds ?? DEFAULT_TABLE_KINDS,
    tableMinHeaderHits: config.tableMinHeaderHits ?? 3,
    render: {
      maxPx,
      hardMaxPx,
      minTextPx: config.renderMinTextPx ?? 14,
      dropTextPx: config.renderDropTextPx ?? 3,
      gridLongSide: config.gridLongSide ?? 8,
      maxZoomFraction: config.renderMaxZoomFraction ?? 0.25,
      maxLabels: config.renderMaxLabels ?? 120,
    },
  }
}
