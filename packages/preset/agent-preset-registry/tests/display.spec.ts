/**
 * Display resolution: shipped presets resolve through dictionary keys, and
 * user-authored metadata is never translated.
 */

import { describe, expect, it } from 'vitest'
import { isBuiltInPreset, presetDisplayText, type BuiltInPresetCopyKey } from '../src/display.ts'

const t = (key: BuiltInPresetCopyKey): string => `t:${key}`

describe('presetDisplayText', () => {
  it('resolves a shipped preset through its dictionary keys', () => {
    expect(presetDisplayText({ id: 'standard' }, t)).toEqual({
      name: 't:presetStandardName',
      description: 't:presetStandardDescription',
    })
  })

  // zhitong increment: the 智通数工AI preset row publishes no name and resolves as a shipped preset.
  it('resolves the 智通数工AI preset through its dictionary keys and files it as built-in', () => {
    expect(isBuiltInPreset({ id: 'zhitong' })).toBe(true)
    expect(presetDisplayText({ id: 'zhitong' }, t)).toEqual({
      name: 't:presetZhitongName',
      description: 't:presetZhitongDescription',
    })
    expect(isBuiltInPreset({ id: 'zhitong', name: '智通数工AI' })).toBe(false)
  })

  it('keeps user-authored metadata untranslated', () => {
    expect(presetDisplayText({ id: 'mine', name: '我的模式', description: '自述' }, t))
      .toEqual({ name: '我的模式', description: '自述' })
  })

  it('falls back to the id for a preset publishing no metadata', () => {
    // A system id outside the shipped set behaves like authored metadata:
    // there is no dictionary copy to resolve.
    expect(presetDisplayText({ id: 'future' }, t)).toEqual({ name: 'future' })
    expect(presetDisplayText({ id: 'bare' }, t)).toEqual({ name: 'bare' })
  })
})
