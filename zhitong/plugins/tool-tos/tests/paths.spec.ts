import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { resolveSpec } from '../src/config.ts'
import { PathError, fromKey, mirrorPath, parseRemotePath, relFromMirror, toKey } from '../src/paths.ts'

describe('parseRemotePath', () => {
  const location = { bucket: 'zt-bucket', prefix: '某咨询公司' }

  it('normalizes separators and marks directories', () => {
    expect(parseRemotePath('项目\\2026-007-甲\\资料\\', location)).toEqual({ rel: '项目/2026-007-甲/资料', directory: true })
    expect(parseRemotePath('./项目//a.pdf', location)).toEqual({ rel: '项目/a.pdf', directory: false })
    expect(parseRemotePath('', location)).toEqual({ rel: '', directory: true })
  })

  it('accepts a tos:// URI only for the configured bucket and prefix', () => {
    expect(parseRemotePath('tos://zt-bucket/某咨询公司/项目/a.pdf', location)).toEqual({ rel: '项目/a.pdf', directory: false })
    expect(parseRemotePath('tos://zt-bucket/某咨询公司', location)).toEqual({ rel: '', directory: true })
    expect(() => parseRemotePath('tos://zt-bucket/别的公司/a.pdf', location)).toThrow(PathError)
    expect(() => parseRemotePath('tos://other/某咨询公司/a.pdf', location)).toThrow(PathError)
    expect(() => parseRemotePath('tos://zt-bucket/a.pdf', { prefix: '' })).toThrow(PathError)
  })

  it.each(['/abs', '\\abs', 'C:\\x', 'd:/x', 'a/../b', '..'])('refuses %s', (input) => {
    expect(() => parseRemotePath(input, location)).toThrow(PathError)
  })
})

describe('keys', () => {
  it('joins and strips the company prefix', () => {
    expect(toKey('公司', '项目/a.pdf', false)).toBe('公司/项目/a.pdf')
    expect(toKey('公司', '', true)).toBe('公司/')
    expect(toKey('', '', true)).toBe('')
    expect(fromKey('公司', '公司/项目/')).toBe('项目/')
    expect(fromKey('', '项目/a.pdf')).toBe('项目/a.pdf')
  })
})

describe('mirrorPath on POSIX and Windows', () => {
  it('maps a relative path under the root on both platforms', () => {
    expect(mirrorPath('/home/u/zhitong', '项目/a b/合同.pdf', path.posix)).toBe('/home/u/zhitong/项目/a b/合同.pdf')
    expect(mirrorPath('C:\\Users\\u\\zhitong', '项目/a b/合同.pdf', path.win32)).toBe('C:\\Users\\u\\zhitong\\项目\\a b\\合同.pdf')
  })

  it.each(['项目/a:b.pdf', '项目/CON', '项目/nul.txt', '项目/尾随点.', '项目/a?.pdf'])('refuses %s on Windows only', (rel) => {
    expect(() => mirrorPath('C:\\zt', rel, path.win32)).toThrow(PathError)
    expect(() => mirrorPath('/zt', rel, path.posix)).not.toThrow()
  })

  it('refuses the reserved state directory', () => {
    expect(() => mirrorPath('/zt', '.zhitong-cache/index.json', path.posix)).toThrow(PathError)
  })

  it('maps mirror files back to relative paths', () => {
    expect(relFromMirror('C:\\zt', 'C:\\zt\\项目\\a.pdf', path.win32)).toBe('项目/a.pdf')
    expect(relFromMirror('C:\\zt', 'D:\\other\\a.pdf', path.win32)).toBeUndefined()
    expect(relFromMirror('/zt', '/zt/项目/a.pdf', path.posix)).toBe('项目/a.pdf')
    expect(relFromMirror('/zt', '/elsewhere/a.pdf', path.posix)).toBeUndefined()
    expect(relFromMirror('/zt', '/zt/.zhitong-cache/index.json', path.posix)).toBeUndefined()
  })
})

describe('resolveSpec', () => {
  it('defaults the mirror to ~/zhitong and normalizes prefix and extensions', () => {
    const spec = resolveSpec({ prefix: '/公司/子/', noAutoPullExtensions: ['DWG', '.Zip'] })
    expect(spec.cacheRoot.endsWith(`${path.sep}zhitong`)).toBe(true)
    expect(spec.prefix).toBe('公司/子')
    expect([...spec.noAutoPullExtensions]).toEqual(['.dwg', '.zip'])
    expect(spec.connection).toEqual({ kind: 'unconfigured', missing: ['endpoint', 'region', 'bucket'] })
  })
})
