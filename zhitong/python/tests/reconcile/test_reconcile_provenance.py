# 来源：engine-service/tests/test_reconcile_provenance.py（zhitong-cost-ai@991ff5cd）
"""WS08-09（issue #760）：对账结果回源定位 + 无编码行按单位工程择优配对。

修的现场：R1 门窗一期对账结果里 5 行「铝合金门窗」，分不清是哪栋楼；弱键（名称|特征|单位）没有楼栋
上下文，多个候选时退到行序配对 —— 审定侧 sheet 顺序一换，6# 楼的送审就对上了别的楼的审定。
"""
from __future__ import annotations

import io

from openpyxl import Workbook

from zt.reconcile import engine as reconcile_engine

HEAD = ["序号", "项目编码", "项目名称", "项目特征描述", "计量单位", "工程量", "综合单价", "合价"]
BUILDINGS = ["6#", "7#", "14#", "19#", "S11#"]
# 每栋楼送审/审定金额刻意设成「按金额最接近配对会配错楼」：6# 送审 100000，最接近的审定是 7# 的 95000
SUBMIT = {"6#": 100000, "7#": 60000, "14#": 45000, "19#": 30000, "S11#": 20000}
APPROVE = {"6#": 40000, "7#": 95000, "14#": 58000, "19#": 21000, "S11#": 29000}


def _doors(amounts: dict, order: list[str]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for b in order:
        ws = wb.create_sheet(b)
        ws.append([f"单位工程名称：{b}楼【门窗】"])
        ws.append(HEAD)
        ws.append([1, None, "铝合金门窗", "断桥隔热", "m2", amounts[b] / 1000, 1000, amounts[b]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _run(approve_order):
    return reconcile_engine.run(_doors(SUBMIT, BUILDINGS), "门窗-送审.xlsx",
                                _doors(APPROVE, approve_order), "门窗-审定.xlsx",
                                submitted_file_id="FS", approved_file_id="FA")


def test_five_identical_door_rows_pair_by_unit_project_regardless_of_sheet_order():
    for order in (BUILDINGS, list(reversed(BUILDINGS)), ["19#", "6#", "S11#", "7#", "14#"]):
        res = _run(order)
        rows = [r for r in res["rows"] if r["item_name"] == "铝合金门窗"]
        assert len(rows) == 5
        for r in rows:
            assert r["submitted_sheet"] == r["approved_sheet"], (order, r)
            b = r["submitted_sheet"]
            assert r["unit_project"] == f"{b}楼【门窗】"
            assert r["submitted_amount"] == SUBMIT[b] and r["approved_amount"] == APPROVE[b]
        assert {r["unit_project"] for r in rows} == {f"{b}楼【门窗】" for b in BUILDINGS}


def test_rows_carry_both_sides_file_sheet_row():
    res = _run(BUILDINGS)
    for r in res["rows"]:
        assert r["submitted_file"] == "门窗-送审.xlsx" and r["submitted_file_id"] == "FS"
        assert r["approved_file"] == "门窗-审定.xlsx" and r["approved_file_id"] == "FA"
        assert r["submitted_row"] == 3 and r["approved_row"] == 3


def test_only_one_side_row_has_null_location_on_the_other_side():
    extra = dict(APPROVE, **{"99#": 1234})
    res = reconcile_engine.run(_doors(SUBMIT, BUILDINGS), "s.xlsx", _doors(extra, BUILDINGS + ["99#"]), "a.xlsx")
    only_b = [r for r in res["rows"] if r["status"] == "仅审定"]
    assert len(only_b) == 1
    assert only_b[0]["submitted_row"] is None and only_b[0]["approved_sheet"] == "99#"
