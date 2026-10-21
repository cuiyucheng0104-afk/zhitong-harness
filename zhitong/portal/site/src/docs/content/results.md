---
title: 结果状态与告警
slug: results
group: 参考
order: 1
summary: 结果里的状态、需人工确认标记、告警，以及脚本调用失败时的情况，帮您判断结果能不能用。
updated: 2026-10-20
sources:
  - zhitong/python/zt/common
  - zhitong/STATUS.md
---

## 这一页讲什么

核对、指标、投控、清单、概算、报告等能力的计算部分由脚本完成。每个脚本运行后输出一份结构相同的结果，助手按结果如实转述给您。本页说明结果里的状态、需人工确认标记、告警，以及脚本调用失败时的情况，方便您判断一次结果能不能用、缺了什么、下一步做什么。

CAD 看图是插件工具，不使用这套结果格式，见本页「CAD 看图的提示与拒绝」。

## 一份结果包含什么

每个脚本的完整结果写在工作目录的 `result.json` 里，包含：

| 字段 | 含义 |
|---|---|
| `status` | 状态：`ok` / `partial` / `empty` / `insufficient` |
| `status_reason` | 状态原因码，例如 `xls_unsupported`；`empty`、`insufficient` 必带 |
| `coverage` | 覆盖度：用了几份文件、读出多少行、哪些文件或表没有计入及原因 |
| `warning_items` | 告警列表，每条有码、级别、说明，可能有处理建议 |
| `data` | 结果数据 |
| `needs_manual` | 恒为 `true` |

脚本不会输出"成功但内容为空"的结果：`ok` 必须有数据；没有结果时用 `empty` 并写明原因。

## 四种状态

| 状态 | 界面中文 | 含义 | 助手必须怎么说 | 助手可以怎么说 |
|---|---|---|---|---|
| `ok` | 完成 | 输入齐全，结果完整 | 转述全部告警；金额、数量注明需人工复核 | 给出结论 |
| `partial` | 部分完成 | 有结果，但有文件、表或片段没算进去 | 说明缺了哪些（告警和 `coverage.skipped`），说明结论不完整；不把部分完成说成完成 | 给出已算部分的结果 |
| `empty` | 无结果 | 输入齐全，但没有可以给出的结果 | 转述原因码和原因 | 建议下一步 |
| `insufficient` | 资料不足 | 输入不足以给出结果：缺件、格式不对、口径有问题 | 不给任何金额结论；转述原因和处理建议，告诉您下一步 | — |

几点规则：

- `partial` 一定带覆盖度，并且至少有一条 `warn` 或 `error` 级告警说明缺在哪。
- 投控检测检出 0 条时，只有送审表读出了有金额的清单行（`coverage.rows_parsed` 大于 0），助手才会说"本轮未检出异常"。
- 概算计算的状态为 `ok` 时，`status_reason` 也可能写着质量结论 `draft` 或 `needs_review`，表示这是草稿或需复核的初稿。

### 常见的状态原因

