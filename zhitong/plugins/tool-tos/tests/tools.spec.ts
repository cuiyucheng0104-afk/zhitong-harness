import { mkdirSync, readFileSync, utimesSync, writeFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import type { Context } from '@deepseek-ai/cordis'
import * as ToolTos from '../src/index.ts'
import type { Config } from '../src/index.ts'
import { call, tempDir, text, toolContext, valueOf } from './support.ts'

interface Listing {
  path: string
  location: string
  dirs: string[]
  files: Array<{ path: string; size: number; cached: boolean }>
  next?: string
}
interface PullItem { path: string; local: string; status: string; message?: string }
interface Pull { path: string; items: PullItem[]; skipped: string[]; truncated: boolean }
interface Stat { exists: boolean; localState: string; local: string; sha256?: string; size?: number }
interface Push {
  path: string
  status: string
  verified: boolean
  sha256: string
  replaced: { etag: string } | null
  remoteChangedSincePull: boolean
}

const cleanups: Array<() => void> = []
afterEach(() => {
  while (cleanups.length > 0) cleanups.pop()!()
})

/** A bucket directory with the company prefix `某咨询公司`, and an empty mirror root. */
function fixture(): { bucket: string; cache: string; put: (rel: string, content: string) => string } {
  const bucket = tempDir('bucket')
  const cache = tempDir('cache')
  cleanups.push(bucket.cleanup, cache.cleanup)
  const put = (rel: string, content: string): string => {
    const file = join(bucket.path, '某咨询公司', ...rel.split('/'))
    mkdirSync(join(file, '..'), { recursive: true })
    writeFileSync(file, content)
    return file
  }
  return { bucket: bucket.path, cache: cache.path, put }
}

async function mount(config: Config): Promise<Context> {
  const { ctx } = await toolContext()
  await ctx.plugin(ToolTos, config)
  return ctx
}

async function localSetup(extra: Partial<Config> = {}) {
  const f = fixture()
  const ctx = await mount({ backend: 'local', localRoot: f.bucket, prefix: '/某咨询公司/', cacheRoot: f.cache, ...extra })
  return { ...f, ctx }
}

const PROJECT = '项目/2026-007-某小区 一期'

describe('tos_ls', () => {
  it('lists one level relative to the company prefix and pages with continuation', async () => {
    const { ctx, put } = await localSetup({ maxListEntries: 2 })
    put(`${PROJECT}/项目说明.md`, '# 项目说明')
    put(`${PROJECT}/资料/合同.pdf`, 'pdf')
    put(`${PROJECT}/图纸/总图.dwg`, 'dwg')
    put('案例索引.md', '| 编号 |')

    const root = valueOf<Listing>(await call(ctx, 'tos_ls', { path: '' }))
    expect(root.location).toMatch(/^local:\/\/.*\/某咨询公司\/$/u)
    expect(root.dirs).toEqual(['项目/'])
    expect(root.files.map(file => file.path)).toEqual(['案例索引.md'])

    const first = valueOf<Listing>(await call(ctx, 'tos_ls', { path: `${PROJECT}/`, limit: 50 }))
    expect(first.path).toBe(`${PROJECT}/`)
    expect([...first.dirs, ...first.files.map(file => file.path)]).toEqual([`${PROJECT}/图纸/`, `${PROJECT}/资料/`])
    expect(first.next).toBe('2')
    const second = valueOf<Listing>(await call(ctx, 'tos_ls', { path: `${PROJECT}\\`, continuation: first.next }))
    expect(second.files.map(file => file.path)).toEqual([`${PROJECT}/项目说明.md`])
    expect(second.next).toBeUndefined()
  })

  it('lists recursively, names a single file, and reports an empty directory', async () => {
    const { ctx, put } = await localSetup()
    put(`${PROJECT}/资料/a.pdf`, 'a')
    put(`${PROJECT}/资料/子目录/b.pdf`, 'b')
    const all = valueOf<Listing>(await call(ctx, 'tos_ls', { path: PROJECT, recursive: true }))
    expect(all.dirs).toEqual([])
    expect(all.files.map(file => file.path)).toEqual([`${PROJECT}/资料/a.pdf`, `${PROJECT}/资料/子目录/b.pdf`])
    const single = valueOf<Listing>(await call(ctx, 'tos_ls', { path: `${PROJECT}/资料/a.pdf` }))
    expect(single.files).toEqual([expect.objectContaining({ path: `${PROJECT}/资料/a.pdf`, size: 1, cached: false })])
    const missing = await call(ctx, 'tos_ls', { path: '项目/不存在/' })
    expect(text(missing)).toContain('（空）')
  })

  it('refuses paths that leave the prefix', async () => {
    const { ctx } = await localSetup()
    for (const path of ['../其他公司/', '/etc/', 'C:\\Users\\', '项目/../../x', 'tos://bucket/x']) {
      const result = await call(ctx, 'tos_ls', { path })
      expect(result.isError, path).toBe(true)
    }
    expect(text(await call(ctx, 'tos_ls', { path: '.zhitong-cache/' }))).not.toContain('保留目录')
    expect((await call(ctx, 'tos_pull', { path: '.zhitong-cache/index.json' })).isError).toBe(true)
  })
})

describe('tos_pull and tos_stat', () => {
  it('downloads into a mirror with the bucket layout, then serves the cached copy', async () => {
    const { ctx, cache, put } = await localSetup()
    put(`${PROJECT}/资料/合同 v2.pdf`, '合同内容')
    const rel = `${PROJECT}/资料/合同 v2.pdf`
    expect(valueOf<Stat>(await call(ctx, 'tos_stat', { path: rel })).localState).toBe('absent')

    const first = valueOf<Pull>(await call(ctx, 'tos_pull', { path: rel }))
    expect(first.items).toEqual([expect.objectContaining({ status: 'downloaded', local: join(cache, ...rel.split('/')) })])
    expect(readFileSync(first.items[0]!.local, 'utf8')).toBe('合同内容')
    expect(valueOf<Stat>(await call(ctx, 'tos_stat', { path: rel })).localState).toBe('current')
    expect(valueOf<Listing>(await call(ctx, 'tos_ls', { path: `${PROJECT}/资料/` })).files[0]!.cached).toBe(true)

    const again = valueOf<Pull>(await call(ctx, 'tos_pull', { path: rel }))
    expect(again.items[0]!.status).toBe('cached')
  })

  it('refreshes a stale copy, protects local edits, and overwrites on request', async () => {
    const { ctx, put } = await localSetup()
    const rel = `${PROJECT}/工作/核对.xlsx`
    put(rel, 'v1')
    const local = valueOf<Pull>(await call(ctx, 'tos_pull', { path: rel })).items[0]!.local

    put(rel, 'version 2')
    expect(valueOf<Stat>(await call(ctx, 'tos_stat', { path: rel })).localState).toBe('stale')
    expect(valueOf<Pull>(await call(ctx, 'tos_pull', { path: rel })).items[0]!.status).toBe('downloaded')
    expect(readFileSync(local, 'utf8')).toBe('version 2')

    writeFileSync(local, 'local edit')
    expect(valueOf<Stat>(await call(ctx, 'tos_stat', { path: rel })).localState).toBe('modified')
    const conflict = valueOf<Pull>(await call(ctx, 'tos_pull', { path: rel }))
    expect(conflict.items[0]).toMatchObject({ status: 'conflict' })
    expect(conflict.items[0]!.message).toContain('tos_push')
    expect(readFileSync(local, 'utf8')).toBe('local edit')

    expect(valueOf<Pull>(await call(ctx, 'tos_pull', { path: rel, overwrite: true })).items[0]!.status).toBe('downloaded')
    expect(readFileSync(local, 'utf8')).toBe('version 2')
  })

  it('adopts an untracked local file whose content already matches', async () => {
    const { ctx, cache, put } = await localSetup()
    const rel = `${PROJECT}/项目说明.md`
    put(rel, '# 说明')
    const local = join(cache, ...rel.split('/'))
    mkdirSync(join(local, '..'), { recursive: true })
    writeFileSync(local, '# 说明')
    expect(valueOf<Stat>(await call(ctx, 'tos_stat', { path: rel })).localState).toBe('untracked')
    expect(valueOf<Pull>(await call(ctx, 'tos_pull', { path: rel })).items[0]!.status).toBe('cached')
    expect(valueOf<Stat>(await call(ctx, 'tos_stat', { path: rel })).localState).toBe('current')
    writeFileSync(local, '# 不同内容')
    utimesSync(local, new Date(0), new Date(0))
    expect(valueOf<Pull>(await call(ctx, 'tos_pull', { path: rel })).items[0]!.status).toBe('conflict')
  })

  it('pulls a directory recursively, skipping drawings unless asked', async () => {
    const { ctx, put } = await localSetup()
    put(`${PROJECT}/资料/a.pdf`, 'a')
    put(`${PROJECT}/资料/子/b.docx`, 'b')
    put(`${PROJECT}/图纸/总图.DWG`, 'dwg')
    const pulled = valueOf<Pull>(await call(ctx, 'tos_pull', { path: `${PROJECT}/` }))
    expect(pulled.items.map(item => item.path)).toEqual([`${PROJECT}/资料/a.pdf`, `${PROJECT}/资料/子/b.docx`])
    expect(pulled.skipped).toEqual([`${PROJECT}/图纸/总图.DWG`])
    expect(pulled.truncated).toBe(false)
    expect(text(await call(ctx, 'tos_pull', { path: `${PROJECT}/` }))).toContain('cached 2')

    const withDrawings = valueOf<Pull>(await call(ctx, 'tos_pull', { path: `${PROJECT}/图纸/`, include_drawings: true }))
    expect(withDrawings.items.map(item => item.status)).toEqual(['downloaded'])
    const named = valueOf<Pull>(await call(ctx, 'tos_pull', { path: `${PROJECT}/图纸/总图.DWG` }))
    expect(named.items[0]!.status).toBe('cached')
  })

  it('stops a directory pull at maxPullFiles and says so', async () => {
    const { ctx, put } = await localSetup({ maxPullFiles: 2 })
    for (const name of ['1.txt', '2.txt', '3.txt']) put(`批量/${name}`, name)
    const pulled = valueOf<Pull>(await call(ctx, 'tos_pull', { path: '批量/' }))
    expect(pulled.items).toHaveLength(2)
    expect(pulled.truncated).toBe(true)
    expect(text(await call(ctx, 'tos_pull', { path: '批量/' }))).toContain('缩小目录范围')
  })

  it('fails loudly for a missing file', async () => {
    const { ctx } = await localSetup()
    const result = await call(ctx, 'tos_pull', { path: '项目/没有.pdf' })
    expect(result.isError).toBe(true)
    expect(text(result)).toContain('桶内没有文件')
  })
})

describe('cache bound', () => {
  const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

  it('evicts least-recently-used unmodified files and never evicts local edits', async () => {
    const { ctx, put } = await localSetup({ cacheMaxBytes: 10 })
    put('a.txt', 'aaaa')
    put('b.txt', 'bbbb')
    put('c.txt', 'cccc')
    const a = valueOf<Pull>(await call(ctx, 'tos_pull', { path: 'a.txt' })).items[0]!.local
    await sleep(5)
    const b = valueOf<Pull>(await call(ctx, 'tos_pull', { path: 'b.txt' })).items[0]!.local
    await sleep(5)
    writeFileSync(b, 'bbbb edited')
    const c = valueOf<Pull>(await call(ctx, 'tos_pull', { path: 'c.txt' }))
    expect(c.items[0]!.status).toBe('downloaded')
    expect(existsSync(a)).toBe(false)
    expect(readFileSync(b, 'utf8')).toBe('bbbb edited')
    expect(valueOf<Stat>(await call(ctx, 'tos_stat', { path: 'a.txt' })).localState).toBe('absent')
  })

  it('skips a file that does not fit when eviction is off', async () => {
    const { ctx, put } = await localSetup({ cacheMaxBytes: 6, eviction: 'none' })
    put('a.txt', 'aaaa')
    put('b.txt', 'bbbb')
    valueOf<Pull>(await call(ctx, 'tos_pull', { path: 'a.txt' }))
    const b = valueOf<Pull>(await call(ctx, 'tos_pull', { path: 'b.txt' }))
    expect(b.items[0]).toMatchObject({ status: 'cache-full' })
    expect(b.items[0]!.message).toContain('cacheMaxBytes')
  })
})

describe('tos_push', () => {
  it('uploads a mirror file back to its own path and verifies it', async () => {
    const { ctx, bucket, put } = await localSetup()
    const rel = `${PROJECT}/成果/报告.docx`
    put(rel, 'draft')
    const local = valueOf<Pull>(await call(ctx, 'tos_pull', { path: rel })).items[0]!.local
    writeFileSync(local, 'final report')
    const pushed = valueOf<Push>(await call(ctx, 'tos_push', { local_path: local }))
    expect(pushed).toMatchObject({ path: rel, status: 'uploaded', verified: true, remoteChangedSincePull: false })
    expect(pushed.replaced).not.toBeNull()
    expect(readFileSync(join(bucket, '某咨询公司', ...rel.split('/')), 'utf8')).toBe('final report')
    expect(valueOf<Stat>(await call(ctx, 'tos_stat', { path: rel }))).toMatchObject({ localState: 'current', sha256: pushed.sha256 })
    expect(valueOf<Push>(await call(ctx, 'tos_push', { local_path: local })).status).toBe('unchanged')
  })

  it('uploads an outside file to a named target or directory', async () => {
    const { ctx, bucket } = await localSetup()
    const work = tempDir('work')
    cleanups.push(work.cleanup)
    const file = join(work.path, '核对 结果.xlsx')
    writeFileSync(file, 'xlsx')

    const needsTarget = await call(ctx, 'tos_push', { local_path: file })
    expect(text(needsTarget)).toContain('path')
    expect((await call(ctx, 'tos_push', { local_path: '相对/路径.xlsx', path: 'x' })).isError).toBe(true)

    const intoDir = valueOf<Push>(await call(ctx, 'tos_push', { local_path: file, path: `${PROJECT}/工作/2026-10-19-核对/` }))
    expect(intoDir).toMatchObject({ path: `${PROJECT}/工作/2026-10-19-核对/核对 结果.xlsx`, replaced: null })
    expect(existsSync(join(bucket, '某咨询公司', ...intoDir.path.split('/')))).toBe(true)

    const named = valueOf<Push>(await call(ctx, 'tos_push', { local_path: file, path: `${PROJECT}/成果/核对.xlsx` }))
    expect(named.path).toBe(`${PROJECT}/成果/核对.xlsx`)
  })

  it('reports when someone else changed the object after this mirror pulled it', async () => {
    const { ctx, put } = await localSetup()
    const rel = `${PROJECT}/项目说明.md`
    put(rel, 'v1')
    const local = valueOf<Pull>(await call(ctx, 'tos_pull', { path: rel })).items[0]!.local
    put(rel, 'colleague edit')
    writeFileSync(local, 'my edit')
    const pushed = await call(ctx, 'tos_push', { local_path: local })
    expect(valueOf<Push>(pushed).remoteChangedSincePull).toBe(true)
    expect(text(pushed)).toContain('被别人改过')
  })

  it('refuses files over the push bound and directories', async () => {
    const { ctx, cache } = await localSetup({ maxPushBytes: 3 })
    const file = join(cache, 'big.txt')
    writeFileSync(file, 'four')
    expect(text(await call(ctx, 'tos_push', { local_path: file }))).toContain('超过单次上传上限')
    expect(text(await call(ctx, 'tos_push', { local_path: cache, path: 'x' }))).toContain('不是普通文件')
    expect(text(await call(ctx, 'tos_push', { local_path: join(cache, 'none.txt'), path: 'x' }))).toContain('本机没有文件')
  })

  it('deduplicates identical content already in the mirror', async () => {
    const { ctx, cache } = await localSetup()
    const file = join(cache, 'seed.txt')
    writeFileSync(file, 'same bytes')
    valueOf<Push>(await call(ctx, 'tos_push', { local_path: file, path: '甲/同一份.txt' }))
    valueOf<Push>(await call(ctx, 'tos_push', { local_path: file, path: '乙/同一份.txt' }))
    expect(valueOf<Pull>(await call(ctx, 'tos_pull', { path: '甲/同一份.txt' })).items[0]!.status).toBe('downloaded')
    expect(valueOf<Pull>(await call(ctx, 'tos_pull', { path: '乙/同一份.txt' })).items[0]!.status).toBe('deduplicated')
  })
})

describe('TOS backend configuration', () => {
  it('asks for config_import while the connection is incomplete', async () => {
    const cache = tempDir('cache')
    cleanups.push(cache.cleanup)
    const ctx = await mount({ backend: 'tos', endpoint: 'tos-cn-beijing.volces.com', cacheRoot: cache.path })
    const result = await call(ctx, 'tos_ls', { path: '' })
    expect(result.isError).toBe(true)
    expect(text(result)).toContain('config_import')
    expect(text(result)).toContain('region')
  })

  it('asks for config_import while the access keys are missing, without contacting TOS', async () => {
    const cache = tempDir('cache')
    cleanups.push(cache.cleanup)
    const ctx = await mount({ backend: 'tos', endpoint: 'tos-cn-beijing.volces.com', region: 'cn-beijing', bucket: 'zt-test', cacheRoot: cache.path })
    const result = await call(ctx, 'tos_stat', { path: 'a.txt' })
    expect(text(result)).toContain('凭据存储里没有 TOS 访问密钥')
    const uri = await call(ctx, 'tos_ls', { path: 'tos://other-bucket/x/' })
    expect(text(uri)).toContain('不是当前配置的桶')
  })

  it('refuses a local backend without a root at load', async () => {
    const { ctx } = await toolContext()
    const fiber = ctx.plugin(ToolTos, { backend: 'local' })
    await expect(fiber).rejects.toThrow(/localRoot/u)
  })
})

describe('registration', () => {
  it('removes all four tools when the plugin is disposed', async () => {
    const { ctx } = await toolContext()
    const fiber = ctx.plugin(ToolTos, { backend: 'tos' })
    await fiber
    const names = () => ctx.tools.schemas().map(schema => schema.name).filter(name => name.startsWith('tos_'))
    expect(names().sort()).toEqual(['tos_ls', 'tos_pull', 'tos_push', 'tos_stat'])
    await fiber.dispose()
    expect(names()).toEqual([])
  })
})
