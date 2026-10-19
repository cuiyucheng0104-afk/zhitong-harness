# zhitong-cost-ai 文档与知识库勘察报告（只读，未改动任何文件，未读 .env）

仓库根：`/home/user/zhitong-cost-ai`（下文路径均相对此根）。

**读到的范围**
- 完整读过：`CLAUDE.md`、`README.md`、`CONTRIBUTING.md`、`.kb/` 里的 README、business-logic、faq、deployment、project-config、database。
- 完整读过：四份调研、集成设计 v2、开发方案、数据模型映射、两份前端诊断、交接文档（部分段落）。
- 完整读过：PRD、安全待办、凭据轮换手册、`报告-建筑章GB50854映射覆盖率.md`、待客户确认事项清单、开发清单-条目化-v1、报告模板扩充包 README 与 manifest。
- 读过总纲或头部：`2026-09-29-生产质检整改-design.md`（全文）、`2026-10-01-实跑全量测试整改-design.md`（总纲前 120 行）、WS14 与 WS29 头部。
- 抽样读过：`deploy/README.md` 的备份、多租户、开通租户章节，`backup-nightly.sh`、`tos-backup-upload.py` 头部，若干 `engine-service` 数据文件头，`裁定/裁定记录.md` 前 80 行，AGENT 文档若干段。
- 没读全：`.kb/changelog.d/` 的 388 个片段没有逐个读，只按文件名聚类，并抽读了 5 个。
- 没读：`.kb/api.md`、`tech-stack.md`、`testing.md`、`AGENT-变异覆盖率泳道.md`、`AGENT-G`、`阶段I-接口契约.md`（57KB）。
- 只读了头部：WS21–WS29 九份子 spec（共约 2.3MB）。

**先说三件会影响判断的事实**
1. 仓里没有任何关于 DeepSeek Harness 或 Cordis 的设计。我用 `grep -i "harness|cordis"` 搜过，命中的只有 CI 脚本里的无关字样。以往的"skill 化"思考只涉及两样东西：`zhitong-gateway` 的 63 个文本 skill，以及 `building-cost-estimator` 这一个 skill。见 C 节。
2. 代码规模：`engine-service/app` 约 5.2 万行 Python，Java `costai` 域约 2.9 万行（155 个文件），前端 212 个 vue。已有 201 个 engine 测试文件、328 个 Java 测试类、96 个前端校验闸脚本。迁移不是小改。
3. 项目 `CLAUDE.md` 的"八条铁律"约束着任何新设计：
   - 引擎不碰 MySQL，写库只有 Java。
   - LLM 不碰金额，抽取结果必须经用户确认，`needs_manual` 恒为 True。
   - 严格查表，不做模糊匹配，宁可空也不编码。
   - 终态只有 done 和 failed。
   - 空结果不是成功。
   - 预备费率不设硬闸。
   - `project_file` 的列和摄取链路冻结。

---

## A. 产品要解决的业务流程

### A.1 用户与角色
- **产品定位**：智通数工 AI 造价副驾（原名天工智通 / yidu-nas 二开）。服务造价咨询企业，目标是多租户 Web SaaS，一家公司一个库。`PRD-造价AI-SaaS化-v1.md` 的目标用户有三类：
  - 造价工程师：导入资料、抽字段、齐套核查、对账、算指标、出报告。
  - 公司管理员：管用户、部门、权限，看 AI 用量。
  - 平台运营（我方）：开租户、监控、计费。
- **系统角色键**（`前端诊断-功能与层级全景.md` §4）：`sys_admin`、`admin`、`knowledge_admin`、`project_admin`、`audit_admin`、`common`。
- **文档里没有专门的"项目经理"角色**。最接近的是 `project_admin`（项目管理员）和 `audit_admin`（审核员）。WS02-P2 记录过：role 表缺 2/3/5/6 种子，导致项目管理员和审核员身份全丢。
- **终端客户**：承接政府投资项目（医院、监狱等）的咨询公司，涉及数据出境和等保问题（`待客户确认事项清单.md` 第 3、4 条）。

### A.2 项目生命周期（实际落地的 8 个入口）
项目工作区本来有 7 个预留的 AI 功能卡（项目资料、AI摘要对比、报告管理、报表管理、成员管理、项目驾驶舱、AI资料审阅），造价 AI 能力接到这些槽位背后（`前端诊断-实机UI走查-20260822.md` §4）。流程如下：
1. **建项目**：
   - 服务范围三选一：全过程造价咨询（20001）、结算审核（20002）、招标控制价编制（20003），存在 `project_service_scope`。
   - 另有项目性质（国有/非国有）、12 个工程分类。
   - 建项目依赖"默认概要模板"种子。种子缺失时报"未找到默认概要模板"，还会留下孤儿项目行。
2. **资料收集**：
   - 文件在 `project_file` 树（冻结，不许改列）。上传走 HTTP 分片，也有对 NAS 的同步。
   - 实测：单个公司资料约 140GB（文档 60GB、图纸 79GB）；单项目峰值 3.3GB。
   - 67% 的 PDF 是扫描件，走 OCR 四态降级链 `text_layer → ocr_sidecar → ocr_service → none`。
3. **标注**（`/engine/tag/classify`）：
   - 为每个文件打 `doc_category`（约 80 个类目）和 `cost_stage`。
   - `cost_stage` 取 6 个枚举：估算 / 概算 / 招标控制价 / 施工过程 / 结算 / 审定。
   - 规则库是 `classify_rules.yaml`（235 条规则：whitelist 90、blacklist 48、archive_keyword 42、upgrade_whitelist 21、archive_ext 15、ancestor_context 14、noise 5）。
   - 判定顺序共 13 步，写在文件头。规则判不出才走 LLM 兜底，再判不出就 `needs_manual`。结果落 `project_file_cost_tag`（一文件一标注）。
4. **齐套核查**（`/engine/audit/check`，纯规则，零 LLM）：
   - 按"阶段 × 应收类目"算 `coverage_rate` 并列缺件。清单表是 `cfg_checklist_stage`（概算、招标控制价、施工过程、结算、审定 5 阶段）和 `cfg_checklist_item`。
   - 清单项带 `aliases`、`requirement_level`（1 必备 / 2 重要 / 3 可选）。
   - 通用清单约 20 项，另有结算审核专属 12 项、招标控制价专属 4 项。
   - 分类器类目与清单类目之间用 `doc_category_map.yaml` 折算。
   - 只统计 `needs_manual=False` 的标签；阶段采用累计口径。
5. **抽取**（"AI摘要对比"，现更名"项目概要"）：
   - 从合同、审定单等资料抽字段，每个值必须带原文 quote 并通过核验。
   - 字段定义：`consulting_fields.py` 的 14 个老字段，扩成 `summary_fields.yaml` 的 78 项，按阶段分组 G1 基本信息、G2 工程概况、G3 工程特征、G4 概算、G5 招标与合同、G6 结算、G7 计价及政策依据。
   - 金额类走确定性读取（审定单、汇总表网格），不让 LLM 转写。
   - 抽取结果须人工"采纳"，落 `project_core_info`（含 `approve_state` 等 4 列）。
   - 这些值最终喂给报告占位符（106 个种子名）。
6. **核对（对账）**（`/engine/reconcile/run`）：
   - 解析广联达 GBQ7 导出的"分部分项工程量清单计价表"Excel。
   - 编码优先、名称|特征|单位兜底，逐行比送审与审定，算核增/核减，按章节汇总。结果落 `cost_reconcile_result`。
7. **指标**（`/engine/indicator/calc`）：单方造价、专业占比、与基准的偏差，可对标同类项目；落 `cost_indicator_result`。
8. **投控**（`/engine/tk/detect`）：
   - 对送审清单检测异常。规则有：重复计取（duplicate）、暂估价滥用（zangu）、行内自洽（self_check）、大额（big_amount）。
   - 带合同基准时再检单价超合同、工程量超合同、送审漏项、合同外新增。
   - 阈值全在 `tk_detect.yaml`。
   - 异常有人工复核状态 pending / confirmed / dismissed，并有只追加的决策日志。
9. **报告**：
   - AI 初稿：24 套模板、172 章，逐章生成，人工审校后定稿，定稿 docx 落 `project_file`。
   - 正式报告：在模板库里放 docx 模板，服务端用 `DocxPlaceholderRenderer` 替换 `{名称}` 占位符，数据来自项目"汇总信息"。
