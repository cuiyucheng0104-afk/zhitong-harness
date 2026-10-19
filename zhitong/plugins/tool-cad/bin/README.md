# dwg2dxf 分发目录

插件按 `Config.dwg2dxfPath` → 环境变量 `DWG2DXF_BIN` → 本目录 `<platform>-<arch>/dwg2dxf[.exe]` → `PATH` 的顺序查找 LibreDWG `dwg2dxf`。本目录只提交说明与合规文本；二进制不进仓库（`.gitignore` 排除），由安装包构建流程放入。

| 子目录 | 来源 | 做法 |
|---|---|---|
| `win32-x64/` | 官方 `libredwg-0.14-win64.zip`，sha256 `1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8` | 解压 `dwg2dxf.exe` 与同目录 DLL |
| `darwin-arm64/`、`darwin-x64/` | 官方源码包 0.14 | 在对应架构的 macOS 上运行 `sh scripts/build-dwg2dxf.sh`（静态构建，不依赖 `libredwg.0.dylib`） |
| `linux-x64/`、`linux-arm64/` | 官方源码包 0.14 | 同上 |

每个子目录必须同时放：`dwg2dxf[.exe]`、`COPYING`（GPLv3 全文）、`VERSION.txt`（第一行是版本，`cad_open` 原样报告）、`SOURCE-OFFER.txt`（本目录同名文件的副本）。构建脚本自动生成这些文件。macOS 版本需与宿主应用一起签名和公证。
