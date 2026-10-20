// node --test zhitong/scripts/tests/：发布脚本 zhitong/scripts/release.sh、release-lib.sh、release-state.mjs。
// 端到端用例在临时 git 仓库里跑，PATH 前面放假 gh / pnpm / node / git / ssh / uname，不联网、不打真包。
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { chmodSync, copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { after, describe, it } from 'node:test'
import { compareVersions, pickRun, prepareManifest, runStatus, stagedStatus, verifySidecar } from '../release-state.mjs'

const REPO = resolve(import.meta.dirname, '..', '..', '..')
const LIB = join(REPO, 'zhitong', 'scripts', 'release-lib.sh')
const MANIFEST = join(REPO, 'zhitong', 'portal', 'site', 'public', 'downloads', 'releases.json')
const REAL_GIT = spawnSync('sh', ['-c', 'command -v git'], { encoding: 'utf8' }).stdout.trim()
const roots = []
after(() => { for (const root of roots) rmSync(root, { recursive: true, force: true }) })
function tempRoot(prefix) {
  const root = mkdtempSync(join(tmpdir(), prefix))
  roots.push(root)
  return root
}
const sha = text => createHash('sha256').update(text).digest('hex')
const baseManifest = () => JSON.parse(readFileSync(MANIFEST, 'utf8'))

/** Run a bash snippet with release-lib.sh sourced. */
function lib(script) {
  return spawnSync('bash', ['-c', `set -u; . ${JSON.stringify(LIB)}; ${script}`], { encoding: 'utf8' })
}
/** Parse arguments with rl_parse_args and return the resulting variables. */
function parse(args) {
  const quoted = args.map(a => `'${a.replaceAll("'", "'\\''")}'`).join(' ')
  const result = lib(`rl_parse_args ${quoted}; rc=$?; printf '%s\\n' "rc=$rc" "version=$REL_VERSION" "ssh=$REL_SSH" `
    + `"skip=$REL_SKIP_MAC$REL_SKIP_WIN$REL_SKIP_DEPLOY" "notag=$REL_NO_TAG" "dry=$REL_DRY_RUN" "from=$REL_FROM" `
    + `"run=$REL_RUN_ID" "notes=$REL_NOTES_FILE" "exe=$REL_WIN_EXE" "timeout=$REL_WIN_TIMEOUT" "keep=$REL_KEEP_ARGS"`)
  const vars = Object.fromEntries(result.stdout.trim().split('\n').map(line => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1)]))
  return { ...vars, stderr: result.stderr }
}

