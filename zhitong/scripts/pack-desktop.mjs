#!/usr/bin/env node
/**
 * Pack the 智通数工AI packages for the Desktop runtime tree (apps/desktop/scripts/package-target.ts runs this
 * between the dsh and vendor release packs).
 *
 * 1. Build every zhitong plugin to `lib/index.js` with its `tsdown.config.ts`; the packed manifest exports that
 *    file through `publishConfig`.
 * 2. Copy `zhitong/skills` and `zhitong/python/zt` into `zhitong/bundle/skills` and `zhitong/bundle/python/zt`
 *    (without bytecode caches) so the bundle tarball carries them; the copies are removed afterwards.
 * 3. `pnpm pack` the bundle and the plugins into `--out`, then check each tarball: the entry exists, every bare
 *    import of a built entry is a declared dependency or peer, the skills and `zt` are present, and tool-cad
 *    carries `bin/<platform>-<arch>/dwg2dxf[.exe]` with its GPL files for the target.
 *
 * Usage: node zhitong/scripts/pack-desktop.mjs --out <dir> --platform <darwin|win32|linux> --arch <arm64|x64>
 *        [--allow-missing-dwg2dxf]
 * `ZT_ALLOW_MISSING_DWG2DXF=1` has the same effect as `--allow-missing-dwg2dxf` (DXF-only installers).
 */

import { execFileSync, spawnSync } from 'node:child_process'
import { builtinModules } from 'node:module'
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { basename, dirname, join, relative, resolve } from 'node:path'
import { parseArgs } from 'node:util'

const ZHITONG = resolve(import.meta.dirname, '..')
const REPOSITORY = resolve(ZHITONG, '..')
const BUNDLE = join(ZHITONG, 'bundle')
const PLUGINS = ['tool-tos', 'config-import', 'tool-cad']
const STAGED = [
  { from: join(ZHITONG, 'skills'), to: join(BUNDLE, 'skills') },
  { from: join(ZHITONG, 'python', 'zt'), to: join(BUNDLE, 'python', 'zt') },
]
const CACHE_NAMES = new Set(['__pycache__', '.pytest_cache', '.DS_Store'])
const GPL_FILES = ['COPYING', 'VERSION.txt', 'SOURCE-OFFER.txt']

/**
 * Bare module specifiers a tsdown ESM bundle imports, excluding Node builtins.
 * @param {string} source - Bundled JavaScript.
 * @returns {string[]} Sorted unique specifiers.
 */
export function bareImports(source) {
  const found = new Set()
  const patterns = [
    /^\s*import\s[^;]*?\sfrom\s*["']([^"']+)["']/gmu,
    /^\s*import\s*["']([^"']+)["']/gmu,
    /^\s*export\s[^;]*?\sfrom\s*["']([^"']+)["']/gmu,
    /\bimport\(\s*["']([^"']+)["']\s*\)/gu,
  ]
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      const specifier = match[1]
      if (specifier.startsWith('.') || specifier.startsWith('/')) continue
      if (specifier.startsWith('node:') || builtinModules.includes(specifier)) continue
      found.add(specifier)
    }
  }
  return [...found].sort()
}

/**
 * Package name of a bare specifier (`@scope/name/sub` → `@scope/name`).
 * @param {string} specifier - Bare import specifier.
 * @returns {string} Package name.
 */
export function packageName(specifier) {
  const parts = specifier.split('/')
  return specifier.startsWith('@') ? parts.slice(0, 2).join('/') : parts[0]
}

/**
 * Bare imports of a built entry that the manifest does not declare as a dependency or peer.
 * @param {string} source - Bundled JavaScript.
 * @param {{ dependencies?: object, peerDependencies?: object, optionalDependencies?: object }} manifest - Package manifest.
 * @returns {string[]} Undeclared specifiers.
 */
export function undeclaredImports(source, manifest) {
  const declared = new Set([
    ...Object.keys(manifest.dependencies ?? {}),
    ...Object.keys(manifest.peerDependencies ?? {}),
    ...Object.keys(manifest.optionalDependencies ?? {}),
  ])
  return bareImports(source).filter(specifier => !declared.has(packageName(specifier)))
}

/**
 * Files tool-cad must carry for one target's DWG conversion.
 * @param {'darwin' | 'win32' | 'linux'} platform - Target platform.
 * @param {'arm64' | 'x64'} arch - Target architecture.
 * @returns {string[]} Package-relative paths.
 */
export function dwg2dxfFiles(platform, arch) {
  const directory = `bin/${platform}-${arch}`
  return [`${directory}/dwg2dxf${platform === 'win32' ? '.exe' : ''}`, ...GPL_FILES.map(file => `${directory}/${file}`)]
}

function run(command, args, cwd) {
  const result = spawnSync(command, args, { cwd, stdio: 'inherit', shell: false })
  if (result.error !== undefined) throw result.error
  if (result.status !== 0) throw new Error(`pack-desktop: ${basename(command)} ${args.join(' ')} exited with ${String(result.status ?? result.signal)}`)
}

