# 集成验收状态

验收日期 2026-10-19，分支 `claude/quirky-gates-woud76`，基于提交 `0f8dae5e0`。spec 见 [README.md](README.md)，工单见 [tasks/README.md](tasks/README.md)。

## 工单状态

| 工单 | 状态 | 提交 | 测试 |
|---|---|---|---|
| W0 基础 | 已合入 | `d2d2dee29` `bf6a23654` | tool-tos vitest 38 通过 1 跳过（真桶）；config-import vitest 11 通过；两包 `tsc --noEmit` 退出码 0；`tests/common` 44 通过 |
| W1 zt-project / zt-ask / zt-archive | 已合入 | `b2e21506a` | textextract 243、sidecar 41、inventory 271，全部通过 |
| W2 zt-reconcile / zt-indicator / zt-tk | 已合入 | `3e20dfe15` `b51172531` | costsheet 263 通过 3 跳过、code_registry 41、amounts 36、reconcile 51、indicator 66、tk 139 |
| W3 zt-report | 已合入 | `e0eac1bd1` `7d45cc22c` | report 544 通过 |
| W4 zt-quantity / zt-estimate | 已合入 | `652d8f79a` `2e41a1fec` `0f8dae5e0` | quantity 647 通过 5 跳过；estimate 548 通过 12 跳过 |
| W5 tool-cad / zt-cad | 已合入（合并提交 `10f0b7b92`，bundle 已挂 `zhitong-tool-cad`） | `d06cac451` `ff978197f` `c8d8bac78` `81fd41991` | 合并后在主树复跑：tool-cad vitest 44 通过；`tsc --noEmit` 退出码 0；真实 DWG 用例依赖本机 `bin/linux-x64/dwg2dxf`（已构建，gitignore 排除） |
| W6 zt-knowledge | 已合入 | `82c7d030c` | `check_knowledge.py --root knowledge-seed`：12 个目录、16 条、0 违规 |
| W7 zt-volc | 已合入 | `e7f584cb0` | volc 102 通过（`ve` 输出为合成夹具） |
| W8 迁移 | 未开始 | — | `zhitong/migration/` 不存在 |
| W9 安装包 | 未开始 | — | — |
| W10 门户文案 | 已合入 | `d4a7fa2dc` | 无测试 |

## 测试原始结果

```text
zhitong/python$ uv run pytest
3036 passed, 20 skipped in 124.90s (0:02:04)

zhitong/plugins/tool-tos$ pnpm vitest run
 Test Files  2 passed | 1 skipped (3)
      Tests  38 passed | 1 skipped (39)
zhitong/plugins/tool-tos$ pnpm exec tsc --noEmit -p .   → exit 0

zhitong/plugins/config-import$ pnpm vitest run
 Test Files  1 passed (1)
      Tests  11 passed (11)
zhitong/plugins/config-import$ pnpm exec tsc --noEmit -p .   → exit 0
```

20 个 pytest 跳过：3 个需要 `ZT_NAS_DATA` 真实语料，4 个需要 `TG_GOLDEN_XLSX` 真实金标，13 个是旧 HTTP 层、鉴权、OCR 服务或 LLM 调用机制的用例，zt 里没有对应物（跳过原因写在各用例的 `reason` 里）。

## 静态检查

- `bundle/cordis.patch.yml`：31 个插件包名都能在 `packages/*/*/package.json` 或 `zhitong/plugins/*/package.json` 找到，子路径导出（`/tools`、`/list-agents`）存在；`skill-filesystem` 的 `providerName`、`includeDefaultRoots`、`bundledSkillDir` 都是该插件的 Config 字段；`bundledSkillDir` 的 `!!js` 表达式解析到 `zhitong/skills`，目录存在。`preset-zhitong` 的 22 个插件行与上游 `standard.patch.yml` 一致，只有 `persona.prefix` 不同。
- skills：11 个 `SKILL.md` 的 frontmatter 都能解析，只有 `name`、`description`、`whenToUse`，`name` 与目录名一致；正文 1997–3920 字符（上限 8000）；正文引用的 `scripts/`、`data/`、`references/`、`templates/`、`../_shared/` 路径全部存在；15 个脚本在 `uv run python <脚本> --help` 下退出码 0。
- 凭据：扫描 AK/SK、token、密码、私钥头，命中的都是测试哨兵值（`AKLTSENTINEL`、`AKLTexample…`、`SENTINEL-SECRET-VALUE`）和文档占位符，没有真实凭据。
- 客户资料：仓里的二进制文件只有合成夹具（openpyxl / python-docx 生成）和 16+3 份 docx 报告模板（作者字段为「天工智通」，正文为空白模板）；`sys_company_code` 只以 `null` 或测试值 `"1"` 出现。

## 本次修复（`fix(zhitong): …`）

1. 去掉误提交的 3 个 `__pycache__/*.pyc`（`skills/zt-archive/scripts/`、`skills/zt-project/scripts/`），新增 `zhitong/.gitignore` 忽略 `__pycache__/`、`*.pyc`、`.pytest_cache/`。
2. 11 处 SKILL.md 把确认工具写成 `user-questions`（那是事件名），模型看到的工具名是 `ask_user_question`，已改正。
3. 旧仓迁来的测试与规则注释里带着真实项目名（北苑街道某地块房地产项目全称、某医院全称、QA 案例代号），改成匿名写法；测试只换字面量，断言不变。`skills/zt-report/data/report_templates.yaml` 第 454 行注释里的「北苑(结算审核)」没改，因为 `test_templates_yaml_is_byte_identical_to_the_old_repo` 要求该文件与旧仓逐字节一致。`survey/` 是勘察底稿，未动。

