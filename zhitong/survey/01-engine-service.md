# engine-service 能力清单 (面向 harness 重实现)

调研范围: `/home/user/zhitong-cost-ai/engine-service`(只读,未跑任何命令、未读 .env)。路径以下均相对该目录。
规模: `app/` 约 52k 行 Python;pytest 文件约 230 个。

## 0. 先看这几点(README 与代码不一致,以代码为准)

1. **README 严重过期**。它只列 9 个端点;`app/main.py:56-68` 实际挂了 13 个 router,共 **26 条路由**(列表见 §1)。
2. **分类规则条数**:
   - README 写"254 条"。`app/engine/data/classify_rules.yaml` 实际 **235 条**(`ancestor_context` 14 / `archive_ext` 15 / `archive_keyword` 42 / `blacklist` 48 / `noise` 5 / `upgrade_whitelist` 21 / `whitelist` 90)。
   - 代码注释里的"204 条"是 WS13 改动前的快照,对应 `scripts/data/classify_rules.pre-ws13.yaml`(27,549 B)。断言在 `tests/test_classify_ws13_delta.py:31`。
3. **没有"四档路由"**。
   - `/engine/chat/complete` 实际只有三种检索形态:`module=all`(不检索,直接 LLM)/ `knowledge` / `project`,见 `app/api/chat.py:1-48, 1522-1566`。
   - `ChatCompleteIn.module` 的注释写 `all | knowledge | project | none`(`app/schemas.py:977`)。但 `none` 和其他任何值都落到 `all` 分支,`skip_retrieval` 字段已无消费方(`schemas.py:981-985`)。
   - 若 Java/前端侧有"全局/无库/知识库/项目"四档,那个映射不在 engine-service 里。我只能确认引擎侧是三档。
4. **没有向量库或任何检索索引**(`qdrant/embedding/faiss/bm25/向量` 全仓零命中)。"检索"是 LLM 驱动的文件树导航 agent,见 §3.12。
5. **"OCR 四态降级链"** = `text_layer → ocr_sidecar → ocr_service → none`,真实存在,但有两份实现,见 §4。
6. **README 称"LLM 凭据固定读 `/Users/cuiqq/.../.llm.env`"不准**。`app/config.py:44` 默认是 `<repo根>/.llm.env`;可用 `LLM_ENV_FILE` 覆盖,也可用进程 env 的 `DEEPSEEK_*` 覆盖(优先级:进程 env > `engine-service/.env` > `.llm.env` > 默认)。默认模型 `deepseek-chat`,base_url `https://api.deepseek.com`。
7. **README 称 `extract/fields` 数字类字段"走 LLM 摘录、精度低于 deepread"也已过期**。现在有确定性网格(`approval_grid.py`)、章节与锚定正则(`report_sections.py`)、计价工作簿费用表(`pricebook_fields.py`)三条确定性通道,LLM 只补缺。
8. README 说 Python 3.11 + 不需要 pymupdf。`Dockerfile` 实为 `python:3.14-slim` + `libreoffice-calc/writer`;`requirements.txt` 注释写明在 3.14.2 上实测通过。

## 1. 路由总览与调用方

鉴权:除 `/engine/health` 外全部校验 header `X-Service-Token`(`app/auth.py`)。`SERVICE_TOKEN` 未配时随机生成并打 CRITICAL 横幅;`SERVICE_TOKEN_REQUIRED=1` 则启动失败(`config.py:77-102`)。多 worker(`WEB_CONCURRENCY>1`)且无固定 token 会启动失败。

两种调用路径:
- **Java 后端内网直调**。`后端/yidu-nas-server/.../costai/client/EngineClient.java` 以及 `TagBatchRunner` / `TagInputFilter`。
- **前端经 nginx `/ragapi` 公网入口**,只开两条:`/engine/chat/complete` 与 `/engine/health`(`app/tenant_scope.py:127-130` 的 `PUBLIC_RAGAPI_PATHS`,其余 404)。前端调用点 `前端/frontend/src/api/aiChat/index.ts:47`。

| 路由 | 调用方(grep 证据) | LLM? |
|---|---|---|
| GET `/engine/health` | 前端/运维 | 否 |
| POST `/engine/tag/classify`, GET `/engine/tag/vocabulary` | Java | 兜底才用 |
| POST `/engine/extract/fields` | Java | 是 |
| POST `/engine/audit/check` | Java | 否 |
| POST `/engine/reconcile/run`, `/indicator/calc`, `/tk/detect`, `/costsheet/probe` | Java | 否 |
| POST `/engine/report/context`, `/facts`, `/section`, `/export`; GET `/report/templates` | Java | 仅 `section` |
| POST `/engine/estimate/extract`; `/suggest`; `/compute`; GET `/estimate/template` | Java | 仅 `extract` |
| POST `/engine/quantity/generate` | Java | 是 |
| POST `/engine/reportform/render`, `/inspect` | Java 侧 grep 无命中(`reportform` 在 `后端/` 的 .java 里零匹配),疑似待接(WS25-c) | 否 |
| POST `/engine/chat/complete` | 前端(`/ragapi`,SSE) | 是 |
| POST `/engine/filetree/ask` | 无生产调用方(`app/schemas.py:955` 注释自述) | 是 |
| POST `/engine/chat/history/query`, `/chat/history/company`, `/query/empty` | 旧前端缓存浏览器 | 否(返回空壳,`chat.py:1601-1616`) |

通用约定:
- 所有请求体继承 `PassthroughMixin`(`schemas.py:15-27`):`sys_company_code/project_id/operator_id` 原样透传,`extra="allow"`。
- 响应带 `usage:{prompt_tokens,completion_tokens,latency_ms,model,total_tokens,provider}`(`schemas.py:30-52`)。纯规则端点 usage 全 0。
- 统一结果信封 `ResultEnvelope`(`app/result_contract.py`):`status ∈ ok/partial/empty/insufficient`、`status_reason`、`coverage{files_total,files_used,rows_parsed,skipped[]}`、`warning_items[{code,level,message,hint?,evidence?}]`。`error` 不走 200,走 422/502/503/504。
- `needs_manual` 对所有金额/数量输出恒为 True(类型 `NeedsManual`,无例外分支)。这是"铁律 2"。
- 阻塞 IO 全部进线程池。有 AST 测试守这点:`tests/test_async_handlers_nonblocking.py`。

## 2. 文件如何到达引擎

- **都不传字节**。请求里是 `FileRef{file_id, rel_path, file_name, ...}`,`rel_path` 相对 `FILE_ROOT`(env,默认 `<repo>/nas-data`,Docker 内 `/data`)。
- 路径只经一个收口 `app/files.py:resolve_safe_path`(`files.py:37-65`):
  - `resolve()` 后必须落在 `FILE_ROOT` 内,否则 400。
  - 公网入口再叠租户子树授权,否则 403(`tenant_scope.authorize_rel_path`)。
- 子树布局(`tenant_scope.py` 模块头):`knowledge/<sys_company_code>/…`、`personal.home/<sftp 用户>/…`、`project/<项目id>/…`。
- 身份来自 nginx 覆盖写入的头 `X-Sys-Company-Code / X-Rag-Sftp-User / X-Rag-Project-Id / X-Rag-Project-Denied`,常量入口头 `X-Tg-Rag-Entry: ragapi`。该头缺失 = 内网直调 = 不强制授权(唯一 fail-open 面)。
- 必须是**纯 ASGI 中间件**(`main.py:35-65`),因为 ContextVar 在 `BaseHTTPMiddleware` 子 task 里会失效,授权闸会静默恒放行。
- 输出方式:JSON 响应体(xlsx 以 `xlsx_base64` 内嵌,docx 以二进制 `Response`)、SSE。
- **引擎不落盘、不连库**。唯一例外是可选 LLM 磁盘缓存(`LLM_CACHE_DIR` + `LLM_CACHE_DISK=1`,默认关)。
- 基准数据(概算 baselines)由 Java 查库后随请求体下发。

## 3. 各能力详述

