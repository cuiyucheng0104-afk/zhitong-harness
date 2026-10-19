---
name: zt-tk
description: 投资控制（跟踪审计）异常检测：对送审计价表跑规则检测重复计取、暂估价、量价不自洽、大额，以及对照合同/中标清单的单价超合同、量超合同、漏报、合同外新增；再逐条与用户对话复核，决定追加到 复核.jsonl。引擎只给疑似，终判归造价师。
whenToUse: 用户要做投控检测、进度款/结算的异常排查、对照合同清单查超量超价，或要逐条复核已检出的异常时。
---

# 投控异常检测与复核

脚本：`zt.tk`（零模型）。规则阈值在随包的 `tk_detect.yaml`（版本 `v1-20260711`，**客户侧仍为 draft**，不是已与客户核对确认的值）。每条异常都只是「疑似」，`review_status` 恒为 `pending`，结论由用户逐条复核决定。

## 1. 准备输入

1. 读 `项目说明.md`：「关键文件指引」里的送审计价表（本期进度款或结算送审，可多份），以及合同/中标清单。
2. 不明确时列 `资料/` 下的 `.xlsx/.xlsm` 并预检（`"$ZT_PYTHON" -m zt.costsheet.cli probe --files ...`），把候选列给用户用 `user-questions` 确认哪些是送审、哪份是合同清单。`.xls` 请用户另存为 `.xlsx`。
3. 没有合同/中标清单也能跑：只跑 v1 规则（重复计取、暂估、行内自洽、大额），`rules_skipped` 会写 `baseline_not_provided`。

## 2. 检测

工作目录 `工作/<YYYY-MM-DD>-投控/`。

```sh
"$ZT_PYTHON" -m zt.tk.cli detect --files 资料/第5期送审.xlsx \
  [--baseline-files 资料/中标清单.xlsx] [--basis auto] --project-id 2026-007 \
  --out 工作/2026-10-19-投控/
```

- `$ZT_PYTHON` 未设置时用 `python3`；等价写法 `scripts/tk.py detect ...`（相对本 skill 目录）。
- `--project-id` 用项目编号：它进入每条异常的 `anomaly_id`，同一行清单在不同轮次检测里身份不变。
- `--basis`：送审文件的期次口径，`auto`（默认）/ `current` / `cumulative` / `contract`。
- `--rules` 可换用另一份阈值 YAML（用户明确要求调阈值时才用，并在汇报里说明用了哪份）。
- 完整结果 `<out>/result.json`，底稿 `<out>/投控异常.xlsx`（汇总、异常清单、对不准的行）。退出码 2 是调用错误，按 `error.hint` 修正。

## 3. 读结果与汇报

`data.anomalies[]`：`type` 规则、`anomaly_type` 中文类别、`confidence_tier`、`item_code/item_name`、`line_amount` 送审金额、`excess_amount` 疑似超出部分、`detail` 证据文案、`source_file/sheet/row` 定位、`anomaly_id`。已按严重度排序。

规则：`duplicate` 重复计取、`code_repeat` 编码重复（数据质量）、`zangu` 暂估/暂定/暂列、`self_check` 量×价≠合价、`big_amount` 大额粗筛（置信最低）、`price_over_baseline` 单价超合同、`qty_over_baseline` 量超合同、`missing_submit` 漏报、`new_item` 合同外新增。

另看：`alignment_issues` / `align_suggestions`（与合同清单对不准、需要人工指定合同行，不带金额）、`baseline.status`（not_provided / provided / invalid）、`rules_skipped`（哪些规则没跑、为什么）、`scope_label`。

汇报：总条数与按规则分布 → 置信高的前若干条（带 `detail` 与定位）→ 对不准的行 → 没跑的规则与原因 → 告警。`coverage.rows_parsed` > 0 且 0 条异常才可以说「本轮未检出异常」。

## 4. 逐条复核

按严重度顺序与用户逐条过（一次 3–5 条）：给出 `detail`、定位，必要时打开原表那一行核对；用户判断后追加决定：

```sh
"$ZT_PYTHON" -m zt.tk.cli review --result 工作/2026-10-19-投控/result.json \
  --log 工作/2026-10-19-投控/复核.jsonl --anomaly-id <anomaly_id> \
  --state confirmed|dismissed|pending --reason "依据……" [--reviewer 张工]
"$ZT_PYTHON" -m zt.tk.cli progress --result 工作/2026-10-19-投控/result.json --log 工作/2026-10-19-投控/复核.jsonl
```

- `confirmed` 确认异常，`dismissed` 判为误报，`pending` 撤回为待复核；理由必填，写明依据（对照了哪份文件哪一行）。
- `复核.jsonl` 只追加，不手改；改判就再追加一条。决定只能来自用户，不要替用户判。
- 每次 `review` 返回 `progress`（各状态条数与仍待复核的 ID），据此告诉用户还剩多少。
- 重新检测（换文件或口径）写到新的工作目录；`anomaly_id` 稳定，可以对照旧目录的 `复核.jsonl` 带过已复核的结论，但要向用户说明哪些证据变了。

## 5. 结果纪律

- 如实转述 `status`：`partial` 说清哪些表或文件没算进去；`insufficient`（送审全部读不出、全部无价、口径问题、`.xls`）不给检测结论，转述 `data.detail.message` 与 `hint`。
- `warning_items` 全部转述：`error`、`warn` 逐条，`info` 可合并。告警码与旧界面说法对照见 `../_shared/costsheet/告警码.md`。
- 疑似不是结论：汇报用「疑似」「需复核」，不要写成「存在重复计取」。
- `needs_manual: true`：金额都要注明需人工复核；不自己计算超出金额或合计。
- 阈值是 draft：用户问「为什么这条算大额」时，说明阈值来自 `tk_detect.yaml` 版本号与具体门槛（`rules_version`、异常的 `threshold`）。

## 6. 落盘

`工作/<日期>-投控/` 下：`result.json`、`投控异常.xlsx`、`复核.jsonl`、`待确认清单.md`（对不准需人工指定合同行的清单项、error 级告警、未复核条数）。每轮复核结束用 `tos_push` 推回桶。
