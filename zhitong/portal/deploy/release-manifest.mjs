#!/usr/bin/env node
/**
 * Stage built installers under their published names and check them against the portal's release manifest
 * (`zhitong/portal/site/public/downloads/releases.json`).
 *
 *   node zhitong/portal/deploy/release-manifest.mjs stage <mac-arm64|win-x64> <installer> [--date YYYY-MM-DD]
 *        [--downloads DIR] [--force]
 *   node zhitong/portal/deploy/release-manifest.mjs verify [--downloads DIR]
 *
 * `stage` copies an electron-builder artifact such as `deepseek-harness-0.2.1-rc.2-mac-arm64-unsigned.dmg` to
 * `<downloads>/ztsgai-<manifest version>-mac-arm64.dmg`, writes `<file>.sha256` in `shasum -a 256` format, and
 * records file, sha256 and size in the manifest; the version embedded in the artifact name becomes `base` (the
 * version the installed app reports). `date` is set to today in Asia/Shanghai when the manifest has none. A
 * different file already published under the same name is refused unless `--force`: browsers and the nginx cache
 * keep the old bytes for a month, so a changed installer needs a new manifest version.
 *
 * `verify` fails unless every file the manifest lists exists in the downloads directory with the recorded size and
 * sha256, and its `.sha256` file matches. deploy.sh runs it before uploading anything.
 *
 * `<downloads>` defaults to `zhitong/portal/downloads/` (ignored by git).
 */