### 3.1 资料标注 `/engine/tag/classify`(`app/api/tag.py`, `engine/classify_rules.py`, `classify_llm.py`, `classify_heads.py`)

- **入参**:`files: list[FileRef]`(≤100 份,超则 413)。FileRef 另有可选 `ancestors[], display_path, doc_key, sha256, input_index` 等(`schemas.py:60-107`)。
- **出参**:`tags[{file_id, doc_category, cost_stage, confidence, source:"rule"|"llm", disposition: rag/archive/skip/pending_ocr/pending_export/system, needs_manual, signal: filename|content, content_text_source, evidence, reason}]` + `usage` + 信封。
- **算法**(`tag.py:1-45` 文档;`classify_rules.py:1-36`):
  1. **确定性规则优先**,命中即停,顺序:noise → 系统生成物(`INDEX.md`、`.ocr.txt`,不读文件不调 LLM)→ 黑名单/升档/疑词 → 扩展名 → `all_of` 复合 → 白名单特指 → 带类目归档词 → 设计文档/CAD 细分 → 直属父目录=专业词 → 祖先目录继承 → 白名单裸词 → 无类目专业词 → 默认档。
  2. **第二信号**:文件名判不出时取首页正文再按标题词判。PDF 走四态链;docx/xlsx/doc/xls 取"正文头"(`classify_heads.py`,300 字;老格式经 LibreOffice,每份 20s、每次请求共 60s)。
  3. **LLM 兜底**(`classify_llm.suggest`):提示词 = 文件名 + 扩展名 + 路径(已剔项目名容器根)+ 正文头(≤300 字)+ **编号闭集类目表**。要求只回 `{"id": n, "evidence":[≤3 段≤30 字原文]}`(`classify_llm.py:166-181`)。
     - 校验:id 必须 ∈ 闭集;`evidence` 至少一段(≥4 字)是文件名/路径/正文头的严格子串,否则整条建议丢弃。
     - LLM 结果一律 `needs_manual=True, evidence="llm"`,阶段和 disposition 由代码按类目重算(P04)。
     - 走 `chat_json`:`max_tokens=300`、`retry_attempts=1`、总时限 `TAG_LLM_TOTAL_SEC`(默认 30s)、缓存、`TAG_PROMPT_VERSION="tag-classify/v2"`。
  4. **同一份文档只问一次**(sha256 相同,或 doc_key 相同且正文头相同并组)。**批内熔断**:LLM 一次不可用则本批后面不再问,返回 `llm_unavailable` 告警(WS28-k)。
- **数据资产**:
  - `engine/data/classify_rules.yaml`(36,261 B,235 条)。文件头 1-38 行是判定顺序说明。
  - `engine/data/doc_category_map.yaml`(4,854 B):分类器类目 → 清单口径折算 + `not_audited` 列表(`category_vocab.py`)。
  - `tests/fixtures/ws13_classify_golden.json`(47 行金标)、`ws23_tag_expected_38.json`。
- **已知取舍**:"自信错标=0"是验收不变量(`test_classify_golden_ws13.py`)。文件名裸词只给 0.65 且 `needs_manual`。

### 3.2 资料齐套核查 `/engine/audit/check`(`api/audit.py`, `engine/audit_check.py`)

- **入参**:`files_with_tags[TaggedFile{file_id, doc_category, cost_stage, source, evidence, confirm_state, ancestors, doc_key,...}]`、`checklist[ChecklistItem{stage_code, doc_category, item_name, requirement_level: required|important|optional, aliases[]}]`。
- **出参**:`missing[], covered[], pending[], advisory[], coverage_rate(可为 null), coverage_rate_upper, required_total, required_covered, required_pending, degraded_matches, input_stats, input_empty`。
- **算法(纯规则,零 LLM)**:
  - 类目比对前两侧都经 `category_vocab.canonical()` 折算。
  - **证据定级** `grade_of`:confirmed(人工确认或 `source=manual`)> strong(`evidence=="filename_rule"`)> weak(其余,**缺 evidence 的旧行也算 weak**)。
  - 只有 confirmed/strong 进分子。weak 进 `pending`。必备项一条命中都没有进 `missing`,重要项进 `advisory`。
  - **冲突表** `engine/data/audit_evidence_rules.yaml`(1,208 B):strong 命中的目录段含"进度款/产值/付款/支付/结算/审核终稿/套价"时降为 weak。
  - 系统生成物不当证据;同 `doc_key` 只算一份。
  - 无 required 项时 `coverage_rate=None`,不是 1.0。
- 回归测试:`tests/test_audit_gt_regression.py` + `fixtures/ws13_audit_gt/cases.json`(人工判缺失的项一项都不许被判已备)。

### 3.3 咨询字段抽取 `/engine/extract/fields`(`api/extract.py`, `engine/field_extract.py`, `consulting_fields.py`, `approval_grid.py`, `report_sections.py`, `pricebook_fields.py`, `extract_sources.py`, `extract_crosscheck.py`, `evidence_check.py`)

- **入参**:`files[]`, `fields?[]`(Java 按阶段下发的字段名清单), `stage_code?`。
- **出参**:`fields[FieldOut]`,字段见 `schemas.py:158-206`:
  - 值与单位:`field, value, kind(amount/rate/duration/org/text/narrative/date/measure), amount_yuan, unit`。
  - 证据:`evidence[]{file_id, rel_path, sheet, cell, row, page, heading, quote,...}`、`quote`。
  - 通道与核验:`channel(grid/section/regex/regex_fulltext/llm/derived/pricebook)`、`verify_level(strong/weak/none)`、`verified`。
  - 歧义:`resolution(single/priority/unresolved/derived)`、`other_candidates`、`sources`。
  - 衍生:`derived/formula/inputs`、`checks_failed`。
  - 其余:`source_role`、`text_source`、`ocr_risk`、`needs_manual=True`、`prompt_version`。
  - 还有 `failed_files[]`、`skipped_files[]`、`empty_files[]`、`checks[]`(勾稽 E1/E2)、`files_summary{requested=skipped+read_failed+no_text+llm_failed+empty+contributed, cache_hits, llm_calls, deterministic_only,...}`、`warning_items`、`message`。
- **14 字段**(`consulting_fields.py:19-24, 77-170`)分四组:
  - 工程概况:工程名称、建设单位、施工单位、建筑规模。
  - 造价数字:送审金额、审定金额、核减金额、核增额、核减率。
  - 审核正文:审核依据、相关事项审核说明。
  - 前期数据:合同价、招标控制价、工期。
  - 每个字段有 `FieldDef{kind, labels(同义词), definition, excludes, value_rule, deny_labels, needs_number, undecided_suffixes}`。
  - 另有 78 个"概要字段"目录 `engine/data/summary_fields.yaml`(33,937 B)。其中 29+38 个新字段"初稿,待造价员签核"(文件头自述)。
