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
| W9 安装包 | 代码与文档已合入；Mac / Windows 实机打包与 M0 验收待用户在目标机器上执行（[INSTALL.md](INSTALL.md) 第二至四部分） | `8f2201c28` `71ca9f9a7` `25872c4e4` `e987013f9` `6a5ecbf66` `810fba853` `67a1a2953` `9f45c916f` 及文档提交 | 见下「W9 验证」 |
| W10 门户文案 | 已合入 | `d4a7fa2dc` | 无测试 |
| W11 品牌替换 | 代码与文档已提交；打包后的应用名、Finder / 开始菜单显示与首次运行待目标机器验证 | 见 git log `feat(zhitong/brand)` | 见下「W11 上游改动」与交付报告 |

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

### W9 已处理（原「需要 W0 / W9 处理」）

- **解释器**：所有 skill 脚本先执行 `skills/_shared/zt_launch.py`：`ZT_PYTHON` → `$DSH_HOME/dsh-runtimes/dsh-primary-runtime` 的解释器 → 安装包内 `Resources/runtime/primary-runtime` 的解释器 → 当前解释器；选中的不是当前解释器就重跑一次；`zt` 从 skills 旁的 `python/` 进 `sys.path`；Python < 3.11 或缺依赖时输出 `zt_not_importable`、退出码 2。11 份 SKILL.md 改成 `<python> scripts/<x>.py`（`<python>` = `$ZT_PYTHON`，否则 `load_workspace_dependencies` 返回的 `python`，都没有才 `python3`），不再写 `-m zt.*`；zt-ask 新增 `scripts/check_answer.py`。
- **Python 依赖**：上游 `scripts/primary-runtime/lock.json` 五个目标都加了 pydantic 2.14.1、pydantic-core 2.50.1、annotated-types 0.8.0、typing-inspection 0.4.4、pypdf 6.21.1、PyYAML 6.0.3（typing-extensions 4.16.0、openpyxl、python-docx、lxml、et-xmlfile 原已在内）。`zt` 不进 wheel 列表（lock 只接受远程 URL）：打包时复制进 `@zhitong/bundle/python/zt`，与 skills 一起解到 asar 外。
- **打包内容**：`skills/`（含 `_shared/`、各 `data/`、`templates/`、`references/`）与 `python/zt` 随 `@zhitong/bundle` 进 `app.asar/dsh`，asarUnpack 到 `app.asar.unpacked/`；`bundledSkillDir` 由 `@zhitong/bundle/skills-dir.cjs` 算出并换成 asar 外路径。`_shared/` 没有 SKILL.md，skill-filesystem 读不到文件时静默跳过、不告警（`readSkillText` 对 ENOENT 返回 undefined）。
- **zt-volc 接入 config-import**：`volc.profile`、`volc.region`、`ssh.hosts[].alias` 写进只有名称的 `$DSH_HOME/zhitong/volc.config.json`，zt-volc 在 `ZT_VOLC_CONFIG` 未设置时读它；`host`、`port`、`user` 写进 `~/.ssh/config` 开头的受管块，私钥写 `~/.ssh/zhitong/<alias>`（0600）。CONFIG-PACKAGE.md 写明 `ve configure set`。
- **模型**：bundle 重述 `agent-default-model` 为 `deepseek-official` / `deepseek-flash`（DeepSeek-V4.1-Flash）；设置页保存的选择仍优先。
- **python/README.md**：补各分区 CLI 入口表与运行时依赖说明；CONVENTIONS 目录表加 `zt/volc/`、`skills/_shared/`、`scripts/`。
- **lockfile**：`pnpm-lock.yaml` 的 `zhitong/bundle` 条目补上 W5 合入时漏掉的 `@zhitong/tool-cad`。

### 仍需处理

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

## W9 上游改动

合并上游时逐项核对；代码里每处都有 `zhitong increment` 注释（JSON 文件除外）。