10. **驾驶舱与 AI 用量**：Java 实时聚合各结果表，另有 `ai_usage_log`。
11. **旁支能力**：
    - 概算（`gsyz_v1` 模板，515 条公式）。
    - GB50854 清单框架生成。
    - AI 对话和知识库问答，四档范围：全局、无库、知识库、项目。
    - 63 个办公 skill 面板（`skills.json`，8 组）。

### A.3 "送审"和"审定"
- **送审**是施工方（承包人）报送的计价；**审定**是咨询单位核定后的计价。
- `engine-service/app/engine/reconcile_engine.py` 的口径：
  - 核减额 = 送审合价 − 审定合价，正数为审减，负数为审增。
  - 核减率 = 核减额 / 送审总价。
- `project_baseline` 表只存送审口径（合同约定的控制价或投标价），"永不出现审定/核减列"，要靠契约测试保证。
- 术语约定：不要把"审定"和"核定"混用，不要把"标注"和"审阅"混用（`.kb/business-logic.md`）。
- 业务上，"结算审核报告"归"审定"阶段（issue #210 的暂定裁决）。

### A.4 "国标清单 GB50854 核算"在本产品里的实际含义
- **并没有做"工程量计算"**。这是最需要对 owner 说清的一点。具体有四块：
  1. **码表**（`engine-service/app/engine/data/gb50854_zj2025.yaml`）：
     - 490 码 / 17 章，其中 332 个国标 9 位码，158 个浙江补充 `Z` 前缀码。
     - 带 `features_text`（项目特征模板）、`name`、`unit`。
     - 版本只用 zj2025（浙江 2025）；国标 2013 与它同码异名的有 241 个，其中 164 个名称不同，另有 89 个 Z 码去 Z 后撞号。2013 只用来提示撞号（D53）。
  2. **清单框架生成**（`quantity_list.py`、`/engine/quantity/generate`）：
     - 输入是设计说明类 xls / xlsx / docx。
     - 流程：判专业范围（市政、安装不套房建码）→ 切片分类（做法片段 / 标题 / 排除句 / 其他）→ LLM 只对片段做短输出分类 → 严格查表 → 语义一致性闸（不一致降为"待核"，不自动改码）→ 标段排除 → 聚合排序 → 特征回填 → 覆盖核算 → 输出 4 个工作表（清单 / 待核与未匹配 / 覆盖核算 / 说明）。
     - **工程量列永久留空**，因为没有图纸。
  3. **章节归类**：编码前 2 位是专业、3–4 位是分部，`gb_chapters_2013.yaml` 做章名兜底，供对账、指标、投控把行归到章。
  4. **概算映射**：概算 21 章里有 19 章映射到 GB50854 的 4 位章前缀，去重后 16 个。构筑物（第 18 章）和附属工程（第 19 章）没有对应章，留 NULL。安装清单 74 条映射为 0，因为它属 GB50856，该码表**未引入**，这是一个缺口（`docs/报告-建筑章GB50854映射覆盖率.md`）。
- 另有离线 demo（`cad_quantity_demo`、两个离线 Mac App）做 DXF 到清单的算量，**不在本仓**，在 owner 本机 `Desktop/天工算量层AI/`。

---

## B. 已记录的缺陷、痛点、冗余、红线、"踩过的坑"

### B.1 规模量级（说明问题的"形状"）
- 2026-09-29 生产质检：缺陷索引 283 条，13 个工作流合并同根因后得 163 个问题（P0 65 / P1 71 / P2 27），估算 228.5 人日。
- 2026-10-01 实跑全量测试（8 个功能加知识库问答，479 条用例）：缺陷 142 条，拆成 152 个分片，估算约 323 人日（`2026-10-01-实跑全量测试整改-design.md`）。
- 实测总评：8 个功能里只有项目驾驶舱可直接用，其余 7 个和知识库问答都要改代码。
  - 字段提取 7 行里 1 行可用，一次点击 330 万 token。
  - AI 初稿 30 章 0 章可直接用。
  - 齐套率 45.5%，真实值 18.2%。
  - 指标总造价只有招标控制价的 58.2%。
  - 清单约 23% 有问题。
  - 正式报告 55 个占位符 0 个被替换。
  - AI 没有编造金额，错在口径、归类、标签，以及"没有依据的话不带标记"。
- 实测只覆盖"清单与控制价编制"这一类业务的 1 个项目，结算审核和全过程投控的资料形态没进过实测（总纲第 9 条）。

### B.2 安全红线（B-01 … B-08，来自 `docs/开发清单-条目化-v1.md` + `docs/安全待办-B线红线-相对main-20260827.md`）

| 编号 | 主题 | 状态（文档记载） |
|---|---|---|
| B-01 | JWT 密钥外部化 | 已完成。未配置则拒绝启动 |
| B-02 | 每租户独立 JWT 密钥 | 待修。静态工具类 `JwtUtils` 全租户共用一把密钥。PR #65 是派生制，一损俱损 |
| B-03 | 删除自动登录后门（`CallBackAutoLoginInterceptor`） | 半做完。硬编码已改读环境变量 `VIKA_CALLBACK_TOKEN`，拦截器仍在注册 |
| B-04 | 收紧 `/nas/oo/**` 等白名单 | 待修。自带 todo fixme；`/nas/**/noNeedSession/**` 是命名约定免登录，最危险 |
| B-05 | 回调租户软校验越权 | 流 1（审阅回调）已用租户绑定服务令牌修复；流 2（OnlyOffice 保存回调 `IGNORE_VALUE`）撞冻结，待裁决 |
| B-06 | 关闭 Druid 控制台 / 改强口令 | 只在开发清单出现；已改为环境变量必填，拒绝空口令 |
| B-07 | 裸文件读路径穿越 | 已修（`fa71a22`）。归一化加 `toRealPath`，越界一律 404 |
| B-08 | 全量凭据轮换 | 待执行。31 个变量加仓内 5 处明文存量，旧值一律视为已泄露，必须作废而不是删文件 |

**同族与相关项**：
- 交接文档 §4 的 R1–R4：
  - JWT 后门（R1）；`/nas/oo` 白名单（R2）；回调租户软校验（R3）；硬编码 JWT 密钥（R4）。
  - 以及：裸磁盘读、前端 `webSecurity:false + nodeIntegration:true`、自动更新走明文 HTTP、Druid `admin/admin`。
- WS01：
  - 用户接口泄露密码哈希和 SFTP 口令。
  - 任意路径读。
  - 文件字节出口缺成员权限校验。
  - 权限写接口可自升项目管理员。
  - 角色与账号写接口缺校验。
  - `/ragapi` 暴露全部引擎端点。
  - 注册信息和报表令牌外发到原厂域名。
  - 初始口令为手机号后 6 位且登录失败锁定被注释。
  - 无安全响应头。
- `/ragapi` 旁路：Nginx 注入 `X-Service-Token` 直连引擎，2026-09-13 之前公网无需登录即可读任意租户文件全文。现已加 `auth_request`，但**不解决跨租户**（`README.md`、issue #445/#446，未关闭只降级）。
- WS12-P13：AI 初稿用 `v-html` 渲染未消毒，文件里的提示注入能在同租户其他成员的浏览器里执行脚本。
- WS05-P04：文档里夹一句指令就能让回答静默改写审定金额。

### B.3 缺陷聚类，并标注"设计层"还是"偶发层"

下面把所有记录的缺陷聚成 14 个主题。"设计层"指换成 agent harness 的组织方式后，这类问题会因结构改变而消失或大幅缩小；"偶发层"指换载体后问题不会自动消失，或本来就是旧平台遗留。

