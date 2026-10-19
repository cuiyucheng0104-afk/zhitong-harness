# 智通造价 Harness 化总规划

状态：提案（2026-10-19，Fable 起草）。本目录是 zhitong-harness 对 DeepSeek Harness 上游的唯一业务增量；上游文档门禁不扫描本目录（见 `scripts/translation-pairing.manifest.json`）。

勘察报告（Sonnet 子代理只读产出，原文归档）：[引擎](survey/01-engine-service.md) · [Java 与数据模型](survey/02-java-backend-data-model.md) · [前端、部署、OCR](survey/03-frontend-deploy-ocr.md) · [文档、缺陷、模板](survey/04-docs-defects-templates.md)。工作分解见 [tasks/README.md](tasks/README.md)。

## 1. 目标与非目标

目标形态：**每位造价工程师在自己的 Mac 或 Windows 电脑上安装 harness，用 skill 和插件完成资料整理、核对、指标、投控、清单、概算、报告；文件存取走公司的云存储（TOS 桶），用哪份拉哪份；成果和记录回传桶里，桶是公司所有项目案例的留档。** 工程师的电脑可以很普通：OCR 和超大文件解析交给一台薄的计算节点。

| 做 | 不做 |
|---|---|
| 本机 harness（Mac + Windows 桌面版），owner 身份 | 多租户 SaaS、多用户登录、principal 权限、Java 后端、MySQL、前端 SPA |
| 单个 TOS 桶 = 真源：原件 + 旁车 + 中间产物 + 成果 + 记录 | 把 NAS 当真源；本机全量同步 |
| 现场列目录、按需拉取、读那一份 | RAG、向量库、预建全文索引 |
| 一台薄计算节点：OCR 服务 + 大文件解析服务 + NAS→TOS 同步 | 服务器上跑业务逻辑、跑模型、跑 UI |
| 保留并整体搬运确定性引擎与规则数据 | 用提示词重写金额类逻辑；让模型「记住」490 条码表 |
| 模型只做分类、路由、摘录、写作；数字与出处由代码产出 | 模型触碰金额、模型自报出处 |
| 人工确认落成记录文件 | 把确认流程做成后台任务和轮询 |

## 2. 技术选型

