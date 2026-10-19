/**
 * Structured reading tools: `cad_open`, `cad_layers`, `cad_frames`,
 * `cad_text_search`, `cad_blocks`. Results are compact tables with handles and
 * world coordinates; rows beyond the limit go to a TSV file whose path is
 * returned.
 * @module @zhitong/tool-cad/tools/read
 */
import { basename } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { blocksToSchema, countBlocks } from '../core/extract.ts'
import type { Rect } from '../core/geometry.ts'
import { expandRect, inRect, normalizeRect } from '../core/geometry.ts'
import { countLabels } from '../core/labels.ts'
import { readTitleBlock } from '../core/sheets.ts'
import { locateTables } from '../core/tables.ts'
import { filterTexts, groupLines } from '../core/textQuery.ts'
import { MM_PER_UNIT, unitEvidence } from '../core/unit.ts'
import type { CadDoc, DocFrame } from '../documents.ts'
import { rounder, shortHash, toTsv, writeResultFile } from '../output.ts'
import type { ToolEnv } from './shared.ts'
import { DOC_PARAM, FRAME_PARAM, NULLABLE_NUMBER, NULLABLE_STRING, RECT, effectiveLimit, frameArg, frameLabels, roundRect, textRef } from './shared.ts'

const UNIT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    unit: { type: 'string', required: true, enum: ['mm', 'cm', 'm', 'in'] },
    status: { type: 'string', required: true, enum: ['confirmed', 'unconfirmed'] },
    method: { type: 'string', required: true },
    basis: { ...NULLABLE_STRING, required: true },
    evidence: { type: 'string', required: true, description: '单位证据摘要' },
    suggestion: { ...NULLABLE_STRING, required: true },
  },
} as const

function unitSummary(doc: CadDoc): { unit: CadDoc['unit']['unit']; status: CadDoc['unit']['status']; method: string; basis: string | null; evidence: string; suggestion: string | null } {
  const ev = unitEvidence(doc.scene)
  return { unit: doc.unit.unit, status: doc.unit.status, method: doc.unit.method, basis: doc.unit.basis, evidence: ev.hint, suggestion: ev.suggestion }
}

/** Frame id per point, first match in frame order. */
function frameOf(frames: readonly DocFrame[], x: number, y: number): string | null {
  for (const f of frames) if (x >= f.x1 && x <= f.x2 && y >= f.y1 && y <= f.y2) return f.id
  return null
}

function hexColor(rgb: number): string {
  return `#${(rgb & 0xffffff).toString(16).padStart(6, '0')}`
}

/**
 * Register the structured reading tools.
 * @param ctx - plugin context.
 * @param env - tool environment.
 */