describe('release-lib.sh', () => {
  it('normalizes distribution versions and rejects malformed ones', () => {
    for (const [input, output] of [['1.0.1', '1.0.1'], ['v1.0.1', '1.0.1'], ['1.0.1-rc.1', '1.0.1-rc.1'], ['10.20.30', '10.20.30']]) {
      const result = lib(`rl_normalize_version ${input}`)
      assert.equal(result.status, 0, input)
      assert.equal(result.stdout, `${output}\n`)
    }
    for (const bad of ['', '1.0', '01.0.0', '1.0.0+build.1', 'vv1.0.0', 'V1.0.0', '1.0.0-', '1.0.0/../x', '1.0.0 ']) {
      assert.equal(lib(`rl_normalize_version '${bad}'`).status, 1, JSON.stringify(bad))
    }
  })

  it('parses defaults', () => {
    const vars = parse(['v1.0.1'])
    assert.equal(vars.rc, '0')
    assert.deepEqual([vars.version, vars.ssh, vars.skip, vars.notag, vars.dry, vars.from, vars.run, vars.timeout, vars.keep],
      ['1.0.1', 'zt-prod', '000', '0', '0', 'trigger', '', '120', ''])
  })

  it('parses every option and keeps resumable ones for the resume hint', () => {
    const vars = parse(['--ssh', 'zt-stage', '1.0.2-rc.1', '--skip-deploy', '--no-tag', '--dry-run', '--from', 'win',
      '--run-id', '987', '--notes-file', '/tmp/notes 1.txt', '--win-timeout', '90'])
    assert.equal(vars.rc, '0', vars.stderr)
    assert.deepEqual([vars.version, vars.ssh, vars.skip, vars.notag, vars.dry, vars.from, vars.run, vars.notes, vars.timeout],
      ['1.0.2-rc.1', 'zt-stage', '001', '1', '1', 'win', '987', '/tmp/notes 1.txt', '90'])
    assert.equal(vars.keep, " --ssh zt-stage --skip-deploy --no-tag --notes-file '/tmp/notes 1.txt' --win-timeout 90")
  })

  it('rejects bad arguments with exit status 2 and a reason', () => {
    for (const [args, message] of [
      [[], /缺少版本号/u],
      [['1.0'], /版本号 1.0 不合法/u],
      [['1.0.1', '1.0.2'], /只能给一个版本号/u],
      [['1.0.1', '--bogus'], /未知选项 --bogus/u],
      [['1.0.1', '--from', 'build'], /--from 只能是/u],
      [['1.0.1', '--from'], /--from 需要一个值/u],
      [['1.0.1', '--ssh', '--skip-mac'], /--ssh 需要一个值/u],
      [['1.0.1', '--run-id', 'abc'], /--run-id 应为数字/u],
      [['1.0.1', '--win-timeout', '0'], /--win-timeout 应为正整数/u],
      [['1.0.1', '--skip-mac', '--skip-win'], /没有安装包可发/u],
      [['1.0.1', '--skip-win', '--no-tag'], /--skip-win 不能与/u],
      [['1.0.1', '--win-exe', 'a.exe', '--run-id', '1'], /--win-exe 不经过 Actions/u],
    ]) {
      const vars = parse(args)
      assert.equal(vars.rc, '2', args.join(' '))
      assert.match(vars.stderr, message, args.join(' '))
    }
  })

  it('selects steps from --from and the skip options', () => {
    const steps = args => lib(`rl_parse_args ${args}; for s in $RL_STEPS; do rl_should_run $s && printf '%s ' $s; done; true`).stdout.trim()
    assert.equal(steps('1.0.1'), 'trigger mac win stage deploy')
    assert.equal(steps('1.0.1 --from mac'), 'mac win stage deploy')
    assert.equal(steps('1.0.1 --from stage'), 'stage deploy')
    assert.equal(steps('1.0.1 --from deploy'), 'deploy')
    assert.equal(steps('1.0.1 --skip-mac --skip-deploy'), 'trigger win stage')
    assert.equal(steps('1.0.1 --skip-win'), 'mac stage deploy')
    assert.equal(steps('1.0.1 --win-exe x.exe'), 'mac win stage deploy')
  })

  it('reads the last DMG line of the packaging log', () => {
    const root = tempRoot('zt-release-log-')
    const log = join(root, 'build.log')
    writeFileSync(log, 'DESKTOP_PACKAGING_RECORD /x\nDMG: /old/a.dmg\nnoise DMG: mentioned\r\n'
      + 'apps/desktop package:mac: DMG: /Users/me/zhitong harness/b-mac-arm64-unsigned.dmg\r\ndone\n')
    const result = lib(`rl_dmg_from_log ${JSON.stringify(log)}`)
    assert.equal(result.stdout, '/Users/me/zhitong harness/b-mac-arm64-unsigned.dmg\n')
    writeFileSync(log, 'build failed\n')
    assert.equal(lib(`rl_dmg_from_log ${JSON.stringify(log)}`).status, 1)
  })

  it('prints copyable commands and resume hints', () => {
    assert.equal(lib(`rl_quote git commit -m 'release(zhitong): v1.0.1' "it's" ''`).stdout,
      `git commit -m 'release(zhitong): v1.0.1' 'it'\\''s' ''\n`)
    assert.equal(lib('rl_parse_args 1.0.1 --ssh zt-b --skip-deploy --from mac; rl_resume_cmd win 42').stdout,
      'bash zhitong/scripts/release.sh 1.0.1 --ssh zt-b --skip-deploy --from win --run-id 42\n')
  })
})

