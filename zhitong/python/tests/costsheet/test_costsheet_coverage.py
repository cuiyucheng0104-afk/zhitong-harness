# 来源：engine-service/tests/test_costsheet_coverage.py（zhitong-cost-ai@991ff5cd）
"""WS08-02 sheet 级状态、跳表告警、合计勾稽与覆盖率（issue #724）。

旧版：找不到表头就 continue、不写任何告警；sheets_used 在取行之前就 append；
只有 0 行时才告警 —— 浙大第五期 7 张明细表（占合同额 76.4%）被整表静默跳过，
warnings 却是 null，meta.sheets 里反倒列出了零贡献的表（QA:tk-02、reconcile-03）。

变异验收：删掉跳表告警 / 勾稽容差改成恒通过 / meta.sheets 改回列出所有认出表头的表 —— 各自用例转红。
"""
from __future__ import annotations

from zt.costsheet.parser import parse_costsheet
from tests.costsheet.fixtures import costsheet_shapes as shapes


def _codes(out: dict) -> list[str]:
    return [w["code"] for w in out["warning_items"]]


def test_two_row_header_sheet_is_used():
    out = parse_costsheet(shapes.zheda_install_two_row(), "安装.xlsx")
    d = out["meta"]["sheets_detail"][0]
    assert d["status"] == "used"
    assert d["header_rows"] == [2, 3]
    assert d["leaf_rows"] == 3 and d["amount_sum"] == 13260.0
    assert d["total_row_amount"] == 13260.0 and d["total_ratio"] == 1.0


def test_broken_header_with_codes_warns_and_coverage_is_poor():
    """列头被改坏但数据行有 12 位编码 → sheet_skipped_has_items（error）；
    可识别清单表金额覆盖率 40000 /（40000 + 60000）= 40% → poor，仍出结果（D42）。"""
    out = parse_costsheet(shapes.header_broken_with_codes(), "浙大第五期.xlsx")
    detail = {d["sheet"]: d for d in out["meta"]["sheets_detail"]}
    assert detail["改坏表头"]["status"] == "no_header"
    skipped = [w for w in out["warning_items"] if w["code"] == "sheet_skipped_has_items"]
    assert len(skipped) == 1 and skipped[0]["sheet"] == "改坏表头" and skipped[0]["level"] == "error"
    cov = out["meta"]["coverage"]
    assert cov["level"] == "poor"
    assert cov["ratio"] == 0.4
    assert cov["amount_used"] == 40000.0 and cov["amount_skipped_estimate"] == 60000.0
    assert cov["skipped_sheets"] == ["改坏表头"]
    assert "coverage_poor" in _codes(out)
    assert out["meta"]["parsed_total"] == 40000.0, "poor 照常出结果"


def test_total_row_mismatch_one_percent_is_flagged():
    out = parse_costsheet(shapes.detail_with_total(20200), "偏差1%.xlsx")
    w = [w for w in out["warning_items"] if w["code"] == "sheet_total_mismatch"]
    assert len(w) == 1 and "20,000.00" in w[0]["message"] and "20,200.00" in w[0]["message"]


def test_total_row_within_half_percent_is_not_flagged():
    out = parse_costsheet(shapes.detail_with_total(20060), "偏差0.3%.xlsx")
    assert "sheet_total_mismatch" not in _codes(out)
    assert out["meta"]["sheets_detail"][0]["total_row_amount"] == 20060.0


def test_meta_sheets_lists_only_contributing_sheets():
    """meta.sheets 只列 used 的表：工日表、台班表、材料表、费用表、汇总表都不在里面。"""
    out = parse_costsheet(shapes.labor_machine_tables(), "市政控制价.xlsx")
    assert out["meta"]["sheets"] == ["分部分项清单与计价表"]
    assert len(out["meta"]["sheets_detail"]) == 4
    door = parse_costsheet(shapes.door_three_block(), "门窗.xlsx", side="audit")
    assert door["meta"]["sheets"] == ["6#楼", "7#楼"]


def test_title_skipped_sheets_are_disclosed_as_info_only():
    out = parse_costsheet(shapes.fee_table_13(), "房建控制价.xlsx")
    w = [w for w in out["warning_items"] if w["code"] == "sheets_skipped_by_title"]
    # WS26-e：表名在 sheets 里，message 只写张数和按跳过词的计数
    assert len(w) == 1 and w[0]["level"] == "info" and any("单位工程招标控制价费用表" in n for n in w[0]["sheets"])
    assert w[0]["message"].startswith("按标题跳过 1 张表（") and "单位工程招标控制价费用表" not in w[0]["message"]
    assert "sheet_skipped_has_items" not in _codes(out)


def test_file_coverage_ok_and_checked_rows():
    out = parse_costsheet(shapes.zheda_three_row_header(), "浙大.xlsx")
    cov = out["meta"]["coverage"]
    assert cov["level"] == "ok" and cov["status"] == "parsed"
    assert cov["checked_rows"] == 3, "本期为 0 的那一行不算「有金额可查」"
    assert cov["leaf_rows"] == 4


def test_every_sheet_has_status_and_reason():
    out = parse_costsheet(shapes.labor_machine_tables(), "市政控制价.xlsx")
    for d in out["meta"]["sheets_detail"]:
        assert d["status"] in ("used", "skipped_by_title", "skipped_non_list", "no_header",
                               "ambiguous", "summary", "unpriced")
        if d["status"] != "used":
            assert d["reason"], f"{d['sheet']} 被跳过却没说原因"
