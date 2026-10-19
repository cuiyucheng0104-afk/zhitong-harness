---
name: zt-reconcile
description: 送审计价表与审定计价表逐行核对（结算审核、进度款审核、审定单复核）：定位两张表、预检、脚本核对、工作底稿 xlsx 落到项目 工作/，再口头汇报核减核增。金额全部由脚本取数计算，模型不算钱。
whenToUse: 用户要对比送审与审定（或报审与审核）计价表、统计核减额与核减率、查哪些清单项被调整、仅送审或仅审定时。
---

# 送审与审定核对

脚本：`zt.reconcile`（零模型，确定可复算）。金额、数量都由脚本从表格取数并计算；你负责找对文件、解释结果、把需要人确认的事项问清楚。

## 1. 定位两张计价表

1. 读项目根目录的 `项目说明.md`，按「关键文件指引」找「送审计价表」「审定计价表」。
2. 指引里没有、或同一角色有多个候选：列 `资料/` 下的 `.xlsx/.xlsm`，先预检，再把候选（文件名 + 预检标签 + 表头期次）列给用户，用 `ask_user_question` 问定送审是哪份、审定是哪份。不要凭文件名猜。
3. 文件在桶里时先 `tos_pull` 到本机缓存，用本机路径调用脚本。

预检（只看是不是计价表，不读金额）：

```sh
<python> scripts/probe.py probe --files 资料/a.xlsx 资料/b.xlsx
```

`kind=costsheet` 才是计价表；`other` 是读过但没有清单表头；`unknown` 看 `reason`。

- `.xls`：本机不转换，请用户用 Excel/WPS 另存为 `.xlsx` 后再给。
- 广联达原生工程文件 `.gbq*/.gtj/.gcl` 读不了，请用户从广联达导出 Excel。

## 2. 运行核对

工作目录 `工作/<YYYY-MM-DD>-核对/`（同一天再做一次用 `-核对-2`）。

```sh
<python> scripts/reconcile.py run \
  --submitted 资料/送审.xlsx --approved 资料/审定.xlsx \
  [--basis auto] --out 工作/2026-10-19-核对/
```

- `<python>` 是解释器绝对路径：设置了 `$ZT_PYTHON` 就用它；否则调用 `load_workspace_dependencies`，用返回的 `python`（桌面版内置 Python）；都没有才用 `python3`。命令里的 scripts/ 路径相对本 skill 目录，写成绝对路径；PowerShell 里写 `& "<python>" …`。脚本报 `zt_not_importable`（退出码 2）时把 `message` 与 `hint` 告诉用户，不要换解释器硬跑。
- `--basis`：`auto`（有本期列比本期，否则比合价，默认）/ `current` 本期 / `cumulative` 累计 / `contract` 合同价。进度款表先用 `auto`；结果提示口径问题时按提示换。
- 也可 `--in request.json`：`{"submitted_file": 路径或 {"path","file_id","file_name"}, "approved_file": …, "basis": "auto"}`。
- stdout 只有一行摘要 `{status, status_reason, warning_items, out}`；完整结果在 `<out>/result.json`，底稿 `<out>/核对结果.xlsx`（汇总、逐行核对、按章汇总）。
- 退出码 2 是调用错误（文件不存在、超过 60 份 / 300 MB、参数不对）：stdout 是 `{"error": {code, message, hint}}`，按 hint 修正后重跑。

## 3. 读结果

`result.json` 是 `{status, status_reason, coverage, warning_items, data}`。先看 `status` 与 `warning_items`，再看 `data.summary` 与 `data.chapters`。`data.rows` 可能上千行：不要整份读进对话，用脚本按 `status` 过滤（`调整` / `仅送审` / `仅审定` / `待核实`）并按 `diff` 绝对值取前 20 行。

`data.summary` 关键字段：`a_total` 送审合计、`b_total` 审定合计、`adjust_amount` 核减额（正 = 审减，负 = 审增）、`adjust_rate` 核减率（核减额 / 送审合计）、`count_same / count_changed / count_only_a / count_only_b / count_uncertain`、`diff_by_qty` 量差、`diff_by_price` 价差、`basis_label` 两侧实际取数口径、`coverage_ok`。

逐行 `status`：`一致`（差 ≤ 1 分）、`调整`、`仅送审`（审定侧没对上，可能是审减删项）、`仅审定`（可能是审增新增）、`待核实`（某一侧合价没取到，不按 0 算）。`matched_by` 是匹配依据（编码 / 名称特征）。

## 4. 汇报

1. 结论一句：送审合计、审定合计、核减额、核减率，全部引用 `summary` 原值并写明「脚本取数，需人工复核」。
2. 按章：核减额绝对值最大的 3–5 章。
3. 主要调整项：核减额最大的若干行，带「送审位置 / 审定位置」（文件、表、行）。
4. 量差与价差各多少；`calc_flags` 里的「计算错误」行单独点出。
5. 状态与告警（见下节）。

## 5. 结果纪律

- 如实转述 `status`：`ok` 可以给结论；`partial` 必须说哪些没算进去（看 `warning_items` 与 `coverage.skipped`），并说明结论不完整；`insufficient` 不给任何金额结论，转述 `data.detail.message` 与告警 `hint`，告诉用户下一步。
- `warning_items` 全部转述：`error` 逐条说，`warn` 逐条说，`info` 可合并一句。告警码含义与旧界面说法对照见 `../_shared/costsheet/告警码.md`。
- `needs_manual: true`：所有金额、数量都要标注需人工复核；不要把脚本结果说成审定结论。
- 不自己算钱：不对金额做加减乘除、不换算比例；需要的数都在 `summary` / `chapters` / `rows` 里。没有的数就说没有。
- 引用只指向读过的内容：行定位只用 `rows[].submitted_sheet/submitted_row/approved_sheet/approved_row`。
- `amounts_identical_suspect`、`all_rows_identical`、`same_file_*`：多半是文件或口径选错，先和用户确认再汇报结论。

## 6. 落盘

`工作/<日期>-核对/` 下：

| 文件 | 内容 |
|---|---|
| `result.json` | 脚本完整结果（不要手改） |
| `核对结果.xlsx` | 工作底稿 |
| `待确认清单.md` | 需要用户确认的事项：口径选择、`待核实` 行、error 级告警、选错文件的嫌疑；每条写来源（文件、表、行或告警码） |

整个目录用 `tos_push` 推回桶内同一项目的 `工作/`。正式审定单或报告进 `成果/` 由 zt-report 负责。
