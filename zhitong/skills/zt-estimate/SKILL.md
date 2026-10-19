---
name: zt-estimate
description: 估算 / 概算编制（gsyz_v1 模板，9 张表、515 条公式）：从设计说明 / 可研抽 11 个规模量候选（不出数）→ 用户确认 → 指标基准正向推算成本位建议值与工程建设其他费建议 → 公式求值、四道拦截闸 → 写真 Excel 公式的概算 xlsx。金额全部由脚本计算，模型不算钱。
whenToUse: 用户要做投资估算 / 设计概算、按规模估总投资、出概算表，或问某项其他费（监理费、设计费…）的建议值时。
---

# 估算 / 概算

脚本：`zt.estimate`（零模型）。两段式：**抽取不出数，计算才出数**——你抽回来的规模量必须经用户确认才进计算。模板 `gsyz_v1` 是脱敏样本；费率规则 `fee_rules_zj2018.json`（浙江 2018 其他费用定额等 16 项）的签核状态是 `owner_release`「仓主默认放行，非造价员签署」，393 个转录数值未经造价员逐值核对；`勘察设计费` 档界闭开性未确认（CLOSURE_KNOWN_GAPS），该条金额单独扣留。随包指标基准是单一来源样本，只作单样本参考。偏离阈值 0.20 是未经造价员确认的占位值。

在项目根目录运行（数据路径相对项目根）。`<python>` 是解释器绝对路径：设置了 `$ZT_PYTHON` 就用它；否则调用 `load_workspace_dependencies`，用返回的 `python`（桌面版内置 Python）；都没有才用 `python3`。命令里的 scripts/ 路径相对本 skill 目录，写成绝对路径；PowerShell 里写 `& "<python>" …`。脚本报 `zt_not_importable`（退出码 2）时把 `message` 与 `hint` 告诉用户，不要换解释器硬跑。工作目录 `工作/<YYYY-MM-DD>-概算/`。

## 1. 抽规模量（两半）

读 `项目说明.md` 找设计说明 / 可研 / 经济技术指标表；扫描件无旁车先 `read_image` 看图写旁车。

```sh
<python> scripts/estimate.py extract_prepare --files 资料/可研报告.pdf 资料/建施说明.docx \
  --project-name "<项目名称，含标段>" --out 工作/2026-10-19-概算/extract/
```

产物：`概算抽取说明.md`（规则、单体清单、总量、逐格口径与同义词）、每份正文 `概算抽取正文-NN.txt`（文件头有 `file_id`；超 12000 字时是按关键词取的窗口）。读完说明再逐份读正文，按说明作答写进 `工作/<日期>-概算/extract_answers.json`：

```json
{"files": [{"file_id": "资料/可研报告.pdf",
  "buildings": [{"name": "1#楼", "level": "above_ground", "function": "住宅", "area": "5000", "quote": "1#楼 住宅 5000"}],
  "checks": {"gross_building_area": [{"value": "30000", "quote": "总建筑面积 30000 ㎡"}]},
  "cells": {"经济技术指标!D4": [{"value": "1.2万", "quote": "总用地面积 1.2万平方米", "scope": "partition"}]}}]}
```

只抄原文、不换算不推算；`quote` 逐字可在正文找到、≤40 字；一格多个不同值全列；面积为空的单体也列（area 给 null）；**严禁写任何金额**。

```sh
<python> scripts/estimate.py extract_finalize --prepare 工作/2026-10-19-概算/extract/result.json \
  --answers 工作/2026-10-19-概算/extract_answers.json --out 工作/2026-10-19-概算/extract_final/
```

脚本做：数值解析（万 / 亿倍率由代码乘）、引文回原文核（`confidence` 1.0 = 引文在原文且值在引文里；`mapping=semantic` 是凭语义对上的格）、单体按出现顺序归位固定槽位（超出落 `unmapped_building`）、槽位合计与原文总面积差 >1% 出 `area_total_mismatch`、建筑密度只作占地推算提示（`derived`，不进候选）、项目名带标段而总量没注明本标段时出 `scope_whole_site_suspect`。

