---
name: zt-indicator
description: 由计价表算造价指标：总造价口径、单方造价、各章占比与单方、造价驱动项、费用构成，并可与同类项目（案例索引）对标。金额全部由脚本取数计算，模型不算钱。
whenToUse: 用户要算单方造价、专业/章节占比、造价构成，或要把本项目与公司历史同类项目对标时。
---

# 造价指标与对标

脚本：`zt.indicator`（零模型）。指标按合同价口径解析计价表；国标编码行不到一半的表（万元估算表、审核汇总表）不参与。

## 1. 准备输入

1. 读 `项目说明.md`：「关键文件指引」里的计价表（控制价、预算、结算的分部分项计价表；多个单体可以一起给），以及总建筑面积、业态、结构。
2. 计价表不明确时：列 `资料/` 下的 `.xlsx/.xlsm` 并预检（`"$ZT_PYTHON" -m zt.costsheet.cli probe --files ...`，或 `../zt-reconcile/scripts/probe.py probe ...`），把候选列给用户用 `user-questions` 确认。`.xls` 请用户另存为 `.xlsx`。
3. 总建筑面积：只用项目说明或资料里写明的数，并记下出处（`--area-source` 写来源，例如「项目说明」「设计说明第 3 页」）；找不到就问用户，不要估。
4. 用户给了含税总造价时用 `--total-amount`，否则脚本按「费用表合计 → 清单明细合计」取。

## 2. 运行

工作目录 `工作/<YYYY-MM-DD>-指标/`。

```sh
"$ZT_PYTHON" -m zt.indicator.cli run --files 资料/6号楼.xlsx 资料/7号楼.xlsx \
  --gross-area 12000 --area-source 项目说明 [--total-amount 50000000] [--baseline 工作/2026-10-19-指标/对标.json] \
  --out 工作/2026-10-19-指标/
```

- `$ZT_PYTHON` 未设置时用 `python3`；等价写法 `scripts/indicator.py run ...`（相对本 skill 目录）。
- 也可 `--in request.json`：`{"price_files": [...], "gross_area", "area_source", "total_amount", "baseline"}`。
- stdout 一行摘要；完整结果 `<out>/result.json`，底稿 `<out>/指标结果.xlsx`（汇总、指标、按章、造价驱动项、未计入文件）。
- 退出码 2 是调用错误（文件不存在、超上限、参数不对），按 `error.hint` 修正。

## 3. 对标（可选）

对标数据来自桶根的 `案例索引.md`（zt-archive 维护）。挑业态相同或相近的项目，把每行**原样抄出**的字段写成 `对标.json`：

```json
{"building_type": "住宅", "structure": "剪力墙", "project_id": "2026-007",
 "peer_library": [{"project_id": "2025-031", "name": "某小区二期", "building_type": "住宅",
                   "structure": "剪力墙", "gross_area": 15000, "unit_cost": 2650.5}],
 "indicator_baselines": {"unit_cost": 2700}}
```

- `peer_library` 的数值只能抄案例索引里写着的，缺就不填该项目；不要换算口径。
- `indicator_baselines` 是用户直接给的对标值（`{指标编码: 值}`）。
- 结果里 `peer_avg_unit_cost` 一行是同类均值与偏差（同类对标一律按明细合计口径单方，`avg_sample_count` 是参与均值的项目数）。

## 4. 读结果与汇报

`data.summary`：`cost_basis` ∈ `user_input`（用户录入）/ `fee_table`（取自费用表）/ `itemized`（清单明细合计，**不是总造价**）、`cost_basis_label`、`cost_basis_notes`、`cost_basis_missing`（回落时没算进去的部分）、`total_amount`、`parsed_total`、`gross_area`、`unit_cost`。

`data.indicators`：`total_amount`、`parsed_total`、`unit_cost`、`unit_cost_itemized`、`chapter_pct:<章码>`、`chapter_unit_cost:<章码>`、`peer_avg_unit_cost`；每行的 `label` 已写明口径，汇报时照用 `label`。

汇报：

1. 总造价（或清单明细合计）与口径标签；`itemized` 时必须说「这是清单明细合计，不含 `cost_basis_missing` 里的部分，不是总造价」。
2. 单方：值、面积及其来源；没有面积时说未计算。
3. 占比最高的几章（`chapters` 已按金额降序）与造价驱动项前几名。
4. 费用构成：`fee_breakdown.available` 为 false 时转述 `reason`，不要自己拆。
5. 对标偏差（如有）与样本数。
6. 未计入文件 `files_failed` 与告警。

## 5. 结果纪律

- 如实转述 `status`：`partial` 说清哪些文件或表没算进去、结果不完整；`insufficient`（全部文件不可计入、可计入的不到一半、`.xls`）不给指标，转述 `data.detail.message` 与 `hint`。
- `warning_items` 全部转述：`error`、`warn` 逐条，`info` 可合并。告警码与旧界面说法对照见 `../_shared/costsheet/告警码.md`（「指标计算」对话框里的面积 = `--gross-area`，「含税总造价」= `--total-amount`）。
- `needs_manual: true`：所有金额、单方、占比都要注明是脚本取数、需人工复核。
- 不自己算钱：不手算单方、占比、偏差；脚本没给的数就说没有。
- 引用只指向读过的内容：面积、对标值写明出处。

## 6. 落盘

`工作/<日期>-指标/` 下：`result.json`、`指标结果.xlsx`、`对标.json`（如有）、`待确认清单.md`（面积来源待确认、口径回落、未计入文件、error 级告警）。用 `tos_push` 推回桶。归档时 zt-archive 会把关键指标写进案例索引。
