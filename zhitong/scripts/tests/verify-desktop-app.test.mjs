// node --test zhitong/scripts/tests/：安装后自检脚本对应用名与品牌客户端包的判断（W11）。
import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, describe, it } from 'node:test'
import { applicationExecutable, asarHasFile, readAsarFile, resourcesDirectory } from '../verify-desktop-app.mjs'

const roots = []
after(() => { for (const root of roots) rmSync(root, { recursive: true, force: true }) })
function temp() {
  const root = mkdtempSync(join(tmpdir(), 'zt-verify-'))
  roots.push(root)
  return root
}

/** Minimal asar archive: Pickle header (sizes + JSON) followed by the packed file bytes. */
function writeAsar(path, files) {
  const tree = { files: {} }
  const contents = []
  let offset = 0
  for (const [name, text] of Object.entries(files)) {
    const parts = name.split('/')
    let node = tree
    for (const part of parts.slice(0, -1)) node = node.files[part] ??= { files: {} }
    const bytes = Buffer.from(text)
    node.files[parts.at(-1)] = { size: bytes.length, offset: String(offset) }
    contents.push(bytes)
    offset += bytes.length
  }
  const json = Buffer.from(JSON.stringify(tree))
  const padded = Math.ceil(json.length / 4) * 4
  const header = Buffer.alloc(16 + padded)
  header.writeUInt32LE(4, 0)
  header.writeUInt32LE(8 + padded, 4)
  header.writeUInt32LE(4 + padded, 8)
  header.writeUInt32LE(json.length, 12)
  json.copy(header, 16)
  writeFileSync(path, Buffer.concat([header, ...contents]))
}

describe('verify-desktop-app brand checks', () => {
  it('finds the 智通数工AI executable beside a macOS or Windows resources directory', () => {
    const mac = join(temp(), '智通数工AI.app')
    mkdirSync(join(mac, 'Contents', 'Resources', 'app.asar.unpacked'), { recursive: true })
    mkdirSync(join(mac, 'Contents', 'MacOS'), { recursive: true })
    const macResources = resourcesDirectory(mac)
    assert.equal(applicationExecutable(macResources), join(mac, 'Contents', 'MacOS', '智通数工AI'))

    const windows = join(temp(), 'ztsgai')
    mkdirSync(join(windows, 'resources', 'app.asar.unpacked'), { recursive: true })
    assert.equal(applicationExecutable(resourcesDirectory(windows)), join(windows, 'ztsgai.exe'))
  })

  it('reports whether app.asar carries the brand client bundle', () => {
    const archive = join(temp(), 'app.asar')
    writeAsar(archive, {
      'dsh/desktop-runtime.json': '{"sharedPackages":[]}',
      'dsh/node_modules/@zhitong/ui-brand/lib/client.js': 'window.__ModuleLoader__.load({})',
    })
    assert.equal(asarHasFile(archive, 'dsh/node_modules/@zhitong/ui-brand/lib/client.js'), true)
    assert.equal(asarHasFile(archive, 'dsh/node_modules/@zhitong/ui-brand/lib'), false)
    assert.equal(asarHasFile(archive, 'dsh/node_modules/@zhitong/tool-tos/lib/index.js'), false)
    assert.deepEqual(readAsarFile(archive, 'dsh/desktop-runtime.json'), { sharedPackages: [] })
  })
})
