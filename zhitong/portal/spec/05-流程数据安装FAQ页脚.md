# 05 使用流程 · 数据与复核 · 安装与交付 · 常见问题 · 页脚

本章规定首页下半部分的五个区块：`#workflow`、`#trust`、`#install`、`#faq` 与页脚。设计变量、交互基础件、示例项目、性能与验收方式全部沿用 [00 章](00-总览与设计系统.md)；本章新增的三个基础件集中在 §6。页面上的示例都带"示例"字样，示例里的公司、桶、项目与金额都是虚构的。

## 0. 本章约定

### 0.1 补充示例数据

以下数据都在 00 章 §8.1 的项目内补充，02、04、06 章如展示同一事实，须用同一组值。

| 项 | 值 | 依据 |
|---|---|---|
| 示例公司 | 示例工程造价咨询有限公司 | 虚构 |
| 示例桶 | endpoint `tos-cn-beijing.volces.com`，region `cn-beijing`，bucket `zt-demo`，前缀 `示例咨询` | 符合 `config-import` 的字段规则（`zhitong/plugins/config-import/src/package.ts`） |
| 配置包 | `示例咨询-配置包.zip`（2.1 KB），根目录一个 `zhitong.config.json`，不含 `ssh`、`volc` 段 | `zhitong/CONFIG-PACKAGE.md` |
| 桶内 `项目/` | 9 个目录，按 `tos_ls` 的字典序：`2025-036-城西安置房三期`、`2025-041-科创园研发楼`、`2026-001-南湖学校扩建`、`2026-002-滨江路市政改造`、`2026-003-高新区人才公寓`、`2026-004-城北社区卫生服务中心`、`2026-005-老城区雨污分流`、`2026-006-江湾体育公园`、`2026-007-滨江综合办公楼` | 虚构；编号格式 `YYYY-NNN` |
| 资料盘点（2026-10-19） | `status: ok`；必备 7 项：已备 3、待确认 1、缺失 3；齐备率 42.86%，上限 57.14%；缺失：结算审核报告、结算审定单、审核汇总表；待确认：变更签证费用（`资料/5 变更资料/签证单汇总.xlsx`，弱证据）；重要资料未找到：投标报价文件；未判出类目：`资料/6 其他/扫描件0001.pdf`；告警 warn 4 条、info 1 条 | 2026-10-20 用 `zhitong/skills/zt-project/scripts/inventory.py scan --consulting-type 结算审核 --stage 审定` 对 §8.1 的 `项目说明.md`、`资料/`、`图纸/` 文件名单实跑所得；3 ÷ 7 = 42.86%，4 ÷ 7 = 57.14% |
| 核对（2026-10-19） | 全部取 00 章 §8.2 | — |
| 报告工作目录 | `工作/2026-10-24-报告/`，39 个文件 | zt-report 的工作目录结构：`context/result.json`、`facts/result.json`、`确认事项.json`，加结算审核报告模板 9 章 × 每章 4 个文件 |
| 归档（2026-10-28） | `成果/` 3 份：`结算审核报告.docx` 1.2 MiB、`结算审定单.xlsx` 38.6 KiB、`审核汇总表.xlsx` 52.3 KiB；`工作/` 3 个目录共 44 个文件：`2026-10-19-盘点/` 2 个 10.9 KiB、`2026-10-19-核对/` 3 个 2.8 MiB、`2026-10-24-报告/` 39 个 1.6 MiB；`2026-10-19-核对/待确认清单.md` 未勾选 2 条；`项目说明.md` 3.6 KiB、`案例索引.md` 4.1 KiB | 虚构；大小写法同 `tos_push` 的 `formatBytes` |
| 案例索引关键指标 | `审定 29,623,713.84 元；核减率 2.97%；土建单方 1,592.67 元/m²（按建筑面积）` | 29,623,713.84 ÷ 18,600.00 = 1,592.67 |

§8.1 的目录树是 2026-10-19 的快照（`成果/` 为空）；本章第四步场景发生在 2026-10-28，那时 `成果/` 已有上表 3 份文件。

### 0.2 文案校正

以下各处与 `门户文案.txt` 不同，按事实来源改写；FAQ 的校正见 §4.2。

| 位置 | 文案稿 | 本章写法 | 依据 |
|---|---|---|---|
| 流程副标题 | 每一步都落在公司自己的桶里 | 从连接公司的桶开始，到归档回桶结束。 | 第一步只写本机凭据存储与 profile，不写桶 |
| 第一步正文 | 安装后首次启动，把服务方交付的配置包拖进对话。 | 加"先在欢迎页填写模型 API Key" | `INSTALL.md` 第四部分：欢迎窗口第一页是 API Key 表单 |
| 第四步正文 | 归档时核对……推送回桶 | 加"经您确认后" | `zt-archive/SKILL.md` 第 3 步：用户确认后才推送 |
| 安装包 | 提供 Mac（.dmg）和 Windows（.exe）安装包 | 写明 Apple 芯片与 x64 | `release-manifest.mjs` 只有 `mac-arm64`、`win-x64` |
| 配置包 | ……SSH 主机别名、密钥及 ve 配置 | ……火山引擎 ve 的 profile 名；ve 自己的密钥不放进配置包 | `CONFIG-PACKAGE.md`「火山引擎 ve profile」 |
| 首次使用 | 把配置包拖进对话…… | 先填写模型 API Key，再拖配置包；缓存上限写明默认 20 GiB | `INSTALL.md` 第四部分；`tool-tos` 的 `cacheMaxBytes` |

### 0.3 文件

```text
src/data/workflow.ts  trust.ts  faq.ts         本章文案与示例数据（类型见各节）
src/components/workflow/
  WorkflowSection.vue  WfStepper.vue  WfPanel.vue  WfScene.vue
  scenes/SceneImport.vue  SceneOpen.vue  SceneTask.vue  SceneArchive.vue
  useWorkflowPin.ts                             钉住、吸附、当前步骤
src/components/trust/  TrustSection.vue  TrustFlow.vue  trust-geometry.ts
src/components/install/ InstallSection.vue  ConfigPackageNote.vue
src/components/faq/     FaqSection.vue  FaqItem.vue
src/components/SiteFooter.vue
src/data/site.ts                                只导出 SUPPORT_CONTACT（由 01 章 site.config.ts 派生，06 章引用）
```

复用 01 章的全局件，不另建：`src/site.config.ts`（01 章 §8.2；本章在 `SiteConfig` 上追加 `legal`，§5.4）、`src/components/acquire/PlatformCard.vue`（01 章 §7.4；本章加两个 prop，§3.4）、`lib/platform.ts`（01 章 §7.5）、`useCopy` 与 `useToast`（01 章 §14）、`downloads.ts` 的改动（01 章 §7.4）。

删除现 `WorkflowSection.vue`、`TrustSection.vue`、`InstallSection.vue`、`FaqSection.vue`，以及 `content.ts` 里的 `workflowSteps`、`trustStatements`、`faqs`。

## 1. 使用流程 `#workflow`

### 1.1 目的

用四段随滚动推进的示例对话，说明从导入配置包到归档回桶，每一步做什么、写到哪里。

### 1.2 文案

| 位置 | 文案 |
|---|---|
| 眉标 | 使用流程 |
| h2 `#workflow-title` | 四步，从安装到归档 |
| 副标题 | 从连接公司的桶开始，到归档回桶结束。 |
| 步骤条 | `<ol aria-label="使用流程四步">`；标记内数字 1–4，标记下文字为四步标题 |
| 写入小标题 | 写到哪里 |
| 场景窗口标题栏 | 智通数工AI · 示例会话 |
| 场景徽标 | 示例 |
| 场景按钮 | 暂停示例 / 播放示例（`aria-label` 与文字相同）；重播本步（`aria-label="重播第 N 步示例"`） |
| 场景容器 | `aria-label="第 N 步示例：<步骤标题>"` |
| 输入框占位（场景内，不可输入） | 第一步：把配置包拖到这里，或告诉我它的路径；其余：说说要做什么 |

| 步 | 标签 | 标题 | 正文 | 写到哪里（等宽路径以芯片显示） | 文档链接 |
|---|---|---|---|---|---|
| 1 | 第一步 | 导入配置包 | 安装后首次启动，先在欢迎页填写模型 API Key，再把服务方交付的配置包拖进对话。系统校验内容，把访问密钥写入本机凭据存储、把桶的地址写入工作配置，不回显密钥，随后列出桶里的项目。 | 本机凭据存储（2 个密钥引用名）· 当前 profile 的 TOS 设置 | 读文档：导入配置包 → `/docs/config-package/` |
| 2 | 第二步 | 开项目 | 选择桶里已有项目，或新建一个。系统先读项目说明，缺少时按目录结构生成草稿，再按咨询类型对照应收资料清单盘点：缺什么直接说明，不替资料贴标签。 | `项目说明.md`「资料盘点」小节 · `工作/2026-10-19-盘点/` | 读文档：开项目与资料盘点 → `/docs/features/project/` |
| 3 | 第三步 | 对话完成任务 | 直接说要做什么，例如"核对送审和审定计价表""检测投控异常""写结算审核报告"。判断、分类、摘录和写作由模型完成；金额、数量、核对、指标由脚本计算；每一步的状态如实转述。 | `工作/2026-10-19-核对/`：`result.json` · `核对结果.xlsx` · `待确认清单.md` | 读文档：送审审定核对 → `/docs/features/check/` |
| 4 | 第四步 | 归档回桶 | 归档时核对"成果"与"工作"目录是否完整，经您确认后推送回桶并回读校验，更新项目说明和案例索引，供下一个项目对标、下一位同事接手。 | 桶内 `成果/`、`工作/` · `项目说明.md`（已出成果、状态）· `案例索引.md`（本项目一行） | 读文档：归档与案例索引 → `/docs/features/archive/` |

#### 1.2.1 场景节拍

每个场景是一段按节拍排列的示例对话。节拍的起点 = 上一拍结束 + `gap`（秒）。场景播完停在终态（不循环）。

| 类型 | 呈现 | 固有时长 |
|---|---|---|
| `drop` | 文件卡从窗口右上角外侧（x +120、y −80、rotate 4°、scale 0.9）飞入输入框，落下后变成用户气泡里的附件芯片 | 0.8 s `power3.inOut` + `DUR.short` |
| `user` | 右侧用户气泡（可带附件芯片） | `DUR.short` |
| `tool` | `ZtToolCall`：中文标签 + 等宽命令；`run` 秒内为进行中，之后显示完成与耗时 `ms`；有 `result` 时在调用条下方显示一段 13px 等宽结果文字（工具的原样输出） | `DUR.short` + `run` |
| `stream` | `ZtStream`，34 字/秒，遇标点停 120 ms | 按字数 |
| `status` | `ZtStatus`：状态 + 告警计数；有 `lines` 时逐条列出告警原文 | `DUR.short` |
| `card` | 结果卡，内部行 `stagger: STAGGER.base` | `DUR.base` + 行数 × 0.07 |
| `ask` | 确认提问卡（对应 `ask_user_question`）；示意指针 0.6 s `power2.inOut` 移到选中项，按下 `scale 0.97` 0.12 s，选中项变实心 | `DUR.base` + 0.72 |
| `push` | 推送清单：标题行 `tos_push × N`，逐行出现，每行 0.18 s 后右侧出现"回读校验通过"与对勾 | 行数 × 0.14 + 0.18 |
| `diff` | 文件改动卡：删除行 1px 删除线 `scaleX 0→1` 0.3 s；插入行底色 `--green-tint` 1.2 s 内从不透明降到 40% | `DUR.base` + 0.3 |
| `note` | 页边标注：一条 1px `--brand-blue` 引线从上一拍伸出（DrawSVG 0.3 s）连到窗口右侧外的标注框；窗口宽 < 600px 时标注框改为内嵌在上一拍之下 | `DUR.base` |
| `outcome` | 窗口左下角的结果条（浅蓝底、等宽数字） | `DUR.short` |

消息列超过窗口正文高度时，消息列整体 `y` 上移到底部对齐，`DUR.base`，`EASE.inOut`；不使用 `scrollTop`。

**场景一 · 导入配置包**（约 11 s）