| 原因码 | 状态 | 出现在 | 含义 |
|---|---|---|---|
| `items_not_counted` | partial | 核对、指标、投控 | 有 error 级告警：有表或文件没算进去 |
| `coverage_partial` | partial | 核对、指标、投控 | 可识别清单表的金额没有全部计入 |
| `coverage_poor` | partial | 核对、指标、投控 | 计入不到一半，结果不能作为结论 |
| `xls_unsupported` | insufficient | 核对、指标、投控 | 有 `.xls`，本机不转换；请另存为 `.xlsx` |
| `basis_not_found` | insufficient | 核对、投控 | 表头没有所选口径的金额列；改用 `auto` 或结果里列出的可用口径 |
| `column_ambiguous` | insufficient | 核对、投控 | 表头有多组金额列分不清；请指定合同、本期或累计 |
| `same_file_same_columns` | insufficient | 核对 | 送审、审定选了同一份文件，且没有两组金额列 |
| `parse_failed` | insufficient | 核对、指标、投控 | 读不出清单行、全部无价，或可计入的文件不到一半；原因在 `data.detail.message` |
| `no_source_files` | empty | 预检、资料盘点 | 没有可处理的文件 |
| `probe_budget_exhausted` | partial | 预检 | 预检时间用完，有文件没有预检；减少文件数后重试 |
| `out_of_scope` | empty | 清单框架 | 不是房屋建筑与装饰工程 |
| `no_practice` | empty | 清单框架 | 没有认出做法层 |
| `no_items` | empty | 清单框架 | 认出的层全部被排除、并入或降为待核，没有正式清单项 |
| `answers_incomplete` | partial | 清单框架 | 有片段没有分类回答 |
| `no_candidates` | empty | 概算抽取 | 没有抽到任何规模量候选 |
| `required_inputs_missing` | insufficient | 概算计算 | 11 个必填规模量有没填的 |
| `area_gate_failed` | insufficient | 概算计算 | 总建筑面积为空或 ≤ 0 |
| `area_total_mismatch` | insufficient | 概算计算 | 单体合计与原文总建筑面积相差超过 1%，且没有确认放行 |
| `all_zero_result` | insufficient | 概算计算 | 建设静态总投资为 0 |
| `no_readable_sources` | empty | 报告 | 本章或所选资料都读不出正文 |
| `too_little_content` | insufficient | 报告 | 去掉待补、待核标记后正文太短 |
| `mostly_todo` | insufficient | 报告 | 正文几乎全是【待补】 |
| `output_truncated` | partial | 报告 | 本章写到篇幅上限，没有写完 |

## 需人工确认

结果的最外层恒带 `needs_manual: true`；含金额、数量、单价、比率的对象也各自带这个标记。界面上显示为"需人工确认"徽标。

它的意思是：这些数由脚本按表格取数计算，或由程序从资料里读取，需要您复核。助手转述时会注明"脚本取数，需人工复核"，不会把脚本结果说成审定结论。

::: note
这个标记按字段名判断，个别计数字段（例如行数）也可能带上它。
:::

## 告警

### 一条告警的组成

| 部分 | 说明 |
|---|---|
| `code` | 告警码，小写英文加下划线，例如 `sheet_total_mismatch` |
| `level` | 级别：`error` / `warn` / `info` |
| `message` | 说明，通常点名文件、工作表或行 |
| `hint` | 处理建议（可能没有） |
| `evidence` | 出处（可能没有） |

### 三个级别

| 级别 | 含义 | 助手怎么转述 |
|---|---|---|
| `error` | 有东西没算进去或算不准 | 逐条说，并说明结果缺了哪块 |
| `warn` | 按降级方式处理了 | 逐条说 |
| `info` | 说明性信息 | 可以合并成一句 |

告警不会拦下计算；需要拦下的情况会以 `insufficient` 或调用失败结束。

### 旧界面说法对照

部分告警的处理建议沿用旧网页的说法。您在对话里直接告诉助手即可：

| 告警里的说法 | 对应的做法 |
|---|---|
| 「对比口径」 | 告诉助手按自动、合同、本期或累计取数 |
| 「指标计算」对话框里的总建筑面积 | 告诉助手总建筑面积及其出处 |
| 「含税总造价」 | 告诉助手含税总造价 |
| 「重新选择 / 分别选择文件」 | 告诉助手换哪份送审、审定或计价文件 |

## 计价表告警码（核对、指标、投控共用）