| # | 主题 | 代表证据 | 层级 |
|---|---|---|---|
| 1 | **空结果和不足结果被当成功**（铁律 8） | WS06-P1；QTY-05（200 加空清单，引擎、Java、前端三层都当成功）；WS12-P06（信息不足也显示绿色"已完成"）；WS13-P13（假齐套，偏差全部朝虚高方向）；WS05-P02（读不了的文件被当成"读过"或"搜过没有"） | **设计层**。需要统一的结果契约和证据对账；harness 里每个 tool 返回带状态、覆盖率、原因的类型化结果 |
| 2 | **LLM 触碰金额、产出不可溯源** | 铁律 2、3；WS07 K1–K6；WS12-P01；WS05-P03；WS10-P10（引文护栏不核数值） | **设计层**。方向一致：LLM 只路由和分类，数字由确定性工具产出，证据位置只能由代码回填，LLM 不能自己写出处 |
| 3 | **同一件事多处各实现一份** | 设计层重复 K25–K28（docx / xlsx / 旁车解析、数字回链、截止与取消、汇总表解析各有多份）；字段主数据 4 套（`_踩点` 与 8-27 spec 说字段库是第 5 套）；两套检索系统（向量 RAG 与 filetree）；报告模板两套概念（引擎 24 套 AI 模板 vs 模板库 docx）；各领域各自写轮询 | **设计层**。这是 owner 说"大量冗余"最直接的证据 |
| 4 | **文本抽取、OCR 降级链静默失败** | WS04 全组；"空串加 text_layer"的组合；9 本扫描定额书无文本；754 份旁车全失败；docx 修订删除文本进正文；xlsx 空格塌缩 | 主要是**偶发层**（解析器质量），但"每个功能各读各的原件、各自缓存"是**设计层** |
| 5 | **同步长调用、超时、单进程引擎** | WS06-P2；499/504/502；`zt-engine` 被 2g 上限 OOM-kill；前端 60s 早于 Java 120s；整项目标注一次同步调用 | **设计层**（任务运行器、deadline 预算、取消），对应 harness 的 jobs |
| 6 | **取材混乱** | WS06-P3：INDEX.md、`.ocr.txt` 旁车、doc/docx 双份、AI 生成物、成稿报告都被当"资料"送给引擎；WS23-a、WS13-P03 同源 | **设计层**。制品需要类型（原件 / 派生 / 生成物），取材由统一选择器负责 |
| 7 | **标注、阶段推断、齐套的领域模型缺陷** | 阶段推断根因（8-30 spec）：42 条 `archive_keyword` 规则里没有一条带 `cost_stage`，代码里 archive 出口把 `cost_stage` 写死为 `None`，"投票池结构性缺席"；清单单阶段裁剪；三档要求级别压成两档；结算审核项目显示 100% 未发现缺件；全库 126 个项目咨询类型都是默认值 | **设计层**（领域模型），但规则表本身是需要保留的资产 |
| 8 | **报告生成** | AI 初稿 0 章可用；模板话当事实；章节越界；分项对比表被写成散文；重名检查不带租户；Web 端无法生成（依赖 Electron 本机替换 docx）；模板库 `template_entity` 0 行 | 一半**设计层**（章节契约、事实只来自已抽字段），一半偶发（Web 化遗留） |
| 9 | **概算、清单产出质量** | 概算单样本、按位置套用、样本包干额被放大（土地费虚高 70%–89%）、多栋被截成 3 栋；清单约 23% 有问题、"范围排除"22 条全错、做法表被逐行拼成一句话 | 偏**设计层**（要多样本基准、口径提示），金额在样本到手前不可交付（D-R116，等外部） |
| 10 | **多租户靠手写纪律** | 每条 SQL 手写 `sys_company_code`，已被证实失守（3 个 mapper 无租户过滤）；`getById`/`updateById` 禁用；`tenant-isolation-probe.sh`；`docs/设计/租户拦截器可行性-20260914.md` | **设计层**。这是选"一租户一库、一容器"的原因 |
| 11 | **旧平台和前端遗留** | Electron 与 Web 双端、ipc 在 Web 下挂起（WS03）；原厂域名硬编码和令牌外发（`ddns.chemball.com`、`sjs.tgzt.cn` 等 7 组）；`views/home/` 是错位共享库（13 个文件依赖）；`vuedraggable@2` 装在 Vue3，keep-alive 冻结和 5 处拖拽疑似一直是坏的 | **偶发层**（换前端或重建即可摆脱），但迁移时是体量大的隐形成本 |
| 12 | **数据和部署面** | 同步 `partition` 少算批数，静默丢数据（WS02-P1）；回收站只靠 MQ 消费者写，生产没有 broker；`sql/` 落后代码，约 25 张表无 DDL；生产 profile 仓内复现不出；jar 烤在镜像里，`restart` 不换镜像，生产曾跑三天旧代码；`mysql <` 不带字符集产生双重编码；无备份 | **偶发层**为主 |
| 13 | **工程流程自我繁殖** | 门禁盯门禁：2026-09-14 "闸族分诊"一次处理 11 条 issue，结论"补洞 5 · 删掉 1 · 降级 4 · 核实后已修 1"，文中直说"连续九轮以上自我繁殖"；GitHub Actions 额度耗尽不会恢复，一切改为本机 `ci-local.sh` / `ci-merged.sh`；私有仓无法配分支保护；`.kb/changelog.d` 有 388 个片段，按文件名粗聚类约 23%（88 个）属于门禁、棘轮、负控、夹具这一类；多窗口并行造成 K1–K33 共 33 处共享文件冲突 | **流程层**。不属于产品功能，但会随"换架构"被整体淘汰或需重定 |
| 14 | **外部阻塞和签核债** | 13 项待客户确认（ICP 备案、云 LLM 书面确认、等保、资料存量、类目清单、真实样本核对）；字段定义待造价员签核（D-R15）；费率规则"仓主默认放行，非造价员签署"（D-2026-09-10-04）；分类口径变更附录 A、B 待送签 | 与架构无关，迁移后同样存在 |

### B.4 "踩过的坑"清单（原文出处各处，已汇总）
- **环境与构建**
  - JDK 8 构建、JRE 17 运行不一致会崩（`ArrayStoreException`）。
  - `-P product` 实际匹配不到 profile，静默退回 dev。
  - `mvn package` 必须带 `-P customer` 和 `clean`，否则静默打出 dev 包或漏掉新增模块。
  - Maven 编译器 2.3.2 让孤儿 `.class` 继续被执行；编译期常量会被 javac 内联进引用方，变异测试时必须 `clean`。
  - `mysql <` 导入必须 `--default-character-set=utf8mb4`，否则出现 `C3A5` 开头的双重编码脏数据。
  - `config` 表系统行要求 `sys_company_code='0'` 且 `creator_id='0'`。
  - Flowable 空表要先 DROP 让它自建。
  - 缺表 `ai_reports`，`/nas/aiReports` 必报 500。
- **运行**
  - 引擎重启不带 `SERVICE_TOKEN` 会随机生成，Java 侧 401。
  - `rel_path` 必须带 `project/{projectId}/` 前缀。
  - 容器 `restart` 不换镜像，换代码必须 `up -d --force-recreate`，判据是镜像 ID 前后对比。
  - `docker compose` 解析 `.env` 与 shell `source` 不同，值里有 `$`、空格、命令替换会静默出错。
  - 已定义的空环境变量会覆盖 profile 预置值（`TENANT_PLATFORM_CODE=` 的例子）。
  - 租户 2 无概算种子时会返回"200 + 覆盖率 0 + 空结果"且不报错。
- **工具链**
  - 本仓路径含中文，`git` 默认输出转义，解析 diff 的闸要加 `-c core.quotepath=false`，否则永远绿。
  - zsh 内建 `echo` 会解释 `\xNN`。
  - macOS 的 `grep`/`diff` 把含中文文本判成二进制。
  - `git diff A..B` 的两点 diff 陷阱，改用 `git merge-tree --write-tree`。
  - `gh` 传正文别用双引号，反引号会被执行。
  - `checkout -b X origin/main` 会把 upstream 设成 main，git 报错时建议 `git push origin HEAD:main`，照抄就直推主干（2026-08-29 出过事故）。
  - 本地分支名当 `--base` 会拿到过期合并树，报"全过"。
- **测试方法**
  - 头号缺陷类："夹具够不到失败分支"。用例名称覆盖整个概念，夹具只覆盖一个分支；有 LLM 兜底的测试会被 LLM 猜对掩盖规则层退化。
  - 变异验收必须是"语义回退"，语法错误不算。
  - 分支绿而合并树红（#338、#330 都发生过）。
  - 有些"成功"是空转：引擎 `duplicate` 规则的判重边界曾被反向订正。
- **前端**
  - Modal 的 zoom 动画卡在 `scale(0.2)` 中间帧，看起来像"紧凑小浮层"。
  - 附件按钮被 `filter: invert(100%)` 涂白、压在白底上消失。
  - 删 `v-if` 留下裸 `<template>`，整区不可见且无编译警告。
