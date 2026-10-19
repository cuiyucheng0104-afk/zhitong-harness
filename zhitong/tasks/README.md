# 工单

执行方式：Fable 负责 spec、验收与合并；每个工单由一个 Sonnet 或 Opus 子代理独立完成，只读 `zhitong/README.md`、本文件和工单指明的勘察段落。产出进 `zhitong/` 对应目录并附测试。

交付自检：产出里没有凭据；没有把「待签核」数据标成已确认；脚本输出遵守 README §4.2 结果契约；改了旧提示词措辞就升 `prompt_version`；路径处理在 Windows 与 POSIX 下都有测试。

## W0 基础：profile、内置 Python、tool-tos、config-import

依赖：无。读：README §3、§5、§7；`packages/bundle/headless/cordis.patch.yml`、`packages/boot/plugin-manager/README.md`、`apps/desktop/README.md`、survey/03 §3.5。

- `zhitong/bundle/`：`package.json` 的 `dsh.bundle.patch`；`cordis.patch.yml` 挂三个插件、`bundledSkillDir` 指向 `zhitong/skills`、造价人设 `personaPrefix`、默认沙箱、缓存根与上限。
- `zhitong/plugins/tool-tos/`：`defineTool` 注册四个工具；火山 TOS 官方 Node SDK；凭据走 harness 凭据存储；本地目录 fake 后端测试全部工具；真桶测试需显式环境变量。
- `zhitong/plugins/config-import/`：`zhitong.config.json` 的 schema、校验、写入；不回显密钥；`zhitong/CONFIG-PACKAGE.md` 写格式说明给你做配置包用。
- `zhitong/python/`：`uv` 锁定 3.11 与依赖清单；插件启动时校验解释器与包指纹；三平台 CI。
- `zhitong/INSTALL.md`：Mac 与 Windows 从零安装到打开样例项目。

## W1 skill：zt-project、zt-ask、zt-archive

依赖：W0。读：README §5、§8；survey/01 §3.2（齐套规则）、§3.12（导航纪律）；survey/04 §A。

- 三份 SKILL.md；`zt-project` 的资料盘点脚本（清单表 + 分类规则，只报缺件不打标签）；`项目说明.md` 与 `案例索引.md` 的模板。
- 样例项目夹具（合成，不含真实客户文件）；录制一个 keyless 会话快照。

## W2 skill：zt-reconcile、zt-indicator、zt-tk

依赖：W0。读：survey/01 §3.4、§7、§9。

- 从 `/home/user/zhitong-cost-ai/engine-service/app/engine/` 提取 `costsheet.py`、`code_registry.py`、`reconcile_engine.py`、`indicator_engine.py`、`tk_engine.py`、`tk_align.py`、`costsheet_probe.py`、`amounts.py` 到各 skill 的 `scripts/`（共享部分放 `zhitong/skills/_shared/`），去掉 FastAPI 与租户代码。
- 子命令 CLI：`python scripts/reconcile.py run --submitted a.xlsx --approved b.xlsx --out work/`；JSON 到 stdout，xlsx 到 `--out`。
- 迁移金标 `tests/golden/`、`costsheet_shapes.py` 夹具、`tk_detect.yaml`；pytest 三平台。
- 三份 SKILL.md：定位文件的规则（按项目说明的关键文件指引，缺则问）、脚本调用、结果转述纪律、`工作/` 产物命名。

## W3 skill：zt-report

依赖：W0。读：README §4.1；survey/01 §3.7；survey/04 §D。

- 提取 `report_compose.py` 的选材与分块、`report_facts.py`、`report_guard.py`、`report_export.py`、`approval_grid.py`、`report_sections.py`；拆成 `prepare`（选材 + 事实编号 + 章节写作要求）与 `finalize`（护栏 + 事实替换）；`export` 出 docx（或改用 skill-office 的 docx 技能，二选一并说明）。
- `data/report_templates.yaml` 原样迁入，每章 `prompt_version` 保留；16 份 docx 模板作可选输出。
- SKILL.md：模板选择、claims 确认（`user-questions`）、逐章循环、护栏结果如实转述、落盘到 `成果/`。
- 迁移 `report_guard` 判例夹具。

## W4 skill：zt-quantity、zt-estimate

依赖：W0。读：survey/01 §3.5、§3.6。

- 清单：`quantity_segment.py`、`quantity_rules.py/yaml`、`quantity_features.py`、`code_registry.py`、`gb50854_zj2025.yaml` → `prepare`/`finalize` + xlsx 渲染；SKILL.md 收录易混淆对照与「码表存在才用、不一致降待核」。
- 概算：`estimate_*`、`fee_rules.py`、`estimate_templates/` → `extract_prepare/finalize`、`suggest`、`compute`；保留闸顺序与 `owner_release` 签核状态、`CLOSURE_KNOWN_GAPS`。
- 合成金标与 515 公式逐格一致测试。

## W5 插件：tool-cad 与 skill zt-cad

