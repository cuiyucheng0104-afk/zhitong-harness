# dwg2dxf 分发目录

插件按 `Config.dwg2dxfPath` → 环境变量 `DWG2DXF_BIN` → 本目录 `<platform>-<arch>/dwg2dxf[.exe]` → `PATH` 的顺序查找 LibreDWG `dwg2dxf`。本目录只提交说明与合规文本；二进制不进仓库（`.gitignore` 排除），由安装包构建流程放入。

| 子目录 | 来源 | 做法 |
|---|---|---|
| `win32-x64/` | 官方 `libredwg-0.14-win64.zip`，sha256 `1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8` | 运行 `scripts/fetch-dwg2dxf-win64.ps1`：校验 sha256，复制 `dwg2dxf.exe` 与 zip 根目录的 DLL（`libredwg-0.dll`、`libiconv-2.dll`、`libpcre2-*.dll`） |
| `darwin-arm64/`、`darwin-x64/` | 官方源码包 0.14 | 在对应架构的 macOS 上运行 `sh scripts/build-dwg2dxf.sh`（静态链接 libredwg；脚本用 `otool -L` 拒绝 Homebrew 等非系统动态库，并做 ad-hoc 签名） |
| `linux-x64/`、`linux-arm64/` | 官方源码包 0.14 | 同上 |

每个子目录必须同时放：`dwg2dxf[.exe]`、`COPYING`（GPLv3 全文，本目录 `COPYING` 是 0.14 源码包里的同一文件）、`VERSION.txt`（第一行是版本，`cad_open` 原样报告）、`SOURCE-OFFER.txt`（本目录同名文件的副本）。两个脚本都会生成这些文件。

桌面安装包（`zhitong/scripts/pack-desktop.mjs`）只要求目标平台的子目录齐全，缺了就停止打包（`ZT_ALLOW_MISSING_DWG2DXF=1` 才放行，安装后只能打开 DXF）；本目录随插件进入 `app.asar/dsh/node_modules/@zhitong/tool-cad/bin/`，并由 asarUnpack 解到 `app.asar.unpacked/` 下，插件按 asar 外的路径启动它。未签名的本机测试包里它保留构建时的 ad-hoc 签名；正式发布由上游签名流程对 dsh 树里的所有 Mach-O 统一签名与公证。
