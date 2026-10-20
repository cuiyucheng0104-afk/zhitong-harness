#!/usr/bin/env node
/**
 * Check an installed or unpacked 智通数工AI Desktop application without starting it.
 *
 * Usage: node zhitong/scripts/verify-desktop-app.mjs <智通数工AI.app | install directory | resources directory>
 *
 * Checks, printing one line each and exiting 1 when any fails:
 * - the runtime descriptor (`app.asar/dsh/desktop-runtime.json`, read through the unpacked twin when Node has
 *   no asar support) lists @zhitong/bundle and its four plugins;
 * - the application executable carries the product name (macOS `Contents/MacOS/智通数工AI`, Windows `ztsgai.exe`)
 *   and app.asar holds the `@zhitong/ui-brand` browser bundle the client module registry serves;
 * - `app.asar.unpacked/dsh/node_modules/@zhitong/bundle/skills` holds `_shared/zt_launch.py` and every zt-* SKILL.md,
 *   and `python/zt` sits beside it;
 * - the bundled Python (`runtime/primary-runtime`) runs each skill script with `--help` through the launcher,
 *   with ZT_PYTHON unset and an empty DSH_HOME, and imports zt's dependencies;
 * - tool-cad's dwg2dxf for this machine is present and executable, with COPYING, VERSION.txt and SOURCE-OFFER.txt.
 */

