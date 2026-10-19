# 来源：engine-service/tests/test_report_sections.py（zhitong-cost-ai@991ff5c，W3 搬入；只改了 import）
"""WS07 K2：审核报告正文的章节原文 + 锚定正则（report_sections）。"""
from __future__ import annotations

from zt.report.sections import cut_sections, page_at, regex_fields, section_fields
from tests.report import _grid_fixtures as fx


def _vals(cands, field):
    return [c["value"] for c in cands if c["field"] == field]


def test_net_reduction_first_does_not_steal_gross_reduction():
    """⑦ 净核减在前：「净核减造价为1280435元，其中核减造价为1418635元」→ 核减 = 1418635。
    夹具故意让净核减先出现，`(?<!净)` 那条后顾断言才考得到（去掉它，第一处命中就是 1280435）。"""
    text = "净核减造价为1280435元，其中核减造价为1418635元、核增造价为138200元"
    got = regex_fields(text)
    assert _vals(got, "核减金额") == ["1418635元"], got
    assert _vals(got, "核增额") == ["138200元"]
    c = next(x for x in got if x["field"] == "核减金额")
    assert c["amount_yuan"] == "1418635.00" and c["verify_level"] == "strong"
    assert c["channel"] == "regex_fulltext", "找不到章节时对全文跑，排序低于章节内的 regex"


def test_approximate_numbers_are_not_taken():
    """⑧ 「核减造价约7.3万元」是近似数，不取（连接词只许 为 / 是 / 冒号）。"""
    assert regex_fields("核减造价约7.3万元") == []
    assert regex_fields("核减造价为约7.3万元") == []


def test_standard_four_chapter_report():
    """⑨ 标准四章报告：审核依据 = 第二章全文（不含第三章首行），金额只在「审核结果 / 项目概况」里取。"""
    text = "\n".join(fx.REPORT_PARAGRAPHS)
    secs = cut_sections(text)
    assert [s.canon for s in secs] == ["项目概况", "审核依据", "相关事项", "审核结果"]
    narr = section_fields(text, sections=secs)
    basis = next(c for c in narr if c["field"] == "审核依据")
    assert basis["value"] == ("1、施工合同及补充协议；\n2、竣工图纸及设计变更；\n"
                              "3、浙江省建设工程计价依据（2018版）。")
    assert "三、相关事项审核说明" not in basis["value"] and "外架" not in basis["value"]
    assert basis["value"] == basis["quote"] and basis["channel"] == "section"
    assert basis["evidence"]["heading"] == "二、审核依据"
    notes = next(c for c in narr if c["field"] == "相关事项审核说明")
    assert notes["value"].startswith("1、外架拆除时间") and "四、审核结果" not in notes["value"]
    money = regex_fields(text, sections=secs)
    assert _vals(money, "送审金额") == ["11894328元"]
    assert _vals(money, "审定金额") == ["10613893元"]
    assert _vals(money, "核减金额") == ["1418635元"]
    assert {c["channel"] for c in money} == {"regex"}
    assert {c["evidence"]["heading"] for c in money} == {"四、审核结果"}


def test_numbers_in_basis_chapter_are_not_scanned():
    """审核依据里引用的标准条文带数（「2018版」「合同价 5000 元」）不是结论：锚定正则只跑结果 / 概况两章。"""
    text = "\n".join(["二、审核依据", "合同价为5000元的零星工程参照执行。", "四、审核结果",
                      "签约合同价为10500000元。"])
    assert _vals(regex_fields(text), "合同价") == ["10500000元"]


def test_fulltext_keeps_every_distinct_value():
    """找不到章节时对全文跑：两个不同的合同价都出候选（交给合并判冲突），不只取第一处静默丢掉第二处。"""
    got = regex_fields("封面：合同价：1234567.00元\n变更：合同价：9999999.00元\n合同价：1234567.00元")
    assert _vals(got, "合同价") == ["1234567.00元", "9999999.00元"]


def test_rate_and_contract_duration():
    got = regex_fields("四、审核结果\n核减率为10.77%，合同工期180日历天，实际工期213天。")
    assert _vals(got, "核减率") == ["10.77%"]
    assert _vals(got, "工期") == ["180日历天"], "决策 D37：只取合同工期，实际工期不取"


def test_page_anchor_backfill():
    text = "[p1]\n封面\n[p3] ｜OCR\n四、审核结果\n审定造价为100元。"
    got = regex_fields(text)
    assert got[0]["evidence"]["page"] == 3
    assert page_at(text, 0) is None