| # | gap | 类型 | 内容 |
|---|---|---|---|
| 1 | 0.4 | drop | `示例咨询-配置包.zip` · 2.1 KB |
| 2 | 0.1 | user | 附件 `示例咨询-配置包.zip`；"这是公司的配置包，帮我导入。" |
| 3 | 0.4 | tool | 导入配置包 `config_import`；run 0.9；ms 420；result：`已导入「示例工程造价咨询有限公司」的配置包：tos://zt-demo/示例咨询/（tos-cn-beijing.volces.com，cn-beijing）。密钥已存入本机凭据存储（ZT_TOS_ACCESS_KEY_ID、ZT_TOS_SECRET_ACCESS_KEY），TOS 工具已按新设置重新加载。` |
| 4 | 0 | note | 标题"config_import 校验的字段"；8 行，每行"字段 · 值 · ✓"，行间 `stagger: 0.09`：`format` zhitong.config/1；`company.name` 示例工程造价咨询有限公司；`tos.endpoint` tos-cn-beijing.volces.com；`tos.region` cn-beijing；`tos.bucket` zt-demo；`tos.prefix` 示例咨询；`tos.accessKeyId` ●●●●●●●● 不回显；`tos.secretAccessKey` ●●●●●●●● 不回显。脚注："另查：文件 ≤ 1 MiB；zip 内恰好一个 zhitong.config.json；不认识的字段一律拒收。" |
| 5 | 0.3 | stream | 导入完成：桶 zt-demo，前缀 示例咨询。两个访问密钥存进了本机凭据存储，对话里不会显示。我先看看桶里有哪些项目。 |
| 6 | 0.3 | tool | 列出项目 `tos_ls 项目/`；run 0.7；ms 610；result：`tos://zt-demo/示例咨询/项目/：9 个目录，0 个文件` |
| 7 | 0.2 | stream | 已连接。项目/ 下有 9 个项目，最近的是 2026-007-滨江综合办公楼。要打开哪一个？ |
| 8 | 0.3 | outcome | 已连接 · 找到 9 个项目 |

第 3 拍的 result 与 `config-import/src/index.ts` 的 `renderImport` 对示例包的输出逐字一致。场景内任何位置都不出现密钥值，只出现引用名与 ●。

**场景二 · 开项目**（约 14 s）

| # | gap | 类型 | 内容 |
|---|---|---|---|
| 1 | 0.3 | card | 项目列表卡，标题 `tos://zt-demo/示例咨询/项目/`；9 行等宽 `[目录] <目录名>/`（顺序见 §0.1）；示意指针在 0.8 s 时移到最后一行，该行底色 `--blue-050` |
| 2 | 0.6 | user | 打开 2026-007 |
| 3 | 0.3 | tool | 读取项目说明 `tos_pull 项目/2026-007-滨江综合办公楼/项目说明.md`；run 0.5；ms 380 |
| 4 | 0.1 | tool | 解析项目说明 `project_doc.py show`；run 0.3；ms 160 |
| 5 | 0.2 | stream | 2026-007 滨江综合办公楼：结算审核，审定阶段；办公，建筑面积 18,600.00 m²；别名 合同号 HT-DEMO-07。关键文件指引里有合同、招标文件、工程量清单、送审与审定计价表的位置。接着按结算审核的资料清单盘点。 |
| 6 | 0.3 | tool | 列出全部文件 `tos_ls 项目/2026-007-滨江综合办公楼/ recursive`；run 0.6；ms 540 |
| 7 | 0.1 | tool | 资料盘点 `inventory.py scan`；run 0.8；ms 730 |
| 8 | 0.2 | status | `ok`（完成）；警告 4 · 提示 1 |
| 9 | 0.1 | card | 盘点结果卡，见下 |
| 10 | 0.3 | stream | 盘点只看了文件名，没有读内容。缺 3 项必备资料：结算审核报告、结算审定单、审核汇总表。变更签证费用只找到疑似文件 签证单汇总.xlsx，打开确认后才能算已备。扫描件0001.pdf 从文件名判断不出类目，可以看图确认。 |
| 11 | 0.3 | outcome | 必备 7 项 · 已备 3 · 待确认 1 · 缺失 3 |

盘点结果卡（行顺序固定）：

| 行 | 文字 |
|---|---|
| 标题 | 资料盘点 · 结算审核 · 审定阶段（含此前各阶段） |
| 指标 | 必备 7 · 已备 3 · 待确认 1 · 缺失 3 ｜ 齐备率 42.86%（上限 57.14%） |
| 缺失（必备） | 结算审核报告 · 结算审定单 · 审核汇总表 |
| 待确认 | 变更签证费用 ← `资料/5 变更资料/签证单汇总.xlsx`（文件名弱证据） |
| 重要资料未找到 | 投标报价文件 |
| 未判出类目 | `资料/6 其他/扫描件0001.pdf` |
| 脚注（13px，`--text-muted`） | 资料清单由旧系统迁来，待签核；盘点只看文件名，不给资料贴标签。 |

**场景三 · 对话完成任务**（约 15 s）

| # | gap | 类型 | 内容 |
|---|---|---|---|
| 1 | 0.4 | user | 核对一下送审和审定计价表 |
| 2 | 0.3 | tool | 拉取文件 `tos_pull 资料/4 结算资料/送审计价表.xlsx`；run 0.5；ms 820 |
| 3 | 0.1 | tool | 拉取文件 `tos_pull 资料/4 结算资料/审定计价表.xlsx`；run 0.5；ms 760 |
| 4 | 0.1 | tool | 预检计价表 `probe.py probe`；run 0.4；ms 290；result：`2 份都是计价表（kind=costsheet）` |
| 5 | 0.1 | tool | 运行核对 `reconcile.py run --basis auto`；run 1.4；ms 3,840 |
| 6 | 0.2 | status | `ok`（完成）；徽标"需人工确认" |
| 7 | 0.1 | card | 核对卡，见下 |
| 8 | 0.2 | card | 产出文件条 3 行：`工作/2026-10-19-核对/核对结果.xlsx`、`工作/2026-10-19-核对/result.json`、`工作/2026-10-19-核对/待确认清单.md` |
| 9 | 0.2 | stream | 送审合计 30,530,406.80 元，审定合计 29,623,713.84 元，核减额 906,692.96 元，核减率 2.97%，均为脚本取数，需人工复核。核减最多的是混凝土及钢筋混凝土工程 546,666.34 元；门窗工程核增 32,612.74 元。量差 612,418.27 元，价差 147,749.55 元。另有 7 行待核实，已写进待确认清单。 |
| 10 | 0.3 | outcome | 核减 906,692.96 元 · 2.97% · 需人工确认 |

核对卡：上排 4 个数（送审合计 30,530,406.80 元、审定合计 29,623,713.84 元、核减额 906,692.96 元、核减率 2.97%），按 `useCountUp` 的格式化与等宽规则，由本拍开始时触发滚动（不按视口触发），`DUR.long`，`EASE.expo`。中排 4 条横条，宽度按 |核减额| ÷ 546,666.34：混凝土及钢筋混凝土工程 核减 546,666.34（100%）、措施项目 核减 239,531.25（43.8%）、土石方工程 核减 81,533.65（14.9%）、门窗工程 核增 32,612.74（6.0%，`--danger-text`）；条从 `scaleX 0` 长出，`DUR.long`，`EASE.expo`，`stagger: STAGGER.base`。下排一行：逐行 1,284：一致 1,031 · 调整 214 · 仅送审 23 · 仅审定 9 · 待核实 7。

**场景四 · 归档回桶**（约 17 s）

| # | gap | 类型 | 内容 |
|---|---|---|---|
| 1 | 0.4 | user | 2026-007 做完了，归档吧 |
| 2 | 0.3 | tool | 列出项目文件 `tos_ls 项目/2026-007-滨江综合办公楼/ recursive`；run 0.6；ms 640 |
| 3 | 0.1 | tool | 拉取案例索引 `tos_pull 案例索引.md`；run 0.4；ms 310 |
| 4 | 0.1 | tool | 归档核对 `archive.py check`；run 0.5；ms 450 |
| 5 | 0.2 | status | `ok`（完成）；警告 1；lines：`2026-10-19-核对/待确认清单.md 还有 2 条未勾选的待确认事项` |
| 6 | 0.3 | ask | 标题"按这样归档？"；4 行：成果 3 份：结算审核报告.docx、结算审定单.xlsx、审核汇总表.xlsx ／ 推送：成果/ 3 个文件、工作/ 44 个文件 ／ 案例索引关键指标：审定 29,623,713.84 元；核减率 2.97%；土建单方 1,592.67 元/m²（按建筑面积） ／ 提醒：待确认清单还有 2 条未勾选，作为遗留写进项目说明；选项"按这样归档""先不归档"，选中第一项 |
| 7 | 0.3 | push | `tos_push × 47`；6 行：`成果/结算审核报告.docx` 1.2 MiB；`成果/结算审定单.xlsx` 38.6 KiB；`成果/审核汇总表.xlsx` 52.3 KiB；`工作/2026-10-19-盘点/` 2 个文件 10.9 KiB；`工作/2026-10-19-核对/` 3 个文件 2.8 MiB；`工作/2026-10-24-报告/` 39 个文件 1.6 MiB |
| 8 | 0.2 | tool | 登记 `archive.py apply --key-metrics "…"`（命令单行省略，`title` 为全文）；run 0.4；ms 230 |
| 9 | 0.2 | diff | `项目说明.md`，见下 |
| 10 | 0.2 | diff | `案例索引.md`，见下 |
| 11 | 0.2 | push | `tos_push × 2`；`项目说明.md` 3.6 KiB；`案例索引.md` 4.1 KiB，行尾加一行小字"覆盖了 2026-10-27 16:42 的旧版本，可从版本历史恢复" |
| 12 | 0.2 | stream | 已归档 2026-007：推送 49 个文件，回读校验全部通过。项目说明的状态改为「已归档」，登记了 3 份成果；案例索引只更新了本项目这一行。2 条待确认事项作为遗留写进了项目说明的工作记录。 |
| 13 | 0.3 | outcome | 回桶 49 个文件 · 回读校验通过 |

`项目说明.md` 改动卡（`-` 删除，`+` 插入，空格开头为上下文）：

```diff
-状态: 进行中
+状态: 已归档
 ## 已出成果
-尚无。成果推送到 `成果/` 后由 zt-archive 在这里逐行登记（相对项目目录的路径）。
+- 成果/结算审核报告.docx
+- 成果/结算审定单.xlsx
+- 成果/审核汇总表.xlsx
 ## 工作记录
+- 2026-10-28 归档。遗留：工作/2026-10-19-核对/待确认清单.md 尚有 2 条未确认。
```

`案例索引.md` 改动卡：表头 8 列与 `zt-project/templates/案例索引.md` 一致；上一行 `2026-006` 灰显作上下文；本项目行的"关键指标""成果链接""状态"三格逐格替换（旧值 `yPercent 0→−100` 移出、新值 `100→0` 移入，0.36 s，`stagger: 0.08`），整行底色 `--blue-050`。

```text
| 编号 | 工程名 | 业态 | 规模 | 咨询类型 | 关键指标 | 成果链接 | 状态 |
| 2026-006 | 江湾体育公园 | … | … | … | … | … | … |            ← 灰显
| 2026-007 | 滨江综合办公楼 | 办公 | 建筑面积 18,600.00 m² | 结算审核 |  |  | 进行中 |      ← 旧
| 2026-007 | 滨江综合办公楼 | 办公 | 建筑面积 18,600.00 m² | 结算审核 | 审定 29,623,713.84 元；核减率 2.97%；土建单方 1,592.67 元/m²（按建筑面积） | 项目/2026-007-滨江综合办公楼/成果/ | 已归档 |   ← 新
```

窗口宽 < 600px 时，该卡改为 8 个"列名：值"的竖排字段，变动的 3 个字段同样逐格替换。

### 1.3 布局

**桌面钉住模式**（`(min-width: 1024px) and (min-height: 580px)`，未减少动效，GSAP 已加载）：