- **协作**
  - 同一分支不能被两个 worktree 占用，别建 `-fix2` 绕行。
  - 派工要按缺陷去重而不是按归属去重（曾因此两条轨道各实现一遍 `/engine/estimate/suggest`）。
  - 报缺陷不等于认领缺陷。

---

## C. 关于 skill 化与 DeepSeek Harness 的既有思考

### C.1 `调研-算量层skill化评估.md` 的结论
- **调研对象**：`building-cost-estimator`。它是一个很小的"施工说明文字 → 国标工程量清单"的确定性查表加 AI 分类工具：
  - 8 个受控文件；核心是 `gb50854_registry.py`（605 行，490 条码）、`SKILL.md`（367 行操作手册）、`GB50854-2013.md`。
  - 输入是 xls / xlsx / docx 的设计说明，输出是单个 xlsx，工程量列留空。
  - 本体不提供运行时，要靠有"读文件夹、跑 Python、写文件"能力的 agent（如 Claude Code）来执行。
  - 唯一的测试是 `check_consistency.py`，只扫描文档里的编码是否存在于 registry。
- **发现**：GB50854 码表已经被复制进至少 5 处独立代码库，包括两个离线 App、`cad_quantity_demo`、RAG 脚手架的 DWG 抽取管线和文件树测试，是事实上的公共资产；而完整的"文字 → 分类 → 查表 → 填参 → 出 xlsx"五步流程只存在这一个仓库里。
- **判断**：
  - 属于"混合类，重心在重执行"。只有"做法描述映射到 GB 编码"这一步需要 LLM 判断。
  - 前后两端都是确定性代码：读三种格式、查 registry、用 openpyxl 渲染精确格式。
  - 现有 63-skill 网关（`zhitong-gateway`）是 63 个 `"runtime": "direct"` 的纯文本包装器：单文件上传、SSE 文本流出，**没有代码执行沙箱，没有文件输出通道**，设计上就不承担真计算。
- **决定做什么**：
  - 做，但不要简单塞进 63-skill 列表，而是**长成 engine-service 里的一个"表格/文件处理引擎"模块**。
  - 分层：UI 入口（项目文件页的专用卡片，选中设计说明文件后触发）→ 编排（后端模块）→ 确定性部分（490 码查表和 xlsx 渲染，留在代码层，不经 LLM）→ LLM 部分（一次结构化 JSON 调用，只做分类与参数抽取）。
  - SKILL.md 收窄为"编码分类加参数填充"的提示词模板。
  - 估算 10–18 人天。
  - 前置：多文件上传通道、文件输出与下载通道、一批带人工核对答案的样例（20–30 个）以验证准确率。
- **明确不做**：
  - 挂首页（首页不绑项目文件夹，且网关只收 1 个文件）。
  - 让 LLM 现场"记忆" 490 个编码。
  - 在网关里新增一个形态完全不同的"文件任务"分支（会破坏"改 manifest 加一行"的设计初衷）。
- **后续落地**：2026-08-23 的《对话与知识库集成-design》D 节确认"算量层是 490 条码表，不是 AI"，作为基础数据让对账、指标、投控变准，另做"按设计说明生成清单框架"能力；之后经 WS11 重写成 10 步流水线（见 A.4）。

### C.2 其他三份调研的相关结论
- **数据库模式（filetree）**：
  - 采用。核心是"确定性定案行"范式——工具产出结论句而不是只递证据，让模型的活从归纳降为转述。
  - D26 定律："一个修复的期望通过率 ≈ 它把多少判断从模型搬进了工具"。
  - 保留：7 个只读工具、定案行、八道防线、三本预算账加四道硬拦。
  - 砍掉：实体注册表（跨项目消歧）、双胞胎项目图（60GB 历史脏数据特产）、预建 INDEX.md（改为现场遍历）。
  - 已落地为引擎的 `filetree` 与 `/engine/filetree/ask`、`/engine/chat/complete`。
  - **与 DeepSeek 直接相关的风险**：
    - 所有验收数字（20/20、19/20）都是在本机 qwen3.6-35b 上测的，换 DeepSeek 必须重跑。
    - `reasoning_effort:"none"` 是 qwen 实测写法，DeepSeek 上大概率静默失效（D9）。
    - 日志显示模型为 `deepseek-v4-flash`。
    - 深度思考开关在整改中被隐藏（D29）。
- **AI 对话框**：不整体移植（脚手架用 Element Plus，本产品用 ant-design-vue 4，不能混用）；做契约级补齐：plan / step / attribution / confidence 四类 SSE 事件、终态纪律（streaming → done|error|stopped，中断不等于 done）、范围选择器、附件。SSE 传输层沿用 `@microsoft/fetch-event-source`。
- **知识库**：放弃向量 RAG（实测 hybrid recall@10 约 0.245）；新建 `knowledge_file`（仿 `personal_space_file`）加树状落盘；历史遗留的 `knowledge_entity` 链路从未真正传过文件内容，检索从未通过。
- **整体被拒绝或搁置的方案**：向量库隔离治理（暂缓）、Univer 嵌入、OnlyOffice 在线编辑（一期不做，已购授权，验收现场会被问到）、SQLite 自动建表、引擎直连 MySQL、"产品结构重构"（`98_产品重构设计/` 已搁置，用户口径是只修功能不改 8 个入口）、可变长单体概算（固定 6 槽位）、部署 RocketMQ。

### C.3 与 Harness 迁移直接相关的既有约束
- 目前实际架构是"Java 业务后端是 MySQL 唯一写者，Python 引擎无状态，用 service token 调用，任务用 `engine_task` 做 saga 账本"。
- 旧文档里所谓 skill，仅指 63 个办公 skill（`engine-service/app/engine/data/skills.json`，写作 / 表格 / 演示 / 阅读 / 沟通 / 思考 / 语音 / 日程 8 组，源自仓外 `zhitong-gateway/manifest.json`）。它们在整改中被判为"空壳且会编造"：f07 术语库不存在却冒称依据，函件会编造期限和法律后果条款（WS05-P14，D30 决定 f07 置灰）。
- 引擎是 FastAPI 的 10 个 router / 约 16 个端点：`health`、`tag`、`extract`、`audit`、`report`、`report_templates`、`stubs`（reconcile / indicator / tk）、`quantity`、`estimate`、`reportform`、`chat`、`chat_writing`、`filetree`、`costsheet_probe`。

---

## D. 报告模板

模板分三层。

### D.1 引擎内置：24 套 AI 初稿模板 / 172 章
- 文件：`engine-service/app/engine/data/report_templates.yaml`（2303 行）。引擎只读，`@lru_cache`，改完要重启引擎。
- **每章字段**：
  - `code`、`title`、`seq`。
  - `rag_query`：选材检索词。
  - `gen_prompt`：四段式，【必备要素】【取材】【格式】【缺失处理】。
  - `excludes`：本章不写的内容。
  - `facts_allowed`：允许使用的事实。
  - `claims`：程序性陈述，让用户在"确认事项"一步勾选，不进 `gen_prompt`。
  - 另有 `attachment_hints`、`note_user`、`enabled`。
- **`section code` 是单章重试的定位键，改了会导致旧初稿重试 422**，月报以外不要改。
- Java 白名单只下发 `template_code`、`name`、`note` 以及章的 `code`、`title`、`seq`、`claims`，`rag_query` 和 `gen_prompt` 不到浏览器（#836）。

