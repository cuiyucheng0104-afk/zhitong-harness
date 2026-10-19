# 来源：engine-service/app/engine/warning_codes.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""概算链路 warning code 的**单一真源**（O-13）。

为什么需要它：warning code 此前散落在 4 个模块的字符串字面量里，前端
`estimateModel.ts` 另存一份中文映射 `WARNING_CODE_CN`。实测两边对不齐——
引擎发的码前端字典里没有，结果页就把**英文码本身**当分组标题渲染给造价员看
（"fee_band_closure_unconfirmed" 出现在一份要给甲方看的概算里）。

这里做三件事：
  1. 把全部码集中登记，逐条给中文名 + 严重度 + 该怎么办；
  2. 随 `GET /engine/estimate/template` 下发，前端「接口字典优先、本地兜底」；
  3. `tests/test_warning_codes.py` 扫源码：模块里发出的码只要没登记就红 ——
     这条比"各模块改用常量"更管用，因为它连**新加的**码也拦得住。

严重度口径（前端据此分组/配色，不是拦截）：
  block  没有拦截语义的码不该用这一档；本模块目前不设 block，
         真正的拦截走 HTTP 4xx（全零闸 422、必填闸 422），不靠 warning。
  warn   影响金额或口径，造价员必须看一眼并做决定
  info   完成度/降级/来源说明，看不看不影响正确性
