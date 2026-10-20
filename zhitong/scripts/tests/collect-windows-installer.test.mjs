// node --test zhitong/scripts/tests/：Windows 安装包改名与校验文件（.github/workflows/zhitong-windows-installer.yml 调用）。
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, describe, it } from 'node:test'
import { collectWindowsInstaller, installerFileName, locateWindowsArtifacts } from '../collect-windows-installer.mjs'

const roots = []
after(() => { for (const root of roots) rmSync(root, { recursive: true, force: true }) })
function artifactsDir(files) {
  const root = mkdtempSync(join(tmpdir(), 'zt-collect-'))
  roots.push(root)
  const artifacts = join(root, 'unsigned-artifacts')
  mkdirSync(join(artifacts, 'win-unpacked', 'resources', 'app.asar.unpacked'), { recursive: true })
  for (const [name, body] of Object.entries(files)) writeFileSync(join(artifacts, name), body)
  return { root, artifacts }
}

describe('collect-windows-installer', () => {
  it('names the installer after the distribution version', () => {
    assert.equal(installerFileName('1.0.0'), 'ztsgai-1.0.0-win-x64-setup.exe')
    assert.equal(installerFileName('1.0.1-rc.1'), 'ztsgai-1.0.1-rc.1-win-x64-setup.exe')
    for (const bad of ['v1.0.0', '1.0', '1.0.0+build.1', '01.0.0', '1.0.0/../x', '']) {
      assert.throws(() => installerFileName(bad), /must look like/u, bad)
    }
  })

  it('copies the single installer and writes a shasum-format checksum', async () => {
    const body = 'installer bytes'
    const { root, artifacts } = artifactsDir({
      'deepseek-harness-0.2.1-rc.2-win-x64-unsigned.exe': body,
      '__uninstaller-nsis-dsh-desktop.exe': 'helper',
      'deepseek-harness-0.2.1-rc.2-win-x64-unsigned.exe.blockmap': 'map',
    })
    const out = join(root, 'dist')
    const result = await collectWindowsInstaller({ version: '1.0.0', artifacts, out })
    const hash = createHash('sha256').update(body).digest('hex')
    assert.equal(result.installer, join(out, 'ztsgai-1.0.0-win-x64-setup.exe'))
    assert.equal(readFileSync(result.installer, 'utf8'), body)
    assert.equal(result.hash, hash)
    assert.equal(readFileSync(result.sha256, 'utf8'), `${hash}  ztsgai-1.0.0-win-x64-setup.exe\n`)
    assert.equal(result.source, 'deepseek-harness-0.2.1-rc.2-win-x64-unsigned.exe')
    assert.equal(result.unpacked, join(artifacts, 'win-unpacked'))
  })

  it('refuses zero or several installers and a missing unpacked application', () => {
    assert.throws(() => locateWindowsArtifacts(artifactsDir({}).artifacts), /found 0/u)
    assert.throws(() => locateWindowsArtifacts(artifactsDir({ 'a.exe': '1', 'b.exe': '2' }).artifacts), /found 2/u)
    const { artifacts } = artifactsDir({ 'a.exe': '1' })
    rmSync(join(artifacts, 'win-unpacked'), { recursive: true })
    assert.throws(() => locateWindowsArtifacts(artifacts), /app\.asar\.unpacked/u)
    assert.throws(() => locateWindowsArtifacts(join(artifacts, 'missing')), /does not exist/u)
  })
})
