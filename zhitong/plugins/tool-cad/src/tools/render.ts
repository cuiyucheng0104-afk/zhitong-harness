/**
 * `cad_render`: one PNG per call. A frame alone gives the overview with a
 * lettered grid and texts drawn as empty boxes; a cell, rectangle, point
 * neighbourhood, text id, or handle gives a zoomed view with texts drawn. The
 * result carries the image path, its world rectangle, pixels per unit, and
 * (for `text=ids`) the number → text id table, so the model can read the image
 * with `read_image` and map what it sees back to structured rows.
 * @module @zhitong/tool-cad/tools/render
 */
import type { Context } from '@deepseek-ai/cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import type { Rect } from '../core/geometry.ts'
import { rounder, shortHash, toTsv, writeResultFile } from '../output.ts'
import type { TargetArgs } from '../render/plan.ts'
import { planRender } from '../render/plan.ts'
import type { TextMode } from '../render/raster.ts'
import { gridColumnName, renderRegion } from '../render/raster.ts'
import type { ToolEnv } from './shared.ts'
import { DOC_PARAM, NULLABLE_NUMBER, NULLABLE_STRING, RECT, parseTextRef, roundRect, textRef } from './shared.ts'

/**
 * Register `cad_render`.
 * @param ctx - plugin context.
 * @param env - tool environment.
 */