| 模板编码 | 名称 | 章数与结构 |
|---|---|---|
| `tzkz_monthly_v0` | 投资控制月报（全过程造价咨询月报） | 7：项目工作概况 / 项目进展情况 / 项目投资控制总体情况 / 本期主要咨询工作内容 / 重大事件 / 存在问题及建议 / 下期工作计划 |
| `guzhi_chengguo`、`gaisuan_chengguo`、`yusuan_chengguo`、`jiesuan_chengguo` | 估算 / 概算 / 预算(工程量清单) / 结算 咨询成果报告 | 各 8 章：封面、扉页、目录、编制报告、基本情况、编制情况、其他需要说明的问题、附表 |
| `guzhi_shuoming`、`gaisuan_shuoming`、`guzhi_shenhe` | 估算 / 概算编制说明、估算审核说明 | 各 3 章：依据 / 原则及办法 / 其他 |
| `jiesuan_shuoming` | 结算编制说明 | 4 章：工程概况 / 编制依据 / 原则及办法 / 特殊情况说明 |
| `kzj_bz_baogao` 及市政 `_shizheng`、园林 `_yuanlin` 变体 | 招标控制价编制报告 | 房建 10 章（含导语、落款，八章正文）；市政 9 章；园林 8 章 |
| `gaisuan_shenhe` 及 `_shizheng` | 概算审核报告 | 8 章：导语、项目概况、审核依据、审核情况说明、审核结果、与送审概算对比分析、附件、落款 |
| `yusuan_shenhe` 及 `_shizheng`、`_yuanlin` | 预算审核报告 | 房建 9 / 市政 7 / 园林 9 章 |
| `jiesuan_shenhe_bg` 及 `_shizheng`、`_yuanlin` | 结算审核报告 | 各 9 章：导语、项目概况、（工程主要）特征、审核依据、相关事项审核说明、审核结果、造价对比分析、审核附件、落款 |
| `zaojia_shendingdan` | 工程造价审定单 | 1 章，单章表单：表头、送审 / 审定 / 核减 / 核增明细、合计大写、四方签章 |
| `qd_bz_shuoming` 及 `_shizheng`、`_yuanlin` | 工程量清单编制说明 | 房建 10 章（概况、招标范围、编制依据、总体要求、规费费率税金、其他项目费、通用共性计量计价、建筑专项、安装专项、总体计价约定）；市政、园林各 7 章 |

### D.2 模板库里的 docx：16 份扩充包 + 3 份起步包（供"生成正式报告"）
- 位置：`docs/报告模板扩充包/`（16 份）、`docs/报告模板起步包/`（3 份）。
- 渲染：服务端 `DocxPlaceholderRenderer` 用项目"汇总信息"替换 `{名称}`。生成的报告文件名等于模板名。
- 写法约束：
  - 占位符只能用 `summary-template-seed.sql` 里的 106 个种子名之一。
  - 不能用 `{#}` `{/}` `{^}` `{@}` 循环或条件标签。
  - 只放正文、表格（含嵌套）、页眉页脚；文本框、内容控件、脚注里的占位符服务端不替换也不报。
  - 不预置任何金额（铁律 2）；背景金额只用 `{合同总价}`、`{招标控制价}`、`{概算总投资}`。
  - 不用 `{概算建安造价}`（种子里两行同名，取值不定）。
  - 程序性事项写成"【待补：……（只写实际执行过的）】"。
- 汇总信息为空时，渲染结果是 `###名称###`，界面提示"N 个占位符替换失败"，这是数据没填，不是模板坏了。
- 这 16 份**不在种子里**的 7 份通用模板，上传前要在模板库手建分类；9 份有对应的分类种子 id 后缀。

| # | 文件 | 分类 | 占位符数 | 章节结构 | 金额格数 | 【待补】数 |
|---|---|---|---|---|---|---|
| 1 | 竣工结算审核报告（房建） | 结算审核模版 10008 | 55 | 一项目概况 / 二工程主要特征 / 三审核依据 / 四相关事项审核说明 / 五审核结果 / 六造价对比分析 / 七审核附件 | 12 | 14 |
| 2 | 工程造价审定单 | 同上 | 4 | 无标题，表单 | 16 | 0 |
| 3 | 竣工结算审核报告封面扉页 | 同上 | 2 | 封面与扉页 | 0 | 5 |
| 4 | 竣工结算审核报告（市政） | 市政工程 10002 | 30 | 一项目概况 / 二工程特征 / 三合同主要约定 / 四审核依据 / 五相关事项审核说明 / 六审核结果 / 七造价对比分析 / 八附件 | 12 | 18 |
| 5 | 竣工结算审核报告（园林） | 仿古园林工程 10005 | 30 | 同市政版结构 | 12 | 18 |
| 6 | 招标控制价编制报告 | 招标控制价模版 10007 | 32 | 一工程概况 / 二编制依据 / 三编制原则及办法 / 四其他项目费 / 五有关事项说明 / 六编制结果 | 6 | 13 |
| 7 | 工程量清单及招标控制价编制说明 | 同上 | 31 | 一至五（同上去掉"编制结果"） | 0 | 5 |
| 8 | 预算（招标控制价）审核报告 | 同上 | 21 | 一工程概况 / 二审核范围 / 三审核依据 / 四取费标准及材料价格说明 / 五相关事项审核说明 / 六审核结果 / 七审核对比分析 | 12 | 15 |
| 9 | 设计概算审核报告 | 通用（新建） | 21 | 一项目概况 / 二审核依据 / 三审核情况说明 / 四审核结果 / 五审核结果与送审概算对比分析 / 六附件 | 15 | 13 |
| 10 | 全过程造价咨询月报 | 通用 | 18 | 七章（同 `tzkz_monthly_v0`） | 19 | 20 |
| 11 | 咨询成果报告书（估算） | 通用 | 13 | 目录 / 估算编制报告 / 基本情况 / 工程估算编制情况 / 其他需要说明的问题 / 附表 | 5 | 13 |
| 12 | 咨询成果报告书（概算） | 通用 | 13 | 同上，改"概算" | 5 | 13 |
| 13 | 咨询成果报告书（结算编制） | 通用 | 20 | 同上，改"结算编制" | 6 | 12 |
| 14 | 竣工财务决算审核报告 | 通用 | 25 | 一项目概况 / 二概算批复及执行情况 / 三审核依据 / 四审核结果 / 五资金来源及到位情况 / 六交付使用资产情况 / 七审核发现的问题及建议 / 八附件 | 25 | 15 |
| 15 | 造价咨询意见书 | 通用 | 9 | 一基本情况 / 二咨询依据 / 三分析过程 / 四咨询意见 / 五需要说明的事项 | 3 | 7 |
| 16 | 造价咨询实施方案 | 通用 | 11 | 一项目概况 / 二咨询服务范围与周期 / 三项目实施计划 / 四质量保证措施 / 五重点难点及应对措施 / 六人员配置 / 七成果文件清单 | 0 | 7 |

- **16 份合计用到 77 个种子占位符**：
  工程名称、委托单位、建设单位、施工单位、监理单位、设计单位、代建单位、招标代理单位、全过程跟审单位、审批单位、批复文号、建设地点、工程类别、项目类型、项目等级、服务范围、项目周期、工程承包范围、工程非承包范围、工程奖项的约定、合同价格形式、合同总价、合同签定日期、合同文件的优先顺序、招标控制价、概算总投资、总承包服务费、计划/实际 开工竣工日期与总日历天数、验收工程质量、质量要求、建筑总面积、地上/地下 建筑面积与层数、建筑高度、建筑结构类型、抗震设防烈度、设计使用年限、人防等级、基坑围护、桩基、基础、结构、砌体、屋面、楼地面、外墙面、内墙面、天棚、门窗、建筑装饰工程、安装工程、给排水、电气、暖通、消防、智能化、定额及取费依据、政策文件依据、信息价依据、相关资料依据、工程计量与计价依据、人工价格调整方式、商品混凝土水泥钢材价格调整方式、电线电缆母线价格调整方式、变更估价的约定、补充条款、共性说明、项目实施计划、项目实施质量、项目实施过程中重点难点的具体实施措施。
- 种子里有 106 个名称，未被用到的 29 个，包括：结算价一组、各"（含税）"分项、概算建安造价、概算预备费、地质勘察单位、场内交通、裙房层数等。
- `templates_manifest.json` 由 `build_report_templates.py` 从 docx 重算写出（含 sha256），不手工登记。校验器 `check_templates.py`、`check_forbidden_words.py`、`render_sim.py`、`mutate_checkers.py` 三个扫到 0 份退出 2。
- **起步包（3 份）**：结算审核报告、工程造价审定单、报告封面扉页的"起步模板"，等客户正式模板到位后替换。
- **边界**：章节骨架按造价咨询惯例和 GB/T 51095 口径自审，**不能替代持证造价工程师签核**；安装工程和轨道交通暂无专用模板（安装先用房建版）；流程表格下两个子分类属地方财政口径，需客户提供原件。