describe('release-state.mjs', () => {
  it('orders versions by semantic-version precedence', () => {
    const ordered = ['0.9.9', '1.0.0-alpha', '1.0.0-alpha.1', '1.0.0-alpha.beta', '1.0.0-beta.2', '1.0.0-beta.11', '1.0.0-rc.1', '1.0.0', '1.0.1', '1.0.10', '1.1.0']
    for (let i = 0; i < ordered.length - 1; i += 1) {
      assert.ok(compareVersions(ordered[i], ordered[i + 1]) < 0, `${ordered[i]} < ${ordered[i + 1]}`)
      assert.ok(compareVersions(ordered[i + 1], ordered[i]) > 0, `${ordered[i + 1]} > ${ordered[i]}`)
    }
    assert.equal(compareVersions('1.0.0', '1.0.0'), 0)
    assert.throws(() => compareVersions('1.0', '1.0.0'), /cannot compare/u)
  })

  it('bumps the manifest to a new version, clearing staged files and keeping platform notes', () => {
    const staged = baseManifest()
    staged.date = '2026-10-21'
    staged.platforms['mac-arm64'] = { ...staged.platforms['mac-arm64'], file: 'ztsgai-1.0.0-mac-arm64.dmg', sha256: 'a'.repeat(64), size: 10 }
    const bumped = prepareManifest(staged, '1.0.1', undefined)
    assert.equal(bumped.bumpedFrom, '1.0.0')
    assert.equal(bumped.manifest.version, '1.0.1')
    assert.equal(bumped.manifest.date, null)
    assert.equal(bumped.manifest.base, staged.base)
    assert.deepEqual(bumped.manifest.notes, staged.notes)
    assert.deepEqual(bumped.manifest.platforms['mac-arm64'], { file: null, sha256: null, size: null, notes: staged.platforms['mac-arm64'].notes })
    assert.equal(staged.platforms['mac-arm64'].file, 'ztsgai-1.0.0-mac-arm64.dmg', 'input is not mutated')

    const same = prepareManifest(staged, '1.0.0', undefined)
    assert.equal(same.changed, false)
    assert.equal(same.bumpedFrom, null)
    const noted = prepareManifest(staged, '1.0.0', ['修复导入'])
    assert.equal(noted.changed, true)
    assert.deepEqual(noted.manifest.notes, ['修复导入'])
    assert.equal(noted.manifest.platforms['mac-arm64'].file, 'ztsgai-1.0.0-mac-arm64.dmg')
  })

  it('picks the newest Windows run for the version, commit and trigger time', () => {
    const runs = [
      { databaseId: 1, headSha: 'aaa', createdAt: '2026-10-20T08:00:00Z', displayTitle: 'zhitong · Windows installer', event: 'push', headBranch: 'v1.0.1' },
      { databaseId: 2, headSha: 'bbb', createdAt: '2026-10-20T09:00:00Z', displayTitle: 'zhitong · Windows installer v1.0.1', event: 'workflow_dispatch', headBranch: 'master' },
      { databaseId: 3, headSha: 'bbb', createdAt: '2026-10-20T09:30:00Z', displayTitle: 'zhitong · Windows installer v1.0.10', event: 'workflow_dispatch', headBranch: 'master' },
      { databaseId: 4, headSha: 'ccc', createdAt: '2026-10-20T07:00:00Z', displayTitle: 'CI', event: 'push', headBranch: 'master' },
    ]
    assert.equal(pickRun(runs, { version: '1.0.1' }), 2)
    assert.equal(pickRun(runs, { version: '1.0.1', sha: 'aaa' }), 1)
    assert.equal(pickRun(runs, { version: '1.0.1', sha: 'bbb', since: '2026-10-20T09:05:00Z' }), 2, 'tolerates clock skew')
    assert.equal(pickRun(runs, { version: '1.0.1', since: '2026-10-20T10:00:00Z' }), null)
    assert.equal(pickRun(runs, { version: '1.0.10' }), 3)
    assert.equal(pickRun(runs, { version: '1.0.2' }), null)
  })

  it('summarizes run progress with placeholders for empty fields', () => {
    assert.deepEqual(runStatus({ status: 'in_progress', conclusion: '', jobs: [
      { name: 'Package Windows x64 installer', status: 'in_progress', steps: [{ name: 'Install locked dependencies', status: 'completed' }, { name: 'Build unsigned installer', status: 'in_progress' }] },
      { name: 'Publish GitHub Release', status: 'queued' },
    ] }), { status: 'in_progress', conclusion: '-', current: 'Package Windows x64 installer / Build unsigned installer' })
    assert.deepEqual(runStatus({ status: 'queued', conclusion: null, jobs: [{ name: 'Package Windows x64 installer', status: 'queued' }] }),
      { status: 'queued', conclusion: '-', current: 'Package Windows x64 installer' })
    assert.deepEqual(runStatus({ status: 'completed', conclusion: 'failure' }), { status: 'completed', conclusion: 'failure', current: '-' })
  })

  it('treats an installer as staged only when manifest, file and checksum file agree', async () => {
    const downloads = tempRoot('zt-release-staged-')
    const file = 'ztsgai-1.0.1-win-x64-setup.exe'
    const body = 'windows bytes'
    const manifest = prepareManifest(baseManifest(), '1.0.1', undefined).manifest
    manifest.platforms['win-x64'] = { ...manifest.platforms['win-x64'], file, sha256: sha(body), size: body.length }
    assert.match((await stagedStatus(manifest, 'win-x64', '1.0.1', downloads)).reason, /missing/u)
    writeFileSync(join(downloads, file), body)
    assert.match((await stagedStatus(manifest, 'win-x64', '1.0.1', downloads)).reason, /\.sha256 is missing/u)
    writeFileSync(join(downloads, `${file}.sha256`), `${sha(body)}  ${file}\n`)
    assert.deepEqual(await stagedStatus(manifest, 'win-x64', '1.0.1', downloads), { staged: true, reason: `${file} sha256 ${sha(body)}` })
    assert.equal((await stagedStatus(manifest, 'win-x64', '1.0.2', downloads)).staged, false)
    assert.equal((await stagedStatus(manifest, 'mac-arm64', '1.0.1', downloads)).staged, false)
    assert.equal(await verifySidecar(join(downloads, file)), sha(body))
    writeFileSync(join(downloads, file), 'tampered')
    assert.equal((await stagedStatus(manifest, 'win-x64', '1.0.1', downloads)).staged, false)
    await assert.rejects(verifySidecar(join(downloads, file)), /differs/u)
  })
})

