# 来源：engine-service/tests/test_tk_align_unit_project.py（zhitong-cost-ai@991ff5cd）
"""WS26-m（issue #828，P21 / 缺陷 07-013；铁律 3）：合同比对的对齐 —— 同一个键在合同清单里有多行时，
先用单位工程收窄；收窄后仍不唯一就判 AMBIGUOUS、不出金额，不再取第一条。

修的现场（生产实测 TK-H02：送审原件对内容相同的合同清单 A，两份 sha256 相同）：
  · 出 13 条置信「高」的「工程量疑似超合同」，疑似超出额合计 35,505.38 元 —— 一份清单自己比自己；
  · 9 条「屋面泛水压条」（每栋楼各列一次的补充清单项，编码各不相同）全部对到 6#楼土建第 119 行；
  · 12 位编码 030702001003 在「地下室暖通」「S3#楼装修安装」各一行，后一行被对到前一行；
  · 8855 行里 205 行「严格对齐」到的不是同表同行，统计却写 exact 8855、coverage 1。
根因：tk_align 的三个索引键都不含单位工程，同键多行时取 hits[0] / 同码候选里第一条名称单位相同的。

夹具每条都走到会出错的那条分支（CLAUDE.md §5.2）：
  · 同名补充项放在三张表里、后两张的工程量比第一张大 15% 以上、行金额 ≥ 1000 —— 取第一条必报 2 条；
  · 反方向（第一张的合同量最大）钉漏报：取第一条时后两栋楼真超了也报不出来；
  · AMBIGUOUS 的夹具同时过 new_item 的金额线与覆盖率线 —— 算成新增会显形。
变异验收见 PR。
"""
from __future__ import annotations

import io

from openpyxl import Workbook

from tests.costsheet.fixtures.endpoint import HEADERS, client
from zt.tk import align as tk_align
from zt.tk import engine as tk_engine
from zt.costsheet.parser import parse_costsheet
from tests.costsheet.fixtures import costsheet_shapes as shapes


HEAD = ["序号", "项目编码", "项目名称", "项目特征描述", "计量单位", "工程量", "综合单价", "合价"]
CONTRACT_RULES = {"price_over_baseline", "qty_over_baseline", "missing_submit", "new_item"}
AMOUNT_KEYS = {"base_price", "base_qty", "base_amount", "excess_amount", "baseline_value"}
CFG = tk_engine.load_rules()

SUBMIT_NAME, SUBMIT_ID = "送审.xlsx", "S1"
CONTRACT_NAME, CONTRACT_ID = "合同清单.xlsx", "B1"