| 项 | 选择 | 为什么 |
|---|---|---|
| 运行位置 | harness 装在每位工程师本机，桌面版（Electron）同时出 Mac 与 Windows 包 | 用户要求；上游 `apps/desktop` 已有双平台打包与 Windows 签名流程 |
| 文件真源 | 单个 TOS 桶（`projects/<key>/...` 目录约定，开版本控制） | 异地、版本、生命周期都是桶自带的；按 key 直接定位，不需要数据库 |
| 本机访问方式 | 按需拉取到本机缓存 `~/zhitong/`（Windows：`%USERPROFILE%\zhitong\`），缓存有容量上限并按最近使用淘汰 | 低配机器不能全量同步 140 GB；agent 一次只读几份文件 |
| NAS | 保留，角色降为「计算节点的热副本 + 存量资料的上传入口」；真源是桶。NAS→TOS 每晚单向同步，TOS→NAS 按需拉 | 140 GB 存量从 NAS 内网上传到同区域 TOS 最省事；OCR 服务直接读 NAS 上的热副本不用再下载 |
| 计算节点 | 现有 ECS 瘦身：只跑 `ocr-service`（已有，RapidOCR）+ `zt-engine` 的 HTTP 外壳（只开确定性端点）+ 同步任务；Java、MySQL、前端、`/ragapi` 全部下线 | 本机没有 OCR 能力、低配机器解析 200 MB PDF 会卡；这两样集中到一台机器上做，一份扫描件公司只 OCR 一次 |
| 计算节点访问 | 两个 HTTP API，`X-Service-Token` 鉴权（沿用旧契约），TLS 由 nginx 终结；凭据存 harness 凭据存储 | 旧 OCR 契约 v1.1 已经是这个形态，不用重做 |
| 数据库 | 不要 MySQL。每项目 `manifest.json` + `records/*.json` 放桶里；跨项目查询用本机 SQLite 目录，从 manifest 随时重建 | 元数据索引不是 RAG；可重建就不需要备份它 |
| 检索 | 不建 RAG、不建向量库 | 旧项目向量召回 recall@10 ≈ 0.245 已放弃；「现场列目录 + 按名定位 + 读那一份」在 20/20 用例上验证过，harness 自带 `ls/grep/read` 就是这个模式 |
| 计算引擎 | 保留 Python，做成跨平台 CLI `zt-engine`，由 TS 工具插件包装；同一份代码也是计算节点上的 HTTP 外壳 | 5.2 万行确定性代码 + 201 个测试文件不重写；核心依赖只有 `openpyxl`、`pypdf`、`PyYAML`，Windows 可跑 |
| 本机/远端分流 | 工具插件按文件大小与类型分流：小文件本机算；超阈值的 PDF、需要 LibreOffice 转换的 `.doc/.xls`、OCR 一律发计算节点 | 本机不装 LibreOffice，不跑 OCR |
| 模型 | DeepSeek，由 harness 统一调用；Python 侧不再调模型 | LLM 判断全部回到 agent，Python 只做「准备输入」和「校验输出」 |
| Python 运行时 | 安装包内置独立 Python（`uv` 管理，锁定 3.11），不依赖用户机器 | 工程师不装开发环境 |
| 图纸 79 GB | 原样归档进桶，不处理，缓存永不自动拉取 | agent 不读 DWG |

### 2.1 被否决的方案

- **harness 跑在服务器上、浏览器访问**：用户要求本机运行；且 harness Web 是单 owner 进程，一人一进程的运维负担不小。
- **本机 harness 通过 SSH 执行族（`fs-ssh`/`subprocess-ssh`）把文件和进程放在服务器**：上游明确不支持 Windows 端，Web 工作区 UI 也假定本机文件系统。等上游补齐 Windows 再评估。
- **本机 OCR（RapidOCR CPU）**：低配 Windows 机器 2–4 秒/页，50 页扫描件就是几分钟，而且每台机器各 OCR 一遍。集中到计算节点做一次、旁车回桶。
- **火山引擎云 OCR API 替代自建 OCR**：可行，但旧 2882 份旁车来自 PP-OCR 系模型，换引擎会改变分页文本形态；先沿用自建，云 OCR 留作后备。
- **把 NAS 当真源，TOS 只做备份**：那样每个本机都要连 NAS（SMB/VPN），Windows/Mac 挂载体验差且离线不可用；桶 + 本机缓存简单得多。

## 3. 勘察结论（对规划有约束力的事实）

1. 旧产品冗余的根因是**用户自己当调度员**：标注→齐套有固定顺序却要手点；核对、指标、投控各弹同一个文件选择器且选择不共享；概算与概要各抽一遍同样的字段；结果散在 8 个抽屉里，于是又造了「上次结果」入口。一个项目约 60–150 次点击。这一层在 agent 编排下整体消失。
2. 真正的领域资产是确定性代码与规则数据，不是提示词壳：`costsheet.py`（2252 行，广联达计价表版式识别，14 种真实版式夹具）是核对、指标、投控、报告取数、字段抽取的共同底座；`estimate_engine` 515 条公式拓扑求值；`quantity_segment`/`quantity_rules` 切片器；`report_guard`/`answer_guard` 护栏；`classify_rules.yaml` 235 条（客户已核对）；`gb50854_zj2025.yaml` 490 码；`report_templates.yaml` 24 套 172 章；`summary_fields.yaml` 78 字段；`fee_rules_zj2018.json` 16 条费率。完整清单见勘察报告 01 §5 与 04 §F。
3. 必须原样带走的产品口径：`needs_manual` 恒真；证据三档（confirmed / strong / weak，weak 不进分子）；失败绝不以「成功 + 空结果」返回；提示词改措辞必须升 `prompt_version`；费率、字段词典、投控阈值均处于「待造价员签核」状态，迁移不得洗成已确认。
4. 旧项目**没有向量库**。知识库问答是现场 `os.walk` 生成目录图 + 模型逐步发 `LIST/GREP/DOC/PDF` 指令的导航循环（2000 余行）。需要搬的是它的约束（步数预算、读不了的文件硬拦、引用只能指向读过的内容），不是工具本身。
5. 存量数据：单公司资料约 140 GB（文档 60 GB、图纸 79 GB），单项目峰值 3.3 GB；67% 的 PDF 是扫描件；NAS 上已有 2882 份分页格式 OCR 旁车（`<原件名>.ocr.txt`）。**TOS 桶目前只存 MySQL 每日 dump，NAS 原件没有任何异地备份。**
6. 旧 MySQL 里值得保留的记录：`project`（名称、工程分类、服务范围、金额）、`project_file_cost_tag`（已确认标签）、`project_summary_info` + `project_summary_value_log`（已确认字段）、`cost_reconcile_result`、`cost_indicator_result`、`audit_tk_anomaly` + `audit_tk_decision_log`（复核留痕）、`report_instance` + `report_section_state`、`ai_chat_*`。其余是平台 CRUD 或从未被写入。
7. 旧前端的 63 个「技能」只是目录标签，8 个写作技能被整改判为「空壳且会编造」，不搬。
8. 旧 `ocr-service` 契约（`POST /ocr/recognize`，base64 入、分页文本出，`deadline_ms`）和 `zt-engine` 的确定性端点可以原样保留为计算节点 API；旧引擎已经按 ≤6 页切块、按会话预算调用 OCR，这套客户端逻辑搬进 `tool-docs`。

## 4. 目标架构

```text
工程师的 Mac / Windows
└─ DeepSeek Harness 桌面版，profile = zhitong   (dsh-base + 桌面 Web + zhitong bundle)
   ├─ skills/                 造价技能：SKILL.md + 规则数据 + 小脚本
   ├─ @zhitong/tool-tos       桶工具：ls / stat / pull / push / manifest；本机缓存 ~/zhitong/
   ├─ @zhitong/tool-docs      文档读取：docx/xlsx/pdf 文本、旁车；按阈值分流到计算节点（OCR、转换、大 PDF）
   ├─ @zhitong/tool-engine    确定性引擎工具：本机 zt-engine CLI；超阈值任务发计算节点
   ├─ @zhitong/tool-catalog   跨项目目录：本机 SQLite，从 manifest 重建
   └─ 内置 Python 运行时       uv 锁定 3.11 + zt-engine + 依赖

计算节点（现有 ECS，瘦身）                        火山引擎 TOS 桶（公司唯一真源）
├─ ocr-service   (已有容器)   ──写旁车──┐          └─ 见 §5
├─ zt-engine-http (确定性端点)          ├─ 推送 ─▶
├─ NAS 热副本 /opt/zhitong/data        │
└─ 同步任务：NAS→TOS 每晚；TOS→NAS 按需 ┘
```

身份只有一个：桶的 AK/SK 与计算节点的服务令牌，都走 harness 的凭据存储。没有第二个人连进同一个 harness 进程，所以 Peer principal、远程访问控制都不启用。

### 4.1 工作目录就是项目

一个会话对应一个项目：`zt-project open <key>` 把 `manifest.json` 拉到 `~/zhitong/projects/<key>/`，建出与桶同构的目录树（只建目录与占位，不拉内容），并把会话工作目录切到那里。之后 agent 的所有文件操作都发生在本机缓存里：

- 读：harness 自带 `ls/grep/read` 先看目录与 manifest；要读内容时调 `tos_pull <paths|glob>` 把那几份拉下来，再用 `doc_text` 取正文。这就是「用哪个再去读那个」。
- 写：中间产物写 `work/`，成果写 `deliverables/`，记录写 `records/`；`tos_push` 按路径回传，桶上开版本控制，覆盖安全。
- 缓存：默认上限 20 GB，按最近使用淘汰；`source/` 下的图纸类扩展名永不自动拉取；`deliverables/` 与 `records/` 推送成功前不淘汰。
- OCR：`doc_text` 发现扫描件且桶里无旁车时，把对象 key 发给计算节点；节点从 NAS 热副本（或从桶拉）取原件，OCR 后把 `<原件名>.ocr.txt` 推回桶，本机再拉旁车。公司范围内只做一次。

### 4.2 本机与计算节点分流

| 任务 | 本机 | 计算节点 |
|---|---|---|
| xlsx/docx/文字层 PDF 文本 | ≤ 50 MB 且 PDF ≤ 300 页 | 超阈值 |
| `.doc/.xls` 转换 | 不做 | LibreOffice headless |
| OCR | 不做 | `ocr-service` |
| 计价表解析、核对、指标、投控、齐套、概算、清单切片、报告护栏、docx 导出 | 默认 | 送检文件总量 > 300 MB 时 |

阈值是 bundle 的 Config 字段，可按机器调整。分流对 skill 透明：同一个工具名，插件内部决定走本机还是远端，结果格式一致。计算节点不可达时工具明确报 `remote_unavailable`，不静默降级为空结果。

### 4.3 模型与代码的分工：两半式工具

旧引擎里每条 LLM 调用都夹在确定性步骤中间（切片→模型分类→校验→聚合）。迁移后 Python 不再调模型，每个这样的步骤拆成 `prepare` 与 `finalize` 两个工具，中间那步由 agent 自己完成：

| 能力 | `*_prepare` 产出（代码） | agent 做的事 | `*_finalize` 校验（代码） |
|---|---|---|---|
| 资料标注 | 规则命中结果；未命中文件的文件名、路径、300 字正文头、编号闭集类目表 | 对未命中文件选类目编号并给 ≤3 段原文证据 | 编号必须在闭集；证据必须是原文严格子串；阶段与去向由代码按类目重算；一律 `needs_manual` |
| 字段抽取 | 确定性通道（审定单网格、章节锚定、计价表费用表）已得字段；剩余字段的定义、同义词、排除项与切片正文 | 对剩余字段给 `{value, quote}` | quote 必须逐字在原文；value 必须是 quote 子串；数值保值；合并与冲突由代码排序 |
| 清单生成 | 专业判定、practice/heading/exclusion 切片（原文与位置由代码产生）、490 码受控表、易混淆对照 | 对每个片段给 `{role, 基码, 排除句编号, why}` | 码必须存在；语义一致性闸只判不改码；覆盖不变式（每个片段恰有一个去向） |
| 报告章节 | 按模板章节的 `rag_query` 选材切块、金额事实编号 `〔Fn〕`（不给数值）、写作要求 | 写本章正文，每句标 `[资料n]`，金额只写 `〔Fn〕` | `report_guard`：每个数字必须在送入资料里逐字找到；程序性陈述未勾选加【待核】；`〔Fn〕` 换成单元格原值并带出处 |
| 概算抽取 | 关键词窗口、11 个规模量输入位的路径与口径 | 给每格候选 `{value, quote, scope}` 与单体列表 | 引文回原文；万/亿倍率由代码乘；单体归位固定槽位；面积合计对账 |

零 LLM 的能力（齐套核查、核对、指标、投控检测、概算计算与渲染、报表视图、docx 导出、计价表预检）保持为单个工具，直接返回类型化结果。

### 4.4 结果契约

每个工具返回带状态的类型化 JSON，沿用旧引擎的信封语义：`status ∈ ok | partial | empty | insufficient`、`status_reason`、`coverage{files_total, files_used, rows_parsed, skipped[]}`、`warning_items[]`、金额与数量字段恒带 `needs_manual: true`。失败抛错，不返回「成功 + 空」。harness 的 `defineTool` 要求 `output.schema` 与 `render` 分离，正好承载这一契约。

### 4.5 人工确认

旧产品把确认散在 8 个抽屉里。新方案统一为两种形式：

- 会话内：harness 的 `user-questions` 提问（选类目、选阶段、采纳候选、复核异常），答案由 skill 写进 `records/`。
- 会话外：每个待确认集合落成一份 `work/<日期>-<任务>/pending.md` 清单；工程师可以在编辑器里改，下次会话 agent 读回。

## 5. 桶目录约定

```text
tos://<bucket>/
  projects/<project-key>/
    manifest.json          项目元数据 + 文件清单（相对路径、sha256、大小、mtime、
                           doc_category、cost_stage、confirm_state、text_source）
    source/                原始资料树，原样；旁车 <原件名>.ocr.txt 与原件并列
    work/<yyyymmdd>-<任务>/ 中间产物：核对/指标/投控/清单 的 json 与 xlsx、pending.md
    deliverables/          成果：报告 docx、审定单、清单 xlsx、概算 xlsx
    records/               结构化记录：tags.json、summary.json、reconcile/*.json、
                           tk/anomalies.json、tk/decisions.jsonl、reports/*.json
  knowledge/               定额、规范、费率扫描图、公司模板（含旁车）
  templates/               report_templates.yaml、16 份 docx 模板、概算模板
  catalog/                 catalog.sqlite 的最近一次构建产物（可随时重建）
  legacy/mysql/            迁移时导出的旧库 JSON，只读
```

`project-key` 建议 `<年份>-<公司编号>-<工程名简写>`；旧 `project.id` 与 `sys_company_code` 记在 manifest 里以便追溯。`manifest.json` 是桶内唯一需要「读全」的文件，其余按需。NAS 热副本的目录结构与桶完全一致（`/opt/zhitong/data/tos-mirror/projects/<key>/...`），同步工具用 rclone，桶侧为准。

## 6. 组件清单

### 6.1 工具插件（TypeScript，Cordis 插件）

| 包 | 工具 | 说明 |
|---|---|---|
| `@zhitong/tool-tos` | `tos_ls`, `tos_stat`, `tos_pull`, `tos_push`, `tos_manifest` | 火山 TOS 官方 Node SDK；pull 以 sha256 去重进本机缓存；push 回读校验；缓存容量与淘汰策略是 Config；凭据来自 harness 凭据存储；路径处理用 `node:path`，Windows 与 POSIX 都测 |
| `@zhitong/tool-docs` | `doc_text`, `doc_outline`, `sheet_read`, `ocr_request` | 包装 `zt-engine` 的 `textextract`/`text_chain`/`sidecar_format`；返回 `text_source` 四态；按 §4.2 分流；`ocr_request` 调计算节点，等待旁车回桶后拉取 |
| `@zhitong/tool-engine` | `costsheet_probe`, `costsheet_parse`, `reconcile_run`, `indicator_calc`, `tk_detect`, `audit_check`, `tag_prepare/finalize`, `extract_prepare/finalize`, `quantity_prepare/finalize`, `estimate_extract_prepare/finalize`, `estimate_suggest`, `estimate_compute`, `report_context`, `report_facts`, `report_section_prepare/finalize`, `report_export`, `reportform_render/inspect` | 每个工具 = 一条 `zt-engine` 子命令，JSON in/out；本机经 `ctx.subprocess` 调用内置 Python；远端经 HTTP 调同名端点；schema 由 Python pydantic 模型生成 |
| `@zhitong/tool-catalog` | `catalog_rebuild`, `catalog_query` | 从所有 manifest 与 records 聚合成本机 SQLite；`catalog_query` 只读 SQL、限时、限行 |
| `@zhitong/bundle` | — | `cordis.patch.yml`：挂上述插件、`bundledSkillDir`、造价人设 `personaPrefix`、默认沙箱与审批策略、缓存根、分流阈值、计算节点地址 |

### 6.2 Python 引擎（`zhitong/engine/`）

从 `engine-service/app/engine/*`、`textextract.py`、`text_chain.py`、`sidecar_format.py`、`filetree/answer_guard.py`、`report_guard.py`、`report_export.py` 提取为包 `zt_engine`，去掉 `tenant_scope`、`auth`、`llm_client`、SSE；`parse_pool` 的进程隔离在本机不用，但文件大小与页数上限保留并作为分流阈值的来源。两个入口：

- CLI：`zt-engine <cmd> --in a.json --out b.json`，本机用；`zt-engine schema <cmd>` 输出 JSON Schema。
- HTTP：`zt-engine-http`，只注册确定性端点与 OCR 代理，`X-Service-Token` 鉴权，部署在计算节点。

201 个 pytest 文件随代码迁移，金标夹具原样保留；CI 在 Linux、macOS、Windows 三个矩阵上跑。

### 6.3 计算节点（`zhitong/compute-node/`）

docker-compose 三个服务：`ocr`（沿用旧镜像）、`engine-http`、`sync`（rclone 定时任务）；nginx 只做 TLS 与两条路由。内存上限约 6 GB，现有 4C16G 足够。不再有 Java、MySQL、前端、`/ragapi`。

### 6.4 技能（`zhitong/skills/<name>/SKILL.md`）

| 技能 | 触发 | 编排 |
|---|---|---|
| `zt-project` | 开工、建项目、换项目 | 新建或打开 project-key；拉 manifest；识别资料角色；缺标签则进入 `zt-tagging` |
| `zt-tagging` | 标注、齐套 | `tag_prepare` → agent 补未命中 → `tag_finalize` → `audit_check`；待确认写 `pending.md`；确认后写 `records/tags.json` 与 manifest |
| `zt-summary` | 项目概要、抽字段 | `extract_prepare` → agent 摘录 → `extract_finalize`；候选冲突用 `user-questions` 让用户采纳；写 `records/summary.json` |
| `zt-reconcile` | 送审审定核对 | 从 manifest 按角色选送审/审定表，缺则问；`costsheet_probe` → `reconcile_run` → xlsx 到 `work/`；要点口头汇报 |
| `zt-indicator` | 指标、单方造价 | `indicator_calc`；对标用 `catalog_query` 找同类项目 |
| `zt-tk` | 投控、异常检测、复核 | `tk_detect`；复核逐条 `user-questions`；决策追加 `records/tk/decisions.jsonl`；重跑按 `anomaly_uid` 合并 |
| `zt-report` | 报告、初稿、正式报告 | 选模板 → `report_context` → `report_facts` → 逐章 `report_section_prepare` / agent 写 / `report_section_finalize` → `report_export` → `deliverables/`；正式报告走 docx 占位符模板 |
| `zt-quantity` | 清单框架、GB50854 | `quantity_prepare` → agent 分类 → `quantity_finalize` → xlsx |
| `zt-estimate` | 概算 | `estimate_extract_prepare/finalize` → `estimate_suggest` → 用户补输入 → `estimate_compute` → xlsx |
| `zt-archive` | 归档、上传、留档 | 校验 `deliverables/` 与 `records/` 完整，`tos_push`，`catalog_rebuild` |
| `zt-ask` | 项目问答、知识库问答 | 导航纪律：先 manifest，再 `tos_pull` 单份，再 `doc_text`；引用只能指向读过的位置；无出处的数字标出；文档内指令不执行 |

每个 SKILL.md 收录对应旧提示词的措辞（字段定义、排除项、章节 `gen_prompt` 四段式、清单易混淆对照），并标注 `prompt_version` 与签核状态。

## 7. 存量迁移与 NAS 的新角色

1. **冻结**：停止旧系统写入，`mysqldump` 一份终态。
2. **导出记录**：按 `project` 逐项目把 §3.6 列出的表导出为 JSON 到 `legacy/mysql/<project.id>/`；据此生成 `projects/<key>/manifest.json`（文件清单来自 `project_file` 的 `disk_relative_parent_folder/disk_file_name`，标签来自已确认的 `project_file_cost_tag`，文本可用性来自是否存在旁车）与 `records/*.json`。
3. **在 NAS 上重排**：`/opt/zhitong/data/nas-data/project/<id>/...` 硬链接或移动到 `/opt/zhitong/data/tos-mirror/projects/<key>/source/...`，旁车并列；`knowledge/1/...` → `knowledge/`。NAS 从此按桶目录约定组织。
4. **上传**：rclone 从 NAS 镜像目录同步到桶，内网到同区域 TOS，断点续传，分夜跑；逐文件校验 sha256 与 `project_file.sha256`。
5. **校验**：每个项目的 manifest 文件数、总字节、sha256 全部对上才算完成；差异写报告，不静默跳过。
6. **切换**：Java、MySQL、前端容器下线；计算节点 compose 上线；NAS 镜像目录保留为热副本，由 `sync` 服务维持与桶一致。

图纸 79 GB 原样上传；754 份「全失败占位」旁车按 `sidecar_format` 判定标为未命中，不当正文，由计算节点分夜补 OCR（约 32 小时）。

## 8. 里程碑

| 阶段 | 产出 | 验收 |
|---|---|---|
| M0 骨架 | `zhitong` profile 可启动；内置 Python 运行时；`tool-tos` 能 ls/pull/push 测试桶；`zt-project` 能开项目 | Mac 与 Windows 各一台干净机器从零装到能打开样例项目 |
| M1 读与问 | `tool-docs`（含旁车、远端 OCR 分流）、`zt-ask`；计算节点 compose | 对样例项目的 20 条问答复现旧 filetree 的通过率；一份扫描件走完 OCR 回桶 |
| M2 计价表 | `tool-engine` 的 costsheet / reconcile / indicator / tk / audit；`zt-reconcile`、`zt-indicator`、`zt-tk`、`zt-tagging` | 旧金标 `tests/golden` 与 14 种版式夹具在三平台全绿 |
| M3 报告 | `report_*`、`zt-report`、`zt-summary`、docx 导出与占位符模板 | 一份结算审核报告从资料到 docx 走通；`report_guard` 判例夹具全绿 |
| M4 清单与概算 | `quantity_*`、`estimate_*`、两个技能 | 合成金标与 515 公式逐格一致 |
| M5 迁移 | §7 脚本与运行手册；`catalog` | 全量校验报告 0 差异；旧业务容器下线 |

M1 之后每个阶段都附一个 keyless 录制会话快照（harness 的 `test:snapshot`）作为回归。

## 9. 与上游的关系

- `zhitong/` 目录是本仓的全部增量，不改 `packages/`；上游更新通过普通 merge 合入。
- 插件以本地路径安装进 profile（`dsh plugin` 支持 `link:<绝对路径>`），不进上游工作区 glob，不受上游 100% 覆盖率与双语门禁约束；本目录自带 vitest 与 pytest。
- 桌面安装包在上游 `apps/desktop` 打包流程上叠加 zhitong bundle 与内置 Python 运行时；Windows 签名按 `apps/desktop/windows-signing/README.md`。
- 本目录文档只写中文；`scripts/translation-pairing.manifest.json` 把 `zhitong/` 列入排除。

## 10. 待确认

1. 生产那套系统退役还是继续给他人使用？影响 §7 是「迁移」还是「同步」。
2. `project-key` 的编号规则；公司是否已有项目编号体系。
3. 桶：沿用 `zhitong-prod-backup-*` 还是新建业务桶（建议新建，生命周期规则不同）。
4. 工程师机器的最低配置（内存、磁盘剩余）；决定缓存上限默认值与分流阈值。
5. 计算节点的网络暴露方式：公网 + TLS + 令牌，还是公司 VPN 内网。
6. 费率规则、字段词典、投控阈值的签核人是谁，迁移后是否安排一次签核。
7. 图纸是否有任何需要 agent 读取的场景（DWG/DXF），还是纯归档。