"""
from __future__ import annotations

WARN = "warn"
INFO = "info"


def _c(label: str, severity: str, hint: str) -> dict:
    return {"label": label, "severity": severity, "hint": hint}


# ---------------------------------------------------------------- 求值 / 渲染
UNKNOWN_INPUT = "unknown_input"
UNKNOWN_RATE = "unknown_rate"
DIV_BY_ZERO = "div_by_zero"
TEXT_IN_ARITHMETIC = "text_in_arithmetic"
TEMPLATE_FIX = "template_fix"
RATE_OUT_OF_RANGE = "rate_out_of_range"
OPTIONAL_INPUT_MISSING = "optional_input_missing"
COST_INPUT_INCOMPLETE = "cost_input_incomplete"
RATIO_SCALE_SUSPECT = "ratio_scale_suspect"

# ---------------------------------------------------------------- 正向推算
UNIT_COST_UNPARSED = "unit_cost_unparsed"
BASELINE_ROW_INVALID = "baseline_row_invalid"
BASELINE_DIMS_UNASSERTED = "baseline_dims_unasserted"
ITEMS_UNSUPPORTED = "items_unsupported"
FEE_CELL_DUAL_SOURCE = "fee_cell_dual_source"
BASELINE_SINGLE_SAMPLE = "baseline_single_sample"
BUILDING_USE_UNCONFIRMED = "building_use_unconfirmed"

# ---------------------------------------------------------------- 面积闸 / 对账 / 抽取（WS10-A）
AREA_GATE_ABSENT = "area_gate_absent"
AREA_MISMATCH_ACKNOWLEDGED = "area_mismatch_acknowledged"
AREA_TOTAL_MISMATCH = "area_total_mismatch"
CHECK_VALUE_AMBIGUOUS = "check_value_ambiguous"
LAND_COST_UNFILLED = "land_cost_unfilled"
FOOTPRINT_MISSING = "footprint_missing"
# WS29-s（issue #968）：项目名带标段，而抽到的总建筑面积没有注明是本标段的
SCOPE_WHOLE_SITE_SUSPECT = "scope_whole_site_suspect"
# WS29-d（issue #1010）：楼号表里没有面积的单体（保留、不归位）；建筑密度写法认不出（不推算占地）
BUILDING_AREA_MISSING = "building_area_missing"
DENSITY_FORMAT_UNRECOGNIZED = "density_format_unrecognized"

# ---------------------------------------------------------------- 产出质量（WS10-B，issue #761）
SOURCE_TEXT_INCOMPLETE = "source_text_incomplete"
# 抽取入参去重（WS29-p，issue #970）
SOURCE_FILE_DUPLICATE = "source_file_duplicate"
# zt 改动：抽取由 agent 作答，某份可读文件没有回答
EXTRACT_ANSWER_MISSING = "extract_answer_missing"
# zt 改动：suggest 没给指标基准时用随包样本基准
BASELINES_DEFAULT_SAMPLE = "baselines_default_sample"
FEE_VALUE_STALE = "fee_value_stale"
FEE_AGGREGATE_MISMATCH = "fee_aggregate_mismatch"
FEE_POSSIBLE_DOUBLE_COUNT = "fee_possible_double_count"
TEMPLATE_PLACEHOLDER_LEFT = "template_placeholder_left"
# 质量结论的理由码（quality.reasons[].code）：不是告警，但结果页同样要显示成中文
COVERAGE_BELOW_DRAFT = "coverage_below_draft"
SHEET_UNFILLED = "sheet_unfilled"
REFERENCE_VALUES_ADOPTED = "reference_values_adopted"
OWNER_RELEASED_FEE_ADOPTED = "owner_released_fee_adopted"
INPUT_SOURCES_UNDECLARED = "input_sources_undeclared"
# WS29-d：占地是按 用地面积 × 建筑密度 推算后由用户点「填入推算值」写入的（理由码，记需复核）
FOOTPRINT_DERIVED = "footprint_derived"
# WS29-q（issue #1000）：专项 / 室外 / 其他费整表没填（U18），概算偏离参照造价（U19）
SHEET_UNFILLED_REVIEW = "sheet_unfilled_review"
REFERENCE_COST_DEVIATION = "reference_cost_deviation"

# ---------------------------------------------------------------- compute 拦截闸（insufficient 的 status_reason）
# zt 改动：报表管理（WS25-b）没有迁入，它专用的码（reportform_* / area_ack_voided / report_origin_cap）已删；
# 两道闸的码留作 compute 拒算时信封里那条 error 级告警的中文名
REQUIRED_INPUTS_MISSING = "required_inputs_missing"
AREA_GATE_FAILED = "area_gate_failed"

# ---------------------------------------------------------------- 费率基数接线
FEE_BASES_ABSENT = "fee_bases_absent"
FEE_BASE_DERIVED = "fee_base_derived"
FEE_RULES_UNAVAILABLE = "fee_rules_unavailable"
FEE_BASES_UNSUPPORTED = "fee_bases_unsupported"
FEE_BASES_SPEC_UNSUPPORTED = "fee_bases_spec_unsupported"
FEE_ATTRS_UNSUPPORTED = "fee_attrs_unsupported"
FEE_ATTRS_SPEC_UNSUPPORTED = "fee_attrs_spec_unsupported"
FEE_BASE_MAGNITUDE_SUSPECT = "fee_base_magnitude_suspect"

# ---------------------------------------------------------------- 费率求值
FEE_RULES_UNSIGNED = "fee_rules_unsigned"
FEE_RULES_OWNER_RELEASED = "fee_rules_owner_released"
FEE_SUGGESTION_WITHHELD = "fee_suggestion_withheld"
FEE_BASE_MISSING = "fee_base_missing"
FEE_BASE_NON_POSITIVE = "fee_base_non_positive"
FEE_BASE_OUT_OF_TABLE = "fee_base_out_of_table"
FEE_MANUAL_ONLY = "fee_manual_only"
FEE_PARTIAL_COVERAGE = "fee_partial_coverage"
FEE_PARADIGM_DISPUTED = "fee_paradigm_disputed"
FEE_BAND_CLOSURE_UNCONFIRMED = "fee_band_closure_unconfirmed"
FEE_BAND_OPEN_ENDED = "fee_band_open_ended"
FEE_MIN_FEE_APPLIED = "fee_min_fee_applied"
FEE_MATRIX_NOT_APPLICABLE = "fee_matrix_not_applicable"
FEE_ATTR_DEFAULTED = "fee_attr_defaulted"
FEE_ATTR_UNKNOWN_VALUE = "fee_attr_unknown_value"
FEE_WRITE_TARGET_AGGREGATE = "fee_write_target_aggregate"
FEE_APPLICABILITY_UNCONFIRMED = "fee_applicability_unconfirmed"
FEE_RULE_NOT_APPLICABLE = "fee_rule_not_applicable"


WARNING_CODES: dict[str, dict] = {
    # —— 求值 / 渲染 ——
    UNKNOWN_INPUT: _c("未声明的输入位", INFO,
                      "该键不在模板声明的输入位里，已忽略；通常是调用方拼错了格号"),
    UNKNOWN_RATE: _c("未声明的费率参数", WARN,
                     "该键不在模板声明的费率参数里，已忽略，对应费率按模板默认值计——"
                     "通常是拼错了参数名（如把 reserve_rate 写成驼峰）。金额随默认值变动，"
                     "请对照响应里的 rates_used 核对本次生效费率"),
    DIV_BY_ZERO: _c("除零（分母为空）", INFO,
                    "单方指标/占比的分母还没填，属正常空态；下载的 xlsx 里显示为空白而不是 #DIV/0!"),
    TEXT_IN_ARITHMETIC: _c("文本参与了算术", WARN,
                           "有单元格把文本当数值参与计算，结果不可信，请核对该格"),
    TEMPLATE_FIX: _c("原表缺陷已修正", INFO,
                     "源模板本身有错（如 SUM 区间漏行、跨表错引），引擎按修正后的公式算"),
    RATE_OUT_OF_RANGE: _c("费率超出常规区间", WARN,
                          "按你填的费率照算，不拦截（铁律 7）；请确认这个费率是有依据的"),
    OPTIONAL_INPUT_MISSING: _c("选填项未填，合计可能偏低", WARN,
                               "建设期融资费用 / 铺底流动资金未填时按 0 计，"
                               "建设动态总投资会恒等于建设静态总投资"),
    COST_INPUT_INCOMPLETE: _c("成本位未填完", WARN,
                              "未填的成本位按「空格 = 0」参与求值，各级合计因此偏低；"
                              "可用正向推算出建议值后逐条确认"),
    RATIO_SCALE_SUSPECT: _c("比值位标度可疑（疑似差 100 倍）", WARN,
                            "该格是比值列，存的是小数（列头的 % 只是显示格式）；"
                            "收到的值大于 1，多半是把百分数直接填进来了。"
                            "仍按传入值照算，请核对标度"),

    # —— 正向推算 ——
    UNIT_COST_UNPARSED: _c("单方指标公式形态异常", INFO,
                           "该行的单方指标公式不是 =Cn/En*10000 形态，反解不出数量格，本行不出建议"),
    BASELINE_ROW_INVALID: _c("基准行不可用", WARN,
                             "有基准行缺少可用的单方指标，已忽略；请检查基准库数据"),
    BASELINE_DIMS_UNASSERTED: _c("基准维度未断言（通配匹配）", WARN,
                                 "命中的基准行 region/price_period/structure_type 为 NULL，"
                                 "按通配匹配出建议——建议值未区分地区/价期/结构，请核对"
                                 "对本项目的适用性；根治需给基准库补维度数据"),
    ITEMS_UNSUPPORTED: _c("条目字典未参与回链", INFO,
                          "本版引擎不接受 items 参数，item_code 回链已跳过（不影响金额）"),
    FEE_CELL_DUAL_SOURCE: _c("该格有两个来源的建议值", WARN,
                             "指标基准库与费率规则各出一套，口径不同、不可相加；"
                             "请二选一（默认取有文号可追溯的费率侧）"),
    BASELINE_SINGLE_SAMPLE: _c("基准只有单一样本，建议值仅作参考", WARN,
                               "同一指标的样本来源少于 3 个（D47），建议值不自动预填；"
                               "请逐条或按组确认后采纳，采纳过参考值的概算按需复核处理"),
    BUILDING_USE_UNCONFIRMED: _c("未确认项目业态", WARN,
                                 "不知道是住宅、办公还是仓储物流，就判断不了幕墙 / 精装修这类"
                                 "分项该不该出参考值；请在「项目画像」里选择业态后重新推算"),

    # —— 面积闸 / 对账 / 抽取（WS10-A）——
    AREA_GATE_ABSENT: _c("模板未声明面积闸", INFO,
                         "总建筑面积为 0 的概算不会被自动拦下，请人工核对经济技术指标"),
    AREA_MISMATCH_ACKNOWLEDGED: _c("单体面积与原文总面积不一致（已确认）", WARN,
                                   "槽位合计与原文总建筑面积相差超过 1%，用户已确认并写明理由；"
                                   "本表按需复核处理"),
    AREA_TOTAL_MISMATCH: _c("单体面积合计与原文总面积对不上", WARN,
                            "多栋项目被截成模板槽位数时会少算面积；请在单体归位里把未归位的"
                            "单体并入槽位，或在生成前确认差异并写明理由"),
    CHECK_VALUE_AMBIGUOUS: _c("原文总量出现多个数值", WARN,
                              "同一个总量（如总建筑面积）原文给了不同数字，没法拿它对账；"
                              "请在单体归位里核对"),
    LAND_COST_UNFILLED: _c("建设用地费未填", WARN,
                           "该格不按面积推算（样本里是包干额），请填出让合同价或挂牌价；"
                           "划拨或不计列时显式填 0"),
    FOOTPRINT_MISSING: _c("建筑占地面积缺失，室外面积按整块用地计", WARN,
                          "室外面积 = 用地面积 − 占地面积，占地为 0 时室外及配套的数量偏大；"
                          "原文有建筑占地 / 基底面积时请补填"),
    SCOPE_WHOLE_SITE_SUSPECT: _c("疑似全地块口径", WARN,
                                 "项目名称里有标段，所选文件给的总建筑面积没有注明是本标段的，"
                                 "很可能是整个地块的数；照着写入，概算规模会按全地块出。"
                                 "请按分标段资料填写本标段的面积、用地与车位"),
    BUILDING_AREA_MISSING: _c("有单体原文没有面积", WARN,
                              "原文列了这些单体但没写面积（如楼号表的面积列空着），它们照样列在单体归位里、"
                              "标「原文无面积」，不自动归位、不计入合计；请按分标段面积表等资料手填后再并入槽位"),
    DENSITY_FORMAT_UNRECOGNIZED: _c("建筑密度写法认不出", INFO,
                                    "只认「建筑密度 30%」这种百分数写法；不带 % 的小数分不清是 0.3% 还是 30%，"
                                    "不拿它推算占地。占地请按总平面图或规划条件填写"),

    # —— 费率基数接线 ——
    FEE_BASES_ABSENT: _c("未提供计费基数", WARN,
                         "没给基数就算不出其他费建议；这不代表本项目没有工程建设其他费用"),
    FEE_BASE_DERIVED: _c("计费基数由引擎兜底推导", INFO,
                         "用本次求值的工程费用合计（估概算总表!C5）当「工程费用」基数；"
                         "成本位收敛后建议重算一次"),
    FEE_RULES_UNAVAILABLE: _c("费率规则引擎未接入", WARN,
                              "部署侧缺 zt.estimate.fee_rules；不是「本项目没有其他费」"),
    FEE_BASES_UNSUPPORTED: _c("本版引擎不接受计费基数参数", INFO,
                              "required_fee_bases 的已满足标记已跳过（不影响金额）"),
    FEE_BASES_SPEC_UNSUPPORTED: _c("本版费率引擎不下发基数清单", INFO,
                                   "调用方需自行确定基数键与单位"),
    FEE_ATTRS_UNSUPPORTED: _c("本版引擎不接受计费属性参数", INFO,
                              "required_fee_attrs 的已满足标记已跳过（不影响金额）"),
    FEE_ATTRS_SPEC_UNSUPPORTED: _c("本版费率引擎不下发计费属性清单", WARN,
                                   "取费列/情形/用途的受控下拉无从渲染，引擎将按默认值"
                                   "算钱并逐条发 fee_attr_defaulted，造价员没有机会纠正"),
    FEE_BASE_MAGNITUDE_SUSPECT: _c("计费基数量级可疑", WARN,
                                   "该值与其声明单位差了几个数量级，很可能单位传错"
                                   "（万m² 与 m² 差 10⁴）；仍按传入值照算，请核对"),

    # —— 费率求值 ——
    FEE_RULES_UNSIGNED: _c("费率规则未经造价员签署", WARN,
                           "规则数据由 LLM 看图转录、尚未逐值对图签字，本次**不产出**任何"
                           "建议金额；签署后即出值"),
    FEE_RULES_OWNER_RELEASED: _c("费率建议已放行，但不是造价员签署的", WARN,
                                 "仓主 2026-09-10 默认放行以便先部署（issue #159）："
                                 "建议值会出，但这批 LLM 转录费率**未经造价员逐值核对**，"
                                 "请当作待核实的参考，逐条确认后再采纳"),
    FEE_SUGGESTION_WITHHELD: _c("建议金额被扣留", WARN,
                                "规则依据齐全但金额不予下发：或因规则集未签署，"
                                "或因该条目档界闭开性未确认（铁律 2 / 铁律 3）；"
                                "具体原因见该条的 unavailable_reason"),
    FEE_BASE_MISSING: _c("该费用项缺计费基数", WARN,
                         "本项不出建议值；可接受的基数键见 required_fee_bases"),
    FEE_BASE_NON_POSITIVE: _c("计费基数非正数", WARN, "基数 ≤ 0，本项不出建议值"),
    FEE_BASE_OUT_OF_TABLE: _c("基数超出费率表范围", WARN,
                              "已按最近档外推，超出原表覆盖范围，请人工复核"),
    FEE_MANUAL_ONLY: _c("原表无数值费率，须人工填报", INFO,
                        "该项在原定额里写的是「详见文件」一类，无法规则化"),
    FEE_PARTIAL_COVERAGE: _c("规则只覆盖部分子项", WARN,
                             "建议值**不含**未覆盖的子项，须人工补齐"),
    FEE_PARADIGM_DISPUTED: _c("计费范式归类有争议", WARN,
                              "原表表头与 spec 归类不一致，需造价员拍板；见签署清单 SC-2"),
    FEE_BAND_CLOSURE_UNCONFIRMED: _c("档位闭开性未确认", WARN,
                                     "原表未注明档界归属（含不含上下界），引擎按同类条目的"
                                     "约定处理；金额是否受影响见告警正文"),
    # 措辞更正（对抗复核第 2 轮）：原文写「按下界费率计」，与实现不符 ——
    # 该档没有上界**基数**可插值，原表只给下限时取下限、给了收费区间时取区间中值，
    # 两条支路都不是"按下界费率计"。具体走了哪一条见告警正文。
    FEE_BAND_OPEN_ENDED: _c("落在开口档", INFO,
                            "基数落在原表最后一个开口档（无上界），档内无法插值；"
                            "原表只给下限时取下限，给了收费区间时取区间中值"),
    FEE_MIN_FEE_APPLIED: _c("已按最低收费计", INFO, "按费率算得低于原表最低收费，取最低收费"),
    FEE_MATRIX_NOT_APPLICABLE: _c("单价矩阵未命中", WARN,
                                  "给定的项目属性组合在原表矩阵里查不到，本项不出建议值"),
    FEE_ATTR_DEFAULTED: _c("项目属性回落默认值", WARN,
                           "影响金额的属性没给，已用默认值算；请确认默认值适用于本项目"),
    FEE_ATTR_UNKNOWN_VALUE: _c("项目属性取值不认识", WARN,
                               "给的取值不在原表的选项里，已回落默认值"),
    FEE_WRITE_TARGET_AGGREGATE: _c("该值是小计参考值，不能直接填", WARN,
                                   "落点是公式格（小计），须由造价员自行拆到子项；引擎不做平分"),
    FEE_APPLICABILITY_UNCONFIRMED: _c("费率规则的适用条件未确认", WARN,
                                      "该费率只对特定项目成立（如杭州市区、生产性项目），"
                                      "未选择项目所在地 / 项目性质时不出建议值，也不回落默认值"),
    FEE_RULE_NOT_APPLICABLE: _c("费率规则不适用于本项目", INFO,
                                "按本项目的所在地 / 性质，该条费率不适用；按当地文件或实际人工填报"),
    # —— WS10-B（issue #761）——
    SOURCE_TEXT_INCOMPLETE: _c("资料有缺页或被截断", WARN,
                               "该文件部分页没取到正文（扫描页未识别 / OCR 预算用完），这些页里的指标"
                               "没检索到，not_found 不代表原文没有；可补旁车或 OCR 后重抽"),
    SOURCE_FILE_DUPLICATE: _c("内容相同的文件只读了一份", INFO,
                              "所选文件里有几份内容完全相同（原件 sha256 一致，不看文件名），只按其中一份抽取、"
                              "只调一次模型，候选与单体不会因此出两遍；告警里点名了保留的是哪一份"),
    BASELINES_DEFAULT_SAMPLE: _c("用了随包样本基准", INFO,
                                 "请求没有给指标基准，用随包的 gsyz_v1 样本基准（单一来源）；建议值只作单样本参考，"
                                 "有企业指标库时请用 --baselines 指定"),
    EXTRACT_ANSWER_MISSING: _c("有文件没有抽取回答", WARN,
                               "这份文件读到了正文，但 answers 里没有它的回答，它的指标本次没有抽取；"
                               "补上这份文件的回答后重跑 extract_finalize"),
    FEE_VALUE_STALE: _c("采纳的费率值已过期", WARN,
                        "该格采纳自费率建议，但按本次基数重算的结果变了（多半是成本位又改过）；"
                        "请回第 3 步重新推算或确认"),
    FEE_AGGREGATE_MISMATCH: _c("子项之和与费率小计对不上", WARN,
                               "汇总型费率（项目建设管理费 / 建设管理其他费）只给小计参考值，"
                               "子项由人拆；子项和偏离小计超过 20%，请核对是否重复计列或漏项"),
    FEE_POSSIBLE_DOUBLE_COUNT: _c("可能重复计列", WARN,
                                  "建设管理其他费的规则小计已含施工阶段全过程造价咨询，子项里的"
                                  "工程造价咨询费又有值；政府投资项目请核对是否另计结算审核费用"),
    TEMPLATE_PLACEHOLDER_LEFT: _c("交付表残留样本占位符", WARN,
                                  "交付表里还有样本表的占位符（如 ***、x%），请改成本项目的实际名称"),
    COVERAGE_BELOW_DRAFT: _c("覆盖率低于草稿阈值", WARN,
                             "成本位填得太少，这份表只能当草稿看；可调推算建议逐条确认后再生成"),
    SHEET_UNFILLED: _c("整张费用表未填", WARN,
                       "建筑工程费或安装工程费一格都没填，合计按 0 计，这份表只能当草稿看"),
    REFERENCE_VALUES_ADOPTED: _c("采纳了单样本参考值", INFO,
                                 "基准样本来源不足（D47），采纳的参考值须造价员复核"),
    OWNER_RELEASED_FEE_ADOPTED: _c("采纳了未经造价员签署的费率", INFO,
                                   "费率规则集为仓主默认放行、未经造价员逐值签署，采纳的建议值须复核"),
    INPUT_SOURCES_UNDECLARED: _c("输入位来源未申报", INFO,
                                 "调用方没说明这些数从哪来（手填 / 抽取 / 导入 / 采纳），交付表的"
                                 "逐格来源表无法写全，按需复核处理"),
    FOOTPRINT_DERIVED: _c("占地按建筑密度推算", WARN,
                          "原文没有建筑占地面积，占地是按 用地面积 × 建筑密度 推算后填入的，不是原文数值；"
                          "室外面积随它计算，本表按需复核处理"),
    SHEET_UNFILLED_REVIEW: _c("有费用表一格都没填", WARN,
                              "专项工程费、室外及配套工程费或工程建设其他费整张表没填，合计按 0 计入；"
                              "本项目确实没有这类费用可以不填，否则请回第 3 步补"),
    REFERENCE_COST_DEVIATION: _c("概算与参照造价相差较大", WARN,
                                 "建设静态总投资与第 5 步填的参照造价（如招标控制价）之比超出 0.7～1.3 倍；"
                                 "多半是单价样本或规模口径不一致，请核对（只提示，不拦）"),
    # —— compute 拦截闸（zt）——
    REQUIRED_INPUTS_MISSING: _c("必填指标位未填完", WARN,
                                "经济技术指标表的 11 个必填位有缺，compute 拒算；补齐后重算"),
    AREA_GATE_FAILED: _c("总建筑面积为空或为 0", WARN,
                         "没有建筑面积就没有可交付的口径（单方指标失真，金额只剩室外部分），compute 拒算"),
}


# 正向推算 unresolved 的 reason 口径（不是 warning，但结果页同样要显示成中文）
UNRESOLVED_REASONS: dict[str, dict] = {
    "no_baseline": _c("指标基准库无对应行", INFO,
                      "按 单元格→item_code→item_name 三级严格查表均未命中；不做模糊匹配（铁律 3）"),
    "no_quantity": _c("缺数量，推不出金额", INFO,
                      "该行的数量格没有值：要么是待填的数量输入位，要么上游根输入没填全"),
    "no_rule": _c("两个来源都没有", WARN,
                  "指标基准库与费率规则都不覆盖这一格，须人工填报"),
    "quantity_zero": _c("数量为 0", INFO, "单方指标乘不出金额"),
    # —— WS10-A ——
    "not_applicable_for_use": _c("本业态通常不含该分项", INFO,
                                 "按项目业态（如仓储物流、工业厂房）判断通常不含，不出参考值"
                                 "（初始口径，待造价员确认）；确有时直接填实际值"),
    "baseline_not_scalable": _c("样本包干额，不按面积推算", INFO,
                                "该格在样本里是包干额；建议值看费率规则（工程建设其他费）"),
    "manual_required": _c("须人工填报", INFO,
                          "该格在样本里是包干额且无费率规则，按合同 / 报价 / 实际填"),
    "applicability_unconfirmed": _c("费率适用条件未确认", WARN,
                                    "选择项目所在地 / 项目性质后才出建议值"),
    "rule_not_applicable": _c("费率规则不适用本项目", INFO,
                              "按当地文件或实际人工填报"),
    # 抽取（extract）侧
    "total_only_no_partition": _c("原文只有总量，无法分区", INFO,
                                  "总量已放在该组首位，其余分区须人工拆分或留空"),
    "unmapped_building": _c("单体未归位", WARN,
                            "超出模板槽位的单体不猜、不合并；请在单体归位里并入某个槽位"),
}


def describe(code: str) -> dict | None:
    """→ {label, severity, hint}；未登记回 None（调用方据此原样显示码，并该去登记它）。"""
    return WARNING_CODES.get(code) or UNRESOLVED_REASONS.get(code)


def payload() -> dict:
    """随 GET /estimate/template 下发的字典。前端「接口字典优先、本地兜底」。"""
    return {"warnings": dict(WARNING_CODES), "unresolved_reasons": dict(UNRESOLVED_REASONS)}
