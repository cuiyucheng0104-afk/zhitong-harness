# 安装

本文分两部分：开发者在本仓从源码启动 `zhitong` profile；终端用户在 Mac / Windows 安装（W9 补全）。

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
uv sync            # 建 .venv，安装 zt（可编辑）与依赖
uv run pytest      # 可选：跑 Python 测试
```

skill 脚本用 `$ZT_PYTHON -m zt.<分区>.cli …` 调用。启动 harness 前把 `ZT_PYTHON` 指向这个虚拟环境的解释器：

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

插件以源码（`src/index.ts`）入口运行，依赖源码启动的 tsx 加载器；打包版本的构建产物由 W9 补。

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
```

`pnpm run typecheck` 依赖上游各包的声明产物（`pnpm run build:artifacts` 生成的 `lib/types`）。连真桶的往返测试 `tool-tos/tests/tos-live.spec.ts` 只在设置了 `ZT_TOS_TEST_ENDPOINT`、`ZT_TOS_TEST_REGION`、`ZT_TOS_TEST_BUCKET`、`ZT_TOS_TEST_PREFIX`、`ZT_TOS_TEST_ACCESS_KEY_ID`、`ZT_TOS_TEST_SECRET_ACCESS_KEY` 时运行，测试对象写在 `<前缀>/tool-tos-live/<随机>/` 下。

## 二、终端用户：Mac 安装

（W9 补：下载 `.dmg`、拖入「应用程序」、首次打开的 Gatekeeper 提示、导入配置包、打开样例项目。）

## 三、终端用户：Windows 安装

（W9 补：运行安装程序 `.exe`、SmartScreen 提示、中文用户名路径、导入配置包、打开样例项目。）