依赖：W0。读：README §7；`survey/05-cad-viewer.md` 全文（§8 是推荐设计，按它做）。

- 从 `/home/user/cuiyucheng0104-afk/tiangong-cad-viewer` 搬 core（`src/engine/*`、`frames.ts`、`roomCheck.ts`、`extract.ts` 去掉 `downloadFile`、`diff.ts`、`shxText.ts`）与 convert（`resolveDwg2dxf`、魔数嗅探、UTF-8/GBK 嗅探、spawn），按 §2.2 补齐：ASCII 临时名、`mkdtemp`、超时与杀进程树、400 MB 上限；经 harness `ctx.subprocess` 调用。
- 新写 `cad_render`：`@napi-rs/canvas` 为主、纯 JS 光栅化为降级；白底、图层过滤、SHX 笔画字体 + 内置 Noto Sans SC 子集回退；按图框/矩形/点周边出 PNG，大图切片带重叠，返回 `world_rect`、`px_per_unit`、`image_size`；默认拒绝渲染整张大图。
- 第一批工具 `cad_open`、`cad_frames`、`cad_text_search`、`cad_render`、`cad_blocks`；第二批 `cad_set_unit`、`cad_rooms`、`cad_table`、`cad_layers`、`cad_diff`。判据常量（`GAP`、`MIN_AREA_M2`、`MIN_PTS`、`TXTROOM`、面积范围、`EPS`）进 Config。解析缓存按 `sha256 + SCENE_VERSION` 落在 `图纸/.cache/`。
- dwg2dxf 分发：`bin/<platform-arch>/`；Windows 官方 0.14 zip + sha256；macOS 在 CI 用 `./configure --disable-bindings --disable-shared` 静态构建；随附 GPLv3 文本、`VERSION.txt`、源码 offer、`THIRD_PARTY_NOTICES`；禁止引入 `@mlightcad/libredwg-web` 等链接式封装。
- 测试：`fixture_t3.dwg` → `buildScene` 摘要黄金区间；PNG 尺寸与非空白像素比例；中文与空格路径转换；三平台冒烟。沿用 `unit.test.mts` 的合成场景用例。
- `zt-cad` SKILL.md：先 `cad_open` 看摘要与单位证据，再 `cad_frames`/`cad_text_search` 缩小范围，再 `cad_render` + `read_image` 看图；量纲类操作先确认单位；输出进 `工作/`。

## W6 skill：zt-knowledge（含初版内容）

依赖：W0。读：README §5、§8；survey/04 §F.3；`/home/user/zhitong-cost-ai/docs/知识库结构化/`。

- SKILL.md：知识库目录规范、条目格式（来源、日期、适用范围）、写入纪律（只写有出处的内容）、工作中回写流程。
- 初版内容：用 `web_search/web_fetch` 爬取并整理——GB50854-2013 章节与计算规则摘要、浙江 2025 清单码表说明、浙江 2018 其他费用定额、常用规范目录、费率表；`fee_images` 与 `docs/知识库结构化/` 的 K0–K9 生成器迁入。每条带 URL 与抓取日期。
- 输出到 `zhitong/knowledge-seed/`，迁移时上传到桶 `知识库/`。

## W7 skill：zt-volc

依赖：W0。读：README §8；用户本机脚本的功能描述（`vec` = `ve --profile zt-ak` 封装；`ssh-access-sync.sh` = 安全组白名单同步；`pssh` = 登录生产服务器）。

- SKILL.md 与 `scripts/`：TOS 桶管理（列桶、生命周期、版本）、ECS 启停与状态、安全组白名单增删、SSH 到服务器执行命令；全部通过 `ve` CLI 与 ssh，不直接调 SDK。
- 凭据来自配置包；危险操作（删桶、改安全组）先 `user-questions` 确认。
- 无法在 CI 里连真火山：用录制的 `ve` 输出做测试。

## W8 第一个客户资料整理与上传

依赖：W1。读：README §6；survey/02 §2.1、§3.1–§3.2；survey/03 §3.5。

- `zhitong/migration/`：`export-projects.py`（只导 `project` 基本信息）、`relayout.py`（显示路径还原、清理、分类、图纸分离、生成项目说明）、`verify.py`、`upload.sh`（rclone）；全部只读旧目录，写到镜像目录；整理报告。
- `runbook.md`：在 ECS 上逐条执行的命令，不含凭据值。

## W9 安装包

依赖：W0–W7。读：`apps/desktop/README.md`、`apps/desktop/windows-signing/README.md`。

- 在上游桌面打包上叠加 bundle、skills、Python 运行时、dwg2dxf；Mac dmg 与 Windows exe；两台干净机器实装并跑 M0 验收。

## W10 门户文案

依赖：spec 定稿。读：README 全文；survey/04 §A。

- `zhitong/portal/门户文案.txt`：产品定位、给谁用、解决什么、12 项能力逐条说明、工作流示例、与旧方式对比、安装与配置、安全与数据归属、FAQ；给网页设计用，分段标注栏目。