## 遗留问题

### 需要 W0 / W9 处理

- **解释器**：skill 脚本只在能 `import zt` 的解释器下运行。用系统 `python3` 直接跑会以 `ModuleNotFoundError` 退出（退出码 1、无 JSON），不符合结果契约。安装包要设置 `ZT_PYTHON` 并让 `zt` 可导入；或由 W0 给脚本加一段统一的导入检查，输出 `{"error": {"code": "zt_not_importable", …}}` 并以退出码 2 结束。
- **打包内容**：`skills/_shared/`（无 SKILL.md，不应被当作 skill 加载）与 `skills/zt-project/data/` 要随 skills 一起分发；W1 的脚本会把 `ZT_PROJECT_DATA` 设为各自 skill 的 `data/`。
- **zt-volc 接入 config-import**（W7）：`ssh`、`volc` 两节目前只校验（`deferredSections`）。config-import 需把 `volc.profile`、`volc.region`、`ssh.hosts[].alias` 写到 skill 可读的位置并设置 `ZT_VOLC_CONFIG`；`host`、`user`、`port`、`privateKey` 写进 `~/.ssh/config`。CONFIG-PACKAGE.md 要写明 `ve` profile 由用户 `ve configure set` 创建。
- **模型**：bundle 没有固定模型，按账户目录取默认；spec 定的是 DeepSeek V4.1 Flash（上游目录 id `deepseek-flash`），如需固定由 W0 在 profile 里设置。
- **python/README.md**（W0 拥有）：可补各分区 CLI 入口：`zt.textextract.cli extract|search|check-answer`、`zt.sidecar.cli parse|locate`、`zt.inventory.cli scan`、`zt.costsheet.cli probe`、`zt.reconcile.cli run`、`zt.indicator.cli run`、`zt.tk.cli detect|review|progress`，以及 W7 新增的 `zt/volc/` 分区（CONVENTIONS 的目录表里没有它）。
- **zt.common**：`to_rel_posix("   ")` 不拒收纯空格路径，之后才报 `file_not_found`；实际使用无影响。
- **CI**：可在有真实语料的机器上设置 `ZT_NAS_DATA`、`TG_GOLDEN_XLSX`，跑上面 7 个跳过用例。
- **W8 迁移**：`upload.sh` 要排除 `knowledge-seed/_tools/`；生成项目说明时对齐 W1 的格式（可直接用 `zt.inventory.draft.draft_project_doc`）。

### 数据签核与口径

- zt-project 的 `classify_rules.yaml`、`checklist.yaml`、`doc_category_map.yaml`、`audit_evidence_rules.yaml` 整体待签核：WS13 起的变更与分套清单 42101–42212 在旧仓就未获客户确认，`checklist.yaml` 每条带 `signoff`（seed / provisional / unconfirmed）。对客户不能说「按客户确认的清单」。
- W2 的 `tk_detect.yaml` 阈值是草案；「金额完全相同的重复行会不会漏判」仍未回答。
- W6 知识库：所有网页条目的数字、日期、文号只来自搜索摘要，全部标待核；浙江 2025 码表（490 码，158 个 Z 码）与定额正式附录未逐码核对；`fee_rules_transcription.md` 是仓主默认放行，不是造价员签署；`repo-snapshot` 里 `quantity_rules.*` 来自旧仓工作树而非 `33601ca8`。
- W4 保留了 `owner_release` 签核状态与 `CLOSURE_KNOWN_GAPS`（勘察设计费闭开性缺口单独扣留）。

### 功能与验证缺口

- 没有在真实广联达导出文件上做过端到端核对，M1 验收项「一个真实项目从头核对到尾」未完成；W2 全部输入是合成 openpyxl 夹具。
- W2 告警文案仍指向旧网页（「对比口径」「指标计算」对话框、「含税总造价」），为了与金标一致没有改；SKILL.md 与 `_shared/costsheet/告警码.md` 写了对应参数。`needs_manual` 按字段名模式标注，可能误标 `rows_total` 这类计数。金标只比较旧 JSON 里有的字段，新字段不受检。
- W2 留给 W3 的事项：`tests/indicator/test_fee_breakdown.py` 删掉的 report_facts 断言（C8 = 2157365.00，差 -0.37）要在 report 侧补回；`tests/report` 里目前没有这条断言，尚未补回。
- W1 资料盘点只看文件名；扫描件和 `IMG_0001.jpg` 一类进 `unclassified_files`（默认只列前 100 个）。项目编号分配没有锁，只靠推送后的回读发现撞号（spec 决策 13）。案例索引模板比 spec §5 多一列「状态」，需 spec 负责人确认是否保留。
- W7 的 `ve` 与 `tosutil` 输出是按 SDK 字段手写的合成夹具，`tosutil.*.txt` 的行格式未经真实工具核实；拿到真实 `ve` 后按 `tests/volc/fixtures/README.md` 重录并脱敏。夹具里的 `120.55.10.x` 是真实公网段，因为校验逻辑要求 `is_global`，不能换成文档保留段。
- 还没有录制 keyless 会话快照（W1 工单要求的一项），也没有在三平台 CI 上跑过；Windows 路径只有单元测试覆盖。
- W5 tool-cad 在独立分支上，合入后需重新执行本文件的 bundle 与 skill 检查（新插件包名、`zt-cad` 的 SKILL.md）。