export function registerReadTools(ctx: Context, env: ToolEnv): void {
  ctx.tools.register(defineTool({
    name: 'cad_open',
    description: '打开一张 DWG 或 DXF 图纸（绝对路径），返回 doc 与摘要：格式嗅探、转换器版本、编码、范围、实体/文字/块计数、跳过的实体、图框数，以及单位与单位证据。'
      + 'DWG 经 dwg2dxf 转换；解析结果按内容哈希缓存在图纸目录的 .cache/，同一文件再次打开很快。之后的 cad_* 工具都用这里返回的 doc。'
      + '单位未确认（unit.status=unconfirmed）时，面积等量纲类工具会拒绝执行，需要先向用户确认并调用 cad_set_unit。',
    parameters: {
      path: { type: 'string', required: true, description: '图纸文件的绝对路径（.dwg 或 .dxf；以文件头判断格式，不看扩展名）' },
      force: { type: 'boolean', description: '忽略缓存重新转换与解析' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          doc: { type: 'string', required: true },
          path: { type: 'string', required: true },
          format: { type: 'string', required: true, enum: ['dwg', 'dxf'] },
          sha256: { type: 'string', required: true },
          encoding: { type: 'string', required: true },
          converter: { type: 'json', required: true, description: '{path, version}；DXF 直读为 null' },
          acadver: { ...NULLABLE_STRING, required: true },
          codepage: { ...NULLABLE_STRING, required: true },
          bbox: { ...RECT, required: true },
          counts: { type: 'json', required: true },
          skipped: { type: 'json', required: true, description: '跳过的实体类型与次数（最多 12 项）' },
          unit: { ...UNIT_SCHEMA, required: true },
          frames: { type: 'json', required: true, description: '图框 id 列表与种类计数' },
          cache: { type: 'json', required: true },
          warnings: { type: 'array', required: true, items: { type: 'string' } },
        },
      },
      render: (_args, v) => [{ type: 'text', text: renderOpen(v) }],
    },
    presentCall: args => ({ card: 'generic', title: `打开图纸 ${basename(args.path)}`, kind: 'read', locations: [{ path: args.path }] }),
    async execute(args, exec) {
      const doc = await env.docs.open(args.path, args.force === true, exec.signal)
      const s = doc.scene
      const round = rounder(doc.unit.unit)
      const { frames, warnings: frameWarnings } = env.docs.frames(doc)
      const warnings = [...doc.warnings, ...frameWarnings]
      const skippedEntries = Object.entries(s.stats.skipped).sort((a, b) => b[1] - a[1])
      const paper = s.stats.skipped.paperspace ?? 0
      if (paper > 0) warnings.push(`跳过了 ${paper} 个图纸空间（布局）实体；只读取模型空间`)
      const missingBlocks = skippedEntries.filter(([k]) => k.startsWith('INSERT?'))
      if (missingBlocks.length > 0) warnings.push(`${missingBlocks.length} 种块引用找不到块定义（转换器保真度缺口），这些块只计数不出图形`)
      const proxies = (s.stats.skipped.ACAD_PROXY_ENTITY ?? 0) + skippedEntries.filter(([k]) => k.startsWith('TCH_') || k.startsWith('TDB')).reduce((n, [, c]) => n + c, 0)
      if (proxies > 0) warnings.push(`有 ${proxies} 个天正/代理实体未被解析；如是天正原生图，请在天正里导出 T3 后再打开`)
      if (doc.meta.hatchSkipped > 0) warnings.push(`${doc.meta.hatchSkipped} 条填充边界无法使用（椭圆/样条边或退化环）`)
      if (doc.unit.status === 'unconfirmed') warnings.push('单位未确认：量纲类工具（cad_rooms）会拒绝执行，见 unit.evidence')
      return {
        doc: doc.id,
        path: doc.path,
        format: doc.meta.format,
        sha256: doc.meta.sha256,
        encoding: doc.meta.encoding,
        converter: doc.meta.converter,
        acadver: s.header.acadver,
        codepage: s.header.codepage,
        bbox: roundRect({ x1: s.bbox.minX, y1: s.bbox.minY, x2: s.bbox.maxX, y2: s.bbox.maxY }, round),
        counts: {
          entities: s.stats.entityCount,
          segments: s.stats.segCount,
          texts: s.texts.length,
          inserts: s.inserts.length,
          closed_polylines: s.polys.length,
          hatches: doc.meta.hatchCount,
          layers: s.layerTable.length,
          dimensions_sampled: s.dims.length,
        },
        skipped: Object.fromEntries(skippedEntries.slice(0, 12)),
        unit: unitSummary(doc),
        frames: {
          ids: frames.map(f => f.id),
          sheets: frames.filter(f => f.kind === 'sheet').length,
          clusters: frames.filter(f => f.kind === 'cluster').length,
        },
        cache: { hit: doc.cache.hit, path: doc.cache.path, dir: doc.cacheDir },
        warnings,
      }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'cad_layers',
    description: '按图层统计线段、文字、块引用、填充数，附图层颜色、冻结/关闭状态和最多 3 条样例文字；可限定在某个图框内。用来判断哪些图层是墙、门窗、标注、文字。',
    parameters: {
      doc: DOC_PARAM,
      frame: FRAME_PARAM,
      limit: { type: 'integer', description: '最多返回的图层数（按内容量排序）' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          doc: { type: 'string', required: true },
          frame: { ...NULLABLE_STRING, required: true },
          total: { type: 'integer', required: true },
          truncated: { type: 'boolean', required: true },
          layers: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                name: { type: 'string', required: true },
                segments: { type: 'integer', required: true },
                texts: { type: 'integer', required: true },
                inserts: { type: 'integer', required: true },
                hatches: { type: 'integer', required: true },
                color: { type: 'string', required: true },
                frozen: { type: 'boolean', required: true },
                off: { type: 'boolean', required: true },
                samples: { type: 'array', required: true, items: { type: 'string' } },
              },
            },
          },
        },
      },
      render: (_args, v) => [{
        type: 'text',
        text: `${v.doc}${v.frame !== null ? ` 图框 ${v.frame}` : ''} 共 ${v.total} 个图层${v.truncated ? `（只列前 ${v.layers.length} 个）` : ''}\n`
          + toTsv(['图层', '线段', '文字', '块', '填充', '颜色', '状态', '样例文字'], v.layers.map(l => [
            l.name, l.segments, l.texts, l.inserts, l.hatches, l.color, l.frozen ? '冻结' : l.off ? '关闭' : '', l.samples.join(' | '),
          ])),
      }],
    },
    isConcurrencySafe: () => true,
    async execute(args) {
      const doc = env.docs.get(args.doc)
      const frame = frameArg(env, doc, args.frame)
      const inside = (x: number, y: number): boolean => frame === null || inRect(frame, x, y)
      const stats = new Map<string, { segments: number; texts: number; inserts: number; hatches: number; samples: string[] }>()
      const entry = (name: string): { segments: number; texts: number; inserts: number; hatches: number; samples: string[] } => {
        let e = stats.get(name)
        if (e === undefined) { e = { segments: 0, texts: 0, inserts: 0, hatches: 0, samples: [] }; stats.set(name, e) }
        return e
      }
      for (const l of doc.scene.layers) {
        const p = l.positions
        let n = 0
        for (let i = 0; i + 5 < p.length; i += 6) if (inside((p[i]! + p[i + 3]!) / 2, (p[i + 1]! + p[i + 4]!) / 2)) n++
        if (n > 0) entry(l.name).segments += n
      }
      for (const t of doc.scene.texts) {
        if (!inside(t.x, t.y)) continue
        const e = entry(t.layer)
        e.texts++
        if (e.samples.length < 3 && !e.samples.includes(t.str)) e.samples.push(t.str.slice(0, 30))
      }
      for (const ins of doc.scene.inserts) if (inside(ins.x, ins.y)) entry(ins.layer).inserts++
      for (const h of doc.scene.hatches) {
        const p = h.positions
        let n = 0
        for (let i = 0; i + 8 < p.length; i += 9) if (inside(p[i]!, p[i + 1]!)) n++
        if (n > 0) entry(h.name).hatches += n
      }
      const table = new Map(doc.scene.layerTable.map(l => [l.name, l]))
      const rows = [...stats.entries()]
        .map(([name, e]) => {
          const info = table.get(name)
          return { name, ...e, color: hexColor(info?.color ?? 0xffffff), frozen: info?.frozen ?? false, off: info !== undefined && !info.visible }
        })
        .sort((a, b) => (b.segments + b.texts * 10 + b.inserts * 10) - (a.segments + a.texts * 10 + a.inserts * 10))
      const limit = effectiveLimit(env, args.limit)
      return { doc: doc.id, frame: frame?.id ?? null, total: rows.length, truncated: rows.length > limit, layers: rows.slice(0, limit) }
    },
  }))

  const TITLE_VALUE = { oneOf: [{ type: 'object', additionalProperties: false, properties: { value: { type: 'string', required: true }, ref: { type: 'string', required: true }, handle: { type: 'string', required: true } } }, { type: 'null' }] } as const

  ctx.tools.register(defineTool({
    name: 'cad_frames',
    description: '列出图纸里的图框：kind=sheet 是按 A0–A4 图幅识别的图框线，kind=cluster 是按 30m 空白聚类出的图形簇（不在任何图框线内的；范围含簇边上的图名、说明文字），都找不到时给整张图范围 W1。'
      + '每个图框给出范围、图幅/比例，以及标题栏启发式读取的图名、图号、比例、楼层（带置信度和来源文字 id/句柄）。启发式按制图惯例猜测，引用前用 cad_text_search 或 cad_render 核对。',
    parameters: { doc: DOC_PARAM },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          doc: { type: 'string', required: true },
          unit: { type: 'string', required: true },
          unit_confirmed: { type: 'boolean', required: true },
          frames: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                id: { type: 'string', required: true },
                kind: { type: 'string', required: true, enum: ['sheet', 'cluster', 'extent'] },
                rect: { ...RECT, required: true },
                area_m2: { ...NULLABLE_NUMBER, required: true, description: '单位未确认时为 null' },
                paper: { ...NULLABLE_STRING, required: true },
                border_scale: { ...NULLABLE_NUMBER, required: true, description: '图框线尺寸反推的 1:N' },
                name: { ...TITLE_VALUE, required: true },
                number: { ...TITLE_VALUE, required: true },
                scale: { ...TITLE_VALUE, required: true },
                floor: { ...NULLABLE_STRING, required: true },
                floor_confidence: { ...NULLABLE_STRING, required: true },
                fields: { type: 'json', required: true, description: '标题栏标签 → 值（工程名称、日期等）' },
                texts: { type: 'integer', required: true },
                inserts: { type: 'integer', required: true },
              },
            },
          },
          warnings: { type: 'array', required: true, items: { type: 'string' } },
        },
      },
      render: (_args, v) => [{ type: 'text', text: renderFrames(v) }],
    },
    isConcurrencySafe: () => true,
    async execute(args) {
      const doc = env.docs.get(args.doc)
      const { frames, warnings } = env.docs.frames(doc)
      const round = rounder(doc.unit.unit)
      const m2 = (MM_PER_UNIT[doc.unit.unit] / 1000) ** 2
      const confirmed = doc.unit.status === 'confirmed'
      const options = { fieldLabels: env.spec.title.fieldLabels, numberPattern: env.spec.title.numberPattern }
      const out = frames.map((f) => {
        const size = Math.max(f.x2 - f.x1, f.y2 - f.y1)
        const region: Rect = f.kind === 'cluster' ? expandRect(f, size * env.spec.title.marginRatio * 0.25) : f
        const tb = readTitleBlock(doc.scene, region, options)
        const ref = (v: { value: string; textId: number; handle: string } | null): { value: string; ref: string; handle: string } | null =>
          v === null ? null : { value: v.value, ref: textRef(v.textId), handle: v.handle }
        let texts = 0
        for (const t of doc.scene.texts) if (inRect(f, t.x, t.y)) texts++
        let inserts = 0
        for (const i of doc.scene.inserts) if (i.depth === 0 && inRect(f, i.x, i.y)) inserts++
        return {
          id: f.id,
          kind: f.kind,
          rect: roundRect(f, round),
          area_m2: confirmed ? Number(((f.x2 - f.x1) * (f.y2 - f.y1) * m2).toFixed(1)) : null,
          paper: f.sheet?.paper ?? null,
          border_scale: f.sheet?.scale ?? null,
          name: ref(tb.name),
          number: ref(tb.number),
          scale: ref(tb.scale),
          floor: tb.floor?.label ?? null,
          floor_confidence: tb.floor?.confidence ?? null,
          fields: Object.fromEntries(Object.entries(tb.fields).map(([k, v]) => [k, `${v.value}（${textRef(v.textId)}）`])),
          texts,
          inserts,
        }
      })
      return { doc: doc.id, unit: doc.unit.unit, unit_confirmed: confirmed, frames: out, warnings }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'cad_text_search',
    description: '在图纸文字里检索：按图框、图层、子串、正则、矩形范围、最小字高过滤，返回紧凑表格（id、文字、坐标、字高、图层、图框、句柄）。'
      + 'group=line 把同一基线上相邻的碎片拼成一行（标题、说明常被拆成多段）。结果超过 limit 时只返回前若干行，全部结果写进 TSV 文件并返回路径。'
      + '不要无过滤地整表拉取；先用 frame/layers/query 缩小范围。返回的 id（T 开头）可交给 cad_render 的 text_id 放大查看。',
    parameters: {
      doc: DOC_PARAM,
      query: { type: 'string', description: '子串（不区分大小写）' },
      regex: { type: 'string', description: 'JavaScript 正则（u 标志），如 ^\\d+层平面图' },
      frame: FRAME_PARAM,
      layers: { type: 'array', items: { type: 'string' }, description: '只看这些图层（名称精确匹配）' },
      rect: { ...RECT, description: '世界坐标矩形' },
      min_height: { type: 'number', description: '最小字高（图纸单位），过滤小字注释' },
      group: { type: 'string', enum: ['none', 'line'], description: '默认 none' },
      limit: { type: 'integer', description: '最多返回行数' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          doc: { type: 'string', required: true },
          unit: { type: 'string', required: true },
          total: { type: 'integer', required: true },
          truncated: { type: 'boolean', required: true },
          file: { ...NULLABLE_STRING, required: true, description: '截断时全部结果的 TSV 路径' },
          rows: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                id: { type: 'string', required: true, description: '首段文字 id；group=line 时其余片段见 ids' },
                ids: { type: 'array', items: { type: 'string' } },
                text: { type: 'string', required: true },
                x: { type: 'number', required: true },
                y: { type: 'number', required: true },
                h: { type: 'number', required: true },
                layer: { type: 'string', required: true },
                frame: { ...NULLABLE_STRING, required: true },
                handle: { type: 'string', required: true },
              },
            },
          },
        },
      },
      render: (_args, v) => [{
        type: 'text',
        text: `${v.total} 条${v.truncated ? `，只列前 ${v.rows.length} 条，全部见 ${v.file}` : ''}（坐标单位 ${v.unit}）\n`
          + toTsv(['id', '文字', 'x', 'y', '字高', '图层', '图框', '句柄'], v.rows.map(r => [
            r.ids !== undefined && r.ids.length > 1 ? `${r.id}+${r.ids.length - 1}` : r.id, r.text, r.x, r.y, r.h, r.layer, r.frame, r.handle,
          ])),
      }],
    },
    isConcurrencySafe: () => true,
    async execute(args) {
      const doc = env.docs.get(args.doc)
      const frame = frameArg(env, doc, args.frame)
      let regex: RegExp | undefined
      if (args.regex !== undefined && args.regex !== '') {
        try {
          regex = new RegExp(args.regex, 'u')
        } catch (error) {
          throw new Error(`regex 不合法：${error instanceof Error ? error.message : String(error)}`, { cause: error })
        }
      }
      let rect: Rect | undefined = frame ?? undefined
      if (args.rect !== undefined) {
        const r = normalizeRect(args.rect)
        rect = rect === undefined ? r : { x1: Math.max(r.x1, rect.x1), y1: Math.max(r.y1, rect.y1), x2: Math.min(r.x2, rect.x2), y2: Math.min(r.y2, rect.y2) }
      }
      const texts = doc.scene.texts
      const { frames } = env.docs.frames(doc)
      const round = rounder(doc.unit.unit)
      const hRound = (v: number): number => Number(v.toPrecision(3))
      const filter = {
        ...rect !== undefined ? { rect } : {},
        ...args.layers !== undefined && args.layers.length > 0 ? { layers: new Set(args.layers) } : {},
        ...args.min_height !== undefined ? { minHeight: args.min_height } : {},
      }
      type Row = { id: string; ids?: string[]; text: string; x: number; y: number; h: number; layer: string; frame: string | null; handle: string }
      let rows: Row[]
      if (args.group === 'line') {
        const base = filterTexts(texts, filter)
        rows = groupLines(texts, base)
          .filter(l => (args.query === undefined || l.str.toLowerCase().includes(args.query.toLowerCase())) && (regex === undefined || regex.test(l.str)))
          .map(l => ({
            id: textRef(l.ids[0]!), ids: l.ids.map(textRef), text: l.str, x: round(l.x), y: round(l.y), h: hRound(l.h), layer: l.layer,
            frame: frameOf(frames, l.x, l.y), handle: texts[l.ids[0]!]!.handle,
          }))
      } else {
        rows = filterTexts(texts, { ...filter, ...args.query !== undefined ? { query: args.query } : {}, ...regex !== undefined ? { regex } : {} })
          .map((i) => {
            const t = texts[i]!
            return { id: textRef(i), text: t.str, x: round(t.x), y: round(t.y), h: hRound(t.h), layer: t.layer, frame: frameOf(frames, t.x, t.y), handle: t.handle }
          })
      }
      const limit = effectiveLimit(env, args.limit)
      let file: string | null = null
      if (rows.length > limit) {
        file = await writeResultFile(doc.cacheDir, 'out', `${doc.id}-text-${shortHash(args)}.tsv`, `${toTsv(['id', 'ids', 'text', 'x', 'y', 'h', 'layer', 'frame', 'handle'], rows.map(r => [
          r.id, (r.ids ?? [r.id]).join(','), r.text, r.x, r.y, r.h, r.layer, r.frame, r.handle,
        ]))}\n`)
      }
      return { doc: doc.id, unit: doc.unit.unit, total: rows.length, truncated: rows.length > limit, file, rows: rows.slice(0, limit) }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'cad_blocks',
    description: '块引用计数（按块名，含各层嵌套，匿名块除外）与门窗编号文字计数（M1021、C1518、FM甲1022 等；门窗表里列出的编号单独计 in_tables，不算入数量），都按图框分组。两种计数可以互相印证；数量一律以这里的结果为准，不要从图片数。'
      + '尺寸标注、动态块等匿名块内部的引用不计（合计里给出 anonymous_internal）。每个块与编号附样例坐标/句柄；全部坐标写进 TSV 文件。as_schema=true 另存统一算量 schema（RecognitionItem）JSON。',
    parameters: {
      doc: DOC_PARAM,
      frame: FRAME_PARAM,
      pattern: { type: 'string', description: '只统计名称匹配此正则的块' },
      labels: { type: 'boolean', description: '同时统计门窗编号文字，默认 true' },
      label_pattern: { type: 'string', description: '覆盖默认的门窗编号正则' },
      as_schema: { type: 'boolean', description: '另存统一算量 schema JSON' },
      limit: { type: 'integer', description: '每类最多返回行数' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          doc: { type: 'string', required: true },
          frame: { ...NULLABLE_STRING, required: true },
          blocks: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                name: { type: 'string', required: true },
                count: { type: 'integer', required: true },
                nested: { type: 'integer', required: true, description: '其中位于其他块内的引用数' },
                layers: { type: 'array', required: true, items: { type: 'string' } },
                per_frame: { type: 'json', required: true },
                sample: { type: 'json', required: true, description: '最多 3 个 {x, y, handle}' },
              },
            },
          },
          labels: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                label: { type: 'string', required: true },
                count: { type: 'integer', required: true },
                in_tables: { type: 'integer', required: true, description: '门窗表等表格里出现的次数（不计入 count）' },
                per_frame: { type: 'json', required: true },
                refs: { type: 'array', required: true, items: { type: 'string' }, description: '最多 5 个文字 id' },
              },
            },
          },
          totals: { type: 'json', required: true },
          truncated: { type: 'boolean', required: true },
          file: { type: 'string', required: true, description: '全部引用与编号坐标的 TSV' },
          schema_file: { ...NULLABLE_STRING, required: true },
          needs_manual: { type: 'boolean', required: true },
        },
      },
      render: (_args, v) => [{ type: 'text', text: renderBlocks(v) }],
    },
    isConcurrencySafe: () => true,
    async execute(args) {
      const doc = env.docs.get(args.doc)
      const frame = frameArg(env, doc, args.frame)
      const { frames } = env.docs.frames(doc)
      const labelled = frameLabels(frames)
      const round = rounder(doc.unit.unit)
      let namePattern: RegExp | undefined
      let labelPattern = env.spec.openingLabel
      try {
        if (args.pattern !== undefined && args.pattern !== '') namePattern = new RegExp(args.pattern, 'u')
        if (args.label_pattern !== undefined && args.label_pattern !== '') labelPattern = new RegExp(args.label_pattern, 'u')
      } catch (error) {
        throw new Error(`正则不合法：${error instanceof Error ? error.message : String(error)}`, { cause: error })
      }
      const inFrame = doc.scene.inserts.filter(i => (frame === null || inRect(frame, i.x, i.y)) && (namePattern === undefined || namePattern.test(i.name)))
      // References inside anonymous blocks are dimension arrowheads and dynamic-block internals, not placed components.
      const inserts = inFrame.filter(i => i.parent === null || !i.parent.startsWith('*'))
      const counts = countBlocks({ inserts }, labelled)
      const byName = new Map<string, typeof inserts>()
      for (const i of inserts) {
        if (i.name.startsWith('*')) continue
        let list = byName.get(i.name)
        if (list === undefined) { list = []; byName.set(i.name, list) }
        list.push(i)
      }
      const limit = effectiveLimit(env, args.limit)
      const blocks = counts.map((c) => {
        const list = byName.get(c.name) ?? []
        return {
          name: c.name,
          count: c.count,
          nested: list.filter(i => i.depth > 0).length,
          layers: c.layers,
          per_frame: c.perFrame,
          sample: list.slice(0, 3).map(i => ({ x: round(i.x), y: round(i.y), handle: i.handle })),
        }
      })
      const texts = doc.scene.texts
      const tableRects = args.labels === false ? [] : locateTables(doc.scene, env.spec.tableKinds, frame, env.spec.tableMinHeaderHits).map(t => t.rect)
      const labelCounts = args.labels === false
        ? []
        : countLabels(texts, filterTexts(texts, frame !== null ? { rect: frame } : {}), labelPattern, labelled, tableRects)
      const tsvRows: Array<Array<string | number | null>> = []
      for (const [name, list] of byName) for (const i of list) tsvRows.push(['block', name, round(i.x), round(i.y), i.layer, frameOf(frames, i.x, i.y), i.handle, i.depth])
      for (const l of labelCounts) for (const id of l.ids) {
        const t = texts[id]!
        tsvRows.push(['label', l.label, round(t.x), round(t.y), t.layer, frameOf(frames, t.x, t.y), t.handle, textRef(id)])
      }
      const file = await writeResultFile(doc.cacheDir, 'out', `${doc.id}-blocks-${shortHash(args)}.tsv`, `${toTsv(['kind', 'name', 'x', 'y', 'layer', 'frame', 'handle', 'depth_or_text'], tsvRows)}\n`)
      let schemaFile: string | null = null
      if (args.as_schema === true) {
        const u = doc.unit
        const envelope = blocksToSchema(counts, basename(doc.path), { unit: u.unit, insunits: doc.scene.header.insunits, confirmed: u.status === 'confirmed', confirmedAt: u.confirmedAt, method: u.method })
        schemaFile = await writeResultFile(doc.cacheDir, 'out', `${doc.id}-blocks-schema-${shortHash(args)}.json`, `${JSON.stringify(envelope, null, 2)}\n`)
      }
      return {
        doc: doc.id,
        frame: frame?.id ?? null,
        blocks: blocks.slice(0, limit),
        labels: labelCounts.slice(0, limit).map(l => ({ label: l.label, count: l.count, in_tables: l.inTables, per_frame: l.perFrame, refs: l.ids.slice(0, 5).map(textRef) })),
        totals: {
          block_refs: blocks.reduce((n, b) => n + b.count, 0),
          distinct_blocks: blocks.length,
          anonymous_internal: inFrame.length - inserts.length,
          label_texts: labelCounts.reduce((n, l) => n + l.count, 0),
          distinct_labels: labelCounts.length,
        },
        truncated: blocks.length > limit || labelCounts.length > limit,
        file,
        schema_file: schemaFile,
        needs_manual: true,
      }
    },
  }))
}

