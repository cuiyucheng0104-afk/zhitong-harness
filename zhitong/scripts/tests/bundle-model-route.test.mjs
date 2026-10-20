// node --test zhitong/scripts/tests/：@zhitong/bundle 的模型路由（W14 问题 1）。
// 用临时 DSH_HOME 从源码启动 dsh（tsx），约 10 秒：建 web 与 headless 两个 profile，link 本 bundle，
// 在用户层写入旧安装留下的默认模型（deepseek-account，上游账号登录后 initializeDefaultModel 写的那一行），
// 然后核对组合结果与一次真实的 headless 请求。模型请求发往本机假服务器，不连外网。
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { after, before, describe, it } from 'node:test'

const repo = resolve(import.meta.dirname, '../../..')
const tsx = pathToFileURL(createRequire(join(repo, 'package.json')).resolve('tsx/esm')).href
const bin = join(repo, 'apps/cli/src/bin.ts')
const STALE_DEFAULT = '- id: agent-default-model\n  config:\n    provider: deepseek-account\n    model: deepseek-flash\n'

const root = mkdtempSync(join(tmpdir(), 'zt-model-route-'))
const home = join(root, 'dsh-home')
const cwd = join(root, 'workspace')
mkdirSync(home)
mkdirSync(cwd)
after(() => { rmSync(root, { recursive: true, force: true }) })

/** Environment without any ambient DeepSeek key or endpoint, so only what the test stores is visible. */
function environment(extra = {}) {
  // The workspace is outside the repository (no repository `.env`), so tsx needs the root tsconfig `paths` named.
  const env = { ...process.env, DSH_HOME: home, TSX_TSCONFIG_PATH: join(repo, 'tsconfig.json'), ...extra }
  for (const name of ['DEEPSEEK_API_KEY', 'DEEPSEEK_BASE_URL']) if (!(name in extra)) delete env[name]
  return env
}

function dsh(args, extra) {
  return new Promise((done, fail) => {
    const child = spawn(process.execPath, ['--import', tsx, bin, ...args], { cwd, env: environment(extra) })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (chunk) => { stdout += chunk })
    child.stderr.on('data', (chunk) => { stderr += chunk })
    child.on('error', fail)
    child.on('close', code => done({ code, stdout, stderr }))
  })
}

async function profile(name, template) {
  const created = await dsh(['--profile', name, '--from-default-profile', template, '--dump-config'])
  assert.equal(created.code, 0, created.stderr)
  const linked = await dsh(['plugin', '--profile', name, 'add', `link:${join(repo, 'zhitong/bundle')}`])
  assert.equal(linked.code, 0, linked.stderr)
  writeFileSync(join(home, 'profiles', name, 'cordis.patch.yml'), STALE_DEFAULT)
}

/** One composed entry from `--dump-config`, from its `- id:` line to the next top-level entry or layer comment. */
function entry(dump, id) {
  const lines = dump.split('\n')
  const start = lines.indexOf(`- id: ${id}`)
  assert.notEqual(start, -1, `no entry ${id}`)
  let end = start + 1
  while (end < lines.length && !lines[end].startsWith('- ') && !lines[end].startsWith('#')) end++
  return lines.slice(start, end).join('\n')
}

describe('@zhitong/bundle model route', { timeout: 300_000 }, () => {
  before(async () => {
    await profile('zt-web', 'web')
    await profile('zt-headless', 'headless')
  })

  it('composes the API-key route as the default and ignores a stale account default in the user layer', async () => {
    const { code, stdout, stderr } = await dsh(['--profile', 'zt-web', '--dump-config'])
    assert.equal(code, 0, stderr)
    assert.match(entry(stdout, 'zhitong-default-model'),
      /name: '@deepseek-ai\/dsh-agent-default-model'\n {2}config:\n {4}provider: deepseek-official\n {4}model: deepseek-flash$/u)
    const upstream = entry(stdout, 'agent-default-model')
    assert.match(upstream, /provider: deepseek-account/u)
    assert.match(upstream, /\n {2}disabled: true$/u)
    assert.match(entry(stdout, 'llm-deepseek-account'), /\n {2}disabled: true$/u)
    assert.doesNotMatch(entry(stdout, 'llm-deepseek'), /disabled/u)
    const preset = entry(stdout, 'preset-zhitong')
    assert.match(preset, /\n {4}id: zhitong\n {4}order: 0\n/u)
    assert.doesNotMatch(preset, /\n {4}(name|description):/u)
  })

  it('reports a missing key, not an account sign-in, when no key is stored', async () => {
    const { code, stderr } = await dsh(['--profile', 'zt-headless', 'say hi'])
    assert.notEqual(code, 0)
    assert.match(stderr, /MISSING_CREDENTIAL: .*"deepseek-official".*DEEPSEEK_API_KEY/u)
    assert.doesNotMatch(stderr, /ACCOUNT_SIGN_IN_REQUIRED/u)
  })

  it('sends the key stored under DEEPSEEK_API_KEY, as the welcome page saves it, on the official route', async () => {
    const seen = []
    const server = createServer((request, response) => {
      seen.push({ method: request.method, url: request.url, key: request.headers['x-api-key'] })
      request.resume()
      response.writeHead(401, { 'content-type': 'application/json' })
      response.end(JSON.stringify({ type: 'error', error: { type: 'authentication_error', message: 'test server' } }))
    })
    await new Promise(done => server.listen(0, '127.0.0.1', done))
    try {
      // The headless template reads keys from the launch environment; this overlay mounts the managed store the
      // desktop and Web profiles use, and the key goes where the welcome page writes it.
      writeFileSync(join(home, '.credentials.yaml'), 'version: 1\nrefs:\n  DEEPSEEK_API_KEY: sk-zt14-welcome\n', { mode: 0o600 })
      const overlay = join(root, 'credentials.overlay.yml')
      writeFileSync(overlay, '- id: credentials\n  disabled: false\n- id: authorization\n  disabled: false\n')
      const { stderr } = await dsh(['--profile', 'zt-headless', '--patch', overlay, 'say hi'],
        { DEEPSEEK_BASE_URL: `http://127.0.0.1:${server.address().port}/anthropic` })
      assert.doesNotMatch(stderr, /ACCOUNT_SIGN_IN_REQUIRED|MISSING_CREDENTIAL/u)
      const messages = seen.filter(request => request.method === 'POST' && request.url === '/anthropic/v1/messages')
      assert.ok(messages.length > 0, `no Messages request reached the test server: ${JSON.stringify(seen)}\n${stderr}`)
      for (const request of messages) assert.equal(request.key, 'sk-zt14-welcome')
    } finally {
      await new Promise(done => server.close(done))
      rmSync(join(home, '.credentials.yaml'), { force: true })
    }
  })
})
