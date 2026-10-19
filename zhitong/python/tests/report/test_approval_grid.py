# 来源：engine-service/tests/test_approval_grid.py（zhitong-cost-ai@991ff5c，W3 搬入；只改了 import）
"""WS07 K2：审定单 / 汇总表的确定性网格读取（QA:extract-01）。

改前：金额全靠 LLM 摘录，只送明细表时核减金额被取成「净核金额」列的 1280435.50（正确值 1418635.50，
差 138200 元），verified=true、界面零告警。现在表头定位 → 列语义 → 合计行 → 单元格，值带坐标。

夹具在 tests/extract_fixtures.py（内存里造，形状照真实版式，C19）。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from zt.report.approval_grid import display, read_grid_fields
from zt.report.fields import NET_REDUCTION, amount_column_semantic
from tests.report import _grid_fixtures as fx


def _by_field(res) -> dict:
    out: dict = {}
    for c in res.candidates:
        out.setdefault(c["field"], []).append(c)
    return out


def test_p2_shape_reads_gross_reduction_not_net():
    """① 真实审定单形状：送审 D6:E7 合并、净核减在 G、其中 H7 核减 / I7 核增。
    核减必须取 H10（1418635），不是 G10 的净核减（1280435）。"""
    got = _by_field(read_grid_fields(fx.p2_shape(), "xlsx", "审定单出.xlsx"))
    (cut,) = got["核减金额"]
    assert cut["value"] == "1418635" and cut["amount_yuan"] == "1418635.00", cut
    assert cut["evidence"]["cell"] == "H10" and cut["evidence"]["row_label"] == "合计", cut
    assert cut["evidence"]["col_label"] == "其中|核减金额（元）", cut
    assert cut["verify_level"] == "strong" and cut["channel"] == "grid"
    assert cut["quote"] == "审定单!H10〔核减金额（元） × 合计〕= 1418635", cut["quote"]
    assert [c["value"] for c in got["核增额"]] == ["138200"]
    assert [c["value"] for c in got["送审金额"]] == ["11894328"], "D/E 两列合并成一列，送审不判歧义"
    assert got["送审金额"][0]["evidence"]["cell"] == "D10"
    assert [c["value"] for c in got["审定金额"]] == ["10613893"]
    # 净核减不是输出字段：识别出来只为不把它当核减
    assert all(c["value"] != "1280435" for cs in got.values() for c in cs)


def test_p2_shape_header_key_values_and_remark():
    """表头键值行（工程名称 / 建设单位）与备注格里的合同价、合同工期（锚定正则）。"""
    got = _by_field(read_grid_fields(fx.p2_shape(), "xlsx", "审定单出.xlsx"))
    assert [c["value"] for c in got["工程名称"]] == ["城中河综合整治工程"]
    assert [c["value"] for c in got["建设单位"]] == ["某某区城市建设投资有限公司"]
    (price,) = got["合同价"]
    assert price["amount_yuan"] == "10500000.00" and price["evidence"]["row_label"] == "备注", price
    assert price["from_remark"] is True
    assert [c["value"] for c in got["工期"]] == ["180日历天"]


def _text_values(res) -> list[tuple[str, str, str]]:
    return [(c["field"], c["evidence"]["sheet"], c["value"]) for c in res.candidates if c["kind"] != "amount"]


def test_bill_and_fee_sheet_column_heads_are_not_key_values():
    """PR #768 评审：汇总表所在的工作簿里还有清单 / 规费 / 材料表，它们的「项目名称」是列头。

    改前：工程名称 = 「项目特征描述」（清单表 D3）、「计算基础」（规费表 C1），verify_level=strong，
    LLM 不再补问。三张表覆盖三条判据：清单表与规费表的右邻是列头词；材料表右邻「品牌」不在
    列头词表里，只有「这一行不是标签｜值排法」拦得住。"""
    res = read_grid_fields(fx.summary_with_bill_sheets(page_header=False), "xlsx", "明细.xlsx")
    assert _text_values(res) == [], _text_values(res)
    # 金额照旧从汇总表读
    assert [c["value"] for c in _by_field(res)["核减金额"]] == ["1418635"]


def test_gb50500_page_header_line_is_cut_before_the_next_label():
    """GB50500 清单表上方一格写完的表头行「工程名称：X    标段：Y    第 1 页 共 3 页」：
    改前整串（连标段、页码）当工程名称、strong。只取到下一个标签之前。"""
    res = read_grid_fields(fx.summary_with_bill_sheets(page_header=True), "xlsx", "明细.xlsx")
    assert _text_values(res) == [("工程名称", "分部分项工程量清单", "城中河综合整治工程")], _text_values(res)


def test_key_value_form_layouts():
    """真实表单排法照样出值：一行两对、拆成几格的 GB50500 表头行（下面紧贴着清单表）、带「单位：元」
    且紧挨着金额表头的审定单抬头；两列小表的列头与空白模板不出值。
    PR #768 第四轮白名单：同一行「工程名称|X|（空）|单位：元」下面什么都没有、或下面只有一行说明时，
    和「只有一行的空白表头」结构一样，拿不准 → 不出值（交 LLM），不再按「看起来不像列头」放行。
    PR #768 第五轮：带序号列的「概况」表不再凭「行首有序号」出值（序号分不出概况表和核对表），交 LLM。
    PR #768 第七轮（用户 2026-09-30 裁定 ②）：网格读出的文本字段只作候选，一律 weak —— 正面证据再充分也不给 strong。"""
    res = read_grid_fields(fx.kv_form_layouts(), "xlsx", "表单.xlsx")
    got = _text_values(res)
    assert got == [
        ("工程名称", "两对", "城中河综合整治工程"),
        ("建设单位", "两对", "某某区城市建设投资有限公司"),
        ("工程名称", "拆格表头", "城中河综合整治工程"),
        ("工程名称", "单位元", "城中河综合整治工程"),
    ], got
    assert {c["verify_level"] for c in res.candidates if c["kind"] != "amount"} == {"weak"}, res.candidates
    assert {c["verify_level"] for c in res.candidates if c["kind"] == "amount"} == {"strong"}, "金额不受影响"


