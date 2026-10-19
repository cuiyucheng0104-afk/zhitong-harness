import { randomUUID } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { credentialRef } from '@deepseek-ai/dsh-credentials'
import * as ToolTos from '../src/index.ts'
import { call, tempDir, toolContext, valueOf } from './support.ts'

// Real-bucket round trip. Runs only when every variable is set; never in CI by default.
const env = {
  endpoint: process.env['ZT_TOS_TEST_ENDPOINT'],
  region: process.env['ZT_TOS_TEST_REGION'],
  bucket: process.env['ZT_TOS_TEST_BUCKET'],
  prefix: process.env['ZT_TOS_TEST_PREFIX'],
  accessKeyId: process.env['ZT_TOS_TEST_ACCESS_KEY_ID'],
  secretAccessKey: process.env['ZT_TOS_TEST_SECRET_ACCESS_KEY'],
}
const live = Object.values(env).every(value => value !== undefined && value !== '')

describe.skipIf(!live)('tool-tos against a real TOS bucket', () => {
  it('pushes, lists, stats, and pulls one object', async () => {
    const cache = tempDir('live-cache')
    try {
      const { ctx, credentials } = await toolContext()
      await credentials!.set(credentialRef('ZT_TOS_ACCESS_KEY_ID'), env.accessKeyId!)
      await credentials!.set(credentialRef('ZT_TOS_SECRET_ACCESS_KEY'), env.secretAccessKey!)
      await ctx.plugin(ToolTos, {
        backend: 'tos', endpoint: env.endpoint!, region: env.region!, bucket: env.bucket!, prefix: env.prefix!, cacheRoot: cache.path,
      })
      const dir = `tool-tos-live/${randomUUID()}`
      const file = join(cache.path, '上传 测试.txt')
      writeFileSync(file, `智通数工AI ${dir}`)
      const pushed = valueOf<{ path: string; verified: boolean }>(await call(ctx, 'tos_push', { local_path: file, path: `${dir}/` }))
      expect(pushed.verified).toBe(true)
      const listing = valueOf<{ files: Array<{ path: string }> }>(await call(ctx, 'tos_ls', { path: `${dir}/` }))
      expect(listing.files.map(entry => entry.path)).toEqual([pushed.path])
      const pulled = valueOf<{ items: Array<{ status: string }> }>(await call(ctx, 'tos_pull', { path: pushed.path }))
      expect(pulled.items[0]!.status).toBe('downloaded')
    } finally {
      cache.cleanup()
    }
  }, 60_000)
})
