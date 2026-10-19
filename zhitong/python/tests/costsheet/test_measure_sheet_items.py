# 来源：engine-service/tests/test_measure_sheet_items.py（zhitong-cost-ai@991ff5cd）
"""WS26-p（issue #883，实测缺陷 07-003）：施工技术措施项目综合单价计算表读入清单项行，与费用表逐表勾稽。

修的现场：测试项目的招标控制价「…一标段.xlsx」有 113 张「表10.2.2-17 施工技术措施项目综合单价计算表」，
被 _SHEET_SKIP 的「综合单价计算」整张按标题跳过 —— 108 张里 625 个措施清单项、39,071,850.25 元
（占应检金额 17.4%）不参与投控检测、对账、指标；界面是绿色「已完成」。只把跳过词拿掉也不行：
「综合单价」下有 6 个子列，现在的解析器把这 113 张全判成 ambiguous，一行都读不出。

夹具 shapes.measure_calc_sheets 照原件的形状脱敏造（CLAUDE.md §5.2：夹具要够得到会错的分支）：
定额子目行有单位、数量、单价，形状和清单项很像（读错一行就是重复计）；「合计(元)」列是取整到元的数；
另有费用表「施工技术措施项目」行可以勾稽。期望值全部按夹具构造手算（见夹具 docstring），不从解析器输出反抄。
"""
from __future__ import annotations

import pytest

from tests.costsheet.fixtures.endpoint import HEADERS, client
from zt.indicator import engine as indicator_engine
from zt.reconcile import engine as reconcile_engine
from zt.costsheet.parser import parse_costsheet
from tests.costsheet.fixtures import costsheet_shapes as shapes

# 手算真值（见 shapes.measure_calc_sheets 的 docstring）
A_UNIT, B_UNIT, C_UNIT = "地下室-土石方工程", "地下室-地下室土建工程", "室外-室外道路工程"
A_ITEMS = {"011706002001": 180995.32, "011702001001": 9262.25}           # 之和 190,257.57
B_ITEMS = {"011701003002": 66241.86, "Z011701009001": 33746.41, "01B004": 10260.00}   # 之和 110,248.27
A_SUM, B_SUM = 190257.57, 110248.27
LIST_SUM = 171440.00                                                      # 分部分项 12,500 + 2,940 + 96,000 + 60,000
ALL_SUM = 471945.84                                                       # LIST_SUM + A_SUM + B_SUM
A_CALC = "表10.2.2-17 施工技术措施项目综合单价计算表【土石"
B_CALC = "表10.2.2-17 施工技术措施项目综合单价计算表【地下"
C_CALC = "表10.2.2-17 施工技术措施项目综合单价计算表【室外"


def _parse(raw: bytes, **kw) -> dict:
    return parse_costsheet(raw, "一标段.xlsx", side="submit", file_id="F1", **kw)


def _detail(res: dict, sheet: str) -> dict:
    return next(d for d in res["meta"]["sheets_detail"] if d["sheet"] == sheet)


def _from(res: dict, sheet: str) -> list[dict]:
    return [it for it in res["items"] if it["sheet"] == sheet]


def _codes(res: dict) -> list[str]:
    return [w["code"] for w in res["warning_items"]]


# ---------------------------------------------------------------- 1. 只读清单项行，金额 = 数量 × 小计

def test_only_bill_item_rows_are_read_and_quota_rows_are_not():
    """土石方那张：2 个清单项，下面各挂 3 / 2 行定额子目。读出恰好 2 行，行号是清单项那一行（第 7、12 行），
    定额子目行（「补」「1-93 换」「5-97 换」…）一行都不在。"""
    res = _parse(shapes.measure_calc_sheets())
    rows = _from(res, A_CALC)
    assert [(it["code"], it["row"]) for it in rows] == [("011706002001", 7), ("011702001001", 12)]
    assert {it["code"] for it in rows} == set(A_ITEMS), "定额子目行被当成清单项读进来了"
    for it in rows:
        assert it["amount"] == A_ITEMS[it["code"]]
        assert it["unit_project"] == A_UNIT
        assert it["measure"] is True and it["section"].startswith("技术措施")
        assert it["row_kind"] == "item" and it["file_id"] == "F1"
    d = _detail(res, A_CALC)
    assert (d["status"], d["format"], d["leaf_rows"], d["amount_sum"]) == ("used", "measure_calc", 2, A_SUM)
    assert d["measure_check"]["against"] == "fee_table" and d["measure_check"]["diff"] == 0.0
    assert "measure_sheet_unreconciled" not in _codes(res)