| 文件 | 改动 |
|---|---|
| `scripts/primary-runtime/lock.json` | 共享 `wheels` 加 annotated-types、typing-inspection、pydantic、pypdf 的 py3 wheel；五个目标各加 pydantic-core、PyYAML 的 cp312 wheel；`pythonPackages` 加六项。改变所有目标的 payload digest（已安装的 runtime 会在下次使用时整体替换），也进入 Python SDK 的 runtime payload |
| `apps/desktop/scripts/package-target.ts` | vendor 打包之后运行 `zhitong/scripts/pack-desktop.mjs`，输出到 `packed/zhitong` |
| `apps/desktop/scripts/prepare-package-set.ts` | `ROOT_PACKAGES` 加 `@zhitong/bundle`；默认输入加 `packedZhitong` |
| `apps/desktop/scripts/desktop-build-paths.mjs`、`.d.mts` | 新路径 `packedZhitong` |
| `apps/desktop/scripts/electron-builder-config.mjs` | asarUnpack 加 `@zhitong/bundle/{skills,python}`、`@zhitong/tool-cad/{bin,assets}` |
| `apps/desktop/src/project-manager.ts` | 新 profile 在运行时描述含 `@zhitong/bundle` 时选中它（`desktopProfileBundles`）；恢复操作保留它；运行时项目 `allowBuilds` 加 `tos-crc64-js: false` |
| `apps/desktop/scripts/smoke-runtime.ts` | Host 冒烟用与新 profile 相同的 bundle 列表 |
| `apps/desktop/tests/{desktop-build-paths,prepare-package-set,project-manager}.spec.ts`、`runtime-fixture.ts` | 对应断言与夹具 |
| `pnpm-lock.yaml` | config-import 新增两个 workspace 依赖；bundle 补 tool-cad |

## W11 上游改动

品牌替换（产品名 **智通数工AI**，ASCII 标识 `ztsgai`，官网 https://ztsgai.com）与首次运行只引导模型 API Key。合并上游时逐项核对；代码里每处都有 `zhitong increment` 注释（JSON、Markdown、测试期望文件除外）。

### 桌面壳（`apps/desktop`）

| 文件 | 改动 | 面向 |
|---|---|---|
| `scripts/electron-builder-config.mjs`、`electron-builder.config.d.mts` | `productName` 智通数工AI（macOS `智通数工AI.app`）；协议显示名智通数工AI（`dsh://` 不变）；`win.executableName` `ztsgai`（安装到 `%LOCALAPPDATA%\Programs\ztsgai\ztsgai.exe`；非 ASCII 产品名会让 electron-builder 退回包名作目录名，且 `dsh.cmd` 按控制台代码页解析）；两个 `mac.extendInfo` 键合成一个——原对象字面量里第二个 `extendInfo` 覆盖了第一个，`CFBundleLocalizations` 一直没进 Info.plist；麦克风说明换产品名 | 最终用户 |
| `scripts/desktop-package-environment.mjs`、`.env.{macos,windows}.example`、`config/*-packaging/{production,test}.env.example`、`packaging/README{,.zh}.md` | 本机未签名包与模板的应用 ID `com.ztsgai.harness` | 打包者 |
| `scripts/smoke-packaged-runtime.ts`、`package-macos.ts`、`package-target.ts`、`verify-retained-desktop.ts` | `.app` 与可执行文件名跟随新产品名 | 打包流程 |
| `scripts/installed-update-builder.ts`、`test-windows-installer.mjs` | 上游 Windows 更新资格测试与安装器测试按 `${productName}.exe` 找程序，这两处去掉 `executableName` | 上游 CI |
| `cli/dsh`、`cli/dsh.cmd` | 启动器指向 `MacOS/智通数工AI` 与 `ztsgai.exe` | 最终用户（`dsh` 命令） |
| `scripts/command-path.ps1` | `dsh` 命令 PATH 所有权记录 `HKCU\Software\Ztsgai\Command`、互斥体 `Global\Ztsgai.Command.<sid>`，与上游安装互不覆盖 | Windows |
| `src/locale.ts`、`src/main.ts` | 中英两套壳文案（关于、菜单隐藏 / 退出、托盘、退出确认、启动失败、恢复对话框、更新标题、欢迎窗口）换成智通数工AI；欢迎语「造价咨询的 AI 工作台」；API Key 页写明默认 `https://api.deepseek.com` 与 DeepSeek V4.1 Flash（官方推荐）；关于面板 `applicationName` | 最终用户 |
| `src/client/WelcomePage.tsx`、`src/client/welcome.tsx` | `Welcome` 新增 `accountSignIn`（默认 true，上游行为不变）；打包入口传 false：欢迎窗口第一页就是 API Key 表单，没有「登录」与「返回登录」 | 最终用户 |
| `renderer/assets/welcome-brand.svg` | 欢迎窗口顶部换成占位文字标（不再是 DeepSeek 鲸鱼与字标） | 最终用户 |
| `installer/strings.nsh`、`installer/extract-report.h` | Windows 安装界面中英文案；解压失败报告头 `ztsgai installer` | 最终用户 |
| `tests/…` 与 `tests/expected/…` | 断言产品名、应用 ID、可执行文件名、命令路径的用例与期望输出；新增 `welcome/{zh-CN,en}-key-only.expected.txt` | — |

