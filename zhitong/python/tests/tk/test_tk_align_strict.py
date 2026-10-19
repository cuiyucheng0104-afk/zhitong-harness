# 来源：engine-service/tests/test_tk_align_strict.py（zhitong-cost-ai@991ff5cd）
"""WS08-07 / WS08-10（issue #760）：投控合同基准改为清单文件 + 严格对齐（铁律 3）。

修的现场（spec WS08-07，均在 origin/dev 源码上核对过）：
  · Java 把 WBS 级 {wbs_unit_id, baseline_type, amount} 当清单级基准发来，基准索引为空 →
    一旦有数据，100% 送审行都被判「合同外新增」；
  · 编码没对上就用 difflib「名称+单位+特征相似度 ≥0.3」模糊对齐，并据此产出价差/量差金额
    （De315 PE 管对上 De500 PE 管）；
  · 精确分支只比编码，不看名称与单位（04B003「接驳费用」对上「检查井高度调整」照样出价差）；
  · new_item 没有覆盖率护栏：基准只选了一小部分，其余全被当成合同外新增。

每条用例的夹具都构造到「会失败的那个形状」（CLAUDE.md §5.2），变异验收见 PR。
"""
from __future__ import annotations

import io
from pathlib import Path

from openpyxl import Workbook

from zt.tk import align as tk_align

from zt.tk import engine as tk_engine

HEAD = ["序号", "项目编码", "项目名称", "项目特征描述", "计量单位", "工程量", "综合单价", "合价"]


