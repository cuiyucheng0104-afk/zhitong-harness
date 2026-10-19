/**
 * Second-batch tools: `cad_set_unit` (unit gate), `cad_rooms` (two-way room
 * areas, unit required), `cad_table` (table location and extraction),
 * `cad_diff` (segment, text, and block differences between two drawings).
 * @module @zhitong/tool-cad/tools/analysis
 */
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { diffScenes } from '../core/diff.ts'
import type { TableResult } from '../core/extract.ts'
import { countBlocks, extractTable, tableToCsv } from '../core/extract.ts'
import type { Rect } from '../core/geometry.ts'
import { inRect, normalizeRect } from '../core/geometry.ts'
import { checkRooms } from '../core/roomCheck.ts'
import { locateTables } from '../core/tables.ts'
import type { UnitName, UnitState } from '../core/unit.ts'
import { MM_PER_UNIT, unitEvidence } from '../core/unit.ts'
import { rounder, shortHash, toTsv, writeResultFile } from '../output.ts'
import { renderRegion } from '../render/raster.ts'
import type { ToolEnv } from './shared.ts'
import { DOC_PARAM, FRAME_PARAM, NULLABLE_NUMBER, NULLABLE_STRING, RECT, effectiveLimit, frameArg, requireConfirmedUnit, roundRect, textRef } from './shared.ts'

/**
 * Register the second-batch tools.
 * @param ctx - plugin context.
 * @param env - tool environment.
 */