| 码 | 级别 | 含义 | 您可以怎么做 |
|---|---|---|---|
| `not_excel` | error | 不是 Excel 文件 | 计价表只支持 .xlsx / .xlsm（.xls 需另存）；不要选 Word、PDF |
| `xls_unsupported` | error | 旧版 .xls 不支持 | 用 Excel 或 WPS 另存为 .xlsx 后再试 |
| `xlsx_unreadable` | error | 无法读取 xlsx | 用 Excel 或 WPS 另存为 .xlsx 后再试 |
| `stylesheet_patched` | info | 样式表已补名 | 单元格样式缺名称，已在内存里补名后读取，数据不受影响 |
| `stylesheet_dropped` | warn | 样式表已忽略 | 样式表损坏，已忽略样式；日期列可能显示为数字 |
| `no_items` | error | 没有读出清单行 | 确认选的是分部分项清单与计价表（表头有项目编码、名称、合价），或审核汇总表（表头有报审、审核、核减金额） |
| `file_unpriced` | error | 没有单价和金额 | 疑似招标工程量清单（只有工程量），已剔除，不参与金额计算 |
| `sheet_truncated` | warn | 工作表超长已截断 | 单表超过 8,000 行，只取前 8,000 行 |
| `sheet_skipped_has_items` | error | 有清单的表被跳过 | 该表含清单编码或标题像计价表，但表头没认出来或口径有歧义，金额未计入 |
| `sheets_skipped_by_title` | info | 按标题跳过的表 | 封面、说明、费用表、工日 / 台班 / 材料一览表等非清单表不计入 |
| `measure_sheets_skipped` | warn | 技术措施表没有参与 | 施工技术措施项目综合单价计算表按所选口径读不出或版式认不出；措施项请人工核对 |
| `sheets_skipped_non_list` | info | 非国标清单表已排除 | 国标编码行不到一半的表（如万元估算表）不参与指标计算 |
| `column_ambiguous` | error | 金额列口径有歧义 | 表头有多组金额 / 工程量列；请指定合同、本期或累计 |
| `basis_not_found` | error | 表头没有所选口径的金额列 | 把对比口径改为自动 |
| `party_columns_missing` | warn | 没有对应当事方的列 | 表头分了送审 / 审核列，但没有本侧要的那一组，已按不带当事方的列取数 |
| `amount_scaled_wan` | info | 万元已换算为元 | 表头标注「万元」，金额与单价已乘以 10,000 |
| `audit_summary_format` | info | 按审核汇总表解析 | 表头有成对的报审 / 审核 / 核减金额列，按审核汇总版式解析 |
| `sheet_total_mismatch` | error | 合计对不上 | 明细行之和与该表合计行偏差超过 0.5%：可能漏行，或多算了标题、小计行 |
| `measure_sheet_unreconciled` | error | 技术措施表对不上，未计入 | 措施综合单价计算表的清单项之和与同一单位工程费用表的「施工技术措施项目」相差超过 1 元（没有费用表时与本表合计行比），整张没有计入；请人工核对 |
| `summary_detail_mismatch` | error | 汇总表与明细表对不上 | 汇总表只用于勾稽、不计入；两者之和偏差超过 0.5% |
| `summary_only` | info | 只有汇总表 | 工作簿里没有明细表，已按汇总表计入 |
| `cross_sheet_dedup` | info | 跨表重复行已去重 | 不同工作表里编码、名称、金额完全相同的行只计一次 |
| `coverage_partial` | warn | 部分清单表未计入 | 可识别清单表的金额没有全部计入，见各表状态 |
| `coverage_poor` | error | 覆盖率不足 | 可识别清单表的金额计入不到一半，结果不可作为结论 |
| `chapter_coverage_low` | info | 章名覆盖率低 | 来自标准章名表的金额不到 80%，其余归入补充项目 / 无编码项 / 非国标编号项 |
| `amounts_identical_suspect` | error | 两侧金额疑似取成同一列 | 匹配行里 95% 以上两侧金额逐分相同，且表头有多组金额列；请确认对比口径 |
| `same_file_two_sides` | info | 两侧是同一份文件 | 表头同时有送审、审定两组金额列，已按两组列分别取数；审核对比表这样选是正确用法 |
| `same_file_sheets_excluded` | error | 同一列金额的表未参与对账 | 这些表没有分送审、审定两组金额列，同一份文件放两侧必然全部一致，已剔除；请分别选择送审文件和审定文件 |
| `all_rows_identical` | warn | 全部一致 | 两份文件每一行金额逐分相同、核减额为 0；可能是合法结果，也可能是审定文件选错了 |
| `calc_error_rows` | warn | 行内量×价≠合价 | 已在对应行标记「送审计算错误 / 审定计算错误」；差额可能来自算术错误而不是量价调整 |
| `baseline_rows_invalid` | error | 合同基准行不可用 | 基准行既没有清单编码也没有名称，无法严格对齐；超合同、漏报、合同外新增比对本轮未做 |
| `baseline_file_unparsed` | error | 合同 / 中标清单未解析出清单行 | 该文件没有参与超合同、漏报、合同外新增比对；请确认选的是合同或中标清单（分部分项计价表） |
| `baseline_coverage_low` | warn | 合同基准覆盖率低 | 送审行里能严格对齐到合同清单的不到一半，本轮不判合同外新增（大多是没对上，不是真新增） |
| `baseline_conflicts` | warn | 需要人工指定合同行 | 编码相同但名称或单位不同，或合同清单里有多行可对；不出金额，列为待人工指定 |
| `files_failed` | error | 部分文件未计入 | 这些文件读不出清单或不是清单表，结果只含其余文件 |
| `file_duplicate` | warn | 重复文件已剔除 | 两份文件内容完全相同（sha256 一致），只计一份 |
| `file_overlap_suspect` | warn | 疑似重复清单 | 两份文件的清单行 90% 以上完全相同；同构楼栋可能确实同清单，未自动剔除，请确认没有重复选 |
| `area_missing` | warn | 未提供建筑面积 | 没有总建筑面积，单方造价与各章单方未计算；请告诉助手总建筑面积 |
| `fee_total_unavailable` | info | 没有费用表合计 | 所选文件里没有费用表，只算出清单明细合计，不是总造价；可以提供含税总造价 |
| `fee_total_unreadable` | warn | 费用表合计未采用 | 有费用表，但合计没读到，或与各单位工程费用表之和相差超过 1 元；结果是清单明细合计，不是总造价；可以提供含税总造价 |
| `fee_breakdown_unreconciled` | info | 费用构成表未显示 | 单位工程费用表六项（分部分项、技术措施、组织措施、其他项目、规费、增值税）相加与合计相差超过 1 元；总造价取数不受影响 |
| `fee_itemized_mismatch` | warn | 费用表与清单对不上 | 费用表里的分部分项工程费（或施工技术措施项目）与读入的清单合计相差超过 1 元：可能有清单行没读进来，也可能费用表不是按这份清单算的 |

