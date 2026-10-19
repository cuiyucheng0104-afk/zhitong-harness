# 来源：engine-service/tests/test_tk_evidence.py（zhitong-cost-ai@991ff5cd）
"""WS08-11（issue #760）：投控证据文案、涉及金额口径、判重口径。

修的现场：
  · 详情文案是 f-string 直接插值 —— 暂估价条目里出现「基准 None」；
  · 「基准」在不同规则里分别是大额阈值、组内首行金额、量×价计算值；
  · 「涉及金额」一列混用整行金额与差额；
  · 一行 6355.3、一行 0 的同码也判「重复计取」（min_amount=0，只看组内最大金额过线）。
"""
from __future__ import annotations

from zt.tk import engine as tk_engine

CFG = tk_engine.load_rules()


def _r(row, code, name, qty, price, amount, **kw):
    r = {"project_id": "P", "file_id": "F1", "source_file": "第5期.xlsx", "sheet": "土建", "row": row,
         "item_code": code, "item_name": name, "item_feature": "", "unit": "m3",
         "submit_qty": qty, "submit_price": price, "submit_amount": amount}
    r.update(kw)
    return r


def _all_rules_fixture():
    """每条规则都至少命中一次的一组行（含基准规则族与降级的 code_repeat）。"""
    rows = [
        _r(2, "010401009001", "暂估价-幕墙", None, None, 30000),                       # zangu
        _r(3, "010402001001", "空心砖墙", 100, 430, 30000),                            # self_check
        _r(4, "010601001001", "钢筋工程", None, None, 104000),                         # big_amount（无量价）
        _r(5, "010501001001", "现浇混凝土基础", 120, 500, 60000),                      # price_over
        _r(6, "010502001001", "矩形柱", 200, 400, 80000),                              # qty_over
        _r(7, "010503001001", "矩形梁", None, None, None),                             # missing_submit
        _r(8, "010101001001", "平整场地", 1, 6355.3, 6355.3),                          # code_repeat
        _r(9, "010101001001", "平整场地", 0, 0, 0),
        _r(10, "010999999001", "签证增补", 10, 1000, 9000),                            # new_item（+自洽）
        _r(11, "010904001001", "防水", 10, 100, 1000),
        _r(12, "010904001001", "防水", 10, 100, 1000),                                 # duplicate
    ]
    bases = [
        {"project_id": "P", "item_code": "010501001001", "item_name": "现浇混凝土基础", "unit": "m3",
         "base_qty": 100, "base_price": 400, "base_amount": 40000, "source": "中标清单.xlsx", "sheet": "清单", "row": 5},
        {"project_id": "P", "item_code": "010502001001", "item_name": "矩形柱", "unit": "m3",
         "base_qty": 100, "base_price": 400, "base_amount": 40000, "source": "中标清单.xlsx", "sheet": "清单", "row": 6},
        {"project_id": "P", "item_code": "010503001001", "item_name": "矩形梁", "unit": "m3",
         "base_qty": 100, "base_price": 500, "base_amount": 50000, "source": "中标清单.xlsx", "sheet": "清单", "row": 7},
        {"project_id": "P", "item_code": "010402001001", "item_name": "空心砖墙", "unit": "m3",
         "base_qty": 100, "base_price": 430, "base_amount": 43000, "source": "中标清单.xlsx", "sheet": "清单", "row": 8},
        {"project_id": "P", "item_code": "010401009001", "item_name": "暂估价-幕墙", "unit": "m3",
         "base_qty": None, "base_price": None, "base_amount": 30000, "source": "中标清单.xlsx", "sheet": "清单", "row": 9},
        {"project_id": "P", "item_code": "010101001001", "item_name": "平整场地", "unit": "m3",
         "base_qty": 1, "base_price": 1, "base_amount": 1, "source": "中标清单.xlsx", "sheet": "清单", "row": 10},
        {"project_id": "P", "item_code": "010904001001", "item_name": "防水", "unit": "m3",
         "base_qty": 10, "base_price": 100, "base_amount": 1000, "source": "中标清单.xlsx", "sheet": "清单", "row": 11},
    ]
    return rows, bases


