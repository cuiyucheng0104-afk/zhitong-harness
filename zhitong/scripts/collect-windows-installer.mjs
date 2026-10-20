#!/usr/bin/env node
/**
 * Name the unsigned Windows installer for distribution after `pnpm run package:desktop:win:x64:unsigned`.
 *
 *   node zhitong/scripts/collect-windows-installer.mjs --version <x.y.z> --out <dir> [--artifacts <dir>]
 *
 * `--artifacts` defaults to `apps/desktop/.desktop-build/targets/win-x64/unsigned-artifacts`. It must hold exactly
 * one installer `.exe` at its top level (electron-builder's `__uninstaller-*` helpers are ignored) and the
 * `win-unpacked/resources/app.asar.unpacked` tree. The installer is copied to `<out>/ztsgai-<version>-win-x64-setup.exe`
 * and `<out>/ztsgai-<version>-win-x64-setup.exe.sha256` is written in `shasum -a 256` format (`<hex>  <file>\n`), the
 * names and format `zhitong/portal/deploy/release-manifest.mjs` publishes. `<version>` is the distribution version; the
 * installed application keeps reporting the product version from `apps/desktop/package.json` (printed as `base`).
 *
 * Prints `installer`, `sha256`, `hash`, `unpacked`, `source` and `base` as `key=value` lines and appends them to
 * `$GITHUB_OUTPUT` when that variable is set. Exits 1 with a message on any mismatch.
 */

import { createHash } from 'node:crypto'
import { appendFileSync, copyFileSync, createReadStream, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { parseArgs } from 'node:util'

const REPOSITORY = resolve(import.meta.dirname, '..', '..')
const DEFAULT_ARTIFACTS = join(REPOSITORY, 'apps', 'desktop', '.desktop-build', 'targets', 'win-x64', 'unsigned-artifacts')
/** Distribution version: `x.y.z` with an optional prerelease such as `1.0.1-rc.1`; no build metadata. */
const VERSION = /^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/u

/**
 * Published installer name for one distribution version.
 * @param {string} version - Distribution version without a leading `v`.
 * @returns {string} `ztsgai-<version>-win-x64-setup.exe`.
 */
export function installerFileName(version) {
  if (!VERSION.test(version)) throw new Error(`collect-windows-installer: version ${JSON.stringify(version)} must look like 1.0.0 or 1.0.1-rc.1`)
  return `ztsgai-${version}-win-x64-setup.exe`
}

/**
 * Find the installer and the unpacked application electron-builder wrote.
 * @param {string} artifacts - electron-builder output directory.
 * @returns {{ installer: string, unpacked: string }} Absolute paths.
 */
export function locateWindowsArtifacts(artifacts) {
  if (!existsSync(artifacts)) throw new Error(`collect-windows-installer: ${artifacts} does not exist; packaging did not finish`)
  const installers = readdirSync(artifacts, { withFileTypes: true })
    .filter(entry => entry.isFile() && entry.name.toLowerCase().endsWith('.exe') && !entry.name.startsWith('__'))
    .map(entry => entry.name)
  if (installers.length !== 1) {
    throw new Error(`collect-windows-installer: expected one installer .exe in ${artifacts}, found ${installers.length}: ${installers.join(', ')}`)
  }
  const unpacked = join(artifacts, 'win-unpacked')
  if (!existsSync(join(unpacked, 'resources', 'app.asar.unpacked'))) {
    throw new Error(`collect-windows-installer: ${unpacked} has no resources/app.asar.unpacked`)
  }
  return { installer: join(artifacts, installers[0]), unpacked }
}

/**
 * Hash a file.
 * @param {string} path - File to read.
 * @returns {Promise<string>} Lowercase hexadecimal SHA-256.
 */
export function sha256File(path) {
  return new Promise((resolvePromise, reject) => {
    const hash = createHash('sha256')
    createReadStream(path).on('error', reject).on('data', chunk => hash.update(chunk)).on('end', () => resolvePromise(hash.digest('hex')))
  })
}

/**
 * Copy the installer under its published name and write its checksum file.
 * @param {{ version: string, artifacts: string, out: string }} options - Distribution version and directories.
 * @returns {Promise<{ installer: string, sha256: string, hash: string, unpacked: string, source: string }>} Written paths and hash.
 */
export async function collectWindowsInstaller({ version, artifacts, out }) {
  const file = installerFileName(version)
  const located = locateWindowsArtifacts(resolve(artifacts))
  mkdirSync(out, { recursive: true })
  const installer = join(resolve(out), file)
  copyFileSync(located.installer, installer)
  const hash = await sha256File(installer)
  const sha256 = `${installer}.sha256`
  writeFileSync(sha256, `${hash}  ${file}\n`)
  return { installer, sha256, hash, unpacked: located.unpacked, source: basename(located.installer) }
}

async function main() {
  const { values } = parseArgs({
    options: { version: { type: 'string' }, out: { type: 'string' }, artifacts: { type: 'string' } },
  })
  if (values.version === undefined || values.out === undefined) {
    throw new Error('usage: node zhitong/scripts/collect-windows-installer.mjs --version <x.y.z> --out <dir> [--artifacts <dir>]')
  }
  const result = await collectWindowsInstaller({ version: values.version.replace(/^v/u, ''), artifacts: values.artifacts ?? DEFAULT_ARTIFACTS, out: values.out })
  const base = JSON.parse(readFileSync(join(REPOSITORY, 'apps', 'desktop', 'package.json'), 'utf8')).version
  const lines = Object.entries({ ...result, base }).map(([key, value]) => `${key}=${value}`)
  console.log(lines.join('\n'))
  if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, `${lines.join('\n')}\n`)
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === import.meta.filename) {
  try {
    await main()
  }
  catch (error) {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
  }
}