function pnpm(args, cwd) {
  const entry = process.env.npm_execpath
  // Under `pnpm exec`, npm_execpath names pnpm's JavaScript entry; a direct `node` launch uses pnpm from PATH.
  if (entry !== undefined && entry !== '' && /\.(?:c|m)?js$/u.test(entry)) run(process.execPath, [entry, ...args], cwd)
  else run(process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm', args, cwd)
}

function copyWithoutCaches(from, to) {
  rmSync(to, { recursive: true, force: true })
  cpSync(from, to, {
    recursive: true,
    filter: source => !CACHE_NAMES.has(basename(source)) && !source.endsWith('.pyc'),
  })
}

function tarballFiles(tarball) {
  return execFileSync('tar', ['-tzf', tarball], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
    .split(/\r?\n/u).filter(line => line !== '').map(line => line.replace(/^package\//u, ''))
}

function tarballText(tarball, file) {
  return execFileSync('tar', ['-xOzf', tarball, `package/${file}`], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
}

function checkTarball(tarball, options) {
  const files = new Set(tarballFiles(tarball))
  const manifest = JSON.parse(tarballText(tarball, 'package.json'))
  const problems = []
  for (const file of options.required) if (!files.has(file)) problems.push(`缺少 ${file}`)
  if (options.entry !== undefined) {
    if (manifest.exports?.['.'] !== `./${options.entry}`) problems.push(`exports["."] 不是 ./${options.entry}`)
    if (files.has(options.entry)) {
      const undeclared = undeclaredImports(tarballText(tarball, options.entry), manifest)
      if (undeclared.length > 0) problems.push(`${options.entry} 导入了未声明的包：${undeclared.join(', ')}`)
    }
  }
  for (const prefix of options.requiredPrefixes ?? []) {
    if (![...files].some(file => file.startsWith(prefix))) problems.push(`没有 ${prefix} 下的文件`)
  }
  if (problems.length > 0) throw new Error(`pack-desktop: ${basename(tarball)}：\n  - ${problems.join('\n  - ')}`)
  return manifest
}

function main() {
  const { values } = parseArgs({
    options: {
      out: { type: 'string' },
      platform: { type: 'string' },
      arch: { type: 'string' },
      'allow-missing-dwg2dxf': { type: 'boolean', default: false },
    },
    allowPositionals: false,
  })
  if (values.out === undefined || !['darwin', 'win32', 'linux'].includes(values.platform ?? '') || !['arm64', 'x64'].includes(values.arch ?? '')) {
    throw new Error('usage: node zhitong/scripts/pack-desktop.mjs --out <dir> --platform <darwin|win32|linux> --arch <arm64|x64> [--allow-missing-dwg2dxf]')
  }
  const out = resolve(REPOSITORY, values.out)
  const allowMissing = values['allow-missing-dwg2dxf'] || process.env.ZT_ALLOW_MISSING_DWG2DXF === '1'
  const converter = dwg2dxfFiles(values.platform, values.arch)
  const missingConverter = converter.filter(file => !existsSync(join(ZHITONG, 'plugins', 'tool-cad', file)))
  if (missingConverter.length > 0 && !allowMissing) {
    throw new Error(`pack-desktop: tool-cad 缺少 ${missingConverter.join('、')}。`
      + `macOS/Linux 先运行 sh zhitong/plugins/tool-cad/scripts/build-dwg2dxf.sh，Windows 先运行 zhitong/plugins/tool-cad/scripts/fetch-dwg2dxf-win64.ps1（见 zhitong/INSTALL.md）。`)
  }

  const tsdown = join(REPOSITORY, 'node_modules', 'tsdown', 'dist', 'run.mjs')
  for (const plugin of PLUGINS) run(process.execPath, [tsdown], join(ZHITONG, 'plugins', plugin))

  rmSync(out, { recursive: true, force: true })
  mkdirSync(out, { recursive: true })
  try {
    for (const { from, to } of STAGED) copyWithoutCaches(from, to)
    if (existsSync(join(BUNDLE, 'skills', 'README.md'))) throw new Error('pack-desktop: skills/ 根目录不能有 .md 文件（会被当作 skill 解析）')
    for (const directory of [BUNDLE, ...PLUGINS.map(plugin => join(ZHITONG, 'plugins', plugin))]) {
      pnpm(['pack', '--pack-destination', out], directory)
    }
  } finally {
    for (const { to } of STAGED) rmSync(to, { recursive: true, force: true })
    rmSync(join(BUNDLE, 'python'), { recursive: true, force: true })
  }

  const tarballs = readdirSync(out).filter(file => file.endsWith('.tgz'))
  const find = name => {
    const file = tarballs.find(candidate => candidate.startsWith(`${name.replace('@', '').replace('/', '-')}-`))
    if (file === undefined) throw new Error(`pack-desktop: ${out} 里没有 ${name} 的 tarball`)
    return join(out, file)
  }
  const skills = readdirSync(join(ZHITONG, 'skills'), { withFileTypes: true })
    .filter(entry => entry.isDirectory() && entry.name.startsWith('zt-')).map(entry => `skills/${entry.name}/SKILL.md`)
  checkTarball(find('@zhitong/bundle'), {
    required: ['cordis.patch.yml', 'skills-dir.cjs', 'skills/_shared/zt_launch.py', 'python/zt/__init__.py', ...skills],
  })
  checkTarball(find('@zhitong/tool-tos'), { required: ['lib/index.js'], entry: 'lib/index.js' })
  checkTarball(find('@zhitong/config-import'), { required: ['lib/index.js'], entry: 'lib/index.js' })
  checkTarball(find('@zhitong/tool-cad'), {
    required: ['lib/index.js', 'assets/fonts/kst32b.shx', 'assets/fonts/NotoSansSC-Regular-GB2312.otf',
      ...missingConverter.length > 0 ? [] : converter],
    entry: 'lib/index.js',
  })
  console.log(`pack-desktop: ${tarballs.length} tarballs in ${out.startsWith(REPOSITORY) ? relative(REPOSITORY, out) : out}（${skills.length} 个 skill${missingConverter.length > 0 ? '，未带 dwg2dxf' : ''}）`)
  if (missingConverter.length > 0) console.warn(`pack-desktop: 警告：未打包 dwg2dxf（${dirname(converter[0])}），安装后只能打开 DXF`)
}

if (import.meta.main) main()