def _all_hits(rows, bases):
    """不折叠的全部命中（每条规则单独跑），用于检查每个模板。"""
    index = tk_engine.build_index(bases)
    rules = CFG["rules"]
    conf = CFG["confidence"]
    hits = tk_engine.rule_duplicate(rows, rules["duplicate"], conf["duplicate"], conf["code_repeat"])
    for name, fn in tk_engine._RULES.items():
        hits += fn(rows, rules[name], conf[name])
    for name, fn in tk_engine._BASELINE_RULES.items():
        hits += fn(rows, rules[name], conf[name], index)
    return hits


def test_every_rule_template_renders_without_none():
    rows, bases = _all_rules_fixture()
    hits = _all_hits(rows, bases)
    rules_hit = {h["subtype"] for h in hits}
    assert rules_hit >= {"duplicate", "code_repeat", "zangu", "self_check", "big_amount", "price_over_baseline",
                         "qty_over_baseline", "missing_submit", "new_item"}, f"夹具失效：只命中了 {rules_hit}"
    for h in hits:
        assert "None" not in h["detail"], f"{h['subtype']} 文案里出现 None：{h['detail']}"
        assert "null" not in h["detail"]
        assert h["detail"].startswith(h["anomaly_type"])


def test_zero_amount_twin_is_code_repeat_not_duplicate():
    rows = [_r(8, "010101001001", "平整场地", 1, 6355.3, 6355.3), _r(9, "010101001001", "平整场地", 0, 0, 0)]
    out = tk_engine.rule_duplicate(rows, {"min_amount": 0}, 0.7, 0.3)
    assert {a["subtype"] for a in out} == {"code_repeat"}
    assert all(a["severity"] == 0 and a["anomaly_type"] == "编码重复（数据质量）" for a in out)
    assert out[0]["members"] == [
        {"file": "第5期.xlsx", "file_id": "F1", "sheet": "土建", "row": 8, "amount": 6355.3},
        {"file": "第5期.xlsx", "file_id": "F1", "sheet": "土建", "row": 9, "amount": 0.0},
    ]


def test_two_nonzero_rows_are_duplicate_and_zero_member_is_not_flagged():
    rows = [_r(2, "010101001001", "平整场地", 1, 100, 100), _r(3, "010101001001", "平整场地", 1, 100, 100),
            _r(4, "010101001001", "平整场地", 0, 0, 0)]
    out = tk_engine.rule_duplicate(rows, {"min_amount": 0}, 0.7, 0.3)
    assert sorted((a["subtype"], a["row"]) for a in out) == [("duplicate", 2), ("duplicate", 3)]
    assert len(out[0]["members"]) == 3


def test_excess_amount_is_price_delta_times_submitted_qty():
    rows, bases = _all_rules_fixture()
    hits = {h["subtype"]: h for h in _all_hits(rows, bases) if h["row"] in (5, 6)}
    p = hits["price_over_baseline"]
    assert p["excess_amount"] == (500 - 400) * 120 and p["severity"] == p["excess_amount"]
    assert p["line_amount"] == 60000 and p["baseline_value"] == 400
    q = hits["qty_over_baseline"]
    assert q["excess_amount"] == (200 - 100) * 400 and q["anomaly_type"] == "工程量疑似超合同"


def test_big_amount_threshold_is_not_a_baseline():
    rows = [_r(4, "010601001001", "钢筋工程", None, None, 104000)]
    a = tk_engine.rule_big_amount(rows, {"min_amount": 20000}, 0.3)[0]
    assert a["baseline_value"] is None and a["threshold"] == 20000
    assert a["line_amount"] == 104000 and a["excess_amount"] is None and a["severity"] == 104000
    assert "大额线 20,000.00" in a["detail"]