// ── 端到端：临时仓库 + 假工具 ───────────────────────────────────────────

const FAKE_GH = String.raw`#!/usr/bin/env bash
printf 'gh %s\n' "$*" >>"$FAKE_LOG"
case "$1 $2" in
  'auth status') ;;
  'workflow run') ;;
  'run list')
    sha="$(git rev-parse -q --verify "refs/tags/v$FAKE_VERSION^{commit}" || git rev-parse HEAD)"
    now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '[{"databaseId":111,"headSha":"0000","status":"completed","createdAt":"2020-01-01T00:00:00Z","displayTitle":"zhitong · Windows installer v0.9.0","event":"push","headBranch":"v0.9.0"},'
    printf '{"databaseId":4242,"headSha":"%s","status":"queued","createdAt":"%s","displayTitle":"zhitong · Windows installer v%s","event":"push","headBranch":"v%s"}]\n' "$sha" "$now" "$FAKE_VERSION" "$FAKE_VERSION"
    ;;
  'run view')
    n=$(( $(cat "$FAKE_DIR/views" 2>/dev/null || echo 0) + 1 )); echo "$n" >"$FAKE_DIR/views"
    if [ "$n" -lt 2 ]; then
      echo '{"status":"in_progress","conclusion":"","jobs":[{"name":"Package Windows x64 installer","status":"in_progress","steps":[{"name":"Build unsigned installer","status":"in_progress"}]}]}'
    else
      printf '{"status":"completed","conclusion":"%s","jobs":[]}\n' "$(cat "$FAKE_DIR/conclusion" 2>/dev/null || echo success)"
    fi
    ;;
  'run download')
    while [ $# -gt 0 ]; do [ "$1" = -D ] && dir="$2"; shift; done
    file="ztsgai-$FAKE_VERSION-win-x64-setup.exe"
    printf 'fake windows installer %s\n' "$FAKE_VERSION" >"$dir/$file"
    hash="$("$REAL_NODE" -e 'const c=require("node:crypto"),f=require("node:fs");console.log(c.createHash("sha256").update(f.readFileSync(process.argv[1])).digest("hex"))' "$dir/$file")"
    printf '%s  %s\n' "$hash" "$file" >"$dir/$file.sha256"
    ;;
  'release view')
    case "$*" in *url*) echo "https://github.com/example/zhitong-harness/releases/tag/$3" ;; *) exit 1 ;; esac
    ;;
  *) echo "fake gh: unexpected $*" >&2; exit 1 ;;
esac
`
const FAKE_PNPM = String.raw`#!/usr/bin/env bash
printf 'pnpm %s\n' "$*" >>"$FAKE_LOG"
case "$*" in
  'install --frozen-lockfile') echo 'Lockfile is up to date' ;;
  'run package:desktop:mac:arm64:unsigned --check') echo 'check ok' ;;
  'run package:desktop:mac:arm64:unsigned')
    out="$PWD/apps/desktop/.desktop-build/targets/mac-arm64/unsigned-artifacts"
    mkdir -p "$out"
    printf 'fake dmg\n' >"$out/deepseek-harness-0.2.1-rc.2-mac-arm64-unsigned.dmg"
    echo "DESKTOP_PACKAGING_RECORD $PWD/apps/desktop/.desktop-build/packaging-runs/x"
    echo "DMG: $out/deepseek-harness-0.2.1-rc.2-mac-arm64-unsigned.dmg"
    ;;
  *) echo "fake pnpm: unexpected $*" >&2; exit 1 ;;
esac
`
const FAKES = {
  'gh': FAKE_GH,
  'pnpm': FAKE_PNPM,
  'node': '#!/bin/sh\nprintf \'node %s\\n\' "$*" >>"$FAKE_LOG"\nexec "$REAL_NODE" "$@"\n',
  'git': '#!/bin/sh\ncase "$1" in commit|push|tag) printf \'git %s\\n\' "$*" >>"$FAKE_LOG" ;; esac\nexec "$REAL_GIT" "$@"\n',
  'ssh': '#!/bin/sh\nprintf \'ssh %s\\n\' "$*" >>"$FAKE_LOG"\n',
  'uname': '#!/bin/sh\ncase "$1" in -s) echo Darwin ;; -m) echo arm64 ;; *) echo Darwin ;; esac\n',
  'rsync': '#!/bin/sh\nexit 0\n',
  'curl': '#!/bin/sh\nexit 0\n',
  'npm': '#!/bin/sh\nexit 0\n',
}
const COPIED = [
  'zhitong/scripts/release.sh',
  'zhitong/scripts/release-lib.sh',
  'zhitong/scripts/release-state.mjs',
  'zhitong/portal/deploy/release-manifest.mjs',
  'zhitong/portal/site/src/data/release-manifest.mjs',
  'zhitong/portal/site/public/downloads/releases.json',
]

