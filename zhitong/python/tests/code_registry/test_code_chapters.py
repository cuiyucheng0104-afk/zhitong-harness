# 来源：engine-service/tests/test_code_chapters.py（zhitong-cost-ai@991ff5cd）
"""WS08-06 码表与章节口径统一（issue #724；D43 章名以 GB 2013 为准、D53 编码版本只用 zj2025）。

旧版：zj2025 码表 chapters 只有 0101–0116、0118；查不到就「其他」；chapter_of 直接取前 4 位；
costsheet 先去掉所有非数字再归章、非 01 附录只按前 2 位归章；tk_align 不补前导 0。于是
安装 11 章里 10 章叫「其他」（占金额 99.79%）、0117 措施项目叫「其他」、01B047 被拆进 0104、
01B001 成了伪章节 01B0、丢了前导 0 的 11 位编码归「其他」，三个端点章名互不一致。

变异验收：删掉补 0 / 回退为去非数字取前 4 位 / 删掉 2013 章名表兜底 / 删掉 label 去重 —— 各自用例转红。
"""
from __future__ import annotations

import pytest

from zt.code_registry import registry as cr
from zt.indicator import engine as indicator_engine
from zt.reconcile import engine as reconcile_engine
from zt.tk import align as tk_align
from zt.tk import engine as tk_engine
from zt.costsheet.parser import parse_costsheet
from tests.costsheet.fixtures import costsheet_shapes as shapes


# ---------------------------------------------------------------- 章名

def test_0117_and_0118_are_both_measures():
    assert cr.classify_chapter("011701001001").name == "措施项目"
    assert cr.classify_chapter("Z011801001").name == "措施项目"
    assert cr.chapter_name("0117") == "措施项目"
    assert cr.chapter_name("0118") == "措施项目"


@pytest.mark.parametrize("code,key,name", [
    ("030404017001", "0304", "电气设备安装工程"),
    ("030101001001", "0301", "机械设备安装工程"),
    ("031001006001", "0310", "给排水、采暖、燃气工程"),
    ("040201004001", "0402", "道路工程"),
    ("050101001001", "0501", "绿化工程"),
    ("010401003001", "0104", "砌筑工程"),
])
def test_standard_chapter_names_from_2013_table(code, key, name):
    ch = cr.classify_chapter(code)
    assert (ch.key, ch.name) == (key, name)
    assert ch.standard


def test_unknown_chapter_in_known_appendix_is_written_as_code_never_other():
    # WS26-h2（07-010 第 1 项）：兜底不再是「附录名·章码」——查不到的章不给它安一个专业名
    ch = cr.classify_chapter("020101001001")
    assert ch.name == "章码 0201（章名表里没有）"
    assert ch.appendix_name == "仿古建筑工程"
    assert not ch.standard


# ---------------------------------------------------------------- 编码规范化

def test_eleven_digit_code_is_padded_and_goes_to_pipe_network():
    nc = cr.normalize_code("40504001004")
    assert (nc.kind, nc.code, nc.padded) == (cr.GB, "040504001004", True)
    assert cr.normalize_code(40504001004).code == "040504001004", "编码列存成数字也一样"
    assert (cr.classify_chapter("40504001004").key, cr.classify_chapter("40504001004").name) \
        == ("0405", "管网工程")


def test_eight_digit_code_is_padded_to_nine():
    assert cr.normalize_code("10101001").code == "010101001"


def test_material_codes_and_amounts_are_not_padded_into_gb_codes():
    """00010101（工日编码）补 0 后附录码 00 不合法 → 不当国标编码。"""
    assert cr.normalize_code("00010101").kind == cr.NON_GB


def test_fullwidth_whitespace_and_z_prefix():
    nc = cr.normalize_code(" Ｚ０１０１０１００１ ")
    assert (nc.kind, nc.code, nc.z_prefix, nc.display) == (cr.GB, "010101001", True, "Z010101001")


def test_supplement_code_with_section_goes_to_section_chapter():
    ch = cr.classify_chapter("01B047", section="0104 砌筑工程")
    assert (ch.key, ch.name) == ("0104", "砌筑工程")


def test_supplement_code_without_section_is_appendix_supplement():
    ch = cr.classify_chapter("01B047")
    assert (ch.key, ch.name) == ("01B", "房屋建筑与装饰补充项目")
    ch2 = cr.classify_chapter("01B001")
    assert ch2.key == "01B", "旧版 code_registry.chapter_of 给出伪章节 01B0"