# ---------------------------------------------------------------- PR #768 第三轮：数据表列头拿不准就不出值

@pytest.mark.parametrize("sheet", sorted(fx.DATA_TABLE_HEADS))
def test_data_table_column_heads_are_not_key_values(sheet):
    """第二轮评审实测：「项目名称|内容」「项目名称|费用」「项目名称|审核意见|备注」「项目名称|变更内容|备注」
    「工程名称|结算方式|备注」这几种列头行被当成表单行放行，工程名称 = 列头词、strong、channel=grid。
    第四轮起不带冒号的「标签|值」只有正面证据成立才出值：这几行是一列标签的第一行、只有一对，没有正面证据，不出值。"""
    res = read_grid_fields(fx.sheets({sheet: fx.DATA_TABLE_HEADS[sheet]}), "xlsx", "明细.xlsx")
    assert _text_values(res) == [], _text_values(res)


def test_overview_table_header_row_is_not_the_project_name():
    """第二轮评审端到端探针里的「工程概况」表：表头「项目名称|内容」，下面「工程名称|城中河综合整治工程」。
    改前工程名称 = 「内容」（B1）、strong。
    第四轮白名单：第一行是一列标签的最上面一行，没有正面证据 → 不出值；「工程名称」那一行虽然在一列
    表单标签中间，但同一列里还有一个映射到工程名称的标签 —— 拿不准哪个是本项目的名称 → 也不出值
    （交 LLM）；「建设单位」在中间、字段唯一 → 出值（第七轮起网格文本只作候选，weak）；「施工单位」是最后一行、
    下面什么都没有 → 不出值。"""
    res = read_grid_fields(fx.sheets({"工程概况": fx.OVERVIEW_ROWS}), "xlsx", "概况.xlsx")
    got = [(c["field"], c["value"], c["evidence"]["cell"], c["verify_level"]) for c in res.candidates]
    assert got == [("建设单位", "某某区城市建设投资有限公司", "B3", "weak")], got


def test_overview_header_without_a_name_row_is_still_a_header():
    """同一种概况表，但下面没有「工程名称」这一行：「项目名称|内容」是一列标签的最上面一行，没有正面证据，
    不出值；「建设单位」上下都是表单标签 → 出值。"""
    res = read_grid_fields(fx.sheets({"工程概况": fx.OVERVIEW_ROWS_NO_NAME}), "xlsx", "概况.xlsx")
    assert [(c["field"], c["value"]) for c in res.candidates] == [
        ("建设单位", "某某区城市建设投资有限公司")], res.candidates


def test_same_field_label_twice_in_one_column_yields_no_name():
    """表头标签是「工程名称」（不是项目名称），下面同一列有映射到同一字段的「项目名称」：上面那行没有正面证据；
    下面那行同一列里另有一个工程名称标签 → 拿不准 → 两行都不出工程名称（交 LLM）。
    「建设单位」是最后一行、下面什么都没有 → 不出值。"""
    res = read_grid_fields(fx.sheets({"概况": fx.OVERVIEW_ROWS_NAME_HEAD}), "xlsx", "概况.xlsx")
    assert [(c["field"], c["value"]) for c in res.candidates] == [], res.candidates


# ---------------------------------------------------------------- PR #768 第四轮：不带冒号的「标签|值」改白名单

def _names_and_heads(res) -> list:
    """读出来的工程名称，以及任何字段里读成了列头词 / 核对结论的值（都是错值）。"""
    return [(c["field"], c["evidence"]["sheet"], c["value"]) for c in res.candidates
            if c["kind"] != "amount" and (c["field"] == "工程名称" or c["value"] in fx.HEAD_TRAP_WORDS)]


@pytest.mark.parametrize("sheet", sorted(fx.HEAD_TRAPS))
def test_column_heads_without_positive_evidence_yield_nothing(sheet):
    """第三轮评审实测 8 种形状仍出 strong 列头词：列头下面多一行分类行「一、土建工程」、空行、单位行「（元）」、
    「（空）|详见附表」，或者列头下面接的正是表单标签（建设单位 / 工期 / 章节标题）。改前判据只看紧下一行。
    第四轮：不带冒号的「标签|值」只有正面证据成立才出值 —— 这些形状一个都没有，工程名称不出值、
    也不许有任何字段读成列头词。一行两对的列头行（审核记录表）下面往下找（跳过分类行 / 空行 / 单位行）
    找到数据行，就是列头行；「备注|说明」不算第二对；核对表里不同标签的值一样 → 值列不是表单值。"""
    res = read_grid_fields(fx.sheets({sheet: fx.HEAD_TRAPS[sheet]}), "xlsx", "明细.xlsx")
    assert _names_and_heads(res) == [], res.candidates