- **流程**(`extract.py:1-47`):
  1. 取材计划 `extract_sources.plan_files`:INDEX/旁车/压缩包/专有格式/转换孪生进 `skipped_files`;按"文档角色"确定性排序。
     - 角色由文件名关键词判定(`consulting_fields.ROLE_RULES`):封面扉页/踏勘单/审定单/汇总表/对比表/审核报告/合同/招标/其它。
     - 定向请求另有细分角色:设计说明/勘察报告/面积表/招标文件/编制说明。
  2. 阶段一:所有识别出角色的文件;阶段二:只针对仍缺 strong 值的字段,在"其它"文件里补抽,有名额上限。
  3. 每份文件三步:读正文(§4,`text_chain.load_document_text`,原件进有内存上限的子进程 `parse_pool.py` / `parse_worker.py`)→ 确定性通道 → LLM。
     - **确定性通道**(0 token):
       - `approval_grid`:审定单/汇总表 xlsx 的表头定位 + 严格金额列语义词表(`consulting_fields.AMOUNT_COLUMN_RULES`)+ 合计行 + `sheet!cell` 坐标。会区分"净核减"与"核减"。
       - `report_sections`:按"一、二、三"切章,"审核依据/相关事项"取整章原文;金额/核减率/工期用锚定正则。
       - `pricebook_fields`:计价工作簿(项目级/单项/单位工程费用表)确定性读取"招标控制价/工程名称",明细表不送模型。
     - **LLM 通道** `field_extract._prompt`(`field_extract.py:303-334`)结构:
       - 开头写文件名 + 文档类型。
       - 按字段分组(数值 / 单位与名称 / 叙述,每组 ≤8 字段)给"定义/同义词/排除/取值规则"。
       - 5-7 条硬规则:value 必须是 quote 的连续片段;quote 必须逐字可在正文找到并含字段标签;叙述类只抄原文;没有就 null;制表符换行写空格。
       - 正文用 `<<<资料正文>>> … <<<资料正文结束>>>` 包裹为不可信数据。
       - 输出 `{字段名: {"value","quote"} | null}`。
     - 正文按 `[工作表]` 切片,每片约 60,000 字(`EXTRACT_MAX_TEXT_CHARS`)。`max_tokens` 8192。全进程并发信号量 6。经 `chat_json_batched`(截断对半拆批、解析失败重试、缓存)。
     - 版本 `FIELD_PROMPT_VERSION="consulting-fields/v4"`,进缓存键,有测试钉住 hash(`tests/test_llm_chat_json.py`)。
  4. 每个候选经 `evidence_check.verify_candidate` 按字段类型核验。引文必须在原文,且保数值。
  5. 合并 `merge_candidates`(`field_extract.py:1570`):排序键含"未核验、来源优先级(`FIELD_SOURCE_PRIORITY`)、通道、弱核验、OCR 风险、路径…",与输入顺序无关。同级冲突留空待选。
  6. 勾稽自检 + 核减率由代码算(`extract_crosscheck.py`)。
- **预算与保护**:
  - token 预算 `EXTRACT_TOKEN_BUDGET` 默认 150 万输入 token,单份文件 ≤34%。
  - 总时限 `EXTRACT_TOTAL_BUDGET_SEC` 默认 540s。
  - 解析子进程 ≤2 个、每个 700MB、120s。文件 ≤200MB、PDF 只读前 300 页。
  - 调用方断开即停调度。
- 失败语义:全部文件失败 422;部分失败 200 + `failed_files`。

### 3.4 计价表三件套 + 预检(`api/stubs.py`, `engine/costsheet.py`, `reconcile_engine.py`, `indicator_engine.py`, `tk_engine.py`, `tk_align.py`, `code_registry.py`, `costsheet_probe.py`)

**输入格式**:广联达导出的 xlsx/xlsm("分部分项工程量清单计价表"、审核汇总表等)。`.xls` 经 LibreOffice 转 xlsx。**不能读 `.gbq*/.gtj/.gcl`**(`api/report.py` 的 `_EXPORT_HINTS` 给出"请导出为 Excel/PDF")。三个端点都是普通 `def`(进线程池)。送检上限默认 60 份 / 300MB,超则 413(`COSTSHEET_MAX_FILES/MAX_TOTAL_MB`)。

**共用取数层** `costsheet.py`(2252 行,纯规则,无 LLM,docstring `costsheet.py:1-48`):
- 表头块检测(前 30 行锚行 + 续行吸收)→ 列路径。
- 列角色 = 量度(qty/price/amount) × 期次(current/previous/cumulative/contract/dated) × 当事方(submit/audit/delta) × 量纲(万元 ×10000)。
- 绑定:候选唯一才绑定,多于一个即歧义,该表不产出行并出 `column_ambiguous`。看不懂就说出来,不猜。
- 行分类:item/lump_sum/title/subtotal。sheet 状态:used/skipped_by_title/skipped_non_list/no_header/ambiguous/summary/unpriced。
- 汇总表与明细表二选一;合计行勾稽偏差 >0.5% 告警。
- 费用表分层 `scan_fee_sheet/resolve_fee_total`:项目级合计与各单位工程之和差 ≤1 元才采用。
- `parse_audit_summary` 读审核汇总表(保留合计/派生行、单元格坐标、Decimal 串)。
- 章节一律走 `code_registry.classify_chapter`。去重只做**跨 sheet**。
- 词表有大量真实世界命名常量(`_SHEET_SKIP`、`_PERIOD_KW`、`_PARTY_KW` 等,`costsheet.py:73-150`),**这是最该整体搬的资产**。

**`/reconcile/run`**:入参 `submitted_file, approved_file, basis(auto/current/cumulative/contract)`。出参 `rows[{item_code,item_name,feature,unit,chapter,submitted_qty/price/amount,approved_*,diff,status,matched_by}]`、`total_diff`、`chapters`、`summary`、`file_coverage`。
- 算法(`reconcile_engine.reconcile`):编码强键(≥3 位)优先,弱键 `名称|特征[:60]|单位`,允许一码多行(队列消费);按"分"比较(ROUND_HALF_UP),≤1 分判一致。
- 核减额 = 送审 − 审定(正=审减,负=审增);核减率 = 核减额 / 送审总价。

**`/indicator/calc`**:入参 `price_files, gross_area, area_source, total_amount, baseline`。出参 `indicators[{indicator_code,value,baseline_value,deviation,label}]`、`summary`、`chapters`、`top_items`、`fee_breakdown`(费用构成六项)、`files_used/failed`。
- 算法:单方造价 = 总造价 / 面积;章节占比;造价驱动项 Top-N;可选同类项目对标(`match_similar`:业态+结构+面积相近打分)。
- 总造价优先级:用户录入 > 费用表合计 > 明细合计。
- **不识别 WBS(单体)归属**。`wbs_units` 参数已不再读(D41 删了面积分摊)。

**`/tk/detect`**(投控异常检测):入参 `submission_files, baseline_files?, baseline?, basis`。出参 `anomalies[{type, severity, detail,...整行定位}]`、`rules_version`、`alignment_issues`、`align_suggestions`、`rules_run/rules_skipped`、`baseline`、`scope_label`。
- 规则:
  - v1:duplicate(同项目+同期+同单位工程内同编码且≥2 行金额非零)、zangu(暂估/暂定/暂列,分四档)、self_check(量×价≠合价,容差 2%)、big_amount(≥20,000)。
  - v2(需合同清单):price_over_baseline(>10%)、qty_over_baseline(>15%)、missing_submit、new_item。
  - 严格对齐才出金额(`tk_align.EXACT`);同码不同名、多行歧义进 `alignment_issues`。
  - 异常身份 uid = (project_id, file_key, sheet, row)。
- 阈值全在 `engine/data/tk_detect.yaml`(3,756 B,版本 `v1-20260711`,**客户侧仍标 draft**)。
- 引擎只产"疑似",终判归 Java/造价师。

**`/costsheet/probe`**(`costsheet_probe.py`):预检文件是否像计价表,返回 `kind ∈ costsheet/other/unknown`、`list_sheets/sheets_total/basis_available`。**响应无任何金额字段**,有白名单测试。预算默认 8s。

**已知缺陷与注意**:
- README 自述:`duplicate` 规则看不到"金额完全相同的重复行",因为 costsheet 跨表去重已吞掉。同表完全相同行 WS08 后已保留(去重只跨 sheet),这条以 README 为准需复核。
- 金标 `tests/golden/*.json` 来自 openpyxl 自造样例,**不是真实项目数据**,只防漂移不证明正确(`test_golden.py` 头注)。

### 3.5 GB50854 清单生成 `/engine/quantity/generate`(`api/quantity.py`, `engine/quantity_list.py`, `quantity_segment.py`, `quantity_rules.py`(3179 行), `quantity_features.py`, `code_registry.py`)

