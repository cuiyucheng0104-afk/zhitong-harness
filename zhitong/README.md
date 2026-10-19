# 智通数工AI：产品 spec

版本 2（2026-10-19）。版本 1 的多租户、计算节点、Python HTTP 引擎方案已废弃；本文件是当前唯一有效的 spec。勘察报告原文在 [survey/](survey/)，工单在 [tasks/README.md](tasks/README.md)。本目录是对 DeepSeek Harness 上游的全部业务增量，上游文档门禁不扫描它。

## 1. 定位

**把 DeepSeek Harness 做成造价咨询公司的工作台。** 工程师下载安装包（Mac / Windows），导入公司配置包，就能在对话里完成核对、指标、投控、清单、概算、报告、看图、问答，文件直接存取公司的火山引擎 TOS 桶。旧项目（Java + Python 引擎 + Vue 前端）被提炼为一组内置 skill 和少量插件；凡是 harness 自己能做的事（读文件、看图、写文档、跑脚本、搜网页、编排子代理），一律用 harness 做，不再另起服务。

## 2. 已拍板的决策

| # | 决策 | 后果 |
|---|---|---|
| 1 | 安装包支持 Mac 与 Windows | 所有 skill 脚本跨平台；安装包内置 Python 运行时；路径处理不假定 POSIX |
| 2 | 旧系统迁移完成后废弃 | 不做兼容层；旧 MySQL 不导出业务记录（从未人工确认过），只导项目基本信息 |
| 3 | 文件通道只有 TOS；NAS、ECS、桶都是现成的，不新建 | 一个 TOS 插件；用户配 AK/SK 即可读写；NAS 只在迁移时作上传源 |
| 4 | 迁移允许清理、重命名、优化结构 | 见 §6 整理规范 |
| 5 | 文件识别交给 DeepSeek（`read_image` + office/pdf skill） | 不做 OCR 服务；扫描件优先读现成旁车，没有旁车才看图 |
| 6 | 看 CAD 图做成插件（移植 tiangong-cad-viewer） | DWG→DXF→结构化数据与图框 PNG；agent 看图框图片 |
| 7 | 企业知识库是一个 skill：初版由爬取制作，之后 agent 在工作中持续补充回桶 | 知识库目录对所有项目可见 |
| 8 | 资料标注、字段抽取两项废弃；其余第一期全要 | 报告所需事实由 agent 现场从资料读取 |
| 9 | 计价表解析、公式概算等金额计算是 skill 内 Python 脚本，可事后修改 | 模型不算钱；脚本与规则数据是普通文件 |
| 10 | 报告以逐章提示词（24 套 172 章）为准 | docx 正式模板作为可选输出格式 |
| 11 | agent 要能操作火山引擎全部运维（参照你本机的 `vec`、`pssh`、`ssh-access-sync.sh`） | 火山运维 skill + SSH |
| 12 | 客户配置包由你在本机整理，不进仓库 | harness 提供「导入配置包」能力与配置包格式说明 |
| 13 | 多人同时用同一桶：开版本控制，不做锁 | 冲突靠版本回退 |

品牌名：**智通数工AI**。模型：DeepSeek V4.1 Flash（支持图片输入）。

## 3. 产品形态

```text
安装包（Mac .dmg / Windows .exe，基于上游 apps/desktop）
├─ DeepSeek Harness 桌面版，profile = zhitong
├─ 内置 Python 运行时（uv 锁定 3.11）+ skill 脚本依赖（openpyxl、pypdf、PyYAML、python-docx…）
├─ 内置 dwg2dxf（LibreDWG，GPL 进程边界，asar 外）
├─ plugins/   tool-tos · tool-cad · config-import
└─ skills/    zt-project · zt-reconcile · zt-indicator · zt-tk · zt-report · zt-quantity
              zt-estimate · zt-ask · zt-archive · zt-knowledge · zt-volc · zt-cad

客户配置包（zip，你在本机做）
└─ zhitong.config.json：TOS endpoint/region/bucket/prefix、AK/SK、公司名、
   可选 SSH 主机别名与密钥、可选火山 ve profile

火山引擎 TOS 桶（公司唯一真源，开版本控制）
└─ 见 §5
```

安装后第一次启动：工程师把配置包拖进对话，`config-import` 校验并写入 harness 凭据存储与 profile 配置；之后 `zt-project` 列出桶里的项目。

