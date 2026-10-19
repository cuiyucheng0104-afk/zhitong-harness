/** Schema fragments and helpers shared by the tool modules. @module @zhitong/tool-cad/tools/shared */

import type { ToolCadSpec } from '../config.ts'
import type { Rect } from '../core/geometry.ts'
import type { ShxTextEngine } from '../core/shxText.ts'
import { unitEvidence } from '../core/unit.ts'
import type { CadDoc, CadDocuments, DocFrame } from '../documents.ts'

/** What every tool module receives from the plugin. */
export interface ToolEnv {
  spec: ToolCadSpec
  docs: CadDocuments
  /** Lazily loaded SHX engine and registered fallback font family. */
  fonts: () => { shx: ShxTextEngine; family: string }
}

/** Nullable string schema. */
export const NULLABLE_STRING = { oneOf: [{ type: 'string' }, { type: 'null' }] } as const
/** Nullable number schema. */
export const NULLABLE_NUMBER = { oneOf: [{ type: 'number' }, { type: 'null' }] } as const

/** World rectangle schema (`x1 ≤ x2`, `y1 ≤ y2` in results). */
export const RECT = {
  type: 'object',
  additionalProperties: false,
  properties: {
    x1: { type: 'number', required: true },
    y1: { type: 'number', required: true },
    x2: { type: 'number', required: true },
    y2: { type: 'number', required: true },
  },
} as const

/** Nullable rectangle schema. */
export const NULLABLE_RECT = { oneOf: [RECT, { type: 'null' }] } as const

/** Shared `doc` parameter. */
export const DOC_PARAM = { type: 'string', required: true, description: 'cad_open 返回的 doc' } as const

/** Shared optional `frame` parameter. */
export const FRAME_PARAM = { type: 'string', description: '图框 id（cad_frames 返回，如 S1、F2）；省略为整张图' } as const

/**
 * Rectangle rounded for output.
 * @param r - rectangle.
 * @param round - coordinate rounding.
 * @returns the rounded rectangle.
 */
export function roundRect(r: Rect, round: (v: number) => number): Rect {
  return { x1: round(r.x1), y1: round(r.y1), x2: round(r.x2), y2: round(r.y2) }
}

/**
 * Text id as shown to the model.
 * @param index - scene text index.
 * @returns `T<index>`.
 */
export function textRef(index: number): string {
  return `T${index}`
}

/**
 * Parse a text id.
 * @param ref - `T<index>` or a bare index.
 * @returns the scene text index.
 * @throws when the id is malformed.
 */
export function parseTextRef(ref: string): number {
  const m = /^T?(\d+)$/i.exec(ref.trim())
  if (m === null) throw new Error(`文字 id ${ref} 不合法；应为 T 加数字，如 T12`)
  return Number(m[1])
}

/**
 * The region a frame argument selects.
 * @param env - tool environment.
 * @param doc - open document.
 * @param frame - frame id, or undefined for the whole drawing.
 * @returns the frame, or null for the whole drawing.
 */
export function frameArg(env: ToolEnv, doc: CadDoc, frame: string | undefined): DocFrame | null {
  return frame === undefined || frame === '' ? null : env.docs.frame(doc, frame)
}

/**
 * Clamp a requested row limit.
 * @param env - tool environment.
 * @param limit - requested limit.
 * @returns the effective limit.
 */
export function effectiveLimit(env: ToolEnv, limit: number | undefined): number {
  if (limit === undefined) return env.spec.listLimit
  if (!(limit >= 1)) throw new Error('limit 必须是正整数')
  return Math.min(Math.floor(limit), env.spec.listMaxLimit)
}

/**
 * Refuse a dimensional operation while the unit is unconfirmed.
 * @param doc - open document.
 * @param what - operation name for the message.
 * @throws with the unit evidence and the confirmation instruction when unconfirmed.
 */
export function requireConfirmedUnit(doc: CadDoc, what: string): void {
  if (doc.unit.status === 'confirmed') return
  const ev = unitEvidence(doc.scene)
  throw new Error(`单位未确认，${what}需要量纲，已拒绝执行。证据：${ev.hint}。`
    + `请向用户确认图纸单位后调用 cad_set_unit（unit + basis），或在证据一致时用 cad_set_unit verify=true 按尺寸标注比对确认`)
}

/**
 * Frame label lookup used by per-frame grouping.
 * @param frames - document frames.
 * @returns rectangles labelled with frame ids.
 */
export function frameLabels(frames: readonly DocFrame[]): Array<{ label: string; x1: number; y1: number; x2: number; y2: number }> {
  return frames.map(f => ({ label: f.id, x1: f.x1, y1: f.y1, x2: f.x2, y2: f.y2 }))
}
