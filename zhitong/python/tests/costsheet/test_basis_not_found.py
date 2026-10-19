# 来源：engine-service/tests/test_basis_not_found.py（zhitong-cost-ai@991ff5cd）
"""WS26-e（issue #967，实测缺陷 07-009 第 1、2 项；spec WS26 §1.2 P10、§3.4）：口径选错时指对方向。

修的现场（TK-F01 / TK-F02）：投控送审只勾「…一标段.xlsx」（表头「工程量 / 综合单价 / 合价」，不分期），口径选「本期」。
横幅正文是「submission_files 全部解析失败：表头存在多组金额列，无法确定口径，请选择对比口径：…一标段.xlsx」——
表头只有一组不分期的合价列，根本没有「多组」；用户被叫去「选择对比口径」，而他刚选的正是不存在的那个；
还露出了字段名 submission_files。根因：costsheet 把「表头有金额列、只是没有所要期次」也记成 ambiguous +
column_ambiguous，投控 / 对账只看 ambiguous 就套那句话；422 的 detail 是字符串，Java 没有机器码、没有可用口径。

期望值逐条手写（夹具真值见 tests/fixtures/costsheet_shapes.py 各夹具 docstring），不从解析器输出反抄。
"""
from __future__ import annotations

import pytest

from tests.costsheet.fixtures.endpoint import HEADERS, client
from zt.indicator import engine as indicator_engine
from zt.reconcile import engine as reconcile_engine
from zt.tk import engine as tk_engine
from zt.costsheet.parser import parse_costsheet
from tests.costsheet.fixtures import costsheet_shapes as shapes



def _codes(out: dict) -> list[str]:
    return [w["code"] for w in out["warning_items"]]


def _w(out: dict, code: str) -> dict:
    return next(w for w in out["warning_items"] if w["code"] == code)


# ---------------------------------------------------------------- 1. 表级：basis_missing 与 ambiguous 分开

def test_plain_amount_table_with_current_basis_is_basis_missing_not_ambiguous():
    """只有不分期合价列的表选「本期」：状态 basis_missing、码 basis_not_found（不是 column_ambiguous）；
    basis_available 只有 plain；文案写「不分期的合价列」，不写「合同价」（评审 S7：不分期 ≠ 合同价）。"""
    out = parse_costsheet(shapes.detail_with_total(), "一标段.xlsx", basis="current")
    d = out["meta"]["sheets_detail"][0]
    assert out["items"] == [] and d["status"] == "basis_missing"
    assert "basis_not_found" in _codes(out) and "column_ambiguous" not in _codes(out)
    assert out["meta"]["basis_available"] == ["plain"]
    w = _w(out, "basis_not_found")
    assert w["level"] == "error" and "「本期」" in w["message"] and "不分期的合价列" in w["message"]
    assert "合同价" not in w["message"]
    assert w["hint"] == "这张表没有所选口径的金额列。请改用『自动』。"


def test_contract_and_current_table_with_cumulative_names_both_and_offers_contract():
    """有合同价、本期两组列、没有累计的表选「累计」：文案写出「合同价」「本期」，提示可改「自动」或「合同价」。"""
    out = parse_costsheet(shapes.contract_and_current_columns(), "进度款.xlsx", basis="cumulative")
    assert out["meta"]["sheets_detail"][0]["status"] == "basis_missing"
    assert out["meta"]["basis_available"] == ["contract", "current"]
    w = _w(out, "basis_not_found")
    assert "合同价列" in w["message"] and "本期列" in w["message"] and "「累计」" in w["message"]
    assert "可改用『自动』或『合同价』" in w["hint"]
    # 同一张表选「本期」「合同价」都读得出（真值：本期 4,800 + 3,120；合同 96,000 + 52,000）
    assert parse_costsheet(shapes.contract_and_current_columns(), "x.xlsx", basis="current")["meta"]["parsed_total"] \
        == 7920.0
    assert parse_costsheet(shapes.contract_and_current_columns(), "x.xlsx", basis="contract")["meta"]["parsed_total"] \
        == 148000.0


def test_contract_vs_settle_amount_under_auto_stays_column_ambiguous():
    """「合同金额 | 结算金额」并列、auto：真正的「多组列分不清」，老行为不能被新分支吃掉。"""
    out = parse_costsheet(shapes.contract_and_settle_amounts(), "结算.xlsx", basis="auto")
    assert out["meta"]["sheets_detail"][0]["status"] == "ambiguous"
    assert "column_ambiguous" in _codes(out) and "basis_not_found" not in _codes(out)


