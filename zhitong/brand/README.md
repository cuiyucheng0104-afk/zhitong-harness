# 智通数工AI 品牌图形与应用图标

唯一来源是 `brand-mark.svg`：64 单位的圆角方块，蓝色渐变（`#00B3EC` → `#0666F5`），白色十字与四段绿色短划（`#12D99F`），整体旋转 −43°。它来自门户网站工程（`zhitong/portal/site/assets/brand-mark.svg`，两份内容相同），原工程资源说明写的是「依据用户提供的蓝绿 Logo 重绘的原型示意图标，正式发布前需品牌方确认」。品牌方确认或换稿后，替换本文件与门户那一份，再按下面的步骤重新生成。

## 生成

```sh
cd zhitong/scripts/brand-icons
npm ci
npm run render                                   # 写 zhitong/brand 与 zhitong/portal/site/public
cd ../../..
node zhitong/scripts/apply-brand-icons.mjs       # 复制进 apps/desktop/resources/zhitong-*
node zhitong/scripts/apply-brand-icons.mjs --check
```

`zhitong/scripts/brand-icons/` 是独立的 npm 项目（只依赖 `sharp`，有自己的 `package-lock.json`），不进 pnpm 工作区，不碰根 lockfile。

## 产物

| 文件 | 内容 |
|---|---|
| `icon-macos.svg` | macOS 1024 画布：按 Apple 图标网格，824 px 圆角方块居中（四边各留 100 px 透明边距），圆角半径 185.4 px，边距内带柔和投影 |
| `icon-windows.svg` | Windows 1024 画布：960 px 方块（四边 32 px），保持品牌图形自身的圆角比例（17/64），无投影 |
| `icons/icon-<n>.png` | Windows 版式的 PNG：16、32、48、64、128、256、512、1024 |
| `icons/icon-macos-1024.png` | macOS 版式 1024 PNG |
| `icons/icon.icns` | macOS 图标：16、32、64、128、256、512、1024（含 16@2x 至 512@2x），PNG 编码 |
| `icons/icon.ico` | Windows 图标：16、24、32、48、64、128、256；256 为 PNG，其余为 32 位 DIB（资源管理器、Electron 窗口图标与 NSIS 都能读） |
| `icons/tray.ico` | Windows 托盘：16、20、24、32、40、48、64（与上游 `render-tray-icon.ts` 的尺寸一致） |
| `../portal/site/public/favicon.svg`、`favicon.ico`（16/32/48）、`apple-touch-icon.png`（180，不透明满版方块，iOS 自己加圆角） | 门户网站图标 |

## W11 合入后要改的行

`apply-brand-icons.mjs` 只新增 `apps/desktop/resources/zhitong-*` 文件，上游的鲸鱼图标原样保留。要让安装包用上新图标，改下面这些引用（行号为 2026-10-20 工作树中的位置，以引号里的原文为准）：

`apps/desktop/scripts/electron-builder-config.mjs`

| 约第几行 | 原文 | 改为 |
|---|---|---|
| 160 | `{ from: fileURLToPath(new URL('../resources/icon-windows.png', import.meta.url)), to: 'icon.png' },` | `'../resources/zhitong-icon-windows.png'` |
| 162 | `...(packagesWindows ? [{ from: fileURLToPath(new URL('../resources/tray-windows.ico', import.meta.url)), to: 'tray.ico' }] : []),` | `'../resources/zhitong-tray-windows.ico'` |
| 165（`mac:` 下） | `icon: fileURLToPath(new URL('../resources/icon-macos.png', import.meta.url)),` | `'../resources/zhitong-icon.icns'` |
| 248（`win:` 下） | `icon: fileURLToPath(new URL('../resources/icon-windows.png', import.meta.url)),` | `'../resources/zhitong-icon.ico'` |

`apps/desktop/src/main.ts`（开发模式直接读 `resources/`，打包后读的是上面复制成的 `icon.png`、`tray.ico`，不用改）

| 约第几行 | 原文 | 改为 |
|---|---|---|
| 932 | `join(app.getAppPath(), 'resources', 'icon-windows.png')` | `'zhitong-icon-windows.png'` |
| 992 | `join(app.getAppPath(), 'resources', 'tray-windows.ico')` | `'zhitong-tray-windows.ico'` |

测试里同名的期望要一起改：

| 文件:约第几行 | 原文 | 改为 |
|---|---|---|
| `apps/desktop/tests/installer-packaging.spec.ts:42` | `new URL('../resources/icon-windows.png', import.meta.url)` | `'../resources/zhitong-icon-windows.png'` |
| `apps/desktop/tests/installer-packaging.spec.ts:46` | `new URL('../resources/tray-windows.ico', import.meta.url)` | `'../resources/zhitong-tray-windows.ico'` |
| `apps/desktop/tests/main-startup.spec.ts:550` | `join('desktop-test-app', 'resources', 'icon-windows.png')` | `'zhitong-icon-windows.png'` |

改完在 `apps/desktop` 跑 `pnpm vitest run tests/installer-packaging.spec.ts tests/main-startup.spec.ts`。

另一种做法是用新图标覆盖上游的 `icon-macos.png`、`icon-windows.png`、`tray-windows.ico`（用 `icons/icon-macos-1024.png`、`icons/icon-1024.png`、`icons/tray.ico`），配置与测试都不用改，代价是与上游合并时这三个二进制文件每次冲突，且 `pnpm run render:tray-icon` 会用上游 SVG 把托盘图标改回鲸鱼。

## 没有覆盖的品牌位置

- Windows 安装向导的横幅与侧栏：`apps/desktop/installer/assets/brand*.png`（600×196、1200×392，浅色与深色）是鲸鱼图标加「deepseek HARNESS」字标，`uninstaller-sidebar.png`（164×314）也是上游图稿；换成智通数工AI 需要设计稿。
- `apps/desktop/resources/icon.png`、`icon.svg` 是上游原始图稿，不参与打包。
