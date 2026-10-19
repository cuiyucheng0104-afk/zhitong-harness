import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { strToU8, zipSync } from 'fflate'
import type { Context } from '@deepseek-ai/cordis'
import * as ConfigImport from '../src/index.ts'
import { PackageError, parsePackage } from '../src/package.ts'
import { call, tempDir, text, toolContext, valueOf } from '../../tool-tos/tests/support.ts'

const SECRET_ID = 'AKLTexampleAccessKeyId0001'
const SECRET_KEY = 'TWpVd05qSXhNekl0ZXhhbXBsZS1zZWNyZXQ='

function pkg(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    format: 'zhitong.config/1',
    company: { name: '某某工程造价咨询有限公司' },
    tos: {
      endpoint: 'tos-cn-beijing.volces.com',
      region: 'cn-beijing',
      bucket: 'zt-company',
      prefix: '/某某咨询/',
      accessKeyId: ` ${SECRET_ID} `,
      secretAccessKey: SECRET_KEY,
    },
    ...overrides,
  }
}

interface Entry { options: { id: string; name: string; config: Record<string, unknown> } }

/** Stand-in for ctx.configEditor that records applied configs. */
class FakeEditor {
  readonly rows: Entry[] = [
    { options: { id: 'zhitong-tool-tos', name: '@zhitong/tool-tos', config: { cacheMaxBytes: 1000, backend: 'tos' } } },
  ]

  failWith: Error | undefined

  entries(): Entry[] {
    return this.rows
  }

  async edit(entry: Entry, change: (current: Record<string, unknown>, inherited: Record<string, unknown>) => Record<string, unknown>): Promise<void> {
    if (this.failWith !== undefined) throw this.failWith
    entry.options.config = change(structuredClone(entry.options.config), {})
  }
}

const cleanups: Array<() => void> = []
afterEach(() => {
  while (cleanups.length > 0) cleanups.pop()!()
})

function workDir(): string {
  const dir = tempDir('config')
  cleanups.push(dir.cleanup)
  return dir.path
}

async function setup(options: { editor?: boolean; credentials?: boolean } = {}) {
  const { ctx, credentials } = await toolContext(options.credentials !== false)
  const editor = new FakeEditor()
  if (options.editor !== false) {
    ctx.provide('configEditor')
    ctx.set('configEditor', editor)
  }
  await ctx.plugin(ConfigImport, {})
  return { ctx, credentials, editor }
}

function writePackage(dir: string, value: unknown, name = 'zhitong.config.json'): string {
  const file = join(dir, name)
  writeFileSync(file, typeof value === 'string' ? value : JSON.stringify(value, null, 2))
  return file
}

function expectNoSecret(output: string): void {
  expect(output).not.toContain(SECRET_ID)
  expect(output).not.toContain(SECRET_KEY)
}

interface ImportValue {
  applied: boolean
  company: string
  tos: { endpoint: string; region: string; bucket: string; prefix: string }
  storedCredentials: string[]
  deferredSections: string[]
}

async function importOk(ctx: Context, path: string, dryRun = false): Promise<{ value: ImportValue; output: string }> {
  const result = await call(ctx, 'config_import', { path, ...dryRun ? { dry_run: true } : {} })
  const output = `${text(result)}${JSON.stringify(result.isError ? null : result.value)}`
  return { value: valueOf<ImportValue>(result), output }
}

