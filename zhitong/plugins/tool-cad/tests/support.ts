import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context } from '@deepseek-ai/cordis'
import { ToolCallId } from '@deepseek-ai/dsh-llm'
import LocalSubprocessRuntime from '@deepseek-ai/dsh-subprocess-local'
import SystemPrompt from '@deepseek-ai/dsh-system-prompt'
import ToolRuntime from '@deepseek-ai/dsh-tools'
import type { ToolExecutionResult } from '@deepseek-ai/dsh-tools'
import type { BuiltScene, LayerGeom } from '../src/core/sceneBuilder.ts'

/**
 * A context with the tool runtime and the local subprocess provider.
 * @returns the context.
 */
export async function toolContext(): Promise<Context> {
  const ctx = new Context()
  await ctx.plugin(SystemPrompt)
  await ctx.plugin(ToolRuntime)
  await ctx.plugin(LocalSubprocessRuntime)
  return ctx
}

let counter = 0

/**
 * Execute one tool call through the registry.
 * @param ctx - context with the tool runtime.
 * @param name - tool name.
 * @param args - tool arguments.
 * @returns the execution result.
 */
export function call(ctx: Context, name: string, args: Record<string, unknown>): Promise<ToolExecutionResult> {
  return ctx.tools.execute({ signal: new AbortController().signal, callId: ToolCallId(`call-${++counter}`), name, arguments: args })
}

/**
 * The text of a result's content.
 * @param result - execution result.
 * @returns concatenated text blocks.
 */
export function text(result: ToolExecutionResult): string {
  return result.content.map(block => (block.type === 'text' ? block.text : '')).join('')
}

/**
 * A successful result's canonical value; fails the test with the error text otherwise.
 * @param result - execution result.
 * @returns the value.
 */
export function valueOf<T>(result: ToolExecutionResult): T {
  if (result.isError) throw new Error(`tool failed: ${text(result)}`)
  return result.value as T
}

/**
 * A fresh temporary directory removed by the returned disposer.
 * @param label - directory name prefix.
 * @returns the path and its cleanup.
 */
export function tempDir(label: string): { path: string; cleanup: () => void } {
  const path = mkdtempSync(join(tmpdir(), `zt-${label}-`))
  return { path, cleanup: () => rmSync(path, { recursive: true, force: true }) }
}

/**
 * Empty scene with overrides (synthetic fixtures that skip DXF parsing).
 * @param overrides - fields to set.
 * @returns the scene.
 */
export function emptyScene(overrides: Partial<BuiltScene> = {}): BuiltScene {
  return {
    layers: [],
    hatches: [],
    texts: [],
    inserts: [],
    header: { insunits: null, measurement: null, acadver: null, codepage: null },
    polys: [],
    dims: [],
    layerTable: [],
    bbox: { minX: 0, minY: 0, maxX: 1, maxY: 1 },
    stats: { entityCount: 0, segCount: 0, skipped: {}, parseMs: 0, buildMs: 0 },
    ...overrides,
  }
}

/**
 * Layer of white segments.
 * @param name - layer name.
 * @param segments - [x1, y1, x2, y2] segments.
 * @returns the layer geometry.
 */
export function makeLayer(name: string, segments: Array<[number, number, number, number]>): LayerGeom {
  const positions = new Float32Array(segments.length * 6)
  const colors = new Float32Array(segments.length * 6)
  segments.forEach(([x1, y1, x2, y2], i) => {
    positions.set([x1, y1, 0, x2, y2, 0], i * 6)
    colors.set([1, 1, 1, 1, 1, 1], i * 6)
  })
  return { name, positions, colors, segCount: segments.length }
}

/**
 * Text item with defaults for the fields a test does not care about.
 * @param str - text.
 * @param x - anchor X.
 * @param y - anchor Y.
 * @param layer - layer name.
 * @param h - height.
 * @returns the text item.
 */
export function textItem(str: string, x: number, y: number, layer = '0', h = 300): BuiltScene['texts'][number] {
  return { x, y, h, rot: 0, str, layer, rgb: 0xffffff, handle: 'H', block: null }
}
