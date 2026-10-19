# 来源：engine-service/tests/test_tk_zangu_scope.py（zhitong-cost-ai@991ff5cd）
"""WS26-n（issue #1007，spec WS26 §3.14，D-R164）：暂估规则分四档。

修的现场（TK-C06，缺陷 07-005）：原件 10 行「PC楼梯」的项目特征里写着「5. 钢筋含量：暂定按100kg/m3」，
rule_zangu 在「名称 + 特征」拼成的整段里找「暂估 / 暂定 / 暂列」，10 / 10 判成「整项存疑-暂估价」、置信 0.6，
排进「重点」。那是含钢量的取值说明，不是暂估价；原件清单表「暂估价」一列 8855 行全空，引擎也不读那一列。

四档（都照出，不少出一条；只有第四档降置信）：
  1. 清单表「其中：暂估价」分项列本行有非零值        → 0.6，marker_scope=provisional_amount
  2. 名称里有「暂估 / 暂定 / 暂列」                  → 0.6，marker_scope=name
  3. 项目特征里有价款词（暂估价 / 暂定价 / 暂列金额…） → 0.6，marker_scope=feature_price_word
  4. 只在项目特征里出现裸的「暂估 / 暂定 / 暂列」     → 0.3（低），marker_scope=feature_text，「不一定是暂估价」

合入条件：暂估命中条数不变（只变置信）。弱命中降到 0.3 后与大额粗筛同为 0.3，折叠时若按单条置信排，
按规则名 big_amount 在前 —— 10 条「钢筋含量暂定」会整体变成大额、暂估条数 10 → 0。反过来，弱命中也不能在同一行上
压掉本身归「重点」的自洽 / 合同外新增，把它们带进「数据质量」（评审阻断）。折叠次序下面有用例钉住。
"""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path

from openpyxl import Workbook

from zt.tk import engine as tk_engine
from zt.costsheet.parser import parse_costsheet

CFG = tk_engine.load_rules()
ZCFG = CFG["rules"]["zangu"]
CONF = CFG["confidence"]

PC_FEATURE = "1. 构件类型：预制楼梯\n2. 混凝土强度等级：C30\n5. 钢筋含量：暂定按100kg/m3"


def _r(row, name, feature="", amount=30000.0, qty=None, price=None, **kw):
    r = {"project_id": "P", "file_id": "F1", "source_file": "某街道一标段.xlsx", "sheet": "7#楼土建", "row": row,
         "item_code": f"0105130010{row:02d}", "item_name": name, "item_feature": feature, "unit": "m3",
         "submit_qty": qty, "submit_price": price, "submit_amount": amount}
    r.update(kw)
    return r


def _zangu(rows):
    return [a for a in tk_engine.detect(rows, CFG) if a["subtype"] == "zangu"]


def _one(row):
    hits = _zangu([row])
    assert len(hits) == 1, f"应命中一条暂估，实际 {len(hits)} 条：{[a['detail'] for a in tk_engine.detect([row], CFG)]}"
    return hits[0]


# ---------------------------------------------------------------- 配置

def test_price_words_and_weak_confidence_come_from_config():
    """价款词与裸词两张表、弱命中的置信都在 tk_detect.yaml 里（阈值全配置，禁止硬编码）。"""
    assert ZCFG["markers"] == ["暂估", "暂定", "暂列"]
    assert set(ZCFG["price_words"]) == {"暂估价", "暂定价", "暂列金额", "暂估单价", "暂定单价", "暂估金额", "暂定金额"}
    assert ZCFG["feature_text_confidence"] == 0.3
    assert CONF["zangu"] == 0.6
    assert all(any(m in w for m in ZCFG["markers"]) for w in ZCFG["price_words"]), \
        "每个价款词都含一个裸词：第三档是第四档的子集，命中集合不因分档而变"


# ---------------------------------------------------------------- 四档

def test_tk_c06_pc_stair_rebar_tentative_is_weak_feature_text():
    """★ 钉 TK-C06：特征「钢筋含量：暂定按100kg/m3」、名称「PC楼梯」→ 仍命中，置信 0.3 / 低，归 feature_text。"""
    a = _one(_r(53, "PC楼梯", PC_FEATURE, amount=133984.87))
    assert a["confidence"] == 0.3
    assert a["confidence_tier"] == "低"
    assert a["marker_scope"] == "feature_text"
    assert a["marker"] == "暂定"
    assert "项目特征里出现「暂定」，不一定是暂估价" in a["detail"]
    assert "置信度 0.3" in a["detail"]


def test_feature_price_word_is_strong():
    a = _one(_r(7, "钢筋", "1. 材料暂估价 500 元/t"))
    assert (a["confidence"], a["confidence_tier"], a["marker_scope"], a["marker"]) == (0.6, "中", "feature_price_word", "暂估价")
    assert "不一定" not in a["detail"]