def test_head_over_label_column_still_reads_the_real_rows():
    """「工程名称|内容」下接建设单位、施工单位：列头行不出值；「建设单位」上下都是表单标签 → 照样出值
    （值是真值，不是列头词）；「施工单位」是最后一行、下面什么都没有 → 不出值。"""
    res = read_grid_fields(fx.sheets({"概况": fx.HEAD_TRAPS["内容_下接建设单位"]}), "xlsx", "概况.xlsx")
    assert _text_values(res) == [("建设单位", "概况", "某某区城市建设投资有限公司")], _text_values(res)


def test_recall_layouts_read_with_positive_evidence_and_stay_silent_without():
    """第三轮评审「召回下降」：能用正面证据读出的就读出，读不出的只能是不出值（交 LLM），不能是错值。
    正面证据：紧挨着金额表头（中间只隔空行 / 「单位：元」行）；一行两对（下面紧贴清单表 / 空行后的金额表头 /
    下一行也是两对 / 另一张表的列头）；一列连续表单标签的中间一行。
    没有正面证据：「工程名称|X」是一列标签的第一行（下面是「工程地址」）、下面只有一行说明；一行两对但
    下一行是没登记的「工程地址|…」（和半填的数据行分不清）。
    PR #768 第五轮：带序号、上面没有列头行的一列表单，中间一行（建设单位）照样读出，第一行交 LLM；
    上面有列头行「序号|项目|内容」的，和核对表「序号|检查项|结果」分不清，整列都不出值。
    PR #768 第六轮：一行两对下面是正好两格列头词的另一张表列头 → 照样读出（钉住「至少两格」的门槛）；
    一列表单上面是「标题 | 第 1 页 共 1 页」「标题 | 单位：元」→ 页码 / 单位说明不算内容，这一行不是列头，照样读出。
    PR #768 第七轮：判据①先走到表单块的最上面一行再找列头（和判据④一致）——「两对_上面半行表单_再上核对表」隔空行
    找到核对表的一整行 → 改由 LLM 读（召回代价，见夹具 docstring）；「两对_两行表单_上面标题编号」照样读出。
    网格文本一律 weak（用户 2026-09-30 裁定 ②：只作候选）。"""
    res = read_grid_fields(fx.recall_layouts(), "xlsx", "表单.xlsx")
    name, org, builder = "城中河综合整治工程", "某某区城市建设投资有限公司", "某某建设集团有限公司"
    assert _text_values(res) == [
        ("工程名称", "下接金额表头", name),
        ("工程名称", "单位行后接金额表头", name),
        ("工程名称", "两对_标段_清单", name),
        ("工程名称", "两对_空行后接金额表头", name),
        ("建设单位", "两对_空行后接金额表头", org),
        ("工程名称", "两对_下接表单", name),
        ("建设单位", "两对_下接表单", org),
        ("施工单位", "两对_下接表单", builder),
        ("工程名称", "两对_下接费用表", name),
        ("建设单位", "两对_下接费用表", org),
        ("建设单位", "块中间", org),
        ("施工单位", "块中间", builder),
        ("工程名称", "一格写完开头", name),
        ("建设单位", "一格写完开头", org),
        ("工程名称", "两对_下接合并值", name),
        ("建设单位", "两对_下接合并值", org),
        ("建设单位", "序号表单_无表头", org),
        ("工程名称", "两对_下接两格列头", name),
        ("建设单位", "两对_下接两格列头", org),
        ("建设单位", "标题页码_表单块", org),
        ("施工单位", "标题页码_表单块", builder),
        ("施工单位", "标题单位元_表单块", builder),
        ("工程名称", "两对_上面标题编号", name),
        ("建设单位", "两对_上面标题编号", org),
        ("工程名称", "两对_上面右侧标题编号", name),
        ("施工单位", "两对_上面右侧标题编号", builder),
        ("建设单位", "两对_两行表单_上面标题编号", org),
        ("施工单位", "两对_两行表单_上面标题编号", builder),
        ("工程名称", "两对_两行表单_上面标题编号", name),
    ], _text_values(res)
    assert {c["verify_level"] for c in res.candidates if c["kind"] != "amount"} == {"weak"}
    assert {c["verify_level"] for c in res.candidates if c["kind"] == "amount"} == {"strong"}, "金额不受影响"


def test_merged_label_looks_below_the_merged_region():
    """第三轮非阻断（变异 M6 没被抓到）：标签格跨两行合并（A2:A3「项目名称」、B2:B3「费用」），
    上面是表单行「建设单位|…」、下面第 4 行起是数据。「正下方」要从合并区底边往下算 —— 是数据，
    所以它不在一列表单标签中间，不出值；从 A3 算会读到合并区自己，误判成上下都是表单标签。"""
    res = read_grid_fields(fx.merged_label_head_below_form(), "xlsx", "明细.xlsx")
    assert _text_values(res) == [], _text_values(res)


def test_label_merged_into_the_header_block_is_part_of_the_header():
    """两级表头：「项目名称」占 A1:A2，第 2 行是金额表头。A1 的合并区伸进了表头，它是表头的一部分，
    不是「紧挨着金额表头的抬头」→ 不出值。"""
    res = read_grid_fields(fx.merged_label_over_header_block(), "xlsx", "明细.xlsx")
    assert _text_values(res) == [], _text_values(res)


