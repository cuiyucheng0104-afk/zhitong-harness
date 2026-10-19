# 来源：engine-service/tests/test_measure_sheets_skipped.py（zhitong-cost-ai@991ff5cd）
"""WS26-e（issue #967，实测缺陷 07-004 第 1 项的引擎侧、07-003 的披露部分；spec WS26 §1.2 P11、P20，§3.4；
总纲 D-R87 / D-R162）：跳表告警压缩 + 读不了的技术措施表如实披露 + 范围标签。

修的现场（TK-C03、RF-30）：「…一标段.xlsx」355 张表，被「按标题跳过」的 242 张（费用表 129 + 措施表 113）
用顿号拼进一句 info 告警，7448 字、页面上高 943px；措施表被说成「非清单表」（它们带清单编码行，金额没算进去）。
WS26-p 上线后能勾稽的措施表已经读入，本片只对**读不进来的**措施表出黄字（所选口径读不出 / 版式认不出），
勾稽不过的那种已有 measure_sheet_unreconciled（红）。

夹具 shapes.unreadable_measure_sheets / progress_with_measure_calc / measure_calc_sheets 的真值见各自 docstring。
"""
from __future__ import annotations


from tests.costsheet.fixtures.endpoint import HEADERS, client
from zt.reconcile import engine as reconcile_engine
from zt.tk import engine as tk_engine
from zt.costsheet.parser import parse_costsheet
from tests.costsheet.fixtures import costsheet_shapes as shapes



def _ws(out: dict, code: str) -> list[dict]:
    return [w for w in out["warning_items"] if w["code"] == code]


# ---------------------------------------------------------------- 1. 读不了的措施表：单独一条 warn

def test_unreadable_measure_sheets_get_their_own_warn_not_non_list_wording():
    """2 张有清单编码的措施分析表（版式认不出）+ 1 张没有编码的 → measure_sheets_skipped，warn 级；
    文案不含「非清单表」；sheets 是这 3 张表名；它们不再出现在「按标题跳过」那一条里。"""
    out = parse_costsheet(shapes.unreadable_measure_sheets(n_fee=2, n_measure=2, n_measure_no_code=1),
                          "一标段.xlsx")
    (m,) = _ws(out, "measure_sheets_skipped")
    assert m["level"] == "warn"
    assert "非清单表" not in m["message"]
    assert m["message"] == ("施工技术措施项目 3 张表没有参与（其中 2 张有清单编码行）："
                            "版式认不出（缺「清单序号」或「综合单价 / 小计」列）；结果只含分部分项清单")
    assert m["sheets"] == ["措施综合单价分析表1", "措施综合单价分析表2", "措施综合单价分析表N1"]
    assert "人工核对" in m["hint"]
    (t,) = _ws(out, "sheets_skipped_by_title")
    assert t["level"] == "info" and t["message"] == "按标题跳过 2 张表（费用表 2）"
    assert t["sheets"] == ["表-13 单位工程费用表1", "表-13 单位工程费用表2"]
    cov = out["meta"]["coverage"]
    assert cov["measure_skipped"] == {"sheets": 3, "sheets_with_codes": 2, "unreconciled": 0}
    assert cov["measure_used"] == 0
    assert cov["scope_label"] == "仅分部分项清单（施工技术措施项目 3 张表未参与）"
    # 覆盖率的分母不含措施表：改的是说法，不是数（spec §3.4 第 5 条）
    assert (cov["level"], cov["ratio"], cov["amount_used"]) == ("ok", 1.0, 20000.0)


def test_measure_disclosure_does_not_make_the_task_partial():
    """warn 不触发 partial（stubs._status）：这类工作簿不能每次都是黄色「部分完成」（U14 / D-R87）。"""
    f = shapes.put(shapes.unreadable_measure_sheets(), "ws26e-措施读不了.xlsx", "U1")
    r = client.post("/engine/tk/detect", headers=HEADERS, json={"project_id": "P1", "submission_files": [f]})
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["status"] == "ok", body["warning_items"]
    (m,) = [w for w in body["warning_items"] if w["code"] == "measure_sheets_skipped"]
    assert m["level"] == "warn" and m["sheets"] == ["措施综合单价分析表1", "措施综合单价分析表2"]
    assert body["scope_label"] == "仅分部分项清单（施工技术措施项目 2 张表未参与）"