### Web 客户端与脚本

| 文件 | 改动 |
|---|---|
| `scripts/client-build-environment.ts`（及 `.client.spec.ts`） | official 构建（桌面打包走 `build:official`）的文档标题 `DSH_CLIENT_TITLE` = 智通数工AI |
| `apps/web/public/manifest.webmanifest`（及 `tests/pwa-manifest.e2e.ts`） | PWA 名称智通数工AI |
| `packages/client/ui-settings-account/src/client/locales{,/onboarding}.ts` | 产品名换成智通数工AI；「登录 DeepSeek Harness 账号」改为「DeepSeek 账号」（该账号是 DeepSeek 的账号）。本 bundle 已禁用该行，改它是为了重新启用时文案也正确 |
| `packages/client/ui-settings-account/src/contact-config.ts`（及 `contact-url.client.spec.ts`） | 「反馈」默认打开 `https://ztsgai.com/`（原为上游飞书问卷）。注意 `contactUrl` 会附加 `prefill_uid`（DeepSeek 账号 uid）、版本与设备描述查询参数 |
| `packages/client/ui-settings-models/src/client/locales.ts` | 预览版说明换成智通数工AI 自己的文字（含官网）；首次运行 API Key 步骤标题与说明（默认接口、推荐模型、自定义 OpenAI 兼容地址的位置） |
| `packages/client/ui-plugin-manager`、`ui-shortcuts`、`ui-sidebar-documentpreview` 的 `locales.ts` | 插件安装安全提示、快捷键「重新启动 / 升级」、Office 预览不可用提示中的产品名 |
| `apps/cli/src/plugin.ts`（及 `tests/plugin.spec.ts`） | `dsh plugin --profile desktop` 的报错改成让用户先打开「智通数工AI」桌面应用 |
| `apps/web/tests/…` | Web e2e 里对应文案的期望（Linux 上未运行，见下） |
| `pnpm-lock.yaml` | 新 importer `zhitong/plugins/ui-brand`；bundle 依赖它 |

### zhitong 侧（不是上游改动，列出备查）

- `@zhitong/ui-brand`（`zhitong/plugins/ui-brand/`）：填 `sidebar.brand.mark`、`sidebar.brand.name`、`conversation.hero.brand.mark`（占位文字标，主题 token 取色，深浅两色自动切换）与 `conversation.input.model.label`（`deepseek-flash` 显示「DeepSeek V4.1 Flash」+「官方推荐」）。
- `bundle/cordis.patch.yml`：禁用 `ui-brand-official`、`ui-deepseek-model-label-1017`、`ui-settings-account`，插入 `zhitong-ui-brand`。禁用 `ui-settings-account` 后 `settings.models.sign-in` 无占位者，Web 首次运行的 `DeepSeekOnboardingDialog` 直接显示 `deepseek-official` 的 API Key 表单（复用设置页 `ProviderEditor`），设置页没有「账号」页，侧栏设置按钮回到上游默认样式。Host 侧 `deepseek-account`、`authorization`、`account-controller` 保留：桌面主进程启动时读账号状态（`welcome-backend.ts` 的 `account.state()`），禁用会让欢迎流程失败。
- `scripts/pack-desktop.mjs` 构建并打包 ui-brand，检查 `lib/client.js` 与 `exports["./client"]`；`scripts/verify-desktop-app.mjs` 检查五个 `@zhitong/*` 包、可执行文件名与 `app.asar` 里的品牌客户端包。

### 有意保留的「DeepSeek Harness」