def test_whole_file_totals_include_the_measure_items():
    """分部分项 171,440.00 + 两张措施表 300,505.84 = 471,945.84；解析 9 行（4 + 2 + 3）；计入 5 张表。"""
    res = _parse(shapes.measure_calc_sheets())
    cov = res["meta"]["coverage"]
    assert res["meta"]["parsed_total"] == ALL_SUM and res["meta"]["item_count"] == 9
    assert cov["amount_used"] == ALL_SUM and cov["sheets"] == 5
    assert A_CALC in cov["used_sheets"] and B_CALC in cov["used_sheets"] and C_CALC not in cov["used_sheets"]
    # 读进来的措施表不再出现在「按标题跳过」的名单里
    skipped = next(w["message"] for w in res["warning_items"] if w["code"] == "sheets_skipped_by_title")
    assert "施工技术措施项目综合单价计算表" not in skipped


# ---------------------------------------------------------------- 2. 「合计(元)」列是取整数：不用它做金额

def test_amount_is_qty_times_subtotal_not_the_rounded_total_column():
    """「合计(元)」列写的是 180,995 与 9,262（取整到元），金额必须是「数量 × 小计」到分。"""
    res = _parse(shapes.measure_calc_sheets())
    amounts = {it["code"]: it["amount"] for it in _from(res, A_CALC)}
    assert amounts == {"011706002001": 180995.32, "011702001001": 9262.25}
    assert 180995 not in amounts.values() and 9262 not in amounts.values()
    pad = next(it for it in _from(res, A_CALC) if it["code"] == "011702001001")
    assert (pad["qty"], pad["price"]) == (182.94, 50.63), "单价取的不是「综合单价 / 小计」那一列"


# ---------------------------------------------------------------- 3. 与费用表差 2 元 → 整张不计入

def test_two_yuan_off_the_fee_table_row_is_not_counted():
    res = _parse(shapes.measure_calc_sheets(fee_delta=2.0))
    assert _from(res, A_CALC) == [], "勾稽不过的表不能计入"
    d = _detail(res, A_CALC)
    assert d["status"] == "measure_unreconciled" and d["leaf_rows"] == 0 and d["amount_sum"] == 0
    w = [x for x in res["warning_items"] if x["code"] == "measure_sheet_unreconciled"]
    assert len(w) == 1 and w[0]["level"] == "error" and w[0]["sheet"] == A_CALC
    for num in ("190,257.57", "190,259.57", "2.00"):
        assert num in w[0]["message"], w[0]["message"]
    # 别的单位工程照常计入
    assert {it["code"] for it in _from(res, B_CALC)} == set(B_ITEMS)
    assert res["meta"]["parsed_total"] == round(LIST_SUM + B_SUM, 2)


@pytest.mark.parametrize("delta,counted", [(1.0, True), (-1.0, True), (1.01, False), (-1.01, False)])
def test_fee_table_tolerance_is_one_yuan_inclusive(delta, counted):
    res = _parse(shapes.measure_calc_sheets(fee_delta=delta))
    assert bool(_from(res, A_CALC)) is counted


def test_unreconciled_sheet_makes_the_task_partial():
    """error 级告警 = 有东西没算进去 → 任务 partial（items_not_counted），不是绿色「已完成」。"""
    headers = HEADERS
    bad = shapes.put(shapes.measure_calc_sheets(fee_delta=2.0), "ws26p-off.xlsx", "B")
    r = client.post("/engine/tk/detect", headers=headers, json={"project_id": "P1", "submission_files": [bad]})
    assert r.status_code == 200, r.text[:300]
    assert (r.json()["status"], r.json()["status_reason"]) == ("partial", "items_not_counted")
    good = shapes.put(shapes.measure_calc_sheets(), "ws26p-ok.xlsx", "G")
    r2 = client.post("/engine/tk/detect", headers=headers, json={"project_id": "P1", "submission_files": [good]})
    body = r2.json()
    assert r2.status_code == 200 and body["status"] == "ok", body.get("warning_items")
    assert body["file_coverage"][0]["amount_used"] == ALL_SUM


# ---------------------------------------------------------------- 4. 没有费用表：与本表合计行勾稽