## 其他能力的告警与原因

### 计价表预检

预检只回答"是不是计价表"，不读金额。每份文件一个标签：

| 标签 | 含义 |
|---|---|
| `costsheet` | 至少一张表认出了清单表头 |
| `other` | 读完了，没有清单表头（`no_list_header`） |
| `unknown` | 没读或没读完，原因见下 |

| 原因码 | 说明 |
|---|---|
| `xls` | 旧格式 .xls，未预检；请用 Excel / WPS 另存为 .xlsx |
| `not_excel` | 不是 xlsx / xlsm，未预检 |
| `timeout` | 预检时间用完（一次总共 8 秒），未预检 |
| `too_large` | 文件超过 64 MB，未预检 |
| `missing` | 读不到文件 |
| `unreadable` | 文件读不开 |

### 投控检测

| 码 | 级别或类型 | 含义 |
|---|---|---|
| `baseline_not_provided` | 没跑的规则原因 | 没有给合同 / 中标清单 |
| `baseline_invalid` | 没跑的规则原因 | 给了合同 / 中标清单，但一行都没读出来 |
| `baseline_coverage_low` | 没跑的规则原因 | 严格对齐率不到一半，不判合同外新增 |
| `rule_disabled` | 没跑的规则原因 | 阈值文件里关闭了这条规则 |

复核时可能出现的调用失败：`reason_required`（复核理由为空）、`invalid_state`（状态不是 confirmed / dismissed / pending）、`anomaly_not_found`（本轮结果里没有这个异常编号）、`invalid_review_log`（`复核.jsonl` 某行被手改坏了，请恢复那一行）。

### 报告撰写