/** A git repository holding the release scripts, its bare origin, and a PATH of fake tools. */
function sandbox() {
  const root = tempRoot('zt-release-e2e-')
  const repo = join(root, 'repo')
  const bin = join(root, 'bin')
  const fake = join(root, 'fake')
  for (const dir of [repo, bin, fake]) mkdirSync(dir, { recursive: true })
  for (const path of COPIED) {
    mkdirSync(dirname(join(repo, path)), { recursive: true })
    copyFileSync(join(REPO, path), join(repo, path))
  }
  writeFileSync(join(repo, 'zhitong/portal/deploy/deploy.sh'), '#!/usr/bin/env bash\nprintf \'deploy.sh %s\\n\' "$*" >>"$FAKE_LOG"\n')
  writeFileSync(join(repo, '.gitignore'), 'zhitong/portal/downloads/\napps/desktop/.desktop-build/\nzhitong/plugins/tool-cad/bin/*/\n')
  mkdirSync(join(repo, 'zhitong/plugins/tool-cad/bin/darwin-arm64'), { recursive: true })
  writeFileSync(join(repo, 'zhitong/plugins/tool-cad/bin/darwin-arm64/dwg2dxf'), '#!/bin/sh\n')
  chmodSync(join(repo, 'zhitong/plugins/tool-cad/bin/darwin-arm64/dwg2dxf'), 0o755)
  for (const [name, body] of Object.entries(FAKES)) {
    writeFileSync(join(bin, name), body)
    chmodSync(join(bin, name), 0o755)
  }
  const git = (...args) => {
    const result = spawnSync(REAL_GIT, args, { cwd: repo, encoding: 'utf8' })
    assert.equal(result.status, 0, `git ${args.join(' ')}: ${result.stderr}`)
    return result.stdout.trim()
  }
  git('init', '-q', '-b', 'master')
  git('config', 'user.name', 'Release Test')
  git('config', 'user.email', 'release@example.invalid')
  git('add', '-A')
  git('commit', '-q', '-m', 'initial')
  spawnSync(REAL_GIT, ['init', '-q', '--bare', join(root, 'origin.git')])
  git('remote', 'add', 'origin', join(root, 'origin.git'))
  git('push', '-q', '-u', 'origin', 'master')
  const log = join(fake, 'calls.log')
  const release = (args, extraEnv = {}) => {
    writeFileSync(log, '')
    const result = spawnSync('bash', [join(repo, 'zhitong/scripts/release.sh'), ...args], {
      cwd: repo,
      encoding: 'utf8',
      env: {
        ...process.env,
        PATH: `${bin}:${process.env.PATH}`,
        FAKE_LOG: log,
        FAKE_DIR: fake,
        FAKE_VERSION: '1.0.1',
        REAL_NODE: process.execPath,
        REAL_GIT,
        ZT_RELEASE_POLL_SECONDS: '0',
        ZT_RELEASE_PROGRESS_SECONDS: '0',
        ZT_RELEASE_LOOKUP_SECONDS: '0',
        ...extraEnv,
      },
    })
    return { ...result, calls: readFileSync(log, 'utf8').trim().split('\n').filter(Boolean) }
  }
  const originGit = (...args) => spawnSync(REAL_GIT, ['--git-dir', join(root, 'origin.git'), ...args], { encoding: 'utf8' }).stdout.trim()
  return { root, repo, fake, git, originGit, release }
}