- 区块标题（眉标、h2、副标题）在钉住框之上，随页面正常滚走。
- 钉住框 `.wf-pin`：高 `100vh`，上内边距 `calc(var(--header-h, 72px) + 16px)`，下内边距 24px；自上而下为步骤条（高 64px）、间距 24px、横向轨道。
- 步骤条：4 个标记分别位于内容宽的 12.5%、37.5%、62.5%、87.5%；标记 28px 圆，内为等宽数字；标记下 8px 为步骤标题（14px）。标记中心线上有一条从 12.5% 到 87.5% 的 SVG 尺寸线：底线 2px `--grid-line`，每个标记处 8px 竖向端点刻度；进度线 2px `--brand-blue`。
- 轨道 `.wf-track`：4 个面板横排，间距 48px。面板宽：≥ 1280px 时为"内容宽 − 96px"（下一个面板露出 48px）；1024–1279px 时为内容宽，右缘 48px 渐隐提示。
- 面板 `.wf-panel` 内两栏：左为文字栏（≥ 1280px 宽 320px，1024–1279px 宽 272px），右为场景窗口，栏距 48px / 32px。窗口宽 = 面板宽 − 文字栏 − 栏距（1440 宽时 784px，1280 时 624px，1024 时 528px）；窗口高 `clamp(380px, 100vh − 200px, 560px)`。
- 文字栏自上而下：标签（13px 等宽，`--brand-blue`）、h3、正文（17px）、"写到哪里"小标题与路径芯片（13px 等宽，`--blue-tint` 底，可换行）、文档链接。
- 场景窗口：1px `--line` 边框、12px 圆角、`--shadow-workbench`；标题栏 36px（左品牌字标与"智通数工AI · 示例会话"，右"示例"徽标、暂停/播放、重播两个 28px 图标按钮，命中区 44px）；正文区内边距 16px；底部 44px 输入条（占位文字，不可输入）。窗口内正文 14px、工具条与芯片 13px、等宽 13px。

**平板（768–1023px）与手机（≤ 767px），以及桌面上不满足钉住条件时**：纵向时间线。

- `<ol>` 左侧竖轨：平板 x = 23px，手机 x = 15px；底线 2px `--grid-line`，进度线 2px `--brand-blue`。标记 32px（平板）/ 28px（手机）圆，与轨对齐。
- 每步内容左缩进：平板 64px、手机 48px；步与步间距 64px（手机 56px）。每步先文字后场景窗口。
- 场景窗口宽：平板 `min(100%, 640px)`，手机 100%；高随内容（消息列不平移，全部展开）。手机上项目列表卡只显示最后 4 行加一行"另 5 个目录"；推送清单把 3 个成果文件合并为一行"成果/ 3 个文件 1.3 MiB"；页边标注内嵌。

### 1.4 组件与数据

```ts
// src/data/workflow.ts
export type StepId = 'import' | 'open' | 'task' | 'archive';

export interface WorkflowStep {
  id: StepId;
  label: '第一步' | '第二步' | '第三步' | '第四步';
  title: string;
  body: string;
  writes: { text: string; mono: boolean }[];   // "写到哪里"芯片
  doc: { text: string; href: string };          // href 必须在 06 章路由表内
  scene: SceneBeat[];
  outcome: string;
}

export type ResultStatus = 'ok' | 'partial' | 'empty' | 'insufficient';

export type SceneBeat =
  | { kind: 'drop'; gap: number; file: string; size: string }
  | { kind: 'user'; gap: number; text: string; attachment?: string }
  | { kind: 'tool'; gap: number; label: string; command: string; run: number; ms: number; result?: string }
  | { kind: 'stream'; gap: number; text: string }
  | { kind: 'status'; gap: number; status: ResultStatus; counts?: { warn?: number; info?: number }; manual?: boolean; lines?: string[] }
  | { kind: 'card'; gap: number; card: 'projects' | 'inventory' | 'reconcile' | 'files' }
  | { kind: 'ask'; gap: number; title: string; lines: string[]; options: [string, string]; pick: 0 | 1 }
  | { kind: 'push'; gap: number; title: string; rows: { path: string; size: string; note?: string }[] }
  | { kind: 'diff'; gap: number; file: '项目说明.md' | '案例索引.md' }
  | { kind: 'note'; gap: number; title: string; rows: { field: string; value: string }[]; footnote: string }
  | { kind: 'outcome'; gap: number; text: string };
```

- 核对卡、核对相关文字里的每个数从 02 章使用的同一份 §8.2 常量导入（`src/data/demo.ts`），不在 `workflow.ts` 重复书写字面量。
- `WorkflowSection.vue` 渲染标题与 `<ol class="wf-steps">`；每个 `<li class="wf-panel">` 内含 `WfPanel`（文字栏）与 `WfScene`（窗口外壳，props：`step: WorkflowStep`、`index: number`、`mode: 'pinned' | 'stacked'`）。四个场景组件只负责把 `scene` 节拍渲染成终态 DOM，并导出 `build(tl: gsap.core.Timeline): void` 往时间线上排节拍。
- 场景内的选项、按钮、文件条全部用非交互元素（`<span>`、`<div>`），只有标题栏的暂停/播放与重播是 `<button>`。
- 若 02 章定义了产出文件条或确认提问卡组件，场景复用之，不另写。

### 1.5 交互与动效

**钉住与推进**（`useWorkflowPin.ts`，在 `gsap.matchMedia()` 的钉住条件内创建，条件不满足时自动还原）：

```ts
const stepX = (i: number) => i * (panelWidth() + 48);
const tl = gsap.timeline({ defaults: { ease: EASE.inOut } });
tl.addLabel('s1', 0);
for (let i = 1; i <= 3; i++) {
  const at = 0.3 + (i - 1) * 1.2;                       // 每段先停 0.3，再移 0.9
  tl.to(track, { x: () => -stepX(i), duration: 0.9 }, at)
    .to(panels[i - 1], { opacity: 0.32, scale: 0.97, duration: 0.9 }, at)
    .fromTo(panels[i], { opacity: 0.32, scale: 0.97 }, { opacity: 1, scale: 1, duration: 0.9 }, at)
    .fromTo(progressLine, { drawSVG: `0% ${((i - 1) / 3) * 100}%` },
            { drawSVG: `0% ${(i / 3) * 100}%`, duration: 0.9, ease: EASE.linear }, at)
    .addLabel(`s${i + 1}`, at + 0.9);
}
tl.to({}, { duration: 0.3 });                           // 末尾停 0.3，总长 3.9
ScrollTrigger.create({
  trigger: pinFrame, start: 'top top',
  end: () => `+=${Math.round(innerHeight * 3.2)}`,
  pin: true, scrub: SCRUB.damp, anticipatePin: 1, invalidateOnRefresh: true, animation: tl,
  onUpdate: () => setActive(nearestLabelIndex(tl.time())),   // 用平滑后的时间，与画面一致
});
```

- 初始：面板 2–4 `opacity 0.32, scale 0.97`，进度线 `drawSVG: '0% 0%'`。只动 `transform`、`opacity`、`stroke-dashoffset`。
- 当前步骤变化时：对应标记 `aria-current="step"`；标记状态——未到：白底、1px `--line` 边、`--text-muted` 数字；当前：`--brand-blue` 底、白字、外圈 4px `rgba(6,102,245,.16)`，切换 `DUR.short`；已过：`--brand-navy` 底、白色对勾。
- **吸附由 Lenis 驱动**，不用 ScrollTrigger 的 `snap`（避免两套滚动动画竞争）：Lenis `scroll` 事件后 160 ms 无新事件、且 `|lenis.velocity| < 0.1`、且当前位置在钉住区间内时，取所在两标签对应的滚动位置 a < b 与比例 p = (cur − a)/(b − a)；向下滚动时 p ≥ 0.12 吸到 b，否则回 a；向上滚动时 p ≤ 0.88 吸到 a，否则回 b。调用 `lenis.scrollTo(target, { duration: clamp(0.35, |Δ| / innerHeight × 0.9, 0.8), easing: t => t < .5 ? 2*t*t : 1 - Math.pow(-2*t + 2, 2) / 2 })`。标签 n 的滚动位置 = `st.start + label_n / 3.9 × (st.end − st.start)`。
- 步骤标记是 `<button>`，带 `v-magnetic`；点击标记 n → `lenis.scrollTo(标签 n 的位置, { duration: 1.0 })`，焦点留在标记上。
- 焦点进入某面板（Tab 到文档链接或场景按钮）而该面板不是当前步骤时，同样滚到该标签。

**场景播放**：

- 每个场景一条 GSAP 时间线（`build()` 排出），由一个 `useAutoplay` 实例管理暂停原因，`hold: Infinity`（播完停在终态，不前进、不循环）。
- 钉住模式：某步第一次成为当前步骤时开始播放；不是当前步骤时以 `offscreen` 原因暂停，回来后从原位置继续；已播完的场景保持终态。纵向模式：场景窗口可见比例 ≥ 0.35 时开始（`useInView`），离开暂停。
- `hover`：指针进入窗口暂停，离开 600 ms 后继续。`focus`：焦点在窗口按钮上时暂停。`hidden`：页面不可见。
- 暂停/播放按钮切换 `user` 原因；重播：时间线 `progress(0)` 后播放，并清除 `user` 原因。播完后暂停/播放按钮变为禁用，只留重播。

**纵向时间线**：进度线是 `.wf-rail-progress`（`transform-origin: top`），`scaleY 0 → 1`，ScrollTrigger `trigger: ol`、`start: 'top 65%'`、`end: 'bottom 65%'`、`scrub: SCRUB.soft`。标记在进度线经过时切换为"已过"，`DUR.short`。每步文字按 `useReveal` 的 `block` 入场，场景窗口 `block` 入场，延后 0.08 s。

**入场**：h2 `data-reveal="heading"`，副标题 `block`；钉住模式下步骤条在钉住框进入视口时整体 `block` 入场，进度线底线 DrawSVG `0% → 100%`，`DUR.long`，`EASE.out`。

### 1.6 降级

- **默认 CSS 是纵向时间线**：预渲染 HTML 里四步都是纵向排列、场景是终态（全部消息可见、消息列不平移），无 JS 或 GSAP 加载失败时就是这个样子。JS 在钉住条件满足时给 `#workflow` 加 `.wf--pinned`，CSS 才切换到横向轨道；`gsap.matchMedia` 还原时移除该类。
- 减少动效：任何宽度都用纵向时间线；不钉住、不 scrub；进度线全长；场景直接显示终态，暂停/播放与重播按钮不渲染；入场按 00 章 §5.6。
- 打印：`@media print` 强制纵向、终态，隐藏场景按钮。
- 视口高 < 580px 的桌面：纵向时间线。

### 1.7 无障碍

- 步骤条 `<ol aria-label="使用流程四步">`，标记按钮 `aria-label="第 N 步：<标题>"`，当前步骤 `aria-current="step"`。
- 场景容器 `role="group"`、`aria-roledescription="示例"`、`aria-label="第 N 步示例：<标题>"`；消息列 `aria-live="off"`。DOM 内始终是终态全文（节拍只改 `opacity`/`transform`，不用 `display: none`），读屏读到的是完整对话。
- 场景内除两个按钮外没有可聚焦元素；示意指针 `aria-hidden="true"`。
- 键盘用户按 Tab 依次经过：步骤标记 1–4 → 第一步文字栏链接 → 第一步场景按钮 → 第二步……；焦点进入面板时滚动到该步（§1.5）。

### 1.8 验收标准