- **入参**:`files[](设计说明 xlsx/docx/pdf/txt)`, `code_version="zj2025"`, `project_name`(解析标段)、`eng_category_name`、`deadline_ms`。
- **出参**:`items[{code(基码+3位流水),base_code,name,unit,features,section,source,sources[{file_name,location,quote,evidence}],practice,part,category,notes}]`、`unmatched[{kind: pending_review/unmatched/excluded_scope/out_of_scope/llm_failed, text, reason_code, suggested}]`、`xlsx_base64`(4 个工作表:清单 / 待核与未匹配 / 覆盖核算 / 说明)、`coverage_detail`、`registry_fingerprint`、`prompt_version`、`usage{llm_calls,cache_hits}`。
- **流水线**(`quantity_list.py:1-34`),切片与去向全部确定性,LLM 只对片段编号做短输出分类:
  1. 读取(sha256 相同只读一份;扫描 PDF 走降级链回调,闭包注入)。
  2. 判专业:`quantity_rules.yaml` 的领域词计数,building_share<0.3 且非房建词≥20 则 `out_of_scope`。
  3. `quantity_segment`:切成 practice/heading/exclusion/other 片段,**原文与位置(`Sheet1!D6(第6行·楼地面做法第4层)`)全由代码产生**。
  4. 片段数闸:最多 800 片段,0 个则 422 `no_practice`。
  5. 层内标记(自理/二次装修/精装修)直接记账,不送模型。
  6. **LLM 分类**:`_SYSTEM_TEMPLATE`(`quantity_list.py:299-329`)把**整张 490 条受控码表(编码|名称|单位)塞进 system prompt**。要求每片段回 `{"id","role": main/aux/base, "c": 9位基码或空串, "ex": 排除句编号, "why": ≤12字}`。附"易混淆对照"(`quantity_rules.yaml` 的 `confusables`,约 14 条)和 5 个"条件候选"编码的受控特征。
     - 批量:每批 ≤40 片段 / 6000 字,并发 3,`max_tokens` 2048,100s 总时限,截断二分,漏答补问。
     - 版本 `QUANTITY_PROMPT_VERSION="qty-2026-10-10.1"`,有测试按指纹钉住。
  7. 闸:码表存在 → **语义一致性闸**(`check_consistency` 只判,从不改码,不一致降"待核",决策 D52)→ 角色闸 → 标段/范围排除(正则 `exclusion_patterns` lot/owner/secondary/not_in_scope)。
  8. 聚合:同码合并、辅层并入、跨来源去重、排序后分配流水号。
  9. 项目特征(`quantity_features.py`):码表 `features_text` 解析为槽位并从 1 重编号;"做法名称/部位"由代码填;其余槽由 LLM **逐字摘录**,取值必须是原文子串,通过标 `〔AI摘录〕`,不通过写"待补(AI 摘录未通过原文校验)"。
  10. **覆盖不变式**:每个 practice 片段恰有一个去向,不成立则 500 `coverage_invariant`。
- 状态码:ok / partial(200);no_text, out_of_scope, no_practice, too_many_segments, no_items(422);全部批失败 / DeepSeek / OCR 不可用(502);超时无结果(504)。错误体统一 `{detail, reason_code, coverage?, unmatched?, usage?}`。
- **数据资产**:
  - `engine/data/gb50854_zj2025.yaml`(94,300 B):浙江 2025 码表,490 条、17 章,含 `Z` 前缀补充码。由 `scripts/convert_gb_registry.py` 从仓外 `…/building-cost-estimator/gb50854_registry.py` 转换而来(该路径硬编码在脚本里,**仓内无法复现**)。
  - `engine/data/gb_chapters_2013.yaml`(3,411 B):仅提供章名,不参与 lookup(D53)。
  - `engine/data/quantity_rules.yaml`(32,298 B)。
- 范围边界:只支持房建 0101–0118;安装/市政/道桥 422。
- 注:父级 `调研-算量层skill化评估.md` 存在,可能已有 skill 化初步评估(我没读)。

### 3.6 概算 `/engine/estimate/*`(`api/estimate.py`(805 行), `engine/estimate_{extract,engine,suggest,render,checks,gates,policy,quality,xlsx_values}.py`, `fee_rules.py`(1711 行))

两段式,"抽取不出数、计算才出数"。

**`POST /estimate/extract`**:入参 `files, template_code="gsyz_v1", project_name`。出参 `candidates[{cell,label,unit,seq,value,quote,confidence,verification,building_names}]`、`unresolved[{cell,reason: not_found/ambiguous/no_text/total_only_no_partition/unmapped_building,candidates,derived}]`、`buildings[]`、`check_values[]`、`text_stats`、`scope`。
- **只抽规模量**(11 个根输入位:面积 ㎡ / 车位 辆),响应无金额字段(有测试扫键名)。
- 流程:`load_document_text` 页级降级链 → 关键词窗口(超 12000 字不再截文首)→ LLM。
- `_prompt`(`estimate_extract.py:402-454`)要求回 `{"buildings":[...],"checks":{...},"cells":{cell:[{value,quote,scope}]}}`。
  - buildings 逐个列单体,面积空则 null;不得拿层数/高度顶替面积。
  - 每格带"路径|口径|同义词|分组"。
  - 原文有多个值全列。严禁输出金额。
  - `max_tokens` 取策略 6000(D-R119),`chat_json`,`ESTIMATE_PROMPT_VERSION="estimate-extract/v3"`。
- 确定性后处理:数值由 `parse_quantity()` 解析(万/亿倍率是 Python 乘法);引文回原文校验(保数值归一);单体按出现顺序归位固定槽位,超出落 `unmapped_building`;槽位合计 vs 原文总面积差 >1% 出 `area_total_mismatch`;建筑密度只作占地提示(`derived`,不进候选)。
- 失败:全部无正文 422(措辞点明 OCR 通道);LLM/OCR 不可用或输出不可解析 502,**绝不 200+空候选**。

**`POST /estimate/suggest`**(全确定性,零 LLM):入参 `inputs, baselines[](Java 查库下发), items, dims, fee_bases, fee_attrs`。出参 `suggestions, unresolved, fee, coverage, totals, required_fee_bases, required_fee_attrs, aggregate_checks, tolerance=0.20`。
- 算法:从模板 224 条 `=C7/E7*10000` 公式反解"成本格→数量格"(150 个成本位),建议值 = 同语义键基准成员**中位数** × 规模 / 10000。样本来源 <3 个 → `reference_only`。包干额不按面积放大;业态不适用不出值;严格查表,不模糊匹配。
- 偏离校核在前端本地做,阈值由引擎单点下发。

**费率规则 `fee_rules.py`**(5.工程建设其他费用,16 条规则,零 LLM):
- 数据 `engine/data/fee_rules_zj2018.json`(49,426 B):16 项。8 种范式:`progressive_difference / base_price_interpolation / banded_value_range_interpolation / banded_rate_range_interpolation / banded_unit_price_progressive / base_rate_range / unit_price_matrix / manual`。
- 数据来自 16 张定额扫描图(`estimate_templates/fee_images/`)由 **LLM 双遍转录**,转录过程见 `fee_rules_transcription.md`(10,741 B)。
- **签核状态是"仓主默认放行,非造价员签署"**(`signoff_kind=owner_release`)。每次求值带 `fee_rules_owner_released` 告警。
- `勘察设计费` 档界闭开性未确认(登记为 `CLOSURE_KNOWN_GAPS`,有测试棘轮),**该条金额单独扣留**。
- C6/C9 是公式格,`write_target=aggregate` 只出小计;工程保险费无数值规则,`manual`。调整系数一律不自动应用。

**`POST /estimate/compute`**(零 LLM):入参 `inputs{cell:number}`(严格拒 bool,pydantic 会把 `true` 静默转 1.0,所以声明为 `Any` 再自检)、`rates`(预备费率,默认 5%,软区间 3–8% 只告警)、`render`、`area_checks, acknowledged_checks, slot_labels, input_sources, fee_bases, fee_attrs, project_profile, generated_at`。出参 `sheets, totals, indicators, input_coverage, rates_used, warnings, quality{review_level: ok/needs_review/draft}, aggregate_checks, xlsx_base64`。
- 拦截闸**顺序由测试钉死**(`estimate.py:558-640`):必填闸(11 个输入位)→ P04 面积闸 → P05 面积对账(可带理由确认放行)→ 全零闸。面积闸必须在全零闸前,因为总面积为 0 时室外成本仍让 C47≠0。
- 求值器 `estimate_engine.run`:对 `gsyz_v1.json` 的 515 条公式拓扑求值。语言只有 SUM + 四则 + 跨表引用;空格按 0;除零得 None + 告警;16 条 `DISPIMG` 不求值。
- 渲染器 `estimate_render.render_estimate`:写 **499 条真 Excel 公式**(不写静态值)、费率独立到 `估概算总表!J46`、末页"生成说明"、5 表 I 列写计费依据、非 ok 时标题加"【草稿】/【需复核】"、`estimate_xlsx_values` 给公式格补 `<v>` 缓存值、同输入逐字节一致(`generated_at` 由 Java 传)。