## 2. 用户确认

把 `candidates`（值、引文、置信）、`unresolved`（not_found / ambiguous 列出全部候选 / total_only_no_partition / unmapped_building）、单体归位逐项用 `ask_user_question` 请用户确认或改值。**只有用户确认过的数才进计算**；`derived` 推算值要用户点头才填，来源记 `derived`。11 个必填位：D4 用地面积、D7/D8 地下室、D10–D12 地上单体、D13 构筑物、D15/D16 占地、D19/D20 地面 / 地下机动车位（均在「经济技术指标」表）。

## 3. 正向推算（可选，零模型）

请求 `工作/<日期>-概算/suggest_request.json`：`{"inputs": {确认过的格: 数}, "dims": {...}, "fee_bases": {"工程费用": 万元}, "fee_attrs": {...}}`。

```sh
<python> scripts/estimate.py suggest --in 工作/2026-10-19-概算/suggest_request.json \
  [--baselines 知识库/指标基准.json] --out 工作/2026-10-19-概算/suggest/
```

不给 `--baselines` 时用随包样本基准（会出 `baselines_default_sample`）。产物 `suggestions`（中位数 × 规模，带回链与区间）、`fee`（其他费建议）、`required_fee_bases` / `required_fee_attrs`（还缺哪些计费基数与属性，按它们问用户）。建议值逐条给用户采纳或覆盖，不自动写入。

## 4. 计算与出表

请求 `compute_request.json`：`inputs`（用户确认的全部格）、可选 `rates`（`reserve_rate` 预备费率，默认 5%，3–8% 外只告警）、`area_checks`、`acknowledged_checks`（`[{code, reason}]`，用户确认面积差异的理由）、`slot_labels`（槽位格 → 单体名）、`input_sources`（每格来源 user / extract / fee_rules…）、`fee_bases`、`fee_attrs`、`project_profile`、`project_name`、`generated_at`（固定它则两次出表逐字节一致）。

```sh
<python> scripts/estimate.py compute --in 工作/2026-10-19-概算/compute_request.json --out 工作/2026-10-19-概算/
```

拦截闸顺序固定：必填 → 面积闸 → 面积对账（可带理由确认放行）→ 全零。被拦时 `status=insufficient`，`status_reason` 是闸的码，`data.detail` 原文转述给用户并按它补输入。通过后 `概算.xlsx`：499 条真公式、费率独立在 `估概算总表!J46`、末页「生成说明」；`quality.review_level` 非 ok 时标题带【草稿】/【需复核】，信封 `status_reason` 也是它。

模板元数据（行树、输入位、告警码中文名）：`<python> scripts/estimate.py template`。

## 5. 汇报与纪律

- 如实转述 `status`、`status_reason` 与 `warning_items`（warn 逐条，info 合并）；告警中文名与处理建议在 `template` 的 `code_dictionary` 里。
- 七项合计（工程费用、其他费、预备费、静态 / 动态总投资…）照抄 `totals`，不自己加减；说明 `input_coverage`（150 个成本位填了几个）。
- `needs_manual: true`：所有金额、数量都是待复核初稿。费率建议要提签核状态（owner_release，非造价员签署）与 `勘察设计费` 扣留。
- 不在抽取阶段说出任何金额；不替用户选 ambiguous 的值。
- 退出码 2 是调用错误（字段不合法、bool 当数、模板不存在、回答形状不对），按 `error.message` 修正。
- 落盘：`extract/`、`extract_answers.json`、`extract_final/`、请求 JSON、`result.json`、`概算.xlsx`、`待确认清单.md`（未确认的格、面积差异、需复核理由）。确认后 `tos_push` 到 `成果/`。抽取说明原文与版本见 `references/抽取说明原文.md`。