def test_same_field_label_further_down_the_column_is_found():
    """第三轮非阻断（变异 M7 没被抓到）：同一列连续的表单标签里，「项目名称|内容」与「工程名称|城中河…」
    之间隔着一行「施工单位」。要沿整列往上 / 往下找，不能只看紧挨着的一行：两行都拿不准，不出工程名称；
    「施工单位」字段唯一 → 出值。"""
    res = read_grid_fields(fx.sheets({"概况": fx.SAME_FIELD_TWO_ROWS_APART}), "xlsx", "概况.xlsx")
    assert _text_values(res) == [("施工单位", "概况", "某某建设集团有限公司")], _text_values(res)


# ---------------------------------------------------------------- PR #768 第五轮：金额表头判定太粗 / 判据②删掉

def _amount_rows(res) -> set[str]:
    """读出的金额取自哪一行（合计行的行标签是「合计」）。"""
    return {c["evidence"]["row_label"] for c in res.candidates if c["kind"] == "amount"}


@pytest.mark.parametrize("sheet", sorted(fx.FALSE_HEADER_TRAPS))
def test_data_row_misread_as_amount_header_is_not_evidence(sheet):
    """第四轮评审阻断 1 (a)：`_header_block` 把两格提到「送审 / 审定 / 核减 / 核增 / 合同价」的数据行当成金额表头，
    它上面的列头行按判据③「紧挨在金额表头上面」读出 strong 列头词（「工程名称|审核意见 / 合同价|按签约合同价…」
    → 「审核意见」，5/5）。现在判据③要这张表真从合计行读出了金额、表头首行在标签列有标题、且那个标题不像金额列。"""
    res = read_grid_fields(fx.sheets({sheet: fx.FALSE_HEADER_TRAPS[sheet]}), "xlsx", "意见.xlsx")
    assert _names_and_heads(res) == [], res.candidates


def test_false_header_fixtures_reach_their_own_gate():
    """§5.2：两个夹具各只让一道闸拦得住 —— 这里核对它们真的走到了那道闸前面。
    「条目行像表头_单行数」读出了金额、但不是合计行（只有「合计行」那道闸拦得住）；
    「说明_核减金额_合计行」真从合计行读出了金额（只有「表头标签列不像金额列」那道闸拦得住）。"""
    single = read_grid_fields(fx.sheets({"x": fx.FALSE_HEADER_TRAPS["条目行像表头_单行数"]}), "xlsx", "x.xlsx")
    assert _amount_rows(single) == {"签证"}, single.candidates
    total = read_grid_fields(fx.sheets({"x": fx.FALSE_HEADER_TRAPS["说明_核减金额_合计行"]}), "xlsx", "x.xlsx")
    assert _amount_rows(total) == {"合计"}, total.candidates


@pytest.mark.parametrize("case", sorted(fx.TWO_LEVEL_HEADERS))
def test_two_level_header_group_title_is_not_a_project_name(case):
    """第四轮评审阻断 1 (b)：两级表头「项目名称|费用（B:D 合并）/（空）|送审金额|审定金额|核减金额」，条目列没有纵向合并、
    没有序号列 —— 改前读出 strong「费用」（组标题换成「工程造价」「结算审核情况」「审核情况」同样读出）；上一行排两对
    「项目名称|费用|工期|说明」时走判据①「下面是金额表头不算数据行」的豁免，也读出「费用」。
    表头首行在标签那一列没有标题 → 上一行是多级表头的上一级，不是抬头。夹具的合计行真读得出金额（第一道闸拦不住）。"""
    res = read_grid_fields(fx.two_level_header(**fx.TWO_LEVEL_HEADERS[case]), "xlsx", "审定单.xlsx")
    assert _names_and_heads(res) == [], res.candidates
    got = _by_field(res)
    assert [c["value"] for c in got["审定金额"]] == ["7200000"] and _amount_rows(res) == {"合计"}, res.candidates


@pytest.mark.parametrize("sheet", sorted(fx.CHECKLISTS))
def test_checklist_conclusions_are_not_values(sheet):
    """第四轮评审阻断 2：核对表「序号|检查项|结果 / 1|工程名称|相符 / 2|建设单位|基本相符 / 3|施工单位|不符」—— 结论各不相同，
    同值否决够不到；判据②（行首有序号）单独算正面证据 → 读出 strong「相符」。判据②删掉。
    只删判据②不够：工程名称排在中间时判据④（一列表单标签的中间）照样读出「相符」。现在一列表单标签（或一行两对）
    上面紧挨着一行列头（标签列上方不是表单标签、值列上方另有一格）→ 值是这张表那一列的数据，拿不准，不出值。"""
    res = read_grid_fields(fx.sheets({sheet: fx.CHECKLISTS[sheet]}), "xlsx", "核对.xlsx")
    assert _names_and_heads(res) == [], res.candidates


def test_checklist_header_is_found_above_merged_section_rows():
    """列头「序号|检查项|结果」和表体之间夹着合并成一格的分节行「一、基本信息」：分节行跳过，往上找到列头 →
    工程名称排在中间（判据④）、一行两对（判据①）都不出值。"""
    res = read_grid_fields(fx.checklist_with_merged_section_rows(), "xlsx", "核对.xlsx")
    assert _names_and_heads(res) == [], res.candidates