| 编号 | 标准 |
|---|---|
| AC-05-01 | 禁用 JS 访问 `/`：`#workflow` 内可读到四步的标签、标题、正文、写入芯片、文档链接，以及四个场景的全部终态文字 |
| AC-05-02 | 1440×900、未减少动效：滚到 `.wf-pin` 顶部时开始钉住；钉住期间页面滚动距离 = `round(3.2 × innerHeight)` ± 2px |
| AC-05-03 | 在钉住区间内停止滚动 160 ms 后，页面吸附到 §1.5 规则选出的标签位置，误差 ≤ 2px，吸附用时 ≤ 0.8 s |
| AC-05-04 | 位于标签 n 时，只有第 n 个标记带 `aria-current="step"`；进度线已画长度 = (n − 1)/3 × 全长，误差 ≤ 1% |
| AC-05-05 | 位于标签 n 时，面板 n `opacity` = 1、`scale` = 1，其余面板 `opacity` = 0.32 |
| AC-05-06 | 场景 n 的时间线在第 n 步第一次成为当前步骤前 `progress()` 为 0；成为当前步骤后开始推进 |
| AC-05-07 | 指针进入正在播放的场景窗口，时间线在 1 帧内暂停；离开 600 ms 后从同一位置继续（`time()` 差 < 0.05 s） |
| AC-05-08 | 暂停/播放按钮的文字与 `aria-label` 在"暂停示例 / 播放示例"间切换；播完后该按钮 `disabled` |
| AC-05-09 | 点"重播本步"：时间线回到 0 并播放到结束 |
| AC-05-10 | 场景播放中滚到另一步：原场景暂停；滚回后从原位置继续 |
| AC-05-11 | 场景一第 3 拍 result 与 `renderImport` 对示例包的输出逐字相同（vitest 快照：用 `config-import` 的 `parsePackage` 解析示例包，按 `renderImport` 的模板拼出字符串后比对） |
| AC-05-12 | 场景 DOM 里不出现任何 `AKLT` 开头的串或密钥样式的值；出现 `ZT_TOS_ACCESS_KEY_ID`、`ZT_TOS_SECRET_ACCESS_KEY` 与 ● |
| AC-05-13 | 场景二的盘点数字与 §0.1 一致：7 / 3 / 1 / 3，42.86% = round(3/7)，57.14% = round(4/7)（vitest 断言） |
| AC-05-14 | 场景三的金额、比例、行数全部来自 `demo.ts` 的 §8.2 常量（vitest 检查 `workflow.ts` 不含这些数的字面量） |
| AC-05-15 | 场景四案例索引新行 8 列，列序同模板；成果链接 = `项目/2026-007-滨江综合办公楼/成果/`；1,592.67 = round(29,623,713.84 ÷ 18,600.00, 2) |
| AC-05-16 | 1024×700（innerHeight ≥ 580）钉住；1024×560 不钉住、显示纵向时间线 |
| AC-05-17 | 390 与 768 宽：无钉住；竖轨进度线 `scaleY` 随滚动增长；每个场景在窗口可见 ≥ 35% 时开始播放 |
| AC-05-18 | 减少动效：任何宽度都是纵向时间线、场景为终态、无暂停与重播按钮、进度线全长 |
| AC-05-19 | 点击步骤标记 3：滚动结束时第 3 步为当前步骤，焦点仍在该标记 |
| AC-05-20 | 从第 1 步用 Tab 走到第 2 步的文档链接：钉住进度移到标签 s2 |
| AC-05-21 | 四个文档链接都解析到 06 章路由表中的预渲染页面（00 章 §12 死链检查） |
| AC-05-22 | Chrome Performance 录制钉住区间的滚动：无 > 50 ms 长任务；轨道与面板的补间不触发 Layout |
| AC-05-23 | 打印预览：四步纵向、场景终态、无场景按钮 |
| AC-05-24 | 场景窗口内文字最小 12px；场景中除两个按钮外 `tabindex` ≥ 0 的元素数为 0 |

## 2. 数据与复核 `#trust`

### 2.1 目的

用一张会动的数据流图说明：资料在公司桶里，哪些内容会发给模型，金额在哪里算，凭据停在哪里，结果交给谁签发；四条原则与图互相指认。

### 2.2 文案

| 位置 | 文案 |
|---|---|
| 眉标 | 数据与复核 |
| h2 `#trust-title` | 数据在您自己的桶里，数字有出处 |
| 副标题 | 四条原则，写进产品的工作方式。 |
| 图 `<title>` | 数据流向示意 |
| 图 `<desc>` | 公司存储桶、工程师电脑、模型服务与人工复核之间，五类内容的去向。 |
| 模型说明（`figcaption`，图下方，始终可见） | 模型说明：对话中读取的文件内容（包括交给模型看的扫描页和图纸图片）会作为对话上下文发送给所配置的模型服务。默认模型为 DeepSeek V4.1 Flash，默认连接 DeepSeek 官方接口，也可改为贵司指定的 OpenAI 兼容接口；部署方式在交付配置时说明。 |

图内文字（SVG `<text>`）：

| 元素 | 文字 |
|---|---|
| 公司存储桶 | 公司存储桶 ／ 火山引擎 TOS ／ 开启版本控制 ／ `项目/` ／ `知识库/` ／ `案例索引.md` |
| 工程师电脑 | 工程师电脑 ／ 智通数工AI 桌面版 |
| 本机缓存（车道） | 本机缓存 ／ `~/zhitong` · 只缓存用到的文件 |
| 脚本计算（车道） | 脚本计算 ／ 内置 Python · 金额与数量 |
| 凭据存储（车道） | 凭据存储 ／ TOS 密钥 · 模型 API Key |
| 模型服务 | 模型服务 ／ DeepSeek V4.1 Flash ／ 阅读 · 判断 · 分类 ／ 摘录 · 写作 ／ 不计算金额 |
| 人工复核 | 人工复核与签发 ／ 需人工确认 · 待核 · 由人签发 |
| 连线标签 | 按需拉取 + `tos_pull`；回读校验 + `tos_push`；仅用于 + 直连公司桶（点线）；对话上下文；回复文字；不进对话（锁下方） |

图例（按钮，见 §2.5）：

| 类型 | 图形 | 颜色 | 文字 |
|---|---|---|---|
| `file` | 20×14 圆角矩形，内两条横线 | `--brand-blue` | 文件内容 |
| `amount` | 半径 9 的圆，内白色"¥" | `--success-text` | 金额与数量（只在脚本里算） |
| `credential` | 22×12 钥匙 | `--warning-text` | 凭据（不离开本机） |
| `reply` | 20×14 圆角矩形，内三条短横线 | `--brand-navy` | 模型回复与初稿 |
| `result` | 20×14 圆角矩形，内对勾 | `--blue-600` | 成果回桶 |
| 线型 | 实线 / 虚线 / 点线 | `--ink` 40% | 实线：传送内容；虚线：脚本结果原值，模型只转述；点线：本机用凭据连接，不传内容 |

四条原则（文案稿原文；卡片编号等宽）：

| # | 标题 | 正文 | 关联图元（§2.5） |
|---|---|---|---|
| 01 | 数据归客户所有 | 项目资料、成果和知识库都存放在公司自己的火山引擎 TOS 桶里。桶开启版本控制；多人共用时不加锁，出现覆盖通过版本回退恢复。 | `owned` |
| 02 | 凭据不离开本机 | 访问桶所需的密钥由配置包导入，保存在本机的凭据存储中，导入时不回显。工程师在自己的电脑上直接读写公司的桶。 | `credential` |
| 03 | 每个数字有出处 | 模型不算钱，金额和数量由脚本计算。报告中的数字必须在送入的资料里逐字找到；金额带出处；找不到出处的数字会被标出，不会被悄悄放行。 | `source` |
| 04 | AI 结果需人工确认 | 金额与数量一律标注"需人工确认"。脚本失败时以错误结束，不会输出"成功但为空"；状态和警示项如实转述。最终签发由人负责。 | `review` |

卡片底部提示（仅精确指针设备显示，13px）：悬停查看图中对应位置。

节点说明卡（`ZtPopover`，标准结构；两行的标签按节点给出；底部动作只有"读文档" → `/docs/security/`）：

| 节点 | 标题 | 一句话 | 第一行 | 第二行 |
|---|---|---|---|---|
| `tos` | 公司存储桶（TOS） | 项目资料、成果和知识库存放在贵司自己的火山引擎对象存储（TOS）桶里，由贵司持有。 | 存放：`项目/`、`知识库/`、`案例索引.md`；桶开启版本控制，被覆盖的版本可以回退。 | 进出：工程师电脑按需拉取单个文件；推送后回读大小与 SHA-256 校验。 |
| `cache` | 本机缓存 | 只缓存用到的文件，目录与桶同构。 | 位置：`~/zhitong`（Windows `%USERPROFILE%\zhitong`），默认上限 20 GiB，满了先淘汰最久未用且未改动的文件。 | 规则：本机改过、未推送的文件不会被拉取覆盖；图纸与压缩包不随目录自动拉取。 |
| `script` | 脚本计算 | 金额、数量、核对和指标由安装包内置的 Python 脚本计算。 | 产出：结果 JSON（状态、告警、`needs_manual: true`）与 xlsx 工作底稿，写进项目的 `工作/`。 | 与模型：结果摘要会作为对话上下文交给模型转述；按技能规则，模型只引用原值，不做加减乘除。 |
| `cred` | 本机凭据存储 | 访问桶的密钥由配置包导入，保存在本机，仅当前用户可读。 | 存放：TOS 访问密钥（引用名 `ZT_TOS_ACCESS_KEY_ID`、`ZT_TOS_SECRET_ACCESS_KEY`）与模型 API Key。 | 去向：TOS 密钥只供本机的 TOS 工具连接公司桶，导入结果与报错里不出现密钥值，也不写进对话；模型 API Key 只用于向所配置的模型服务验证身份。 |
| `model` | 模型服务 · DeepSeek V4.1 Flash | 负责阅读、判断、分类、摘录和写作，不负责算钱。 | 收到：对话内容，以及对话中读取的文件内容、扫描页与图纸图片、脚本结果摘要。 | 送出：文字回复与报告初稿；报告里的金额先写成事实编号，由脚本换成原值并带出处。 |
| `review` | 人工复核与签发 | 结果是供您复核的初稿，签发由人负责。 | 标注：金额与数量标"需人工确认"；报告中未核实的程序性陈述标"待核"；导出的 Word 页眉写明"AI 初稿，金额未经人工核对，不得直接出具"。 | 记录：投控异常的"确认 / 误报"决策追加记录在项目 `工作/` 目录。 |

读屏用的流向列表（`<ol class="sr-only">`，紧跟 SVG）：

1. 文件内容：从公司存储桶按需拉取到本机缓存；对话中读取时，作为对话上下文发送给模型服务。
2. 金额与数量：只在本机脚本中计算，结果写进工作底稿，交人工复核；结果摘要作为上下文交给模型转述。
3. 凭据：保存在本机凭据存储，只用于连接公司存储桶和模型服务，不写进对话。
4. 模型回复：判断、摘录与写作的文字回到对话，作为初稿交人工复核。
5. 成果：推送回公司存储桶，并回读校验。

### 2.3 布局

- **桌面（≥ 1024px）**：标题占左 7 列；其下图占满 12 列，`max-width: 1120px` 居中，使用宽几何（viewBox `0 0 1040 576`）；图下 24px 为图例（一行，项间距 24px），再下 16px 为模型说明（14px，`--text-muted`，最大宽 880px，左侧 16px 信息图标）；再下 64px 为四张原则卡，每张 3 列。
- **平板（768–1023px）**：图用窄几何（viewBox `0 0 360 656`），`max-width: 480px` 居中；图例 3 列网格；原则卡 2×2。
- **手机（≤ 767px）**：窄几何，宽 100%；图例 2 列网格；原则卡单列。
- SVG 内字号（用户单位）：宽几何标题 20、正文与连线标签 15、等宽 15；窄几何标题 16、正文 13。由此 1024 宽时最小渲染字号 12px，390 宽时 12.6px。
- 节点覆盖按钮：每个节点上叠一个透明 `<button>`，用百分比定位（left = x ÷ viewBox 宽，top = y ÷ viewBox 高，宽高同理），与 SVG 同比例缩放；聚焦时显示 `--focus-ring`，圆角与节点一致。

**宽几何**（`trust-geometry.ts` 的 `WIDE`）：

