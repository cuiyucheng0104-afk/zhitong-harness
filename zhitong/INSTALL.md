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
pnpm --dir zhitong/plugins/ui-brand run build
```

`pnpm-workspace.yaml` 已包含 `zhitong/bundle` 与 `zhitong/plugins/*`，一次 `pnpm install` 同时链接各插件与 bundle。源码启动 Web 需要 `pnpm run build` 产出的前端与 Host 产物。品牌插件 `@zhitong/ui-brand` 是 Web 客户端插件，浏览器加载的是它构建出的 `lib/client.js`（根目录的 `pnpm run build` 不构建 `zhitong/`），所以第三条命令不能省；改了它的源码要重跑。

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
- 品牌：禁用上游 `ui-brand-official`，由 `zhitong-ui-brand` 在侧栏与新会话页显示品牌图形（内联 SVG，蓝色渐变圆角方块）与「智通数工AI」字标，模型选择器里 `deepseek-flash` 显示为「DeepSeek V4.1 Flash 官方推荐」；禁用 `ui-settings-account`（没有 DeepSeek 账号登录、账号菜单与充值页），首次运行直接弹出模型 API Key 表单。
- 模型：禁用账号路由 `llm-deepseek-account`，只留 API Key 路由 `deepseek-official`；默认模型由 `zhitong-default-model` 行持有（`deepseek-official` / `deepseek-flash`），上游 `agent-default-model` 行禁用，旧安装留在用户层的默认模型（例如账号登录后写入的 `deepseek-account`）因此不再生效。

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

1. 双击 DMG，把「智通数工AI」拖进「应用程序」（DMG 文件名仍是 `deepseek-harness-…`，见 [STATUS.md](STATUS.md)「W11 上游改动」）。
2. 第一次打开：在「应用程序」里**右键 → 打开 → 打开**。本机构建的包没有隔离属性，多数情况下直接双击也能开；若提示「无法验证开发者」，到「系统设置 → 隐私与安全性」底部点「仍要打开」。把 DMG 拷到别的 Mac 上安装时如果提示「已损坏」，在终端执行 `xattr -dr com.apple.quarantine "/Applications/智通数工AI.app"` 后再右键打开。
3. 可选的离线自检（不启动应用）：

   ```sh
   node zhitong/scripts/verify-desktop-app.mjs "/Applications/智通数工AI.app"
   ```

   逐项检查：运行时描述里有五个 `@zhitong/*` 包、应用可执行文件名是「智通数工AI」且 `app.asar` 里有品牌插件的 `lib/client.js`、12 个 skill 与 `python/zt` 在 asar 外、内置 Python 能导入 zt 的依赖并以 `--help` 跑通每个 skill 脚本、`dwg2dxf` 可执行且带 GPL 文件。最后一行应为「全部 21 项通过」。

然后按第四部分做首次运行与验收。

日常发布（本机打 Mac 包、Actions 打 Windows 包、登记并部署到门户）用一条命令完成，见 [RELEASE.md](RELEASE.md)。

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
DSH_DESKTOP_APP_ID=com.ztsgai.harness
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
node zhitong\scripts\verify-desktop-app.mjs "$env:LOCALAPPDATA\Programs\ztsgai"
```

Windows 用户名含中文时，`%USERPROFILE%\.dsh` 与 `%TEMP%` 都在中文路径下：官方 win64 的 dwg2dxf 用 ANSI `fopen`，tool-cad 已把输入拷成 ASCII 文件名，但临时目录本身仍在 `%TEMP%`；遇到 DWG 打不开时，先把用户环境变量 `TEMP`、`TMP` 改到纯英文路径（如 `C:\Temp`）再重启应用。

### 5. 用 GitHub Actions 打包

没有 Windows 构建机时，用仓库里的 `zhitong · Windows installer` workflow（`.github/workflows/zhitong-windows-installer.yml`）在 GitHub 托管的 `windows-latest` 上打同样的未签名安装包。它按上面 1–4 步执行：装依赖、写只含占位的 `.env.windows`（应用 ID 与 `https://update.invalid`，不含密钥）、取 dwg2dxf、`--check` 后打包，再对 `win-unpacked` 跑 `verify-desktop-app.mjs`。

1. 打开仓库的 **Actions** 页，左侧选 **zhitong · Windows installer**，点 **Run workflow**。
2. 「Use workflow from」选要打包的分支；`version` 填发行版本（如 `1.0.0`，不带 `v`）；`ref` 留空即打所选分支；要同时发 Release 就勾 `publish`。
3. 运行约 40–60 分钟。完成后在运行页底部 **Artifacts** 下载 `ztsgai-<version>-win-x64-setup`（zip 内是 `ztsgai-<version>-win-x64-setup.exe` 与同名 `.sha256`，保留 7 天）；勾了 `publish` 的也可以到 **Releases** 的 `v<version>` 下载。推送 `v*` tag（如 `git push origin v1.0.0`）同样会打包并发布 Release。

下载后在 PowerShell 里用 `(Get-FileHash -Algorithm SHA256 .\ztsgai-1.0.0-win-x64-setup.exe).Hash.ToLower()` 与 `.sha256` 文件第一列核对，再按第 4 步安装。文件名与 `zhitong/portal/site/public/downloads/releases.json` 的约定一致；安装后应用报告的版本仍是 `apps/desktop/package.json` 的产品版本，运行摘要与 Release 说明里记为「应用内版本」。私有仓的 Windows 分钟按 2 倍计费，一次运行约占 80–120 分钟额度；fork 里上游的 CI、CI master、Sandbox、E2E、Release (dsh) 已改成只手动触发，不会自动消耗额度。打包失败时下载 `ztsgai-windows-packaging-logs-*` 查看各阶段日志。

## 四、首次运行与验收清单

### 1. 首次运行

1. 欢迎窗口直接是「填写模型 API Key 开始使用」：默认连接 DeepSeek 官方接口 `https://api.deepseek.com`，模型 DeepSeek V4.1 Flash（官方推荐）。填 DeepSeek API Key 保存后进入工作区（密钥进本机凭据存储 `~/.dsh/.credentials.yaml`）；或「稍后配置」。没有 DeepSeek 账号登录入口。要改用公司网关或其他 OpenAI 兼容地址，进入工作区后在「设置 → 模型 → 添加模型提供商 → 自定义模型 API」填 Provider ID、Base URL、协议（OpenAI Chat Completions）、API Key 与模型，再在输入框的模型选择器里选它。
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

应用名与数据位置：应用叫「智通数工AI」（macOS `/Applications/智通数工AI.app`；Windows 装在 `%LOCALAPPDATA%\Programs\ztsgai\ztsgai.exe`，开始菜单与「应用和功能」里显示「智通数工AI」），应用 ID `com.ztsgai.harness`，与上游 DeepSeek Harness 桌面版（`com.deepseek.harness`）是两个独立安装，可以并存、互不覆盖。数据位置没有随品牌改名：harness 数据仍在 `$DSH_HOME`（默认 `~/.dsh`）；Electron userData 仍是 `~/Library/Application Support/@deepseek-ai/dsh-desktop`（Windows `%APPDATA%\@deepseek-ai\dsh-desktop`），它由包名决定、不随产品名变化，所以与上游桌面版共用窗口快捷键与桌面设置文件。Electron 的单实例锁也放在这个 userData 里，所以两个版本不会同时运行：一个已在运行时打开另一个，只会把正在运行的那个窗口调到前台（按代码推断，未在实机验证）。

桌面版使用的 profile 名是 `desktop`（不是第一部分开发用的 `zhitong`）。如果这台机器以前装过上游 DeepSeek Harness 桌面版，`~/.dsh/profiles/desktop` 已经存在，新版本不会改它的 bundle 列表：在完全退出应用后把旧的 `~/.dsh/profiles/desktop` 改名（例如加后缀 `.bak`），再打开应用让它按新模板重建 profile；旧 profile 里装过的第三方插件需要重新安装。

### 2. 验收清单

| 检查 | 期望 |
|---|---|
| 品牌 | 窗口标题、Dock / 任务栏、关于、托盘、菜单（隐藏 / 退出）都是「智通数工AI」；侧栏左上角与新会话页标题左边是品牌图形（蓝色渐变圆角方块、白十字、绿短划，不是空白方块），侧栏图形右边是「智通数工AI」字标，不是 deepseek 鲸鱼与 HARNESS 字标；新会话页标题「造价咨询工作台」加「预览版」标签，输入框占位「描述你要做的造价任务，/ 调用指令，@ 文件或对话」；设置里没有「账号」页 |
| 首次运行 | 欢迎窗口第一页就是 API Key 表单，没有「登录」按钮；保存后直接进入工作区 |
| 新会话的预设 | 「智通数工AI」（预设列表第一个，造价人设）；设置 →「Agent 预设」里它在「内置」区，标签「新任务默认」 |
| 默认模型 | 只填过欢迎页的 API Key，新会话的模型选择器就显示「DeepSeek V4.1 Flash 官方推荐」（`deepseek-official` / `deepseek-flash`；输入框里另选的模型之后优先），不是「请选择模型」；发一句话不报「请先登录 DeepSeek」；设置 → 模型只有一个「DeepSeek」提供商 |
| 问 agent「列出可用的 skill」，或看 `skill` 工具的目录 | 12 个：zt-project、zt-ask、zt-archive、zt-reconcile、zt-indicator、zt-tk、zt-report、zt-quantity、zt-estimate、zt-knowledge、zt-volc、zt-cad；没有 `_shared` |
| 工具 | `tos_ls`、`tos_stat`、`tos_pull`、`tos_push`、`config_import`、`cad_open` 等 10 个 `cad_*`，以及上游的 `load_workspace_dependencies` |
| Python | 让 agent 跑任一 skill 脚本（例如「用 zt-tk 看一下帮助」）：它先调 `load_workspace_dependencies` 取 `python`，再运行 `<python> <skill 目录>/scripts/tk.py --help`，输出子命令列表；不应出现 `zt_not_importable` |
| 看图 | 给一张 DWG 让 agent `cad_open`：结果里转换器版本是 `LibreDWG dwg2dxf 0.14`；DXF 不需要转换器 |
| 配置包 | `config_import` 的结果列出凭据引用名、桶地址；有 ssh / volc 段时列出写入的文件，且不含任何密钥 |
| 离线自检 | `node zhitong/scripts/verify-desktop-app.mjs <应用路径>` 全部通过 |