def test_without_fee_table_reconciles_against_the_sheet_total_row():
    """合计行 190,257（逐行取整后相加），清单项之和 190,257.57，差 0.57 ≤ 0.5 × 2 + 0.5 → 计入。"""
    res = _parse(shapes.measure_calc_sheets(with_fee=False))
    assert {it["code"] for it in _from(res, A_CALC)} == set(A_ITEMS)
    chk = _detail(res, A_CALC)["measure_check"]
    assert (chk["against"], chk["reference"], chk["diff"]) == ("sheet_total", 190257.0, 0.57)
    assert res["meta"]["parsed_total"] == ALL_SUM


def test_without_fee_table_beyond_the_sheet_total_tolerance_is_not_counted():
    """合计行改成 190,262：与 190,257.57 差 4.43，超过 1.50 → 不计入，error 告警写出两个数。"""
    res = _parse(shapes.measure_calc_sheets(with_fee=False, total_delta=5.0))
    assert _from(res, A_CALC) == [] and _detail(res, A_CALC)["status"] == "measure_unreconciled"
    msg = next(w["message"] for w in res["warning_items"] if w["code"] == "measure_sheet_unreconciled")
    for num in ("190,257.57", "190,262.00", "4.43", "1.50"):
        assert num in msg, msg


@pytest.mark.parametrize("delta,counted", [(2.07, True), (-0.93, True), (2.08, False), (-0.94, False)])
def test_sheet_total_tolerance_is_half_a_yuan_per_row_plus_half(delta, counted):
    """2 个清单项：容差 0.5 × 2 + 0.5 = 1.50 元（每行「合计(元)」取整最多差 0.5，合计行再取整一次）。
    合计行 190,257 + delta，差 = |delta − 0.57|：2.07 → 1.50（过），2.08 → 1.51（不过）；
    −0.93 → 1.50（过），−0.94 → 1.51（不过）。"""
    res = _parse(shapes.measure_calc_sheets(with_fee=False, total_delta=delta))
    assert bool(_from(res, A_CALC)) is counted


# ---------------------------------------------------------------- 5. 另有措施清单表：不重复计

def test_measure_list_sheet_for_the_same_unit_wins_and_calc_sheet_is_skipped():
    """土石方另有一张被计入的「施工技术措施项目清单与计价表」（名称写成「排水降水」，跨表去重挡不住）：
    计算表照旧跳过、不告警；另一个单位工程的计算表照常读。"""
    res = _parse(shapes.measure_calc_sheets(with_measure_list=True))
    d = _detail(res, A_CALC)
    assert d["status"] == "skipped_by_title" and "措施项目清单与计价表" in d["reason"]
    assert _from(res, A_CALC) == []
    assert {it["code"] for it in _from(res, B_CALC)} == set(B_ITEMS)
    assert "measure_sheet_unreconciled" not in _codes(res)
    # 金额只计一次：分部分项 + 措施清单表（180,995.32 + 9,262.25）+ 土建计算表
    assert res["meta"]["parsed_total"] == ALL_SUM


# ---------------------------------------------------------------- 6. 没有清单序号的措施表

def test_measure_sheet_without_any_bill_item_is_measure_empty_and_silent():
    res = _parse(shapes.measure_calc_sheets())
    d = _detail(res, C_CALC)
    assert (d["status"], d["leaf_rows"]) == ("measure_empty", 0)
    assert _from(res, C_CALC) == []
    assert not [w for w in res["warning_items"] if w.get("sheet") == C_CALC]
    assert C_CALC not in res["meta"]["coverage"]["skipped_sheets"]


# ---------------------------------------------------------------- 7. 分部分项的综合单价分析表照旧跳过

@pytest.mark.parametrize("with_fee", [True, False])
def test_non_measure_unit_price_analysis_sheet_is_still_skipped(with_fee):
    """版式与措施表完全一样（清单序号、综合单价 / 小计），只是标题不带「措施」——分部分项的单价已经在
    清单与计价表里计过一次，再读就是重复计。"""
    res = _parse(shapes.measure_calc_sheets(with_fee=with_fee, with_price_analysis=True))
    sheet = "表10.2.2-15 综合单价计算表【土石方工程】"
    d = _detail(res, sheet)
    assert d["status"] == "skipped_by_title" and d["format"] is None
    assert _from(res, sheet) == []
    assert "cross_sheet_dedup" not in _codes(res) and "measure_sheet_unreconciled" not in _codes(res)
    assert res["meta"]["parsed_total"] == ALL_SUM