import { createHash } from 'node:crypto'
import { copyFileSync, createReadStream, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { basename, extname, join, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import {
  parseReleaseManifest,
  RELEASE_PLATFORMS,
  releaseFileName,
} from '../site/src/data/release-manifest.mjs'

const PORTAL = resolve(import.meta.dirname, '..')
const MANIFEST = join(PORTAL, 'site', 'public', 'downloads', 'releases.json')
const DEFAULT_DOWNLOADS = join(PORTAL, 'downloads')

/** Installer extension each platform accepts. */
const EXTENSION = { 'mac-arm64': '.dmg', 'win-x64': '.exe' }

/** electron-builder artifact name (apps/desktop/scripts/electron-builder-config.mjs `artifactName`). */
const ARTIFACT = /^deepseek-harness-(?<version>.+)-(?<os>mac|win)-(?<arch>arm64|x64)(?:-unsigned|-unnotarized)?\.(?:dmg|exe)$/u

/**
 * Hash a file.
 * @param {string} path - File to read.
 * @returns {Promise<string>} Lowercase hexadecimal SHA-256.
 */
function sha256(path) {
  return new Promise((resolveHash, rejectHash) => {
    const hash = createHash('sha256')
    createReadStream(path).on('error', rejectHash).on('data', chunk => hash.update(chunk))
      .on('end', () => resolveHash(hash.digest('hex')))
  })
}

/**
 * Today's date where the release is published.
 * @returns {string} `YYYY-MM-DD` in Asia/Shanghai.
 */
function today() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(new Date())
}

/** @returns {import('../site/src/data/release-manifest.mjs').ReleaseManifest} */
function readManifest() {
  return parseReleaseManifest(JSON.parse(readFileSync(MANIFEST, 'utf8')))
}

/**
 * Write the manifest after validating it.
 * @param {object} manifest - Manifest to store.
 */
function writeManifest(manifest) {
  parseReleaseManifest(manifest)
  writeFileSync(MANIFEST, `${JSON.stringify(manifest, null, 2)}\n`)
}

/**
 * Stage one installer.
 * @param {string} platform - Platform id.
 * @param {string} installer - Path to the built installer.
 * @param {{ downloads: string, date?: string, force: boolean }} options - Destination and overrides.
 */
async function stage(platform, installer, options) {
  if (!RELEASE_PLATFORMS.includes(platform)) {
    throw new Error(`unknown platform ${platform}; expected ${RELEASE_PLATFORMS.join(' or ')}`)
  }
  const source = resolve(installer)
  if (!existsSync(source)) throw new Error(`installer not found: ${source}`)
  if (extname(source).toLowerCase() !== EXTENSION[platform]) {
    throw new Error(`${basename(source)} is not a ${EXTENSION[platform]} installer for ${platform}`)
  }
  const artifact = ARTIFACT.exec(basename(source))
  const expectedTarget = platform === 'mac-arm64' ? ['mac', 'arm64'] : ['win', 'x64']
  if (artifact !== null && (artifact.groups.os !== expectedTarget[0] || artifact.groups.arch !== expectedTarget[1])) {
    throw new Error(`${basename(source)} was built for ${artifact.groups.os}-${artifact.groups.arch}, not ${platform}`)
  }
  const manifest = readManifest()
  const file = releaseFileName(platform, manifest.version)
  const destination = join(options.downloads, file)
  const hash = await sha256(source)
  if (existsSync(destination) && (await sha256(destination)) !== hash && !options.force) {
    throw new Error(`${destination} already exists with different contents; publish a new version instead, `
      + 'or pass --force if this file was never uploaded')
  }
  mkdirSync(options.downloads, { recursive: true })
  if (destination !== source) copyFileSync(source, destination)
  writeFileSync(`${destination}.sha256`, `${hash}  ${file}\n`)
  const size = statSync(destination).size
  manifest.platforms[platform] = { ...manifest.platforms[platform], file, sha256: hash, size }
  manifest.date = options.date ?? manifest.date ?? today()
  if (artifact !== null) manifest.base = artifact.groups.version
  else console.warn(`warning: ${basename(source)} is not an electron-builder artifact name; base left at ${manifest.base}`)
  writeManifest(manifest)
  console.info(`staged ${basename(source)} -> ${destination}`)
  console.info(`  sha256 ${hash}  size ${String(size)}  version ${manifest.version}  base ${String(manifest.base)}  date ${manifest.date}`)
  console.info(`  updated ${MANIFEST}`)
}

/**
 * Check every listed installer.
 * @param {{ downloads: string }} options - Directory holding the installers.
 * @returns {Promise<boolean>} Whether everything matches.
 */
async function verify(options) {
  const manifest = readManifest()
  let ok = true
  let listed = 0
  for (const platform of RELEASE_PLATFORMS) {
    const entry = manifest.platforms[platform]
    if (entry.file === null) {
      console.info(`${platform}: not released (the portal shows 即将发布)`)
      continue
    }
    listed += 1
    const path = join(options.downloads, entry.file)
    const problems = []
    if (!existsSync(path)) problems.push('file missing')
    else {
      if (statSync(path).size !== entry.size) problems.push(`size ${String(statSync(path).size)} != ${String(entry.size)}`)
      if ((await sha256(path)) !== entry.sha256) problems.push('sha256 differs from releases.json')
      const sidecar = `${path}.sha256`
      if (!existsSync(sidecar)) problems.push('.sha256 file missing')
      else if (readFileSync(sidecar, 'utf8') !== `${entry.sha256}  ${entry.file}\n`) problems.push('.sha256 file differs')
    }
    if (problems.length > 0) ok = false
    console.info(`${platform}: ${entry.file} ${problems.length === 0 ? 'ok' : problems.join('; ')}`)
  }
  console.info(`version ${manifest.version}, date ${String(manifest.date)}, ${String(listed)} installer(s) listed`)
  return ok
}

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    downloads: { type: 'string', default: DEFAULT_DOWNLOADS },
    date: { type: 'string' },
    force: { type: 'boolean', default: false },
  },
})
const [command, ...rest] = positionals
const downloads = resolve(values.downloads)
try {
  if (command === 'stage' && rest.length === 2) {
    await stage(rest[0], rest[1], { downloads, date: values.date, force: values.force })
  } else if (command === 'verify' && rest.length === 0) {
    if (!(await verify({ downloads }))) process.exit(1)
  } else {
    console.error('usage: release-manifest.mjs stage <mac-arm64|win-x64> <installer> [--date YYYY-MM-DD] [--downloads DIR] [--force]')
    console.error('       release-manifest.mjs verify [--downloads DIR]')
    process.exit(2)
  }
} catch (error) {
  console.error(`release-manifest: ${error instanceof Error ? error.message : String(error)}`)
  process.exit(1)
}
