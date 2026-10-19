# 来源：engine-service/tests/test_tk_sweep_evidence.py（zhitong-cost-ai@991ff5cd）
"""WS26-c（issue #792，P06）：投控重跑的「本轮证据」—— rules_run / rules_skipped / baseline.exact_rows /
file_coverage[].used_sheets。

修的现场：Java 清扫旧的待复核异常时只问「来源文件在不在本轮送出去的名单里」。于是
  · 文件这一轮读不出（unparsed / unpriced）→ 它上一轮的待复核全删；
  · 某张表这一轮没用上（口径歧义）→ 那张表上的旧待复核全删；
  · 没勾合同清单 → 四类基准规则根本没跑，旧的「单价 / 工程量疑似超合同、送审缺失、合同外新增」
    被删，或被「大额粗筛」顶替；
  · 基准只覆盖一部分行、跨文件判重缺了对家 → 没被重新判的行被删。
引擎手里本来就有这四样事实，以前没回给 Java。本文件钉住引擎这一半；Java 那一半见
TkSweepScopeTest / TkAnomalyUpsertPlannerTest。

夹具每条都走到会出错的那条分支（CLAUDE.md §5.2）；变异验收见 PR。
"""
from __future__ import annotations

import copy
import io

from openpyxl import Workbook

from tests.costsheet.fixtures.endpoint import HEADERS, client
from zt.tk import engine as tk_engine
from zt.costsheet.parser import parse_costsheet
from tests.costsheet.fixtures import costsheet_shapes as shapes


HEAD = ["序号", "项目编码", "项目名称", "项目特征描述", "计量单位", "工程量", "综合单价", "合价"]
# 进度款版式：合同量价 + 本期量价两组列
HEAD_PERIOD = ["序号", "项目编码", "项目名称", "计量单位", "合同工程量", "综合单价", "合同合价",
               "本期工程量", "本期合价"]

BASELINE_RULES = {"price_over_baseline", "qty_over_baseline", "missing_submit", "new_item"}
V1_RULES = {"duplicate": "group_members", "code_repeat": "group_members",
            "zangu": "all", "self_check": "all", "big_amount": "all"}


