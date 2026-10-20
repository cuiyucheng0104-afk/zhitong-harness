#!/usr/bin/env node
/**
 * Release bookkeeping for `zhitong/scripts/release.sh`: version checks, the manifest version bump, staged-installer
 * detection, and picking the Windows packaging run out of `gh` JSON. The manifest is
 * `zhitong/portal/site/public/downloads/releases.json`; installers are staged by `zhitong/portal/deploy/release-manifest.mjs`.
 *
 *   node zhitong/scripts/release-state.mjs check-version <version>
 *   node zhitong/scripts/release-state.mjs prepare --version <v> [--notes-file <file>]
 *   node zhitong/scripts/release-state.mjs staged <mac-arm64|win-x64> --version <v>
 *   node zhitong/scripts/release-state.mjs pick-run --version <v> [--sha <commit>] [--since <ISO time>]   < gh run list --json …
 *   node zhitong/scripts/release-state.mjs run-status                                                    < gh run view --json status,conclusion,jobs
 *   node zhitong/scripts/release-state.mjs verify-sidecar <installer>
 *   node zhitong/scripts/release-state.mjs summary --version <v> [--site-url <url>]
 *
 * Every command accepts `--manifest <file>` and `--downloads <dir>` (defaults: the repository manifest and
 * `zhitong/portal/downloads/`). Exit status 1 means "no" for `staged`, "not found" for `pick-run`, and a failed check
 * elsewhere; 2 is a usage error.
 */