def _book(sheets: dict[str, list[list]], unit_projects: dict[str, str] | None = None) -> bytes:
    """{表名: [数据行…]} → xlsx 字节。数据行不含序号；第 1 行是表头，数据从第 2 行起。

    unit_projects = {表名: 单位工程名}：在表头上方加一行「单位工程名称：xx」（GB50500 表-08 的抬头），
    这时表头在第 2 行、数据从第 3 行起。"""
    wb = Workbook()
    for n, (title, rows) in enumerate(sheets.items()):
        ws = wb.active if n == 0 else wb.create_sheet()
        ws.title = title
        if unit_projects and title in unit_projects:
            ws.append([f"单位工程名称：{unit_projects[title]}"])
        ws.append(HEAD)
        for i, r in enumerate(rows, 1):
            ws.append([i] + list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _run(submit: dict, contract: dict) -> dict:
    return tk_engine.run([(_book(submit), SUBMIT_NAME, SUBMIT_ID)], None, project_id="P",
                         baseline_files=[(_book(contract), CONTRACT_NAME, CONTRACT_ID)])


def _rows_and_bases(submit: dict, contract: dict) -> tuple[list[dict], list[dict]]:
    rows = tk_engine.costsheet_items_to_rows(
        parse_costsheet(_book(submit), SUBMIT_NAME, side="submit", file_id=SUBMIT_ID)["items"], "P", SUBMIT_NAME)
    bases = tk_engine.baseline_rows_from_items(
        parse_costsheet(_book(contract), CONTRACT_NAME, basis="contract", file_id=CONTRACT_ID)["items"],
        "P", CONTRACT_NAME, CONTRACT_ID)
    return rows, bases


def _contract_hits(res: dict) -> list[tuple]:
    return sorted((a["subtype"], a["sheet"], a["row"]) for a in res["anomalies"] if a["subtype"] in CONTRACT_RULES)


def _no_amounts(obj) -> bool:
    if isinstance(obj, dict):
        return not (AMOUNT_KEYS & set(obj)) and all(_no_amounts(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_no_amounts(v) for v in obj)
    return True


def _mem_row(code, name, feature, unit, qty, price, amount, *, sheet, row, unit_project=None) -> dict:
    r = {"project_id": "P", "file_id": SUBMIT_ID, "source_file": SUBMIT_NAME, "sheet": sheet, "row": row,
         "item_code": code, "item_name": name, "item_feature": feature, "unit": unit,
         "submit_qty": qty, "submit_price": price, "submit_amount": amount}
    if unit_project is not None:
        r["unit_project"] = unit_project
    return r


def _mem_base(code, name, feature, unit, qty, price, *, sheet, row, unit_project=None) -> dict:
    b = {"project_id": "P", "item_code": code, "item_name": name, "item_feature": feature, "unit": unit,
         "base_qty": qty, "base_price": price, "base_amount": round(qty * price, 2),
         "source": CONTRACT_NAME, "file_id": CONTRACT_ID, "sheet": sheet, "row": row}
    if unit_project is not None:
        b["unit_project"] = unit_project
    return b


# ---------------------------------------------------------------- 1. 自比：三栋楼各有同名补充项（07-013）

# 每栋楼一张表：一条国标码行（编码各不相同）+ 一条「屋面泛水压条」补充项（编码各不相同，
# 名称、特征、单位相同）。7#、21# 的工程量比 6# 大 15% 以上，行金额都 ≥ 1000 元。
PRESS = ("屋面泛水压条", "铝合金压条 30×3，射钉固定", "m")
THREE_BUILDINGS = {
    "6#楼土建": [["010401003001", "实心砖墙", "MU10", "m3", 100, 480, 48000],
                ["01B016", *PRESS, 176.76, 19.55, 3455.66]],
    "7#楼土建": [["010401003002", "实心砖墙", "MU10", "m3", 120, 480, 57600],
                ["01B048", *PRESS, 394.62, 19.55, 7714.82]],
    "21#楼土建": [["010401003003", "实心砖墙", "MU10", "m3", 90, 480, 43200],
                 ["01B221", *PRESS, 299.16, 19.55, 5848.58]],
}


def test_self_compare_three_buildings_with_same_supplement_item_reports_nothing():
    """送审 = 合同。旧代码把 7#、21# 的压条对到 6# 那一行，报 2 条置信「高」的工程量疑似超合同。"""
    res = _run(THREE_BUILDINGS, THREE_BUILDINGS)
    assert _contract_hits(res) == []
    stats = res["baseline"]["stats"]
    assert stats["aligned"]["exact"] == 6 and stats["coverage"] == 1
    assert res["alignment_issues"] == [] and res["align_suggestions"] == []


def test_self_compare_aligns_every_row_to_same_sheet_same_row():
    """exact 的计数说明不了「对到了哪一行」—— 旧代码也写 exact 6。逐行看基准行的表名与行号。"""
    rows, bases = _rows_and_bases(THREE_BUILDINGS, THREE_BUILDINGS)
    index = tk_align.build_index(bases)
    assert len(rows) == 6, "夹具自检：三张表各 2 行"
    for r in rows:
        al = tk_align.align_row(r, index)
        assert al.method == tk_align.EXACT, r
        assert (al.base["sheet"], al.base["row"]) == (r["sheet"], r["row"]), (r["sheet"], r["row"], al.base)


def test_overrun_is_judged_against_own_building_not_the_first_one():
    """漏报方向：6# 的合同量最大（500），7# 合同量 100、送审 200（超 100%）。
    取第一条时 7# 的 200 拿去和 6# 的 500 比，报不出来；21# 没动，不该报。"""
    contract = {
        "6#楼土建": [["01B016", *PRESS, 500, 20, 10000]],
        "7#楼土建": [["01B048", *PRESS, 100, 20, 2000]],
        "21#楼土建": [["01B221", *PRESS, 300, 20, 6000]],
    }
    submit = {**contract, "7#楼土建": [["01B048", *PRESS, 200, 20, 4000]]}
    res = _run(submit, contract)
    assert _contract_hits(res) == [("qty_over_baseline", "7#楼土建", 2)]
    a = next(x for x in res["anomalies"] if x["subtype"] == "qty_over_baseline")
    assert a["baseline_value"] == 100 and a["reported_value"] == 200
    assert a["excess_amount"] == 2000 and a["deviation_pct"] == 100.0
    assert a["baseline_ref"]["sheet"] == "7#楼土建" and a["baseline_ref"]["item_code"] == "01B048"


# ---------------------------------------------------------------- 2. 国标码在两个单位工程各一行

GB_TWICE = {
    "地下室暖通": [["030702001003", "碳钢通风管道", "镀锌钢板 δ=0.75", "m2", 10.0, 113.32, 1133.2]],
    "S3#楼装修安装": [["030702001003", "碳钢通风管道", "镀锌钢板 δ=1.0", "m2", 14.72, 113.32, 1668.07]],
}


def test_same_gb_code_in_two_unit_projects_self_compare_reports_nothing():
    """12 位编码在两个单位工程各出现一次（特征不同、量不同）。旧代码把后一行对到前一行：
    14.72 > 10.0 × 1.15，行金额 1668.07 ≥ 1000，报 1 条工程量疑似超合同。"""
    res = _run(GB_TWICE, GB_TWICE)
    assert _contract_hits(res) == []
    rows, bases = _rows_and_bases(GB_TWICE, GB_TWICE)
    index = tk_align.build_index(bases)
    assert [(tk_align.align_row(r, index).base or {}).get("sheet") for r in rows] == ["地下室暖通", "S3#楼装修安装"]


# ---------------------------------------------------------------- 3. 单位工程写法不同 → AMBIGUOUS

# 合同：实心砖墙这个国标码在两栋楼各一行。送审把表名写成「6#楼」（合同里是「6#楼土建」），收窄不到。
# 另外两行（矩形柱、矩形梁）在合同里各只有一行 —— 覆盖率 2/3 过线，new_item 这条规则真的跑了；
# 那一行送审金额 96,000 ≥ 5000，被算成合同外新增会显形。
AMBIG_CONTRACT = {
    "6#楼土建": [["010401003001", "实心砖墙", "MU10", "m3", 100, 480, 48000],
                ["010502001001", "矩形柱", "C30", "m3", 50, 600, 30000]],
    "7#楼土建": [["010401003001", "实心砖墙", "MU10", "m3", 120, 480, 57600],
                ["010503001001", "矩形梁", "C30", "m3", 40, 620, 24800]],
}
AMBIG_SUBMIT = {
    "6#楼": [["010401003001", "实心砖墙", "MU10", "m3", 200, 480, 96000],
            ["010502001001", "矩形柱", "C30", "m3", 50, 600, 30000],
            ["010503001001", "矩形梁", "C30", "m3", 40, 620, 24800]],
}


def test_unit_project_spelled_differently_is_ambiguous_not_first_row():
    res = _run(AMBIG_SUBMIT, AMBIG_CONTRACT)
    assert res["rules_run"].get("new_item") == "all", "夹具自检：覆盖率过线，new_item 真的跑了"
    assert res["rules_run"].get("qty_over_baseline") == "exact_rows"
    # 不出金额：这一行的量 200 比两条候选的 100 / 120 都超过 15%，取任何一条都会报
    assert _contract_hits(res) == []
    # 进「待人工指定」，两条候选全部列出，不带任何金额
    assert len(res["alignment_issues"]) == 1
    issue = res["alignment_issues"][0]
    assert issue["method"] == tk_align.AMBIGUOUS
    assert (issue["sheet"], issue["row"], issue["item_code"]) == ("6#楼", 2, "010401003001")
    assert [(c["sheet"], c["row"]) for c in issue["baseline"]] == [("6#楼土建", 2), ("7#楼土建", 2)]
    assert "合同清单里有 2 行" in issue["reason"] and "无法确定对哪一行" in issue["reason"]
    assert "6#楼" in issue["reason"]
    assert _no_amounts(res["alignment_issues"])
    # 不在严格对齐的行级证据里（WS26-c：没被重新判过的旧待复核不删）
    assert res["baseline"]["exact_rows"] == {SUBMIT_ID: {"6#楼": [3, 4]}}
    # 不是「对齐建议」
    assert res["align_suggestions"] == []


def test_ambiguous_row_alignment_has_no_base():
    rows, bases = _rows_and_bases(AMBIG_SUBMIT, AMBIG_CONTRACT)
    al = tk_align.align_row(rows[0], tk_align.build_index(bases))
    assert al.method == tk_align.AMBIGUOUS and al.base is None and len(al.candidates) == 2


def test_ambiguous_rows_are_reported_in_the_conflicts_warning_with_both_counts():
    """告警不新增码：并入 baseline_conflicts，文案分开数「同码不同名」与「多行可对」。"""
    submit = {"6#楼": AMBIG_SUBMIT["6#楼"] + [["010502001001", "矩形柱-改名", "C30", "m3", 5, 600, 3000]]}
    res = _run(submit, AMBIG_CONTRACT)
    msgs = [w["message"] for w in res["warning_items"] if w["code"] == "baseline_conflicts"]
    assert msgs == ["2 行需要人工指定合同行（其中 1 行同编码不同名称或单位，1 行在合同清单里有多行可对），未出金额"]
    assert sorted(i["method"] for i in res["alignment_issues"]) == [tk_align.AMBIGUOUS, tk_align.CONFLICT]


# ---------------------------------------------------------------- 4. 唯一命中不看单位工程

def test_single_baseline_row_is_exact_even_when_unit_project_names_differ():
    """进度款报审表与合同清单的表名、单位工程叫法常常完全不同。合同里这个键只有一行时照常严格对齐，
    否则整份都对不上、覆盖率掉到 0（这就是不把单位工程放进对齐键的原因）。"""
    contract = {"中标清单": [["010501001001", "现浇混凝土基础", "C30", "m3", 100, 400, 40000],
                            ["01B047", "砌体加固筋", "Φ8", "t", 1.5, 3000, 4500]]}
    submit = {"第3期进度款-土建": [["010501001001", "现浇混凝土基础", "C30", "m3", 100, 500, 50000],
                                 ["01B047", "砌体加固筋", "Φ8", "t", 1.5, 3000, 4500]]}
    res = _run(submit, contract)
    assert _contract_hits(res) == [("price_over_baseline", "第3期进度款-土建", 2)]
    a = next(x for x in res["anomalies"] if x["subtype"] == "price_over_baseline")
    assert a["excess_amount"] == 10000 and a["baseline_ref"]["sheet"] == "中标清单"
    assert res["baseline"]["stats"]["aligned"] == {"exact": 2, "conflict": 0, "suggest": 0, "new_item": 0,
                                                   "ambiguous": 0}


# ---------------------------------------------------------------- 5. 补充码：同单位工程里仍多行

def test_supplement_rows_in_same_unit_project_are_told_apart_by_code_text():
    """同一栋楼里两行补充项，名称、特征、单位全相同，编码原文不同（01B016 / 01B017，量不同）。
    自比：各对各的，0 条。取第一条时第二行（300）会拿去和第一行（100）比。"""
    sheet = {"6#楼土建": [["01B016", *PRESS, 100, 20, 2000], ["01B017", *PRESS, 300, 20, 6000]]}
    res = _run(sheet, sheet)
    assert _contract_hits(res) == [] and res["alignment_issues"] == []
    rows, bases = _rows_and_bases(sheet, sheet)
    index = tk_align.build_index(bases)
    assert [tk_align.align_row(r, index).base["row"] for r in rows] == [2, 3]


def test_supplement_code_text_is_compared_inside_the_same_unit_project_first():
    """补充码是每栋楼各编各的流水号，两栋楼会撞号：6# 有 01B016、01B017 两行同名压条，7# 也有一行 01B016。
    先收窄到同单位工程（6# 的两行），再在这两行里看编码原文 —— 不是在三行里找 01B016（那样有两行）。"""
    book = {"6#楼土建": [["01B016", *PRESS, 100, 20, 2000], ["01B017", *PRESS, 300, 20, 6000]],
            "7#楼土建": [["01B016", *PRESS, 500, 20, 10000]]}
    res = _run(book, book)
    assert _contract_hits(res) == [] and res["alignment_issues"] == []
    rows, bases = _rows_and_bases(book, book)
    index = tk_align.build_index(bases)
    assert [(tk_align.align_row(r, index).base["sheet"], tk_align.align_row(r, index).base["row"]) for r in rows] == [
        ("6#楼土建", 2), ("6#楼土建", 3), ("7#楼土建", 2)]


def test_supplement_rows_with_same_code_text_in_same_unit_project_are_ambiguous():
    """编码原文也相同：分不清，两行都进待人工指定，不出金额。"""
    sheet = {"6#楼土建": [["01B016", *PRESS, 100, 20, 2000], ["01B016", *PRESS, 300, 20, 6000]]}
    res = _run(sheet, sheet)
    assert _contract_hits(res) == []
    assert [(i["row"], i["method"]) for i in res["alignment_issues"]] == [(2, "ambiguous"), (3, "ambiguous")]
    assert all(len(i["baseline"]) == 2 for i in res["alignment_issues"])
    assert res["baseline"]["exact_rows"] == {}
    assert _no_amounts(res["alignment_issues"])


def test_supplement_code_text_narrows_when_no_unit_project_matches():
    """送审表名写法与合同不同（收窄不到同单位工程），但补充码原文只对得上一行 → 对到那一行。
    没有编码的同名行则无从分辨 → AMBIGUOUS。"""
    contract = {"6#楼土建": [["01B016", *PRESS, 100, 20, 2000], ["", "成品保护", "按实", "项", 1, 800, 800]],
                "7#楼土建": [["01B048", *PRESS, 300, 20, 6000], ["", "成品保护", "按实", "项", 1, 900, 900]]}
    rows = [_mem_row("01B048", *PRESS, 300, 20, 6000, sheet="7#楼", row=2),
            _mem_row("", "成品保护", "按实", "项", 1, 5000, 5000, sheet="7#楼", row=3)]
    _unused, bases = _rows_and_bases(contract, contract)
    index = tk_align.build_index(bases)
    al = tk_align.align_row(rows[0], index)
    assert al.method == tk_align.EXACT and (al.base["sheet"], al.base["item_code"]) == ("7#楼土建", "01B048")
    al2 = tk_align.align_row(rows[1], index)
    assert al2.method == tk_align.AMBIGUOUS and al2.base is None and len(al2.candidates) == 2


def test_gb_code_twice_in_same_unit_project_is_ambiguous():
    """国标码在同一单位工程里重复两行（名称、单位相同）：编码本来就在键里，没有别的可收窄 → AMBIGUOUS。"""
    bases = [_mem_base("010401003001", "实心砖墙", "MU10", "m3", 100, 480, sheet="6#楼土建", row=2),
             _mem_base("010401003001", "实心砖墙", "MU15", "m3", 300, 480, sheet="6#楼土建", row=9)]
    row = _mem_row("010401003001", "实心砖墙", "MU15", "m3", 300, 480, 144000, sheet="6#楼土建", row=9)
    al = tk_align.align_row(row, tk_align.build_index(bases))
    assert al.method == tk_align.AMBIGUOUS and al.base is None
    assert "其中 2 行" in al.reason and "6#楼土建" in al.reason


def test_unit_project_field_wins_over_sheet_name_and_is_normalised():
    """收窄用的是单位工程（表头上方「单位工程名称」，缺省才是表名）；全角括号、空白不影响比较。"""
    bases = [_mem_base("01B016", *PRESS, 100, 20, sheet="表-08(1)", row=5, unit_project="6#楼【建筑】"),
             _mem_base("01B048", *PRESS, 300, 20, sheet="表-08(2)", row=5, unit_project="7#楼【建筑】")]
    row = _mem_row("01B999", *PRESS, 300, 20, 6000, sheet="进度款", row=8, unit_project="7#楼 [建筑]")
    al = tk_align.align_row(row, tk_align.build_index(bases))
    assert al.method == tk_align.EXACT and al.base["sheet"] == "表-08(2)"


def test_unit_project_from_header_line_narrows_when_sheet_names_say_nothing():
    """导出件的表名常是「表-08(1)」「表-08(2)」，楼栋写在表头上方的「单位工程名称」里；送审文件的表名、
    表的先后顺序还和合同不一样。同一个国标码两栋楼各一行：只有基准行带着单位工程才对得上各自那一行。
    6#楼 送审量 100 = 合同量；7#楼 送审量 300 = 合同量。对反了的话 7# 的 300 对 6# 的 100 会报超合同。"""
    wall = ["010401003001", "实心砖墙", "MU10", "m3"]
    contract = _book({"表-08(1)": [wall + [100, 480, 48000]], "表-08(2)": [wall + [300, 480, 144000]]},
                     {"表-08(1)": "6#楼【建筑】", "表-08(2)": "7#楼【建筑】"})
    submit = _book({"Sheet1": [wall + [300, 480, 144000]], "Sheet2": [wall + [100, 480, 48000]]},
                   {"Sheet1": "7#楼【建筑】", "Sheet2": "6#楼【建筑】"})
    res = tk_engine.run([(submit, SUBMIT_NAME, SUBMIT_ID)], None, project_id="P",
                        baseline_files=[(contract, CONTRACT_NAME, CONTRACT_ID)])
    assert _contract_hits(res) == [] and res["alignment_issues"] == []
    assert res["baseline"]["stats"]["aligned"]["exact"] == 2
    assert res["baseline"]["exact_rows"] == {SUBMIT_ID: {"Sheet1": [3], "Sheet2": [3]}}
    rows = tk_engine.costsheet_items_to_rows(
        parse_costsheet(submit, SUBMIT_NAME, side="submit", file_id=SUBMIT_ID)["items"], "P", SUBMIT_NAME)
    bases = tk_engine.baseline_rows_from_items(
        parse_costsheet(contract, CONTRACT_NAME, basis="contract", file_id=CONTRACT_ID)["items"],
        "P", CONTRACT_NAME, CONTRACT_ID)
    assert [r["unit_project"] for r in rows] == ["7#楼【建筑】", "6#楼【建筑】"], "夹具自检：单位工程取自表头上方"
    index = tk_align.build_index(bases)
    assert [tk_align.align_row(r, index).base["sheet"] for r in rows] == ["表-08(2)", "表-08(1)"]


def test_row_without_unit_project_does_not_match_a_baseline_row_without_one():
    """空对空不算「同单位工程」：送审行没有单位工程信息（老调用方直接喂内存行），基准两行里
    一行有、一行没有 —— 不能因为两边都是空就认定是同一个单位工程。"""
    bases = [{k: v for k, v in _mem_base("010401003001", "实心砖墙", "MU10", "m3", 100, 480, sheet="", row=2).items()
              if k != "sheet"},
             _mem_base("010401003001", "实心砖墙", "MU10", "m3", 300, 480, sheet="7#楼土建", row=2)]
    row = {k: v for k, v in _mem_row("010401003001", "实心砖墙", "MU10", "m3", 300, 480, 144000, sheet="", row=2).items()
           if k != "sheet"}
    al = tk_align.align_row(row, tk_align.build_index(bases))
    assert al.method == tk_align.AMBIGUOUS and al.base is None
    assert "送审行没有单位工程信息" in al.reason


def test_baseline_rows_carry_unit_project():
    """基准行要带上单位工程，否则收窄无从谈起（旧版 baseline_rows_from_items 没搬这一项）。"""
    _rows, bases = _rows_and_bases(THREE_BUILDINGS, THREE_BUILDINGS)
    assert [b["unit_project"] for b in bases] == ["6#楼土建"] * 2 + ["7#楼土建"] * 2 + ["21#楼土建"] * 2


# ---------------------------------------------------------------- 6. 埋入差异回归（TK-H00 真值表 R1–R7）

# 一张桩基工程表（编码在整份工作簿里只出现一次）+ 三栋楼的表（同名补充项每栋各列一次）。
# 送审在桩基工程表上埋 7 处，楼栋表原样不动。量、价、合价照真值表。
PILE_CONTRACT = [
    ["010202007001", "钻孔. 注浆", "锚杆", "m", 8319, 54.99, 457461.81],                       # R1
    ["010904002001", "锚杆头涂膜防水", "", "m2", 366.97, 56.96, 20902.61],
    ["010904001001", "锚杆头卷材防水", "", "m2", 366.97, 28.71, 10535.71],                     # R7
    ["010302003004", "Φ700mm干作业旋挖桩机成孔(土层)", "", "m", 233.99, 583.09, 136437.23],     # R2
    ["010302003005", "Φ700mm干作业旋挖桩机成孔(强风化岩)", "", "m", 58.5, 1071.95, 62709.08],   # R6
    ["010515004001", "钢筋笼", "", "t", 14.24, 4379.94, 62370.35],                              # R3
    ["010301004002", "凿Φ700混凝土桩头", "", "根", 64, 169.765, 10864.96],                      # R4
]
PILE_SUBMIT = [
    ["010202007001", "钻孔. 注浆", "锚杆", "m", 8319, 65.99, 548970.81],                       # R1 单价 ×1.2
    ["010904002001", "锚杆头涂膜防水", "", "m2", 366.97, 56.96, 20902.61],
    ["010904001901", "锚杆头卷材防水", "", "m2", 366.97, 28.71, 10535.71],                     # R7 只改编码
    ["010302003004", "Φ700mm干作业旋挖桩机成孔(土层)", "", "m", 304.19, 583.09, 177370.15],     # R2 工程量 ×1.3
    ["010302003005", "Φ700mm干作业旋挖桩机成孔(强风化岩)", "", "m", 58.5, 1071.95, 68979.99],   # R6 只改合价
    ["010515004001", "钢筋笼", "", "t", None, None, None],                                      # R3 量价金额清空
    ["010301004002", "凿Φ700混凝土桩头（改名测试）", "", "根", 64, 169.765, 10864.96],          # R4 改名
    ["010101001901", "测试新增项", "", "m3", 100, 100, 10000],                                  # R5 新增
]
PILE = "桩基工程"


def test_planted_differences_r1_to_r7_all_hit_with_same_amounts_and_nothing_else():
    res = _run({PILE: PILE_SUBMIT, **THREE_BUILDINGS}, {PILE: PILE_CONTRACT, **THREE_BUILDINGS})
    # 合同类正好四条：R1、R2、R3、R5；楼栋表没动，一条都不该有
    assert _contract_hits(res) == [("missing_submit", PILE, 7), ("new_item", PILE, 9),
                                   ("price_over_baseline", PILE, 2), ("qty_over_baseline", PILE, 5)]
    by_rule = {a["subtype"]: a for a in res["anomalies"] if a["sheet"] == PILE}
    r1, r2, r3 = by_rule["price_over_baseline"], by_rule["qty_over_baseline"], by_rule["missing_submit"]
    assert (r1["excess_amount"], r1["line_amount"], r1["deviation_pct"]) == (91509.0, 548970.81, 20.0)
    assert (r2["excess_amount"], r2["line_amount"], r2["deviation_pct"]) == (40932.92, 177370.15, 30.0)
    assert r3["baseline_value"] == 62370.35 and r3["line_amount"] is None
    assert by_rule["new_item"]["line_amount"] == 10000
    # R6：自洽，不出超合同
    assert by_rule["self_check"]["row"] == 6 and by_rule["self_check"]["deviation_pct"] == 9.09
    # R4 仍是 CONFLICT，R7 仍是 SUGGEST；两行都不出异常
    assert [(i["row"], i["method"], i["reason"]) for i in res["alignment_issues"]] == [
        (8, "conflict", "编码相同但名称不同")]
    assert [(s["row"], s["candidates"][0]["item_code"]) for s in res["align_suggestions"]] == [(4, "010904001001")]
    assert {(a["sheet"], a["row"]) for a in res["anomalies"]}.isdisjoint({(PILE, 8), (PILE, 4)})
    assert res["baseline"]["stats"]["aligned"] == {"exact": 11, "conflict": 1, "suggest": 1, "new_item": 1,
                                                   "ambiguous": 0}


# ---------------------------------------------------------------- 7. 统计

def test_aligned_counts_have_five_buckets_that_sum_to_submitted_rows():
    """exact 只数真正唯一对上的；AMBIGUOUS 单独一档；五档之和 = 送审行数；覆盖率的算法不变。"""
    submit = {"6#楼": AMBIG_SUBMIT["6#楼"] + [["010502001001", "矩形柱-改名", "C30", "m3", 5, 600, 3000],
                                              ["010999999001", "签证增补", "", "项", 1, 10000, 10000],
                                              ["010503001009", "矩形梁", "C30", "m3", 1, 620, 620]]}
    res = _run(submit, AMBIG_CONTRACT)
    stats = res["baseline"]["stats"]
    assert stats["aligned"] == {"exact": 2, "conflict": 1, "suggest": 1, "new_item": 1, "ambiguous": 1}
    assert sum(stats["aligned"].values()) == res["rows_total"] == 6
    assert stats["coded_rows"] == 6 and stats["exact_coded"] == 2 and stats["coverage"] == round(2 / 6, 4)


def test_align_stats_has_the_ambiguous_bucket():
    """align_stats 的每项目计数表也是五档（少了这一档，遇到 AMBIGUOUS 行会 KeyError）。"""
    rows, bases = _rows_and_bases(AMBIG_SUBMIT, AMBIG_CONTRACT)
    per = tk_align.align_stats(rows, tk_align.build_index(bases))
    assert per == {"P": {"exact": 2, "conflict": 0, "suggest": 0, "new_item": 0, "ambiguous": 1, "total": 3}}


def test_endpoint_exposes_ambiguous_count_and_issue():
    sub = shapes.put(_book(AMBIG_SUBMIT), "ws26m-送审.xlsx", "S-M")
    base = shapes.put(_book(AMBIG_CONTRACT), "ws26m-合同.xlsx", "B-M")
    r = client.post("/engine/tk/detect", headers=HEADERS,
                    json={"submission_files": [sub], "baseline_files": [base], "project_id": "P"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["baseline"]["stats"]["aligned"]["ambiguous"] == 1
    assert body["baseline"]["stats"]["aligned"]["exact"] == 2
    assert [i["method"] for i in body["alignment_issues"]] == ["ambiguous"]
    assert body["baseline"]["exact_rows"] == {"S-M": {"6#楼": [3, 4]}}


# ---------------------------------------------------------------- 8. 覆盖率低的百分数（07-014 第 3 项）

def _coverage_message(n_aligned: int, n_total: int) -> str:
    rows = [_mem_row(f"0105{i:08d}", f"清单项{i}", "", "m3", 1, 100, 100, sheet="分部分项", row=i + 2)
            for i in range(n_total)]
    bases = [_mem_base(f"0105{i:08d}", f"清单项{i}", "", "m3", 1, 100, sheet="清单", row=i + 2)
             for i in range(n_aligned)]
    # 一行谁也对不上的基准行：n_aligned = 0 时基准也不是空的（空基准走的是「没给合同清单」那条路）
    bases.append(_mem_base("019900000001", "无关项", "", "项", 1, 1, sheet="清单", row=1))
    out = tk_engine.detect_full(rows, CFG, bases)
    msgs = [w["message"] for w in out["warning_items"] if w["code"] == "baseline_coverage_low"]
    assert len(msgs) == 1, msgs
    return msgs[0]


def test_low_coverage_message_keeps_two_decimals_below_one_percent():
    """生产 TK-H04：合同清单只对上 14 / 8626 行，黄条写「（0%，门槛 50%）」，实际是 0.16%。"""
    msg = _coverage_message(14, 8626)
    assert "带标准编码的 8626 行" in msg and "只有 14 行" in msg
    assert "（0.16%，门槛 50%）" in msg, msg


def test_low_coverage_message_keeps_whole_percent_at_or_above_one_percent():
    assert "（20%，门槛 50%）" in _coverage_message(1, 5)
    assert "（1%，门槛 50%）" in _coverage_message(1, 100)
    assert "（0%，门槛 50%）" in _coverage_message(0, 5), "一行都没对上才写 0%"


def test_low_coverage_message_never_prints_zero_when_some_rows_aligned():
    """1 / 20001 ≈ 0.005%：两位小数也会抹成 0.00%，写「不到 0.01%」。"""
    msg = _coverage_message(1, 20001)
    assert "（不到 0.01%，门槛 50%）" in msg, msg