**`GET /estimate/template`**:返回行树 + 输入位元数据(驱动前端表单)。

**数据资产**(`engine/data/estimate_templates/`):
- `gsyz_v1_template.xlsx`(68,417 B):脱敏模板种子。9 sheet、515 公式、211 输入位。**现在是"修正前形态"**,是 `test_estimate_template_fixes.py` 的证据源,不能随便改。
- `gsyz_v1.json`(264,514 B):由 `scripts/build_estimate_template.py` 确定性生成的引擎模板。含三处原表缺陷修正(F30 错引 E35→E46;哨兵行 SUM 统一含哨兵;序号 float 塌缩重建为字符串 53 处)。
- `gsyz_v1.policy.json`(12,521 B):槽位、面积闸、语义键、抽取锚点与 `extract_max_tokens` 等。
- `fee_images/image1..16.png`(合计约 3.9MB,单张 14–367KB)+ `image_map.json`(5,888 B):16 张《浙江省建设工程其他费用定额(2018)》扫描页,公开出版物,图 ↔ 单元格 I6…I30 ↔ 费用项。
- `README.md`(8,886 B)。

**注意**:真实金标 `TG_GOLDEN_XLSX` 不入仓,L1 回放测试在 CI 恒 skip;CI 靠 `tests/fixtures/estimate_gsyz_v1_synthetic.json`(与 LibreOffice 独立重算一致后固化)。

### 3.7 AI 报告初稿 `/engine/report/*`(`api/report.py`, `api/report_templates.py`, `engine/report_compose.py`, `report_guard.py`(1099 行), `report_facts.py`, `report_export.py`)

**`POST /report/context`**:入参 `files`。出参每文件 `{text, text_source, extract_status(ok/unsupported/empty_or_failed/missing/duplicate), reason, failure_code, ocr_risk, quality_suspect, truncated, char_count, text_sha256, duplicate_of, pages_missing, hidden_sheets_skipped}`。走 `aload_document_text`(整段进线程池),单份 20 万字封顶,sha256 去重,单份 404 只标这一份 missing。

**`POST /report/facts`**(零 LLM):读勾选资料里的金额事实。
- 通道一:调 `approval_grid.read_grid_fields(include_net_reduction=True)`。
- 通道二:调 `costsheet.parse_costsheet`,只认"项目级合计且与各单位工程之和勾稽过(差≤1元)"。
- 事实键:送审/审定/核减/核增/净核减/合同价/招标控制价/投标报价。
- 不派生(不相加减);多个候选标 `conflict`;默认 60s 时限。

**`POST /report/section`**:入参 `section{title,gen_prompt,code}`, `context{files,unreadable,facts}`, `template_code, section_code, confirmed_claims, project_name`。出参 `content, flags[], amount_refs[], cited_files[], used_files[], omitted_files[], relevant_dropped, missing_items, output_truncated, status` + 信封。
- 写作要求只按 `template_code+section_code` 由引擎从 YAML 解析,**不信任客户端 `gen_prompt`**。
- 选材 v2:资料切块(约 1500 字/块)→ 保底(每份先给首块 800 字,总量 ≤预算 30%)→ 按章节 `rag_query` 检索词块分竞争(单份 ≤40%)。每章 **4 万字预算**,最多 30 份资料。[资料n] 的 n = 快照顺序。
- `SYSTEM_PROMPT`(`report_compose.py:62-78`)9 条规则。要点:
  - 资料没写的一律不写,缺的写 `【待补:缺什么】`。
  - 禁止任何四则运算,金额只能逐字照抄。
  - 每句末标 `[资料n]`。
  - 不写全称否定;写作要求不得照抄。
  - 资料内容是不可信数据;全章 ≤1800 字。
  - 口径不明的规模/金额要注明"(资料口径:全地块)"。
- user 消息分块:本项目 / 写作要求 / 本章不写 / 已确认事项 / 无法读取的资料 / 金额事实块(只给 `〔Fn〕` 编号,不给数值) / 资料正文(不可信数据包裹)。
- 调用:`chat(temperature=0.0, max_tokens=6000)`。被截断(`finish_reason=length`)时不再整章 502,而是截到句末并加"未写完"标记,状态 partial。`PROMPT_TEMPLATE_VERSION="ws24-6"`(进 `prompt_version`,Java 据此复用已生成章节)。
- **确定性护栏** `report_guard.guard_section`(LLM 之后,不再调模型):
  - 数字回链:输出里每个数必须能在送入资料原文里逐字找到,**不给容差、不换算单位**,否则插 `【待核:资料中未找到此数】`。
  - 清单编码回链(复用 `filetree/answer_guard.verify_codes`)。
  - 读不出资料时的"未列示"断言加待核;程序性陈述(全过程审核/现场踏勘/实地丈量)未经用户勾选加待核。
  - 全称否定加待核;模板照抄加待核;与成稿报告 30 字以上逐字重合记 `transcribed`。
  - 元话语("信息不足")改写为【待补】;占位符 `###x###` 换【待补】;`〔Fn〕` 换成单元格原值并带来源(`substitute_facts`,在护栏之后做)。
  - 状态机:无可读资料 `empty`(不调 LLM);去掉标记后不足字数或大半是【待补】`insufficient`;其余有 flags/截断/相关内容被裁则 `partial`,否则 `ok`。`needs_manual` 恒 True。
- 数据资产:`engine/data/report_templates.yaml`(**161,035 B,24 套模板**,约 170 章)。模板码如 `tzkz_monthly_v0`(投资控制月报)、`guzhi/gaisuan/yusuan/jiesuan_chengguo`(估/概/预/结算咨询成果报告)、`*_shuoming`、`*_shenhe(_bg)`、`zaojia_shendingdan`、`kzj_bz_baogao(_shizheng/_yuanlin)`、`qd_bz_shuoming(_shizheng/_yuanlin)`。章节字段 `code/title/seq/rag_query/gen_prompt/excludes/claims/facts_allowed/attachment_hints`。`gen_prompt` 统一写成【必备要素】【取材】【格式】【缺失处理】四段。**章节 `code` 是单章重试的定位键,改了会 422**。

**`POST /report/export`**:入参 `title, sections[{title,content,quality,missing_items,flags,table}], disclaimer, appendix`。出参 docx 二进制。`report_export.build_docx` 是**零依赖手写 OOXML**:部件含 styles/header(页眉=免责声明)/document;每个 run 显式设 `w:eastAsia` 字体(标题黑体、正文宋体);XML 控制字符剔除;附录"资料来源与完成度"。

**`GET /report/templates`**:返回 enabled 模板及每章 `prompt_version`。

### 3.8 报表管理 `/engine/reportform/render|inspect`(`api/reportform.py`, `schemas_reportform.py`, `engine/reportform_view.py`, `reportform_baseline.py`)

- 零 LLM、无状态。只支持 `gsyz_v1`。
- **render**:`origin: blank|edit` + `context`(重渲上下文,`extra=ignore` 白名单取键)+ `base_context` + `deadline_ms`。跑与 compute **同源同顺序的闸**,但不拒绝,只降为"草稿"并点名理由。产物最高只到"需复核"(CAP_MESSAGE)。出 xlsx + 视图 + 完成度 + 质量结论。
- **inspect**:一本 xlsx → 只读视图(冻结/列宽/合并/非空单元格 `{r,c,t,v,d,f,role}`)。防护先于解析:只收 `.xlsx`,读 zip 目录就判条目数(500)、解压总量(50MB)、单条目(20MB)、视图总格数 200,000。超行列上限标 `truncated` 并告警。
- 基线公式集合 = 渲染器当前版本空白输出(501 个公式格),不是 `gsyz_v1.json`。