| 位置 | 原因 |
|---|---|
| `LICENSE`、第三方声明、`BRAND_GUIDELINES*`、`vendor/` | 版权行与许可要求 |
| 包名 `@deepseek-ai/dsh-*`、`dsh` 命令、`dsh://`、`$DSH_HOME` / `~/.dsh`、Electron userData `@deepseek-ai/dsh-desktop` | 技术标识与数据位置，改名会丢数据或破坏升级 |
| 安装包文件名 `deepseek-harness-<版本>-<平台>.dmg/.exe`（`artifactName`） | 上游发布 / 上传 / 版本发现 / 资格测试约 30 个脚本与用例按这个前缀匹配；换前缀要连同上游发布链一起改，留作后续 |
| `packages/core/system-prompt` 的 `You are an AI agent powered by DeepSeek Harness.`、`harness-dev-context` | 模型可见的描述性身份（「基于 DeepSeek Harness」），改动要重录快照与两套 SDK 期望；智通人设在 `personaPrefix` 里 |
| `apps/cli/src/args.ts` 的 `--help` 描述、`docs/cli-help*.md` | 开发者命令行帮助，描述上游 `dsh` |
| 欢迎页 / 引导页文字中的「基于 DeepSeek Harness 构建」、`llm-pi-ai` 插件描述 | 描述性用法，品牌规范允许 |
| `apps/desktop/scripts/development-app.ts`（Harness Dev） | 只在开发机上出现的开发版应用 |
| 启动冲突提示里的「DSH」 | 上游缩写，品牌规范允许 |
| `docs/`、`.agents/`、各包 README 与 `package.json` 描述 | 开发者文档 |

## W9 验证（Linux 容器，2026-10-19）

```text
scripts/primary-runtime$ vitest run prepare.spec.ts                      17 passed
tsx scripts/primary-runtime/prepare.ts --target linux-x64 --python-only  exit 0（含 smoke.py 发行包集合核对与 pip check：No broken requirements found）
apps/desktop$ vitest run tests/                                           145 文件通过；macos-notarization-proxy.spec.ts 15 例失败（flock 原生插件未构建，与本次改动无关）
apps/desktop$ tsc --noEmit -p tsconfig.host.json                          exit 0
zhitong/python$ uv run pytest                                             3045 passed, 20 skipped
zhitong/plugins/{tool-tos,config-import,tool-cad}$ vitest run             38+1 跳过 / 15 / 46 通过；tsc --noEmit 均 exit 0
node --test zhitong/scripts/tests/*.test.mjs                              7 passed
node zhitong/scripts/pack-desktop.mjs --platform linux --arch x64         4 个 tarball，内容检查通过
pnpm install --frozen-lockfile（排除 documentpreview）                    通过
```

模拟验证：把打出的 tarball 解到假的 `Resources/app.asar{,.unpacked}/dsh/node_modules` 布局，按 Cordis YAML 方言解析 `cordis.patch.yml` 并以 `with (ctx) eval` 求值 `bundledSkillDir`：安装包布局（空 profile + installAnchor）得到 `app.asar.unpacked/.../skills`，仓库布局（link 安装）得到 `zhitong/skills`，两者都没有时报错；`verify-desktop-app.mjs` 对假布局（真实 asar 描述文件 + linux-x64 standalone Python 3.12）20 项全部通过，其中没有依赖的 venv 解释器经启动器重跑到内置解释器。tarball 用 pnpm（hoisted、autoInstallPeers=false）装进临时项目，外部依赖装得上，暴露出 `tos-crc64-js` 构建脚本需要在运行时项目放行（已加）。

### Linux 上无法验证（需在目标机器上做）

- `pnpm run package:desktop:mac:arm64:unsigned` 与 `package:desktop:win:x64:unsigned` 整条流程（含 `build:official`、`release:pack`、Electron 下载、`prepare:dsh` 的 `pnpm install --prod`、Host 冒烟、electron-builder、DMG / NSIS），以及 Host 冒烟在带 `@zhitong/bundle` 的 profile 下能否启动。
- Electron `ELECTRON_RUN_AS_NODE` 下：运行时解析能否从 `profileContext.installAnchor` 解析到 `@zhitong/bundle/skills-dir.cjs`、asar 内 `existsSync` 与 asar→unpacked 映射、`@napi-rs/canvas` 从 unpacked 路径注册字体、从 unpacked 路径启动 dwg2dxf。
- macOS 上 `build-dwg2dxf.sh`（clang 静态链接、`otool -L` 检查、ad-hoc 签名）与 ad-hoc 签名应用里子进程能否执行；Gatekeeper 首次打开流程。
- Windows：`fetch-dwg2dxf-win64.ps1`（没有 PowerShell，未执行；zip 的 sha256 与根目录文件清单已在 Linux 上核对）、`.env.windows` 最小配置下打包、NSIS 安装、中文用户名路径。
- 打开应用后的验收清单（预设、12 个 skill、`load_workspace_dependencies` 对智通预设可见、`cad_open`、`config_import` 写 ssh/volc）与两台干净机器的 M0 验收。
