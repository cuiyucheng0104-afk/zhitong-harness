# 来源：engine-service/tests/test_reconcile_money_arith.py（zhitong-cost-ai@991ff5cd）
"""WS08-19（issue #760）：对账按分比较 + 行内量×价校验 + 量差/价差归因。

修的现场：
  · 二进制浮点比较、容差 0.01：4,316.76 对 4,316.77（差 0.010000000000218）判成「调整」；
  · 送审方把 100×430 算成 30,000（应为 43,000），引擎没有任何标记，造价员看不出差额从哪来；
  · 只比合价，不拆量差和价差。
"""
from __future__ import annotations

import io

from openpyxl import Workbook

from zt.reconcile import engine as reconcile_engine
from zt.costsheet.parser import round_money, to_cents


def _it(code, amount, qty=None, price=None, name="清单项", **kw):
    it = {"code": code, "name": name, "feature": "", "unit": "m3", "qty": qty, "price": price, "amount": amount,
          "chapter": "0104", "chapter_name": "砌筑工程", "file": "x.xlsx", "sheet": "S", "row": 2}
    it.update(kw)
    return it


def _one(a, b) -> dict:
    return reconcile_engine.reconcile([a], [b])["rows"][0]


def test_one_cent_apart_is_consistent_with_rounding_note():
    r = _one(_it("010401003001", 4316.76), _it("010401003001", 4316.77))
    assert r["status"] == "一致" and r["rounding_note"] == "舍入差 ±0.01"


def test_two_cents_apart_is_adjusted():
    r = _one(_it("010401003001", 4316.76), _it("010401003001", 4316.78))
    assert r["status"] == "调整" and r["rounding_note"] is None
    assert r["adjust"] == -0.02


def test_money_rounding_is_half_up_on_the_decimal_not_the_binary_float():
    """2.675 在二进制里是 2.67499999…，round(x, 2) 给 2.67；0.125 被 round 的「银行家舍入」舍成 0.12。
    按十进制四舍五入（ROUND_HALF_UP）应是 2.68 与 0.13。"""
    assert round(2.675, 2) == 2.67 and round(0.125, 2) == 0.12     # 夹具自检：确实是会舍错的数
    assert to_cents(2.675) == 268 and round_money(2.675) == 2.68
    assert to_cents(0.125) == 13 and to_cents(-0.125) == -13
    assert to_cents(None) is None and round_money("x") is None


def test_submitted_arithmetic_error_is_flagged():
    """R0 形：100 × 430 写成 30,000。"""
    r = _one(_it("010402001001", 30000, qty=100, price=430), _it("010402001001", 43000, qty=100, price=430))
    assert r["calc_flags"] == ["送审计算错误"]


def test_arithmetic_check_tolerance_and_period_guard():
    # 差 0.9 元（< 1 元）不标
    ok = _one(_it("A1B001", 1000.9, qty=10, price=100), _it("A1B001", 1000, qty=10, price=100))
    assert ok["calc_flags"] == []
    # 进度款形：量是合同量、额是本期产值 —— 量×价≠额是常态，不是算错
    progress = _one(_it("010401003001", 500, qty=100, price=430, periods={"qty": "contract", "amount": "current"}),
                    _it("010401003001", 500, qty=100, price=430, periods={"qty": "contract", "amount": "current"}))
    assert progress["calc_flags"] == []


def test_qty_and_price_attribution_sum_to_total_diff_for_consistent_rows():
    a = _it("010501001001", 120 * 500, qty=120, price=500)
    b = _it("010501001001", 100 * 460, qty=100, price=460)
    r = _one(a, b)
    assert r["diff_by_qty"] == (120 - 100) * 460
    assert r["diff_by_price"] == (500 - 460) * 120
    assert round(r["diff_by_qty"] + r["diff_by_price"], 2) == r["adjust"]
    res = reconcile_engine.reconcile([a], [b])
    assert res["summary"]["diff_by_qty"] == 9200 and res["summary"]["diff_by_price"] == 4800


def test_attribution_needs_all_four_numbers():
    r = _one(_it("010501001001", 60000, qty=None, price=500), _it("010501001001", 46000, qty=100, price=460))
    assert r["diff_by_qty"] is None and r["diff_by_price"] is None


def _bill(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "分部分项清单与计价表"
    ws.append(["序号", "项目编码", "项目名称", "项目特征描述", "计量单位", "工程量", "综合单价", "合价"])
    for i, r in enumerate(rows, 1):
        ws.append([i] + list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_end_to_end_flags_and_warning():
    sub = _bill([["010402001001", "空心砖墙", "", "m3", 100, 430, 30000],
                 ["010401003001", "实心砖墙", "", "m3", 10, 431.676, 4316.76]])
    app = _bill([["010402001001", "空心砖墙", "", "m3", 100, 430, 43000],
                 ["010401003001", "实心砖墙", "", "m3", 10, 431.677, 4316.77]])
    res = reconcile_engine.run(sub, "送审.xlsx", app, "审定.xlsx")
    by_code = {r["item_code"]: r for r in res["rows"]}
    assert by_code["010402001001"]["calc_flags"] == ["送审计算错误"]
    assert by_code["010401003001"]["status"] == "一致"
    assert "calc_error_rows" in [w["code"] for w in res["warning_items"]]
    assert res["summary"]["count_calc_error_a"] == 1 and res["summary"]["count_rounding"] == 1