def test_wording_is_suspected_over_contract_not_verdict():
    """「价核减 / 量核减」是定案口吻；引擎只能判断「疑似」。"""
    rows, bases = _all_rules_fixture()
    types = {h["anomaly_type"] for h in _all_hits(rows, bases)}
    assert "价核减" not in types and "量核减" not in types
    assert {"单价疑似超合同", "工程量疑似超合同"} <= types


# ---------------------------------------------------------------- WS26-c（issue #792，P07）severity 取整到分

def test_severity_is_rounded_to_cents_for_missing_submit():
    """missing_submit 的 severity 取基准金额，旧版不取整：合同量 3 × 合同单价 411522.63 在浮点里是
    1234567.8900000001（18 个字符）。Java 把它原样写进 audit_tk_anomaly.severity（varchar(16)，
    STRICT 模式）→ 整批落库回滚、任务判 persist_failed。"""
    assert repr(3 * 411522.63) == "1234567.8900000001", "夹具自检：这组量价必须真的乘出 18 个字符的浮点"
    rows = [_r(7, "010503001001", "矩形梁", None, None, None)]
    bases = [{"project_id": "P", "item_code": "010503001001", "item_name": "矩形梁", "unit": "m3",
              "base_qty": 3, "base_price": 411522.63, "base_amount": None,
              "source": "中标清单.xlsx", "sheet": "清单", "row": 7}]
    (a,) = [x for x in tk_engine.detect(rows, CFG, bases) if x["subtype"] == "missing_submit"]
    assert repr(a["severity"]) == "1234567.89"
    assert a["baseline_value"] == 1234567.89


def test_every_rule_emits_severity_with_at_most_two_decimals():
    rows, bases = _all_rules_fixture()
    rows.append(_r(13, "010505001001", "有梁板", 3, 33333.37, 3 * 33333.37))      # 100000.11000000002
    hits = _all_hits(rows, bases)
    assert any(h["row"] == 13 and h["subtype"] == "big_amount" for h in hits), "夹具自检：第 13 行要命中大额"
    for h in hits:
        assert h["severity"] == round(h["severity"], 2), (h["subtype"], repr(h["severity"]))
        assert len(repr(h["severity"])) <= 16, (h["subtype"], repr(h["severity"]))


# ---------------------------------------------------------------- WS26-n（issue #1007，P24）负数行的大额证据句

def test_negative_big_amount_evidence_uses_absolute_value_and_says_negative():
    """TK-C04：「回填方（借土）」合价 −133,984.87。判定用绝对值（照旧命中），改前证据句写
    「送审金额 -133,984.87 ≥ 大额线 20,000.00」—— 字面不成立，也没提示是冲减项。"""
    rows = [_r(16, "010103001002", "回填方（借土）", 1, -133984.87, -133984.87)]
    (a,) = tk_engine.rule_big_amount(rows, CFG["rules"]["big_amount"], CFG["confidence"]["big_amount"])
    assert a["line_amount"] == -133984.87 and a["severity"] == 133984.87, "判定与金额口径不变"
    assert "绝对值 133,984.87 ≥ 大额线 20,000.00" in a["detail"]
    assert "金额为负，请核对是否冲减项" in a["detail"]
    assert "送审金额 -133,984.87 ≥" not in a["detail"], "带负号的原值不再写在「≥」左边"
    assert "-133,984.87" in a["detail"], "原值仍写出来，对得上原表"


def test_positive_big_amount_evidence_unchanged():
    rows = [_r(4, "010601001001", "钢筋工程", None, None, 104000)]
    (a,) = tk_engine.rule_big_amount(rows, CFG["rules"]["big_amount"], CFG["confidence"]["big_amount"])
    assert "送审金额 104,000.00 ≥ 大额线 20,000.00" in a["detail"]
    assert "金额为负" not in a["detail"] and "绝对值" not in a["detail"]