### 3.9 AI 对话网关 `/engine/chat/complete`(`api/chat.py` 1616 行 + `api/chat_writing.py`, `app/filetree/*`)

- **入参** `ChatCompleteIn`(`schemas.py:965-991`):`query, module(all|knowledge|project), messages[](≤10 轮,每条带 role/content/turn/failed), project_ids[], skill_id, session_id, think, attachment_paths[]`,另 `sysCompanyCode`(camelCase 落 extra)。
- **出参**:SSE,**OpenAI 兼容帧** `data: {"choices":[{"delta":{...}}]}`,以 `data: [DONE]` 收尾,不用具名事件。
  - 扩展字段挂 delta 同级:`delta.plan / step / attribution / reference.chunks`。
  - usage 与 `nav{stopped, answer_kind, n_steps, n_failed_steps}` 放在最后一个数据帧。
  - 终态纪律:任何异常转成 content 帧"[生成中断:…]"再 `[DONE]`,因为前端没有带内错误帧格式(D5)。
- **"流式"是假的**:`llm_client.chat` 非流式(`stream:false`),整包拿到后按 24 字符切片、每片 sleep 20ms 下发(`chat.py:89-90, 276-294`)。有旧前端兼容用的 `time.sleep(0.8)`(`chat.py:1415-1421`)。
- **路由**(`chat.py:1522-1566`):
  - `all`:`_stream_llm`,直接多轮 LLM,`temperature=0.3`、`max_tokens=4000`,**不检索**(D31)。人设由 `skill_id` 所属技能组决定:技能目录 `engine/data/skills.json`(11,106 B,63 个技能 f01–f63、8 组)里"写作"组(f01–f08)用写作人设(`chat_writing.py`,7 个模板),否则 `_SYSTEM_GENERAL`。其余 55 个技能只是目录,引擎侧无行为。
  - `knowledge`:`root=knowledge/<sys_company_code>`,租户号优先取 `X-Sys-Company-Code` 头,缺席才回落请求体(打 WARNING)。
  - `project`:`project_ids` 必须恰好一个且是单一路径段,`root=project/<id>`。
  - 两档检索根都过 `_validate_root_rel` 双层白名单。
- **检索档流程**(`_stream_filetree`,`chat.py:1246-1420`):
  1. 追问改写 `_rewrite_followup`(一次 LLM,`max_tokens=200`,15s):`_REWRITE_SYSTEM`(`chat.py:440`)要求只输出 `REWRITE: …`/`KEEP` + `REF: 第n轮`。台账带轮次,清洗页脚与 `[ID:n]`,改写引入上文没有的编码则判失败。
  2. `agent.navigate`(§3.12)。
  3. 有附件则追加一次"合并轮"LLM(`_SYSTEM_MERGE`);写作技能再追加一次"按技能成稿"LLM。
  4. 引用后处理:`〔E编号〕` 标记 → 只发被引证据 → 换成前端认的 `[ID:k]`,chunk 带 `source`;`_anchor_chunk` 把整段读取的引用对准被引的行/页/段。
  5. `answer_guard.review_answer`(3 档共用)。
- **`answer_guard.py`(1147 行)**:数字回链(`find_numbers`/`NumberIndex`)、算式与合计复算、页脚"以原件为准/须复核"、提示注入防护(`DATA_BOUNDARY`)、清单编码按 zj2025 码表核对、LaTeX 公式转纯文本(`PLAIN_FORMULA`)、字数约束(>1.1×则压缩一次)、编造条款检测(`fabricated_terms`)。
- **附件**(`chat.py:204-266`):`attachment_paths` 经 `read_file_bytes`;PDF 空文本走旧版 `pdf_text_with_sidecar`(§4);附件+问题合计 >80,000 字符 422;OCR 来源的附件前置"来自 OCR 请核对原件"提示。
- 取消:`filetree/deadline.stream_cancel_on_close` 包装同步生成器,断连即置位 cancel(生产实测过一次全库 grep 跑了约 14.5 分钟的事故)。
- 3 个 history 端点已迁 Java,仅返回空壳。

### 3.10 `/engine/filetree/ask`

同一 `agent.navigate`,但发**具名 SSE 事件**(`plan/step/reference/message/done/error`),与 chat 的 OpenAI 帧不同。无生产调用方。

### 3.11 `/engine/health`

`{version, llm_ready, file_root_ok, ocr_ready}`,仅看配置齐全性,不探活。

### 3.12 检索/知识库导航机制(无向量,无索引)

核心 `app/filetree/agent.py`(2181 行)、`tools.py`(2242 行)、`mapper.py`、`closing.py`(2582 行):
- **每次提问现场 `os.walk` 生成目录地图**(`mapper.py`,`MAP_MAX_LINES=400`,8s 预算),塞进 system prompt。"无索引"是明确的设计决定。
- LLM 每步**只输出一行 DSL 指令**:`LIST / OUTLINE / SHEET / DOC / PDF / GREP / SCAN_HEADS / ANSWER`(`agent.py:1360-1423` 的 `_SYSTEM_TMPL`,`NAV_MAX_TOKENS=1200`)。
  - `GREP` 是纯 Python 字面量扫描,多关键词=同一检索单元内 AND;txt 一行 / docx 一段或表格行 / xlsx 一行 / PDF 一行。
  - 文件状态四态 readable/need_ocr/failed/unknown(`tools.py` D-6)。
- 预算:`max_steps=8`、失败步额外 4、LLM 调用总闸 14、墙钟 90s(收尾预留 12s)、单步工具 30s、LLM 单次 45s。
- **硬拦与确定性护城河**:
  - ②③④⑤ 硬拦:读不了的文件被拦、同键重复指令回放不计步、第 3 次收尾、同文件读新区间 ≤5 次。
  - 路径逐段纠错(去数字前缀/ID 前缀/全半角)、动词与文件类型不匹配先改写。
  - 文件名锚定(收紧后只在"明确指向"时强制先读)。
  - 项目档问"投控/齐套/指标/对账"这类只存在库里的结果,导航前直接指路,不调模型。
- **收尾** `closing.closing_answer`:步数/时间用完不再回"未能给出结论"。有内容证据则一次收尾调用只依据编号证据作答(`answer_kind=partial`);否则确定性拼出 `not_found/unreadable/unfinished`。`answer_kind` 词表:`answer/partial/not_found/unreadable/unfinished/cancelled/empty`,并有到 C1 outcome 的映射(`closing.py` `ANSWER_KIND_OUTCOME`)。
- **OCR 旁车**(`x.pdf.ocr.txt` 或 `x.ocr.txt`)在 PDF 文字层无效时按页顶上;原件在场的旁车不单独成文件(地图/LIST/GREP 都隐藏,引用记在原件上)。超大扫描定额书直接检索旁车。
- 空根(`_root_is_empty`)直接回"该范围还没有文件"(`retrieval_root_empty`);根不可读回 `retrieval_root_unavailable` + `error_id`,真实路径只进服务端日志。

## 4. OCR "四态降级链"集成点

- **服务**:独立容器 `ocr-service/`(同仓,RapidOCR 3.9.2 + onnxruntime,即 PP-OCR 系 ONNX,不是 paddlepaddle)。契约 `docs/契约-ocr-service-v1.md`(v1.1):`POST {OCR_BASE_URL}/ocr/recognize`,body `{content_b64, file_name, lang, max_pages, deadline_ms}`,头 `X-Service-Token`。**传 base64,不传路径**(两服务不共享文件系统)。
- **客户端** `app/ocr_client.py`(564 行):`recognize()`(整份)与 `recognize_pages()`+`OcrSession`(按页)。
  - 错误分型:`OCRUnavailable`(可重试→502)与 `OCRInputError`(400/413/422,不可重试→按"无正文")。
  - `OCREmptyResult` 继承 Unavailable 但**不熔断**。
  - 会话级预算与熔断:预算分场景(字段抽取/对话附件 45s、报告 90s、默认 60s);页级切 ≤6 页子 PDF;单文件默认 ≤30 页;大小闸 30MB。
