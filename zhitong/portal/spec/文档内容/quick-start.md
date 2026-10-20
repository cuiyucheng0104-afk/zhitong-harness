---
title: 快速开始
slug: quick-start
group: 开始使用
order: 1
summary: 从安装到打开第一个项目、做第一次核对的最短路径，约 15 分钟。
updated: 2026-10-20
sources:
  - zhitong/INSTALL.md
  - zhitong/CONFIG-PACKAGE.md
  - zhitong/portal/site/src/data/downloads.ts
  - apps/desktop/src/locale.ts
  - zhitong/plugins/config-import/src/index.ts
  - zhitong/skills/zt-project/SKILL.md
  - zhitong/skills/zt-reconcile/SKILL.md
---

本页把安装、导入配置包、打开项目、做第一个任务压缩成一条路径。每一步都有详细说明页，遇到问题时点进去看。

## 开始前准备

| 需要 | 从哪里来 | 说明 |
|---|---|---|
| 安装包 | 本站[安装](/docs/install/)页 | Mac（Apple 芯片）的 `.dmg`，或 Windows（x64）的 `.exe` |
| 配置包 | 服务方单独交付 | 一个 `.zip` 或 `zhitong.config.json` 文件，里面有公司存储桶的地址和访问密钥。它不随安装包分发，[这页](/docs/config-package/)说明它包含什么 |
| 模型 API Key | 贵司管理员或服务方 | 默认使用 DeepSeek 官方接口；如果公司用自己的模型网关，还需要网关地址 |
| 网络 | 公司网络 | 能访问 `https://api.deepseek.com`（或公司模型网关）和配置包里的存储桶地址 |

## 第一步：安装并打开

::: steps
1. 下载与您电脑对应的安装包，按[校验安装包](/docs/install/#校验安装包)核对 SHA256。
2. **Mac**：打开 `.dmg`，把"智通数工AI"拖进"应用程序"。第一次打开时，在"应用程序"里按住 Control 点按应用（或右键）→ 打开 → 打开。
   **Windows**：双击安装程序，安装到当前用户，不需要管理员权限。出现"Windows 已保护你的电脑"时，点"更多信息"→"仍要运行"。
3. 欢迎窗口显示"填写模型 API Key 开始使用"。在"输入 API 密钥"框里粘贴 API Key，点"保存并继续"。默认连接 DeepSeek 官方接口，模型为 DeepSeek V4.1 Flash（官方推荐）。
4. 进入工作区后新建会话。确认预设是"智通数工AI"，输入框的模型选择器显示"DeepSeek V4.1 Flash"和"官方推荐"。
:::

安装包被系统拦截、API Key 保存失败等情况，见[安装](/docs/install/)。

## 第二步：导入配置包

::: steps
1. 把配置包文件拖进对话框，发送"导入这个配置包"。
2. 它会调用导入工具 `config_import`。成功时，工具结果里有类似这样一行（示例）：

   ```text
   已导入「某某工程造价咨询有限公司」的配置包：tos://zt-company/某某咨询/（tos-cn-beijing.volces.com，cn-beijing）。密钥已存入本机凭据存储（ZT_TOS_ACCESS_KEY_ID、ZT_TOS_SECRET_ACCESS_KEY），TOS 工具已按新设置重新加载。
   ```

3. 导入后，把配置包从"下载"文件夹里删掉。它含明文密钥，不要转发。
:::

::: tip 拖进去后它说找不到文件
把配置包的完整路径发给它，例如"导入配置包 /Users/zhang/Downloads/某某咨询.zip"。复制路径的方法：Mac 在访达里选中文件，按 `kbd:Option+Command+C`；Windows 11 右键文件 →"复制文件地址"，Windows 10 按住 Shift 右键 →"复制为路径"。
:::

## 第三步：打开项目

::: utterances
- 列一下桶里有哪些项目
- 打开 2026-007
:::

它先列出 `项目/` 下的目录（工具 `tos_ls`），再拉取并读取项目说明（`tos_pull`，然后运行项目说明脚本），向您转述：

| 转述内容 | 示例 |
|---|---|
| 编号与工程名 | 2026-007 滨江综合办公楼 |
| 咨询类型与阶段 | 结算审核 / 审定 |
| 关键文件指引 | 送审计价表在 `资料/4 结算资料/送审计价表.xlsx`，审定计价表在 `资料/4 结算资料/审定计价表.xlsx` … |
| 已出成果 | 尚无 |

如果项目说明里的咨询类型或阶段还写着"待确认"，它会先问您，再继续。项目说明不存在时，它会按目录生成草稿，详见[开项目与资料盘点](/docs/features/project/)。

## 第四步：做第一个任务

::: utterances
- 核对一下 2026-007 的送审和审定计价表
:::

它会按项目说明找到两张计价表，先预检，再运行核对脚本，把工作底稿写到 `工作/2026-10-19-核对/`，然后口头汇报。示例结果：

| 项 | 金额（元，示例） |
|---|---|
| 送审合计 | 30,530,406.80 |
| 审定合计 | 29,623,713.84 |
| 核减额 | 906,692.96 |
| 核减率 | 2.97% |

这些金额由脚本从表格取数计算，标注 `status:manual`，需要您打开 `核对结果.xlsx` 复核。读法见[送审审定核对](/docs/features/check/)和[结果状态与告警](/docs/results/)。

::: confirm
- 核减额、核减率、逐行调整都要对照工作底稿复核后才能用于审定单或报告。
- 如果它提示某张表"没有参与"或"合计对不上"，那部分金额没有算进去，结果不完整。
:::

## 接下来

- 想了解它每一步在做什么、怎么回答它的确认提问：[对话、确认与结果的基本用法](/docs/basics/)
- 想一次交代多步工作：[多步任务与多代理](/docs/agents/)
- 项目目录、编号和多人协作规则：[项目与存储桶目录](/docs/projects/)
