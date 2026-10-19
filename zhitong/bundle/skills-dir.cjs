'use strict'
/**
 * 智通数工AI skill 根目录，供 cordis.patch.yml 里 zhitong-skills 行的 `bundledSkillDir` 求值。
 *
 * - 打包布局：`pack-desktop.mjs` 把 zhitong/skills 复制进本包的 `skills/`（含 `_shared/`），优先用它；
 * - 仓库布局（`link:./zhitong/bundle` 装进 profile）：用本包旁边的 `../skills`。
 *
 * 结果位于 Electron 的 `app.asar` 内时换成 `app.asar.unpacked` 里的同名路径：skill 脚本由 Python 子进程运行，
 * 子进程读不了 asar；安装包用 asarUnpack 把 `@zhitong/bundle/skills/**` 解到 asar 外。
 */
const { existsSync } = require('node:fs')
const { join, resolve, sep } = require('node:path')

/**
 * Map a path inside an `app.asar` archive to its `app.asar.unpacked` twin when that twin exists.
 * @param {string} path - Absolute path.
 * @returns {string} The unpacked path, or `path` unchanged outside an archive or without an unpacked twin.
 */
function physicalPath(path) {
  const marker = `${sep}app.asar${sep}`
  const index = path.lastIndexOf(marker)
  if (index < 0) return path
  const unpacked = `${path.slice(0, index)}${sep}app.asar.unpacked${sep}${path.slice(index + marker.length)}`
  return existsSync(unpacked) ? unpacked : path
}

/**
 * Locate the skill root for a bundle package directory.
 * @param {string} [root] - Directory containing this package's package.json; defaults to this file's directory.
 * @returns {string} Absolute skill root.
 * @throws {Error} When neither layout has a `_shared` directory, so a missing skill tree fails at load.
 */
function skillsDir(root = __dirname) {
  for (const candidate of [join(root, 'skills'), resolve(root, '..', 'skills')]) {
    if (existsSync(join(candidate, '_shared'))) return physicalPath(candidate)
  }
  throw new Error(`@zhitong/bundle: 找不到 skill 目录（${join(root, 'skills')} 与 ${resolve(root, '..', 'skills')} 都没有 _shared/）`)
}

module.exports = { physicalPath, skillsDir }