- **配置**:`OCR_BASE_URL` 未配时 `ocr_ready=False`,扫描件只能靠旁车,无旁车明确报错,不静默空。
- **两份实现并存(整合时要注意)**:
  1. **新:页级** `app/text_chain.py::load_document_text`(559 行,宣称"统一抽取入口 C6")。逐页判定文字层可用(`textextract.page_status`/`classify_pdf_pages`,识别 blank/thin/garbled/扫描水印)→ 按页取旁车(旁车页数与 PDF 不一致则不按页对位)→ 其余页交 `OcrSession` → `merge_pdf_pages`。带 sha256 进程内缓存(`text_cache.py`,`TEXT_CACHE_MAX_CHARS` 默认 4M 字符)。**用户:** `extract/fields`、`report/context`、`estimate/extract`。
  2. **旧:整份级兼容函数** `textextract.pdf_text_with_sidecar`(`textextract.py:945-973`),文字层 → 旁车 → OCR → none,**整份文字层为空才补**,混合 PDF 的扫描页会被丢。**用户:** `chat.py`(附件)、`tag.py`(首页正文第二信号)、`quantity.py`(`pdf_fallback`)。docstring 自述"六个消费端迁到 text_chain 之后再删"。
- **旁车格式** `engine/sidecar_format.py`(370 行):生产 NAS 上 2882 份旁车全是分页格式(`## pN` 锚点 + `> ` 卷头/判定行)。按**白名单**剥元数据,白名单外的 `> ` 行保留;**"一页可用的都没有"判为未命中**(曾有 754 份全是"OCR 连续失败"占位句的旁车被当正文)。写侧版式在 `sidecar_layout.py`,补跑工具 `app/tools/ocr_backfill.py`。
- `files.read_ocr_sidecar_doc` 做软链逃逸与跨租户越权防护。

## 5. 数据资产清单(`app/engine/data/` 及相关)

| 路径 | 大小 | 内容 |
|---|---|---|
| `classify_rules.yaml` | 36,261 B | 235 条文件名分档规则 |
| `doc_category_map.yaml` | 4,854 B | 类目 → 清单口径折算 + not_audited |
| `audit_evidence_rules.yaml` | 1,208 B | 齐套核查冲突表 |
| `gb50854_zj2025.yaml` | 94,300 B | 浙江 2025 GB50854 码表,490 条 / 17 章 |
| `gb_chapters_2013.yaml` | 3,411 B | 2013 国标章名 |
| `quantity_rules.yaml` | 32,298 B | 清单生成确定性规则(专业词、做法词表、层角色词、混淆对照、排除句正则) |
| `tk_detect.yaml` | 3,756 B | 投控规则阈值(v1-20260711,draft) |
| `summary_fields.yaml` | 33,937 B | 78 个概要字段目录(初稿待签核) |
| `report_templates.yaml` | 161,035 B | 24 套报告模板 |
| `skills.json` | 11,106 B | 63 技能目录(仅写作组 f01–f08 有后端行为) |
| `fee_rules_zj2018.json` | 49,426 B | 16 条其他费费率规则(LLM 转录,仓主默认放行) |
| `fee_rules_transcription.md` | 10,741 B | 转录过程记录 |
| `estimate_templates/gsyz_v1_template.xlsx` | 68,417 B | 脱敏概算模板种子 |
| `estimate_templates/gsyz_v1.json` | 264,514 B | 固化引擎模板(515 公式 / 211 输入位) |
| `estimate_templates/gsyz_v1.policy.json` | 12,521 B | 模板策略 |
| `estimate_templates/fee_images/image1..16.png` + `image_map.json` | 约 3.9MB + 5,888 B | 16 张定额扫描图 |
| `estimate_templates/README.md` | 8,886 B | 脱敏/公式/缺陷说明 |
| `scripts/data/classify_rules.pre-ws13.yaml` | 27,549 B | WS13 前 204 条快照(仅供 delta 对照) |
| `tests/fixtures/`、`tests/golden/` | 合计约 4MB(`tests/`) | 金标与自造 xlsx |

## 6. 外部依赖

`requirements.txt`(直接依赖,无锁版):`fastapi, uvicorn, pydantic, httpx, PyYAML, openpyxl, pypdf, pytest`。注:README 声称的 `python-dotenv`、`python-multipart` 实际不在 requirements 里(`.env` 用手写解析器,`config.py:_parse_env_file`)。

**承载领域逻辑的**:
- `openpyxl`:xlsx 读写。costsheet 全部解析、概算 xlsx 渲染、报表视图的底座。`engine/xlsx_tolerant.py` 做样式表损坏兜底。
- `pypdf`:PDF 文字层 + 切页 + 扫描探针。表格版面还原是**自写**的(`textextract.layout_table_text`)。
- **自写 OOXML 读写**:`docx_reader.py`(907 行,含编号/修订/域)、`textextract.read_xlsx`/`_read_xlsx_raw`(纯 XML 回退)、`report_export.build_docx`(手写 docx 输出)。
- **LibreOffice headless**(apt `libreoffice-calc/writer`,非 pip):`.doc/.xls` → docx/xlsx 转换(`textextract.libreoffice_convert_ex`,超时 60s `SOFFICE_TIMEOUT_SEC`);scripts 里用它独立重算概算公式做交叉验证。
- `PyYAML`:规则数据加载。

**纯基础设施**:`fastapi/uvicorn/pydantic/httpx`(`llm_client.py` 自己用 httpx 流式读以实现总时限)。DeepSeek 调用无 SDK,走 OpenAI 兼容 `/v1/chat/completions`。

**不存在**:pandas、python-docx、pdfplumber、pymupdf、任何向量库/embedding、tiktoken(token 估算用 `字数/1.4`,`field_extract.CHARS_PER_TOKEN`)。

## 7. LLM 客户端要点(`app/llm_client.py`,可直接复用其设计)

- 非流式,`temperature` 默认 0.1(chat)/ 0.0(`chat_json`)。读间隔超时 + **整次总时限**(流式读 body 时每块检查,防"先 200 再吊着发保活字节"挂 15 分钟)。
- `chat_json`:`max_tokens` 与 `prompt_version` **必填**;`finish_reason=length` 抛 `LLMTruncated`(不解析半截 JSON);`LLMUnavailable` 退避重试(凭据缺失不重试);解析失败重新调用;进程内 LRU 缓存(键含 model/prompt_version/temperature/max_tokens/messages 全文/scope,默认 2000 条 / 24h);`deadline` 含取消信号。
- `chat_json_batched`:截断时对半拆批。`pick_exact`:闭集严格等值匹配,替代子串匹配。
- 纪律闸:`tests/test_llm_call_discipline.py` 棘轮盯裸 `chat` 不带 `max_tokens`。
- 所有异常文本经 `redact()`(`app/redact.py`)脱敏。

## 8. 已知缺陷 / 硬编码 / 待签核

- **TODO/FIXME/XXX**:`app/` 与 `scripts/` 中**未发现**真正的 TODO/FIXME 标记(命中的都是业务词"待补/TODO 占位符")。缺陷以"已知缺口/待签核"形式写在注释里:
  - `勘察设计费` 档界闭开性未确认:`fee_rules.py:30,859`,`CLOSURE_KNOWN_GAPS`。
  - 费率规则集"仓主默认放行,非造价员签署":`fee_rules.py:917-1003`。
  - `tk_detect.yaml` 阈值 draft。
  - `summary_fields.yaml` 全部定义"初稿待签核"。
  - 概算偏离阈值 `DEFAULT_TOLERANCE=0.20` 是"未经造价员确认的占位默认值"(`estimate_suggest.py:45`)。
  - `classify_rules.yaml` 的 `classify.confidence.content_signal=0.7`、`bare=0.65` 等运行参数不是客户确认值(`classify_rules.py` `_DEFAULTS` 注释)。