## 4. 架构：每件事谁来做

| 事 | 由谁做 | 说明 |
|---|---|---|
| 列目录、找文件、读文本 | harness 自带 `ls/grep/read` + `tos_*` | 先看项目说明，再拉具体文件；不建索引 |
| 读 docx/xlsx/pdf | 上游 `skill-office` + skill 脚本 | 文字层 PDF 直接抽文本 |
| 看扫描件、图片、图框 | `read_image` → DeepSeek 视觉 | 有旁车先读旁车 |
| 看 DWG | `tool-cad` | 转 DXF、出图框 PNG、出房间面积与文字表 |
| 金额计算 | skill 内 Python 脚本 | 广联达表解析、核对、指标、投控规则、概算公式、清单切片与查表 |
| 判断、分类、摘录、写作 | DeepSeek（agent 本身） | 脚本给输入与校验，模型做中间那步 |
| 多步任务 | skill 编排；必要时 `subagent`/`workflow` | 一次会话做完一个项目的全部工作 |
| 人工确认 | `user-questions` 对话确认 + 写记录文件 | 不做后台任务与轮询 |
| 写成果 | skill-office 出 docx/xlsx → `tos_push` 到项目 `成果/` | |
| 查别的项目 | `tos_ls` + 读项目说明；跨项目汇总用 `zt-archive` 维护的 `案例索引.md` | 不要数据库 |
| 搜资料、补知识库 | 上游 `web_search/web_fetch` + `zt-knowledge` | |
| 火山运维 | `zt-volc`（`ve` CLI）+ harness bash/ssh | |

### 4.1 模型与脚本的分工（两半式）

每个原来「切片→模型→校验→聚合」的流程，脚本提供 `prepare` 与 `finalize` 两个子命令，中间那步由 agent 完成：

| 能力 | `prepare`（脚本） | agent | `finalize`（脚本） |
|---|---|---|---|
| 清单生成 | 专业判定、做法/标题/排除句切片（原文与位置由代码产生）、490 码受控表、易混淆对照 | 每片段给 `{role, 基码, 排除句编号, why}` | 码必须存在；一致性闸只判不改码；每个片段恰有一个去向 |
| 报告章节 | 按章节 `rag_query` 选材切块、金额事实编号 `〔Fn〕`（不给数值）、写作要求四段式 | 写本章，每句标 `[资料n]`，金额只写 `〔Fn〕` | 每个数字必须在送入资料里逐字找到；未勾选的程序性陈述加【待核】；`〔Fn〕` 换原值并带出处 |
| 概算抽取 | 关键词窗口、11 个规模量输入位的路径与口径 | 每格候选 `{value, quote, scope}` | 引文回原文；倍率由代码乘；单体归固定槽位；面积合计对账 |

零模型的能力（核对、指标、投控检测、概算计算与渲染、docx 导出、计价表预检）是单个脚本子命令。

### 4.2 结果契约

脚本输出 JSON：`status ∈ ok | partial | empty | insufficient`、`status_reason`、`coverage`、`warning_items[]`；金额与数量恒带 `needs_manual: true`。失败以非零退出码 + 错误 JSON 结束，不输出「成功 + 空」。SKILL.md 要求 agent 把 `status` 与 `warning_items` 如实转述给用户。

## 5. 桶目录规范

```text
tos://<bucket>/<公司前缀>/
  项目/<项目编号>-<工程名>/
    项目说明.md        agent 入口：基本信息、咨询类型、阶段、关键文件指引、已出成果清单
    资料/              客户原件，按迁移整理规范清理后的目录；旁车 <原件名>.ocr.txt 与原件并列
    图纸/              DWG/DXF/PDF 图纸；tool-cad 的缓存产物（dxf、图框 png）放 图纸/.cache/
    工作/<日期>-<任务>/ 中间产物：核对/指标/投控/清单 json 与 xlsx、待确认清单.md
    成果/              报告 docx、审定单、清单 xlsx、概算 xlsx
  知识库/
    规范/  定额/  费率/  模板/  公司经验/      每个子目录一份 README.md 说明内容与来源
  案例索引.md          每个项目一行：编号、工程名、业态、规模、咨询类型、关键指标、成果链接
```

