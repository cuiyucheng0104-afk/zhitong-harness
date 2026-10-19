# 来源：engine-service/tests/test_parse_audit_summary.py（zhitong-cost-ai@991ff5cd）
"""parse_audit_summary —— 多行多列审核汇总表的带溯源读法（总纲 K27，WS08-A 交付给 WS12-B / WS07；issue #724）。

与 parse_costsheet 的区别：报告取数要的是**原样的每一格**——
  · 合计 / 累计 / 派生段的行保留（kind=total / derived），不截断丢弃；
  · 金额是 Decimal 字符串（float 走 repr，不带二进制尾差）；
  · 每个值带单元格坐标，可回链到原格。
"""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

from zt.costsheet.parser import parse_audit_summary
from tests.costsheet.fixtures import costsheet_shapes as shapes
from tests.costsheet.test_costsheet_audit_summary import _audit_summary_xlsx

# zt 改动：真实语料根目录由环境变量 ZT_NAS_DATA 指定（旧仓写死开发机路径）；未设置时这些用例跳过
NAS_DATA = Path(os.environ.get("ZT_NAS_DATA") or "/nonexistent/zt-nas-data")
REAL_SAMPLE = (NAS_DATA / "project/30002/3、审核汇总表(1).xlsx")


def test_rows_keep_totals_and_derived_segment_with_provenance():
    out = parse_audit_summary(_audit_summary_xlsx(), "3、审核汇总表.xlsx", file_id="F32")
    assert out["file_id"] == "F32"
    (sh,) = out["sheets"]
    assert sh["header_rows"] == [4]
    kinds = [(r["name"], r["kind"]) for r in sh["rows"]]
    assert kinds[:4] == [("土建工程", "item"), ("安装工程", "item"), ("钢结构", "item"), ("气动物流", "item")]
    assert ("累计完成总产值（1——4之和）", "total") in kinds
    assert ("截止上期累计完成产值", "derived") in kinds
    assert ("钢结构", "derived") in kinds, "派生段里同名的「钢结构」保留但标为 derived"
    first = sh["rows"][0]
    assert first["values"]["submit.amount"] == "289061595.12"
    assert first["values"]["audit.amount"] == "288950262.04"
    assert first["values"]["delta.amount"] == "111333.08"
    assert first["cells"] == {"submit.amount": "C5", "audit.amount": "D5", "delta.amount": "E5"}
    cols = {c["key"]: c for c in sh["columns"]}
    assert cols["submit.amount"]["path"] == "报审金额(元)" and cols["submit.amount"]["col"] == "C"


def test_values_are_exact_decimal_strings():
    (sh,) = parse_audit_summary(_audit_summary_xlsx(), "x.xlsx")["sheets"]
    for r in sh["rows"]:
        for v in r["values"].values():
            Decimal(v)      # 可无损转回 Decimal
            assert "e" not in v.lower()


def test_checks_compare_item_sum_with_first_total_row():
    (sh,) = parse_audit_summary(_audit_summary_xlsx(), "x.xlsx")["sheets"]
    chk = {c["key"]: c for c in sh["checks"]}
    s = Decimal("289061595.12") + Decimal("191911823") + Decimal("2421814.19") + Decimal("1359527")
    assert Decimal(chk["submit.amount"]["items_sum"]) == s
    assert Decimal(chk["submit.amount"]["total"]) == Decimal("484754759.31")
    assert Decimal(chk["submit.amount"]["diff"]) == s - Decimal("484754759.31")


def test_approval_form_and_door_summary():
    (ap,) = parse_audit_summary(shapes.approval_form(), "审定单.xlsx")["sheets"]
    assert [r["kind"] for r in ap["rows"]] == ["item", "item", "total"]
    assert {c["key"]: c["diff"] for c in ap["checks"]} == {
        "audit.amount": "0", "delta.amount": "0", "submit.amount": "0"}
    door = parse_audit_summary(shapes.door_three_block(), "门窗.xlsx")["sheets"]
    names = [s["sheet"] for s in door]
    assert "汇总" in names, "汇总表：原合同 / 送审 / 审核 / 核减"
    summary = next(s for s in door if s["sheet"] == "汇总")
    assert summary["rows"][-1]["values"]["audit.amount"] == "149400"


def test_wan_yuan_is_scaled_in_decimal():
    from openpyxl import Workbook
    import io
    wb = Workbook()
    ws = wb.active
    ws.append(["序号", "工程名称", "送审金额（万元）", "审定金额（万元）"])
    ws.append([1, "土建", 12.3456, 12.3])
    buf = io.BytesIO()
    wb.save(buf)
    (sh,) = parse_audit_summary(buf.getvalue(), "x.xlsx")["sheets"]
    assert sh["rows"][0]["values"] == {"submit.amount": "123456.0000", "audit.amount": "123000.0"}


def test_non_audit_sheets_are_not_returned():
    assert parse_audit_summary(shapes.detail_with_total(), "明细.xlsx")["sheets"] == []


@pytest.mark.skipif(not REAL_SAMPLE.exists(), reason="真实语料不入仓；设置 ZT_NAS_DATA 指向 nas-data 目录后才跑")
def test_real_30002_audit_summary():
    (sh,) = parse_audit_summary(REAL_SAMPLE.read_bytes(), REAL_SAMPLE.name)["sheets"]
    items = [r for r in sh["rows"] if r["kind"] == "item"]
    assert len(items) == 18
    chk = {c["key"]: c for c in sh["checks"]}
    assert Decimal(chk["submit.amount"]["diff"]).copy_abs() <= Decimal("0.01"), "18 项报审之和 = 累计完成总产值"