| 元素 | 几何 |
|---|---|
| `tos` | x 16, y 160, w 224, h 208, rx 12 |
| 电脑外框 | x 336, y 88, w 368, h 320, rx 14；标题基线 (360, 120)，副标题 (360, 144) |
| `cache` 车道 | x 360, y 160, w 264, h 64, rx 8；文字 (376, 188)、(376, 210) |
| `script` 车道 | x 360, y 240, w 264, h 64；文字 (376, 268)、(376, 290) |
| `cred` 车道 | x 360, y 320, w 264, h 64；文字 (376, 348)、(376, 370) |
| `model` | x 800, y 160, w 224, h 208, rx 12；文字起点 x 816，基线 196 / 220 / 260 / 284 / 332 |
| `review` | x 336, y 472, w 368, h 88, rx 12；文字 (360, 506)、(360, 534) |
| 锁 | 中心 (648, 352)，16×20 |
| `pull` | `M240 180 H360`，标签 (300, 152)、(300, 170) |
| `push` | `M360 204 H240`，标签 (300, 224)、(300, 242) |
| `credTos`（点线） | `M360 352 H240`，标签 (300, 326)、(300, 342) |
| `ctxFile` | `M624 192 H656 Q664 192 664 200 V224 Q664 232 672 232 H800`，标签"对话上下文" (736, 222) |
| `ctxSum`（虚线） | `M624 272 H656 Q664 272 664 264 V240 Q664 232 672 232 H800` |
| `credStub` | `M624 352 H636`，止于锁 |
| `reply` | `M800 292 H692 Q684 292 684 300 V472`，标签"回复文字" (742, 284) |
| `review` 路 | `M360 272 H352 Q344 272 344 280 V472` |
| 锁下标签 | "不进对话" (648, 392) |

**窄几何**（`NARROW`，viewBox `0 0 360 656`）：

| 元素 | 几何 |
|---|---|
| `tos` | x 16, y 16, w 328, h 80；文字 (32, 48)、(32, 72) |
| 电脑外框 | x 16, y 152, w 328, h 320；标题 (32, 180) |
| `cache` / `script` / `cred` 车道 | x 32, w 232, h 64；y 208 / 288 / 368 |
| `review` | x 16, y 544, w 144, h 96 |
| `model` | x 200, y 544, w 144, h 96 |
| 锁 | 中心 (284, 400) |
| `pull` | `M120 96 V208`，标签"按需拉取" (112, 128) 右对齐 |
| `push` | `M152 208 V96`，标签"回读校验" (160, 128) |
| `ctxFile` | `M264 240 H288 Q296 240 296 248 V544` |
| `ctxSum`（虚线） | `M264 320 H288 Q296 320 296 328 V544` |
| `credStub` | `M264 400 H276` |
| `reply` | `M200 592 H160` |
| `review` 路 | `M32 320 H28 Q24 320 24 328 V544` |
| `credTos` | 不画；`pull`/`push` 标签旁加 12×12 钥匙图标 |

### 2.4 组件与数据

```ts
// src/components/trust/trust-geometry.ts
export type TrustNodeId = 'tos' | 'cache' | 'script' | 'cred' | 'model' | 'review';
export type TrustPathId = 'pull' | 'push' | 'credTos' | 'ctxFile' | 'ctxSum' | 'credStub' | 'reply' | 'reviewPath';
export type PacketKind = 'file' | 'amount' | 'amountEcho' | 'credential' | 'reply' | 'result';
// 原则卡用前四个键；图例用后四个键，图例"凭据"复用 credential
export type FocusKey = 'owned' | 'credential' | 'source' | 'review' | 'file' | 'amount' | 'reply' | 'result';

export interface TrustGeometry {
  viewBox: [0, 0, number, number];
  nodes: Record<TrustNodeId, { x: number; y: number; w: number; h: number; rx: number }>;
  paths: Record<TrustPathId, { d: string; line: 'solid' | 'dashed' | 'dotted' } | null>; // null = 本几何不画
  labels: { at: [number, number]; anchor: 'start' | 'middle' | 'end'; text: string; mono?: boolean }[];
  lock: [number, number];
  rest: Record<PacketKind, [number, number]>;  // 减少动效与无 JS 时数据包的静止位置
}

export const FOCUS: Record<FocusKey, { nodes: TrustNodeId[]; paths: TrustPathId[]; packets: PacketKind[] }> = {
  owned:      { nodes: ['tos', 'cache'],     paths: ['pull', 'push'],                 packets: ['file', 'result'] },
  credential: { nodes: ['cred'],             paths: ['credStub', 'credTos'],          packets: ['credential'] },
  source:     { nodes: ['script', 'review'], paths: ['reviewPath', 'ctxSum'],         packets: ['amount', 'amountEcho'] },
  review:     { nodes: ['review', 'model'],  paths: ['reply', 'reviewPath'],          packets: ['reply', 'amount'] },
  file:       { nodes: ['tos', 'cache', 'model'], paths: ['pull', 'ctxFile'],         packets: ['file'] },
  amount:     { nodes: ['script', 'review'], paths: ['reviewPath', 'ctxSum'],         packets: ['amount', 'amountEcho'] },
  reply:      { nodes: ['model', 'review'],  paths: ['reply'],                        packets: ['reply'] },
  result:     { nodes: ['cache', 'tos'],     paths: ['push'],                         packets: ['result'] },
};
```

静止位置 `rest`：宽几何 `file` (736, 232)、`amount` (344, 400)、`amountEcho` (664, 252)、`credential` (630, 352)、`reply` (684, 400)、`result` (300, 204)；窄几何 `file` (296, 500)、`amount` (24, 480)、`amountEcho` (280, 320)、`credential` (270, 400)、`reply` (180, 592)、`result` (152, 150)。

- `TrustSection.vue`：标题、`TrustFlow`、图例、模型说明、原则卡；持有 `focus: Ref<FocusKey | null>`。
- `TrustFlow.vue`：props `geometry: TrustGeometry`、`focus: FocusKey | null`；预渲染时输出完整 SVG（节点、连线、标签、锁、处于 `rest` 的数据包）与覆盖按钮。宽窄两套 SVG 都输出，CSS 按断点显示其一（`display: none` 的那套不建时间线）。
- 节点覆盖按钮用原生 `popovertarget` 指向各自的 `ZtPopover`，所以水合前点击也能打开（浏览器默认居中定位），水合后由 `@floating-ui/dom` 定位。

### 2.5 交互与动效

**首次入场**（`useInView`，阈值 0.35，只一次）：节点 `opacity 0→1, y 8→0`，`DUR.base`，`EASE.out`，`stagger: STAGGER.base`（顺序 tos、电脑外框、三车道、model、review）；连线 DrawSVG `0% → 100%`，`DUR.long`，`EASE.out`，`stagger: STAGGER.base`，与节点同起点后 0.2 s；全部结束 0.4 s 后开始循环。

**循环时间线 `flow`**（`repeat: -1`，`repeatDelay: 1.5`，一圈 9.2 s；数据包用 `MotionPathPlugin`，`align: <path>`、`alignOrigin: [0.5, 0.5]`、`autoRotate: false`）：

| 时间 | 对象 | 动作 |
|---|---|---|
| 0.00 | `file` | 出现在 `pull` 起点，`opacity 0→1` 0.16 s；沿 `pull` 0.9 s `power1.inOut` |
| 0.90 | `cache` 车道 | 底色闪 `--blue-050` 0.5 s 后回原色 |
| 1.25 | `file` | 沿 `ctxFile` 1.3 s `power1.inOut` |
| 2.55 | `model` | 边框 `stroke-width 1.5 → 3 → 1.5`，0.45 s；`file` 0.2 s 淡出 |
| 1.00 | `credential` | 在 `credStub` 起点 `scale 0.6→1`，0.28 s，`back.out(2)` |
| 1.28 | `credential` | 沿 `credStub` 0.45 s `power2.in` |
| 1.73 | 锁 | `keyframes: { x: [0, -3, 3, -2, 2, 0] }` 0.36 s；填色闪 `--danger-text` 0.36 s；`credential` `x −6`、`opacity →0` 0.3 s；"不进对话"标签 `opacity 0→1` 0.2 s，停留到 3.60 后 0.2 s 淡出 |
| 3.00 | `script` 车道 | 底色闪 `--green-tint` 0.5 s；`amount` 在车道左缘出现 0.2 s |
| 3.20 | `amount` | 沿 `reviewPath` 1.1 s `power1.inOut`；4.30 `review` 边框脉冲 0.45 s |
| 3.30 | `amountEcho` | 虚线圆，`opacity 0.9`，沿 `ctxSum` 1.3 s；4.60 `model` 小脉冲（`stroke-width 1.5 → 2.2 → 1.5`） |
| 5.00 | `reply` | 沿 `reply` 1.4 s `power1.inOut`；6.40 `review` 脉冲 |
| 6.80 | `result` | 在 `cache` 车道左缘出现；沿 `push` 0.9 s；7.70 `tos` 脉冲，节点右上角 14px 对勾 `scale 0→1` 0.28 s，停留 0.8 s 后淡出 |

窄几何用同一时间表，换成窄几何的路径。`amount` 永远只走 `reviewPath`；去往模型的只有虚线 `amountEcho`；`credential` 只走 `credStub`。

**聚焦模式**：锁与"不进对话"标签归入 `credential` 键；电脑外框与连线标签随其所属节点或连线。`focus` 非空时，不在 `FOCUS[focus]` 里的节点、连线、标签、数据包加 `.is-dim`（`opacity: 0.28`，`transition: opacity var(--dur-short) var(--ease-out)`）；循环照常进行。触发：

- 原则卡：`pointerenter` / `focusin` 设为该卡的键，`pointerleave` / `focusout` 清空；触屏上点卡切换（卡为 `<button aria-pressed>`），再点或点别处清空。
- 图例项：同上，键为对应 `PacketKind`（`amountEcho` 归入 `amount`）。
- 节点说明卡打开时设为包含该节点的键（`tos`→`owned`，`cache`→`file`，`script`→`source`，`cred`→`credential`，`model`→`review`，`review`→`review`），关闭时清空。

**原则卡**：`useSpotlight`；`data-reveal="stagger"` 入场。

**暂停**：循环挂在 `useInView`（阈值 0.35）上，离开视口或页面不可见即暂停；说明卡打开时不暂停。

### 2.6 降级

- 无 JS：预渲染 SVG 完整，数据包在 `rest` 位置静止，图例、模型说明、原则卡都在；节点按钮靠 `popovertarget` 仍能打开说明卡。
- 减少动效：不建 `flow` 与入场时间线；数据包在 `rest`；聚焦模式保留，但不带过渡。
- 动效块加载失败：同无 JS。
- 打印：SVG 静止，说明卡不打印。

### 2.7 无障碍

- `<figure>` 包 SVG、覆盖按钮、读屏流向列表、图例与 `figcaption`；SVG `role="img"`、`aria-labelledby` 指向 `<title>` 与 `<desc>`；SVG 内文字对读屏隐藏（由 `role="img"` 收起），事实由流向列表与说明卡提供。
- 节点按钮 `aria-label="<节点标题>：查看说明"`，`aria-expanded`、`aria-controls` 由 `ZtPopover` 管理；Esc 关闭、焦点回到按钮。
- 图例项与原则卡为 `<button type="button" aria-pressed>`；`aria-describedby` 指向图 `<desc>`。
- 五类数据包靠形状区分，颜色之外另有图例文字；节点描边与背景对比 ≥ 3:1（WCAG 1.4.11）。

### 2.8 验收标准