def _bill(rows: list[list], sheet: str = "分部分项清单与计价表") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(HEAD)
    for i, r in enumerate(rows, 1):
        ws.append([i] + list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _row(code, name, feature, unit, qty, price, amount, row=2, **kw) -> dict:
    r = {"project_id": "P", "file_id": "S1", "source_file": "送审.xlsx", "sheet": "分部分项", "row": row,
         "item_code": code, "item_name": name, "item_feature": feature, "unit": unit,
         "submit_qty": qty, "submit_price": price, "submit_amount": amount}
    r.update(kw)
    return r


def _base(code, name, feature, unit, qty, price, amount=None, row=5) -> dict:
    return {"project_id": "P", "item_code": code, "item_name": name, "item_feature": feature, "unit": unit,
            "base_qty": qty, "base_price": price, "base_amount": amount if amount is not None else qty * price,
            "source": "中标清单.xlsx", "file_id": "B1", "sheet": "分部分项", "row": row}


CFG = tk_engine.load_rules()
AMOUNT_KEYS = {"base_price", "base_qty", "base_amount", "excess_amount", "baseline_value"}


def _no_amounts(obj) -> bool:
    """alignment_issues / align_suggestions 里任何层级都不许带金额键（铁律 3：对不准就不出数）。"""
    if isinstance(obj, dict):
        return not (AMOUNT_KEYS & set(obj)) and all(_no_amounts(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_no_amounts(v) for v in obj)
    return True


# ---------------------------------------------------------------- 模糊对齐不出金额

def test_same_name_different_feature_goes_to_suggestions_without_amount():
    """De315 对 De500：同名同单位、特征不同。旧版 difflib 模糊对齐后按 De500 的单价算价差。"""
    rows = [_row("", "PE给水管", "De315 PN1.0", "m", 100, 500, 50000)]
    bases = [_base("", "PE给水管", "De500 PN1.0", "m", 100, 400)]
    out = tk_engine.detect_full(rows, CFG, bases)
    assert not [a for a in out["anomalies"] if a["subtype"] in ("price_over_baseline", "qty_over_baseline")]
    assert len(out["align_suggestions"]) == 1
    sug = out["align_suggestions"][0]
    assert sug["candidates"][0]["item_feature"] == "De500 PN1.0"
    assert _no_amounts(out["align_suggestions"])


def test_different_gb_codes_same_name_is_suggestion_not_exact():
    rows = [_row("040501004001", "塑料管", "De315", "m", 100, 500, 50000)]
    bases = [_base("040501004002", "塑料管", "De500", "m", 100, 400)]
    al = tk_align.align_row(rows[0], tk_align.build_index(bases))
    assert al.method == tk_align.SUGGEST and al.base is None


# ---------------------------------------------------------------- 同码不同名 → CONFLICT

def test_same_supplement_code_different_name_is_conflict():
    """04B003 接驳费用 对 检查井高度调整（同码不同名）：不出金额，写进 alignment_issues。"""
    rows = [_row("04B003", "接驳费用", "", "项", 1, 90000, 90000)]
    bases = [_base("04B003", "检查井高度调整", "", "项", 1, 30000)]
    out = tk_engine.detect_full(rows, CFG, bases)
    assert [a["subtype"] for a in out["anomalies"] if a["subtype"] in
            ("price_over_baseline", "qty_over_baseline", "missing_submit", "new_item")] == []
    assert len(out["alignment_issues"]) == 1
    issue = out["alignment_issues"][0]
    assert issue["item_code"] == "04B003" and "名称不同" in issue["reason"]
    assert issue["baseline"][0]["item_name"] == "检查井高度调整"
    assert _no_amounts(out["alignment_issues"])
    assert "baseline_conflicts" in [w["code"] for w in out["warning_items"]]


def test_same_gb_code_different_name_or_unit_is_conflict():
    idx = tk_align.build_index([_base("010501001001", "现浇混凝土基础", "C30", "m3", 100, 400)])
    assert tk_align.align_row(_row("010501001001", "垫层", "C15", "m3", 1, 1, 1), idx).method == tk_align.CONFLICT
    assert tk_align.align_row(_row("010501001001", "现浇混凝土基础", "C30", "m2", 1, 1, 1), idx).method \
        == tk_align.CONFLICT


def test_gb_code_name_unit_equal_is_exact_with_unit_synonym_and_fullwidth():
    """严格 ≠ 死板：单位同义（m³/立方米/m3）与全角半角、空白不影响精确对齐。"""
    idx = tk_align.build_index([_base("010501001001", "现浇混凝土基础", "C30", "m3", 100, 400)])
    al = tk_align.align_row(_row("10501001001", "现浇 混凝土基础", "C30", "m³", 1, 1, 1), idx)
    assert al.method == tk_align.EXACT and al.base["row"] == 5


def test_supplement_code_exact_needs_name_feature_unit_all_equal():
    idx = tk_align.build_index([_base("01B047", "砌体加固筋", "Φ8", "t", 1.5, 3000)])
    assert tk_align.align_row(_row("01B047", "砌体加固筋", "Φ8", "t", 2, 3500, 7000), idx).method == tk_align.EXACT
    assert tk_align.align_row(_row("01B047", "砌体加固筋", "Φ10", "t", 2, 3500, 7000), idx).method \
        == tk_align.CONFLICT


# ---------------------------------------------------------------- 同键多行不取第一条（WS26-m，issue #828）

def test_same_key_twice_in_baseline_is_ambiguous_not_the_first_row():
    """同一个国标码 + 名称 + 单位在基准里有两行（单价 400 / 600），送审单价 500。
    旧版取第一行（400）→ 报「单价疑似超合同」并带超出额；换个顺序先遇到 600 就不报 —— 结论随行序变。"""
    rows = [_row("010501001001", "现浇混凝土基础", "C30", "m3", 100, 500, 50000)]
    for bases in ([_base("010501001001", "现浇混凝土基础", "C30", "m3", 100, 400, row=5),
                   _base("010501001001", "现浇混凝土基础", "C35", "m3", 100, 600, row=9)],
                  [_base("010501001001", "现浇混凝土基础", "C35", "m3", 100, 600, row=9),
                   _base("010501001001", "现浇混凝土基础", "C30", "m3", 100, 400, row=5)]):
        out = tk_engine.detect_full(rows, CFG, bases)
        assert [a["subtype"] for a in out["anomalies"]] == ["big_amount"], "不出任何合同类异常，也不算合同外新增"
        assert [(i["method"], len(i["baseline"])) for i in out["alignment_issues"]] == [("ambiguous", 2)]
        assert _no_amounts(out["alignment_issues"])
        assert out["exact_rows"] == {}
        assert out["baseline_stats"]["aligned"] == {"exact": 0, "conflict": 0, "suggest": 0, "new_item": 0,
                                                    "ambiguous": 1}


def test_legacy_baseline_rows_with_same_key_twice_are_ambiguous():
    """旧 `baseline` 参数的基准行没有表名也没有单位工程：收窄无从谈起，同键两行 → AMBIGUOUS。"""
    raw = _bill([["010501001001", "现浇混凝土基础", "C30", "m3", 100, 500, 50000]])
    legacy = [{"item_code": "010501001001", "item_name": "现浇混凝土基础", "unit": "m3",
               "base_qty": 100, "base_price": 400, "base_amount": 40000},
              {"item_code": "010501001001", "item_name": "现浇混凝土基础", "unit": "m3",
               "base_qty": 100, "base_price": 600, "base_amount": 60000}]
    res = tk_engine.run([(raw, "送审.xlsx", "S1")], legacy, project_id="P9")
    assert [a["subtype"] for a in res["anomalies"]] == ["big_amount"]
    assert [i["method"] for i in res["alignment_issues"]] == ["ambiguous"]
    assert "没有一行的单位工程与送审行的「分部分项清单与计价表」写法相同" in res["alignment_issues"][0]["reason"]


def test_conflict_issue_is_tagged_and_wins_over_ambiguity_when_name_differs():
    """同码两行、名称都对不上：还是 CONFLICT（编码相同但名称不同），不是 AMBIGUOUS。"""
    bases = [_base("010501001001", "现浇混凝土基础", "C30", "m3", 100, 400, row=5),
             _base("010501001001", "现浇混凝土基础", "C35", "m3", 100, 600, row=9)]
    out = tk_engine.detect_full([_row("010501001001", "垫层", "C15", "m3", 100, 500, 50000)], CFG, bases)
    assert [(i["method"], i["reason"]) for i in out["alignment_issues"]] == [("conflict", "编码相同但名称不同")]


def test_source_has_no_fuzzy_matcher_left():
    """源码闸：difflib 与模糊阈值配置都删了（配置里留着就会有人再接回去）。"""
    src = Path(tk_align.__file__).read_text(encoding="utf-8")
    assert "import difflib" not in src and "SequenceMatcher(" not in src
    yml = Path(tk_engine.RULES_PATH).read_text(encoding="utf-8")
    assert "fuzzy_feature_min:" not in yml and "fuzzy_conf_factor:" not in yml


# ---------------------------------------------------------------- Java 形状的基准 → 拒收

def test_java_wbs_shaped_baseline_is_rejected_and_no_new_item():
    raw = _bill([["010101001001", "平整场地", "", "m2", 1000, 30, 30000],
                 ["010401003001", "实心砖墙", "", "m3", 200, 480, 96000]])
    wbs = [{"wbs_unit_id": "W1", "baseline_type": "budget", "amount": 1_000_000},
           {"wbs_unit_id": "W2", "baseline_type": "budget", "amount": 2_000_000}]
    res = tk_engine.run([(raw, "送审.xlsx", "S1")], wbs, project_id="P")
    assert [a for a in res["anomalies"] if a["subtype"] == "new_item"] == []
    assert "baseline_rows_invalid" in [w["code"] for w in res["warning_items"]]
    assert res["baseline"]["status"] == "invalid" and res["baseline"]["rows_rejected"] == 2


def test_legacy_baseline_rows_without_project_id_use_request_project():
    """缺 project_id 的清单级旧基准行用请求里的项目号（旧版按 '' 建索引，永远对不上）。"""
    raw = _bill([["010501001001", "现浇混凝土基础", "C30", "m3", 100, 500, 50000]])
    legacy = [{"item_code": "010501001001", "item_name": "现浇混凝土基础", "unit": "m3",
               "base_qty": 100, "base_price": 400, "base_amount": 40000}]
    res = tk_engine.run([(raw, "送审.xlsx", "S1")], legacy, project_id="P9")
    assert [a["subtype"] for a in res["anomalies"]] == ["price_over_baseline"]


def test_empty_baseline_emits_no_warning_but_says_not_provided():
    """WS08-10：Java 旧版恒发 baseline=[]，引擎每次都追加一条技术告警，前端把它说成「未能纳入比对」。"""
    raw = _bill([["010101001001", "平整场地", "", "m2", 1000, 30, 30000]])
    for baseline in ([], None):
        res = tk_engine.run([(raw, "送审.xlsx", "S1")], baseline, project_id="P")
        codes = [w["code"] for w in res["warning_items"]]
        assert not [c for c in codes if c.startswith("baseline")], codes
        assert not [w for w in res["warnings"] if "baseline" in w.lower() or "基准" in w]
        assert res["baseline"]["status"] == "not_provided"


# ---------------------------------------------------------------- new_item 覆盖率护栏

def _coded_rows(n_aligned: int, n_total: int) -> tuple[list, list]:
    rows, bases = [], []
    for i in range(n_total):
        code = f"0105010010{i:02d}"
        rows.append(_row(code, f"清单项{i}", "", "m3", 100, 100, 10000, row=i + 2))
        if i < n_aligned:
            bases.append(_base(code, f"清单项{i}", "", "m3", 100, 100, row=i + 5))
    return rows, bases


def test_new_item_skipped_when_baseline_coverage_is_20_percent():
    rows, bases = _coded_rows(1, 5)
    out = tk_engine.detect_full(rows, CFG, bases)
    assert [a for a in out["anomalies"] if a["subtype"] == "new_item"] == []
    assert out["baseline_stats"]["coverage"] == 0.2 and out["baseline_stats"]["new_item_checked"] is False
    assert "baseline_coverage_low" in [w["code"] for w in out["warning_items"]]


def test_new_item_reported_when_coverage_reaches_threshold():
    """对照：覆盖率 60% 时护栏放行，没对上的两行判合同外新增 —— 护栏不是把规则整个关掉。"""
    rows, bases = _coded_rows(3, 5)
    out = tk_engine.detect_full(rows, CFG, bases)
    assert sorted(a["row"] for a in out["anomalies"] if a["subtype"] == "new_item") == [5, 6]
    assert "baseline_coverage_low" not in [w["code"] for w in out["warning_items"]]


# ---------------------------------------------------------------- 基准文件端到端

def test_baseline_file_end_to_end_price_over_contract():
    """送审单价 500 对合同单价 400（勾选的中标清单文件）→ 单价疑似超合同，超出额 =（500−400）× 送审量。"""
    submit = _bill([["010501001001", "现浇混凝土基础", "C30", "m3", 120, 500, 60000]])
    contract = _bill([["010501001001", "现浇混凝土基础", "C30", "m3", 100, 400, 40000]], sheet="中标清单")
    res = tk_engine.run([(submit, "第3期进度款.xlsx", "S1")], None, project_id="P",
                        baseline_files=[(contract, "中标清单.xlsx", "B1")])
    by_rule = {a["subtype"]: a for a in res["anomalies"]}
    assert set(by_rule) == {"price_over_baseline"}, [a["subtype"] for a in res["anomalies"]]
    a = by_rule["price_over_baseline"]
    assert a["anomaly_type"] == "单价疑似超合同"
    assert a["reported_value"] == 500 and a["baseline_value"] == 400
    assert a["excess_amount"] == 12000 and a["severity"] == 12000 and a["line_amount"] == 60000
    assert a["baseline_ref"] == {"file": "中标清单.xlsx", "file_id": "B1", "sheet": "中标清单", "row": 2,
                                 "item_code": "010501001001", "item_name": "现浇混凝土基础", "unit": "m3"}
    assert res["baseline"]["status"] == "provided" and res["baseline"]["files"] == ["中标清单.xlsx"]


def test_unparsable_baseline_file_is_reported_not_silently_ignored():
    submit = _bill([["010101001001", "平整场地", "", "m2", 1000, 30, 30000]])
    res = tk_engine.run([(submit, "送审.xlsx", "S1")], None, project_id="P",
                        baseline_files=[(b"not a zip", "合同.xlsx", "B1")])
    assert "baseline_file_unparsed" in [w["code"] for w in res["warning_items"]]
    assert res["baseline"]["status"] == "invalid"