| 码 | 级别 | 含义 |
|---|---|---|
| `facts_none` | warn | 模板需要金额，但所选资料里一个都没读到；金额位全部是【待补】或 AI 转写 |
| `fact_conflict` | warn | 几份资料写的同一金额不一致，程序不取舍，已列出各处的值并标【待核】 |
| `facts_timeout` | warn | 金额事实读取超时，有资料没有读 |
| `facts_files_skipped` | warn | 有表格没有读金额，附原因 |
| `unreadable_files` | warn | 有资料读不出正文 |
| `duplicate_files` | info | 内容相同的资料只读一份 |
| `source_capped` / `files_trimmed` / `relevant_dropped` / `files_omitted` | warn / info | 资料超过篇幅，有内容被截短或略去 |
| `unknown_claims` | warn | 确认事项里有本模板不认识的键 |
| `sections_not_ok` | warn | 导出时有章节不是完整初稿，列出章名与标签 |
| `unbacked_number` | warn | 数字在资料原文中找不到，已标【待核】 |
| `cited_number` | warn | 数字在所引的资料里找不到，已标【待核】 |
| `unconfirmed_claim` | warn | 程序性陈述未经确认、资料中未见同样说法，已标【待核】 |
| `unreadable_claim` | warn | 「未列示 / 未载明」类断言可能只是资料读不出，已标【待核】 |
| `unsupported_negation` | warn | 全称否定的结论资料中没有依据，已标【待核】 |
| `template_echo` | warn | 照抄了模板写作要求、资料中未见，已标【待核】 |
| `transcribed` | warn | 与成稿报告逐字重合 30 字以上，疑似转写 |
| `transcribed_amount` | warn | 金额是 AI 从资料转写的、不是程序取数，已标【待核】 |
| `bad_placeholder` | warn | 金额占位符没有程序取数，已换成【待补：金额】 |
| `out_of_scope_amount` | warn | 金额不是本章该写的，已标【待核】 |
| `unknown_citation` | warn | `[资料n]` 引用的编号不存在 |
| `raw_placeholder` | warn | 模板占位符没有替换，已换成【待补】 |
| `blank_quantity` | warn | 数量或名称是空的，已标【待核】 |
| `unbacked_code` | warn | 清单编码在送入的资料里找不到，已标【待核】 |

### 清单框架

| 码 | 级别 | 含义 |
|---|---|---|
| `quantity_pending_review` | warn | 有片段降为待核，未进正式清单 |
| `quantity_unmatched` | warn | 有片段没有得到码表里的编码，需人工补 |
| `quantity_excluded_scope` | info | 有片段按原文排除句划出本次范围 |
| `quantity_lot_unknown` | warn | 项目名称里解析不到标段，命中标段排除句的做法降为待核 |
| `quantity_fitout_provisional` | info | 做法层注明详精装修设计，按暂定做法列项，是否属于本次范围请确认 |
| `quantity_block_lines_unrecognized` | info | 做法块里有行没有认成构造层 |
| `quantity_exclusion_object_too_generic` | warn | 读着像排除句，但对象只有「面层」这类泛指词，没有据此排除 |
| `quantity_file_out_of_scope` / `quantity_section_out_of_scope` | warn | 文件或章节不是房建专业 |
| `quantity_file_skipped_no_text` | warn | 文件抽不出正文，已跳过 |
| `quantity_ocr_source` | warn | 正文来自扫描件识别文本，请对照原件 |
| `quantity_llm_failed` | warn | 有片段没有回答，结果为部分完成 |
| `quantity_features_skipped` | warn | 项目特征还没有摘录，相关槽位写「待补」 |
| `quantity_cross_version` | info | 编码在其他版本码表里同号异名，已在来源列标注 |

### 概算编制

| 码 | 级别 | 含义 |
|---|---|---|
| `baselines_default_sample` | info | 没有给指标基准，用随包单一样本基准 |
| `baseline_single_sample` | warn | 样本来源少于 3 个，建议值只作参考，不自动预填 |
| `baseline_dims_unasserted` | warn | 基准没有区分地区、价期、结构类型 |
| `building_use_unconfirmed` | warn | 没有确认业态 |
| `fee_bases_absent` / `fee_base_missing` | warn | 缺计费基数，相关其他费不出参考值 |
| `fee_rules_owner_released` | warn | 费率规则是仓主默认放行，不是造价员签署 |
| `fee_suggestion_withheld` | warn | 勘察设计费等档位闭开性未确认，参考金额扣留 |
| `fee_attr_defaulted` | warn | 费率属性按默认值计算，请确认 |
| `fee_manual_only` | info | 没有数值规则，须人工填报 |
| `cost_input_incomplete` | warn | 成本位未填完，未填的按 0 计，合计偏低 |
| `optional_input_missing` | warn | 建设期融资费用 / 铺底流动资金未填，按 0 计 |
| `land_cost_unfilled` | warn | 建设用地费未填，按 0 计 |
| `area_total_mismatch` | warn | 单体面积合计与原文总面积对不上 |
| `area_mismatch_acknowledged` | warn | 面积差异已由您确认放行 |
| `scope_whole_site_suspect` | warn | 疑似全地块口径的面积 |
| `rate_out_of_range` | warn | 费率超出常规区间，照算不拦截 |
| `div_by_zero` | info | 分母为空，xlsx 里显示为空白 |
| `template_fix` | info | 源模板本身的公式缺陷已修正 |

