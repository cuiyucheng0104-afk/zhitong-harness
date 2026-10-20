# 安装

本文四部分：一、开发者在本仓从源码启动 `zhitong` profile；二、在 Apple Silicon Mac 上从源码打出 DMG 并安装；三、在 Windows x64 上打出安装程序并安装；四、首次运行与验收清单（两个平台共用）。打包改动了哪些上游文件见 [STATUS.md](STATUS.md) 的「W9 上游改动」。

## 一、开发者：从源码启动 zhitong profile

### 1. 前置

- Node `^22.19` 或 `>=24`；pnpm 11（`corepack enable` 后用仓库 `packageManager` 指定的版本）。
- [uv](https://docs.astral.sh/uv/)；Python ≥ 3.11（本机已有即可，uv 也可自行下载）。
- DeepSeek API key（`DEEPSEEK_API_KEY`，或启动后在设置页填写）。

### 2. 安装依赖并构建

在仓库根目录：

```sh
pnpm install
pnpm run build
```

`pnpm-workspace.yaml` 已包含 `zhitong/bundle` 与 `zhitong/plugins/*`，一次 `pnpm install` 同时链接两个插件与 bundle。源码启动 Web 需要 `pnpm run build` 产出的前端与 Host 产物。

> 网络受限的环境里，`cdn.sheetjs.com` 不可达会让整仓 `pnpm install` 失败（`packages/client/ui-sidebar-documentpreview` 依赖它的 xlsx 包）。只跑 zhitong 插件测试时可用 `pnpm install --frozen-lockfile --filter '!@deepseek-ai/dsh-client-ui-sidebar-documentpreview'`；启动 Web 仍需要完整安装。

### 3. Python 运行时

```sh
cd zhitong/python
uv sync
uv run pytest
```

skill 脚本（`skills/<名>/scripts/*.py`）开头经 `skills/_shared/zt_launch.py` 选解释器：`ZT_PYTHON` → 桌面版 primary runtime（`~/.dsh/dsh-runtimes/dsh-primary-runtime`）→ 当前解释器；`zt` 从 skills 旁的 `python/` 加入 `sys.path`。开发时启动 harness 前把 `ZT_PYTHON` 指向这个虚拟环境的解释器：

- macOS / Linux：`export ZT_PYTHON="$PWD/.venv/bin/python"`
- Windows（PowerShell）：`$env:ZT_PYTHON = "$PWD\.venv\Scripts\python.exe"`

也可以写进启动目录（仓库根目录）的 `.env` 或 `~/.dsh/.env`（`ZT_PYTHON=/绝对路径/…`），`dsh` 启动时把两者作为环境层读入；`.env` 不要提交。

### 4. 建 zhitong profile 并装入 bundle

`zhitong` profile 以 Web 模板为底，再叠加 `@zhitong/bundle`。在仓库根目录：

```sh
# 以 web 模板新建（或重置）名为 zhitong 的 profile；--dump-config 只打印配置、不启动
pnpm dsh --profile zhitong --from-default-profile web --dump-config > /dev/null

# 以 link: 方式把 bundle 装进 profile（路径相对当前目录解析为绝对路径）
pnpm dsh plugin --profile zhitong add link:./zhitong/bundle

# 确认 bundle 层已生效：输出里应有 "# == @zhitong/bundle" 段与 zhitong-tool-tos、preset-zhitong 行
pnpm dsh --profile zhitong --dump-config | grep -n "zhitong"
```

`--from-default-profile` 会删除同名 profile 已安装的依赖与用户 patch，只在首次创建或需要重置时运行。profile 位于 `$DSH_HOME/profiles/zhitong`（默认 `~/.dsh/profiles/zhitong`）。

bundle 做了这些事（详见 `zhitong/bundle/cordis.patch.yml`）：

- 挂 `zhitong-tool-tos`（`tos_ls`/`tos_stat`/`tos_pull`/`tos_push`）与 `zhitong-config-import`（`config_import`）。
- 挂只读 `zhitong/skills` 的 skill 目录（provider 名 `zhitong`）。
- 新增默认预设「智通数工AI」（`preset-zhitong`），系统提示词使用造价人设；沙箱沿用 `workspace-write + ask`。

开发 profile 里插件以源码（`src/index.ts`）入口运行，依赖源码启动的 tsx 加载器。安装包用的是 `pnpm --dir zhitong/plugins/<插件> run build`（tsdown）产出的 `lib/index.js`，由打包流程自动构建（见第二部分）。

### 5. 启动

```sh
ZT_PYTHON="$PWD/zhitong/python/.venv/bin/python" pnpm dsh --profile zhitong
```

浏览器打开后：

1. 新会话默认使用「智通数工AI」预设。
2. 把公司配置包（格式见 [CONFIG-PACKAGE.md](CONFIG-PACKAGE.md)）拖进对话，或告诉 agent 它的本机路径；agent 调用 `config_import`，密钥进本机凭据存储，桶设置写进 `~/.dsh/profiles/zhitong/cordis.patch.yml`。
3. 让 agent 列出 `项目/`，打开样例项目。

没有真实桶时，可让 TOS 工具读本机目录（目录结构与桶内公司前缀以下相同）。在 `~/.dsh/profiles/zhitong/cordis.patch.yml` 追加：

```yaml
- id: zhitong-tool-tos
  config:
    backend: local
    localRoot: /绝对路径/样例桶
```

### 6. 测试

```sh
cd zhitong/plugins/tool-tos && pnpm vitest run && pnpm run typecheck
cd zhitong/plugins/config-import && pnpm vitest run && pnpm run typecheck
cd zhitong/python && uv run pytest
node --test zhitong/scripts/tests/*.test.mjs   # 在仓库根目录：打包脚本与 skill 目录定位
```

`pnpm run typecheck` 依赖上游各包的声明产物（`pnpm run build:artifacts` 生成的 `lib/types`）。连真桶的往返测试 `tool-tos/tests/tos-live.spec.ts` 只在设置了 `ZT_TOS_TEST_ENDPOINT`、`ZT_TOS_TEST_REGION`、`ZT_TOS_TEST_BUCKET`、`ZT_TOS_TEST_PREFIX`、`ZT_TOS_TEST_ACCESS_KEY_ID`、`ZT_TOS_TEST_SECRET_ACCESS_KEY` 时运行，测试对象写在 `<前缀>/tool-tos-live/<随机>/` 下。

## 二、Mac（Apple Silicon）：从源码打出 DMG 并安装

上游只支持在对应平台上打包：arm64 DMG 必须在 Apple Silicon Mac 上构建，Linux 不能打桌面包。下面是在一台 Mac 上从零到打开应用的完整步骤；未签名的本机测试包不需要 Apple 开发者账号、证书或 `.env.macos`。

### 1. 前置

| 需要 | 安装方式 | 用途 |
|---|---|---|
| Xcode 命令行工具 | `xcode-select --install` | git、clang、make、strip、codesign、otool；编译 dwg2dxf 与原生模块 |
| Node 24（或 `^22.19`） | [nodejs.org](https://nodejs.org) 的 macOS 安装包，或 `brew install node@24` 后按提示把它加进 `PATH` | 构建与打包脚本 |
| pnpm 11.28.5 | `corepack enable`，然后在仓库根目录执行任何 `pnpm` 命令时自动取 `packageManager` 指定的版本 | 依赖安装与打包 |
| uv（可选） | `brew install uv` 或 `curl -LsSf https://astral.sh/uv/install.sh \| sh` | 只用于跑 `zhitong/python` 的测试；打包不需要 |
| Homebrew（可选） | [brew.sh](https://brew.sh) | 只用来装上面的 Node / uv；打包本身不需要任何 brew 包 |

- **不需要 autotools**：dwg2dxf 用 LibreDWG 0.14 的官方发布包构建，包里已有生成好的 `./configure`。只有改成从 LibreDWG 的 git 源码构建时才需要 `brew install autoconf automake libtool pkg-config texinfo`。
- Homebrew 装过 `pcre2`、`libiconv` 等库也没关系：构建脚本会用 `otool -L` 检查，产物只能链接 `/usr/lib` 与 `/System` 下的系统库，否则直接报错。
- 网络：需要能访问 github.com（Electron、python-build-standalone、LibreDWG 发布包）、registry.npmjs.org、nodejs.org、files.pythonhosted.org。公司网络要走代理时按常规设置 `HTTPS_PROXY`；npm 镜像可设 `DSH_DESKTOP_NPM_REGISTRY=https://registry.npmmirror.com`。
- 磁盘：仓库、依赖与打包中间产物合计约 10 GB。

### 2. 取源码并安装依赖

```sh
git clone https://github.com/cuiyucheng0104-afk/zhitong-harness.git
cd zhitong-harness
git checkout claude/quirky-gates-woud76
corepack enable
pnpm install --frozen-lockfile
```

### 3. 构建 dwg2dxf

```sh
sh zhitong/plugins/tool-cad/scripts/build-dwg2dxf.sh "$HOME/.cache/zhitong/dwg2dxf-build"
```

构建目录必须是不含空格与非 ASCII 字符的路径（automake 会拒绝，macOS 的临时目录也触发过这个错误），所以显式传一个。命令块里不要带 `#` 注释：zsh 交互式 shell 默认不识别行内注释，会把 `#` 之后的词当参数传给命令。

脚本下载 LibreDWG 0.14 源码包（sha256 钉死），静态链接 libredwg 编出 `dwg2dxf`，检查只链接系统库，strip 后做 ad-hoc 签名，装到 `zhitong/plugins/tool-cad/bin/darwin-arm64/`，同目录生成 `COPYING`（GPLv3）、`VERSION.txt`、`SOURCE-OFFER.txt`。耗时几分钟。验证：

```sh
ls zhitong/plugins/tool-cad/bin/darwin-arm64/   # COPYING  SOURCE-OFFER.txt  VERSION.txt  dwg2dxf
zhitong/plugins/tool-cad/bin/darwin-arm64/dwg2dxf --version
```

这个目录被 `.gitignore` 排除，不会提交。缺了它打包会停下并提示；确实只要 DXF 时可以 `export ZT_ALLOW_MISSING_DWG2DXF=1` 放行。

### 4. 打包

```sh
pnpm run package:desktop:mac:arm64:unsigned --check
pnpm run package:desktop:mac:arm64:unsigned
```

第二条命令一次做完：构建整个仓库 → 打包 dsh 与 vendor 的 npm 包 → `zhitong/scripts/pack-desktop.mjs` 构建三个插件的 `lib/index.js`、把 `zhitong/skills` 与 `zhitong/python/zt` 放进 `@zhitong/bundle` 并打包、检查 tarball 内容 → 下载并组装内置运行时（Python 3.12 带 numpy、pandas、openpyxl、python-docx、pypdf、PyYAML、pydantic 等，Node、pnpm）→ 安装 `app.asar/dsh` 生产依赖树（含 `@zhitong/*`）→ 用新 profile（Web 模板 + `@zhitong/bundle`）启动一次 Host 做冒烟 → electron-builder 出 DMG 并对装好的应用再冒烟一次。首次运行要下载 Electron 与各运行时，约 20–40 分钟。

成功时最后一行是：

```text
DMG: /…/zhitong-harness/apps/desktop/.desktop-build/targets/mac-arm64/unsigned-artifacts/deepseek-harness-0.2.1-rc.2-mac-arm64-unsigned.dmg
```

每次运行开头会打印 `DESKTOP_PACKAGING_RECORD <目录>`，失败时看该目录下的 `events.jsonl`、`stderr.log`。常见失败：

| 现象 | 处理 |
|---|---|
| `pack-desktop: tool-cad 缺少 bin/darwin-arm64/dwg2dxf…` | 先做第 3 步 |
| pnpm 报某个依赖的 build script 未批准 | 把包名告诉维护者，加进 `apps/desktop/src/project-manager.ts` 的 `allowBuilds` |
| 下载超时 | 设代理或 `DSH_DESKTOP_NPM_REGISTRY` 后重跑；已下载的归档有缓存 |

### 5. 安装与第一次打开

1. 双击 DMG，把「DeepSeek Harness」拖进「应用程序」（应用名沿用上游，打开后默认预设是「智通数工AI」）。
2. 第一次打开：在「应用程序」里**右键 → 打开 → 打开**。本机构建的包没有隔离属性，多数情况下直接双击也能开；若提示「无法验证开发者」，到「系统设置 → 隐私与安全性」底部点「仍要打开」。把 DMG 拷到别的 Mac 上安装时如果提示「已损坏」，在终端执行 `xattr -dr com.apple.quarantine "/Applications/DeepSeek Harness.app"` 后再右键打开。
3. 可选的离线自检（不启动应用）：

   ```sh
   node zhitong/scripts/verify-desktop-app.mjs "/Applications/DeepSeek Harness.app"
   ```

   逐项检查：运行时描述里有四个 `@zhitong/*` 包、12 个 skill 与 `python/zt` 在 asar 外、内置 Python 能导入 zt 的依赖并以 `--help` 跑通每个 skill 脚本、`dwg2dxf` 可执行且带 GPL 文件。最后一行应为「全部 20 项通过」。

然后按第四部分做首次运行与验收。

## 三、Windows x64：打出安装程序并安装

在 Windows 10/11 x64 上构建（上游不支持交叉打包）。以下命令在 PowerShell 里执行。

### 1. 前置

- Node 24（[nodejs.org](https://nodejs.org) 的 x64 msi）；`corepack enable`。
- Git for Windows、PowerShell 5.1 或 7、系统自带的 `tar`。
- Python 3（`PATH` 里没有时设 `PYTHON` 环境变量）、Visual C++ Build Tools 与 Windows SDK：上游打包用来编译原生模块（见 `apps/desktop/packaging/README.md`「Unsigned Windows test installer」）。
- 网络要求同 Mac。

### 2. 取源码、依赖与 dwg2dxf

```powershell
git clone https://github.com/cuiyucheng0104-afk/zhitong-harness.git
cd zhitong-harness
git checkout claude/quirky-gates-woud76
pnpm install --frozen-lockfile
powershell -NoProfile -ExecutionPolicy Bypass -File zhitong\plugins\tool-cad\scripts\fetch-dwg2dxf-win64.ps1
```

最后一条下载 LibreDWG 官方 `libredwg-0.14-win64.zip`（sha256 钉死），把 `dwg2dxf.exe` 与 zip 根目录的 DLL（`libredwg-0.dll`、`libiconv-2.dll`、`libpcre2-*.dll`）装进 `zhitong\plugins\tool-cad\bin\win32-x64\`，并放上 `COPYING`、`SOURCE-OFFER.txt`、`VERSION.txt`。

### 3. 本机打包配置

未签名的 Windows 包仍要求应用 ID 与强制更新策略的服务地址。复制模板并改成下面几行（其余行可以删掉或留空）：

```powershell
Copy-Item apps\desktop\.env.windows.example apps\desktop\.env.windows
notepad apps\desktop\.env.windows
```

```dotenv
DSH_DESKTOP_APP_ID=com.deepseek.harness
DSH_DESKTOP_AUTO_UPDATE_ENV=production
DSH_DESKTOP_MANDATORY_UPDATE_PROD_ORIGIN=https://update.invalid
```

`production` 不能带 `DSH_DESKTOP_MANDATORY_UPDATE_CONFIG` 里的 `allowedAuthOrigins`，把模板里那一行删掉。`update.invalid` 是不存在的地址：应用定期查询会失败，失败不会阻塞使用；以后有了真实的更新服务再换成它的 HTTPS 地址。`.env.windows` 被 Git 忽略。

### 4. 打包与安装

```powershell
pnpm run package:desktop:win:x64:unsigned --check
pnpm run package:desktop:win:x64:unsigned
```

产物：`apps\desktop\.desktop-build\targets\win-x64\unsigned-artifacts\deepseek-harness-0.2.1-rc.2-win-x64-unsigned.exe`。运行它安装到当前用户；SmartScreen 拦截时点「更多信息 → 仍要运行」。安装后可做离线自检（路径换成实际安装目录）：

```powershell
node zhitong\scripts\verify-desktop-app.mjs "$env:LOCALAPPDATA\Programs\DeepSeek Harness"
```

Windows 用户名含中文时，`%USERPROFILE%\.dsh` 与 `%TEMP%` 都在中文路径下：官方 win64 的 dwg2dxf 用 ANSI `fopen`，tool-cad 已把输入拷成 ASCII 文件名，但临时目录本身仍在 `%TEMP%`；遇到 DWG 打不开时，先把用户环境变量 `TEMP`、`TMP` 改到纯英文路径（如 `C:\Temp`）再重启应用。

## 四、首次运行与验收清单

### 1. 首次运行

1. 欢迎窗口里填 DeepSeek API key（或「稍后设置」，之后在设置页填）。
2. 进入工作区后新建会话，确认预设是「智通数工AI」。
3. 导入公司配置包：把 `zhitong.config.json` 或含它的 `.zip`（格式见 [CONFIG-PACKAGE.md](CONFIG-PACKAGE.md)）拖进对话，或告诉 agent 它的本机路径；agent 调用 `config_import`。TOS 密钥进本机凭据存储，桶设置写进桌面 profile 的 `~/.dsh/profiles/desktop/cordis.patch.yml`，配置包里的 SSH 主机写进 `~/.ssh/config` 开头的受管块，火山 ve profile 名写进 `~/.dsh/zhitong/volc.config.json`。用 zt-volc 前在终端里按 CONFIG-PACKAGE.md「火山引擎 ve profile」建好 `ve` 的 profile。
4. 没有真实桶时让 TOS 工具读本机目录：完全退出应用，在 `~/.dsh/profiles/desktop/cordis.patch.yml`（Windows `%USERPROFILE%\.dsh\profiles\desktop\cordis.patch.yml`）追加下面几行再打开应用：

   ```yaml
   - id: zhitong-tool-tos
     config:
       backend: local
       localRoot: /绝对路径/样例桶
   ```

5. 让 agent 列出 `项目/`，打开样例项目。

桌面版使用的 profile 名是 `desktop`（不是第一部分开发用的 `zhitong`）。如果这台机器以前装过上游 DeepSeek Harness 桌面版，`~/.dsh/profiles/desktop` 已经存在，新版本不会改它的 bundle 列表：在完全退出应用后把旧的 `~/.dsh/profiles/desktop` 改名（例如加后缀 `.bak`），再打开应用让它按新模板重建 profile；旧 profile 里装过的第三方插件需要重新安装。

### 2. 验收清单

| 检查 | 期望 |
|---|---|
| 新会话的预设 | 「智通数工AI」（预设列表第一个，造价人设） |
| 默认模型 | DeepSeek-V4.1-Flash（`deepseek-official` / `deepseek-flash`；设置页另选的模型优先） |
| 问 agent「列出可用的 skill」，或看 `skill` 工具的目录 | 12 个：zt-project、zt-ask、zt-archive、zt-reconcile、zt-indicator、zt-tk、zt-report、zt-quantity、zt-estimate、zt-knowledge、zt-volc、zt-cad；没有 `_shared` |
| 工具 | `tos_ls`、`tos_stat`、`tos_pull`、`tos_push`、`config_import`、`cad_open` 等 10 个 `cad_*`，以及上游的 `load_workspace_dependencies` |
| Python | 让 agent 跑任一 skill 脚本（例如「用 zt-tk 看一下帮助」）：它先调 `load_workspace_dependencies` 取 `python`，再运行 `<python> <skill 目录>/scripts/tk.py --help`，输出子命令列表；不应出现 `zt_not_importable` |
| 看图 | 给一张 DWG 让 agent `cad_open`：结果里转换器版本是 `LibreDWG dwg2dxf 0.14`；DXF 不需要转换器 |
| 配置包 | `config_import` 的结果列出凭据引用名、桶地址；有 ssh / volc 段时列出写入的文件，且不含任何密钥 |
| 离线自检 | `node zhitong/scripts/verify-desktop-app.mjs <应用路径>` 全部通过 |