interface OpenView {
  doc: string; path: string; format: string; encoding: string; converter: unknown; acadver: string | null
  bbox: Rect; counts: unknown; skipped: unknown
  unit: { unit: string; status: string; method: string; evidence: string }
  frames: unknown; cache: unknown; warnings: string[]
}

function renderOpen(v: OpenView): string {
  const lines = [
    `doc=${v.doc}  ${v.format.toUpperCase()}${v.acadver !== null ? ` ${v.acadver}` : ''}  编码 ${v.encoding}${v.converter !== null ? `  转换器 ${JSON.stringify(v.converter)}` : ''}`,
    `范围 x ${v.bbox.x1}…${v.bbox.x2}  y ${v.bbox.y1}…${v.bbox.y2}`,
    `计数 ${JSON.stringify(v.counts)}`,
    `跳过 ${JSON.stringify(v.skipped)}`,
    `单位 ${v.unit.unit}（${v.unit.status === 'confirmed' ? `已确认：${v.unit.method}` : '未确认'}）证据：${v.unit.evidence}`,
    `图框 ${JSON.stringify(v.frames)}`,
    `缓存 ${JSON.stringify(v.cache)}`,
  ]
  for (const w of v.warnings) lines.push(`警告：${w}`)
  return lines.join('\n')
}