import { spawnSync } from 'node:child_process'
import { accessSync, constants, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const EXPECTED_SKILLS = ['zt-archive', 'zt-ask', 'zt-cad', 'zt-estimate', 'zt-indicator', 'zt-knowledge', 'zt-project',
  'zt-quantity', 'zt-reconcile', 'zt-report', 'zt-tk', 'zt-volc']
const ZHITONG_PACKAGES = ['@zhitong/bundle', '@zhitong/config-import', '@zhitong/tool-cad', '@zhitong/tool-tos', '@zhitong/ui-brand']
/** macOS executable (productName) and Windows executable (win.executableName) in apps/desktop/scripts/electron-builder-config.mjs. */
const MAC_EXECUTABLE = '智通数工AI'
const WINDOWS_EXECUTABLE = 'ztsgai.exe'

/**
 * Locate the Electron resources directory from an application path.
 * @param {string} input - `.app` bundle, Windows install directory, or the resources directory itself.
 * @returns {string} Absolute resources directory.
 */
export function resourcesDirectory(input) {
  const path = resolve(input)
  for (const candidate of [path, join(path, 'Contents', 'Resources'), join(path, 'resources')]) {
    if (existsSync(join(candidate, 'app.asar.unpacked'))) return candidate
  }
  throw new Error(`verify-desktop-app: ${path} 下找不到 app.asar.unpacked（给 .app、安装目录或 resources 目录）`)
}

function readDescriptor(resources) {
  // Plain Node cannot read inside app.asar; electron-builder archives the descriptor, so parse the archive directly.
  const unpacked = join(resources, 'app.asar.unpacked', 'dsh', 'desktop-runtime.json')
  if (existsSync(unpacked)) return JSON.parse(readFileSync(unpacked, 'utf8'))
  const archive = join(resources, 'app.asar')
  if (!existsSync(archive)) return undefined
  return readAsarFile(archive, 'dsh/desktop-runtime.json')
}

/**
 * Read one JSON file stored (not unpacked) inside an asar archive.
 * @param {string} archive - Path of app.asar.
 * @param {string} file - Archive-relative path with `/` separators.
 * @returns {unknown} Parsed JSON, or undefined when the entry is absent or unpacked.
 */
export function readAsarFile(archive, file) {
  const bytes = readFileSync(archive)
  // asar header: Pickle(uint32 size) + Pickle(uint32 payload, uint32 strlen, json)
  const headerSize = bytes.readUInt32LE(4)
  const jsonLength = bytes.readUInt32LE(12)
  const header = JSON.parse(bytes.subarray(16, 16 + jsonLength).toString('utf8'))
  let node = header
  for (const part of file.split('/')) {
    node = node.files?.[part]
    if (node === undefined) return undefined
  }
  if (node.unpacked === true || typeof node.offset !== 'string') return undefined
  const start = 8 + headerSize + Number(node.offset)
  return JSON.parse(bytes.subarray(start, start + node.size).toString('utf8'))
}

/**
 * Whether an asar archive lists a file, packed or unpacked.
 * @param {string} archive - Path of app.asar.
 * @param {string} file - Archive-relative path with `/` separators.
 * @returns {boolean} True when the header has a file entry at that path.
 */
export function asarHasFile(archive, file) {
  const bytes = readFileSync(archive)
  const jsonLength = bytes.readUInt32LE(12)
  let node = JSON.parse(bytes.subarray(16, 16 + jsonLength).toString('utf8'))
  for (const part of file.split('/')) {
    node = node.files?.[part]
    if (node === undefined) return false
  }
  return node.files === undefined
}

/**
 * The application executable that sits beside a resources directory.
 * @param {string} resources - Electron resources directory (`Contents/Resources` or `resources`).
 * @returns {string} Absolute executable path for this layout.
 */
export function applicationExecutable(resources) {
  const macOS = join(resources, '..', 'MacOS')
  return existsSync(macOS) ? join(macOS, MAC_EXECUTABLE) : join(resources, '..', WINDOWS_EXECUTABLE)
}

function pythonPath(resources) {
  const root = join(resources, 'runtime', 'primary-runtime', 'dependencies', 'python')
  return process.platform === 'win32' ? join(root, 'python.exe') : join(root, 'bin', 'python3')
}

function main() {
  const input = process.argv[2]
  if (input === undefined) throw new Error('usage: node zhitong/scripts/verify-desktop-app.mjs <智通数工AI.app | 安装目录 | resources 目录>')
  const resources = resourcesDirectory(input)
  const results = []
  const check = (name, test) => {
    try {
      const detail = test()
      results.push(true)
      console.log(`ok    ${name}${detail ? `：${detail}` : ''}`)
    } catch (error) {
      results.push(false)
      console.log(`FAIL  ${name}：${error instanceof Error ? error.message : String(error)}`)
    }
  }

  check('运行时描述列出 zhitong 包', () => {
    const descriptor = readDescriptor(resources)
    if (descriptor === undefined) throw new Error('读不到 dsh/desktop-runtime.json')
    const names = new Set(descriptor.sharedPackages.map(entry => entry.name))
    const missing = ZHITONG_PACKAGES.filter(name => !names.has(name))
    if (missing.length > 0) throw new Error(`缺少 ${missing.join(', ')}`)
    return ZHITONG_PACKAGES.join(', ')
  })

  check('应用名与品牌客户端包', () => {
    const executable = applicationExecutable(resources)
    if (!existsSync(executable)) throw new Error(`${executable} 不存在（应用名应为智通数工AI）`)
    const archive = join(resources, 'app.asar')
    const client = 'dsh/node_modules/@zhitong/ui-brand/lib/client.js'
    if (!existsSync(archive) || !asarHasFile(archive, client)) throw new Error(`app.asar 里没有 ${client}`)
    return executable
  })

  const bundle = join(resources, 'app.asar.unpacked', 'dsh', 'node_modules', '@zhitong', 'bundle')
  const skills = join(bundle, 'skills')
  check('skills 在 asar 外', () => {
    if (!existsSync(join(skills, '_shared', 'zt_launch.py'))) throw new Error(`${skills}/_shared/zt_launch.py 不存在`)
    const present = readdirSync(skills).filter(name => existsSync(join(skills, name, 'SKILL.md'))).sort()
    const missing = EXPECTED_SKILLS.filter(name => !present.includes(name))
    if (missing.length > 0) throw new Error(`缺少 ${missing.join(', ')}`)
    if (!existsSync(join(bundle, 'python', 'zt', '__init__.py'))) throw new Error('python/zt 不在 skills 旁')
    return `${present.length} 个 skill`
  })

  const python = pythonPath(resources)
  const home = mkdtempSync(join(tmpdir(), 'zt-verify-home-'))
  try {
    const env = { ...process.env, DSH_HOME: home }
    delete env.ZT_PYTHON
    delete env.ZT_LAUNCHED
    check('内置 Python 带齐 zt 依赖', () => {
      const run = spawnSync(python, ['-I', '-c', 'import sys, pydantic, yaml, openpyxl, pypdf, docx; print(sys.version.split()[0])'],
        { encoding: 'utf8', env, timeout: 120_000 })
      if (run.status !== 0) throw new Error(`${python}：${run.stderr || run.error?.message}`)
      return `Python ${run.stdout.trim()}`
    })
    for (const skill of EXPECTED_SKILLS) {
      const directory = join(skills, skill, 'scripts')
      if (!existsSync(directory)) continue
      for (const script of readdirSync(directory).filter(name => name.endsWith('.py')).sort()) {
        check(`${skill}/scripts/${script} --help`, () => {
          const run = spawnSync(python, [join(directory, script), '--help'], { encoding: 'utf8', env, cwd: home, timeout: 120_000 })
          if (run.status !== 0) throw new Error(`退出码 ${String(run.status)}：${(run.stdout + run.stderr).trim().slice(0, 400)}`)
          return ''
        })
      }
    }
  } finally {
    rmSync(home, { recursive: true, force: true })
  }

  check('dwg2dxf 在 asar 外且可执行', () => {
    const directory = join(resources, 'app.asar.unpacked', 'dsh', 'node_modules', '@zhitong', 'tool-cad', 'bin', `${process.platform}-${process.arch}`)
    const binary = join(directory, process.platform === 'win32' ? 'dwg2dxf.exe' : 'dwg2dxf')
    if (!statSync(binary).isFile()) throw new Error(`${binary} 不是文件`)
    if (process.platform !== 'win32') accessSync(binary, constants.X_OK)
    for (const file of ['COPYING', 'VERSION.txt', 'SOURCE-OFFER.txt']) {
      if (!existsSync(join(directory, file))) throw new Error(`缺少 ${file}`)
    }
    const run = spawnSync(binary, ['--version'], { encoding: 'utf8', cwd: directory, timeout: 60_000 })
    if (run.error !== undefined) throw run.error
    return `${readFileSync(join(directory, 'VERSION.txt'), 'utf8').split(/\r?\n/u)[0]}；--version 退出码 ${String(run.status)}`
  })

  const failed = results.filter(ok => !ok).length
  console.log(failed === 0 ? `全部 ${results.length} 项通过` : `${failed} / ${results.length} 项失败`)
  process.exitCode = failed === 0 ? 0 : 1
}

if (import.meta.main) main()
