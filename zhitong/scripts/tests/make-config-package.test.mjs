// node --test zhitong/scripts/tests/：配置包生成脚本（校验、zip 布局、密钥只从环境变量来）。
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { after, describe, it } from 'node:test'

const REPOSITORY = resolve(import.meta.dirname, '..', '..', '..')
const SCRIPT = join(REPOSITORY, 'zhitong', 'scripts', 'make-config-package.ts')
const TSX = join(REPOSITORY, 'node_modules', '.bin', 'tsx')
const roots = []
after(() => { for (const root of roots) rmSync(root, { recursive: true, force: true }) })

function run(args, env) {
  const result = spawnSync(TSX, [SCRIPT, ...args], {
    cwd: REPOSITORY,
    encoding: 'utf8',
    env: { ...process.env, ZT_PKG_ACCESS_KEY_ID: '', ZT_PKG_SECRET_ACCESS_KEY: '', ...env },
    timeout: 120_000,
  })
  return { status: result.status, out: result.stdout + result.stderr }
}

describe('make-config-package', () => {
  it('writes a validated document and a zip config_import can read, without leaking the key', () => {
    const out = mkdtempSync(join(tmpdir(), 'zt-pkg-'))
    roots.push(out)
    const result = run(
      ['--company', '某某 造价/咨询', '--bucket', 'zt-company', '--prefix', '/某某咨询/', '--out', out, '--skip-probe', '--comment', '测试'],
      { ZT_PKG_ACCESS_KEY_ID: 'AKLTtestkey0001', ZT_PKG_SECRET_ACCESS_KEY: 'secret-value-xyz' },
    )
    assert.equal(result.status, 0, result.out)
    assert.ok(!result.out.includes('secret-value-xyz'), 'secret leaked into output')
    assert.ok(!result.out.includes('AKLTtestkey0001'), 'full access key id leaked into output')
    assert.ok(result.out.includes('0001'), 'last four digits of the key id are shown')
    const json = JSON.parse(readFileSync(join(out, '某某造价咨询', 'zhitong.config.json'), 'utf8'))
    assert.equal(json.format, 'zhitong.config/1')
    assert.equal(json.tos.prefix, '某某咨询')
    assert.equal(json.tos.secretAccessKey, 'secret-value-xyz')
    assert.deepEqual(Object.keys(json), ['format', 'comment', 'company', 'tos'])
    if (process.platform !== 'win32') assert.equal(statSync(join(out, '某某造价咨询', 'zhitong.config.json')).mode & 0o777, 0o600)
    const zip = readdirSync(out).find(name => name.endsWith('.zip'))
    assert.match(zip, /^某某造价咨询-zhitong-config-\d{8}\.zip$/u)
    // The zip must hold exactly <stem>/zhitong.config.json, the layout config_import's readPackageText accepts.
    const { unzipSync, strFromU8 } = createRequire(join(REPOSITORY, 'zhitong', 'plugins', 'config-import', 'package.json'))('fflate')
    const entries = unzipSync(readFileSync(join(out, zip)))
    assert.deepEqual(Object.keys(entries), ['某某造价咨询/zhitong.config.json'])
    const parsed = JSON.parse(strFromU8(entries['某某造价咨询/zhitong.config.json']))
    assert.equal(parsed.company.name, '某某 造价/咨询')
    assert.equal(parsed.tos.bucket, 'zt-company')
  })

  it('refuses to run without the key in the environment and rejects an invalid bucket name', () => {
    const out = mkdtempSync(join(tmpdir(), 'zt-pkg-'))
    roots.push(out)
    const missing = run(['--company', 'x', '--bucket', 'zt-company', '--prefix', 'x', '--out', out, '--skip-probe'], {})
    assert.equal(missing.status, 2)
    assert.match(missing.out, /ZT_PKG_ACCESS_KEY_ID/u)
    const invalid = run(
      ['--company', 'x', '--bucket', 'Bad_Bucket', '--prefix', 'x', '--out', out, '--skip-probe'],
      { ZT_PKG_ACCESS_KEY_ID: 'AKLTa', ZT_PKG_SECRET_ACCESS_KEY: 'b' },
    )
    assert.equal(invalid.status, 2)
    assert.match(invalid.out, /tos\.bucket/u)
    assert.equal(readdirSync(out).length, 0, 'nothing written on validation failure')
  })
})