- **本机路径硬编码**:`/Users/cuiqq/...` 出现在 `config.py:18`(注释)、`scripts/convert_gb_registry.py:15`(**唯一真依赖外部路径**,码表转换源)、`Dockerfile:43-45`(注释)、`.env.example`、`README.md`。
- 引擎**不能读广联达原生工程文件**(`.gbq*/.gtj/.gcl`),需用户先导出 xlsx/PDF。
- `filetree/tools.py` D-5:越界错误消息会回显 `rel`(注释自述"若将来进入模型上下文需同时改");`pdf_text` 路径无 pymupdf。
- 对话"流式"是伪流式(见 §3.9);`time.sleep(0.8)` 为旧前端兼容,注释称"下个版本删除"。
- `ChatCompleteIn.skip_retrieval`/`module="none"` 是遗留无效字段。
- 未移植(README 自述):素材仓 `deepread.py`(988 行)、`audit.py`、`attribution.py`、`tk_submission_store.py`、`tk_anomaly_store.py`(复核状态机持久化,在 Java 侧)。
- 时区硬编码 Asia/Shanghai(`chat_writing._CN_TZ`、Dockerfile `TZ`);写作模板"文号 〔2025〕 当前 2026 年"一类时间敏感的防编造规则靠 `today_forms()` 注入日期。

## 9. 测试中值得保留的行为文档

| 测试 | 记录的行为 |
|---|---|
| `test_golden.py` + `tests/golden/*.json` | 对账/指标/投控输出冻结回归(自造样例,非真值) |
| `test_audit_gt_regression.py` + `ws13_audit_gt/cases.json` | 人工判缺失的必备项不许判已备;召回只升不降 |
| `test_classify_golden_ws13.py` | 自信错标=0 棘轮 |
| `test_llm_call_discipline.py` | 裸 `chat` 必须带 `max_tokens` |
| `test_async_handlers_nonblocking.py` / `test_stubs_sync_limits.py` | async 路由不直接调阻塞函数;三个计价端点不阻塞 health |
| `test_tenant_scope.py` | ContextVar 必须穿过流式生成器和线程池(`BaseHTTPMiddleware` 写法会转红) |
| `test_estimate_golden_replay.py`(需 `TG_GOLDEN_XLSX`)、`test_estimate_template_fixes.py`、`test_estimate_gates_refactor.py` | 515 公式逐格一致;闸顺序钉死 |
| `test_fee_rules_*` | 费率数据自证性(溯源、档位递增、速算扣除数等价)、`CLOSURE_KNOWN_GAPS` 不增长 |
| `test_llm_chat_json.py` | 提示词 hash 钉住,改措辞必须升 `*_PROMPT_VERSION` |
| `test_quantity_pipeline.py::test_prompt_version_pinned` | 清单提示词指纹 |
| `test_costsheet_*`、`fixtures/costsheet_shapes.py`(76,738 B,≥14 种真实版式) | 广联达版式识别;`test_fixture_shapes_used.py` 防孤儿夹具 |
| `test_report_guard.py` + `fixtures/report_guard/ws24g_realrun.json`(92,947 B) | 真实运行取证的护栏判例 |
| `test_design_doc_code_index.py` | 设计文档代码位置索引机械核对 |
| `test_costsheet_probe.py` | 预检响应无金额字段(源码闸白名单) |

## 10. 评估:值得移植的领域逻辑 vs harness 已提供的管道

### 值得移植(领域逻辑,不可替代)

1. **`costsheet.py` + `code_registry` + 词表**:广联达计价表版式识别、列角色绑定、费用表分层勾稽。2252 行规则沉淀 + 14 种版式夹具,是 reconcile/indicator/tk/report-facts/字段提取共用底座。**最高优先级,建议整体作为一个确定性 skill/工具而非拆散**。
2. **规则数据**:`classify_rules.yaml`、`doc_category_map.yaml`、`audit_evidence_rules.yaml`、`gb50854_zj2025.yaml`、`quantity_rules.yaml`、`tk_detect.yaml`、`summary_fields.yaml`、`report_templates.yaml`。数据与口径,带客户确认/待签核状态,迁移时要连同 status 与出处一起带。
3. **证据定级与"不自信地错"的纪律**:`grade_of` 三档证据、weak 不进分子、`needs_manual` 恒 True、失败不返回 200+空。这是产品口径,不是实现细节。
4. **概算引擎**:`estimate_engine`(515 公式拓扑求值)+ `gsyz_v1.json` + `estimate_render`(真公式写出)+ 四道闸顺序 + `fee_rules`(16 条费率,需同时带 signoff 状态)。纯确定性,最适合做成一个计算工具。
5. **确定性读取通道**:`approval_grid`(审定单列语义/净核减区分)、`report_sections`(章节切分+锚定正则)、`pricebook_fields`、`evidence_check.verify_candidate`、`amounts`(金额解析与回链,全仓唯一实现)。
6. **LLM 提示词本体与其配套的校验**(不是调用封装):字段抽取提示词(定义/排除项/取值规则)、清单分类提示词(角色 + 易混淆对照 + 受控码表)、报告 `SYSTEM_PROMPT` + 24 套章节 `gen_prompt`、概算抽取提示词。**与之配套的后置确定性校验同样是资产**:引文逐字回原文、数字不容差回链、语义一致性闸不改码、槽位摘录子串校验。
7. **清单生成的确定性切片器** `quantity_segment` + `quantity_rules`(5k 行):原文与位置由代码产生,LLM 只给编号。
8. **报告护栏** `report_guard`(1099 行)与 `answer_guard`(1147 行)。
9. **OCR 旁车格式解析**(`sidecar_format.py`):含生产踩坑(占位句整份旁车判未命中)。
10. **检索导航的"护城河"**:DSL 指令集、硬拦、重复回放、已读区间判定、收尾 `closing`、`answer_kind` 词表。**但若新 harness 自带文件读取/grep 工具,这部分的价值在于"约束与护栏规则"而非工具本身**。

### 是管道(harness 通常已提供,可丢)

- FastAPI 路由壳、`PassthroughMixin`、`X-Service-Token` 鉴权、`ResultEnvelope` 的 HTTP 形态(**其语义要保留**,即 status/coverage/warning_items 与 needs_manual)。
- `llm_client` 的 HTTP 封装、重试、缓存、总时限、`redact`(**设计可借鉴**:`max_tokens`/`prompt_version` 必填、截断绝不当结论、闭集严格等值)。
- SSE 帧拼装、伪流式切片、`stream_cancel_on_close` 断连取消、`request_guard.Deadline`。
- `parse_pool.py`/`parse_worker.py` 子进程内存隔离(若 harness 沙箱已隔离则可丢,但"解析大文件会 OOM"的事实要保留)。
- `tenant_scope.py` + `files.resolve_safe_path` 的租户/用户子树授权(取决于新 harness 的权限模型)。
- `text_cache.py`、`config.py` 的多层 env 读取。
- 对话历史台账/追问改写(`_history_turns`、`_rewrite_followup`)是对话层通用逻辑,harness 若有多轮上下文管理可简化,但"REWRITE/KEEP + REF 第 n 轮 + 引入上文没有的编码则判失败"这套细节有实跑教训。

### 移植时的风险提示

- **Java 依赖面**:Java 侧 `TaskOutcomeJudge`/`EngineClient` 按 `status/status_reason/coverage/warning_items` 契约解释结果。若重实现为 skill,需决定输出契约是否保持。
- **提示词版本进缓存键**:改任何措辞都必须升 `*_PROMPT_VERSION`,否则命中旧缓存。迁到别的缓存机制时这条约束要保留。
- **签核状态是数据的一部分**:`fee_rules`、`summary_fields`、`tk_detect` 均未经造价员最终确认,不应在迁移后被"洗成"已确认。
- 码表转换脚本依赖仓外文件,码表 yaml 是唯一可追溯的产物。
- 我没有逐行读完 `closing.py`、`tools.py`、`quantity_rules.py`、`report_guard.py`、`field_extract.py` 的全部实现细节,以上描述基于其头部 docstring 与关键函数;具体边界条件请以对应测试为准。
