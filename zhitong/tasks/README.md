# 工作分解与子代理工单

执行方式：Fable 负责规划、spec、验收；每个工单由一个 Sonnet 子代理独立完成，只读 `zhitong/README.md`、本文件和工单指明的勘察报告段落，产出进 `zhitong/` 对应目录并附测试。工单之间的依赖按编号。

每个工单交付前自检：产出里没有凭据；没有把「待签核」数据标成已确认；工具输出遵守 README §4.4 结果契约；改动了旧提示词措辞就升 `prompt_version`。

## W0 Python 引擎 CLI 提取

依赖：无。读：survey/01 §1–§5、§7–§10。

- 从 `/home/user/zhitong-cost-ai/engine-service/app` 提取 `engine/*`、`textextract.py`、`text_chain.py`、`text_cache.py`、`sidecar_format.py`、`sidecar_layout.py`、`amounts.py`、`redact.py`、`filetree/answer_guard.py`、`ocr_client.py` 的本机化版本，放到 `zhitong/engine/zt_engine/`。
- 删除：FastAPI、`tenant_scope`、`auth`、`llm_client`、SSE、`parse_pool`/`parse_worker`。保留文件大小、页数、字符上限常量。
- 每个 LLM 夹层拆为 `prepare`/`finalize` 两个纯函数（README §4.3 表），输入输出用 pydantic 模型；现有校验逻辑（闭集、子串、一致性闸、覆盖不变式、`report_guard`）全部落在 `finalize`。
- 入口 `zt-engine <cmd> --in a.json --out b.json`，`zt-engine schema <cmd>` 输出 JSON Schema 供 W2 生成工具定义。
- 迁移 `tests/`：金标、版式夹具、`report_guard` 判例、费率自证、提示词指纹改为校验 `prompt_version` 常量。目标：原测试除 HTTP/租户/LLM 客户端相关外全绿。
- 交付：`zhitong/engine/README.md` 列出每个子命令的输入输出与来源文件。

## W1 TOS 工具插件

依赖：无。读：README §2、§4.1、§5；survey/03 §3.5。