/** Assert that each pattern matches a call, in order. */
function assertOrder(calls, patterns) {
  let at = 0
  for (const pattern of patterns) {
    const found = calls.findIndex((call, i) => i >= at && pattern.test(call))
    assert.notEqual(found, -1, `no call matching ${pattern} after #${at}:\n${calls.join('\n')}`)
    at = found + 1
  }
}

describe('release.sh end to end (fake tools)', () => {
  it('builds both installers, stages, commits, pushes and deploys in order', () => {
    const box = sandbox()
    writeFileSync(join(box.root, 'notes.txt'), '修复概算导入\n\n新增 DWG 图框导出\n')
    const result = box.release(['1.0.1', '--notes-file', join(box.root, 'notes.txt')])
    assert.equal(result.status, 0, result.stdout + result.stderr)
    assertOrder(result.calls, [
      /^gh auth status$/u,
      /^ssh -o BatchMode=yes .* zt-prod true$/u,
      /^git tag -a v1\.0\.1 /u,
      /^git push origin refs\/tags\/v1\.0\.1$/u,
      /^gh run list --workflow zhitong-windows-installer\.yml /u,
      /^pnpm install --frozen-lockfile$/u,
      /^pnpm run package:desktop:mac:arm64:unsigned --check$/u,
      /^pnpm run package:desktop:mac:arm64:unsigned$/u,
      /^node zhitong\/scripts\/release-state\.mjs prepare --version 1\.0\.1 --notes-file /u,
      /^node zhitong\/portal\/deploy\/release-manifest\.mjs stage mac-arm64 .*deepseek-harness-0\.2\.1-rc\.2-mac-arm64-unsigned\.dmg$/u,
      /^gh run view 4242 /u,
      /^gh run download 4242 -n ztsgai-1\.0\.1-win-x64-setup -D /u,
      /^node zhitong\/scripts\/release-state\.mjs verify-sidecar /u,
      /^node zhitong\/portal\/deploy\/release-manifest\.mjs stage win-x64 .*ztsgai-1\.0\.1-win-x64-setup\.exe$/u,
      /^node zhitong\/portal\/deploy\/release-manifest\.mjs verify$/u,
      /^git commit -m release\(zhitong\): v1\.0\.1 -- zhitong\/portal\/site\/public\/downloads\/releases\.json$/u,
      /^git push origin master$/u,
      /^deploy\.sh zt-prod$/u,
    ])
    assert.match(result.stdout, /运行 4242：in_progress，Package Windows x64 installer \/ Build unsigned installer/u)
    assert.match(result.stdout, /ztsgai-1\.0\.1-mac-arm64\.dmg\n {4}sha256 [0-9a-f]{64}/u)
    assert.match(result.stdout, /https:\/\/ztsgai\.com\/downloads\/ztsgai-1\.0\.1-win-x64-setup\.exe/u)
    assert.match(result.stdout, /Release：https:\/\/github\.com\/example\/zhitong-harness\/releases\/tag\/v1\.0\.1/u)

    const published = JSON.parse(box.originGit('show', 'master:zhitong/portal/site/public/downloads/releases.json'))
    assert.equal(published.version, '1.0.1')
    assert.deepEqual(published.notes, ['修复概算导入', '新增 DWG 图框导出'])
    assert.equal(published.platforms['mac-arm64'].sha256, sha('fake dmg\n'))
    assert.equal(published.platforms['win-x64'].sha256, sha('fake windows installer 1.0.1\n'))
    assert.equal(box.originGit('log', '-1', '--format=%s', 'master'), 'release(zhitong): v1.0.1')
    assert.notEqual(box.originGit('rev-parse', '-q', '--verify', 'refs/tags/v1.0.1'), '')
    assert.equal(box.git('status', '--porcelain'), '')
    assert.ok(!existsSync(join(box.repo, 'zhitong/portal/downloads/.release/v1.0.1/win')), 'downloaded copy removed after staging')
  })

  it('stops on a failed Windows run with a resume command that reuses the staged Mac installer', () => {
    const box = sandbox()
    writeFileSync(join(box.fake, 'conclusion'), 'failure')
    const failed = box.release(['1.0.1', '--skip-deploy'])
    assert.equal(failed.status, 1)
    assert.match(failed.stderr, /Windows 运行 4242 结束：failure/u)
    assert.match(failed.stderr, /bash zhitong\/scripts\/release\.sh 1\.0\.1 --skip-deploy --from win --run-id 4242/u)
    assert.ok(existsSync(join(box.repo, 'zhitong/portal/downloads/ztsgai-1.0.1-mac-arm64.dmg')))
    assert.ok(!failed.calls.some(call => call.startsWith('git commit')))

    writeFileSync(join(box.fake, 'conclusion'), 'success')
    rmSync(join(box.fake, 'views'))
    const resumed = box.release(['1.0.1', '--skip-deploy', '--from', 'win', '--run-id', '4242'])
    assert.equal(resumed.status, 0, resumed.stdout + resumed.stderr)
    assert.ok(!resumed.calls.some(call => call.startsWith('pnpm') || call.startsWith('git tag')), resumed.calls.join('\n'))
    assertOrder(resumed.calls, [/^gh run download 4242 /u, /stage win-x64 /u, /^git commit /u, /^git push origin master$/u])
    assert.ok(!resumed.calls.some(call => call.startsWith('deploy.sh')))
    assert.match(resumed.stdout, /门户未部署/u)
    assert.equal(JSON.parse(box.originGit('show', 'master:zhitong/portal/site/public/downloads/releases.json')).platforms['mac-arm64'].file,
      'ztsgai-1.0.1-mac-arm64.dmg')

    const again = box.release(['1.0.1', '--skip-deploy', '--from', 'mac'])
    assert.equal(again.status, 0, again.stdout + again.stderr)
    assert.match(again.stdout, /已 stage：.*ztsgai-1\.0\.1-mac-arm64\.dmg，跳过打包/u)
    assert.match(again.stdout, /已 stage：.*ztsgai-1\.0\.1-win-x64-setup\.exe，跳过下载/u)
    assert.match(again.stdout, /releases\.json 已在提交里/u)
    assert.ok(!again.calls.some(call => /^(pnpm|gh run|git commit|git push)/u.test(call)), again.calls.join('\n'))
  })

  it('names the run id as the missing piece when the pushed tag starts no matching run', () => {
    const box = sandbox()
    const result = box.release(['1.0.1'], { FAKE_VERSION: '9.9.9', ZT_RELEASE_LOOKUP_TRIES: '2' })
    assert.equal(result.status, 1)
    assert.match(result.stderr, /找不到 v1\.0\.1 的「zhitong · Windows installer」运行/u)
    assert.match(result.stderr, /在「trigger」一步失败[\s\S]*release\.sh 1\.0\.1 --from mac --run-id <Actions 页上这次运行的 id>/u)
    assert.equal(result.calls.filter(call => call.startsWith('gh run list')).length, 2)
    assert.notEqual(box.originGit('rev-parse', '-q', '--verify', 'refs/tags/v1.0.1'), '', 'the tag was pushed before the lookup')
    assert.ok(!result.calls.some(call => call.startsWith('pnpm')))
  })

  it('prints the whole path in --dry-run without running or changing anything', () => {
    const box = sandbox()
    const head = box.git('rev-parse', 'HEAD')
    const result = box.release(['1.0.1', '--dry-run'])
    assert.equal(result.status, 0, result.stdout + result.stderr)
    const printed = (result.stdout + result.stderr).split('\n').filter(line => line.startsWith('+ '))
    assertOrder(printed, [
      /^\+ git fetch --quiet origin master$/u,
      /^\+ gh auth status$/u,
      /^\+ git ls-remote --tags origin refs\/tags\/v1\.0\.1$/u,
      /^\+ ssh -o BatchMode=yes -o ConnectTimeout=15 zt-prod true$/u,
      /^\+ git tag -a v1\.0\.1 -m '智通数工AI v1\.0\.1' [0-9a-f]{40}$/u,
      /^\+ git push origin refs\/tags\/v1\.0\.1$/u,
      /^\+ gh run list /u,
      /^\+ pnpm install --frozen-lockfile$/u,
      /^\+ pnpm run package:desktop:mac:arm64:unsigned --check$/u,
      /^\+ pnpm run package:desktop:mac:arm64:unsigned 2>&1 \| tee zhitong\/portal\/downloads\/\.release\/v1\.0\.1\/mac-build\.log$/u,
      /^\+ node zhitong\/scripts\/release-state\.mjs prepare --version 1\.0\.1$/u,
      /^\+ node zhitong\/portal\/deploy\/release-manifest\.mjs stage mac-arm64 /u,
      /^\+ gh run view '<运行id>' --json status,conclusion,jobs/u,
      /^\+ gh run download '<运行id>' -n ztsgai-1\.0\.1-win-x64-setup -D /u,
      /^\+ node zhitong\/scripts\/release-state\.mjs verify-sidecar /u,
      /^\+ node zhitong\/portal\/deploy\/release-manifest\.mjs stage win-x64 /u,
      /^\+ node zhitong\/portal\/deploy\/release-manifest\.mjs verify$/u,
      /^\+ git add -- zhitong\/portal\/site\/public\/downloads\/releases\.json$/u,
      /^\+ git commit -m 'release\(zhitong\): v1\.0\.1' -- /u,
      /^\+ git push origin master$/u,
      /^\+ bash zhitong\/portal\/deploy\/deploy\.sh zt-prod$/u,
    ])
    assert.ok(!result.calls.some(call => /^(gh|pnpm|ssh|git|deploy\.sh) /u.test(call)), result.calls.join('\n'))
    assert.equal(box.git('rev-parse', 'HEAD'), head)
    assert.equal(box.git('status', '--porcelain'), '')
    assert.equal(box.git('tag'), '')
  })

  it('triggers by workflow dispatch with --no-tag', () => {
    const box = sandbox()
    const result = box.release(['1.0.1', '--no-tag', '--skip-mac', '--dry-run'])
    assert.equal(result.status, 0, result.stdout + result.stderr)
    assert.match(result.stdout, /^\+ gh workflow run zhitong-windows-installer\.yml --ref master -f version=1\.0\.1 -f publish=true$/mu)
    assert.match(result.stdout, /^\+ gh release view v1\.0\.1 --json assets/mu)
    assert.doesNotMatch(result.stdout, /git tag|pnpm/u)
  })

  it('refuses to start from a dirty tree, another branch, an older version or an existing tag', () => {
    const box = sandbox()
    writeFileSync(join(box.repo, 'stray.txt'), 'x')
    let result = box.release(['1.0.1'])
    assert.equal(result.status, 1)
    assert.match(result.stderr, /工作树不干净[\s\S]*stray\.txt/u)
    assert.match(result.stderr, /重跑同一条命令/u)
    rmSync(join(box.repo, 'stray.txt'))

    result = box.release(['0.9.0'])
    assert.equal(result.status, 1)
    assert.match(result.stderr, /older than v1\.0\.0/u)

    box.git('switch', '-q', '-c', 'feat/x')
    result = box.release(['1.0.1'])
    assert.equal(result.status, 1)
    assert.match(result.stderr, /当前分支是 feat\/x/u)
    box.git('switch', '-q', 'master')

    box.git('tag', 'v1.0.1')
    box.git('push', '-q', 'origin', 'v1.0.1')
    box.git('tag', '-d', 'v1.0.1')
    result = box.release(['1.0.1'])
    assert.equal(result.status, 1)
    assert.match(result.stderr, /远端已有 tag v1\.0\.1.*--from mac.*--no-tag/u)
    assert.ok(!result.calls.some(call => call.startsWith('pnpm') || call.startsWith('git push')), result.calls.join('\n'))
  })
})