### D.3 其他与报告相关的数据与能力
- 项目概要模板种子 `后端/sql/tenant-init/summary-template-seed.sql`：12 个工程分类 × (25 个分类节点 + 107 个字段)，共 12 模板 / 300 分类 / 1284 条（SHAPE 行机器可读）。生成器 `scripts/generate_summary_template_seed.py`，数据源是 `tenant-seed-template.sql` 里的 `project_core_info_dict`，**名称"工程名称"必须逐字保留**，否则概要回填链路静默失效。
- Java 侧：`ProjectSummaryController`、`CostAiReportController`；报告状态机 `report_instance`（`finalized_at` 为人工审校唯一守卫）、`report_section_state`、`report_audit_log`。
- 概算表：`engine-service/app/engine/data/estimate_templates/gsyz_v1_template.xlsx`（9 sheet、515 公式、211 输入位）。
- 交付文档说明了：生成的 xlsx 是活公式表，但一期编辑形态是"下载后本地 Excel / WPS"，OnlyOffice 在线编辑本期不做。

---

## E. 与迁移相关的运维事实

### E.1 部署拓扑（`deploy/README.md`、`deploy/docker-compose.prod.yml`、`AGENT-A-云基础设施管理员.md`）
- 火山引擎，华东 2（上海），VPC `vpc-zhitong-prod`（172.16.0.0/16，网段是有意避开客户内网 192.168.x）。
- 单台 ECS：`zhitong-prod-web`，4 核 16G，Ubuntu 22.04，公网地址见 README，生产域名 `ztsgai.com`。
- 五服务单机 Docker Compose，项目名 `zhitong`，网络 `zt`：

| 服务 | 容器 | 镜像 | 内存 limit | 备注 |
|---|---|---|---|---|
| mysql | `zt-mysql` | `mysql:8.0` | 2g | 数据目录 `/opt/zhitong/data/mysql` |
| app | `zt-app` | `tg-app:prod` | 5g | Java，堆 `-Xms1024m -Xmx3584m`；jar 烤在镜像里，`restart` 不换镜像；落盘根 `/work` |
| engine | `zt-engine` | `tg-engine:prod` | 2g | `FILE_ROOT=/data`（NAS 只读挂载）；字段提取在有上限的子进程里解析 |
| ocr | `zt-ocr` | `tg-ocr:prod` | 3g | RapidOCR 跑 PP-OCR 系模型（服务目录名叫 `paddleocr-service`，实际是 onnxruntime） |
| nginx | `zt-nginx` | `nginx:1.25-alpine` | 256m | 唯一对外 80/443；前端 dist 在 `/opt/zhitong/nginx/html` |

- **容量上限**由 `deploy/host-capacity.conf` 声明（15360 MiB 可用，预留 1536），上限约 13.5g；CI 闸对账 compose 的 limit 之和。
- **一租户一容器**：同一镜像起 N 个 `app-t<租户码>`，各自库和 `JWT_SECRET`；mysql / engine / ocr / nginx 共享。**4C16G 只塞得下 2 个 app 容器**，第二个租户上线前必须降 app 到 3g 或升主机。租户 1 是平台节点，`1` 和 `2` 是保留码，新租户从 3 起。
- **注意**：文档与代码的现状是——生产共享库实查只有租户 1（2026-09-14）；"租户 2"是开发库状态。
- 数据库：MySQL 8，库 `tian_gong_intelligence`，**无 Flyway / Liquibase**。DDL 来源：
  - 客户 2026-08-21 提供的 155 表 dump。
  - 造价 AI 新增 23 张表。
  - 迁移新机制：`后端/sql/migrations.d/` 登记，存量库由用户按 R6 手工执行。
- 文件存储：宿主路径 `/opt/zhitong/data/nas-data`，挂入 app（读写，容器内 `/work`）、engine 与 ocr（只读 `/data`）。文档称之为 NAS / `enas`，备份文档说 NAS 整块挂进三个业务容器；**docs 里没有明说这条路径是不是真的是独立云盘**，PRD 开发清单写的 A-05 "采购 NAS 2TB 起"，agent A 文档写"待挂 NAS"。迁移前需向运维确认。
- 备份：`/opt/zhitong/backup` 在 `/dev/vda2` 上，与 MySQL 数据目录同盘。

### E.2 TOS 对象存储的现状用途——**仅用于 MySQL 逻辑备份的异地副本，不存任何业务文件**
- 桶：`zhitong-prod-backup-20260929`，cn-shanghai，私有 ACL，版本控制开，生命周期 30 天。
- 子账号 `tos-backup-writer`：只有读、写、列，**实测删除返回 403**，所以本机被攻破也删不掉异地那份。
- 对象键：`mysql/<库>/<库>-<日期>.sql.gz`（前缀可由 `TOS_PREFIX` 改）。
- 流程：
  1. systemd 定时器 `zt-mysql-backup.timer` 在每天 02:30 拉起 `deploy/backup-nightly.sh`（`Persistent=true`，关机错过会补跑）。
  2. 它先等 `zt-mysql` 就绪，再调 `mysql-backup.sh`：主库加每个租户库各 dump 一份（`--source-data=2`），压完立刻校验（`gzip -t`、头有 `CREATE DATABASE`、尾有 `Dump completed`），校验通过才改名为正式文件。
  3. dump 成功后调 `backup-offsite.sh`，用 `deploy/tos-backup-upload.py`（Python 3.10 + 火山 TOS SDK 2.9.3）上传，并用 `head_object` 读回 `content_length` 与本地字节数核对。
  4. 每次写一行 `/opt/zhitong/data/backup-state/last-status`，失败追加 `backup-alert.log`。可选告警钩子 `TG_BACKUP_ALERT_CMD`（D68 决定不接即时告警）。
  5. 退出码：0 全好；1 有库备份失败；2 锁被占或等不到 mysql；3 孤儿备份超阈值；5 dump 成功但异地失败。
- 凭据文件：`/opt/zhitong/app/deploy/.tos-backup.env`（root:root 600），**仅五个变量名**：`TOS_BUCKET`、`TOS_REGION`、`TOS_ENDPOINT`、`TOS_ACCESS_KEY_ID`、`TOS_SECRET_ACCESS_KEY`。上传前脚本校验属主与权限，不 source、不回显，端点只允许 https，不放进 enas（因为 dump 含口令哈希）。
- 云盘快照：每天 03:30，保留 7 份（控制台操作，D67），防盘级故障；与 TOS 两层互不替代。
- 恢复演练：在断网的一次性容器里用最新 dump 恢复到新库；`mysql-backup.sh` 的备份目录之外，**没有任何文件级（NAS 里的项目文件）备份到 TOS**。这是迁移到"TOS 存文档与报告"必须补上的缺口。
- 一个重要的历史事实：2026-09-29 实查时，生产**没有任何定时备份**，只有一份早于 122 个项目迁移的旧 dump，恢复线索（binlog 30 天保留）也在过期；`./deploy.sh check` 照样打印"检查通过"（WS14-ws14-db-backup）。

### E.3 租户开通流程
- 目前有两条路，文档在 `deploy/README.md` 的"开通一个租户"一节与 `一租户一容器编排-design.md`：
  1. **旧路**：Java 自带的 `POST /nas/newSys/agree`（仅 `SYS_ADMIN`）在同库用 `max(sys_company_code)+1` 开新租户，仅平台租户的 sys_admin 可用（`tenant.platform-code`，生产由 `TENANT_PLATFORM_CODE` 注入）。该端点前端零调用。
  2. **新路（一租户一库）**：
     1. 复制 `deploy/tenants/3.env.example` 为 `tenants/3.env` 并填库名、端口、两把私钥、管理员口令哈希；用 `deploy/gen-secrets.sh` 取随机值，用 `init-tenant-db.sh --hash-only` 取管理员口令哈希。
     2. 执行 `./tenant-add.sh 3`，一条命令走完设计 §④ 的 0–10 步：校验租户码和台账撞码 → 预检 → 一次性 mysql 容器里跑 `后端/sql/tenant-init/init-tenant-db.sh`（建库、导 7 份 DDL、DROP Flowable 空表、种子加管理员、造价 AI 应用卡、17 项验证，幂等）→ `gen-compose.sh` 生成 `docker-compose.tenants.yml` → `gen-nginx-tenant.sh` 渲染站点配置 → 打印防火墙命令 → `up -d app app-t3 nginx` → 等 healthy → 取证。
     3. 登录取证、注册表 `admin/upsert` 等需人工做；脚本不碰明文口令。
  - 备案前按端口区分租户（`listen 80<c>`），备案后按域名。
  - **下线顺序**：必须先把租户 conf 移出 `conf.d/` 并 reload nginx，再停容器，最后回收 `tenants/<码>.env`，顺序反了 nginx 整个起不来。
  - 租户注册服务：`tenant_registry` 与 `tenant_registry_alias` 两表，每个租户库里都建，只有注册节点（租户 1）上的是权威副本。取代原厂的 `ddns.chemball.com` 中心注册服务。