def _book(sheets: dict[str, tuple[list, list[list]]]) -> bytes:
    """{表名: (表头, [数据行…])} → xlsx 字节。数据行不含序号。"""
    wb = Workbook()
    first = True
    for title, (head, rows) in sheets.items():
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = title
        ws.append(head)
        for i, r in enumerate(rows, 1):
            ws.append([i] + list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _bill(rows: list[list], sheet: str = "分部分项清单与计价表") -> bytes:
    return _book({sheet: (HEAD, rows)})


# 送审 B：5 行。合同 A 覆盖前 4 行（R1 价超、R2 量超、R3 送审缺失、R4 正常），第 5 行合同里没有（R5 新增）
SUBMIT_B = [
    ["010501001001", "现浇混凝土基础", "C30", "m3", 120, 500, 60000],     # R1 单价 500 > 合同 400
    ["010502001001", "矩形柱", "C30", "m3", 200, 400, 80000],             # R2 量 200 > 合同 100
    ["010503001001", "矩形梁", "C30", "m3", None, None, None],            # R3 送审量价金额全空
    ["010504001001", "直形墙", "C30", "m3", 10, 300, 3000],               # R4 与合同一致
    ["010999999001", "签证增补", "", "项", 1, 10000, 10000],              # R5 合同外新增（合价 10,000）
]
CONTRACT_A = [
    ["010501001001", "现浇混凝土基础", "C30", "m3", 100, 400, 40000],
    ["010502001001", "矩形柱", "C30", "m3", 100, 400, 40000],
    ["010503001001", "矩形梁", "C30", "m3", 100, 500, 50000],
    ["010504001001", "直形墙", "C30", "m3", 10, 300, 3000],
]
SHEET = "分部分项清单与计价表"


def _run(submit_rows=None, contract_rows=None, **kw):
    files = [(_bill(submit_rows or SUBMIT_B), "送审B.xlsx", "S-B")]
    base = [(_bill(contract_rows, sheet="中标清单"), "合同A.xlsx", "B-A")] if contract_rows is not None else None
    return tk_engine.run(files, None, project_id="P", baseline_files=base, **kw)


# ---------------------------------------------------------------- rules_run：四种基准状态

def test_rules_run_without_baseline_has_only_v1_rules_and_names_the_four_skipped():
    """没勾合同清单：四类基准规则没跑。它们不在 rules_run 里，rules_skipped 给出原因。"""
    res = _run()
    assert res["baseline"]["status"] == "not_provided"
    assert res["rules_run"] == V1_RULES
    assert res["rules_skipped"] == {r: "baseline_not_provided" for r in BASELINE_RULES}
    assert res["baseline"]["exact_rows"] == {}


def test_rules_run_with_usable_baseline_has_all_rules_with_their_premises():
    res = _run(contract_rows=CONTRACT_A)
    assert res["baseline"]["status"] == "provided"
    assert res["rules_run"] == {**V1_RULES, "price_over_baseline": "exact_rows",
                                "qty_over_baseline": "exact_rows", "missing_submit": "exact_rows",
                                "new_item": "all"}
    assert res["rules_skipped"] == {}
    # 夹具自检：四类基准异常真的各出了一条（R1、R2、R3、R5），否则「跑了」就是空话
    by_rule = {a["subtype"]: a["row"] for a in res["anomalies"]}
    assert {k: by_rule.get(k) for k in BASELINE_RULES} == {
        "price_over_baseline": 2, "qty_over_baseline": 3, "missing_submit": 4, "new_item": 6}


def test_rules_run_when_baseline_file_is_unreadable_says_invalid_not_not_provided():
    """给了合同清单却读不出：与「没给」是两个原因，页面文案要分开说。"""
    files = [(_bill(SUBMIT_B), "送审B.xlsx", "S-B")]
    res = tk_engine.run(files, None, project_id="P", baseline_files=[(b"not a zip", "合同.xlsx", "B-A")])
    assert res["baseline"]["status"] == "invalid"
    assert res["rules_run"] == V1_RULES
    assert res["rules_skipped"] == {r: "baseline_invalid" for r in BASELINE_RULES}


def test_rules_run_when_coverage_is_low_drops_only_new_item():
    """合同清单只留一行（覆盖率 1/5 < 50%）：三条对齐规则照跑，只有 new_item 没跑。"""
    res = _run(contract_rows=CONTRACT_A[:1])
    assert res["baseline"]["stats"]["new_item_checked"] is False
    assert "new_item" not in res["rules_run"]
    assert {r: res["rules_run"].get(r) for r in BASELINE_RULES - {"new_item"}} == {
        "price_over_baseline": "exact_rows", "qty_over_baseline": "exact_rows", "missing_submit": "exact_rows"}
    assert res["rules_skipped"] == {"new_item": "baseline_coverage_low"}


def test_rules_disabled_in_config_are_not_in_rules_run():
    cfg = copy.deepcopy(tk_engine.load_rules())
    cfg["rules"]["big_amount"]["enabled"] = False
    cfg["rules"]["duplicate"]["enabled"] = False
    cfg["rules"]["qty_over_baseline"]["enabled"] = False
    rows = tk_engine.costsheet_items_to_rows(
        parse_costsheet(_bill(SUBMIT_B), "送审B.xlsx", side="submit", file_id="S-B")["items"], "P", "送审B.xlsx")
    bases = tk_engine.baseline_rows_from_items(
        parse_costsheet(_bill(CONTRACT_A), "合同A.xlsx", basis="contract", file_id="B-A")["items"], "P", "合同A.xlsx")
    out = tk_engine.detect_full(rows, cfg, bases)
    assert set(out["rules_run"]) == {"zangu", "self_check", "price_over_baseline", "missing_submit", "new_item"}
    assert out["rules_skipped"] == {"big_amount": "rule_disabled", "duplicate": "rule_disabled",
                                    "code_repeat": "rule_disabled", "qty_over_baseline": "rule_disabled"}
    # 没有基准时，被配置关掉的基准规则原因仍是「关掉了」，不是「没给基准」
    out2 = tk_engine.detect_full(rows, cfg, None)
    assert out2["rules_skipped"]["qty_over_baseline"] == "rule_disabled"
    assert out2["rules_skipped"]["price_over_baseline"] == "baseline_not_provided"


# ---------------------------------------------------------------- exact_rows 与行级前提

def test_exact_rows_lists_only_strictly_aligned_rows_keyed_by_file_and_sheet():
    """R5（合同里没有）不在里面；同码不同名的行（CONFLICT）也不在里面。"""
    submit = SUBMIT_B + [["010504001001", "直形墙-改名", "C30", "m3", 10, 300, 3000]]   # 同码不同名 → CONFLICT
    res = _run(submit_rows=submit, contract_rows=CONTRACT_A)
    assert res["baseline"]["exact_rows"] == {"S-B": {SHEET: [2, 3, 4, 5]}}
    assert [i["row"] for i in res["alignment_issues"]] == [7], "夹具自检：第 7 行应是 CONFLICT"


def test_ambiguous_row_is_not_in_exact_rows_so_its_old_pending_is_not_swept():
    """WS26-m（issue #828）：合同清单里有两行可对、分不清对哪一行（AMBIGUOUS）的送审行，三条基准规则
    这一轮没有判它 —— 不在 exact_rows 里，Java 就不会把它上一轮的「超合同 / 送审缺失」待复核当成
    「问题没了」删掉。规则本身照样算「跑了」，所以光看 rules_run 会误删。"""
    wall = ["010401003001", "实心砖墙", "MU10", "m3"]
    contract = _book({"6#楼土建": (HEAD, [wall + [100, 480, 48000], CONTRACT_A[0]]),
                      "7#楼土建": (HEAD, [wall + [120, 480, 57600], CONTRACT_A[1]])})
    # 送审表名「6#楼」与合同的「6#楼土建」写法不同：实心砖墙这一行收窄不到唯一一行
    submit = _book({"6#楼": (HEAD, [wall + [200, 480, 96000], SUBMIT_B[0], SUBMIT_B[1]])})
    res = tk_engine.run([(submit, "送审B.xlsx", "S-B")], None, project_id="P",
                        baseline_files=[(contract, "合同A.xlsx", "B-A")])
    assert [(i["row"], i["method"]) for i in res["alignment_issues"]] == [(2, "ambiguous")], "夹具自检"
    for rule in ("price_over_baseline", "qty_over_baseline", "missing_submit"):
        assert res["rules_run"][rule] == "exact_rows"
    assert res["baseline"]["exact_rows"] == {"S-B": {"6#楼": [3, 4]}}
    # 夹具自检：另外两行真的被基准规则判到了（R1 价超、R2 量超），第 2 行一条合同类都没有
    hits = sorted((a["subtype"], a["row"]) for a in res["anomalies"] if a["subtype"] in BASELINE_RULES)
    assert hits == [("price_over_baseline", 3), ("qty_over_baseline", 4)]


def test_row_premise_matches_what_each_rule_actually_judges():
    """行级前提与实现一致：声明 exact_rows 的规则，命中行必在 exact_rows 里；把那一行的基准拿掉，
    规则虽然「跑了」，却不再判这一行（所以 Java 不能据此把它当成「问题没了」）。"""
    full = _run(contract_rows=CONTRACT_A)
    exact = set(full["baseline"]["exact_rows"]["S-B"][SHEET])
    for a in full["anomalies"]:
        premise = full["rules_run"][a["subtype"]]
        if premise == "exact_rows":
            assert a["row"] in exact, a
    assert {a["row"] for a in full["anomalies"] if a["subtype"] == "new_item"}.isdisjoint(exact), \
        "new_item 判的是「没对上」的行，前提只能是 all"

    # 合同清单去掉 R1 那一行、其余三行还在（覆盖率 3/5 过线，四条规则都跑）
    partial = _run(contract_rows=CONTRACT_A[1:])
    assert partial["rules_run"]["price_over_baseline"] == "exact_rows"
    assert 2 not in partial["baseline"]["exact_rows"]["S-B"][SHEET]
    assert [a for a in partial["anomalies"] if a["subtype"] == "price_over_baseline"] == [], \
        "R1 没对上基准：规则跑了但没判它"


def test_duplicate_premise_is_group_members_and_members_name_every_file_in_the_group():
    """跨文件判重：同期次两份文件各一行同码。只送其中一份时这一组拼不出来 —— 所以前提是 group_members，
    每条异常的 members 带着对家的 file_id，Java 据此判断对家这一轮在不在。"""
    row = ["010101001001", "平整场地", "", "m2", 100, 30, 3000]
    a = (_bill([row], sheet="1#楼"), "进度款2024年5月-土建.xlsx", "F-TJ")
    b = (_bill([row], sheet="1#楼"), "进度款2024年5月-土建补报.xlsx", "F-BB")
    both = tk_engine.run([a, b], None, project_id="P")
    dup = [x for x in both["anomalies"] if x["subtype"] == "duplicate"]
    assert len(dup) == 2 and both["rules_run"]["duplicate"] == "group_members"
    assert {m["file_id"] for m in dup[0]["members"]} == {"F-TJ", "F-BB"}
    alone = tk_engine.run([a], None, project_id="P")
    assert [x for x in alone["anomalies"] if x["subtype"] == "duplicate"] == [], "少了对家，这一行不再命中"
    assert alone["rules_run"]["duplicate"] == "group_members", "规则照样算「跑了」—— 光看规则会误删"


# ---------------------------------------------------------------- used_sheets

def test_used_sheets_equals_meta_sheets():
    for raw, name in ((shapes.labor_machine_tables(), "市政控制价.xlsx"),
                      (shapes.header_broken_with_codes(), "浙大第五期.xlsx"),
                      (shapes.zheda_three_row_header(), "浙大.xlsx")):
        out = parse_costsheet(raw, name, side="submit")
        assert out["meta"]["coverage"]["used_sheets"] == out["meta"]["sheets"], name
        assert out["meta"]["sheets"], f"{name}：夹具自检 —— 至少要有一张 used 的表"


def test_unreadable_file_has_empty_used_sheets_not_a_missing_key():
    out = parse_costsheet(b"not a zip", "坏文件.xlsx")
    assert out["meta"]["coverage"]["status"] == "unparsed"
    assert out["meta"]["coverage"]["used_sheets"] == []


def test_sheet_dropped_this_round_is_in_neither_used_nor_skipped_sheets():
    """「表」这条路的要害：表A（表名不像清单、只有 2 个编码、只有不分期合价列）口径自动时计入；
    口径选「本期」时它判歧义、不计入 —— 但它不够 3 个编码，**不在 skipped_sheets 里**。
    拿 skipped_sheets 反推「哪些表没用上」会漏掉它，Java 只能认 used_sheets。"""
    raw = _book({
        "1#楼": (HEAD, [["010101001001", "平整场地", "", "m2", 1000, 30, 30000],
                        ["010401003001", "实心砖墙", "", "m3", 50, 480, 24000]]),
        "2#楼": (HEAD_PERIOD, [["010501001001", "现浇混凝土基础", "m3", 100, 500, 50000, 60, 30000],
                              ["010502001001", "矩形柱", "m3", 100, 600, 60000, 50, 30000]]),
    })
    auto = tk_engine.run([(raw, "进度款.xlsx", "F1")], None, project_id="P", basis="auto")
    cur = tk_engine.run([(raw, "进度款.xlsx", "F1")], None, project_id="P", basis="current")
    assert auto["file_coverage"][0]["used_sheets"] == ["1#楼", "2#楼"]
    cov = cur["file_coverage"][0]
    assert cov["status"] == "parsed" and cov["used_sheets"] == ["2#楼"]
    assert cov["skipped_sheets"] == [], "表A 不在 skipped_sheets 里 —— 这正是不能拿它反推的原因"
    # 口径自动那一轮，表A 上有大额粗筛（30000、24000 ≥ 2 万）；口径本期这一轮表A 整张没看
    assert {a["sheet"] for a in auto["anomalies"]} >= {"1#楼"}
    assert "1#楼" not in {a["sheet"] for a in cur["anomalies"]}


# ---------------------------------------------------------------- 端点透出

def test_endpoint_exposes_the_evidence_fields():
    ref = shapes.put(_bill(SUBMIT_B), "ws26c-送审B.xlsx", "S-B")
    base = shapes.put(_bill(CONTRACT_A, sheet="中标清单"), "ws26c-合同A.xlsx", "B-A")
    r = client.post("/engine/tk/detect", headers=HEADERS,
                    json={"submission_files": [ref], "baseline_files": [base], "project_id": "P"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rules_run"]["price_over_baseline"] == "exact_rows"
    assert body["rules_skipped"] == {}
    assert body["baseline"]["exact_rows"] == {"S-B": {SHEET: [2, 3, 4, 5]}}
    assert body["file_coverage"][0]["used_sheets"] == [SHEET]