| 编号 | 标准 |
|---|---|
| AC-05-25 | ≥ 1024 宽显示 viewBox `0 0 1040 576` 的 SVG；≤ 1023 宽显示 `0 0 360 656` 的 SVG；另一套 `display: none` 且没有时间线 |
| AC-05-26 | 1024、768、390 三个宽度下，图内最小文字的渲染高度 ≥ 12px |
| AC-05-27 | `flow` 只在图可见 ≥ 35% 时推进；滚出视口或切到后台标签页时 `paused()` 为 true |
| AC-05-28 | 一圈内逐帧采样：`credential` 数据包的中心 x 不超过锁的左缘（宽几何 640，窄几何 276） |
| AC-05-29 | 一圈内逐帧采样：实心 `amount` 数据包始终在 `reviewPath` 上，从未出现在 `model` 节点矩形内；进入 `model` 的只有 `file`、`amountEcho` |
| AC-05-30 | `credential` 到达锁时锁抖动 0.36 s，"不进对话"标签可见时长 ≥ 1.6 s |
| AC-05-31 | 6 个节点按钮各自打开对应 `ZtPopover`，文字与 §2.2 表逐字一致；Esc 关闭后焦点回到该按钮 |
| AC-05-32 | 禁用 JS：点击节点按钮能打开说明卡（原生 popover） |
| AC-05-33 | 悬停原则卡 02：锁、`cred` 车道、`credStub`、`credTos` 保持 `opacity 1`，其余图元 0.28，过渡 ≤ 0.3 s；移开后全部恢复 |
| AC-05-34 | 触屏模拟：点原则卡切换 `aria-pressed` 与聚焦模式；再点恢复 |
| AC-05-35 | 悬停图例"金额与数量"：`script`、`review`、`reviewPath`、`ctxSum` 保持高亮 |
| AC-05-36 | 模型说明文字与 §2.2 逐字一致，在所有宽度下无交互即可见 |
| AC-05-37 | 减少动效：无数据包运动，数据包位于 `rest` 坐标（±1 单位）；聚焦模式可用 |
| AC-05-38 | SVG 有 `role="img"`、`<title>`、`<desc>`；读屏流向列表 5 条，文字与 §2.2 一致 |
| AC-05-39 | 四张原则卡标题与正文与 §2.2 逐字一致 |
| AC-05-40 | axe-core：`#trust` 内 0 个 serious / critical；数据包与节点描边对比 ≥ 3:1 |

## 3. 安装与交付 `#install`

### 3.1 目的

让访客按自己的系统下载正确的安装包、核对文件、顺利完成第一次打开，并明白配置包是什么、从哪里来。

### 3.2 文案

| 位置 | 文案 |
|---|---|
| 眉标 | 安装与交付 |
| h2 `#install-title` | 装好、导入、开始用 |
| 副标题 | Mac 与 Windows 两个安装包，配置包由服务方交付。 |
| 安装包 h3 | 安装包 |
| 安装包正文 | 提供 Mac（.dmg，Apple 芯片）和 Windows（.exe，x64）安装包。安装包内含 Python 运行时、脚本依赖库和 DWG 转换组件，无需另行安装 Python。 |
| 版本行 | `v{version}` · `{date} 发布`（`date` 为 null 时"发布日期待定"）；`base` 不为 null 时版本行下加一行"安装后，"关于"中显示的程序版本为 {base}。" |
| 平台卡 | 名称、架构、适用说明、匹配标记"与您的电脑匹配"、文件行、下载按钮"下载 Mac 版 / 下载 Windows 版"（点击后 2.4 s 内为"已开始下载"）、"SHA256 校验值"块与复制、"下载 .sha256 文件"、展开块"首次打开与校验"（步骤与校验命令）、即将发布卡：全部与 01 章 §7.2 逐字相同 |
| 卡下链接 | 安装遇到问题？看安装说明 → `/docs/install/` |
| 手机与平板提示 | 与 01 章 §7.2 相同：您正在使用手机或平板。安装包需要在 Mac 或 Windows 电脑上安装，可以把本页链接发到电脑上打开。 + 按钮"复制页面链接"（本区复制 `location.origin + '/#install'`） |
| 配置包 h3 | 配置包 |
| 配置包正文 | 配置包是服务方按贵司环境整理的一个压缩文件（内含 `zhitong.config.json`），不随安装包分发，也不在本站提供下载。 |
| 配置包内容列表 | 公司名称 ／ 对象存储的地址、区域、桶名与目录前缀 ／ 访问密钥（导入后存入本机凭据存储） ／ 可选：SSH 主机别名、地址与私钥 ／ 可选：火山引擎 ve 的 profile 名（ve 自己的密钥由您在终端里单独设置，不放进配置包） |
| 配置包提醒 | 配置包含明文密钥：导入后请从下载目录删除，不要转发。更换密钥时，服务方发来新配置包，重新导入即可。 |
| 首次使用 h3 | 首次使用 |
| 首次使用正文 | 首次启动先在欢迎页填写模型 API Key（向贵司管理员或服务方获取，默认连接 DeepSeek 官方接口），再把配置包拖进对话，系统校验并写入本机配置，随后即可列出公司桶里的项目。本机只缓存用到的文件，目录与桶同构，缓存上限可配置，默认 20 GiB。 |
| 联系 h3 | 联系服务方（只在 01 章的 `hasContact` 为 true 时渲染） |
| 联系正文 | 安装包与配置包向服务方获取。 + `<dl>`，按 01 章 §8.3 的顺序与格式列出非空项 |
| 文档链接 | 读文档：导入配置包 → `/docs/config-package/` |
| 提示条（01 章 `useToast`） | 已复制 SHA256 校验值 ／ 已复制校验命令 ／ 已复制页面链接 ／ 复制失败，请手动选择文本 |

### 3.3 布局

- **桌面**：区块上下内边距 128px；深色面板 `.install-panel` 占内容宽，`--navy-900` 底、24px 圆角、内边距 72px 64px、`overflow: hidden`；面板内 12 列，左 5 列为眉标、h2、副标题、安装包、配置包、首次使用、联系服务方、文档链接；右 7 列为版本行与两张平台卡（上下排列，间距 16px）。
- **平板**：面板内边距 56px 48px，单列：标题 → 安装包 → 版本行 → 平台卡 → 配置包 → 首次使用 → 联系 → 文档链接。
- **手机**：面板通栏（左右贴边、无圆角），内边距 56px 20px，顺序同平板；平台卡内各行纵向堆叠，下载按钮宽 100%。
- **平台卡**：复用 01 章 `PlatformCard`（内部行序与校验值块见 01 章 §7.3），本区以 `surface="dark"` 渲染：卡底 `rgba(255,255,255,.06)`、1px `rgba(255,255,255,.16)` 边、16px 圆角、内边距 24px（手机 20px）；名称与文件行白色，适用说明与次要文字 `rgba(255,255,255,.76)`；校验值块底 `rgba(255,255,255,.08)`、字 `rgba(255,255,255,.92)`；匹配标记白字、`rgba(0,179,236,.28)` 底；匹配卡边框 `--brand-cyan`；即将发布卡 1px 虚线 `rgba(255,255,255,.28)` 边，徽标仍为 `--warning-bg` 底、`--warning-text` 字。下载按钮 `.button-white`（状态见 01 章 §9）。桌面两卡上下排列，间距 16px；卡下 16px 为"安装遇到问题？"链接。
- 面板内文字白色；次要文字 `rgba(255,255,255,.76)`；等宽值 `rgba(255,255,255,.88)`；聚焦环用 01 章 §9 的深色区聚焦环。
- **装饰插槽**：面板内第一个子元素 `<DecoInstallField>`，`position: absolute; inset: 0; z-index: 0; pointer-events: none; aria-hidden="true"`，尺寸随面板（桌面约 1248×760，平板约 672×1180，手机约 390×1480，以 `ResizeObserver` 取实际值）；内容层 `position: relative; z-index: 1`。07 章实现须满足：文字所在区域的装饰亮度不使白字对比低于 4.5:1；挂在 `useInView` 上；减少动效显示静态终帧；单块 ≤ 12 KB gzip。

### 3.4 组件与数据

数据仍来自 `public/downloads/releases.json` → `release-manifest.mjs` 校验 → `downloads.ts` 的 `release`，页面不写死版本、大小、哈希；`downloads.ts` 的改动以 01 章 §7.4 为准（`verify(file)`、`base` 等）。

本仓当前没有 `public/downloads/releases.json`，`downloads.ts` 的 `import` 会让构建失败。实现时先提交初始清单（之后由 `release-manifest.mjs stage` 填写各平台；不写 `base`，因为解析器不接受 `null`）：

```json
{
  "schema": 1,
  "product": "智通数工AI",
  "version": "1.0.0",
  "date": null,
  "notes": [],
  "platforms": {
    "mac-arm64": { "file": null, "sha256": null, "size": null, "notes": null },
    "win-x64": { "file": null, "sha256": null, "size": null, "notes": null }
  }
}
```

- 01 章 `PlatformCard.vue` 增加两个 prop：`surface: 'light' | 'dark'`（默认 `'light'`，弹层不变）；`magnetic: boolean`（默认 `false`，为 true 时下载按钮带 `v-magnetic`）。本区传 `surface="dark"`、`magnetic`。
- `ConfigPackageNote.vue`：配置包、首次使用两小节，纯展示，无 props。
- 平台识别：水合后调用一次 01 章 `lib/platform.ts`。结果为 `mac-arm64` / `win-x64` → 对应卡 `matched`；`mobile` → 版本行上方显示手机与平板提示；`null` → 无标记。两张卡始终都显示，任何宽度下顺序都不变（本区不随识别结果重排，避免水合后内容跳动）。

### 3.5 交互与动效

- 入场：h2 `heading`；左栏段落 `block`；两张平台卡 `stagger`。匹配状态在水合后设置：卡边框颜色过渡 `DUR.short`，匹配标记 `opacity 0→1, scale 0.9→1`，`DUR.short`，`EASE.out`；标记绝对定位在卡右上角，不引起布局位移。
- 下载按钮 `v-magnetic`（默认参数，偏移上限 10px）；点击后的按钮反馈、自动展开"首次打开与校验"、朗读"已开始下载 {file}"均按 01 章 §7.5（本区的朗读写入 `#page-status`）。
- 复制：01 章 `useCopy` + `useToast`，提示文字见 §3.2。
- "首次打开与校验"的展开收起按 01 章 §7.5；结束后调用 `refreshMotionLayout()`（200 ms 防抖），因为本区高度变化会移动其下 `#faq` 与页脚的触发位置。
- 即将发布卡：无下载按钮、无复制、无磁吸。

### 3.6 降级

- 无 JS：卡片、文件名、大小、完整 SHA256、下载链接、原生 `<details>` 的"首次打开与校验"都可用；无匹配标记；复制按钮不渲染（水合后插入，位置预留）。
- 剪贴板不可用：01 章 `useCopy` 的退路（选中文字 + 错误提示）。
- 减少动效：同 01 章 §7.6；无磁吸、无入场。

### 3.7 无障碍

- 平台区 `<ul aria-label="v{version} 安装包">`，每张卡 `<li>`；区内标题层级 h2（区块）→ h3（安装包、配置包、首次使用、联系服务方）→ h4（卡片名称）。
- 匹配标记是卡片标题内的文字，读屏读作"Mac，与您的电脑匹配"（同 01 章 §7.7）。
- "首次打开与校验"是原生 `<details>`/`<summary>`，脚本增强时保持原生语义。
- 提示条朗读按 01 章 §11（写入 `#page-status`）。

### 3.8 验收标准

| 编号 | 标准 |
|---|---|
| AC-05-41 | 本区的版本、日期、文件名、大小、SHA256 全部来自 `releases.json`；换夹具清单重建后页面随之变化（vitest 渲染断言） |
| AC-05-42 | 平台 `file` 为 null：该卡为即将发布卡，卡内没有 `<a>`、没有复制按钮、没有 `v-magnetic` |
| AC-05-43 | 下载链接 `href` = `/downloads/{file}` 且带 `download`；点击后按钮文字 2.4 s 内为"已开始下载"，"首次打开与校验"展开，`#page-status` 为"已开始下载 {file}" |
| AC-05-44 | 复制 SHA256：剪贴板为 64 位小写十六进制全文；提示条"已复制 SHA256 校验值" |
| AC-05-45 | 剪贴板 API 被拒绝：校验值文字被选中，提示条"复制失败，请手动选择文本" |
| AC-05-46 | UA 为 macOS Safari：Mac 卡有"与您的电脑匹配"与 `--brand-cyan` 边框，Windows 卡照常显示，两卡顺序不变 |
| AC-05-47 | UA 为 Windows：Windows 卡匹配；在 1440 与 390 宽度下两卡顺序都与无识别时相同 |
| AC-05-48 | UA 为 iPhone 或 Android：版本行上方出现手机与平板提示；"复制页面链接"复制 `location.origin + '/#install'`，提示条"已复制页面链接"；两张卡都在，均无匹配标记 |
| AC-05-49 | 预渲染 HTML 中没有匹配标记；匹配状态出现时 CLS 增量为 0 |
| AC-05-50 | 校验命令包含实际文件名，与 01 章 §7.2 的命令逐字一致 |
| AC-05-51 | "首次打开与校验"的步骤与 01 章获取弹层逐字一致（同一组件、同一数据） |
| AC-05-52 | 配置包小节列出 5 项内容与提醒；`#install` 内没有任何指向配置包的下载链接 |
| AC-05-53 | 清单有 `base` 时显示"安装后，"关于"中显示的程序版本为 {base}。"；无 `base` 时不显示 |
| AC-05-54 | `hasContact` 为 false 时本区没有"联系服务方"小节，也没有任何占位文字；为 true 时按 01 章 §8.3 列出非空项 |
| AC-05-55 | `<DecoInstallField>` 位于 `.install-panel` 内、`aria-hidden="true"`、`pointer-events: none`；装饰运行中截图上 axe 色彩对比 0 违规 |
| AC-05-56 | 触屏（`pointer: coarse`）下下载按钮无磁吸位移；精确指针下偏移 ≤ 10px |
| AC-05-57 | 键盘顺序：每张卡内为 下载 → 复制校验值 → .sha256 链接 → 首次打开与校验；Enter/Space 可展开收起 |
| AC-05-58 | 同一 `PlatformCard` 在 01 章获取弹层中仍以 `light` 渲染、无磁吸；本区 `dark` 卡内文字对比 ≥ 4.5:1 |