def test_name_marker_is_strong():
    a = _one(_r(8, "暂列金额", ""))
    assert (a["confidence"], a["confidence_tier"], a["marker_scope"]) == (0.6, "中", "name")
    assert "名称命中「暂列」" in a["detail"]


def test_name_marker_wins_over_weak_feature_text():
    """名称里有「暂定」、特征里又有「钢筋含量暂定」：按强的那一档（名称）。"""
    a = _one(_r(9, "暂定材料-幕墙", PC_FEATURE))
    assert (a["confidence"], a["marker_scope"]) == (0.6, "name")


def test_provisional_column_value_is_strong_and_evidence_shows_it():
    """清单表「其中：暂估价」列本行 12,000 —— 名称、特征里一个字都没有也命中，证据句写出这个数。"""
    a = _one(_r(10, "铝板幕墙", "1. 材料：3mm 铝单板", amount=50000.0, provisional_amount=12000.0))
    assert (a["confidence"], a["confidence_tier"], a["marker_scope"]) == (0.6, "中", "provisional_amount")
    assert a["provisional_amount"] == 12000.0
    assert "清单表「暂估价」列本行 12,000.00" in a["detail"]


def test_provisional_column_wins_over_weak_feature_text():
    a = _one(_r(11, "PC楼梯", PC_FEATURE, provisional_amount=8000.0))
    assert (a["confidence"], a["marker_scope"]) == (0.6, "provisional_amount")


def test_zero_or_missing_provisional_with_no_text_is_no_hit():
    for pv in (None, 0, 0.0, "", "abc"):
        assert _zangu([_r(12, "铝板幕墙", "1. 材料：3mm 铝单板", provisional_amount=pv)]) == [], pv


def test_none_of_the_three_is_no_hit():
    assert _zangu([_r(13, "现浇混凝土基础", "1. 混凝土强度等级：C30")]) == []


def test_below_min_amount_no_hit_in_every_tier():
    low = ZCFG["min_amount"] - 1
    rows = [_r(20, "PC楼梯", PC_FEATURE, amount=low), _r(21, "暂列金额", "", amount=low),
            _r(22, "钢筋", "材料暂估价 500 元/t", amount=low),
            _r(23, "幕墙", "", amount=low, provisional_amount=500.0)]
    assert _zangu(rows) == []


def test_negative_amount_over_line_by_absolute_value_still_hits():
    a = _one(_r(24, "PC楼梯", PC_FEATURE, amount=-5000.0))
    assert a["marker_scope"] == "feature_text" and a["line_amount"] == -5000.0


# ---------------------------------------------------------------- 命中条数不变（合入条件）

def test_hit_set_equals_old_name_plus_feature_rule():
    """第四档只降置信、不少出条：凡「名称或特征里有裸词且金额过线」的行，新规则一条不少地照出。"""
    cases = [
        ("PC楼梯", PC_FEATURE), ("暂列金额", ""), ("钢筋", "材料暂估价 500 元/t"), ("铝板", "暂定做法见图"),
        ("暂估-幕墙", "暂定"), ("现浇基础", "C30"), ("钢筋", "暂列"), ("脚手架", "按暂估工程量"), ("土方", ""),
    ]
    rows = [_r(30 + i, n, f) for i, (n, f) in enumerate(cases)]
    old = {r["row"] for r in rows if any(m in r["item_name"] + r["item_feature"] for m in ZCFG["markers"])}
    new = {a["row"] for a in _zangu(rows)}
    assert old and new == old, f"命中集合变了：旧 {sorted(old)} 新 {sorted(new)}"


def test_weak_zangu_on_big_row_is_still_zangu_not_big_amount():
    """★ 13.4 万的「PC楼梯」也过大额线：弱命中 0.3 与大额同为 0.3，折叠必须仍归暂估（去处档：弱命中排在粗筛之前）。"""
    out = tk_engine.detect([_r(53, "PC楼梯", PC_FEATURE, amount=133984.87)], CFG)
    assert [a["subtype"] for a in out] == ["zangu"], [a["detail"] for a in out]
    assert out[0]["confidence"] == 0.3


def _tab(a):
    """照抄 anomalyTable.ts 的 tabOfRule：引擎这边只用来断言「折叠后这条结果去哪个页签」。"""
    if a["subtype"] == "big_amount":
        return "bulk"
    if a["subtype"] == "code_repeat" or (a["subtype"] == "zangu" and a.get("marker_scope") == "feature_text"):
        return "quality"
    return "focus"


def _raw_scope(row):
    """折叠前暂估规则在这一行上的命中档（detect 出来的是折叠后的，看不到被压掉的那条）。"""
    hits = tk_engine.rule_zangu([row], ZCFG, CONF["zangu"])
    return hits[0]["marker_scope"] if hits else None