def test_only_fee_and_cover_sheets_skipped_gives_no_measure_warning():
    """被跳过的全是费用表、封面 → 只有 sheets_skipped_by_title（info），没有措施告警、没有范围标签。"""
    out = parse_costsheet(shapes.unreadable_measure_sheets(n_fee=3, n_measure=0, cover=True), "x.xlsx")
    assert _ws(out, "measure_sheets_skipped") == []
    (t,) = _ws(out, "sheets_skipped_by_title")
    assert t["level"] == "info" and t["message"] == "按标题跳过 4 张表（费用表 3、封面 1）"
    assert len(t["sheets"]) == 4
    assert out["meta"]["coverage"]["scope_label"] is None


def test_242_skipped_sheets_give_two_short_messages():
    """TK-C03 的量级：129 张费用表 + 113 张措施表 → 两条 message 都短于 80 字，sheets 合计 242 项。"""
    out = parse_costsheet(shapes.unreadable_measure_sheets(n_fee=129, n_measure=108, n_measure_no_code=5),
                          "一标段.xlsx")
    (m,) = _ws(out, "measure_sheets_skipped")
    (t,) = _ws(out, "sheets_skipped_by_title")
    assert len(m["message"]) < 80 and len(t["message"]) < 80, (m["message"], t["message"])
    assert len(m["sheets"]) + len(t["sheets"]) == 242
    assert "113 张" in m["message"] and "108 张有清单编码行" in m["message"]
    assert t["message"] == "按标题跳过 129 张表（费用表 129）"
    # 旧的字符串通道（Java 的 engine_warning、旧前端）同样只拿到短句
    assert all(len(s) < 120 for s in out["warnings"])


def test_measure_calc_sheet_unreadable_under_current_basis_says_why():
    """WS26-p 认得出的措施计算表，选「本期」时没有那个口径 → 黄字写「所选口径「本期」读不出」，hint 指向「自动」。"""
    out = parse_costsheet(shapes.progress_with_measure_calc(), "进度款.xlsx", basis="current")
    assert out["meta"]["parsed_total"] == 4800.0
    (m,) = _ws(out, "measure_sheets_skipped")
    assert "所选口径「本期」读不出" in m["message"] and "『自动』" in m["hint"]
    assert _ws(out, "sheets_skipped_by_title") == []
    # auto：措施表读入，什么都不用披露
    auto = parse_costsheet(shapes.progress_with_measure_calc(), "进度款.xlsx", basis="auto")
    assert _ws(auto, "measure_sheets_skipped") == []
    assert auto["meta"]["coverage"]["scope_label"] == "分部分项 + 技术措施清单"


# ---------------------------------------------------------------- 2. WS26-p 读进来的、勾稽不过的、不重复计的

def test_all_measure_sheets_read_no_yellow_and_scope_says_both():
    """p 上线后本项目的形状：措施表全部读入、一张没有清单序号（measure_empty）→ 不出黄字，
    范围「分部分项 + 技术措施清单」，灰字只数费用表（spec 生产验收第 6 步「p 已上线」那一种）。"""
    out = parse_costsheet(shapes.measure_calc_sheets(), "一标段.xlsx")
    assert _ws(out, "measure_sheets_skipped") == []
    (t,) = _ws(out, "sheets_skipped_by_title")
    assert t["message"] == "按标题跳过 3 张表（费用表 3）"
    cov = out["meta"]["coverage"]
    assert cov["measure_used"] == 2 and cov["measure_skipped"]["sheets"] == 0
    assert cov["scope_label"] == "分部分项 + 技术措施清单"