## 4. 常见问题 `#faq`

### 4.1 目的

回答访客最常问的八个问题，可按主题筛选、可直接链接到某一问。

### 4.2 文案

| 位置 | 文案 |
|---|---|
| 眉标 | 常见问题 |
| h2 `#faq-title` | 常见问题 |
| 副标题 | 安装、数据、结果与协作 |
| 筛选组 | `role="group" aria-label="按主题筛选"`；按钮"全部 8""安装 2""数据 2""结果 2""协作 2"（数字为等宽计数） |
| 筛选播报 | 显示 {n} 个问题：{主题}（"全部"时为"显示全部 8 个问题"） |
| 文档链接 | 在文档中查看更多 → `/docs/troubleshooting/` |
| 每问的复制链接 | 图标按钮，`aria-label="复制本问题的链接"`；提示条"已复制问题链接" |
| 每问的相关文档 | 相关文档：{页标题} → |

八问（显示顺序 = 文案稿顺序；"校正"列说明与文案稿的差异）：

| id | 主题 | 问 | 答 | 相关文档 | 校正与依据 |
|---|---|---|---|---|---|
| `calc` | 结果 | 它会替我算造价吗？ | 不会由模型算。金额与数量由脚本计算，规则和数据是普通文件，可以查看，也可以修改；脚本算出的金额与数量同样标注"需人工确认"。模型负责阅读资料、判断、分类、摘录和写作。 | 数据与安全 `/docs/security/` | 加"同样标注需人工确认"：`README.md` §4.2 结果契约 |
| `use-directly` | 结果 | AI 给出的结果能直接用吗？ | 不能不经确认直接用。金额与数量一律标注"需人工确认"，报告里未核实的程序性陈述标注"待核"，导出的 Word 页眉写明"AI 初稿，金额未经人工核对，不得直接出具"。结果是供您复核的初稿，签发由人负责。 | 结果状态与告警 `/docs/results/` | 加 Word 页眉与"程序性"：`zt-report/SKILL.md` §3、§6 |
| `data-location` | 数据 | 我们的资料会放到哪里？ | 放在贵司自己的火山引擎 TOS 桶里，由贵司持有；工程师电脑只缓存用到的文件。对话中读取的文件内容（包括交给模型看的扫描页和图纸图片）会作为对话上下文发送给所配置的模型服务。模型为 DeepSeek V4.1 Flash，默认连接 DeepSeek 官方接口，也可改为贵司指定的兼容接口，部署方式在交付配置时说明。 | 数据与安全 `/docs/security/` | 加本机缓存、图片、默认接口：`tool-tos/README.md`、`README.md` §4、`INSTALL.md` 第四部分 |
| `concurrent` | 协作 | 几个人同时用同一个项目会冲突吗？ | 多人共用同一个桶，桶开启版本控制，不加锁。推送时如果发现文件在您拉取之后被别人改过，会在对话里告诉您；被覆盖的版本可以从版本历史恢复。 | 项目与存储桶目录 `/docs/projects/` | 加推送时的提示：`tool-tos` 的 `remoteChangedSincePull` |
| `scans-drawings` | 数据 | 扫描件和图纸能看吗？ | 能。扫描件优先读与原件并列的识别文本，没有时由模型看图。DWG 图纸转换后先读结构化内容：图框、标题栏、文字、图块和房间面积，计数与面积由代码计算；需要看空间关系时，再把图框渲染成图片交给模型阅读。看图结果同样需人工确认。 | CAD 看图 `/docs/features/cad/` | 改为"先结构化，后看图"：`zt-cad/SKILL.md` |
| `vector-index` | 安装 | 需要建知识库的向量索引吗？ | 不需要。产品不建向量库，也不建数据库，按需读文件：先读项目说明，再读具体文件；跨项目查询读案例索引。知识库按目录组织，每个目录有一份说明。 | 项目与知识库问答 `/docs/features/qa/` | 加"不建数据库""案例索引"：`README.md` §4、`zt-ask/SKILL.md` |
| `migrate` | 安装 | 原来的资料怎么搬进来？ | 由服务方在交付前整理：按统一目录规范重排、清理重复件和系统生成物、核对文件数与总字节，再上传到桶，并出具整理报告，说明删除和改名情况。 | — | 无改动（`README.md` §6；迁移工单 W8 未开始，本答只描述交付服务，不描述工具） |
| `other-documents` | 协作 | 能写报告以外的文书吗？ | 可以，但要先加模板。内置 24 套模板，覆盖咨询成果报告、编制说明、审核报告、审定单和投资控制月报等；函件、方案、意见书等，由服务方按报告模板机制增加对应模板后即可使用。 | 报告撰写 `/docs/features/report/` | 加"先加模板、由服务方加"：`zt-report/SKILL.md` 纪律（模板由维护方改）；`report_templates.yaml` 无函件类模板 |

DOM 锚点：`<details id="faq-{id}">`，如 `#faq-concurrent`。

### 4.3 布局

- **桌面**：12 列；左 4 列为眉标、h2、副标题、筛选组、文档链接，`position: sticky; top: calc(var(--header-h, 72px) + 32px)`；右 8 列为问题列表。筛选组单行，按钮间距 6px，高 36px（命中区 44px）。
- **平板**：标题区全宽（不吸顶），筛选组一行，列表全宽。
- **手机**：筛选组横向滚动（`overflow-x: auto`，`scroll-snap-type: x proximity`，左右 16px 渐隐遮罩），列表全宽。
- **问题项**：上下内边距 24px（手机 20px），底边 1px `--line`；`summary` 三栏：问题（h3，20px/600，手机 17px）| 主题小标签（13px，`--blue-tint` 底）| 24px 加号图标；展开区：答案（17px，行高 1.8，最大宽 720px）+ 12px 后的一行"相关文档 →"与右侧复制链接按钮。
- 筛选按钮底板由 `useHoverIndicator` 提供（圆角浅蓝底，选中项实心 `--brand-blue` 白字）。

### 4.4 组件与数据

```ts
// src/data/faq.ts
export type FaqGroup = 'install' | 'data' | 'result' | 'collab';
export const FAQ_GROUPS: { id: FaqGroup | 'all'; label: string }[] = [
  { id: 'all', label: '全部' }, { id: 'install', label: '安装' }, { id: 'data', label: '数据' },
  { id: 'result', label: '结果' }, { id: 'collab', label: '协作' },
];
export interface FaqItem {
  id: 'calc' | 'use-directly' | 'data-location' | 'concurrent'
    | 'scans-drawings' | 'vector-index' | 'migrate' | 'other-documents';
  group: FaqGroup;
  question: string;
  answer: string;
  doc: { title: string; href: string } | null;
}
export const FAQS: FaqItem[] = [/* 按 §4.2 表顺序 */];
```

- `FaqSection.vue`：状态 `filter: Ref<FaqGroup | 'all'>`（默认 `'all'`）、`open: Ref<Set<FaqItem['id']>>`（默认含 `calc`，可同时展开多问）。
- `FaqItem.vue`：原生 `<details>`/`<summary>`，脚本增强（§4.5）。

### 4.5 交互与动效

- **展开**（拦截 `summary` 点击，`preventDefault`）：`state = Flip.getState(该问之后的所有问题项与文档链接)`；`details.open = true`；`Flip.from(state, { duration: DUR.base, ease: EASE.out })`；答案容器 `clip-path: inset(0 0 100% 0) → inset(0 0 0% 0)`，`DUR.base`，`EASE.out`；答案内容 `opacity 0→1, y 8→0`，`DUR.short`，延后 0.08 s；加号 `rotate 0→45°`，`DUR.short`，`EASE.out`。
- **收起**：答案容器 `clip-path → inset(0 0 100% 0)`、内容 `opacity → 0`，`DUR.short`；结束时 `getState` → `details.open = false` → `Flip.from(state, { duration: 0.32, ease: EASE.inOut })`；加号 `45°→0`。
- 动画期间再次点击同一问：杀掉当前时间线，从当前值反向。
- 每次展开或收起结束后 200 ms 防抖调用一次 `ScrollTrigger.refresh()`。
- **页内查找**：监听 `details` 的 `toggle` 事件；浏览器因查找而自动展开时，同步 `open` 集合与加号角度（无动画）。
- **筛选**：点击按钮 → `state = Flip.getState(全部问题项)` → 不属于该主题的项设 `hidden` → `Flip.from(state, { duration: DUR.base, ease: EASE.inOut, absolute: true, stagger: STAGGER.tight, onEnter: el => gsap.fromTo(el, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: DUR.short }), onLeave: el => gsap.to(el, { opacity: 0, duration: DUR.micro }) })`；被隐藏的项保留展开状态。筛选按钮 `v-magnetic`；底板随选中项移动（`useHoverIndicator`）；`#faq-status`（`role="status"`）写入筛选播报。
- **深链**：页面加载与 `hashchange` 时，若 hash 为 `#faq-{id}` 且 id 存在：筛选设为"全部"（无动画）→ 展开该问（无动画）→ `lenis.scrollTo(该项, { offset: -(顶栏高度 + 24), duration: 1.1 })`（减少动效时立即跳转）→ 焦点到其 `summary`（`preventScroll`）。
- **复制链接**：01 章 `useCopy().copy('https://ztsgai.com/#faq-{id}', { success: '已复制问题链接' })`；按钮图标 `copy → check` 交叉淡入 160 ms、1.6 s 后复原（同 01 章 §7.5）；同时 `history.replaceState` 为 `#faq-{id}`。
- 入场：h2 `heading`；问题列表 `stagger`。

### 4.6 降级

- 无 JS：原生 `<details>` 可展开收起，全部 8 问可见；筛选组不渲染（水合后插入，预留高度 36px 防位移）；复制链接按钮不渲染；`#faq-{id}` 锚点可跳到对应问（不自动展开）。
- 减少动效：展开、收起、筛选都立即完成。
- 打印：全部展开。

### 4.7 无障碍

- 筛选按钮 `aria-pressed`；Tab 逐个经过。
- `summary` 内为 `<h3>`；`summary` 自带展开状态语义，不另加 `aria-expanded`。
- 主题小标签对读屏追加在问题后，如"它会替我算造价吗？，结果"。
- 筛选只改 `hidden`，焦点所在项被隐藏时焦点移到筛选按钮。

### 4.8 验收标准