def test_checklist_over_amount_header_reaches_the_header_gate():
    """§5.2：「序号_紧压金额表头」的金额表真从合计行读出了金额、表头首行在标签那一列（B 列）有「单位工程」这个
    不像金额列的标题 —— 判据③自己的三道闸都拦不住，只有「上面是列头行」拦得住。"""
    res = read_grid_fields(fx.sheets({"x": fx.CHECKLISTS["序号_紧压金额表头"]}), "xlsx", "x.xlsx")
    assert _amount_rows(res) == {"合计"}, res.candidates


def test_two_pair_head_over_merged_data_rows():
    """评审探针 N3：一行两对的列头行，数据行把「条目 + 审核意见」合并成一格，审核日期 / 审核人照填 ——
    一格横跨几列、但这一行别的列有内容，是数据行，不是标题 / 说明行。"""
    res = read_grid_fields(fx.two_pair_head_over_merged_rows(), "xlsx", "意见.xlsx")
    assert _names_and_heads(res) == [], res.candidates


# ---------------------------------------------------------------- PR #768 第六轮：第五轮评审阻断 1 / 阻断 2 / 非阻断

@pytest.mark.parametrize("sheet", sorted(fx.ONE_HEAD_WORD_DATA_ROWS))
def test_data_row_with_one_head_word_is_still_a_data_row(sheet):
    """第五轮评审阻断 1：一行两对的列头行「工程名称|审核意见|审核日期|审核人」下面，第一条数据行里恰好有一格写了
    「单价」「工程量」「数量」（`_COLUMN_HEADS` 里的词）。改前 `_data_rows_below` 只要有一格是列头词就当「另一张表的
    列头」、不算数据行 → 判据①成立 → 读出 strong「审核意见」「调整内容」「变更内容」。
    另一张表的列头至少两格是列头词才算；只有一格的是数据行 → 这一行是列头行，不出值。"""
    res = read_grid_fields(fx.sheets({sheet: fx.ONE_HEAD_WORD_DATA_ROWS[sheet]}), "xlsx", "意见.xlsx")
    assert _names_and_heads(res) == [], res.candidates


@pytest.mark.parametrize("sheet", sorted(fx.ANNOTATION_ROW_CHECKLISTS))
def test_checklist_header_is_found_above_annotation_rows(sheet):
    """第五轮评审阻断 2：核对表的列头「检查项|结果」和表体之间夹着「（空）|（是/否）」「（空）|详见附表」「（空）|（√/×）」
    这种标签列空、值列有字的注释行。改前 `_column_header_above` 只跳过值列空的行，碰到它就停下判「不是列头」，
    否决失效 → 工程名称排在中间（判据④）或一行两对（判据①）读出 strong「相符」。标签列空着的注释行同样跳过。"""
    res = read_grid_fields(fx.sheets({sheet: fx.ANNOTATION_ROW_CHECKLISTS[sheet]}), "xlsx", "核对.xlsx")
    assert _names_and_heads(res) == [], res.candidates


@pytest.mark.parametrize("sheet", sorted(fx.HALF_ROW_CHECKLISTS))
def test_two_pair_checklist_header_is_found_above_a_half_filled_row(sheet):
    """第六轮自查（变异 B2c 存活时追出来的，改前改后第五轮版本都漏）：一行两对的核对表「检查项|结果|检查项|结果」，
    列头和「工程名称|相符|建设单位|不符」之间夹着一行只填了一对的数据「资料完整性|完整|（空）|（空）」。
    改前 `_column_header_above` 碰到这一行就停下（不是每一对都填满 → 判「不是列头」）→ 判据①读出 strong「相符」。
    这一行没有表单标签、又没填满 → 跳过它往上找，找到列头 → 否决。半行本身不当列头（召回夹具「两对_上面标题编号」）。"""
    res = read_grid_fields(fx.sheets({sheet: fx.HALF_ROW_CHECKLISTS[sheet]}), "xlsx", "核对.xlsx")
    assert _names_and_heads(res) == [], res.candidates


@pytest.mark.parametrize("sheet", sorted(fx.PLACEHOLDER_NAMES))
def test_bracket_placeholder_is_not_a_project_name(sheet):
    """第五轮评审非阻断：签章栏 / 空白模板里工程名称整格都是括号占位（「（盖章）」「（详见封面）」「(详见封面)」
    「（签字）（盖章）」）。带冒号、一格写完、一行两对都算正面证据，改前读出 strong 占位串。整格都是括号的不出值，写 note。"""
    res = read_grid_fields(fx.sheets({sheet: fx.PLACEHOLDER_NAMES[sheet]}), "xlsx", "签章.xlsx")
    assert [c for c in res.candidates if c["field"] == "工程名称"] == [], res.candidates
    assert any("工程名称" in n and "占位" in n for n in res.notes), res.notes


def test_bracketed_suffix_in_a_real_name_is_still_read():
    """占位过滤只认「整格都是括号」：「城中河综合整治工程（二期）」「（二期）城中河综合整治工程」照样读出；
    第七轮扩到【】〔〕［］[] 之后，「【二期】城中河…」「城中河…[二期]」同样照读。"""
    res = read_grid_fields(fx.sheets({"封面": [["工程名称：城中河综合整治工程（二期）"]],
                                      "抬头": [["工程名称", "（二期）城中河综合整治工程", "建设单位",
                                                "某某区城市建设投资有限公司"]],
                                      "方头": [["工程名称：【二期】城中河综合整治工程"]],
                                      "方括号": [["工程名称：城中河综合整治工程[二期]"]]}), "xlsx", "封面.xlsx")
    assert sorted(c["value"] for c in res.candidates if c["field"] == "工程名称") == sorted([
        "城中河综合整治工程（二期）", "（二期）城中河综合整治工程", "【二期】城中河综合整治工程",
        "城中河综合整治工程[二期]"]), res.candidates