- **已知缺口**：`/work` 仍全租户共享一块 NAS，试用版容量闸对整棵 `/work` 算量、`knowledge/` 根无租户维度、分片临时目录按固定管理员 id 分桶，三处跨租户串扰；所有 app 容器用 root 连 MySQL（尚未给每库配受限账号）。

### E.4 凭据轮换（仅列变量名；`docs/运维/凭据轮换手册.md`）
- 手册把 31 个外部化变量全部视为已泄露，必须作废旧值；实际轮换尚未执行（issue #16 保持 OPEN，因为服务器采购曾阻塞）。
- **变量名清单**（来自 `.env.example` 与 `deploy/.env.prod.example`）：
  - 核心：`JWT_SECRET`、`OO_JWT_SECRET`、`DRUID_STAT_LOGIN_USERNAME`、`DRUID_STAT_LOGIN_PASSWORD`。
  - 库：`DATABASE_PASSWORD`、`DATABASE_USERNAME`、`DATABASE_NAME`、`TABLE_SCHEMA`。
  - MinIO：`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`。
  - 第三方：`BAIDU_SEAL_API_KEY`、`BAIDU_SEAL_SECRET_KEY`、`BAIDU_TEXT_API_KEY`、`BAIDU_TEXT_SECRET_KEY`、`KIMI_TOKEN`、`OCR_SPACE_API_KEY`、`VIKA_API_TOKEN`。
  - OMV：`OMV_USERNAME`、`OMV_PASSWORD`。
  - 企业微信：`WECOM_WEBHOOK_KEY`、`WECOM_WEBHOOK_KEY_MONITOR`、`WECOM_WEBHOOK_KEY_DEV`。
  - 服务间：`ENGINE_SERVICE_TOKEN`（引擎侧为 `SERVICE_TOKEN`，必须同值）、`OCR_SERVICE_TOKEN`、`CUSTOMER_USER_KEY`。
  - LLM：`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`（引擎默认从 `~/Desktop/天工智通/.llm.env` 读，环境变量可覆盖）。
  - 租户平台：`TENANT_PLATFORM_CODE`、`TENANT_REGISTRY_WRITE_ENABLED`、`SPRING_PROFILE`。
  - 部署脚本：`DEPLOY_DB_USER`、`DEPLOY_DB_PASSWORD`、`DEPLOY_DB_HOST`、`DEPLOY_DB_NAME`、`DEPLOY_DB_PORT`；代码生成器：`GENERATOR_DB_HOST`、`GENERATOR_DB_USER`、`GENERATOR_DB_PASSWORD`。
  - TOS：见 E.2 的五个键。
  - 引擎运行参数（非机密）：`FILE_ROOT`、`LLM_CACHE_*`、`EXTRACT_PARSE_*`、`EXTRACT_TOKEN_BUDGET`、`TAG_LLM_TOTAL_SEC` 等。
- **轮换顺序**：第 1 批热更类（企业微信、百度 / Kimi / ocr.space / Vika、DeepSeek、钉钉机器人、SMTP、OMV、MinIO）→ 第 2 批服务间令牌（引擎与 Java 两侧同窗口同值）→ 第 3 批停机窗口（`DATABASE_PASSWORD` 先 `ALTER USER` 再改环境变量再重启；`DRUID_STAT_LOGIN_PASSWORD`；`OO_JWT_SECRET` 与 documentserver 同窗口同值；`JWT_SECRET` 最后换，会踢出所有在线用户）。
- **爆炸半径提示**：若 PR #65（派生制）合入，换 `JWT_SECRET` 会同时使全部租户令牌失效。
- DeepSeek key 单独说明：曾经过聊天通道传输，视同泄露，测试完成后要到 platform.deepseek.com 删旧建新，再用旧 key 请求一次确认 401。
- 仓内另有 5 处明文存量（钉钉机器人 token 与加签密钥、企业微信 webhook key 硬编码、SMTP 密码种子、被注释掉的账号密码对、`前端/public/ssl/localhost+1.key` 私钥）。注意：凭据轮换手册 §5 订正了安全待办的一条说法——OnlyOffice JWT 真值从未进过本仓历史，历史里只有非凭据的 document key。
- CI 凭据扫描：gitleaks 闸（`ci-local.sh` 闸⑥）。

### E.5 其他运维事实
- 发布方式：本机构建 → rsync 到服务器仓库镜像 `/opt/zhitong/app/{deploy,后端/…,engine-service,ocr-service,…}` → `deploy.sh build` → `up -d --force-recreate`，判据是镜像 ID 前后对比；每次部署带 `main=<sha>` 巡检。
- 生产写操作一律写成运行手册，由用户执行或确认：`docs/运维/` 下有 `runbook-L1金标回放`、`runbook-OCR旁车补跑`、`runbook-WS02b-角色回填与封面改名`、`runbook-项目文件补同步-R2`、`任务清单-云服务器管理员-20260906`。
- OCR 旁车补跑（`.ocr.txt`）：知识库 9 本约 2184 页加 754 份全失败旁车 38377 页，共约 32 小时，分约 6 晚；工具 `python -m app.tools.ocr_backfill` 写到 `/opt/zhitong/ocr-backfill/`，不直接写 NAS，核对后由用户手工拷回。
- 外部依赖：DeepSeek API（`deepseek-v4-flash`）；OnlyOffice DocumentServer 5.3.4.3（已购授权，一期在线编辑关闭）；LibreOffice（镜像内）；ICP 备案（2–4 周，是最长前置）。
- 已知风险：Spring Boot 2.7.8 已 EOL；fastjson 双版本；jjwt 0.9.1；OnlyOffice 5.3.4.3 多个已知 RCE 或 SSRF；alpine 3.17 已 EOL；Electron 21。

---

## F. 迁移中必须保留的"领域知识资产"

按"没有它们，换了载体也要从零重做"的价值排序。

### F.1 规则表和主数据（`engine-service/app/engine/data/`）
| 资产 | 说明 |
|---|---|
| `gb50854_zj2025.yaml`（4992 行） | 490 码 / 17 章，含 `features_text`、`unit`。最核心的主数据 |
| `gb_chapters_2013.yaml` | 九部规范附录名加 4 位章名兜底。**章名是人工录入，须造价员核对（D43）** |
| `quantity_rules.yaml`（415 行） | 清单生成确定性规则：专业范围词表、做法片段词表、一致性规则 16 条、易混淆 9 条、层的角色、标段排除模式 |
| `classify_rules.yaml`（307 行，235 条） | 文件分类规则，客户已于 D-035 核对确认；13 步判定顺序；每次口径变更随逐行对照附录送签（附录 A 62KB、附录 B 30KB） |
| `doc_category_map.yaml`、`audit_evidence_rules.yaml` | 分类器类目折算到清单类目；核查证据冲突表 |
| `summary_fields.yaml`（585 行，78 项） | 概要字段目录：类型、同义词、定义、排除项、取值规则、适用文档角色。提示词内容改动要升 `FIELD_PROMPT_VERSION`。**这批定义是初稿，待造价员签核（D-R15）** |
| `consulting_fields.py` | 14 个老字段的单一事实源：`FieldDef`、四元组通道（deepread / llmread / rag）、来源优先级、文档角色识别 |
| `tk_detect.yaml` | 投控规则阈值（版本 `v1-20260711`，客户侧仍标 draft，train 6 项目上调的起点值） |
| `fee_rules_zj2018.json` + `fee_rules_transcription.md` | 16 条"工程建设其他费用"费率规则，由浙江 2018 定额等三来源的扫描图 LLM 双遍转录，每值带溯源。**状态为仓主默认放行（非造价员签署）**，勘察费设计费闭开性缺口单独扣留 |
| `estimate_templates/`（`gsyz_v1.json`、`gsyz_v1_template.xlsx`、`gsyz_v1.policy.json`、`fee_images/`） | 概算模板（9 sheet / 515 公式 / 211 输入位），脱敏后入仓；预备费率默认 5%，软区间 3%–8%，1% 必须能算 |
| `report_templates.yaml`（2303 行） | 24 套、172 章的 AI 初稿章节提示词与取材词，见 D.1 |
| `skills.json` | 63 个办公 skill 快照（价值有限，且部分判为空壳会编造） |