| 编号 | 标准 |
|---|---|
| AC-05-59 | 8 问的 id、主题、问、答、相关文档与 §4.2 逐字一致（vitest 快照） |
| AC-05-60 | 筛选按钮计数为 8 / 2 / 2 / 2 / 2；点"安装"后只显示 `vector-index`、`migrate`，`aria-pressed` 只在"安装"上 |
| AC-05-61 | 筛选后 `#faq-status` 为"显示 2 个问题：安装" |
| AC-05-62 | 默认 `calc` 展开、其余收起；可同时展开多问 |
| AC-05-63 | 展开：答案在 0.45 s ± 1 帧内完全显示，后续问题项以 transform 位移，期间无 Layout 抖动（Performance 录制中该交互只有一次布局） |
| AC-05-64 | 收起总时长 0.28 + 0.32 s，结束后 `details.open === false` |
| AC-05-65 | 禁用 JS：点击 `summary` 能展开收起 |
| AC-05-66 | 访问 `/#faq-concurrent`：筛选为"全部"、该问展开、其 `summary` 有焦点且位于顶栏下方 24px 处 |
| AC-05-67 | 页面已打开时把 hash 改为 `#faq-migrate`：同 AC-05-66 的行为 |
| AC-05-68 | 复制链接得到 `https://ztsgai.com/#faq-{id}`，提示条"已复制问题链接" |
| AC-05-69 | Chrome 页内查找命中收起问题里的答案文字：该问展开，加号为 45° |
| AC-05-70 | 每次展开或收起结束后 `ScrollTrigger.refresh` 只调用一次 |
| AC-05-71 | "在文档中查看更多 →"的 `href` 为 `/docs/troubleshooting/`；各问相关文档链接无死链 |
| AC-05-72 | 减少动效：展开、收起、筛选都在 1 帧内完成 |
| AC-05-73 | 筛选到"数据"再回"全部"：之前展开的 `calc` 仍展开 |

## 5. 页脚 `footer.site-footer`

### 5.1 目的

给出品牌一句话、站内与文档入口、运营方联系与法律信息，并提供回到顶部；首页与文档页共用。

### 5.2 文案

| 位置 | 文案 |
|---|---|
| 品牌一句话 | 智通数工AI：把造价咨询里重复的读资料、算数、核对和归档，收进一次对话。 |
| 官网 | 官网：https://ztsgai.com |
| 主按钮 | 获取安装包（打开 01 章获取弹层） |
| 栏目"产品" | 工作示例 `#demo` ／ 适用岗位 `#roles` ／ 它解决什么 `#problem` ／ 产品能力 `#capabilities` ／ 使用流程 `#workflow` ／ 数据与复核 `#trust` ／ 安装与交付 `#install` ／ 常见问题 `#faq`（文档页里写成 `/#<id>`） |
| 栏目"文档" | 快速开始 `/docs/quick-start/` ／ 安装 `/docs/install/` ／ 导入配置包 `/docs/config-package/` ／ 12 项能力 `/docs/#按任务找` ／ 数据与安全 `/docs/security/` ／ 常见问题与排错 `/docs/troubleshooting/` |
| 栏目"联系" | 按 01 章 §8.3 的顺序与格式：服务方 ／ 联系人 ／ 电话（`tel:`）／ 邮箱（`mailto:`）／ 微信（文字 + 复制按钮，提示"已复制微信号"）／ 服务时间；只列非空项；01 章 `hasContact` 为 false 时整栏不渲染 |
| 法律行 | © {构建年份} {company} ／ {icp}（链接 https://beian.miit.gov.cn/）／ {psbText}（链接 {psbHref}）／ 隐私说明（链接 {privacyHref}）；空串的项不渲染，不出现任何占位文字 |
| 说明行 | 基于 DeepSeek Harness 构建 · 页面中的项目、金额与文件均为示例数据 |
| 回到顶部 | 回到顶部（按钮，带向上箭头） |

"基于 DeepSeek Harness 构建"是 `zhitong/README.md` §2 允许的描述性写法：纯文字，不加链接、不用 DeepSeek 或 DeepSeek Harness 的任何图标与字标，不出现在品牌名位置。

### 5.3 布局

- `--surface` 底，顶边 1px `--line`；上内边距 80px，下 32px（手机 56px / 24px）。
- **桌面**：12 列；品牌块 4 列（36px 品牌图形 + 字标、品牌一句话 15px、官网 14px、主按钮）；产品 2 列、文档 3 列、联系 3 列（联系栏不渲染时文档栏占 6 列）。栏标题 13px/600 `--text-muted`，链接 15px，行距 36px。其下 48px 为 1px `--line` 分隔线与法律行（14px，左对齐，项间 `·`）、说明行（13px `--text-muted`），回到顶部按钮在法律行最右。
- **平板**：品牌块全宽；三栏各 4 列。
- **手机**：单列：品牌块 → 产品（两列网格）→ 文档 → 联系 → 法律行（逐项换行）→ 说明行 → 回到顶部（宽 100%，高 44px）。
- 背景右下角为 07 章可选装饰位 `<DecoFooterMark>`：240×120，距右下 0，`aria-hidden`，`pointer-events: none`；不实现时不渲染。

### 5.4 组件与数据

联系方式沿用 01 章 §8.2 的 `ServiceContact`、`contactChannels`、`hasContact`；本章在同一文件里追加法律信息（空串表示未填写，与 01 章约定一致）：

```ts
// src/site.config.ts（01 章 §8.2 的文件，本章追加）
/** 网站运营方的法律信息；空串表示未提供，该项不显示。 */
export interface LegalInfo {
  company: string;      // 网站运营主体全称
  icp: string;          // ICP 备案号，如"浙ICP备XXXXXXXX号-1"
  psbText: string;      // 公安联网备案号文字；与 psbHref 同时填写或同时留空
  psbHref: string;      // 该备案号的官方查询链接，原样填写
  privacyHref: string;  // 隐私说明路径；站内路径须带尾斜杠且在预渲染路由表内
}
export interface SiteConfig { contact: ServiceContact; legal: LegalInfo }
// 默认值：legal 五项均为 ''

/** 法律信息的上线检查；返回问题清单，空数组表示可以上线。 */
export function legalLaunchIssues(l: LegalInfo, routes: readonly string[]): string[];

// src/data/site.ts —— 06 章文档页底部"内容有误或不清楚？{联系方式}"取此值
export const SUPPORT_CONTACT: ContactChannel | null; // = contactChannels(siteConfig.contact)[0] ?? null
```

`legalLaunchIssues` 规则（文字格式同 01 章 §8.4）：`company`、`icp`、`privacyHref` 为空 → "site.config.ts：legal.{字段} 未填写"；任一字段含 01 章的占位正则 → "site.config.ts：legal.{字段} 含占位文字"；`psbText` 与 `psbHref` 只填了一个 → "site.config.ts：legal.psbText 与 legal.psbHref 须同时填写"；`privacyHref` 以 `/` 开头但不在 `routes` 内 → "site.config.ts：legal.privacyHref 不是已预渲染的页面"。`entry-server.ts` 导出的 `launchIssues()` 改为返回 `[...launchIssues(siteConfig.contact), ...legalLaunchIssues(siteConfig.legal, routes)]`，由 01 章 §8.4 的 `ZT_LAUNCH=1` 构建在预渲染时检查并以退出码 1 阻断；本章不另建检查脚本。

- `SiteFooter.vue`：props `context: 'home' | 'docs'`；`home` 时产品链接用 `#<id>` 并经 `scrollToSection`，`docs` 时用 `/#<id>` 普通链接。文档栏的标题与路径从 06 章路由清单按 slug 取（`quick-start`、`install`、`config-package`、`security`、`troubleshooting`），"12 项能力"固定指向 `/docs/#按任务找`。

### 5.5 交互与动效

- 入场：品牌块 `block`，四栏 `stagger`（`STAGGER.base`），法律行 `block`。
- 主按钮与回到顶部 `v-magnetic`。
- 回到顶部：`lenis.scrollTo(0, { duration: 1.2, easing: t => 1 - Math.pow(1 - t, 4), onComplete: () => document.getElementById('main')?.focus({ preventScroll: true }) })`；Lenis 未就绪或减少动效时 `window.scrollTo({ top: 0, behavior: 'instant' })` 后同样聚焦 `#main`。文档页聚焦文档正文的 `main`。
- 链接悬停：下划线从左向右 `scaleX 0→1`，`DUR.short`，`EASE.out`（CSS 过渡）。
- 外部链接（ICP、公安备案）`target="_blank" rel="noopener noreferrer"`，文字后加 12px 外链图标与 `.sr-only`"（在新窗口打开）"。

### 5.6 降级

- 无 JS：全部链接可用；回到顶部按钮渲染为 `<a href="#main">`，水合后替换为按钮行为。
- 减少动效：无磁吸、无入场、回到顶部立即跳转。

### 5.7 无障碍

- `<footer>` 内三栏各为 `<nav aria-label="产品">`、`<nav aria-label="文档">`、`<section aria-label="联系">`；法律行为 `<p>`。
- 回到顶部 `aria-label="回到页面顶部"`。
- 电话、邮箱链接文字即为号码与地址本身。

### 5.8 验收标准

| 编号 | 标准 |
|---|---|
| AC-05-74 | 品牌一句话与说明行逐字一致；说明行中"基于 DeepSeek Harness 构建"不是链接，页脚内没有 DeepSeek 图形资源 |
| AC-05-75 | 首页页脚 8 个产品链接各自滚动到对应章节；文档页页脚的产品链接 `href` 为 `/#<id>` |
| AC-05-76 | 文档栏 6 个链接全部解析到预渲染页面或页内锚点（死链检查） |
| AC-05-77 | `hasContact` 为 false：页面上没有"联系"栏，文档栏占 6 列；只填 `email`：联系栏只有邮箱一项，`href` 为 `mailto:` |
| AC-05-78 | 填写 `icp`：链接到 `https://beian.miit.gov.cn/`，`target="_blank"`，`rel="noopener noreferrer"`；`legal` 各项为空串时法律行不出现该项，也没有占位文字 |
| AC-05-79 | `ZT_LAUNCH=1 npm run build`：`legal.company`、`legal.icp`、`legal.privacyHref` 任一为空时退出码 1，并逐项打印 `legalLaunchIssues` 的文字；`privacyHref` 指向不存在的路由时同样失败；全部填写正确时不因 `legal` 失败 |
| AC-05-80 | `SUPPORT_CONTACT` 等于 `contactChannels(siteConfig.contact)[0]`；没有可联系渠道时为 null |
| AC-05-81 | 点回到顶部：1.2 s 内滚到顶部，结束后 `document.activeElement` 为 `#main`；减少动效时立即完成 |
| AC-05-82 | 1440、1024、768、390 四个宽度截图：栏目分别为 4 栏 / 4 栏 / 品牌全宽 + 3 栏 / 单列，无横向滚动 |

## 6. 本章新增基础件

无。本章用到的全局件都由其它章定义：复制与提示条用 01 章 §14 的 `useCopy`、`useToast`（`ZtToast`）；平台识别用 01 章 §7.5 的 `lib/platform.ts`；平台卡用 01 章的 `PlatformCard`（本章只加 `surface`、`magnetic` 两个 prop，§3.4）；站点配置用 01 章 §8.2 的 `site.config.ts`（本章追加 `legal`，§5.4）。

## 7. 上线阻断项与待定事项

| # | 事项 | 状态 |
|---|---|---|
| 1 | `legal.company`、`legal.icp`、`legal.privacyHref` 未填写 | 阻断（§5.4，`ZT_LAUNCH=1` 构建失败） |
| 2 | 隐私说明页不存在：须新增预渲染路由（建议 `/docs/privacy/`，进 06 章路由表）并由运营方提供正文 | 阻断 |
| 3 | 服务方联系方式未填写 | 阻断（01 章 §8.4） |
| 4 | 仓库缺 `public/downloads/releases.json`，构建失败 | 阻断，按 §3.4 提交初始清单 |
| 5 | Mac / Windows 安装包未在目标机器打包与验收（`STATUS.md` W9） | 不阻断；未上架的平台显示"即将发布" |
| 6 | 安装包未签名，网页下载的 DMG 带隔离属性，可能提示"已损坏"；处理办法（`xattr` 命令）目前只在文档 `/docs/install/` 中，01 章 `PlatformCard` 的首次打开步骤未包含 | 待 01 章决定是否在步骤里补一条 |
| 7 | 案例索引模板比 `README.md` §5 多一列"状态"（`STATUS.md` 待 spec 负责人确认）；本章场景四按模板 8 列展示 | 待定；若删列，场景四与 AC-05-15 同步改为 7 列 |
| 8 | 公安联网备案号是否需要、何时取得 | 待运营方确认；字段已预留 |
