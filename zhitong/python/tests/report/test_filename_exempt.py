"""文件名豁免 ``zt.report.filename_exempt.exempt_spans``（迁自旧仓 tests/test_guard_filename.py，WS21-e / 总纲 K-R19）。

旧仓最后一例（``answer_guard`` 数字回链共用同一函数）依赖问答护栏，zt 没有搬问答护栏，不迁。
报告护栏对这个函数的接入由 ``test_report_guard.py`` 钉着。
"""
from __future__ import annotations

from zt.report.filename_exempt import exempt_forms, exempt_spans, stem_of

_GBQ = "北苑街道一标段1022.GBQ7"


def _exempted(text: str, names: list[str]) -> list[str]:
    return [text[a:b] for a, b in exempt_spans(text, names)]


def test_pure_digit_stem_is_not_exempt():
    """清单里有 `1200.xlsx` 时「合同价 1200 元」不豁免：主名 1200 没有汉字或字母。
    带着扩展名写出来（全名）才算文件名。"""
    assert _exempted("合同价 1200 元", ["1200.xlsx"]) == []
    assert _exempted("见 1200.xlsx 第 3 行", ["1200.xlsx"]) == ["1200.xlsx"]
    assert exempt_forms(["1200.xlsx"]) == {"1200.xlsx"}


def test_full_name_and_qualified_stem_are_exempt():
    """「《北苑街道一标段1022.GBQ7》」与不带书名号、不带扩展名的「北苑街道一标段1022」都豁免。"""
    assert _exempted(f"见《{_GBQ}》", [_GBQ]) == [_GBQ]
    assert _exempted("北苑街道一标段1022 的合同价", [_GBQ]) == ["北苑街道一标段1022"]


def test_half_of_a_stem_is_not_exempt():
    """「一标段1022」只是主名的后半截：不豁免（逐字相等，不做子串、模糊匹配，铁律 3）。"""
    assert _exempted("一标段1022 万元", [_GBQ]) == []


def test_book_title_marks_alone_are_not_a_reason():
    """「《合同价1022万元的说明》」不是任何一份资料的名字：书名号本身不是豁免理由。"""
    assert _exempted("《合同价1022万元的说明》", [_GBQ]) == []
    assert _exempted("《合同价1022万元的说明》", []) == []


def test_short_or_wordless_stems_and_number_boundaries():
    """主名不足 4 个字符的不豁免；写法以数字结尾、正文里后面紧跟数字或小数点的不算命中（那是一个更长的数）。"""
    assert _exempted("见表1 合计 300 元", ["表1.xlsx"]) == []
    assert _exempted("结算汇总2024", ["结算汇总2024.xlsx"]) == ["结算汇总2024"]
    assert _exempted("结算汇总20245 元", ["结算汇总2024.xlsx"]) == []
    assert stem_of("a.b.pdf") == "a.b" and stem_of("无扩展名") == "" and stem_of(".hidden") == ""


def test_spans_are_positions_in_the_given_text():
    text = f"甲 {_GBQ} 乙 {_GBQ}"
    spans = exempt_spans(text, [_GBQ])
    assert [text[a:b] for a, b in spans] == [_GBQ, _GBQ]
    assert spans == sorted(spans) and spans[0][0] == text.index(_GBQ)
    assert exempt_spans("", [_GBQ]) == [] and exempt_spans("正文", []) == []