import { createHash } from 'node:crypto'
import { createReadStream, existsSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { parseArgs } from 'node:util'
import { parseReleaseManifest, RELEASE_PLATFORMS } from '../portal/site/src/data/release-manifest.mjs'

const ZHITONG = resolve(import.meta.dirname, '..')
const DEFAULT_MANIFEST = join(ZHITONG, 'portal', 'site', 'public', 'downloads', 'releases.json')
const DEFAULT_DOWNLOADS = join(ZHITONG, 'portal', 'downloads')
const VERSION = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/u
/** Clock difference tolerated between this machine and GitHub when matching a run to the moment it was triggered. */
const CLOCK_SKEW_MS = 10 * 60 * 1000

/**
 * Compare two distribution versions by semantic-version precedence.
 * @param {string} a - Version without a leading `v`.
 * @param {string} b - Version without a leading `v`.
 * @returns {number} Negative when `a` precedes `b`, zero when equal, positive otherwise.
 * @throws {Error} When either version is malformed.
 */
export function compareVersions(a, b) {
  const pa = VERSION.exec(a)
  const pb = VERSION.exec(b)
  if (pa === null || pb === null) throw new Error(`cannot compare versions ${JSON.stringify(a)} and ${JSON.stringify(b)}`)
  for (let i = 1; i <= 3; i += 1) {
    const diff = Number(pa[i]) - Number(pb[i])
    if (diff !== 0) return diff
  }
  if (pa[4] === undefined || pb[4] === undefined) return (pa[4] === undefined ? 1 : 0) - (pb[4] === undefined ? 1 : 0)
  const ia = pa[4].split('.')
  const ib = pb[4].split('.')
  for (let i = 0; i < Math.min(ia.length, ib.length); i += 1) {
    const na = /^\d+$/u.test(ia[i])
    const nb = /^\d+$/u.test(ib[i])
    if (na && nb && Number(ia[i]) !== Number(ib[i])) return Number(ia[i]) - Number(ib[i])
    if (na !== nb) return na ? -1 : 1
    if (ia[i] !== ib[i]) return ia[i] < ib[i] ? -1 : 1
  }
  return ia.length - ib.length
}

/**
 * Move the manifest to a release version. A different version clears every platform's file, checksum and size and the
 * date (staging fills them again) and keeps the platform notes; the same version is left alone. `notes`, when given,
 * replaces the release notes; otherwise the previous release's notes carry over.
 * @param {Record<string, any>} manifest - Raw parsed `releases.json`.
 * @param {string} version - Release version without a leading `v`.
 * @param {string[] | undefined} notes - Replacement release notes.
 * @returns {{ manifest: Record<string, any>, changed: boolean, bumpedFrom: string | null }} Updated manifest copy.
 */
export function prepareManifest(manifest, version, notes) {
  parseReleaseManifest(manifest)
  const next = structuredClone(manifest)
  let bumpedFrom = null
  if (next.version !== version) {
    bumpedFrom = next.version
    next.version = version
    next.date = null
    for (const platform of RELEASE_PLATFORMS) {
      next.platforms[platform] = { ...next.platforms[platform], file: null, sha256: null, size: null }
    }
  }
  if (notes !== undefined) next.notes = notes
  parseReleaseManifest(next)
  return { manifest: next, changed: JSON.stringify(next) !== JSON.stringify(manifest), bumpedFrom }
}

/**
 * Read release notes: one note per non-empty line.
 * @param {string} path - Notes file.
 * @returns {string[]} Trimmed notes.
 * @throws {Error} When the file holds no note.
 */
export function readNotes(path) {
  const notes = readFileSync(path, 'utf8').split(/\r?\n/u).map(line => line.trim()).filter(line => line !== '')
  if (notes.length === 0) throw new Error(`${path} has no notes; write one note per line`)
  return notes
}

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
 * Whether one platform's installer is staged for a version: the manifest carries the version and lists the file, and
 * the downloads directory holds it with the recorded size, hash and `.sha256` file.
 * @param {Record<string, any>} manifest - Raw parsed `releases.json`.
 * @param {string} platform - Platform id.
 * @param {string} version - Release version.
 * @param {string} downloads - Downloads directory.
 * @returns {Promise<{ staged: boolean, reason: string }>} Verdict and why.
 */
export async function stagedStatus(manifest, platform, version, downloads) {
  const parsed = parseReleaseManifest(manifest)
  if (parsed.version !== version) return { staged: false, reason: `releases.json is at ${parsed.version}, not ${version}` }
  const entry = parsed.platforms[platform]
  if (entry === undefined) throw new Error(`unknown platform ${platform}`)
  if (entry.file === null) return { staged: false, reason: `${platform} has no file in releases.json` }
  const path = join(downloads, entry.file)
  if (!existsSync(path)) return { staged: false, reason: `${path} is missing` }
  if (statSync(path).size !== entry.size) return { staged: false, reason: `${path} size differs from releases.json` }
  if ((await sha256(path)) !== entry.sha256) return { staged: false, reason: `${path} sha256 differs from releases.json` }
  const sidecar = `${path}.sha256`
  if (!existsSync(sidecar) || readFileSync(sidecar, 'utf8') !== `${entry.sha256}  ${entry.file}\n`) {
    return { staged: false, reason: `${sidecar} is missing or differs` }
  }
  return { staged: true, reason: `${entry.file} sha256 ${entry.sha256}` }
}

/**
 * Pick the Windows packaging run for a version from `gh run list --json databaseId,headSha,createdAt,displayTitle,event,headBranch`.
 * A run matches when it was pushed for tag `v<version>` or its title (the workflow's `run-name`) ends in ` v<version>`;
 * `sha` and `since` narrow the match to the commit and the moment the release script triggered it.
 * @param {Array<Record<string, any>>} runs - Runs as `gh` prints them.
 * @param {{ version: string, sha?: string, since?: string }} filter - Version, commit and trigger time.
 * @returns {number | null} The newest matching run id.
 */
export function pickRun(runs, { version, sha, since }) {
  const tag = `v${version}`
  const earliest = since === undefined ? -Infinity : Date.parse(since) - CLOCK_SKEW_MS
  const matches = runs.filter(run => ((run.event === 'push' && run.headBranch === tag)
    || (typeof run.displayTitle === 'string' && run.displayTitle.endsWith(` ${tag}`)))
    && (sha === undefined || run.headSha === sha)
    && Date.parse(run.createdAt) >= earliest)
  matches.sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
  return matches.length === 0 ? null : matches[0].databaseId
}

/**
 * Summarize `gh run view --json status,conclusion,jobs` for a progress line.
 * @param {Record<string, any>} view - Parsed `gh` output.
 * @returns {{ status: string, conclusion: string, current: string }} Fields, `-` when empty.
 */
export function runStatus(view) {
  const jobs = Array.isArray(view.jobs) ? view.jobs : []
  const running = jobs.find(job => job.status === 'in_progress')
  const step = running?.steps?.find(s => s.status === 'in_progress')
  const current = running === undefined
    ? (jobs.find(job => job.status === 'queued')?.name ?? '')
    : `${running.name}${step === undefined ? '' : ` / ${step.name}`}`
  return { status: view.status || '-', conclusion: view.conclusion || '-', current: current || '-' }
}

/**
 * Check an installer against its `<file>.sha256` (`<hex>  <file>` format).
 * @param {string} installer - Installer path.
 * @returns {Promise<string>} The verified hash.
 * @throws {Error} When the checksum file is missing, malformed or differs.
 */
export async function verifySidecar(installer) {
  const sidecar = `${installer}.sha256`
  if (!existsSync(installer)) throw new Error(`${installer} not found`)
  if (!existsSync(sidecar)) throw new Error(`${sidecar} not found`)
  const match = /^([0-9a-f]{64}) {2}(\S+)\n?$/u.exec(readFileSync(sidecar, 'utf8'))
  if (match === null || match[2] !== basename(installer)) throw new Error(`${sidecar} is not "<sha256>  ${basename(installer)}"`)
  const hash = await sha256(installer)
  if (hash !== match[1]) throw new Error(`${installer} sha256 ${hash} differs from ${sidecar} (${match[1]})`)
  return hash
}

/**
 * Read stdin to the end.
 * @returns {Promise<string>} Text.
 */
async function stdin() {
  let text = ''
  for await (const chunk of process.stdin) text += chunk
  return text
}

async function main() {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      'version': { type: 'string' },
      'notes-file': { type: 'string' },
      'sha': { type: 'string' },
      'since': { type: 'string' },
      'site-url': { type: 'string', default: 'https://ztsgai.com' },
      'manifest': { type: 'string', default: DEFAULT_MANIFEST },
      'downloads': { type: 'string', default: DEFAULT_DOWNLOADS },
    },
  })
  const [command, ...rest] = positionals
  const manifestPath = resolve(values.manifest)
  const downloads = resolve(values.downloads)
  const readManifest = () => JSON.parse(readFileSync(manifestPath, 'utf8'))
  const version = values.version ?? (command === 'check-version' ? rest[0] : undefined)
  if (['check-version', 'prepare', 'staged', 'pick-run', 'summary'].includes(command)
    && (version === undefined || !VERSION.test(version))) {
    throw Object.assign(new Error(`${command}: --version must look like 1.0.1, got ${String(version)}`), { usage: true })
  }

  switch (command) {
    case 'check-version': {
      const current = parseReleaseManifest(readManifest()).version
      if (compareVersions(version, current) < 0) {
        throw new Error(`v${version} is older than v${current} in releases.json; release a newer version`)
      }
      console.info(`releases.json is at v${current}; releasing v${version}`)
      return 0
    }
    case 'prepare': {
      const notes = values['notes-file'] === undefined ? undefined : readNotes(values['notes-file'])
      const result = prepareManifest(readManifest(), version, notes)
      if (result.changed) writeFileSync(manifestPath, `${JSON.stringify(result.manifest, null, 2)}\n`)
      if (result.bumpedFrom !== null) {
        console.info(`releases.json: v${result.bumpedFrom} -> v${version}; platform files cleared for staging`)
        if (notes === undefined) console.warn(`warning: release notes carried over from v${result.bumpedFrom}; pass --notes-file to replace them`)
      }
      else console.info(`releases.json is already at v${version}${notes === undefined ? '' : '; notes replaced'}`)
      return 0
    }
    case 'staged': {
      if (rest.length !== 1) break
      const result = await stagedStatus(readManifest(), rest[0], version, downloads)
      console.info(`${rest[0]}: ${result.staged ? 'staged' : 'not staged'} (${result.reason})`)
      return result.staged ? 0 : 1
    }
    case 'pick-run': {
      const runs = JSON.parse(await stdin())
      if (!Array.isArray(runs)) throw new Error('pick-run: stdin must be the JSON array gh run list prints')
      const id = pickRun(runs, { version, sha: values.sha, since: values.since })
      if (id === null) return 1
      console.info(String(id))
      return 0
    }
    case 'run-status': {
      const { status, conclusion, current } = runStatus(JSON.parse(await stdin()))
      console.info([status, conclusion, current].join('\t'))
      return 0
    }
    case 'verify-sidecar': {
      if (rest.length !== 1) break
      console.info(`sha256 ok ${await verifySidecar(resolve(rest[0]))}`)
      return 0
    }
    case 'summary': {
      const manifest = parseReleaseManifest(readManifest())
      if (manifest.version !== version) {
        console.info(`releases.json is at v${manifest.version}, not v${version}`)
        return 0
      }
      const site = values['site-url'].replace(/\/+$/u, '')
      console.info(`版本 v${manifest.version}（应用内版本 ${String(manifest.base)}，日期 ${String(manifest.date)}）`)
      for (const platform of RELEASE_PLATFORMS) {
        const entry = manifest.platforms[platform]
        if (entry.file === null) {
          console.info(`  ${platform}: 未发布（页面显示「即将发布」）`)
          continue
        }
        console.info(`  ${platform}: ${entry.file}`)
        console.info(`    sha256 ${entry.sha256}  ${String(entry.size)} 字节`)
        console.info(`    ${site}/downloads/${entry.file}`)
      }
      console.info(`网站：${site}/`)
      return 0
    }
  }
  console.error('usage: release-state.mjs check-version <v> | prepare --version <v> [--notes-file F] | staged <platform> --version <v>')
  console.error('       | pick-run --version <v> [--sha S] [--since ISO] | run-status | verify-sidecar <file> | summary --version <v>')
  return 2
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === import.meta.filename) {
  try {
    process.exitCode = await main()
  }
  catch (error) {
    console.error(`release-state: ${error instanceof Error ? error.message : String(error)}`)
    process.exitCode = error?.usage === true ? 2 : 1
  }
}