概算的质量结论 `review_level`：`ok`、`needs_review`（需复核）、`draft`（草稿）。理由码包括 `coverage_below_draft`、`sheet_unfilled`、`sheet_unfilled_review`、`reference_values_adopted`、`owner_released_fee_adopted`、`input_sources_undeclared`、`footprint_derived`、`reference_cost_deviation` 等，生成的 xlsx 末页「生成说明」逐条列出。

## CAD 看图的提示与拒绝

CAD 工具直接返回表格，不带上面的状态字段。需要注意两类情况：

- **警告**：开图、列图框时以「警告：…」列出，例如「跳过了 N 个图纸空间（布局）实体；只读取模型空间」「N 种块引用找不到块定义」「有 N 个天正 / 代理实体未被解析」「单位未确认：量纲类工具（cad_rooms）会拒绝执行」。助手会如实转述。
- **拒绝执行**：单位未确认时，房间面积工具返回「单位未确认，房间面积需要量纲，已拒绝执行」，并附单位证据。确认单位后再查即可。局部渲染范围过大也会被拒绝，按提示改用格子或更小范围。

结果为空时，助手会说明可能原因（图层命名不同、转换丢失、范围不对），不会说"没有"。

## 调用失败

脚本无法运行或请求不合法时，不输出结果，而是以退出码 2 结束，并输出一行错误：

```json
{"error": {"code": "input_not_found", "message": "找不到文件：资料/4 结算资料/审定计价表.xlsx", "hint": "确认路径相对于当前目录，或改用绝对路径"}}
```

您在对话里会看到这一步的工具调用标为失败，助手会把 `message` 和 `hint` 告诉您，按提示修正后重跑。

| 码 | 含义 | 下一步 |
|---|---|---|
| `zt_not_importable` | 内置 Python 运行环境不可用：版本低于 3.11、找不到程序包或缺依赖 | 助手转述原因，不换解释器硬跑；见 [常见故障](/docs/troubleshooting/) |
| `input_not_found` | 文件不存在 | 确认文件已拉取到本机，路径正确 |
| `too_many_files` | 一次送检超过 60 份 | 分批运行 |
| `input_too_large` | 一次送检合计超过 300 MB | 分批运行 |
| `invalid_request` | 请求字段缺失、多余或类型不对 | 助手按说明修正参数 |
| `usage` | 命令参数不对 | 助手按用法提示修正 |
| `internal_error` | 未预期的程序错误 | 把对话与工作目录反馈给管理员 |
| `no_text` | 清单框架：所有文件都抽不出正文 | 扫描件先生成识别文本；`.doc` / `.xls` 另存为 `.docx` / `.xlsx` |
| `too_many_segments` | 清单框架：做法片段超过 800 个 | 按单体或专业拆开分次做 |
| `prepare_mismatch` | 清单框架：原件在切片后变了 | 重新切片、重新作答 |
| `coverage_invariant` | 清单框架：内部核算不成立，已中止，不出文件 | 反馈给管理员 |

`zt_not_importable` 的说明会写出是哪个解释器、缺了什么，例如「缺少 zt 的依赖：PyYAML」；处理建议是使用桌面版内置的 Python。

## 相关页面

- [送审审定核对](/docs/features/check/)
- [造价指标](/docs/features/metrics/)
- [投控异常检测与复核](/docs/features/control/)
- [概算编制辅助](/docs/features/estimate/)
- [报告撰写](/docs/features/report/)
- [GB50854 清单框架](/docs/features/bills/)
- [CAD 看图](/docs/features/cad/)
- [常见故障](/docs/troubleshooting/)