def test_unreconciled_measure_sheet_counts_in_scope_but_no_duplicate_yellow():
    """勾稽不过的那张已有红色 measure_sheet_unreconciled：不再叠一条黄字；范围标签写它未参与。"""
    out = parse_costsheet(shapes.measure_calc_sheets(fee_delta=2.0), "一标段.xlsx")
    assert len(_ws(out, "measure_sheet_unreconciled")) == 1
    assert _ws(out, "measure_sheets_skipped") == []
    cov = out["meta"]["coverage"]
    assert cov["measure_skipped"] == {"sheets": 1, "sheets_with_codes": 1, "unreconciled": 1}
    assert cov["scope_label"] == "分部分项 + 技术措施清单（施工技术措施项目 1 张表未参与）"


def test_measure_calc_skipped_because_list_is_counted_is_grey_not_yellow():
    """同一单位工程已有计入的措施项目清单与计价表：计算表不重复计，归进灰字（措施项已在清单表里），不是没读进来。"""
    out = parse_costsheet(shapes.measure_calc_sheets(with_measure_list=True), "一标段.xlsx")
    assert _ws(out, "measure_sheets_skipped") == []
    (t,) = _ws(out, "sheets_skipped_by_title")
    assert t["message"] == "按标题跳过 4 张表（费用表 3、措施项目清单已计入 1）"
    assert out["meta"]["coverage"]["scope_label"] == "分部分项 + 技术措施清单"


# ---------------------------------------------------------------- 3. 范围标签进三条链的结果

def test_reconcile_summary_carries_scope_label_per_side():
    raw = shapes.measure_calc_sheets()
    res = reconcile_engine.run(raw, "送审.xlsx", shapes.measure_calc_sheets(audit_qty=180.0), "审定.xlsx")
    assert res["summary"]["scope_label"] == {"submitted": "分部分项 + 技术措施清单",
                                             "approved": "分部分项 + 技术措施清单"}
    res2 = reconcile_engine.run(shapes.unreadable_measure_sheets(), "a.xlsx",
                                shapes.resaved(shapes.unreadable_measure_sheets()), "b.xlsx")
    assert res2["summary"]["scope_label"]["submitted"] == "仅分部分项清单（施工技术措施项目 2 张表未参与）"


def test_tk_scope_label_sums_parsed_files_only():
    res = tk_engine.run([(shapes.unreadable_measure_sheets(n_measure=2), "a.xlsx", "A"),
                         (shapes.unreadable_measure_sheets(n_measure=1), "b.xlsx", "B"),
                         (shapes.unpriced_bill(), "招标清单.xlsx", "C")], None)
    assert res["scope_label"] == "仅分部分项清单（施工技术措施项目 3 张表未参与）"


# ---------------------------------------------------------------- 4. 合同清单一侧的措施表（WS26-p 评审留下）

def test_baseline_measure_sheet_unreconciled_is_reported_not_swallowed():
    """合同清单里措施表勾稽不过：那个单位工程的措施项不在基准里，送审侧的措施项会被判成「合同外新增」。
    改前合同清单的解析告警一条都不回传，任务是绿的；现在回传 measure_sheet_unreconciled（写明是哪份合同清单），
    任务 partial。"""
    sub = shapes.put(shapes.measure_calc_sheets(), "ws26e-送审.xlsx", "S")
    base = shapes.put(shapes.measure_calc_sheets(fee_delta=2.0), "ws26e-合同清单.xlsx", "C")
    r = client.post("/engine/tk/detect", headers=HEADERS,
                    json={"project_id": "P1", "submission_files": [sub], "baseline_files": [base]})
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    w = [x for x in body["warning_items"] if x["code"] == "measure_sheet_unreconciled"]
    assert len(w) == 1 and w[0]["file"] == "ws26e-合同清单.xlsx"
    assert w[0]["message"].startswith("合同/中标清单「ws26e-合同清单.xlsx」：") and "合同比对" in w[0]["message"]
    assert body["status"] == "partial"
    # 合同清单完好时不回传任何东西
    good = shapes.put(shapes.measure_calc_sheets(), "ws26e-合同清单-好.xlsx", "C2")
    r2 = client.post("/engine/tk/detect", headers=HEADERS,
                     json={"project_id": "P1", "submission_files": [sub], "baseline_files": [good]})
    assert not [x for x in r2.json()["warning_items"] if x["code"].startswith("measure_")]
