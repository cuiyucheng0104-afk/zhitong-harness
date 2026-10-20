# 开发约定（所有工单必读）

spec：[README.md](README.md)。工单：[tasks/README.md](tasks/README.md)。旧项目源码只读：`/home/user/zhitong-cost-ai`（引擎在 `engine-service/app/`）。

## 目录与归属

```text
zhitong/
  bundle/                 @zhitong/bundle：cordis.patch.yml + package.json(dsh.bundle)        W0
  plugins/tool-tos/       @zhitong/tool-tos                                                   W0
  plugins/config-import/  @zhitong/config-import                                              W0
  plugins/ui-brand/       @zhitong/ui-brand（Web 客户端品牌位与推荐模型标签）                  W11
  python/                 uv 项目，包名 zt；pyproject.toml 只有 W0 能改                        W0 建骨架
    zt/common/            结果信封、JSON 读写、CLI 基类、路径工具                                W0
    zt/textextract/ zt/sidecar/ zt/inventory/                                                 W1
    zt/costsheet/ zt/code_registry/ zt/amounts/ zt/reconcile/ zt/indicator/ zt/tk/            W2
    zt/report/                                                                                W3
    zt/quantity/ zt/estimate/                                                                 W4
    zt/volc/                                                                                  W7
    tests/<area>/         与上面同名分区；夹具放 tests/<area>/fixtures/
  skills/<name>/          SKILL.md + scripts/（薄 CLI）+ data/（规则与模板）                    各工单
  skills/_shared/         各 skill 共用的说明与 zt_launch.py（解释器与 zt 定位，无 SKILL.md）     W9
  scripts/                pack-desktop.mjs（桌面安装包打包 bundle、插件、skills 与 zt）           W9
  knowledge-seed/                                                                             W6
  portal/                 门户站点（site/）、部署件（deploy/）、门户文案                              W12
  brand/                  品牌源文件与生成的应用/网站图标；scripts/brand-icons/ 生成器                 W12
  migration/                                                                                  W8
```

每个工单只写自己归属的目录。需要别人目录里的改动（例如新依赖、`zt/common` 的新函数），写进交付报告的「需要的改动」，不要直接改。

## Python

- 入口统一：`python -m zt.<area>.cli <子命令> --in request.json --out result.json`，或 skill 的 `scripts/<x>.py`（只做参数解析后调用 `zt`）。stdout 只输出一个 JSON；日志走 stderr。
- skill 脚本在导入 `zt` 之前执行 `skills/_shared/zt_launch.py` 的固定片段（见该文件文档）：解释器取 `ZT_PYTHON` → 桌面版 primary runtime → 当前解释器，`zt` 不可导入时输出 `zt_not_importable`。新脚本照抄现有脚本的头部；片段之前只能有文档字符串与 `from __future__`。
- 结果信封（`zt.common.envelope`）：`{"status": "ok|partial|empty|insufficient", "status_reason": str|null, "coverage": {...}, "warning_items": [{"code","level","message","hint"?}], "data": {...}, "needs_manual": true}`。金额与数量字段所在对象都带 `needs_manual: true`。失败：退出码 2，stdout 为 `{"error": {"code","message","hint"?}}`，绝不输出「成功 + 空」。
- 不调用任何模型 API。原来夹在流程中间的 LLM 步骤拆成 `prepare` 与 `finalize` 两个子命令（spec §4.1）。
- 跨平台：`pathlib`，显式 `encoding="utf-8"`，不用 `shell=True`，不假定 `/tmp`。Python ≥3.11；容器里是 3.13。
- 依赖只用 pyproject 里已声明的：`openpyxl pypdf PyYAML python-docx pydantic`；测试 `pytest`。
- 从旧仓搬代码时保留文件头的来源注释（原路径）与 `prompt_version`/规则版本常量；数据文件头保留签核状态，不得改成已确认。
- 迁移旧测试与金标：能跑的全跑；跳过的写明原因。

## TypeScript 插件

- 包名 `@zhitong/<name>`，`"type": "module"`，`private: true`；依赖上游用 `"@deepseek-ai/dsh-tools": "workspace:*"`、`"@deepseek-ai/cordis": "workspace:~"`。参照 `packages/shell/tool-bash` 的 `package.json`、`tsconfig.json`（extends 根 `tsconfig.base.json`，`rootDir: src`，`outDir: lib/types`）与 `tests/`。
- 工具用 `defineTool`（`docs/cookbook/adding-a-tool.md`）；`output.schema` 与 `render` 分离；长输出写文件返回路径。
- 可调参数都是 `Config` 字段（schemastery），不写 `DEFAULT_*` 常量当配置。
- 测试 vitest；在包目录 `pnpm vitest run`。`pnpm install` 由 W0 在根目录完成一次。

## Skill

- `zhitong/skills/<kebab-name>/SKILL.md`，frontmatter 必有 `name`、`description`，可选 `whenToUse`。正文 ≤ 8000 字符（上游工具结果修剪阈值 8192），长内容放 `references/` 按需读。
- 正文写：何时用、步骤、调用哪个脚本（`<python> scripts/<x>.py ...`；`<python>` 取 `$ZT_PYTHON`，否则 `load_workspace_dependencies` 返回的 `python`，都没有才 `python3`；不要写 `-m zt...`，桌面版的解释器里 `zt` 不在 site-packages）、结果如何转述、落盘到项目的哪个目录、纪律（结果契约、needs_manual、引用只指向读过的内容）。
- `skills/` 根目录只放 skill 目录与 `_shared/`，不放 `.md` 文件（会被当作 skill 解析）。
- 旧提示词措辞进 SKILL.md 或 `references/`，标注 `prompt_version` 与签核状态。

## Git

- 只 `git add` 自己归属的路径，提交信息 `feat(zhitong/<area>): ...`；遇到 `index.lock` 等 2 秒重试，最多 5 次；不 push；不提交任何凭据、`.env`、真实客户文件。
- 交付报告（作为最终回复）：做了什么、文件清单、测试命令与结果（原样贴摘要）、跳过与原因、需要别的目录的改动、遗留问题。