def test_only_price_ambiguity_under_a_missing_basis_is_reported_as_missing():
    """「综合单价 | 全费用单价 | 合价」选「本期」：金额、工程量在本期下没有候选，单价退到合同 / 不分期时两列并存。
    真正的原因是本期列不存在 —— 改前这条路判成「口径有歧义」，仍指反方向。"""
    out = parse_costsheet(shapes.two_unit_prices_plain_amount(), "x.xlsx", basis="current")
    # 夹具真的够到单价歧义这条分支：auto（落到不分期）时就是单价两列分不清
    auto = parse_costsheet(shapes.two_unit_prices_plain_amount(), "x.xlsx", basis="auto")
    assert auto["meta"]["sheets_detail"][0]["status"] == "ambiguous"
    assert "price：综合单价 | 全费用单价" in auto["meta"]["sheets_detail"][0]["reason"]
    assert out["meta"]["sheets_detail"][0]["status"] == "basis_missing"
    assert "basis_not_found" in _codes(out) and "column_ambiguous" not in _codes(out)


def test_auto_with_cumulative_only_points_to_cumulative():
    """auto 落到「合同或不分期」也取不到（表里只有累计列）：指路到『累计』，不叫人「改用自动」。"""
    out = parse_costsheet(shapes.cumulative_only_columns(), "x.xlsx", basis="auto")
    w = _w(out, "basis_not_found")
    assert "累计列" in w["message"] and w["hint"].endswith("请改用『累计』。")
    assert "『自动』" not in w["hint"]


def test_listy_basis_missing_sheet_still_counts_against_coverage():
    """basis_missing 的表照旧进 skipped_listy（有清单的表被跳过）—— 拆出新状态不许顺手改掉覆盖率口径。"""
    out = parse_costsheet(shapes.detail_with_total(), "x.xlsx", basis="current")
    assert "sheet_skipped_has_items" in _codes(out)
    assert out["meta"]["coverage"]["skipped_sheets"] == ["分部分项清单与计价表"]


# ---------------------------------------------------------------- 2. 投控：422 的 detail 是对象，指对方向

def _tk(files: list[dict], basis: str = "current"):
    return client.post("/engine/tk/detect", headers=HEADERS,
                       json={"project_id": "P1", "submission_files": files, "basis": basis})


def test_tk_single_file_basis_missing_is_422_with_object_detail():
    """TK-F01 的形状：detail 是对象，reason_code=basis_not_found；message 含「『本期』」「不存在」「不分期的合价列」，
    不含「请选择对比口径」、不含 submission_files（生产验收第 2 步的判据）。"""
    f = shapes.put(shapes.detail_with_total(), "ws26e-一标段.xlsx", "F1")
    r = _tk([f])
    assert r.status_code == 422, r.text[:300]
    d = r.json()["detail"]
    assert isinstance(d, dict)
    assert d["reason_code"] == "basis_not_found"
    assert d["message"] == ("所选口径『本期』在以下文件的表头里不存在：ws26e-一标段.xlsx。"
                            "这些文件的金额列是不分期的合价列。请改用『自动』。")
    assert "请选择对比口径" not in d["message"] and "submission_files" not in d["message"]
    assert d["basis_requested"] == "current" and d["basis_available"] == ["plain"]
    assert d["files"] == [{"file": "ws26e-一标段.xlsx", "file_id": "F1", "status": "basis_missing",
                           "basis_available": ["plain"]}]
    assert d["hint"] == "勾选的文件不用改，只把对比口径换掉再开始。", "hint 不重复 message 的最后一句"


def test_tk_all_ambiguous_keeps_the_sentence_without_field_name():
    """全是多组列分不清：保持原句，只把 submission_files 换成「送审文件」；reason_code=column_ambiguous。"""
    f = shapes.put(shapes.a1_period_qty("split"), "ws26e-A1-歧义.xlsx", "A1")
    r = _tk([f], basis="auto")
    assert r.status_code == 422, r.text[:300]
    d = r.json()["detail"]
    assert d["reason_code"] == "column_ambiguous"
    assert d["message"] == ("送审文件全部没有读出清单：表头存在多组金额列，无法确定口径，请选择对比口径："
                            "ws26e-A1-歧义.xlsx")
    assert "submission_files" not in d["message"]


def test_tk_auto_basis_missing_uses_another_code_so_no_auto_retry_button():
    """选的本来就是「自动」还读不出（表里只有累计列）：再给「改用自动口径重新选择」没有用，换码 auto_basis_not_found；
    message 指路到『累计』。"""
    f = shapes.put(shapes.cumulative_only_columns(), "ws26e-只有累计.xlsx", "C1")
    r = _tk([f], basis="auto")
    assert r.status_code == 422, r.text[:300]
    d = r.json()["detail"]
    assert d["reason_code"] == "auto_basis_not_found"
    assert d["message"].startswith("按『自动』口径（有本期列取本期，否则取合同价或不分期列）在以下文件里取不到金额列：")
    assert d["message"].endswith("这些文件的金额列是累计列。请改用『累计』。")


def test_tk_two_files_both_missing_are_both_listed():
    """两份都没有本期列：files 里两份都是 basis_missing；auto 下不分期那份读得出（不是一律 422）。"""
    a = shapes.put(shapes.detail_with_total(), "ws26e-不分期.xlsx", "M1")
    b = shapes.put(shapes.contract_and_settle_amounts(), "ws26e-合同结算.xlsx", "M2")
    r = _tk([a, b], basis="auto")
    assert r.status_code == 200
    r = _tk([a, b], basis="current")
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["reason_code"] == "basis_not_found"
    assert {f["file"]: f["status"] for f in d["files"]} == {"ws26e-不分期.xlsx": "basis_missing",
                                                          "ws26e-合同结算.xlsx": "basis_missing"}


