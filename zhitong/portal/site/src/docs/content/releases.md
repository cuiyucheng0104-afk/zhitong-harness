---
title: 版本与更新
slug: releases
group: 参考
order: 4
summary: 当前发布的版本、各平台安装包与 SHA256，两种版本号的含义，以及怎样更新到新版本。
updated: 2026-10-20
sources:
  - zhitong/RELEASE.md
  - zhitong/portal/deploy/release-manifest.mjs
---

本页的版本信息与首页"安装"区来自同一份发布清单，每次发布安装包时自动更新，不需要手工改页面。

## 当前版本

::: release-current
:::

平台显示"即将发布"时，表示这个版本还没有该平台的安装包，页面上不会出现它的下载链接。

## 两种版本号

| 版本号 | 在哪里看到 | 含义 |
|---|---|---|
| 安装包版本（如 `1.0.0`） | 本页、首页安装区、安装包文件名 | 对外发布的版本号 |
| 应用内版本（如 `0.2.1-rc.2`） | 应用的"关于"窗口；上方卡片的"应用内版本" | 安装包所基于的 DeepSeek Harness 版本，应用自己报告的就是这个号 |

两者不同是正常的。向服务方反馈问题时，请同时提供两个版本号。

## 怎么更新

当前安装包没有接入在线更新服务，应用里的"检查更新…"可能提示检查失败，不影响使用。有新版本时：

::: steps
1. 在本页下载新版本，按[校验安装包](/docs/install/#校验安装包)核对 SHA256。
2. 完全退出应用。
3. Mac：把新版本拖进"应用程序"并选择"替换"；Windows：运行新的安装程序。
4. 打开应用。设置、凭据、对话记录和本机缓存都保留，不需要重新导入配置包。
:::

## 文件名与下载地址

| 平台 | 文件名 | 地址 |
|---|---|---|
| Mac（Apple 芯片） | `ztsgai-<版本>-mac-arm64.dmg` | `https://ztsgai.com/downloads/<文件名>` |
| Windows（x64） | `ztsgai-<版本>-win-x64-setup.exe` | 同上 |

- 每个安装包旁边都有同名的 `.sha256` 文件（如 `ztsgai-1.0.0-mac-arm64.dmg.sha256`），内容是 SHA256 值与文件名。
- **已发布的文件不会换内容**。同一个文件名对应的永远是同一份安装包；安装包有任何变化，都会以新的版本号发布。
- 发布新版本后，旧版本的文件仍保留在服务器上，旧链接继续可用。

## 版本记录

### 1.0.0

首个对外发布的版本，应用内版本 `0.2.1-rc.2`。发布日期见上方卡片。

- 平台：Mac（Apple 芯片）、Windows（x64）。两个平台的安装包分别发布，未发布的平台在上方卡片显示"即将发布"。
- 内置 12 项能力：开项目与资料盘点、送审审定核对、造价指标、投控异常检测与复核、报告撰写、GB50854 清单框架、概算编制辅助、项目与知识库问答、归档与案例索引、企业知识库、火山引擎运维、CAD 看图。
- 安装包未签名，第一次打开需要按[安装](/docs/install/)的步骤放行。
- 当前版本的数据签核与验证状态见[数据与安全](/docs/security/#当前版本的数据与验证状态)。

## 本页数据从哪里来（发布维护者）

本节写给负责发布安装包的人员。

页面在构建时读取门户工程里的发布清单 `zhitong/portal/site/public/downloads/releases.json` 并校验；清单写错时网站构建失败，不会生成坏链接。清单由发布脚本 `zhitong/portal/deploy/release-manifest.mjs stage` 填写，**不要手改** `sha256` 与 `size`。操作步骤见 `zhitong/portal/deploy/runbook.md` 第 4 节。

清单格式（示例：Mac 已发布、Windows 未发布）：

```json
{
  "schema": 1,
  "product": "智通数工AI",
  "version": "1.0.0",
  "date": "<YYYY-MM-DD>",
  "base": "0.2.1-rc.2",
  "notes": [],
  "platforms": {
    "mac-arm64": {
      "file": "ztsgai-1.0.0-mac-arm64.dmg",
      "sha256": "<64 位小写十六进制>",
      "size": 190840832,
      "notes": null
    },
    "win-x64": { "file": null, "sha256": null, "size": null, "notes": null }
  }
}
```

| 字段 | 规则 | 页面上显示为 |
|---|---|---|
| `schema` | 固定为 `1` | — |
| `product` | 非空 | — |
| `version` | `x.y.z`，可带预发布后缀 | 卡片标题"v{version}"；文件名中的版本 |
| `date` | `YYYY-MM-DD`，或在第一个安装包放置前为 `null`；放置时默认取当天的上海日期 | "{date} 发布"；为 `null` 时"尚未发布" |
| `base` | 安装包所基于的 DeepSeek Harness 版本，由放置脚本从构建产物文件名取得 | "应用内版本 {base}" |
| `notes` | 字符串数组，可为空 | 卡片里的版本说明列表 |
| `platforms.<平台>.file` | 必须正好是 `ztsgai-<version>-mac-arm64.dmg` 或 `ztsgai-<version>-win-x64-setup.exe`；未发布为 `null` | 文件名与下载按钮；`null` 时"即将发布" |
| `platforms.<平台>.sha256` | 64 位小写十六进制；`file` 为 `null` 时也为 `null` | SHA256 与复制按钮 |
| `platforms.<平台>.size` | 正整数字节数；`file` 为 `null` 时也为 `null` | 大小，按 MB 显示一位小数（1 MB = 1024 × 1024 字节） |
| `platforms.<平台>.notes` | 字符串或 `null` | 该平台的补充说明 |

发布新版本：把 `version` 改成新号，把各平台的 `file`、`sha256`、`size` 置回 `null`，再逐个平台运行放置脚本。之后把本页"版本记录"补上一节。