def test_weak_zangu_yields_to_self_check_on_same_row():
    """★ 评审阻断：「垫层」特征「厚度暂定100mm」、10 × 2000 ≠ 30000，同时命中自洽与弱命中的暂估。
    弱命中归「数据质量」，折叠时不能把这条量价不自洽从「重点」带走 —— 归自洽。"""
    row = _r(54, "垫层", "厚度暂定100mm", amount=30000.0, qty=10, price=2000)
    assert _raw_scope(row) == "feature_text", "前提：暂估规则在这一行上是弱命中"
    out = tk_engine.detect([row], CFG)
    assert [(a["subtype"], _tab(a)) for a in out] == [("self_check", "focus")], [a["detail"] for a in out]


BASE = [{"project_id": "P", "item_code": "010101001001", "item_name": "挖一般土方", "unit": "m3",
         "base_qty": 100, "base_price": 10, "base_amount": 1000, "source": "合同清单"}]


def test_weak_zangu_yields_to_new_item_on_same_row():
    """★ 评审阻断：勾了合同清单，「签证-土方外运增补」8 万、编码不在合同里、特征「运距暂定按15km」——
    同时命中合同外新增、弱命中的暂估、大额。归合同外新增（重点），不能被弱命中带进「数据质量」。"""
    rows = [_r(1, "挖一般土方", "", amount=1000.0, qty=100, price=10, item_code="010101001001"),
            _r(2, "签证-土方外运增补", "运距暂定按15km", amount=80000.0, item_code="010999999999")]
    assert _raw_scope(rows[1]) == "feature_text", "前提：暂估规则在这一行上是弱命中"
    out = [a for a in tk_engine.detect(rows, CFG, baselines=BASE) if a["row"] == 2]
    assert [(a["subtype"], _tab(a)) for a in out] == [("new_item", "focus")], [a["detail"] for a in out]


def test_strong_zangu_still_beats_self_check():
    """强命中（名称里有「暂列」）照旧 0.6 胜自洽 0.55 —— 只让弱命中让位，规则档的先后不变。"""
    out = tk_engine.detect([_r(57, "暂列金额-垫层", "", amount=30000.0, qty=10, price=2000)], CFG)
    assert [(a["subtype"], a["marker_scope"]) for a in out] == [("zangu", "name")], [a["detail"] for a in out]


def test_weak_zangu_still_beats_code_repeat():
    """同码两行、一行金额为 0 → 编码重复（数据质量）。弱命中那一行仍是暂估：两条都不进「重点」，暂估条数不掉。"""
    rows = [_r(58, "PC楼梯", PC_FEATURE, amount=5000.0, item_code="010513001001"),
            _r(59, "PC楼梯", "", amount=0.0, item_code="010513001001")]
    assert _raw_scope(rows[0]) == "feature_text", "前提：暂估规则在这一行上是弱命中"
    out = {a["row"]: a["subtype"] for a in tk_engine.detect(rows, CFG)}
    assert out == {58: "zangu", 59: "code_repeat"}, out


def test_pick_winner_weak_zangu_ranks_between_focus_rules_and_screens():
    """折叠次序（与输入顺序无关）：弱命中输给每一条本身归「重点」的规则，胜大额粗筛与编码重复。
    弱命中的置信取配置值、规则档 0.6 与 0.99 各试一遍 —— 页签看的是 marker_scope 不是置信，折叠也只能看去处。"""
    for wconf in (ZCFG["feature_text_confidence"], CONF["zangu"], 0.99):
        weak = {"subtype": "zangu", "confidence": wconf, "severity": 1e6, "marker_scope": "feature_text"}
        for rule in CONF:
            if rule == "zangu":
                continue
            other = {"subtype": rule, "confidence": CONF[rule], "severity": 1.0}
            want = "zangu" if rule in ("big_amount", "code_repeat") else rule
            for hits in ([weak, other], [other, weak]):
                assert tk_engine._pick_winner(hits)["subtype"] == want, (wconf, rule, [h["subtype"] for h in hits])


def test_weak_zangu_yields_to_self_check_even_if_weak_confidence_is_raised():
    """有人把 feature_text_confidence 调回 0.6：弱命中仍归「数据质量」（页签看 marker_scope），
    折叠就仍不能让它压掉同一行的量价不自洽。"""
    cfg = copy.deepcopy(CFG)
    cfg["rules"]["zangu"]["feature_text_confidence"] = CONF["zangu"]
    row = _r(60, "垫层", "厚度暂定100mm", amount=30000.0, qty=10, price=2000)
    out = tk_engine.detect([row], cfg)
    assert [(a["subtype"], _tab(a)) for a in out] == [("self_check", "focus")], [a["detail"] for a in out]