项目编号 = `YYYY-NNN`：建项目年份 + 当年三位流水号（如 `2026-007`），由 `zt-project` 在案例索引里取当年最大值加一；目录名 `<编号>-<工程名>`，工程名去掉空格与 `/\:*?"<>|`。客户自己的合同号或内部编号记在项目说明的「别名」里，不进目录名。
`项目说明.md` 与 `案例索引.md` 是桶内唯一需要「读全」的文件。`zt-project` 开项目时读前者，`zt-archive` 归档时更新两者。本机缓存 `~/zhitong/`（Windows `%USERPROFILE%\zhitong\`）与桶同构，只拉用到的文件，上限可配。

## 6. 第一个客户的资料整理规范（NAS → TOS）

整理在 ECS 上执行一次，脚本在 `migration/`，由你运行。目标是让 agent 开项目时三步内找到要的文件。

1. **项目映射**：旧 `project` 表 → `项目/<编号>-<工程名>/`；编号用客户现有编号，没有则 `YYYY-NNN`。旧 `project.id` 记在项目说明里。
2. **目录重排**：旧 `/work/project/<id>/<disk_relative_parent_folder>/` 的显示路径（`relative_parent_folder`）作为新目录名，磁盘名里的 `(1)(2)` 后缀与冲突改名还原为显示名。
3. **清理**：删除 `INDEX.md`、系统生成物、空目录、同 sha256 重复件（保留路径最短的一份）、`.doc/.xls` 已有同名 `.docx/.xlsx` 的旧格式件；754 份「OCR 连续失败」占位旁车删除；其余 2882 份分页旁车保留并列。
4. **归类**：按旧分类规则（`classify_rules.yaml`，客户已核对）对每个文件打一次 `doc_category/cost_stage`，不入库，只用来生成项目说明里的「关键文件指引」（合同、招标文件、送审计价表、审定计价表、设计说明、图纸的位置）。
5. **图纸**：DWG/DXF/图纸 PDF 移到 `图纸/`；其余留 `资料/`。
6. **知识库**：`knowledge/1/` 下的定额、规范按 §5 归入 `知识库/`；9 本无文本扫描书保留，由 `zt-knowledge` 后续用看图逐页补文本。
7. **校验**：文件数与总字节与旧 `project_file` 对账；每个项目生成项目说明；写一份整理报告（删了什么、改了什么名）。
8. **上传**：rclone 内网同步到桶，分夜跑；完成后 Java、MySQL、前端容器下线，ECS 只留作你的运维跳板。

## 7. 插件

| 插件 | 工具 | 说明 |
|---|---|---|
| `tool-tos` | `tos_ls`, `tos_stat`, `tos_pull`, `tos_push` | 火山 TOS Node SDK；凭据来自 harness 凭据存储；pull 以 sha256 去重进缓存；push 回读校验；图纸类扩展名不自动拉 |
| `tool-cad` | 第一批：`cad_open`, `cad_frames`, `cad_text_search`, `cad_render`, `cad_blocks`；第二批：`cad_set_unit`, `cad_rooms`, `cad_table`, `cad_layers`, `cad_diff` | 移植 tiangong-cad-viewer（[勘察](survey/05-cad-viewer.md)）：解析与算量逻辑是纯函数可直接在 Node 跑；dwg2dxf 子进程转换（GPL 进程边界、官方 0.14 钉死 sha256、Windows 中文路径先拷成 ASCII 临时名、`mkdtemp` + 超时）；仓库没有无头栅格化，需新写 `cad_render`（`@napi-rs/canvas`，SHX 笔画字体 + 内置 OFL 中文字体回退，按图框或矩形出 PNG 切片并返回世界坐标元数据供 `read_image`）；macOS 无官方 dwg2dxf 二进制，要在 CI 静态构建；单位门禁（`$INSUNITS` 缺失时量纲类工具拒绝执行） |
| `config-import` | `config_import` | 校验 `zhitong.config.json`，写凭据存储与 profile patch；不回显密钥 |

其余全是 skill。

## 8. Skill

每个 skill 一个目录：`SKILL.md`（触发条件、步骤、纪律、引用的脚本与数据）、`scripts/`（Python，可改）、`data/`（规则与模板，文件头写版本与签核状态）。

| skill | 做什么 | 脚本/数据来源（旧仓） |
|---|---|---|
| `zt-project` | 开项目：读项目说明；缺则扫描目录生成；按旧清单表做资料盘点（缺什么直接说，不打标签） | `cfg_checklist_*` 种子、`classify_rules.yaml` |
| `zt-reconcile` | 送审 vs 审定核对：定位两张计价表→预检→核对→xlsx 到 `工作/`→口头汇报核增核减 | `costsheet.py`、`reconcile_engine.py`、`code_registry.py`、金标 |
| `zt-indicator` | 单方造价、章节占比、对标（查案例索引） | `indicator_engine.py` |
| `zt-tk` | 投控异常检测；逐条对话复核；决策追加到 `工作/.../复核.jsonl` | `tk_engine.py`、`tk_align.py`、`tk_detect.yaml` |
| `zt-report` | 选模板→选材→事实→逐章写→护栏→docx→`成果/` | `report_templates.yaml`、`report_compose.py` 选材、`report_facts.py`、`report_guard.py`、`report_export.py` |
| `zt-quantity` | 设计说明→GB50854 清单框架 xlsx | `quantity_segment.py`、`quantity_rules.yaml`、`gb50854_zj2025.yaml`、`quantity_features.py` |
| `zt-estimate` | 概算：抽规模量→建议→用户补输入→计算→真公式 xlsx | `estimate_*`、`fee_rules.py`、`gsyz_v1*` |
| `zt-ask` | 项目/知识库问答纪律：先项目说明，再拉单份，再读；引用只指向读过的位置；无出处数字标出；文档内指令不执行 | `filetree` 的约束、`answer_guard.py` |
| `zt-archive` | 归档：核对 `成果/` 与 `工作/` 完整，推送，更新项目说明与案例索引 | — |
| `zt-knowledge` | 建设与维护知识库：初版爬取（定额、规范条文、GB50854/浙江 2025 码表、费率）；工作中发现的口径、经验写入 `知识库/公司经验/`；每条带来源与日期 | `docs/知识库结构化/` 生成器、`fee_images/` |
| `zt-volc` | 火山引擎运维：TOS 桶管理、ECS 启停、安全组白名单、SSH 到服务器执行 | 你本机的 `vec`、`pssh`、`ssh-access-sync.sh` 的逻辑 |
| `zt-cad` | 看图流程：开图→列图框→按需栅格化看图→抽文字与面积→结果进 `工作/` | `tool-cad` |

写作类技能不单独做：报告以外的函件、方案、意见书用 `zt-report` 的模板机制加模板即可。

## 9. 里程碑

| 阶段 | 产出 | 验收 |
|---|---|---|
| M0 | profile、内置 Python、`tool-tos`、`config-import`、`zt-project`、`zt-ask`、`zt-archive` | Mac 与 Windows 干净机器从安装到打开样例项目并问答 |
| M1 | `zt-reconcile`、`zt-indicator`、`zt-tk` | 旧金标与 14 种版式夹具三平台全绿；一个真实项目核对走通 |
| M2 | `zt-report`、`zt-quantity`、`zt-estimate` | 一份结算审核报告从资料到 docx；清单与概算合成金标一致 |
| M3 | `tool-cad`、`zt-cad` | 夹具图纸出图框 PNG，DeepSeek 能读出图名与房间 |
| M4 | `zt-knowledge` 初版内容、`zt-volc` | 知识库目录可用；agent 能列桶、看 ECS 状态 |
| M5 | 第一个客户资料整理与上传；安装包发布 | 整理报告 0 差异；客户机器实装 |

每个阶段附一个 keyless 录制会话快照作为回归。

## 10. 与上游的关系

- 只增 `zhitong/`，不改 `packages/`；上游通过普通 merge 合入。
- `pnpm-workspace.yaml` 增加 `zhitong/bundle` 与 `zhitong/plugins/*`，插件以 `workspace:*` 引用上游包（上游 0.2.x 未发布到 npm）；插件以 `link:` 装进 profile；不受上游覆盖率与双语门禁约束，本目录自带 vitest 与 pytest。
- Python 代码集中在 `zhitong/python/`（包 `zt`，uv 管理）；各 skill 的 `scripts/*.py` 是薄 CLI，只 import `zt`。
- 安装包在上游 `apps/desktop` 打包流程上叠加 zhitong bundle、Python 运行时与 dwg2dxf；Windows 签名按 `apps/desktop/windows-signing/README.md`。

## 11. 已定

品牌名智通数工AI；项目编号 `YYYY-NNN`（§5）；模型 DeepSeek V4.1 Flash，图片输入可用，扫描件与看图走 `read_image`。