def test_tk_mixed_message_has_both_sentences():
    """一份口径不存在、一份多组列分不清：两句都写；reason_code 取 basis_not_found（改口径能救回前一份）。"""
    with pytest.raises(tk_engine.ParseFailed) as ei:
        tk_engine.run([(shapes.detail_with_total(), "不分期.xlsx", "X1"),
                       (shapes.a1_period_qty("split"), "A1-歧义.xlsx", "X2")], None, basis="current")
    d = ei.value.detail()
    assert d["reason_code"] == "basis_not_found"
    assert d["message"].startswith("送审文件全部没有读出清单。所选口径『本期』在以下文件的表头里不存在：不分期.xlsx。")
    assert "另有文件表头存在多组金额列，无法确定口径，请选择对比口径：A1-歧义.xlsx" in d["message"]


def test_tk_generic_failure_has_no_field_name():
    """非口径原因（不是清单表）的 422 也不再露 submission_files。"""
    import io

    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "编制说明"
    wb.active.append(["本工程招标控制价编制说明"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(tk_engine.ParseFailed) as ei:
        tk_engine.run([(buf.getvalue(), "说明.xlsx", "G1")], None)
    assert "submission_files" not in str(ei.value) and str(ei.value).startswith("送审文件全部没有读出清单：")
    assert ei.value.detail()["reason_code"] is None


def test_tk_partial_basis_missing_is_200_partial_with_the_warning():
    """多文件里部分 basis_missing：任务照常出结果，告警里有 basis_not_found（error → partial）。"""
    ok = shapes.put(shapes.contract_and_current_columns(), "ws26e-有本期.xlsx", "P1")
    bad = shapes.put(shapes.detail_with_total(), "ws26e-无本期.xlsx", "P2")
    r = _tk([ok, bad])
    assert r.status_code == 200, r.text[:300]
    body = r.json()
    assert body["status"] == "partial"
    w = [x for x in body["warning_items"] if x["code"] == "basis_not_found"]
    assert len(w) == 1 and w[0]["file"] == "ws26e-无本期.xlsx" and w[0]["hint"]


# ---------------------------------------------------------------- 3. 对账：同一套说法

def test_reconcile_basis_missing_is_422_basis_not_found():
    a = shapes.put(shapes.detail_with_total(), "ws26e-对账送审.xlsx", "RA")
    b = shapes.put(shapes.resaved(shapes.detail_with_total()), "ws26e-对账审定.xlsx", "RB")
    r = client.post("/engine/reconcile/run", headers=HEADERS,
                    json={"submitted_file": a, "approved_file": b, "basis": "current"})
    assert r.status_code == 422, r.text[:300]
    d = r.json()["detail"]
    assert d["reason_code"] == "basis_not_found"
    assert d["message"].startswith("所选口径『本期』在以下文件的表头里不存在：送审文件「ws26e-对账送审.xlsx」。")
    assert "不分期的合价列" in d["message"] and "请选择对比口径" not in d["message"]
    assert d["files"][0]["file_id"] == "RA"


def test_reconcile_ambiguous_keeps_the_original_sentence():
    with pytest.raises(reconcile_engine.ParseFailed) as ei:
        reconcile_engine.run(shapes.a1_period_qty("split"), "A1.xlsx",
                             shapes.resaved(shapes.a1_period_qty("split")), "A1-审定.xlsx")
    msg = str(ei.value)
    assert msg.startswith("送审文件「A1.xlsx」解析失败：表头存在多组金额列，无法确定口径，请选择对比口径（")
    assert ei.value.reason_code == "column_ambiguous"


# ---------------------------------------------------------------- 4. 指标：没有口径可选，原因写清楚

def test_indicator_progress_only_file_says_which_columns_it_has():
    """指标按合同价口径取数。表里只有累计列：files_failed 的原因写「表头只有累计列」，不笼统写「未识别」。"""
    with pytest.raises(indicator_engine.ParseFailed) as ei:
        indicator_engine.run([(shapes.cumulative_only_columns(), "累计.xlsx", "I1")], {})
    assert "累计.xlsx" in str(ei.value)
    d = ei.value.detail()
    assert d["message"] == str(ei.value) and d["reason_code"] is None


def test_indicator_files_failed_reason_names_the_columns():
    out = indicator_engine.run([(shapes.cumulative_only_columns(), "累计.xlsx", "I1"),
                                (shapes.detail_with_total(), "标准.xlsx", "I2")], {"gross_area": 100})
    (f,) = out["files_failed"]
    assert f["reason"] == "表头只有累计列，没有合同价或不分期的合价列（指标按合同价口径计算）"