export function registerAnalysisTools(ctx: Context, env: ToolEnv): void {
  ctx.tools.register(defineTool({
    name: 'cad_set_unit',
    description: '确认图纸单位（量纲类工具的前提）。两种方式：unit + basis（向用户确认后填写，basis 写明谁、依据什么），或 verify=true（按尺寸标注「显示值÷实测长度」比对，样本≥5 且一致率≥80% 时自动确认）。'
      + '确认结果记录在图纸缓存目录，下次打开同一文件仍有效。',
    parameters: {
      doc: DOC_PARAM,
      unit: { type: 'string', enum: ['mm', 'cm', 'm', 'in'] },
      basis: { type: 'string', description: '确认依据，如「用户确认：建筑图 mm」' },
      verify: { type: 'boolean', description: '按尺寸标注比对自动确认' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          doc: { type: 'string', required: true },
          unit: { type: 'string', required: true },
          status: { type: 'string', required: true },
          method: { type: 'string', required: true },
          basis: { ...NULLABLE_STRING, required: true },
          confirmed_at: { ...NULLABLE_STRING, required: true },
          evidence: { type: 'string', required: true },
          warnings: { type: 'array', required: true, items: { type: 'string' } },
        },
      },
      render: (_args, v) => [{ type: 'text', text: `${v.doc} 单位 ${v.unit}（${v.status}，${v.method}${v.basis !== null ? `：${v.basis}` : ''}）\n证据：${v.evidence}${v.warnings.map(w => `\n警告：${w}`).join('')}` }],
    },
    async execute(args) {
      const doc = env.docs.get(args.doc)
      const ev = unitEvidence(doc.scene)
      let next: UnitState
      if (args.verify === true) {
        if (ev.suggestion === null || ev.dimensionSamples < 5 || ev.ratioAgreement < 0.8) {
          throw new Error(`尺寸比对不足以自动确认：${ev.hint}。请向用户确认单位后用 unit + basis 调用`)
        }
        if (args.unit !== undefined && args.unit !== ev.suggestion) {
          throw new Error(`尺寸比对指向 ${ev.suggestion}，与给定的 ${args.unit} 不一致：${ev.hint}`)
        }
        next = { status: 'confirmed', unit: ev.suggestion, method: '尺寸比对', confirmedAt: new Date().toISOString(), basis: ev.hint }
      } else {
        if (args.unit === undefined) throw new Error('需要 unit（mm/cm/m/in），或者 verify=true')
        const basis = args.basis?.trim() ?? ''
        if (basis === '') throw new Error('人工确认需要 basis：写明谁确认、依据什么')
        next = { status: 'confirmed', unit: args.unit as UnitName, method: '人工确认', confirmedAt: new Date().toISOString(), basis }
      }
      const warning = await env.docs.setUnit(doc, next)
      const warnings = warning !== null ? [warning] : []
      if (doc.scene.header.insunits !== null && doc.scene.header.insunits !== 0) {
        const fromHeader = ({ 1: 'in', 4: 'mm', 5: 'cm', 6: 'm' } as Record<number, string>)[doc.scene.header.insunits]
        if (fromHeader !== undefined && fromHeader !== next.unit) warnings.push(`与图纸头 $INSUNITS=${doc.scene.header.insunits}（${fromHeader}）不一致`)
      }
      return { doc: doc.id, unit: next.unit, status: next.status, method: next.method, basis: next.basis, confirmed_at: next.confirmedAt, evidence: ev.hint, warnings }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'cad_rooms',
    description: '房间面积双路核对：房间名锚点（默认天正 TXTROOM 图层）所在的最小闭合多段线算几何面积，同一多边形内的面积数字文字作为文字面积，给出差异百分比。'
      + '需要先确认单位。墙是双线、房间边界不闭合或面积文字在转换中丢失时会漏配，未匹配不等于没有房间。面积由代码计算，转述时如实给出 text_m2/geom_m2/diff_pct。',
    parameters: {
      doc: DOC_PARAM,
      frame: FRAME_PARAM,
      limit: { type: 'integer', description: '最多返回行数' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          doc: { type: 'string', required: true },
          unit: { type: 'string', required: true },
          frame: { ...NULLABLE_STRING, required: true },
          anchors: { type: 'integer', required: true, description: '锚点图层上的候选房间名文字数' },
          matched: { type: 'integer', required: true },
          rooms: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                label: { type: 'string', required: true },
                text_m2: { ...NULLABLE_NUMBER, required: true },
                geom_m2: { type: 'number', required: true },
                diff_pct: { ...NULLABLE_NUMBER, required: true },
                x: { type: 'number', required: true },
                y: { type: 'number', required: true },
                layer: { type: 'string', required: true },
                poly_handle: { type: 'string', required: true },
                text_handle: { type: 'string', required: true },
              },
            },
          },
          truncated: { type: 'boolean', required: true },
          file: { type: 'string', required: true },
          note: { type: 'string', required: true },
          needs_manual: { type: 'boolean', required: true },
        },
      },
      render: (_args, v) => {
        const rooms = v.rooms
        return [{
          type: 'text',
          text: `${v.doc}${v.frame !== null ? ` 图框 ${v.frame}` : ''}：锚点 ${v.anchors} 个，匹配 ${v.matched} 间（单位 ${v.unit}）${v.truncated ? `，只列前 ${rooms.length} 间` : ''}\n`
            + toTsv(['房间', '文字面积m²', '几何面积m²', '差异%', 'x', 'y', '多段线句柄'], rooms.map(r => [r.label, r.text_m2, r.geom_m2, r.diff_pct, r.x, r.y, r.poly_handle]))
            + `\n全部：${v.file}\n${v.note}`,
        }]
      },
    },
    isConcurrencySafe: () => true,
    async execute(args) {
      const doc = env.docs.get(args.doc)
      requireConfirmedUnit(doc, '房间面积')
      const frame = frameArg(env, doc, args.frame)
      const round = rounder(doc.unit.unit)
      const scene = frame === null ? doc.scene : { ...doc.scene, texts: doc.scene.texts.filter(t => inRect(frame, t.x, t.y)) }
      const anchors = new Set(env.spec.rooms.anchorLayers)
      const anchorCount = scene.texts.filter(t => anchors.has(t.layer)).length
      const items = checkRooms(scene, MM_PER_UNIT[doc.unit.unit], env.spec.rooms)
      const rows = items.map(i => ({
        label: i.label, text_m2: i.textM2, geom_m2: i.geomM2, diff_pct: i.diffPct, x: round(i.x), y: round(i.y), layer: i.layer, poly_handle: i.polyHandle, text_handle: i.textHandle,
      }))
      const file = await writeResultFile(doc.cacheDir, 'out', `${doc.id}-rooms-${shortHash(args)}.tsv`, `${toTsv(['label', 'text_m2', 'geom_m2', 'diff_pct', 'x', 'y', 'layer', 'poly_handle', 'text_handle'], rows.map(r => [
        r.label, r.text_m2, r.geom_m2, r.diff_pct, r.x, r.y, r.layer, r.poly_handle, r.text_handle,
      ]))}\n`)
      const limit = effectiveLimit(env, args.limit)
      const note = anchorCount === 0
        ? `锚点图层 ${env.spec.rooms.anchorLayers.join('、')} 上没有房间名文字；可用 cad_layers 找房间名所在图层后在配置 roomAnchorLayers 里调整`
        : `未匹配 ${anchorCount - rows.length} 个锚点：常见原因是墙为双线、房间边界不闭合；未匹配不等于没有房间`
      return {
        doc: doc.id,
        unit: doc.unit.unit,
        frame: frame?.id ?? null,
        anchors: anchorCount,
        matched: rows.length,
        rooms: rows.slice(0, limit),
        truncated: rows.length > limit,
        file,
        note,
        needs_manual: true,
      }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'cad_table',
    description: '提取图上的表格（门窗表、材料表等）。给 rect 时直接在该矩形里按表格线重建网格并把文字落格；不给 rect 时按表头关键词（编号、洞口尺寸、数量…）自动找表，可用 frame 限定范围、kind 限定表种。'
      + '每张表返回前若干行与完整 CSV 路径。表格线用填充或块画成时可能找不到网格，这时用 cad_text_search 按范围取文字。',
    parameters: {
      doc: DOC_PARAM,
      frame: FRAME_PARAM,
      rect: { ...RECT, description: '表格所在的世界坐标矩形' },
      kind: { type: 'string', description: `表种：${env.spec.tableKinds.map(k => k.kind).join('、')}；省略为全部` },
      max_rows: { type: 'integer', description: '每张表在结果里最多列出的行数，默认 30' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          doc: { type: 'string', required: true },
          tables: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                kind: { ...NULLABLE_STRING, required: true },
                title: { ...NULLABLE_STRING, required: true },
                rect: { ...RECT, required: true },
                header_ref: { ...NULLABLE_STRING, required: true },
                n_rows: { type: 'integer', required: true },
                n_cols: { type: 'integer', required: true },
                rows: { type: 'array', required: true, items: { type: 'array', items: { type: 'string' } } },
                truncated_rows: { type: 'boolean', required: true },
                csv: { ...NULLABLE_STRING, required: true },
              },
            },
          },
          warnings: { type: 'array', required: true, items: { type: 'string' } },
        },
      },
      render: (_args, v) => {
        if (v.tables.length === 0) return [{ type: 'text', text: `没有找到表格。${v.warnings.join(' ')}` }]
        const parts = v.tables.map((t, i) => [
          `表 ${i + 1}${t.kind !== null ? ` [${t.kind}]` : ''}${t.title !== null ? ` ${t.title}` : ''} 范围 ${JSON.stringify(t.rect)} ${t.n_rows}行×${t.n_cols}列${t.truncated_rows ? `（只列前 ${t.rows.length} 行）` : ''}`,
          t.rows.map(r => r.join('\t')).join('\n'),
          t.csv !== null ? `CSV：${t.csv}` : '没有识别出网格',
        ].join('\n'))
        return [{ type: 'text', text: [...parts, ...v.warnings.map(w => `警告：${w}`)].join('\n\n') }]
      },
    },
    isConcurrencySafe: () => true,
    async execute(args) {
      const doc = env.docs.get(args.doc)
      const frame = frameArg(env, doc, args.frame)
      const round = rounder(doc.unit.unit)
      const maxRows = args.max_rows !== undefined && args.max_rows >= 1 ? Math.floor(args.max_rows) : 30
      const warnings: string[] = []
      const found: Array<{ kind: string | null; title: string | null; rect: Rect; headerRef: string | null; table: TableResult | null }> = []
      if (args.rect !== undefined) {
        const rect = normalizeRect(args.rect)
        found.push({ kind: null, title: null, rect, headerRef: null, table: extractTable(doc.scene, rect) })
      } else {
        const kinds = args.kind !== undefined && args.kind !== '' ? env.spec.tableKinds.filter(k => k.kind === args.kind) : env.spec.tableKinds
        if (kinds.length === 0) throw new Error(`未知表种 ${args.kind}；可用：${env.spec.tableKinds.map(k => k.kind).join('、')}`)
        for (const t of locateTables(doc.scene, kinds, frame, env.spec.tableMinHeaderHits)) {
          found.push({ kind: t.kind, title: t.title, rect: t.rect, headerRef: textRef(t.headerTextId), table: t.table })
        }
        if (found.length === 0) warnings.push(`没有找到含至少 ${env.spec.tableMinHeaderHits} 个表头词的行；可用 cad_text_search 查表名后用 rect 指定范围`)
      }
      const tables = []
      for (const [i, f] of found.entries()) {
        let csv: string | null = null
        if (f.table !== null) {
          csv = await writeResultFile(doc.cacheDir, 'out', `${doc.id}-table-${shortHash(args)}-${i + 1}.csv`, `﻿${tableToCsv(f.table)}\n`)
        }
        tables.push({
          kind: f.kind,
          title: f.title,
          rect: roundRect(f.rect, round),
          header_ref: f.headerRef,
          n_rows: f.table?.nRows ?? 0,
          n_cols: f.table?.nCols ?? 0,
          rows: f.table?.rows.slice(0, maxRows) ?? [],
          truncated_rows: (f.table?.nRows ?? 0) > maxRows,
          csv,
        })
      }
      return { doc: doc.id, tables, warnings }
    },
  }))

  ctx.tools.register(defineTool({
    name: 'cad_diff',
    description: '比较两张已打开的图纸（如同一楼层的新旧版本）：线段级新增/删除/不变计数（自动估计平移配准），文字新增/删除，块数量变化；render=true 另出一张差异图（红=新增，绿=删除，灰=不变）。'
      + '只处理平移，不处理旋转缩放；两图单位须一致。',
    parameters: {
      old_doc: { type: 'string', required: true, description: '旧图 doc' },
      new_doc: { type: 'string', required: true, description: '新图 doc' },
      render: { type: 'boolean', description: '输出差异图' },
      limit: { type: 'integer', description: '文字差异最多列出条数' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          old_doc: { type: 'string', required: true },
          new_doc: { type: 'string', required: true },
          segments: { type: 'json', required: true },
          offset: { type: 'json', required: true },
          texts_added: { type: 'json', required: true, description: '[{text, count}]' },
          texts_removed: { type: 'json', required: true },
          blocks_changed: { type: 'json', required: true, description: '[{name, old, new, delta}]' },
          file: { type: 'string', required: true },
          image: { type: 'json', required: true, description: '{path, image_size, world_rect, px_per_unit} 或 null' },
          warnings: { type: 'array', required: true, items: { type: 'string' } },
        },
      },
      render: (_args, v) => [{
        type: 'text',
        text: [
          `线段 ${JSON.stringify(v.segments)} 配准 ${JSON.stringify(v.offset)}`,
          `新增文字 ${JSON.stringify(v.texts_added)}`,
          `删除文字 ${JSON.stringify(v.texts_removed)}`,
          `块数量变化 ${JSON.stringify(v.blocks_changed)}`,
          `明细：${v.file}`,
          ...v.image !== null ? [`差异图 ${JSON.stringify(v.image)}，用 read_image 查看`] : [],
          ...v.warnings.map(w => `警告：${w}`),
        ].join('\n'),
      }],
    },
    async execute(args) {
      const oldDoc = env.docs.get(args.old_doc)
      const newDoc = env.docs.get(args.new_doc)
      if (oldDoc.unit.unit !== newDoc.unit.unit) throw new Error(`两张图单位不同（${oldDoc.unit.unit} / ${newDoc.unit.unit}），先用 cad_set_unit 统一确认`)
      const warnings: string[] = []
      if (oldDoc.unit.status !== 'confirmed' || newDoc.unit.status !== 'confirmed') warnings.push('单位未确认：量化容差按 mm 假设')
      const eps = env.spec.diffEpsMm / MM_PER_UNIT[oldDoc.unit.unit]
      const diff = diffScenes(oldDoc.scene, newDoc.scene, eps)
      const dx = diff.offset?.dx ?? 0
      const dy = diff.offset?.dy ?? 0
      const textCounts = (texts: ReadonlyArray<{ str: string }>): Map<string, number> => {
        const m = new Map<string, number>()
        for (const t of texts) m.set(t.str, (m.get(t.str) ?? 0) + 1)
        return m
      }
      const oldTexts = textCounts(oldDoc.scene.texts)
      const newTexts = textCounts(newDoc.scene.texts)
      const added: Array<{ text: string; count: number }> = []
      const removed: Array<{ text: string; count: number }> = []
      for (const [s, n] of newTexts) { const o = oldTexts.get(s) ?? 0; if (n > o) added.push({ text: s, count: n - o }) }
      for (const [s, o] of oldTexts) { const n = newTexts.get(s) ?? 0; if (o > n) removed.push({ text: s, count: o - n }) }
      added.sort((a, b) => b.count - a.count)
      removed.sort((a, b) => b.count - a.count)
      const oldBlocks = new Map(countBlocks(oldDoc.scene).map(b => [b.name, b.count]))
      const newBlocks = new Map(countBlocks(newDoc.scene).map(b => [b.name, b.count]))
      const blocksChanged: Array<{ name: string; old: number; new: number; delta: number }> = []
      for (const name of new Set([...oldBlocks.keys(), ...newBlocks.keys()])) {
        const o = oldBlocks.get(name) ?? 0
        const n = newBlocks.get(name) ?? 0
        if (o !== n) blocksChanged.push({ name, old: o, new: n, delta: n - o })
      }
      blocksChanged.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
      const limit = effectiveLimit(env, args.limit)
      const file = await writeResultFile(newDoc.cacheDir, 'out', `${oldDoc.id}-${newDoc.id}-diff.tsv`, `${toTsv(['kind', 'value', 'count'], [
        ...added.map(a => ['text_added', a.text, a.count] as const),
        ...removed.map(a => ['text_removed', a.text, a.count] as const),
        ...blocksChanged.map(b => ['block_delta', b.name, b.delta] as const),
      ])}\n`)
      let image: { path: string; image_size: number[]; world_rect: Rect; px_per_unit: number } | null = null
      if (args.render === true) {
        const b = diff.scene.bbox
        const rect = { x1: b.minX, y1: b.minY, x2: b.maxX, y2: b.maxY }
        const scale = env.spec.render.maxPx / Math.max(rect.x2 - rect.x1, rect.y2 - rect.y1, 1e-9)
        const fonts = env.fonts()
        const out = renderRegion({
          scene: diff.scene, rect, scale, only: null, hidden: new Set(), textMode: 'none', grid: null, highlights: [],
          dropTextPx: env.spec.render.dropTextPx, maxLabels: 0, shx: fonts.shx, fontFamily: fonts.family,
        })
        const path = await writeResultFile(newDoc.cacheDir, 'render', `${oldDoc.id}-${newDoc.id}-diff.png`, out.png)
        const round = rounder(newDoc.unit.unit)
        image = { path, image_size: [out.width, out.height], world_rect: roundRect(rect, round), px_per_unit: Number(scale.toPrecision(6)) }
      }
      return {
        old_doc: oldDoc.id,
        new_doc: newDoc.id,
        segments: diff.counts,
        offset: diff.offset !== undefined ? { dx, dy, votes: diff.offset.votes } : null,
        texts_added: added.slice(0, limit),
        texts_removed: removed.slice(0, limit),
        blocks_changed: blocksChanged.slice(0, limit),
        file,
        image,
        warnings,
      }
    },
  }))
}