### F.2 种子和清单（`后端/sql/tenant-init/`）
- `tenant-seed-template.sql`：五阶段、约 20 项通用资料清单加结算审核 12 项与招标控制价 4 项专属清单、`project_service_scope` 三类、`project_core_info_dict` 字段字典、模板文件夹、config 25 行等。其中清单类目和别名的口径有多项"暂定、后面可改"的客户未确认裁决（#210 审核报告归审定、#319 合同价款约定归施工过程、D63 结算送审书必备、分套清单等）。
- `summary-template-seed.sql`（生成物）、`concept-indicator-seed.sql`（193 条概算条目 + GB50854 章前缀映射，生成器 `generate_concept_seed.py`）、`tenant-registry-seed.sql`、`costai-app-card-upgrade.sql`。
- Java 侧 `costai/summary-field-catalog.json`：哪些字段要抽、哪些是金额、阶段到字段组的映射。与引擎 `summary_fields.yaml` 由两道闸钉住。

### F.3 模板和知识
- `docs/报告模板扩充包/`（16 份 docx、生成器、校验器、manifest）、`docs/报告模板起步包/`（3 份）。
- `docs/知识库结构化/`：K0–K9 共 11 个 Markdown 的生成器和校验器，由码表确定性生成"一码一行"的检索资料；`sources/GB50854-2013.md` 为国标 2013 全文原件（版权页定价已改为"略"）。
- 16 张费率图（`fee_images`）已入知识库（PR #388）。
- 知识库实际数据：生产 `knowledge/1` 下 9 本扫描版定额书至今没有可读文本（数据缺口）。

### F.4 提示词措辞和防线（散在代码里）
- 报告每章 `gen_prompt` 的四段式写法，以及"程序性陈述放 claims 不放正文"的口径。
- 抽取提示词：字段定义、同义词、排除项、取值规则，文档按"不可信数据"包裹；`field_extract.py` 的原文 quote 核验；`quote_locator.py`。
- 分类 LLM 兜底 prompt 带路径和 300 字正文首段（D66）。
- 清单生成的 LLM 片段分类提示词、`quantity_features.py` 的槽位回填。
- 文件树问答的八道防线措辞与定案行（`app/filetree/agent.py`，8000+ 行级别的实现，调研里记录了行号）；A/B/C 引用分级措辞。
- 对话 `chat.py` 的四档路由与泄漏 scrubber。

### F.5 业务术语表（代码和 `.kb/business-logic.md` 中使用）
- **项目与资料**：项目、项目资料（`project_file`）、造价阶段（估算 / 概算 / 招标控制价 / 施工过程 / 结算 / 审定）、资料类目、齐套核查、齐套率（`coverage_rate`）、要求级别（必备 / 重要 / 可选）、咨询类型（全过程造价咨询 / 结算审核 / 招标控制价编制）、标段、WBS 单项 / 单位工程（T1 栋、9# 楼）、期次（第 N 期，从文件名识别）、旁车（`.ocr.txt`）。
- **计价与结算**：送审、审定、核增、核减、核减率（净口径，D36）、基线（合同控制价 / 投标价）、清单项目特征、综合单价、综合合价、暂估价、暂列金额、总承包服务费、安全文明施工基本费、规费、税金、预备费、其他项目费、措施项目、计日工。
- **规范与文件**：GB50854（房屋建筑与装饰）、GB50856（通用安装，**未引入**）、GB/T 51095、广联达 GBQ7、"浙江 2025 版"与"国标 2013 版"。
- **投控**：投控 / 跟踪审计、异常类型（重复计取、暂估价滥用、行内自洽、大额、单价超合同、量超合同、漏项、合同外新增）、HITL 人工复核。
- **概算**：房屋建筑工程概算指引（`gsyz`）、建筑安装工程费、专项工程费、室外及配套工程费、工程建设其他费用。
- 内部口径词：铁律 1–8、needs_manual、ocr_risk、`outcome`（ok / partial / empty / insufficient / error）、`EvidenceRef`（file_id、rel_path、sheet、cell、row、page、paragraph、quote）、定案行、金标。
- 命名坑：术语约定里"标注 ≠ 审阅"，"审定 ≠ 核定"。

### F.6 其他应保留的方法资产
- 金标验收思想（D8）：每个能力带 golden set，引擎在新环境对金标达到原精度才算"接上了"。目前金标是从实现自己生成的，**只能证明与上次一致**，真实样本核对（待客户确认第 9 条）一直没有到位。
- 结果契约 C1–C20（见 `2026-09-29-生产质检整改-design.md`）和 D1–D69 决策，是上一轮已经想清楚的设计，迁移时可直接作为 harness 约束清单。
- `docs/裁定/裁定记录.md`：第一手裁定记录，含"外部阻塞项默认放行先部署"（D-2026-09-10-03）。

---

## G. 我对 owner 所说"大量冗余的任务"的判断（10 行）

1. 最直接的指向是**同一件事被各功能各做一遍**：标注、齐套、抽取、报告、问答、清单、概算各自读一遍原件、各自解析 docx / xlsx、各自选材、各自写轮询、各自处理超时和 OCR 降级（设计层重复 K25–K28，加 WS06 / WS04 / WS07 的"共用层"整改）。
2. 其次是**一个用户任务被拆成 7–8 个相互独立的异步 `engine_task`**（标注 → 齐套 → 抽取 → 核对 → 指标 → 投控 → 报告），用户要逐个入口点按钮，每个任务重复送同一批文件进 LLM，一次字段提取曾用 329 万 token，"任务记录"里每行没有去处（WS28）。
3. 第三是**工程流程本身的自我繁殖**：门禁盯门禁（闸族分诊"连续九轮自我繁殖"）、388 个 changelog 片段里约四分之一与门禁和夹具有关、33 处共享文件冲突裁决、两轮整改合计 300+ 个分片，大量工作是在补"测试够不到失败分支"和"空结果被当成功"。
4. 第四是**重建原厂功能的价值存疑**：原厂目录审阅链、文件级审阅、报表在线填报与 PDF 回传（WS23-b/c/d/e、WS25-f/i2）被总纲标为"价值待确认，用户不叫停就照做"，G2 审计"没有找到它们对应的造价任务"。
5. 第五是**双轨并存**：向量 RAG 与 filetree 两套检索、引擎 24 套 AI 模板与模板库 docx 两套"报告模板"、Electron 与 Web 两个前端、Java 与 Python 两套状态机边界、两套租户开通路径（旧 `/agree` 与新 `tenant-add`）。
6. 第六是**把"成功"定义得太浅**：很多"任务"是返工产生的——200 加空结果被当完成、齐套率假高、报告元话语混进正文，导致需要补一轮"结果充分性契约 + outcome 列 + 前端黄条"。
7. 第七是**人工确认被任务化**：待用户采纳的候选字段、待复核的异常、待签核的字段定义与费率与口径变更附录，这些确认环节没有被合并成统一的"待办收件箱"，散在各功能里。
8. 我的判断：owner 说的"冗余"很可能不是"功能多余"，而是"同一份业务动作（读资料 → 判断 → 出结果 → 人审 → 归档）在产品里被实现了很多遍，每遍都要单独维护、单独出 bug、单独被质检"。
9. 因此迁移到 agent harness 时，最大的收益点是**把"读、选、解析、缓存、证据、结果契约、人审、归档"收成各一个共用 tool / plugin**，而业务功能只剩提示与规则的组合；最大的风险是**把现有的确定性规则表、签核债和铁律一起丢掉**（尤其是铁律 2 / 3 / 8 和 F 节的数据资产）。
10. 需要 owner 确认的一点：他指的"任务"是用户侧的 `engine_task` 与功能入口，还是研发侧的 issue / 分片 / 门禁？证据上两者都成立，但应对方式不同——前者靠重新划分 skill 与共用 tool，后者靠砍掉 Java / 前端 / 门禁这一整层。