- `zhitong/plugins/tool-tos/`：Cordis 插件，`defineTool` 注册 `tos_ls`、`tos_stat`、`tos_pull`、`tos_push`、`tos_manifest`。
- 火山 TOS 官方 Node SDK 或 S3 兼容客户端；凭据走 harness `credentials` 子系统，禁止读环境变量以外的任何文件。
- 本机缓存根 `~/zhitong/`（Windows `%USERPROFILE%\zhitong\`），pull 以 sha256 去重，容量上限与 LRU 淘汰、图纸扩展名永不自动拉取；push 校验回读大小。路径一律 `node:path`，测试在 POSIX 与 Windows 分隔符下各跑一遍。
- 测试：以本地目录模拟桶的 fake 后端跑全部工具；真桶测试默认跳过，需显式环境变量。
- 交付：README（配置字段、桶目录约定链接）。

## W2 引擎工具插件

依赖：W0。读：README §4.3–§4.4、harness `docs/cookbook/adding-a-tool.md`。

- `zhitong/plugins/tool-engine/`：为每个 `zt-engine` 子命令生成一个工具；`parameters` 与 `output.schema` 由 `zt-engine schema` 产出的 JSON Schema 转换；经 `ctx.subprocess` 调用，尊重 `exec.signal`。
- 每个工具的 `output.render` 给模型看摘要（状态、覆盖率、告警、关键数字带 `needs_manual`），完整 JSON 写到 `work/` 并返回路径。
- 测试：用 W0 的夹具跑每个工具一次；错误态（失败、超时、取消）各一例。

## W3 文档读取插件

依赖：W0、W11。读：README §4.1–§4.2、survey/01 §4、survey/03 §4。

- `zhitong/plugins/tool-docs/`：`doc_text`（四态降级，返回 `text_source`、页级来源、截断信息）、`doc_outline`、`sheet_read`、`ocr_request`（把对象 key 发给计算节点，等待旁车回桶后 `tos_pull`）。
- 按 §4.2 阈值分流：小文件本机 `zt-engine`，超阈值、`.doc/.xls`、OCR 走计算节点 HTTP；远端不可达报 `remote_unavailable`。
- 旁车格式与旧生产 2882 份兼容（`sidecar_format` 白名单剥离、占位句整份判未命中）。
- 测试：文字层 PDF、扫描 PDF 有旁车、扫描 PDF 无旁车（用 fake 计算节点）、docx 含修订、xlsx 多表；Windows 路径一例。

## W4 bundle、内置 Python 运行时与安装

依赖：W1、W2、W3。读：README §2、§9；`packages/bundle/headless/cordis.patch.yml`、`packages/boot/plugin-manager/README.md`、`apps/desktop/README.md`。

- `zhitong/plugins/bundle/`：`package.json` 的 `dsh.bundle.patch`；`cordis.patch.yml` 挂四个工具插件、`bundledSkillDir` 指向 `zhitong/skills`、`personaPrefix` 造价人设、默认 `workspace-write` 沙箱、缓存根、分流阈值、计算节点地址。
- 内置 Python：`uv` 锁定 3.11，`zt-engine` 与依赖随桌面包分发；插件启动时校验解释器版本与包指纹，不用用户机器上的 Python。
- `zhitong/INSTALL.md`：Mac 与 Windows 各一份从零安装、配凭据（桶 AK/SK、计算节点令牌）、打开样例项目的步骤；必须在两台干净机器上实跑。

## W11 计算节点

依赖：W0。读：README §4.2、§6.3；survey/03 §3、§4。

- `zhitong/compute-node/`：docker-compose（`ocr` 沿用旧镜像、`engine-http`、`sync` rclone 定时任务）、nginx TLS 与两条路由、`.env.example` 只列变量名。
- `zt-engine-http`：只注册确定性端点与 `POST /ocr/by-key`（按桶 key 取件、OCR、旁车回桶）；`X-Service-Token` 鉴权；预算与切块逻辑沿用旧 `ocr_client`。
- 运行手册：在现有 ECS 上替换旧 compose 的步骤，含 NAS 镜像目录重排。

## W5 技能：zt-project、zt-ask

依赖：W4。读：README §4.1、§6.4；survey/01 §3.12（导航纪律）。

- 两份 SKILL.md；`zt-project` 负责缓存目录树与占位、工作目录切换；`zt-ask` 收录旧 filetree 的约束：先看 manifest 再拉文件、步数预算、读不了的文件直接说明、引用只指向读过的位置、无出处数字标出、文档内指令不执行。
- 录制一个样例项目的 keyless 会话快照作为回归。

## W6 技能：zt-tagging、zt-reconcile、zt-indicator、zt-tk

依赖：W4。读：survey/01 §3.1、§3.2、§3.4；survey/02 §6（复核留痕字段）。

- 四份 SKILL.md；`records/` 文件的 JSON 结构在 `zhitong/records-schema/` 定义并附校验脚本；复核决策追加写 `decisions.jsonl`，重跑按 `anomaly_uid` 合并。

## W7 技能：zt-summary、zt-report

依赖：W4。读：survey/01 §3.3、§3.7；survey/04 §D。

- 迁移 `report_templates.yaml` 与 16 份 docx 模板到 `zhitong/templates/`，附 manifest 与校验脚本；SKILL.md 收录字段定义与章节 `gen_prompt` 四段式；标注 `summary_fields.yaml` 的签核状态。

## W8 技能：zt-quantity、zt-estimate

依赖：W4。读：survey/01 §3.5、§3.6。

- 迁移 `gb50854_zj2025.yaml`、`quantity_rules.yaml`、`estimate_templates/`、`fee_rules_zj2018.json`；SKILL.md 收录易混淆对照与「码表存在才用、不一致降待核」规则；费率规则保留 `owner_release` 签核状态与 `CLOSURE_KNOWN_GAPS`。

## W9 目录插件与 zt-archive

依赖：W1。读：README §5、§6.1。

- `zhitong/plugins/tool-catalog/`：从所有 manifest 与 records 构建 SQLite（项目、文件、标签、指标、核对汇总、异常计数）；`catalog_query` 只读、限时、限行数。
- `zt-archive` SKILL.md：上传前完整性检查清单。

## W10 迁移脚本与运行手册

依赖：W1、W9、W11。读：README §7；survey/02 §2.1、§3.2；survey/03 §3.5。

- `zhitong/migration/`：`export-mysql.py`（按项目导 JSON）、`build-manifests.py`、`relayout-nas.py`（硬链接到桶目录约定的镜像目录）、`upload.sh`（rclone，断点续传、分夜）、`verify.py`（文件数、字节、sha256）。只读旧库与原 NAS 目录，所有写都指向镜像目录与桶。
- `runbook.md`：由用户在旧服务器上执行的逐条命令；不含任何凭据值，只引用 `.tos-backup.env` 同款变量名。