describe('config_import', () => {
  it('stores the access keys and writes the TOS entry config', async () => {
    const { ctx, credentials, editor } = await setup()
    const { value, output } = await importOk(ctx, writePackage(workDir(), pkg()))
    expect(value).toEqual({
      applied: true,
      company: '某某工程造价咨询有限公司',
      tos: { endpoint: 'tos-cn-beijing.volces.com', region: 'cn-beijing', bucket: 'zt-company', prefix: '某某咨询' },
      storedCredentials: ['ZT_TOS_ACCESS_KEY_ID', 'ZT_TOS_SECRET_ACCESS_KEY'],
      deferredSections: [],
    })
    expectNoSecret(output)
    expect(credentials!.values.get('ZT_TOS_ACCESS_KEY_ID')).toBe(SECRET_ID)
    expect(credentials!.values.get('ZT_TOS_SECRET_ACCESS_KEY')).toBe(SECRET_KEY)
    expect(editor.rows[0]!.options.config).toEqual({
      cacheMaxBytes: 1000,
      backend: 'tos',
      endpoint: 'tos-cn-beijing.volces.com',
      region: 'cn-beijing',
      bucket: 'zt-company',
      prefix: '某某咨询',
      accessKeyIdRef: 'ZT_TOS_ACCESS_KEY_ID',
      secretAccessKeyRef: 'ZT_TOS_SECRET_ACCESS_KEY',
    })
    expectNoSecret(JSON.stringify(editor.rows[0]!.options.config))
  })

  it('validates without writing on dry_run', async () => {
    const { ctx, credentials, editor } = await setup()
    const { value, output } = await importOk(ctx, writePackage(workDir(), pkg()), true)
    expect(value.applied).toBe(false)
    expect(output).toContain('未写入')
    expect(credentials!.values.size).toBe(0)
    expect(editor.rows[0]!.options.config).toEqual({ cacheMaxBytes: 1000, backend: 'tos' })
  })

  it('reads the document from a zip, at the root or one directory down', async () => {
    const { ctx } = await setup()
    const dir = workDir()
    const json = strToU8(JSON.stringify(pkg()))
    const flat = join(dir, 'flat.zip')
    writeFileSync(flat, zipSync({ 'zhitong.config.json': json, 'README.txt': strToU8('说明') }))
    expect((await importOk(ctx, flat, true)).value.company).toBe('某某工程造价咨询有限公司')
    const nested = join(dir, 'nested.ZIP')
    writeFileSync(nested, zipSync({ '某某咨询/zhitong.config.json': json, '__MACOSX/某某咨询/zhitong.config.json': strToU8('junk') }))
    expect((await importOk(ctx, nested, true)).value.tos.bucket).toBe('zt-company')

    const twice = join(dir, 'twice.zip')
    writeFileSync(twice, zipSync({ 'a/zhitong.config.json': json, 'b/zhitong.config.json': json }))
    expect(text(await call(ctx, 'config_import', { path: twice }))).toContain('多个')
    const none = join(dir, 'none.zip')
    writeFileSync(none, zipSync({ 'other.json': json }))
    expect(text(await call(ctx, 'config_import', { path: none }))).toContain('没有 zhitong.config.json')
    const broken = join(dir, 'broken.zip')
    writeFileSync(broken, 'not a zip')
    expect(text(await call(ctx, 'config_import', { path: broken }))).toContain('不是有效的 zip')
  })

  it('reports every problem by field path without echoing values', async () => {
    const { ctx, credentials } = await setup()
    const bad = pkg({
      format: 'v0',
      extra: true,
      tos: { endpoint: 'https://tos-cn-beijing.volces.com/', region: '', bucket: 'Bad_Bucket', prefix: '../x', accessKeyId: SECRET_ID },
      ssh: { hosts: [{ alias: 'prod', host: '10.0.0.1', user: 'root', port: 70000, privateKey: SECRET_KEY }, { alias: 'prod', host: 'h', user: 'u' }] },
    })
    const result = await call(ctx, 'config_import', { path: writePackage(workDir(), bad) })
    expect(result.isError).toBe(true)
    const output = text(result)
    for (const fragment of ['format', 'extra 不是认识的字段', 'tos.endpoint', 'tos.region', 'tos.bucket', 'tos.prefix', 'tos.secretAccessKey', 'ssh.hosts[0].port', 'ssh.hosts[1].alias']) {
      expect(output).toContain(fragment)
    }
    expectNoSecret(output)
    expect(credentials!.values.size).toBe(0)
  })

  it('does not echo document text from a JSON syntax error', async () => {
    const { ctx } = await setup()
    const result = await call(ctx, 'config_import', { path: writePackage(workDir(), `{"tos": {"secretAccessKey": "${SECRET_KEY}" oops}}`) })
    expect(text(result)).toContain('不是合法 JSON')
    expectNoSecret(text(result))
  })

  it('validates and defers the ssh and volc sections', async () => {
    const { ctx } = await setup()
    const withExtras = pkg({
      ssh: { hosts: [{ alias: 'zt-prod', host: '10.0.0.1', user: 'root', privateKey: '-----BEGIN OPENSSH PRIVATE KEY-----\nxx\n' }] },
      volc: { profile: 'zt-ak', region: 'cn-beijing' },
    })
    const { value, output } = await importOk(ctx, writePackage(workDir(), withExtras))
    expect(value.deferredSections).toEqual(['ssh', 'volc'])
    expect(output).toContain('暂不应用')
    expect(output).not.toContain('PRIVATE KEY')
  })

  it('refuses relative paths, missing files, and oversized packages', async () => {
    const { ctx } = await setup()
    expect(text(await call(ctx, 'config_import', { path: 'zhitong.config.json' }))).toContain('绝对路径')
    expect(text(await call(ctx, 'config_import', { path: join(workDir(), 'missing.json') }))).toContain('找不到配置包')
    const small = await toolContext()
    await small.ctx.plugin(ConfigImport, { maxPackageBytes: 10 })
    expect(text(await call(small.ctx, 'config_import', { path: writePackage(workDir(), pkg()) }))).toContain('超过上限')
  })

  it('fails loudly when the profile cannot store the result', async () => {
    const noEditor = await setup({ editor: false })
    expect(text(await call(noEditor.ctx, 'config_import', { path: writePackage(workDir(), pkg()) }))).toContain('config-editor')

    const noCredentials = await setup({ credentials: false })
    expect(text(await call(noCredentials.ctx, 'config_import', { path: writePackage(workDir(), pkg()) }))).toContain('凭据存储')

    const missingEntry = await setup()
    missingEntry.editor.rows.length = 0
    expect(text(await call(missingEntry.ctx, 'config_import', { path: writePackage(workDir(), pkg()) }))).toContain('zhitong-tool-tos')
    expect(missingEntry.credentials!.values.size).toBe(0)

    const failing = await setup()
    failing.editor.failWith = new Error('overridden by a home patch')
    const result = await call(failing.ctx, 'config_import', { path: writePackage(workDir(), pkg()) })
    expect(text(result)).toContain('密钥已存入凭据存储，但 TOS 设置未能写入 profile：overridden by a home patch')
    expectNoSecret(text(result))
  })

  it('removes the tool when the plugin is disposed', async () => {
    const { ctx } = await toolContext()
    const fiber = ctx.plugin(ConfigImport, {})
    await fiber
    expect(ctx.tools.schemas().some(schema => schema.name === 'config_import')).toBe(true)
    await fiber.dispose()
    expect(ctx.tools.schemas().some(schema => schema.name === 'config_import')).toBe(false)
  })
})

describe('parsePackage', () => {
  it('accepts the documented example', () => {
    const parsed = parsePackage(JSON.stringify(pkg({ comment: '2026-10 首次发放' })))
    expect(parsed.tos.accessKeyId).toBe(SECRET_ID)
    expect(parsed.tos.prefix).toBe('某某咨询')
  })

  it('accepts a UTF-8 BOM and rejects non-object roots', () => {
    expect(parsePackage(`﻿${JSON.stringify(pkg())}`).company.name).toBe('某某工程造价咨询有限公司')
    expect(() => parsePackage('[]')).toThrow(PackageError)
    expect(() => parsePackage('{"format":"zhitong.config/1"}')).toThrow(/company 必须是对象[\s\S]*tos 必须是对象/u)
  })
})
