---
title: 安装
slug: install
group: 开始使用
order: 2
summary: 下载并校验安装包，在 Mac 或 Windows 上安装、第一次打开、填写模型 API Key，以及更新与卸载。
updated: 2026-10-20
sources:
  - zhitong/INSTALL.md
  - zhitong/STATUS.md
  - zhitong/portal/site/src/data/downloads.ts
  - zhitong/portal/site/src/data/release-manifest.mjs
  - zhitong/portal/deploy/runbook.md
  - zhitong/plugins/tool-tos/README.md
  - apps/desktop/src/locale.ts
  - docs/user/guide/providers.zh.md
---

智通数工AI 提供 Mac 与 Windows 两个安装包。安装包内含 Python 运行时、脚本依赖库和 DWG 图纸转换组件，不需要另装 Python。安装后还要导入公司配置包才能读写公司存储桶，见[导入配置包](/docs/config-package/)。

## 系统要求

| 项 | 要求 |
|---|---|
| Mac | Apple 芯片（M 系列）的 Mac。Intel 芯片的 Mac 目前没有安装包 |
| Windows | Windows 10 或 11，64 位（x64）。安装到当前用户，不需要管理员权限 |
| 网络 | 能访问模型接口（默认 `https://api.deepseek.com`，或公司自己的模型网关）和配置包里的存储桶地址（如 `tos-cn-beijing.volces.com`） |
| 磁盘 | 应用本身之外，本机缓存默认最多占用 20 GiB（只缓存用到的文件，见[项目与存储桶目录](/docs/projects/#本机缓存)） |
| 账号 | 模型 API Key（向贵司管理员或服务方获取）；没有 DeepSeek 账号登录 |

## 下载安装包

::: release-current
:::

文件名形如 `ztsgai-<版本>-mac-arm64.dmg`（Mac）和 `ztsgai-<版本>-win-x64-setup.exe`（Windows）。每个安装包旁边有同名的 `.sha256` 文件，用来校验。平台显示"即将发布"时，表示这个版本还没有该平台的安装包。

::: note 安装包没有签名
当前安装包未经 Apple 公证、未做 Windows 代码签名，所以第一次打开时系统会拦截，按下面的步骤放行即可。放行之前请先校验 SHA256，确认文件是从本站下载、没有损坏或被替换。
:::

## 校验安装包

SHA256 是文件的"指纹"：文件有任何一个字节不同，算出来的值就不同。把您电脑上算出的值与上方卡片里的 SHA256 对比，完全一致才安装。

**Mac**：打开"终端"，进入"下载"文件夹，计算安装包的 SHA256：

```bash
cd ~/Downloads
shasum -a 256 ztsgai-1.0.0-mac-arm64.dmg
```

输出的第一段 64 位字符就是 SHA256，与卡片里的值逐位对比。如果同时下载了 `.sha256` 文件，放在同一文件夹里，可以让系统直接比对：

```bash
shasum -a 256 -c ztsgai-1.0.0-mac-arm64.dmg.sha256
```

显示 `ztsgai-1.0.0-mac-arm64.dmg: OK` 即一致。

**Windows**：打开 PowerShell，进入"下载"文件夹：

```powershell
cd $HOME\Downloads
Get-FileHash .\ztsgai-1.0.0-win-x64-setup.exe -Algorithm SHA256
```

`Hash` 一列就是 SHA256（大写显示，与卡片里的小写值字母大小写不同不影响）。也可以让 PowerShell 直接比对 `.sha256` 文件：

```powershell
(Get-FileHash .\ztsgai-1.0.0-win-x64-setup.exe -Algorithm SHA256).Hash -eq (Get-Content .\ztsgai-1.0.0-win-x64-setup.exe.sha256).Split(' ')[0]
```

显示 `True` 即一致。

命令中的版本号 `1.0.0` 换成您下载的版本。值不一致时不要安装：删除文件，重新下载；仍不一致请联系服务方。

## 在 Mac 上安装

::: steps
1. 双击 `.dmg`，在打开的窗口里把"智通数工AI"拖进"应用程序"。
2. 第一次打开：在"应用程序"里按住 Control 点按"智通数工AI"（或右键）→"打开"→ 在弹出的提示里再点"打开"。
3. macOS 15 及以上如果仍被拦截：打开"系统设置 → 隐私与安全性"，滚到底部，点"仍要打开"，再打开一次应用。
4. 以后直接从"应用程序"或启动台打开即可，不会再提示。
:::

::: note 提示"已损坏，无法打开"
确认 SHA256 校验一致后，打开"终端"执行下面这行，再按第 2 步右键打开：

```bash
xattr -dr com.apple.quarantine "/Applications/智通数工AI.app"
```

这条命令去掉系统给"从网上下载的文件"加的隔离标记。只对校验一致的安装包这样做。
:::

## 在 Windows 上安装

::: steps
1. 双击 `ztsgai-<版本>-win-x64-setup.exe`。
2. 出现"Windows 已保护你的电脑"时，点"更多信息"→"仍要运行"。
3. 安装程序把应用装到当前用户目录（`%LOCALAPPDATA%\Programs\ztsgai\ztsgai.exe`），不需要管理员权限。
4. 安装完成后，从开始菜单打开"智通数工AI"。
:::

::: note Windows 用户名是中文时
看 DWG 图纸用的转换组件不支持中文路径下的临时目录。如果打不开 DWG，把用户环境变量 `TEMP` 和 `TMP` 改到纯英文路径（例如 `C:\Temp`，先建好这个文件夹），然后完全退出并重新打开应用。修改方法：开始菜单搜索"编辑账户的环境变量"，在"用户变量"里分别编辑 `TEMP`、`TMP`。
:::

## 第一次打开

::: steps
1. 欢迎窗口显示"智通数工AI"与"造价咨询的 AI 工作台"，第一页就是"填写模型 API Key 开始使用"，没有登录按钮。说明文字写着：默认连接 DeepSeek 官方接口（`https://api.deepseek.com`），使用 DeepSeek V4.1 Flash（官方推荐）。
2. 在"输入 API 密钥"框里粘贴 API Key，点"保存并继续"。密钥保存在本机凭据存储里，不会显示在界面上。也可以点"稍后配置"，先进入工作区，之后在"设置 → 模型"里填写。
3. 进入工作区后新建会话。如果输入框提示"选择一个工作区开始"，点"选择工作区"选一个本机文件夹。新会话默认使用"智通数工AI"预设（预设列表第一个）；输入框的模型选择器显示"DeepSeek V4.1 Flash"和"官方推荐"。
4. 接着[导入配置包](/docs/config-package/)。
:::

保存 API Key 时可能看到的提示：

| 提示 | 原因与处理 |
|---|---|
| 请输入 API 密钥。 | 输入框是空的 |
| 请仅输入 API 密钥，不要包含引号、空格或环境变量赋值。 | 粘贴时带上了引号、空格，或整行 `DEEPSEEK_API_KEY=…`。只粘贴密钥本身 |
| 无法保存 API 密钥，请重试。 | 重试；仍失败时完全退出应用再打开 |

### 使用公司的模型网关

如果贵司不直接连 DeepSeek 官方接口，而是用公司网关或其他 OpenAI 兼容地址：进入工作区后打开"设置 → 模型 → 添加模型提供商"，切换到"自定义模型 API"，填写 Provider ID（小写英文，之后不能改名）、API 地址、API 协议（选 OpenAI Chat Completions）、API 密钥和模型，保存后在输入框的模型选择器里选它。网关地址与模型名由贵司管理员提供。

## 应用名与数据位置

| 内容 | 位置 |
|---|---|
| 应用 | Mac：`/Applications/智通数工AI.app`；Windows：`%LOCALAPPDATA%\Programs\ztsgai\ztsgai.exe`，开始菜单与"应用和功能"里显示"智通数工AI" |
| 设置、凭据、对话记录 | `~/.dsh`（Windows `%USERPROFILE%\.dsh`）。模型 API Key 与存储桶密钥在其中的 `.credentials.yaml`，仅当前用户可读 |
| 本机文件缓存 | `~/zhitong`（Windows `%USERPROFILE%\zhitong`），与公司存储桶同构，只放拉取过的文件 |
| 窗口与桌面设置 | Mac：`~/Library/Application Support/@deepseek-ai/dsh-desktop`；Windows：`%APPDATA%\@deepseek-ai\dsh-desktop` |

数据位置里出现的 `dsh`、`deepseek-ai` 是产品底层（DeepSeek Harness）的技术标识，没有随产品名更改，这样不会丢数据。

::: note 以前装过 DeepSeek Harness 桌面版
智通数工AI 与 DeepSeek Harness 桌面版是两个独立的应用，可以同时安装，但共用 `~/.dsh` 与上表的窗口设置目录，并且不能同时运行：一个在运行时打开另一个，只会把正在运行的那个窗口调到前台。

如果这台电脑以前用过 DeepSeek Harness 桌面版，新会话里可能没有"智通数工AI"预设，导入配置包时也会报错。处理方法：完全退出应用，把 `~/.dsh/profiles/desktop` 文件夹改名（例如加后缀 `.bak`），再打开智通数工AI，让它重新建立配置。原来在 DeepSeek Harness 里装的第三方插件需要重新安装。
:::

## 关于窗口里的版本号

"关于"窗口显示的是应用内版本（例如 `0.2.1-rc.2`），与安装包文件名里的版本（例如 `1.0.0`）不同。这是正常的：安装包版本是对外发布的版本号，应用内版本是它所基于的 DeepSeek Harness 版本。两者的对应关系见[版本与更新](/docs/releases/)。

## 更新

当前安装包没有接入在线更新服务，应用菜单里的"检查更新…"可能提示"检查更新失败"，不影响使用。更新方法是下载新版本安装包，覆盖安装：

::: steps
1. 在本站下载新版本，[校验 SHA256](/docs/install/#校验安装包)。
2. 完全退出智通数工AI（Mac 用菜单"退出"，Windows 在托盘图标上右键退出）。
3. **Mac**：打开新的 `.dmg`，把应用拖进"应用程序"，选择"替换"。**Windows**：运行新的安装程序。
4. 打开应用。设置、凭据、对话记录和本机缓存都不在应用本身里，覆盖安装不会删除它们，不需要重新导入配置包。
:::

## 卸载

::: steps
1. 完全退出应用。
2. **Mac**：把"应用程序"里的"智通数工AI"拖到废纸篓。**Windows**：打开"设置 → 应用 → 已安装的应用"（Windows 10 为"应用和功能"），找到"智通数工AI"，点"卸载"。
:::

卸载应用不会删除您的数据。需要彻底清除时，再按需删除下表的内容：

| 内容 | 删除前注意 |
|---|---|
| `~/zhitong`（本机缓存） | 先让它确认没有"本机改过但没推回桶"的文件；这些文件只在本机，删除后无法从桶里找回 |
| `~/.dsh`（设置、凭据、对话记录） | 如果同时使用 DeepSeek Harness 桌面版，它也用这个目录，删除会影响它 |
| `~/.ssh/config` 里 `# >>> zhitong config-import` 到 `# <<< zhitong config-import <<<` 之间的内容，以及 `~/.ssh/zhitong/` | 只有配置包里带 SSH 主机时才有，删除后无法再用运维能力登录服务器 |
| 上表"窗口与桌面设置"目录 | 与 DeepSeek Harness 桌面版共用 |

安装说明里没有专门的卸载程序或清理工具，上表按产品写入数据的位置整理。

## 安装遇到问题

常见情况的处理见[常见问题与排错](/docs/troubleshooting/#安装与首次打开)。