# ---------------------------------------------------------------- PR #768 第七轮：第六轮评审阻断 + 用户裁定 ②

@pytest.mark.parametrize("sheet", sorted(fx.TWO_PAIR_BODY_CHECKLISTS))
def test_two_pair_checklist_later_body_rows_are_vetoed(sheet):
    """第六轮评审阻断：一行两对、带列头行的核对表，工程名称不在第一条表体行（W1–W6，另加空行 W7、第三条表体行 W8、
    右半行 W3r）。两对核对表的表体行本身是表单标签行，改前判据①从目标行往上找列头，碰到上面那条表体行就停下判
    「不是列头」→ 读出 strong「相符」「与合同一致」。现在先往上走过紧挨着的表单行到块顶，再找列头（和判据④一致）→ 否决。"""
    res = read_grid_fields(fx.sheets({sheet: fx.TWO_PAIR_BODY_CHECKLISTS[sheet]}), "xlsx", "核对.xlsx")
    assert _names_and_heads(res) == [], res.candidates


def test_two_pair_checklist_later_body_row_under_a_merged_section_row():
    """同上，列头和表体之间夹着合并成一格的分节行「一、基本信息」（A2:E2），工程名称在第二条表体行。"""
    res = read_grid_fields(fx.checklist_with_merged_section_rows(), "xlsx", "核对.xlsx")
    assert [c for c in _names_and_heads(res) if c[1] == "两对核对_第二条"] == [], res.candidates


def _grid_fixture_workbooks() -> list[tuple[str, bytes]]:
    """所有网格召回夹具与陷阱夹具（HEAD_TRAPS 等）：属性测试遍历用。"""
    books: list[tuple[str, bytes]] = [
        ("p2_shape", fx.p2_shape()), ("p2_shape_其它名称", fx.p2_shape(name="城南河综合治理工程")),
        ("p1_shape", fx.p1_shape()), ("summary_shape", fx.summary_shape()),
        ("summary_bill_header", fx.summary_with_bill_sheets(page_header=True)),
        ("summary_bill", fx.summary_with_bill_sheets(page_header=False)),
        ("kv_form_layouts", fx.kv_form_layouts()), ("recall_layouts", fx.recall_layouts()),
        ("conflicting_kv", fx.conflicting_kv()), ("conflicting_kv_same", fx.conflicting_kv(same=True)),
        ("overview", fx.sheets({"工程概况": fx.OVERVIEW_ROWS})),
        ("overview_no_name", fx.sheets({"工程概况": fx.OVERVIEW_ROWS_NO_NAME})),
        ("overview_name_head", fx.sheets({"概况": fx.OVERVIEW_ROWS_NAME_HEAD})),
        ("same_field_apart", fx.sheets({"概况": fx.SAME_FIELD_TWO_ROWS_APART})),
        ("merged_label_below_form", fx.merged_label_head_below_form()),
        ("merged_label_over_header", fx.merged_label_over_header_block()),
        ("checklist_merged_sections", fx.checklist_with_merged_section_rows()),
        ("two_pair_head_merged_rows", fx.two_pair_head_over_merged_rows()),
        ("p2_with_overview", fx.p2_with_sheet("工程概况", fx.OVERVIEW_ROWS)),
        ("p2_with_cover", fx.p2_with_sheet("封面", [["工程名称：", "城南河综合治理工程"]])),
    ]
    for group in ("DATA_TABLE_HEADS", "HEAD_TRAPS", "FALSE_HEADER_TRAPS", "CHECKLISTS", "ONE_HEAD_WORD_DATA_ROWS",
                  "ANNOTATION_ROW_CHECKLISTS", "HALF_ROW_CHECKLISTS", "PLACEHOLDER_NAMES", "TWO_PAIR_BODY_CHECKLISTS"):
        for name, rows in getattr(fx, group).items():
            books.append((f"{group}/{name}", fx.sheets({name: rows})))
    for name, kw in fx.TWO_LEVEL_HEADERS.items():
        books.append((f"TWO_LEVEL_HEADERS/{name}", fx.two_level_header(**kw)))
    return books


def test_grid_text_fields_are_never_strong_and_amounts_are_untouched():
    """用户 2026-09-30 裁定 ②（属性测试）：网格（approval_grid 键值通道，channel=grid）读出的**文本类字段**
    （工程名称、建设单位、施工单位 —— 所有非金额字段）一律 verify_level 不高于 weak、verified=False，
    不论正面证据多充分；这份文件的 LLM 照样问、阶段二照样补抽，最终值由合并决定。
    **金额类字段**（合计行读出的送审 / 审定 / 核减 / 核增 / 合同价）不受影响：照旧 strong、verified、没有候选标记。
    遍历所有召回夹具与陷阱夹具；非空断言防止「一个候选都没有」时恒真（铁律 8）。"""
    text_seen: dict[str, int] = {}
    capped = 0
    amount_seen = 0
    for name, book in _grid_fixture_workbooks():
        for c in read_grid_fields(book, "xlsx", f"{name}.xlsx").candidates:
            if c["channel"] != "grid":
                continue
            if c["kind"] == "amount":
                amount_seen += 1
                assert c["verify_level"] == "strong" and c["verified"] is True, (name, c)
                assert "grid_text_candidate" not in c["verify_notes"], (name, c)
                continue
            text_seen[c["field"]] = text_seen.get(c["field"], 0) + 1
            assert c["verify_level"] != "strong" and c["verified"] is False, (name, c)
            if c["verify_level"] == "weak":
                capped += "grid_text_candidate" in c["verify_notes"]
    # 三个文本字段都真被读到过，且都有正面证据充分（改前会是 strong）的读数被压到 weak
    assert set(text_seen) == {"工程名称", "建设单位", "施工单位"}, text_seen
    assert all(n >= 3 for n in text_seen.values()), text_seen
    assert capped >= 20, capped
    assert amount_seen >= 20, amount_seen