interface FramesView {
  doc: string; unit: string; unit_confirmed: boolean; warnings: string[]
  frames: Array<{
    id: string; kind: string; rect: Rect; area_m2: number | null; paper: string | null; border_scale?: number | null
    name: { value: string; ref: string } | null; number: { value: string; ref: string } | null; scale: { value: string; ref: string } | null
    floor: string | null; floor_confidence?: string | null; texts: number; inserts: number
  }>
}

function renderFrames(v: FramesView): string {
  const rows = v.frames.map(f => [
    f.id, f.kind, `${f.rect.x1},${f.rect.y1},${f.rect.x2},${f.rect.y2}`, f.area_m2, f.paper !== null ? `${f.paper} 1:${f.border_scale ?? '?'}` : '',
    f.name !== null ? `${f.name.value}(${f.name.ref})` : '', f.number !== null ? `${f.number.value}(${f.number.ref})` : '',
    f.scale !== null ? `${f.scale.value}(${f.scale.ref})` : '', f.floor !== null ? `${f.floor}/${f.floor_confidence ?? ''}` : '', f.texts, f.inserts,
  ])
  const head = `${v.doc} 共 ${v.frames.length} 个图框（坐标单位 ${v.unit}${v.unit_confirmed ? '' : '，未确认，面积不计'}）`
  return [head, toTsv(['id', '种类', '范围', '面积m²', '图幅', '图名', '图号', '比例', '楼层/置信', '文字', '块'], rows), ...v.warnings.map(w => `警告：${w}`)].join('\n')
}

interface BlocksView {
  doc: string; frame: string | null; file: string; schema_file: string | null; truncated: boolean
  blocks: Array<{ name: string; count: number; nested: number; layers: string[]; per_frame: unknown }>
  labels: Array<{ label: string; count: number; in_tables: number; per_frame: unknown; refs: string[] }>
  totals: unknown
}

function renderBlocks(v: BlocksView): string {
  const parts = [`${v.doc}${v.frame !== null ? ` 图框 ${v.frame}` : ''} 合计 ${JSON.stringify(v.totals)}${v.truncated ? '（列表已截断）' : ''}`]
  parts.push('块：', toTsv(['块名', '数量', '嵌套', '图层', '分图框'], v.blocks.map(b => [b.name, b.count, b.nested, b.layers.join(','), JSON.stringify(b.per_frame)])))
  if (v.labels.length > 0) parts.push('门窗编号文字：', toTsv(['编号', '数量', '表格内', '分图框', '文字id'], v.labels.map(l => [l.label, l.count, l.in_tables, JSON.stringify(l.per_frame), l.refs.join(',')])))
  parts.push(`全部坐标：${v.file}`)
  if (v.schema_file !== null) parts.push(`统一算量 schema：${v.schema_file}`)
  return parts.join('\n')
}
