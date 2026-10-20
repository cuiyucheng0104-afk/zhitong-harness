// node --test zhitong/scripts/tests/：桌面打包脚本与 bundle 的 skill 目录定位。
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { after, describe, it } from 'node:test'
import { bareImports, dwg2dxfFiles, packageName, tarballFiles, tarballText, undeclaredImports } from '../pack-desktop.mjs'

const require = createRequire(import.meta.url)
const { physicalPath, skillsDir } = require('../../bundle/skills-dir.cjs')
const roots = []
after(() => { for (const root of roots) rmSync(root, { recursive: true, force: true }) })
function temp() {
  const root = mkdtempSync(join(tmpdir(), 'zt-pack-'))
  roots.push(root)
  return root
}

describe('pack-desktop import checks', () => {
  const bundled = [
    'import { readFileSync } from "node:fs";',
    'import z from "@deepseek-ai/schemastery";',
    'import { ShxFont } from "@mlightcad/shx-parser/dist/index.es.js";',
    'import "side-effect";',
    'export { x } from "@scope/re-export";',
    'const lazy = () => import("dxf-parser");',
    'import { local } from "./chunk.js";',
    'const text = "import nothing from \\"not-an-import\\"";',
  ].join('\n')

  it('lists bare package imports, not builtins, relative paths, or string contents', () => {
    assert.deepEqual(bareImports(bundled), [
      '@deepseek-ai/schemastery', '@mlightcad/shx-parser/dist/index.es.js', '@scope/re-export', 'dxf-parser', 'side-effect',
    ])
    assert.equal(packageName('@mlightcad/shx-parser/dist/index.es.js'), '@mlightcad/shx-parser')
    assert.equal(packageName('earcut'), 'earcut')
  })

  it('reports imports the manifest does not declare', () => {
    const manifest = {
      dependencies: { '@deepseek-ai/schemastery': '~3', '@mlightcad/shx-parser': '1', 'dxf-parser': '1' },
      peerDependencies: { '@scope/re-export': '1' },
    }
    assert.deepEqual(undeclaredImports(bundled, manifest), ['side-effect'])
  })

  it('names the converter and GPL files per target', () => {
    assert.deepEqual(dwg2dxfFiles('darwin', 'arm64'), [
      'bin/darwin-arm64/dwg2dxf', 'bin/darwin-arm64/COPYING', 'bin/darwin-arm64/VERSION.txt', 'bin/darwin-arm64/SOURCE-OFFER.txt',
    ])
    assert.equal(dwg2dxfFiles('win32', 'x64')[0], 'bin/win32-x64/dwg2dxf.exe')
  })
})

describe('pack-desktop tarball reading', () => {
  it('lists Chinese-named entries and reads one file without the system tar', () => {
    const root = temp()
    const template = join(root, 'package', 'skills', 'zt-report', 'data', 'docx-templates')
    mkdirSync(template, { recursive: true })
    writeFileSync(join(root, 'package', 'package.json'), '{"name":"@zhitong/bundle"}')
    writeFileSync(join(template, '咨询成果报告书（概算）.docx'), 'docx')
    writeFileSync(join(root, 'package', 'skills', 'zt-report', 'SKILL.md'), '---\nname: zt-report\n---\n中文正文')
    execFileSync('tar', ['-czf', 'bundle.tgz', 'package'], { cwd: root })
    const tarball = join(root, 'bundle.tgz')
    assert.deepEqual(tarballFiles(tarball).sort(), [
      'package.json', 'skills/zt-report/SKILL.md', 'skills/zt-report/data/docx-templates/咨询成果报告书（概算）.docx',
    ])
    assert.equal(tarballText(tarball, 'skills/zt-report/SKILL.md'), '---\nname: zt-report\n---\n中文正文')
    assert.throws(() => tarballText(tarball, 'missing.json'), /里没有 missing.json/u)
  })
})

describe('bundle skills-dir.cjs', () => {
  it('prefers the packed skills/ inside the bundle and maps app.asar to app.asar.unpacked', () => {
    const resources = temp()
    for (const archive of ['app.asar', 'app.asar.unpacked']) {
      mkdirSync(join(resources, archive, 'dsh', 'node_modules', '@zhitong', 'bundle', 'skills', '_shared'), { recursive: true })
    }
    const archived = join(resources, 'app.asar', 'dsh', 'node_modules', '@zhitong', 'bundle')
    assert.equal(skillsDir(archived), join(resources, 'app.asar.unpacked', 'dsh', 'node_modules', '@zhitong', 'bundle', 'skills'))
  })

  it('falls back to the repository layout beside the bundle', () => {
    assert.equal(skillsDir(resolve(import.meta.dirname, '..', '..', 'bundle')), resolve(import.meta.dirname, '..', '..', 'skills'))
  })

  it('fails loudly when no skill tree exists', () => {
    assert.throws(() => skillsDir(join(temp(), 'bundle')), /找不到 skill 目录/u)
  })

  it('keeps paths outside an archive or without an unpacked twin', () => {
    const root = temp()
    const archived = join(root, 'app.asar', 'x')
    writeFileSync(join(root, 'plain'), '')
    assert.equal(physicalPath(archived), archived)
    assert.equal(physicalPath(join(root, 'plain')), join(root, 'plain'))
  })
})