@pytest.mark.parametrize("field", ["工程名称", "建设单位", "施工单位"])
def test_each_grid_text_field_with_full_evidence_is_weak(field):
    """同一条性质按字段各钉一次：召回夹具里正面证据最充分的读数（一行两对 / 块中间 / 紧挨金额表头）也只到 weak，
    并带 grid_text_candidate 标记 —— 上限不能只作用于工程名称。"""
    res = read_grid_fields(fx.recall_layouts(), "xlsx", "表单.xlsx")
    got = [c for c in res.candidates if c["field"] == field]
    assert got, res.candidates
    for c in got:
        assert (c["verify_level"], c["verified"]) == ("weak", False), c
        assert "grid_text_candidate" in c["verify_notes"], c


def test_two_different_readings_in_one_workbook_are_never_strong():
    """同一本工作簿里同一字段读出两个不同的值 → 一律不给 strong（weak），并写 note。
    strong 的后果是这份文件的 LLM 不再问这个字段、阶段二也不补抽 —— 拿不准时不能这样。"""
    res = read_grid_fields(fx.conflicting_kv(), "xlsx", "汇总.xlsx")
    names = [(c["value"], c["verify_level"], c["verified"]) for c in res.candidates if c["field"] == "工程名称"]
    assert sorted(names) == [("城中河综合整治工程", "weak", False),
                             ("城中河综合整治工程（二期）", "weak", False)], names
    assert all("grid_readings_conflict" in c["verify_notes"] for c in res.candidates if c["field"] == "工程名称")
    assert any("工程名称" in n and "不同" in n for n in res.notes), res.notes
    # 别的字段只读出一个值，不受牵连（第七轮起网格文本一律 weak，但不带冲突标记）
    (org,) = [c for c in res.candidates if c["field"] == "建设单位"]
    assert "grid_readings_conflict" not in org["verify_notes"], org
    # 同一个名称写两遍不算冲突
    same = read_grid_fields(fx.conflicting_kv(same=True), "xlsx", "汇总.xlsx")
    assert not [c for c in same.candidates if "grid_readings_conflict" in c["verify_notes"]], same.candidates
    assert not [n for n in same.notes if "不同" in n], same.notes


def test_p1_shape_without_net_column():
    """② 列顺序 送审 / 审定 / 核增 / 核减，没有净核列 → 核减 = 330。"""
    got = _by_field(read_grid_fields(fx.p1_shape(), "xlsx", "审定单.xlsx"))
    assert [c["value"] for c in got["核减金额"]] == ["330"]
    assert [c["value"] for c in got["核增额"]] == ["0"]


def test_summary_shape_takes_total_audit_column_and_number_format():
    """③ 汇总表：审定金额横跨 E3:G3 → 只认子标题「合计审定金额」的 G 列；
    值是浮点、格式「0」→ 展示串按格式取整（正式数），amount_yuan 保留到分。"""
    got = _by_field(read_grid_fields(fx.summary_shape(), "xlsx", "明细.xlsx"))
    (aud,) = got["审定金额"]
    assert aud["evidence"]["cell"] == "G12", aud
    assert aud["value"] == "10613893" and aud["amount_yuan"] == "10613893.46"
    (cut,) = got["核减金额"]
    assert cut["value"] == "1418635" and cut["amount_yuan"] == "1418635.50", cut
    assert cut["evidence"]["cell"] == "I12" and cut["evidence"]["col_label"] == "核减"
    assert [c["value"] for c in got["送审金额"]] == ["11894328"]
    assert got["送审金额"][0]["amount_yuan"] == "11894327.96"


def test_hidden_sheet_is_skipped():
    """④ 隐藏表里的示例金额不读（QA:report-12）；可见表没有金额 → 零候选，note 说明跳过了隐藏表。"""
    res = read_grid_fields(fx.hidden_example_shape(), "xlsx", "模板.xlsx")
    assert res.candidates == []
    assert any("hidden" in n and "示例" in n for n in res.notes), res.notes


def test_no_total_row_with_two_data_rows_yields_nothing():
    """⑤ 没有合计行、有 2 行数据 → 不猜哪一行是合计，不出值，note 写明。"""
    res = read_grid_fields(fx.no_total_two_rows(), "xlsx", "审定单.xlsx")
    assert not [c for c in res.candidates if c["field"] in ("送审金额", "审定金额", "核减金额")]
    assert any("没有合计行" in n for n in res.notes), res.notes


def test_duplicate_semantic_columns_are_ambiguous():
    """⑥ 两列都叫「核减金额」→ 不出值，note「列歧义」；其它列照常出。"""
    res = read_grid_fields(fx.duplicate_reduction_columns(), "xlsx", "审定单.xlsx")
    got = _by_field(res)
    assert "核减金额" not in got
    assert [c["value"] for c in got["送审金额"]] == ["100000"]
    assert any("列歧义" in n and "核减金额" in n for n in res.notes), res.notes