# zt 改动：旧仓直接读前端夹具（repo_only）；前端随旧系统废弃，页签对照抽出冻结在 tests/tk/fixtures/
PARITY = Path(__file__).parent / "fixtures" / "tk_fold_tier_tabs.json"


def test_fold_tier_agrees_with_tab_of_rule_on_parity_fixture():
    """折叠的去处档与旧页面 / 导出的页签是同一张表：口径对照夹具里每一行，去处档 0 ⇔ 页签「重点」。"""
    fx = json.loads(PARITY.read_text(encoding="utf-8"))
    tabs = set()
    for r in fx["rows"]:
        tab = r["tab"]
        h = {"subtype": r["anomalyType"], "marker_scope": r["marker_scope"]}
        assert (tk_engine._fold_tier(h) == 0) == (tab == "focus"), (r["id"], h, tab)
        tabs.add((tab, tk_engine._fold_tier(h)))
    assert tabs >= {("focus", 0), ("quality", 1), ("quality", 2), ("bulk", 2)}, tabs


def test_duplicate_still_beats_zangu():
    """规则档的先后不变：重复计取 0.7 > 暂估 0.6。"""
    rows = [_r(55, "PC楼梯", PC_FEATURE, item_code="010513001001"),
            _r(56, "PC楼梯", PC_FEATURE, item_code="010513001001")]
    assert {a["subtype"] for a in tk_engine.detect(rows, CFG)} == {"duplicate"}


# ---------------------------------------------------------------- 清单表「暂估价」分项列（costsheet）

def _book(rows: list[list]) -> bytes:
    """照生产原件「表10.2.2-16 分部分项工程清单与计价表」的三行表头：金额（元）→ 综合单价 | 合价 | 其中 → 人工费 | 机械费 | 暂估价。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "表10.2.2-16 分部分项工程清单与计价表"
    ws.append(["【表10.2.2-16】"])
    ws.append(["分部分项工程清单与计价表"])
    ws.append(["单位（专业）工程名称：7#楼土建", None, None, None, "标段：", None, None, None, "第 1 页  共 1 页"])
    ws.append(["序号", "项目编码", "项目名称", "项目特征", "计量单位", "工程量", "金额（元）", None, None, None, None, "备注"])
    ws.append([None] * 6 + ["综合单价", "合价", "其中", None, None, None])
    ws.append([None] * 8 + ["人工费", "机械费", "暂估价", None])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROWS = [
    [1, "010513001001", "PC楼梯", PC_FEATURE, "m3", 20, 1500, 30000, 3000, 100, None, None],
    [2, "011209001001", "铝板幕墙", "1. 材料：3mm 铝单板", "m2", 10, 5000, 50000, 1000, 100, 12000, None],
    [3, "010101001001", "平整场地", "", "m2", 100, 5, 500, 100, 10, 0, None],
]


def test_costsheet_carries_provisional_column_value_into_item():
    items = parse_costsheet(_book(ROWS), "t.xlsx", side="submit", basis="auto", file_id="F1")["items"]
    by = {it["name"]: it for it in items}
    assert by["铝板幕墙"].get("provisional_amount") == 12000.0
    assert by["铝板幕墙"]["amount"] == 50000.0, "暂估价是合价的组成，不是合价"
    assert by["PC楼梯"].get("provisional_amount") is None, "空格不是 0，不写这个键"
    assert by["平整场地"].get("provisional_amount") == 0.0


def test_costsheet_without_provisional_column_has_no_key():
    wb = Workbook()
    ws = wb.active
    ws.title = "分部分项清单与计价表"
    ws.append(["序号", "项目编码", "项目名称", "项目特征描述", "计量单位", "工程量", "综合单价", "合价"])
    ws.append([1, "010513001001", "PC楼梯", PC_FEATURE, "m3", 20, 1500, 30000])
    buf = io.BytesIO()
    wb.save(buf)
    items = parse_costsheet(buf.getvalue(), "t.xlsx", side="submit", basis="auto", file_id="F1")["items"]
    assert items and all("provisional_amount" not in it for it in items)


def test_run_end_to_end_provisional_column_and_weak_text():
    out = tk_engine.run([(_book(ROWS), "某街道一标段.xlsx", "F1")], None, project_id="P")
    z = {a["item_name"]: a for a in out["anomalies"] if a["subtype"] == "zangu"}
    assert set(z) == {"PC楼梯", "铝板幕墙"}, sorted(z)
    assert (z["PC楼梯"]["confidence"], z["PC楼梯"]["marker_scope"]) == (0.3, "feature_text")
    assert (z["铝板幕墙"]["confidence"], z["铝板幕墙"]["marker_scope"]) == (0.6, "provisional_amount")
    assert "12,000.00" in z["铝板幕墙"]["detail"]
