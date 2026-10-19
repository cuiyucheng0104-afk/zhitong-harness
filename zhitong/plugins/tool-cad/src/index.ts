/**
 * CAD drawing reader for 智通数工AI: structured reading first, images on
 * demand. DWG converts to DXF through the LibreDWG `dwg2dxf` executable
 * (separate process, `ctx.subprocess`); DXF parses into a headless scene that
 * the tools query for frames and title blocks, texts, blocks and door/window
 * labels, tables, and rooms. `cad_render` rasterizes one frame overview or
 * one zoomed region per call for `read_image`. Counts and areas are always
 * computed here, never read off images; dimensional tools refuse while the
 * drawing unit is unconfirmed.
 *
 * Tools: `cad_open`, `cad_layers`, `cad_frames`, `cad_text_search`,
 * `cad_blocks`, `cad_render`, `cad_set_unit`, `cad_rooms`, `cad_table`,
 * `cad_diff`.
 * @module @zhitong/tool-cad
 */
import { readFileSync } from 'node:fs'
import { basename } from 'node:path'
import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-subprocess'
import type {} from '@deepseek-ai/dsh-tools'
import { Config, resolveSpec } from './config.ts'
import { ShxTextEngine } from './core/shxText.ts'
import { CadDocuments } from './documents.ts'
import { registerFont } from './render/raster.ts'
import { registerAnalysisTools } from './tools/analysis.ts'
import { registerReadTools } from './tools/read.ts'
import { registerRenderTool } from './tools/render.ts'
import type { ToolEnv } from './tools/shared.ts'

export { Config, resolveSpec } from './config.ts'
export type { ToolCadSpec } from './config.ts'

export const name = 'zhitong-tool-cad'
export const inject = ['tools', 'subprocess']

/** Font family alias the fallback font registers under. */
const FALLBACK_FAMILY = 'ZT CAD Sans'

/**
 * Register the CAD tools.
 * @param ctx - plugin context.
 * @param config - validated plugin config.
 */
export function apply(ctx: Context, config: Config): void {
  const spec = resolveSpec(config)
  const docs = new CadDocuments(spec, () => ctx.subprocess)
  let fonts: { shx: ShxTextEngine; family: string } | null = null
  const env: ToolEnv = {
    spec,
    docs,
    fonts: () => {
      if (fonts === null) {
        const shx = new ShxTextEngine()
        for (const path of spec.shxFonts) {
          const buf = readFileSync(path)
          shx.loadFont(basename(path), buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength))
        }
        registerFont(spec.fallbackFont, FALLBACK_FAMILY)
        fonts = { shx, family: FALLBACK_FAMILY }
      }
      return fonts
    },
  }
  registerReadTools(ctx, env)
  registerRenderTool(ctx, env)
  registerAnalysisTools(ctx, env)
}
