---
name: zt-project
description: 开项目与资料盘点：读项目说明；新项目分配编号 YYYY-NNN 并登记案例索引；没有项目说明的目录按目录结构生成草稿；按资料清单盘点缺件（只报缺件，不给文件打标签）。
whenToUse: 用户要新建项目、打开某个已有项目、问「资料齐不齐 / 缺什么」时；做任何项目工作之前，先用本 skill 读项目说明。
---

# 开项目与资料盘点

脚本都在本 skill 的 `scripts/`（零模型）。运行方式：`"${ZT_PYTHON:-python3}" scripts/<x>.py <子命令> ...`（`ZT_PYTHON` 未设置时用 `python3`）。stdout 只有一个 JSON；`status` 与 `warning_items` 要如实转述给用户，`error` 按 `hint` 修。本机缓存根默认 `~/zhitong`（Windows `%USERPROFILE%\zhitong`），与桶同构，`tos_pull` 返回的路径就是本机路径。

## 1. 打开已有项目

1. `tos_ls 项目/` 找目录。用户只给了工程名时按名字匹配；有多个候选就列出来问，不要替他选。
2. `tos_pull 项目/<目录>/项目说明.md`，再 `scripts/project_doc.py show --file <本机路径>`。
3. 向用户转述：编号、工程名、咨询类型、阶段、关键文件指引、已出成果。
   - `status=insufficient`（`project_doc_incomplete`）：必填字段缺失或还是「待确认」。问用户后直接改项目说明的 YAML 头，再继续，不要猜。
   - 项目说明不存在：见 §3。
4. 后续要读哪份资料，按「关键文件指引」里的路径 `tos_pull` 单份文件；不要整目录拉取，更不要拉图纸（`tos_pull` 目录拉取默认跳过图纸）。

## 2. 新开项目

1. `tos_pull 案例索引.md`（要最新的）。桶里还没有时跳过，脚本会按模板新建。
2. 用 `user-questions` 问清：工程名称、咨询类型（全过程造价咨询 / 结算审核 / 招标控制价编制）、阶段（概算 / 招标控制价 / 施工过程 / 结算 / 审定）；业态、规模、客户合同号可选。
3. 先算号：`scripts/new_project.py allocate --index <本机案例索引> --name <工程名> --known <tos_ls 项目/ 看到的目录名>`，把编号和目录名告诉用户确认。
4. 建项目：`scripts/new_project.py create --index ... --root <缓存根> --name ... --consulting-type ... --stage ... [--business --scale --alias --known]`。
5. **立刻** `tos_push` 结果里 `files_to_push` 的两个文件（项目说明、案例索引）。编号推送后才算占住；回读提示 `remoteChangedSincePull` 时，说明别人同时改了案例索引：重新 `tos_pull` 案例索引，删掉本机新建的项目目录，回到第 3 步重新分配。

编号规则：`YYYY-NNN` = 建项目年份 + 当年三位流水号，取案例索引与桶内 `项目/` 目录里当年最大值加一，不补空洞，跨年归零。目录名 `<编号>-<工程名>`，工程名去掉空格与 `/\:*?"<>|`。客户自己的合同号写进项目说明的「别名」，不进目录名。

## 3. 没有项目说明的项目

迁移来的或手建的目录：`tos_pull` 项目目录里要用到的文件到本机（至少让目录结构在本机可见），然后
`scripts/project_doc.py draft --project-dir <本机项目目录> [--consulting-type ... --stage ...]`。

草稿从目录名取编号与工程名，从目录结构生成「目录概览」，在「关键文件指引」里按文件名规则填候选路径（备注「按文件名判断，待确认」）。必须做的：咨询类型和阶段问用户；候选路径逐个打开核对，核对过才去掉「待确认」；然后 `tos_push` 项目说明。草稿不会覆盖已有的项目说明。

## 4. 资料盘点

只看文件名和目录，不读内容，不给文件打标签、不把分类结果写进任何文件。

1. 取文件名单（图纸不用拉到本机）：`tos_ls 项目/<目录>/` 带 `recursive` 翻页列全，把每个 `path` 一行一个写到 `工作/<日期>-盘点/文件清单.txt`。本机已有完整副本时可改用 `--project-dir`。
2. 运行：
```sh
scripts/inventory.py scan --listing 工作/2026-10-19-盘点/文件清单.txt \
  --project-doc <本机项目说明> --out 工作/2026-10-19-盘点/result.json
```
   咨询类型与阶段缺省读项目说明；**阶段不猜**：两处都没有就先问用户，`--all-stages` 只在用户明确要求全部阶段时用。
3. 读结果并转述（完整结果在 `result.json`，stdout 只有摘要，需要明细时读那个文件）：
   - `summary`：必备项总数 / 已备 / 待确认 / 缺失，`coverage_rate` 与上限 `coverage_rate_upper`。比率为 `null` 时没有比率，不要报成 0 或 100%。
   - `missing`：必备但没找到的资料，直接告诉用户缺什么；`advisory` 是重要但缺的，只提示。
   - `pending`：只有弱证据（文件名只有裸词、靠目录语境推断）。**打开候选文件确认**后才能说已备，没确认之前只能说「疑似」。
   - `unclassified_files`：文件名和目录判不出类目的文件。**报缺件前先看这些**，缺的资料可能就叫「新建文本文档」；扫描件用 `read_image` 看。
   - `status=insufficient`（`no_categorized_files`）：一个文件都判不出，缺件清单不可信，不要当成「全缺」。
4. 把结论写进项目说明的「资料盘点」小节：日期、依据的咨询类型与阶段、缺件、待确认事项；`tos_push` 项目说明。

## 纪律

- 清单与分类规则是旧系统迁来的数据，整体**待签核**（`data/` 各文件头写着签核状态）。对客户不要说「按客户确认的清单」。需要改口径就改 `data/` 里的文件，不要在对话里临时改。
- 盘点没读内容：「文件名叫结算审定单」不等于它真是审定单。需要核实就打开。
- 脚本报错 `stage_required`、`invalid_consulting_type`、`unknown_stage` 时，问用户，不要换个参数硬跑。
- 路径一律用项目内相对路径、`/` 分隔；中文和空格路径是正常的。

## 文件

| 路径 | 用途 |
|---|---|
| `scripts/inventory.py` | `scan` 资料盘点 |
| `scripts/new_project.py` | `allocate` 算编号，`create` 开项目（分配逻辑在此文件，可改） |
| `scripts/project_doc.py` | `show` 读项目说明，`draft` 生成草稿 |
| `templates/项目说明.md`、`templates/案例索引.md` | 两份桶内入口文件的模板（占位符 `{{字段}}`） |
| `data/checklist.yaml` | 资料清单（3 套，36 项）、阶段码表、咨询类型 |
| `data/classify_rules.yaml` | 文件名分类规则（235 行） |
| `data/doc_category_map.yaml`、`data/audit_evidence_rules.yaml` | 类目折算表、证据冲突表 |
| `references/inventory.md` | 判定顺序、证据级别、清单口径 |