export function registerRenderTool(ctx: Context, env: ToolEnv): void {
  const r = env.spec.render
  ctx.tools.register(defineTool({
    name: 'cad_render',
    description: '把图纸的一个区域渲染成一张 PNG，返回路径与坐标元数据，然后用 read_image 看图。看图只用来定位和核对，数量、面积、文字内容以结构化工具为准。'
      + `先出总览：只给 frame，得到整张图框一张图，带 A–${gridColumnName(r.gridLongSide - 1)} 列、1… 行的网格，文字画成空框；`
      + '再按需放大：frame+cell（如 C3）、rect、around{x,y,r}、text_id 或 handle 任选其一，文字照常画出，比例按字高自动取。'
      + 'text=ids 时文字框旁标编号，结果里给出编号→文字 id 对照。不能不指定目标渲染整张图；局部范围过大会被拒绝。一次问答通常 2–4 张就够。',
    parameters: {
      doc: DOC_PARAM,
      frame: { type: 'string', description: '图框 id；单独给出时出该图框总览' },
      cell: { type: 'string', description: '总览网格的格子，如 C3；需同时给 frame' },
      rect: { ...RECT, description: '世界坐标矩形' },
      around: {
        type: 'object',
        additionalProperties: false,
        description: '以点为中心、r 为半边长的正方形',
        properties: { x: { type: 'number', required: true }, y: { type: 'number', required: true }, r: { type: 'number', required: true } },
      },
      text_id: { type: 'string', description: '文字 id（cad_text_search 的 T 编号），以它为中心放大' },
      handle: { type: 'string', description: '实体句柄（文字、块引用或闭合多段线所属的顶层实体）' },
      layers: { type: 'array', items: { type: 'string' }, description: '只画这些图层' },
      hide_layers: { type: 'array', items: { type: 'string' }, description: '不画这些图层；冻结与关闭的图层默认不画' },
      text: { type: 'string', enum: ['draw', 'boxes', 'ids', 'none'], description: '文字画法；总览默认 boxes，放大默认 draw' },
      grid: { type: 'boolean', description: '是否画网格；总览默认画' },
      max_px: { type: 'integer', description: `图片长边像素，默认 ${r.maxPx}，上限 ${r.hardMaxPx}` },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          doc: { type: 'string', required: true },
          path: { type: 'string', required: true },
          image_size: { type: 'array', required: true, items: { type: 'integer' }, description: '[宽, 高] 像素' },
          world_rect: { ...RECT, required: true, description: '整张图片对应的世界坐标范围' },
          px_per_unit: { type: 'number', required: true, description: '每图纸单位的像素数；像素 (px,py) → 世界 (x1+px/s, y2−py/s)' },
          unit: { type: 'string', required: true },
          target: { type: 'json', required: true },
          grid: { type: 'json', required: true, description: '总览网格 {cols, rows, rect}；放大图为 null' },
          text_px_median: { ...NULLABLE_NUMBER, required: true },
          labels: {
            type: 'array',
            required: true,
            items: {
              type: 'object',
              additionalProperties: false,
              properties: { n: { type: 'integer', required: true }, id: { type: 'string', required: true }, text: { type: 'string', required: true } },
            },
          },
          stats: { type: 'json', required: true },
          hidden_layers: { type: 'array', required: true, items: { type: 'string' } },
          warnings: { type: 'array', required: true, items: { type: 'string' } },
          frame: { ...NULLABLE_STRING, required: true },
        },
      },
      render: (_args, v) => {
        const lines = [
          `已出图 ${v.path}（${v.image_size[0]}×${v.image_size[1]} px），用 read_image 查看。`,
          `world_rect=${JSON.stringify(v.world_rect)} px_per_unit=${v.px_per_unit} 单位 ${v.unit} 目标 ${JSON.stringify(v.target)}`,
        ]
        if (v.grid !== null) lines.push(`网格 ${JSON.stringify(v.grid)}；放大某格用 cad_render(frame, cell)`)
        if (v.text_px_median !== null) lines.push(`文字中位高度约 ${v.text_px_median} px`)
        lines.push(`绘制 ${JSON.stringify(v.stats)}${v.hidden_layers.length > 0 ? `；未画图层 ${v.hidden_layers.join(',')}` : ''}`)
        if (v.labels.length > 0) lines.push('编号对照：', toTsv(['编号', '文字id', '文字'], v.labels.map(l => [l.n, l.id, l.text])))
        for (const w of v.warnings) lines.push(`警告：${w}`)
        return [{ type: 'text', text: lines.join('\n') }]
      },
    },
    presentCall: args => ({ card: 'generic', title: `CAD 出图 ${args.frame ?? ''}${args.cell !== undefined ? ` ${args.cell}` : ''}`.trim(), kind: 'read' }),
    async execute(args) {
      const doc = env.docs.get(args.doc)
      const { frames } = env.docs.frames(doc)
      if (args.max_px !== undefined && !(args.max_px >= 200 && args.max_px <= r.hardMaxPx)) {
        throw new Error(`max_px 必须在 200–${r.hardMaxPx} 之间`)
      }
      const maxPx = args.max_px ?? r.maxPx
      const target: TargetArgs = {
        ...args.frame !== undefined && args.frame !== '' ? { frame: args.frame } : {},
        ...args.cell !== undefined && args.cell !== '' ? { cell: args.cell } : {},
        ...args.rect !== undefined ? { rect: args.rect } : {},
        ...args.around !== undefined ? { around: args.around } : {},
        ...args.text_id !== undefined && args.text_id !== '' ? { textId: parseTextRef(args.text_id) } : {},
        ...args.handle !== undefined && args.handle !== '' ? { handle: args.handle } : {},
      }
      const plan = planRender(doc.scene, frames, target, {
        maxPx,
        hardMaxPx: Math.max(maxPx, r.hardMaxPx),
        minTextPx: r.minTextPx,
        gridLongSide: r.gridLongSide,
        maxZoomFraction: r.maxZoomFraction,
      })
      const hiddenByState = doc.scene.layerTable.filter(l => l.frozen || !l.visible).map(l => l.name)
      const hidden = new Set([...hiddenByState, ...args.hide_layers ?? []])
      const only = args.layers !== undefined && args.layers.length > 0 ? new Set(args.layers) : null
      const textMode: TextMode = args.text ?? (plan.kind === 'overview' ? 'boxes' : 'draw')
      const wantGrid = args.grid ?? plan.kind === 'overview'
      const fonts = env.fonts()
      const result = renderRegion({
        scene: doc.scene,
        rect: plan.imageRect,
        scale: plan.scale,
        only,
        hidden: only !== null ? new Set<string>() : hidden,
        textMode,
        grid: wantGrid ? plan.grid : null,
        highlights: [],
        dropTextPx: r.dropTextPx,
        maxLabels: r.maxLabels,
        shx: fonts.shx,
        fontFamily: fonts.family,
      })
      const name = `${doc.id}-${plan.frame?.id ?? 'X'}${plan.cell !== null ? `-${plan.cell}` : ''}-${shortHash({ ...args, doc: doc.id })}.png`
      const path = await writeResultFile(doc.cacheDir, 'render', name, result.png)
      const round = rounder(doc.unit.unit)
      const worldRect: Rect = roundRect(plan.imageRect, round)
      const warnings = [...plan.warnings]
      if (result.stats.textsDropped > 0 && textMode !== 'none') warnings.push(`${result.stats.textsDropped} 条文字小于 ${r.dropTextPx} px 未画；放大局部可看清`)
      if (textMode === 'ids' && result.stats.textsBoxed > result.labels.length) warnings.push(`文字框 ${result.stats.textsBoxed} 个，只编号前 ${result.labels.length} 个（从上到下、从左到右）`)
      if (doc.unit.status === 'unconfirmed') warnings.push('单位未确认；坐标按图纸单位给出')
      return {
        doc: doc.id,
        path,
        image_size: [result.width, result.height],
        world_rect: worldRect,
        px_per_unit: Number(plan.scale.toPrecision(6)),
        unit: doc.unit.unit,
        target: { kind: plan.kind, frame: plan.frame?.id ?? null, cell: plan.cell, region: roundRect(plan.region, round) },
        grid: plan.grid !== null && wantGrid ? { cols: plan.grid.cols, rows: plan.grid.rows, rect: roundRect(plan.grid.rect, round) } : null,
        text_px_median: result.medianTextPx !== null ? Math.round(result.medianTextPx) : null,
        labels: result.labels.map(l => ({ n: l.n, id: textRef(l.textId), text: doc.scene.texts[l.textId]!.str })),
        stats: {
          segments: result.stats.segments,
          fills: result.stats.triangles,
          texts_shx: result.stats.textsShx,
          texts_font: result.stats.textsFont,
          texts_boxed: result.stats.textsBoxed,
          texts_dropped: result.stats.textsDropped,
        },
        hidden_layers: only !== null ? [] : [...hidden].sort(),
        warnings,
        frame: plan.frame?.id ?? null,
      }
    },
  }))
}
