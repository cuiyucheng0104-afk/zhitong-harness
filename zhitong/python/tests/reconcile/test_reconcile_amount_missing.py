# 来源：engine-service/tests/test_reconcile_amount_missing.py（zhitong-cost-ai@991ff5cd）
"""WS26-a（issue #856，spec P03 / 03-004 第 2 项）：对账行带出「这一侧金额没取到」。

修的现场：REC-08（原件对测试件 C）里「空调水工程系统调试」两侧合价都没取到，引擎判「待核实」，
但行上 submitted_amount / approved_amount 都写成 0.0 —— 落库、抽屉里看着就是「两侧都是 0」。
`reconcile()` 早已算出 a_none / b_none（用来判「待核实」），只是没带到行上。

本片只增两个布尔：a_amount_missing、b_amount_missing。金额字段本身不改（仍是 0.0），
Java 原样写进 detail，前端据此把缺失的一侧显示成「—」。
期望值都由夹具构造直接给出（amount=None 的那一侧就是缺失），不从引擎输出反抄。
"""
from __future__ import annotations

from zt.reconcile import engine as reconcile_engine


def _it(code, amount, name="清单项", **kw):
    it = {"code": code, "name": name, "feature": "", "unit": "项", "qty": None, "price": None, "amount": amount,
          "chapter": "0310", "chapter_name": "给排水", "file": "x.xlsx", "sheet": "S", "row": 2}
    it.update(kw)
    return it


def _rows(a_items, b_items) -> list[dict]:
    return reconcile_engine.reconcile(a_items, b_items)["rows"]


def test_both_sides_missing_is_pending_and_flags_both():
    """REC-08 的形：同编码两侧都配上，合价都没取到。"""
    r = _rows([_it("031009001001", None, "空调水工程系统调试")],
              [_it("031009001001", None, "空调水工程系统调试")])[0]
    assert r["status"] == "待核实"
    assert r["a_amount_missing"] is True and r["b_amount_missing"] is True
    # 金额字段不变（只增字段）：仍是 0.0，前端靠布尔区分「0」与「没取到」
    assert r["a_amount"] == 0.0 and r["b_amount"] == 0.0


def test_one_side_missing_flags_only_that_side():
    a_missing = _rows([_it("010101001001", None)], [_it("010101001001", 2500.0)])[0]
    assert a_missing["status"] == "待核实"
    assert (a_missing["a_amount_missing"], a_missing["b_amount_missing"]) == (True, False)
    b_missing = _rows([_it("010101001001", 2500.0)], [_it("010101001001", None)])[0]
    assert b_missing["status"] == "待核实"
    assert (b_missing["a_amount_missing"], b_missing["b_amount_missing"]) == (False, True)


def test_real_zero_is_not_missing():
    """真的是 0 元（取到了 0）不是缺失 —— 夹具专门造「取到 0」这一形，区分 `is None` 与 falsy。"""
    r = _rows([_it("010101001001", 0.0)], [_it("010101001001", 0)])[0]
    assert r["status"] == "一致"
    assert r["a_amount_missing"] is False and r["b_amount_missing"] is False


def test_unmatched_side_is_absent_not_missing():
    """仅送审 / 仅审定：另一侧根本没有这一行（审定删掉了 = 审定 0），不是「有这一行但金额没取到」。"""
    rows = _rows([_it("010101001001", 2500.0, "平整场地")], [_it("010401003001", 800.0, "实心砖墙")])
    by = {r["status"]: r for r in rows}
    assert set(by) == {"仅送审", "仅审定"}
    assert (by["仅送审"]["a_amount_missing"], by["仅送审"]["b_amount_missing"]) == (False, False)
    assert (by["仅审定"]["a_amount_missing"], by["仅审定"]["b_amount_missing"]) == (False, False)
    # 仅送审但送审金额本身没取到：那一侧照实标缺失
    lone = _rows([_it("010101001001", None)], [])[0]
    assert lone["status"] == "待核实" and lone["a_amount_missing"] is True and lone["b_amount_missing"] is False


def _fake_parsed(items: list[dict], name: str) -> dict:
    cov = {"level": "good", "file": name}
    return {"items": items, "warnings": [], "warning_items": [],
            "meta": {"sheets_detail": [], "coverage": cov, "basis_used": "plain", "basis_label": "不分期"}}


def test_run_output_rows_carry_both_flags(monkeypatch):
    """接线层把两个布尔原样放进出参行（Java 把出参行整行写进 detail，前端读的就是这一份）。"""
    a_items = [_it("031009001001", None, "空调水工程系统调试"), _it("010101001001", 2500.0, "平整场地")]
    b_items = [_it("031009001001", 120.0, "空调水工程系统调试"), _it("010101001001", 2500.0, "平整场地")]
    parsed = iter([_fake_parsed(a_items, "送审.xlsx"), _fake_parsed(b_items, "审定.xlsx")])
    monkeypatch.setattr(reconcile_engine, "parse_costsheet", lambda *a, **k: next(parsed))
    out = reconcile_engine.run(b"a", "送审.xlsx", b"b", "审定.xlsx")
    by = {r["item_name"]: r for r in out["rows"]}
    assert by["空调水工程系统调试"]["status"] == "待核实"
    assert (by["空调水工程系统调试"]["a_amount_missing"], by["空调水工程系统调试"]["b_amount_missing"]) == (True, False)
    assert (by["平整场地"]["a_amount_missing"], by["平整场地"]["b_amount_missing"]) == (False, False)
