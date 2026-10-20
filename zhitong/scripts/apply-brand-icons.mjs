#!/usr/bin/env node
/**
 * Copy the 智通数工AI application icons from `zhitong/brand/icons/` into `apps/desktop/resources/` under
 * `zhitong-*` names, beside the upstream DeepSeek Harness artwork, which stays untouched.
 *
 * electron-builder reads them only after `apps/desktop/scripts/electron-builder-config.mjs` (and the development
 * paths in `apps/desktop/src/main.ts`) name these files; `zhitong/brand/README.md` lists the exact lines.
 * The icons themselves come from `zhitong/scripts/brand-icons/render-brand-icons.mjs`.
 *
 * Usage: node zhitong/scripts/apply-brand-icons.mjs [--check]
 * `--check` copies nothing and exits 1 when a destination is missing or differs from its source.
 */

import { copyFileSync, existsSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { parseArgs } from 'node:util'

const ZHITONG = resolve(import.meta.dirname, '..')
const ICONS = join(ZHITONG, 'brand', 'icons')
const RESOURCES = join(ZHITONG, '..', 'apps', 'desktop', 'resources')

/** Source in zhitong/brand/icons → destination in apps/desktop/resources, and what reads it. */
export const BRAND_ICON_FILES = [
  { from: 'icon.icns', to: 'zhitong-icon.icns', use: 'mac.icon (app bundle and DMG)' },
  { from: 'icon-macos-1024.png', to: 'zhitong-icon-macos.png', use: 'macOS 1024 px source, if a PNG is preferred' },
  { from: 'icon.ico', to: 'zhitong-icon.ico', use: 'win.icon (executable, installer, uninstaller)' },
  { from: 'icon-1024.png', to: 'zhitong-icon-windows.png', use: 'extraResources icon.png (window and About icon)' },
  { from: 'tray.ico', to: 'zhitong-tray-windows.ico', use: 'extraResources tray.ico (Windows tray)' },
]

const { values } = parseArgs({ options: { check: { type: 'boolean', default: false } } })
let stale = 0
for (const file of BRAND_ICON_FILES) {
  const source = join(ICONS, file.from)
  const destination = join(RESOURCES, file.to)
  if (!existsSync(source)) throw new Error(`apply-brand-icons: missing ${source}; run zhitong/scripts/brand-icons first`)
  const same = existsSync(destination) && readFileSync(source).equals(readFileSync(destination))
  if (values.check) {
    if (!same) {
      stale += 1
      console.error(`stale: apps/desktop/resources/${file.to} (from zhitong/brand/icons/${file.from})`)
    }
    continue
  }
  if (!same) copyFileSync(source, destination)
  console.info(`${same ? 'unchanged' : 'copied'}: apps/desktop/resources/${file.to} — ${file.use}`)
}
if (stale > 0) process.exit(1)
