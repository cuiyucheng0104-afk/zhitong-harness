# 来源：engine-service/tests/test_reconcile_sides.py（zhitong-cost-ai@991ff5cd）
"""WS08-01 对账两侧角色：送审侧 side=submit、审定侧 side=audit（issue #724）。

旧版两侧调同一个解析器、不带侧别：同一份「门窗三段对比表」放两侧，两边取到的都是同一块，
结果「全部一致」—— 假阴性（QA:reconcile-06/08）；审定单放在审定侧取到的是报审金额
（QA:reconcile-01）；进度款两份逐行相同的合同合价拿来比，也是「全部一致」（QA:reconcile-02）。

核减额的期望值都是夹具构造值（见 tests/fixtures/costsheet_shapes.py 的 docstring）。
"""
from __future__ import annotations

import pytest

from tests.costsheet.fixtures.endpoint import HEADERS, client
from zt.common import ZtError
from zt.reconcile import engine as reconcile_engine
from tests.costsheet.fixtures import costsheet_shapes as shapes



def _run(raw_a: bytes, raw_b: bytes, basis: str = "auto") -> dict:
    return reconcile_engine.run(raw_a, "送审.xlsx", raw_b, "审定.xlsx", basis=basis)


def test_door_same_workbook_both_sides_deduction_equals_fixture_value():
    """同一份三段对比表放两侧：送审取「送审」块、审定取「审核」块，核减 = 158400 − 149400 = 9000。"""
    res = _run(shapes.door_three_block(), shapes.door_three_block())
    s = res["summary"]
    assert (s["a_total"], s["b_total"], s["adjust_amount"]) == (158400.0, 149400.0, 9000.0)
    assert res["total_diff"] == 9000.0
    lc = next(r for r in res["rows"] if r["item_code"] == "LC2020")
    assert (lc["submitted_amount"], lc["approved_amount"], lc["diff"]) == (55000.0, 50400.0, 4600.0)
    assert (lc["submitted_qty"], lc["approved_qty"]) == (110.0, 105.0)
    assert s["basis_used"] == {"submitted": "plain.submit", "approved": "plain.audit"}


def test_approval_form_on_approved_side_takes_approved_amount():
    res = _run(shapes.approval_form(), shapes.approval_form())
    assert res["summary"]["a_total"] == 1500000.0
    assert res["summary"]["b_total"] == 1430000.0
    assert res["total_diff"] == 70000.0


def test_wan_approval_form_deduction_is_in_yuan():
    """万元审定单放两侧：核减 70000 元（旧实现 a_total 150、b_total 143、核减 7.0，且无任何告警）。
    元单位审定单对万元审定单：两侧量纲不同也得出同一个核减，逐行差额 50000 / 20000。"""
    res = _run(shapes.approval_form_wan(), shapes.approval_form_wan())
    s = res["summary"]
    assert (s["a_total"], s["b_total"], s["adjust_amount"]) == (1500000.0, 1430000.0, 70000.0)
    assert res["total_diff"] == 70000.0

    mixed = _run(shapes.approval_form(), shapes.approval_form_wan())
    assert (mixed["summary"]["a_total"], mixed["summary"]["b_total"]) == (1500000.0, 1430000.0)
    assert mixed["total_diff"] == 70000.0
    assert sorted(r["diff"] for r in mixed["rows"]) == [20000.0, 50000.0]


def test_zhesi_this_month_submitted_vs_audited():
    res = _run(shapes.zhesi_code_column_totals(), shapes.zhesi_code_column_totals())
    assert (res["summary"]["a_total"], res["summary"]["b_total"]) == (69000.0, 58400.0)
    assert res["total_diff"] == 10600.0
    assert res["summary"]["basis_used"] == {"submitted": "current.submit", "approved": "current.audit"}


def test_missing_qty_and_price_are_none_in_rows():
    """两侧都没有「本月工程量」列：行里的量与价是 None，不是 0.0（旧版 _f() 写成 0.0）。"""
    res = _run(shapes.zhesi_code_column_totals(), shapes.zhesi_code_column_totals())
    row = res["rows"][0]
    assert row["submitted_qty"] is None and row["approved_qty"] is None
    ap = _run(shapes.approval_form(), shapes.approval_form())["rows"][0]
    assert ap["submitted_price"] is None and ap["approved_price"] is None


def test_identical_amounts_with_multi_amount_header_is_flagged():
    """两侧都按合同价取（进度款文件、basis=contract）→ 逐行相同，且表头有多组金额列 → 出护栏告警。

    两侧是**两份不同的文件**（resaved）：同一份文件、同一列的情形由 WS26-b 直接拦成 422
    （tests/test_reconcile_same_file.py），到不了这条护栏。"""
    raw = shapes.zheda_three_row_header()
    res = _run(raw, shapes.resaved(raw), basis="contract")
    assert res["total_diff"] == 0.0
    assert "amounts_identical_suspect" in [w["code"] for w in res["warning_items"]]


def test_identical_amounts_on_plain_header_is_not_flagged():
    """负控：单组金额列的普通清单、两份不同的文件恰好一致 → 不报「取成同一口径」（那条护栏只在
    「可能取错列」时才响）；这种结果由 warn 级的 all_rows_identical 提示（WS26-b）。"""
    raw = shapes.detail_with_total()
    res = _run(raw, shapes.resaved(raw))
    codes = [w["code"] for w in res["warning_items"]]
    assert "amounts_identical_suspect" not in codes and "all_rows_identical" in codes


def test_both_sides_ambiguous_raises_with_basis_hint():
    with pytest.raises(reconcile_engine.ParseFailed) as ei:
        _run(shapes.a1_period_qty("split"), shapes.a1_period_qty("split"))
    assert "无法确定口径" in str(ei.value) and "解析失败" in str(ei.value)


def test_endpoint_passes_basis_and_returns_structured_warnings():
    raw = shapes.zheda_three_row_header()
    a = shapes.put(raw, "对账-浙大-送审.xlsx", "A")
    b = shapes.put(shapes.resaved(raw), "对账-浙大-审定.xlsx", "B")     # 两份不同的文件（WS26-b）
    r = client.post("/engine/reconcile/run", headers=HEADERS,
                    json={"submitted_file": a, "approved_file": b, "basis": "contract"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["basis"] == "contract"
    assert isinstance(body["warning_items"], list)
    assert {"code", "level", "message"} <= set(body["warning_items"][0])
    assert body["coverage"]["files_total"] == 2 and body["coverage"]["files_used"] == 2
    # zt 改动：旧端点回 422；zt 的请求校验抛 ZtError（退出码 2）
    with pytest.raises(ZtError) as exc:
        client.post("/engine/reconcile/run", headers=HEADERS,
                    json={"submitted_file": a, "approved_file": b, "basis": "本期"})
    assert exc.value.code == "invalid_request", "basis 只收 auto/current/cumulative/contract"