# ---------------------------------------------------------------- 8. Z 码、补充码

def test_z_codes_and_supplement_codes_are_read():
    res = _parse(shapes.measure_calc_sheets())
    got = {it["code"]: it for it in _from(res, B_CALC)}
    assert {k: v["amount"] for k, v in got.items()} == B_ITEMS
    # Z 码保留前缀（与同号国标项是两条不同的清单），按国标码归章
    assert got["Z011701009001"]["code_norm"] == "Z011701009001" and got["Z011701009001"]["chapter"] == "0117"
    assert got["01B004"]["code_norm"] == "01B004"
    # 分部标题行带章码（011702 混凝土模板及支架）：补充码按所在分部归章，和分部分项表同一口径
    assert got["01B004"]["chapter"] == "0117" and got["011701003002"]["chapter"] == "0117"
    assert got["01B004"]["section"] == "技术措施 011702 混凝土模板及支架（撑）"
    assert [it["row"] for it in got.values()] == [7, 9, 12]


# ---------------------------------------------------------------- 9. 对账：措施项逐行参与配对

def test_reconcile_pairs_measure_items_and_reports_the_adjustment():
    """审定侧把垫层模板的数量 182.94 改成 180（措施表合计行与费用表同步改）：
    送审 9,262.25、审定 180 × 50.63 = 9,113.40 → 一行「调整」，核减额 148.85；其余措施项「一致」。"""
    sub = shapes.measure_calc_sheets()
    aud = shapes.measure_calc_sheets(audit_qty=180)
    res = reconcile_engine.run(sub, "送审.xlsx", aud, "审定.xlsx")
    changed = [r for r in res["rows"] if r["status"] == "调整"]
    assert [(r["item_code"], r["submitted_amount"], r["approved_amount"], r["diff"]) for r in changed] == \
        [("011702001001", 9262.25, 9113.40, 148.85)]
    assert changed[0]["submitted_sheet"] == A_CALC and changed[0]["submitted_row"] == 12
    assert res["total_diff"] == 148.85
    sm = res["summary"]
    assert (sm["a_total"], sm["b_total"]) == (ALL_SUM, round(ALL_SUM - 148.85, 2))
    measure_rows = [r for r in res["rows"] if (r["submitted_sheet"] or "").startswith("表10.2.2-17")]
    assert len(measure_rows) == 5 and sum(r["status"] == "一致" for r in measure_rows) == 4


# ---------------------------------------------------------------- 指标：回落口径的标签按实际计入的内容写

def test_indicator_itemized_label_follows_what_was_counted():
    full = indicator_engine.run([(shapes.measure_calc_sheets(with_fee=False), "一标段.xlsx", "F1")], {})
    sm = full["summary"]
    assert sm["cost_basis"] == "itemized" and sm["total_amount"] == ALL_SUM
    assert sm["cost_basis_label"] == "分部分项+措施清单合计口径"
    # 措施项目的章出现在章节占比里
    assert "0117" in {c["chapter"] for c in full["chapters"]}
    part = indicator_engine.run([(shapes.measure_calc_sheets(with_fee=False, total_delta=5.0),
                                  "一标段.xlsx", "F1")], {})
    sp = part["summary"]
    assert sp["total_amount"] == round(LIST_SUM + B_SUM, 2)
    assert sp["cost_basis_label"] == "分部分项+措施清单合计口径(技术措施 1 张表未计入)"


def test_indicator_label_when_every_measure_sheet_fails_reconciliation():
    """一张都没计入：不能说「+措施」。"""
    import io
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(shapes.measure_calc_sheets(with_fee=False, total_delta=5.0)))
    del wb[B_CALC]
    buf = io.BytesIO()
    wb.save(buf)
    res = indicator_engine.run([(buf.getvalue(), "一标段.xlsx", "F1")], {})
    assert res["summary"]["cost_basis_label"] == "分部分项清单合计口径(未含措施项目、规费、税金)"


# ---------------------------------------------------------------- 口径：明确要本期 / 累计时不读

def test_explicit_period_basis_keeps_the_old_skip():
    """表里只有不分期的数量与单价：调用方明确要「本期」时这张表没有那个口径，照旧跳过，不拿不分期的数冒充。"""
    res = _parse(shapes.measure_calc_sheets(), basis="current")
    assert _detail(res, A_CALC)["status"] == "skipped_by_title"
    assert _from(res, A_CALC) == []