def test_display_follows_supported_number_formats_only():
    d = Decimal("11894327.9609491")
    assert display(d, "General") == "11894327.9609491"
    assert display(d, "0") == "11894328"
    assert display(d, "0_ ") == "11894328"
    assert display(d, "0.00") == "11894327.96"
    assert display(d, "#,##0") == "11,894,328"
    assert display(d, "#,##0.00") == "11,894,327.96"
    assert display(d, '"¥"#,##0.00;[Red]"¥"-#,##0.00') == "11894327.9609491", "不认识的格式用原值，不猜"


def test_non_spreadsheet_and_unreadable_bytes_do_not_raise():
    assert read_grid_fields(b"not a zip", "xlsx", "坏.xlsx").candidates == []
    assert read_grid_fields(b"anything", "pdf", "x.pdf").candidates == []


def test_group_title_only_semantics_needs_merge_expansion():
    """「审定」二字只在合并的组标题 E3:G3 里、子标题只写「合计」：展开合并区后 G 列的标题是
    「审定金额|合计」才认得出来；不展开就只剩「合计」，审定金额读不出来。"""
    got = _by_field(read_grid_fields(fx.summary_shape(total_label="合计"), "xlsx", "明细.xlsx"))
    (aud,) = got["审定金额"]
    assert aud["evidence"]["cell"] == "G12" and aud["evidence"]["col_label"] == "审定金额|合计", aud


def test_amount_column_semantics_are_strict():
    """列语义严格判定（AMOUNT_COLUMN_RULES）：净核减 / 核增减 / 合同内外都不许被当成对应金额。"""
    assert amount_column_semantic("净核减金额（元）") == NET_REDUCTION
    assert amount_column_semantic("净核金额") == NET_REDUCTION
    assert amount_column_semantic("审减净额") == NET_REDUCTION
    assert amount_column_semantic("核减净额") is None, "含「净」的核减列不是毛额核减"
    assert amount_column_semantic("其中|核减金额（元）") == "核减金额"
    assert amount_column_semantic("核增减合计") is None
    assert amount_column_semantic("其中|核增金额（元）") == "核增额"
    assert amount_column_semantic("送审价（元）") == "送审金额"
    assert amount_column_semantic("报审金额") == "送审金额"
    assert amount_column_semantic("审核定案金额") == "审定金额"
    assert amount_column_semantic("合同价金额") == "合同价"
    assert amount_column_semantic("合同内") is None and amount_column_semantic("合同外金额") is None
    assert amount_column_semantic("单位工程名称") is None


# ---------------------------------------------------------------- issue #783（PR #768 收尾评审 non_blocking ③）

@pytest.mark.parametrize("rows", [
    [["工程名称", "城中河综合整治工程", "建设单位", "（盖章）"]],
    [["工程名称", "城中河综合整治工程", "施工单位", "不符"]],
    [["工程名称：城中河综合整治工程"], ["建设单位：（盖章）"], ["施工单位：不符"]],
], ids=["一行两对_盖章", "一行两对_不符", "一列冒号"])
def test_unverified_grid_text_stays_none_and_is_not_marked_a_candidate(rows):
    """`_cap_grid_text` 只把 strong 压到 weak：本来就是 none 的读数（建设单位 / 施工单位读出「（盖章）」「不符」这类
    不带机构后缀的值，verify_notes 带 not_org_name）保持 none、verified=False，不带 grid_text_candidate —— 抬到 weak
    会让它和正面证据充分的读数同桶，压过原文未命中的别的来源（收尾评审变异 M13 把 none 也抬到 weak，全量照样绿）。
    同一张表里工程名称是正常读数：weak + grid_text_candidate，说明这张表确实走过了上限那一步。"""
    res = read_grid_fields(fx.sheets({"签章": rows}), "xlsx", "签章.xlsx")
    orgs = [c for c in res.candidates if c["field"] in ("建设单位", "施工单位")]
    assert orgs, res.candidates
    for c in orgs:
        assert (c["verify_level"], c["verified"]) == ("none", False), c
        assert "not_org_name" in c["verify_notes"] and "grid_text_candidate" not in c["verify_notes"], c
    (name,) = [c for c in res.candidates if c["field"] == "工程名称"]
    assert (name["verify_level"], name["verified"]) == ("weak", False), name
    assert "grid_text_candidate" in name["verify_notes"], name


def test_fixture_wide_none_readings_are_never_lifted():
    """同一条性质在全部召回 / 陷阱夹具上：凡是 grid_text_candidate 标记的读数，都是从 strong 压下来的 weak；
    none 读数一条都不带这个标记。非空断言：夹具里真有 none 读数（占位类夹具的「（盖章）」），不然恒真（铁律 8）。"""
    nones = 0
    for name, book in _grid_fixture_workbooks():
        for c in read_grid_fields(book, "xlsx", f"{name}.xlsx").candidates:
            if c["channel"] != "grid" or c["kind"] == "amount":
                continue
            if c["verify_level"] == "none":
                nones += 1
                assert "grid_text_candidate" not in c["verify_notes"], (name, c)
            if "grid_text_candidate" in c["verify_notes"]:
                assert c["verify_level"] == "weak", (name, c)
    assert nones >= 4, nones