def test_supplement_code_with_other_appendix_section_is_not_moved():
    """section 的章码不在同一附录时不采信（04B003 在 0104 标题下也不归房建砌筑）。"""
    assert cr.classify_chapter("04B003", section="0104 砌筑工程").key == "04B"


def test_non_gb_and_no_code():
    assert (cr.classify_chapter("LC2020").key, cr.classify_chapter("LC2020").name) == ("NG", "非国标编号项")
    assert (cr.classify_chapter("").key, cr.classify_chapter("").name) == ("00", "无编码项")
    assert cr.classify_chapter(None, section="S.1脚手架工程（编码：011701）").key == "0117"


def test_costsheet_items_carry_classified_chapter_and_section():
    out = parse_costsheet(shapes.s1_title_rows(), "s1.xlsx")
    by_code = {(i["sheet"], i["code"]): i for i in out["items"]}
    sup = by_code[("1#楼建筑", "01B047")]
    assert (sup["chapter"], sup["chapter_name"], sup["section"]) == ("0104", "砌筑工程", "0104 砌筑工程")
    nocode = next(i for i in out["items"] if i["name"] == "砖砌检查井")
    assert nocode["chapter"] == "0104"
    assert sup["appendix_name"] == "房屋建筑与装饰工程"


# ---------------------------------------------------------------- 三处统一

def test_same_item_has_same_chapter_name_in_all_three_endpoints():
    raw = shapes.zheda_install_two_row()
    items = {i["code"]: i for i in parse_costsheet(raw, "安装.xlsx")["items"]}
    ind = indicator_engine.run([(raw, "安装.xlsx")], {"gross_area": 100}, None)
    ind_ch = {c["chapter"]: c["chapter_name"] for c in ind["chapters"]}
    # 审定侧用另存的一份：同一份单列合价表放两侧现在会被拦（WS26-b，issue #800）
    rec = reconcile_engine.run(raw, "a.xlsx", shapes.resaved(raw), "b.xlsx")
    rec_ch = {r["item_code"]: r["chapter_name"] for r in rec["rows"]}
    rows = tk_engine.costsheet_items_to_rows(list(items.values()), "P1", "安装.xlsx")
    for code, it in items.items():
        assert ind_ch[it["chapter"]] == it["chapter_name"] == rec_ch[code]
    assert {r["major"] for r in rows} == {"通用安装工程"}, "投控 major 取附录名"


def test_labels_are_unique_when_chapter_names_collide():
    """市政 0401 与房建 0101 都叫「土石方工程」：同一次结果里 label 追加（章码）。"""
    out = indicator_engine.compute_indicators([
        {"code": "010101001001", "name": "平整场地", "amount": 100.0},
        {"code": "040101001001", "name": "挖一般土方", "amount": 200.0},
        {"code": "010401003001", "name": "实心砖墙", "amount": 300.0},
    ], {"gross_area": 10})
    labels = [c["label"] for c in out["chapters"]]
    assert len(labels) == len(set(labels))
    assert "土石方工程（0101）" in labels and "土石方工程（0401）" in labels
    assert "砌筑工程" in labels, "不重名的 label 就是章名"


def test_install_file_has_no_other_chapter_and_full_coverage():
    raw = shapes.zheda_install_two_row()
    ind = indicator_engine.run([(raw, "安装.xlsx")], {"gross_area": 100}, None)
    assert all(c["chapter_name"] != "其他" for c in ind["chapters"])
    assert ind["chapter_coverage"] == 1.0
    assert "chapter_coverage_low" not in [w["code"] for w in ind["warning_items"]]


def test_chapter_coverage_low_is_info():
    ind = indicator_engine.compute_indicators([
        {"code": "LC2020", "name": "窗", "amount": 900.0},
        {"code": "010101001001", "name": "平整场地", "amount": 100.0},
    ])
    assert ind["chapter_coverage"] == 0.1


def test_tk_align_matches_eleven_digit_code_to_twelve_digit_baseline():
    idx = tk_align.build_index([{"project_id": "P", "item_code": "040504001004", "item_name": "检查井",
                                 "unit": "座"}])
    # WS08-07：align_row 改回 Alignment（base / method / reason / candidates）
    al = tk_align.align_row({"project_id": "P", "item_code": "40504001004",
                             "item_name": "检查井", "unit": "座"}, idx)
    assert al.base is not None and al.method == tk_align.EXACT
