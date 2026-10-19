# 来源：engine-service/tests/test_fee_rules_evaluator.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""费率建议求值器的验收测试（I-2.5 代码部分，契约 §1.4）。

与 `test_fee_rules_data.py` 的分工，别混：
  · 那个文件校验**数据**（转录得对不对、结构自洽不自洽），用的是纯数据复算；
  · 本文件校验**求值器**（`app/engine/fee_rules.py`）的行为。

效力边界（照 test_fee_rules_data.py 的先例写清楚，免得后人误读）：
  · `test_golden_example_reproduced_by_evaluator` 是本文件里**唯一**能证伪「数字抄错了」
    的测试 —— 22.55 万元印在原表注2上，不是我们算的。改任一档位上界或费率，它就红。
  · `test_quick_deduction_equals_tiered_accumulation` **证明不了数据对错**：两种算法从
    同一组 (uppers, rates) 推导，代数上恒等，抄错了两边照样相等。它守的是求值器实现
    不走形（spec 要求用速算扣除数法出数）。
  · 下面那张 `EXPECTED` 手算表守的是**求值器**：每个数都是我按原表规则手算复核过的，
    但它跟数据同源，所以同样不能证明转录正确。转录正确性只有 golden_example 和
    造价员签字两条路。

变异测试记录（真跑过，不是"跑绿就完事"；三处均确认「改→红、改回→绿」）：
  1. 改**费率**：`bidding_agency_fee` works 列第 1 档 1.0% → 1.1%
     → `test_golden_example_reproduced_by_evaluator` 红
       `AssertionError: 复算原表算例不符：期望 22.55 实得 22.65`
     （连带 `test_expected_amounts_hand_checked` 与数据侧
       `test_fee_rules_data.py::test_golden_examples_reproduce` 也红）
  2. 改**档位上界**：`project_management_fee` 第 2 档 5000 → 6000
     → `test_expected_amounts_hand_checked` 红
       `Obtained: 188.0 / Expected: 185.0 ± 1.8e-04`
     ⚠ 值得记一笔：这处变异**数据侧测试全绿**——改上界不破坏任何内部一致性，
       而该条目没有 golden_example。挡住它的只有本文件的手算表。
  3. 改**落点**：`AGGREGATE_CHILD_ROWS` 删掉 `project_management_fee`（aggregate → input）
     → `test_write_target_partition` 红（集合少了 project_management_fee）
       `test_aggregate_items_never_write_formula_cells` 红
       （`project_management_fee 落点错：会写进公式格 / assert 'input' == 'aggregate'`）
       `test_covered_cells_leaves_the_unruled_inputs_to_the_caller` 红（14 != 13）
"""
import math
from pathlib import Path

import pytest

from zt.estimate import fee_rules as fr

SHEET = fr.SHEET

# 一组覆盖全部 16 项的基数（万元 / 万m2 / m2 / kVA，单位见各项 base.unit）
BASES = {
    "工程费用": 12000.0,
    "中标金额": 6000.0,
    "建安工程造价": 9000.0,
    "总建筑面积": 12.0,
    "建筑面积": 40000.0,
    "受电容量": 2000.0,
    "专利计费基数": 3000.0,
}
ATTRS = {
    "region": "urban",
    "land_scenario": "standard",
    "voltage_level": "10",
    "scenario": "user_total",
    "building_use": "residential",
    "bidding_type": "works",
    "consulting_service": "05_bill_budget_control_price",
    "study_stage": "feasibility_report",
    "eia_doc_type": "report_book",
    "building_category": "residential",
    # WS10-P03（issue #722）：三条带适用性的规则只在允许值上求值。给在允许值上，
    # 下面那批手算期望才走得到求值分支；未确认 / 不适用两态见 test_fee_rules_applicability.py。
    "project_city": "hangzhou_core",
    "project_nature": "production",
}

# 手算复核表：(item_id, suggested, range)。每个数的算式写在注释里，便于人核。
EXPECTED = {
    # 1000×2.3% + 4000×1.7% + 5000×1.4% + 2000×1.2% = 23+68+70+24
    "project_management_fee": (185.0, [185.0, 185.0]),
    # 1000×1.8% + 4000×1.32% + 5000×0.96% + 2000×0.6% = 18+52.8+48+12
    "management_other_fee": (130.8, [130.8, 130.8]),
    # 原表注2算例：100×1%+400×0.7%+500×0.55%+4000×0.35%+1000×0.2%
    "bidding_agency_fee": (22.55, [22.55, 22.55]),
    # ‰ 档：100×3.6+400×3.3+500×3.0+1000×2.7+3000×2.4+4000×2.1（÷1000）
    "cost_consulting_fee": (21.48, [21.48, 21.48]),
    # 锚点 10000→174.9、20000→314.7，插值 174.9+139.8×0.2
    "supervision_fee": (202.86, [202.86, 202.86]),
    # 档 (10000,50000] 25.8~69.0，插值 25.8+43.2×2000/40000
    "feasibility_study_fee": (27.96, [27.96, 27.96]),
    # 档 (10000,60000] 2.59%~2.15%，费率 2.59−0.44×2000/50000 = 2.5724%，×12000
    "survey_design_fee": (308.688, [308.688, 308.688]),
    # 档 (3000,20000] 4.5~11.2，插值 4.5+6.7×9000/17000
    "eia_fee": (8.0471, [8.0471, 8.0471]),
    # 累进：5×2.00 + 5×1.75 + 2×1.55 = 10+8.75+3.1；区间 ±20%
    "energy_assessment_fee": (21.85, [17.48, 26.22]),
    # 市区 0.7%~0.8%：84~96，中值 90
    "site_preparation_fee": (90.0, [84.0, 96.0]),
    "engineering_insurance_fee": (None, [None, None]),
    # 40000 m2 × 150 元/m2 ÷ 10000
    "municipal_infrastructure_fee": (600.0, [600.0, 600.0]),
    # 2000 kVA × 200 元/(kV·A) ÷ 10000
    "high_reliability_power_fee": (40.0, [40.0, 40.0]),
    # 0.3%~1%：36~120，中值 78
    "joint_commissioning_fee": (78.0, [36.0, 120.0]),
    # 3%~5%：90~150，中值 120
    "patent_technology_fee": (120.0, [90.0, 150.0]),
    # 1%~1.2%：120~144，中值 132
    "production_preparation_fee": (132.0, [120.0, 144.0]),
}

AGGREGATE_IDS = {"project_management_fee", "management_other_fee"}
MANUAL_IDS = {"engineering_insurance_fee"}


@pytest.fixture(scope="module")
def result():
    return fr._suggest_all_ungated(BASES, ATTRS)


@pytest.fixture(scope="module")
def by_id(result):
    return {s["item_id"]: s for s in result["items"]}


# ----------------------------------------------------------- 最硬的外部验证
def test_golden_example_reproduced_by_evaluator():
    """用**求值器**复算原表自带的算例（数据侧已复算过一遍，这里再走一遍代码路径）。

    工程招标代理费，工程招标，中标金额 6000 万元 → 22.55 万元。
    这个数印在计价格〔2002〕1980号 原表注2 上，不是我们算出来的：
    任一档位上界或费率抄错、或求值器的差额累进写歪，这条就红。
    """
    ex = fr._index()["bidding_agency_fee"]["golden_example"]
    s = fr._suggest_one_ungated("bidding_agency_fee", ex["base"], {"bidding_type": ex["column"]})
    assert s["suggested"] == pytest.approx(ex["expected_fee"], abs=1e-6), (
        f"复算原表算例不符：期望 {ex['expected_fee']} 实得 {s['suggested']}（{ex['desc']}）")
    assert s["suggested"] == pytest.approx(22.55, abs=1e-9), "原表注2 的 22.55 万元被改动了"


# ----------------------------------------------------------- 实现不走形
def _progressive_series():
    """(名称, uppers, 归一后的 rates)。三种档位写法都要认——漏认一种整条静默失效。"""
    for item in fr.list_items():
        if item.get("paradigm") != "progressive_difference":
            continue
        div = fr._RATE_DIVISOR[item["rate_unit"]]
        cols = item.get("columns")
        if isinstance(cols, dict):
            for name, col in cols.items():
                ups, rates = fr.bands_of(item, col)
                yield (f"{item['fee_name']}/{name}", ups, [r / div for r in rates])
        else:
            ups, rates = fr.bands_of(item, None)
            yield (item["fee_name"], ups, [r / div for r in rates])


def test_progressive_series_covers_all_four_items():
    """4 个差额累进条目**每一个**都必须至少产出一条序列（防「列级 bands」漏认）。"""
    covered = {n.split("/")[0] for n, _, _ in _progressive_series()}
    expected = {i["fee_name"] for i in fr.list_items()
                if i.get("paradigm") == "progressive_difference"}
    assert expected <= covered, f"这些条目未被覆盖：{expected - covered}"


def test_quick_deduction_equals_tiered_accumulation():
    """速算扣除数法 == 逐档累加法，逐点一致。

    ⚠ 效力边界：两种算法从同一组 (uppers, rates) 推导，代数上恒等，**证明不了数据对错**。
    它守的是求值器实现不走形 —— spec 要求用速算扣除数法出数，这条锁死那种写法与
    逐档累加等价。数据正确性靠 golden_example。
    """
    checked = 0
    for name, ups, rates in _progressive_series():
        qds = fr.quick_deductions(ups, rates)
        probes, lower = [], 0.0
        for up in ups:
            if up is None:
                probes += [lower * 1.5 + 1, lower * 10 + 1]
                break
            probes += [lower + (up - lower) * f for f in (0.001, 0.5, 0.999)] + [up]
            lower = up
        for x in probes:
            i = fr._locate_band(ups, x)
            a = fr.tiered_amount(x, ups, rates)
            b = x * rates[i] - qds[i]
            assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), f"{name} x={x}：{a} vs {b}"
            checked += 1
    assert checked >= 40, f"探测点只有 {checked} 个，覆盖不足"


def test_evaluator_output_equals_tiered_accumulation():
    """求值器实际吐出来的 suggested，必须等于逐档累加法的独立复算。

    上一条比的是两个 helper；这条比的是**端到端的求值器输出**，
    防止选列 / 单位换算 / 舍入这些接线环节把结果带偏。
    """
    cases = [
        ("project_management_fee", 12000.0, {}),
        ("management_other_fee", 12000.0, {}),
        ("bidding_agency_fee", 6000.0, {"bidding_type": "works"}),
        ("bidding_agency_fee", 123456.0, {"bidding_type": "goods"}),
        ("cost_consulting_fee", 9000.0, {"consulting_service": "05_bill_budget_control_price"}),
        ("cost_consulting_fee", 250000.0, {"consulting_service": "10_whole_process_control"}),
    ]
    for item_id, base, attrs in cases:
        item = fr._index()[item_id]
        col = (item.get("columns") or {}).get(
            attrs.get(fr.COLUMN_ATTR.get(item_id, ""), item.get("default_column")))
        ups, raw = fr.bands_of(item, col)
        div = fr._RATE_DIVISOR[item["rate_unit"]]
        want = fr.tiered_amount(base, ups, [r / div for r in raw])
        got = fr._suggest_one_ungated(item_id, base, attrs)["suggested"]
        assert got == pytest.approx(round(want, 4), abs=1e-6), f"{item_id} base={base}"


# ----------------------------------------------------------- 16 项各出结果
def test_sixteen_items_always_present(result):
    """16 条永远齐全，缺什么一目了然 —— 少一条比给错一条更危险。"""
    assert len(result["items"]) == 16
    assert {s["item_id"] for s in result["items"]} == set(EXPECTED)


def test_expected_amounts_hand_checked(by_id):
    """13 项 input 出 suggested、2 项 aggregate 出小计参考值、1 项 manual 出 None。

    每个期望值都按原表规则手算复核过（算式见 EXPECTED 的注释）。
    改任一档位费率 / 上界，这里就红。
    """
    bad = []
    for item_id, (want, want_range) in EXPECTED.items():
        s = by_id[item_id]
        if want is None:
            if s["suggested"] is not None:
                bad.append(f"{item_id} 应为 None，实得 {s['suggested']}")
            continue
        if s["suggested"] != pytest.approx(want, abs=1e-4):
            bad.append(f"{item_id} 期望 {want} 实得 {s['suggested']}")
        if s["range"] != pytest.approx(want_range, abs=1e-4):
            bad.append(f"{item_id} range 期望 {want_range} 实得 {s['range']}")
    assert not bad, "；".join(bad)


def test_write_target_partition(by_id):
    """落点三分：13 input / 2 aggregate / 1 manual —— 契约 §1.4 点名的分法。"""
    got = {}
    for s in by_id.values():
        got.setdefault(s["write_target"], set()).add(s["item_id"])
    assert got.get("aggregate") == AGGREGATE_IDS
    assert got.get("manual") == MANUAL_IDS
    assert len(got.get("input", ())) == 13
    assert set(EXPECTED) - AGGREGATE_IDS - MANUAL_IDS == got["input"]


def test_input_items_target_cell_is_c_fee_row(by_id):
    """input 项的落点必须是 `5.工程建设其他费用!C{fee_row}`。"""
    rows = {i["item_id"]: i["fee_row"] for i in fr.list_items()}
    for s in by_id.values():
        if s["write_target"] != "input":
            continue
        assert s["target_cell"] == f"{SHEET}!C{rows[s['item_id']]}"
        assert s["suggested"] is not None, f"{s['item_id']} 是输入位却没出建议值"


def test_aggregate_items_never_write_formula_cells(by_id):
    """C6/C9 是公式格（C6=SUM(C7:C8)、C9=SUM(C10:C13)），不许当输入位写。

    这两项必须：target_cell=None、write_target=aggregate、附 aggregate_children，
    且**引擎绝不平分** —— 小计等于原值，不是子项个数分之一。
    """
    expect_children = {
        "project_management_fee": [f"{SHEET}!C7", f"{SHEET}!C8"],
        "management_other_fee": [f"{SHEET}!C{r}" for r in (10, 11, 12, 13)],
    }
    for item_id, children in expect_children.items():
        s = by_id[item_id]
        assert s["write_target"] == "aggregate", f"{item_id} 落点错：会写进公式格"
        assert s["target_cell"] is None, f"{item_id} 不许有 target_cell"
        assert s["aggregate_children"] == children
        assert s["suggested"] == pytest.approx(EXPECTED[item_id][0]), (
            f"{item_id} 的小计参考值被动过——引擎不许平分到子项")
        codes = {w["code"] for w in s["warnings"]}
        assert "fee_write_target_aggregate" in codes, "小计语义必须在 warnings 里说清"


def test_manual_item_yields_no_number(by_id):
    s = by_id["engineering_insurance_fee"]
    assert s["write_target"] == "manual"
    assert s["suggested"] is None and s["range"] == [None, None]
    assert s["target_cell"] is None
    assert s["unavailable_reason"] == "manual_paradigm"
    assert "fee_manual_only" in {w["code"] for w in s["warnings"]}


def test_every_suggestion_is_editable(by_id):
    """铁律：产物是建议不是硬公式，`editable` 恒 True。"""
    assert all(s["editable"] is True for s in by_id.values())


# ----------------------------------------------------------- 闭开性
def test_declared_closure_upper_inclusive_at_boundary():
    """可行性研究费声明 lower_exclusive_upper_inclusive：档界 1000 归**上一档**。

    该范式在档界处数值连续（fee_max[k] == fee_min[k+1]），所以光看金额分不出闭开性；
    真正被闭开性决定的是**落在哪一档**，故这条断言的是 basis.band。
    """
    lo = fr._suggest_one_ungated("feasibility_study_fee", 1000.0, {"study_stage": "feasibility_report"})
    hi = fr._suggest_one_ungated("feasibility_study_fee", 1000.0001, {"study_stage": "feasibility_report"})
    assert lo["basis"]["band_closure"] == fr.CLOSURE_LOWER_EXCLUSIVE
    assert lo["basis"]["band"]["index"] == 0, "上限包含：1000 应归第 1 档"
    assert lo["basis"]["band"]["upper"] == 1000
    assert hi["basis"]["band"]["index"] == 1, "1000 之上应落第 2 档"
    assert lo["suggested"] == pytest.approx(4.6), "第 1 档上端点收费 4.6 万元"


def test_declared_closure_lower_inclusive_at_boundary():
    """节能评估费声明 lower_inclusive_upper_exclusive：档界 5 归**下一档**。"""
    at = fr._suggest_one_ungated("energy_assessment_fee", 5.0, {"building_category": "residential"})
    below = fr._suggest_one_ungated("energy_assessment_fee", 4.9999, {"building_category": "residential"})
    assert at["basis"]["band_closure"] == fr.CLOSURE_LOWER_INCLUSIVE
    assert at["basis"]["band"]["index"] == 1 and at["basis"]["band"]["lower"] == 5
    assert below["basis"]["band"]["index"] == 0
    # 累进计费在档界连续：5 万m2 = 5×2.00 = 10 万元
    assert at["suggested"] == pytest.approx(10.0)


def test_eia_declared_closure_matches_source_note():
    """环评费表2-17注1原文显式「下限不含、上限包含」，不许被改成另一侧。"""
    s = fr._suggest_one_ungated("eia_fee", 3000.0, {"eia_doc_type": "report_book"})
    assert s["basis"]["band_closure"] == fr.CLOSURE_LOWER_EXCLUSIVE
    assert s["basis"]["band_closure_source"] == "declared"
    assert s["basis"]["band"]["index"] == 0 and s["basis"]["band"]["upper"] == 3000


# ----------------------------------------------------------- 已知缺口的降级
def test_survey_design_closure_gap_is_never_silent():
    """勘察设计费未声明闭开性 → 绝不静默选一边。

    降级行为：按默认侧算一遍、按另一侧再算一遍，把「两者是否给出不同金额」
    如实写进 `fee_band_closure_unconfirmed` 告警与 `basis.closure_alternative`。
    这是**实算**出来的结论，不是嘴上断言的。
    """
    s = fr._suggest_one_ungated("survey_design_fee", 12000.0)
    assert s["basis"]["band_closure_source"] == "assumed"
    w = [x for x in s["warnings"] if x["code"] == "fee_band_closure_unconfirmed"]
    assert w, "闭开性未确认必须出告警"
    alt = s["basis"]["closure_alternative"]
    assert alt["closure"] == fr.CLOSURE_LOWER_INCLUSIVE
    assert alt["affects_amount"] is False, "12000 万元在档内，两侧应一致"
    assert "未声明档位闭开性" in w[0]["message"]


def test_survey_design_closure_gap_flags_the_case_where_it_bites():
    """在 x = 表末上界 60000 万元处，闭开性**真的**改变结果 —— 必须报出来。

    lower_exclusive：60000 落进末档，出 1290 万元；
    lower_inclusive：60000 已越过末档上界，落不进任何档，不出建议值。
    这正是「闭开性属影响金额的语义，必须造价员确认」的实证。
    """
    s = fr._suggest_one_ungated("survey_design_fee", 60000.0)
    alt = s["basis"]["closure_alternative"]
    assert s["suggested"] == pytest.approx(1290.0)  # 60000 × 2.15%
    assert alt["suggested"] is None
    assert alt["affects_amount"] is True
    msg = [x for x in s["warnings"] if x["code"] == "fee_band_closure_unconfirmed"][0]["message"]
    assert "两者不同" in msg and "落不进任何档" in msg


def test_survey_design_gap_matches_the_registered_known_gaps():
    """降级只针对已登记的缺口条目；别的条目若漏声明闭开性，应由数据侧测试判红。"""
    gaps = {i["fee_name"] for i in fr.list_items()
            if i.get("paradigm") in fr._CLOSURE_SENSITIVE and not i.get("band_closure")}
    assert gaps == {"勘察设计费"}, f"闭开性缺口集合变了：{gaps}（数据侧 CLOSURE_KNOWN_GAPS 需同步）"


def test_survey_design_reports_partial_coverage():
    """勘察设计费的规则只覆盖「工程设计费」，「工程勘察费」是「详见文件」。

    建议值不含勘察费 —— 这一点必须报出来，否则用户会把设计费当成两项之和。
    """
    s = fr._suggest_one_ungated("survey_design_fee", 12000.0)
    w = [x for x in s["warnings"] if x["code"] == "fee_partial_coverage"]
    assert w and "工程勘察费" in w[0]["message"]
    assert s["basis"]["sub_item_manual"]["name"] == "工程勘察费"


def test_survey_design_does_not_extrapolate_outside_the_table():
    """表外不外推：原文只给 200 万~6 亿，越界就不出数，不编。"""
    for x in (100.0, 60001.0):
        s = fr._suggest_one_ungated("survey_design_fee", x)
        assert s["suggested"] is None, f"x={x} 不该有建议值"
        assert "fee_base_out_of_table" in {w["code"] for w in s["warnings"]}


# ----------------------------------------------------------- 签字位
def test_signoff_state_is_visible_in_three_places(result, by_id):
    """铁律 2 的最后一句：签署状态不许因为好看就藏起来。

    `suggest_one` 拿不到顶层 warnings 列表，所以顶层字段与 basis 里也必须各有一份。

    ⚠ 2026-09-10（#159）起数据是 `signed` + `owner_release`（仓主默认放行，
    **不是**造价员签署）。判据因此从「到处都写着 pending」改成「到处都写着
    **同一个真实状态**，且分得清签的是谁」—— 把 owner_release 显示成
    「已由造价员签署」比 pending 更危险：它会让人以为这些数字有专业背书。
    """
    doc_status = fr._load()["signoff_status"]
    doc_kind = fr._load().get("signoff_kind")
    top_codes = {w["code"] for w in result["warnings"]}
    if doc_status != "signed":
        assert "fee_rules_unsigned" in top_codes
    elif doc_kind != fr.SIGNOFF_KIND_COST_ENGINEER:
        assert "fee_rules_owner_released" in top_codes, (
            "已放行但不是造价员签的，顶层却一条告警都没有 —— 这就是「藏起来」")
    for s in by_id.values():
        assert s["signoff_status"] == doc_status
        assert s["signoff_kind"] == doc_kind
        assert s["basis"]["signoff_status"] == doc_status
        assert s["basis"]["signoff_kind"] == doc_kind
        assert s["basis"]["requires_human_signoff"] is True
    one = fr._suggest_one_ungated("supervision_fee", 12000.0)
    assert one["signoff_status"] == doc_status
    assert one["signoff_kind"] == doc_kind
    assert one["basis"]["signoff_status"] == doc_status
    assert one["basis"]["signoff_kind"] == doc_kind


def test_owner_release_warning_names_the_cost_and_does_not_claim_a_signature():
    """#159：放行告警必须把代价说出来，且**不许**声称造价员签过字。

    这条挡的是「为了界面好看，把 fee_rules_owner_released 的正文写成
    『费率已签署，可放心使用』」那一类改动。
    """
    doc = fr._load()
    if doc.get("signoff_kind") == fr.SIGNOFF_KIND_COST_ENGINEER:
        # 造价员真签了字之后本条不再适用；仍做形状校验，不 skip（跳过=判据消失）
        assert doc.get("signoff_by"), "造价员签署必须写明签字人"
        return
    r = fr.suggest_all(BASES, ATTRS)
    w = next(w for w in r["warnings"] if w["code"] == "fee_rules_owner_released")
    msg = w["message"]
    assert "不是造价员签署" in msg, msg
    assert "未经造价员逐值核对" in msg, msg
    assert doc["signoff_by"] in msg, "告警没如实报出 signoff_by，读者查不到是谁放的行"


def test_basis_is_auditable(by_id):
    """契约 §1.4 锁定的 basis 六键必须齐，且带得回原图。"""
    for s in by_id.values():
        b = s["basis"]
        for k in ("paradigm", "source_ref", "source_image", "base_name", "base_value", "steps"):
            assert k in b, f"{s['item_id']} basis 缺 {k}"
        assert b["source_image"], f"{s['item_id']} 取不到原图，造价员无从复核"
        assert isinstance(b["steps"], list) and b["steps"], f"{s['item_id']} 无算式分解"


# ----------------------------------------------------------- 属性与降级
def test_attr_default_is_warned_not_silent():
    """影响金额的属性回落默认值必须出告警 —— 住宅 150 / 非住宅 220 差 47%。"""
    # project_city 是适用性属性（WS10-P03），不是「可回落默认值」的取费属性，必须给
    s = fr._suggest_one_ungated("municipal_infrastructure_fee", 40000.0,
                                {"project_city": "hangzhou_core"})
    codes = [w["code"] for w in s["warnings"]]
    assert codes.count("fee_attr_defaulted") >= 2  # land_scenario + building_use
    assert s["attrs_used"]["land_scenario"] == "standard"
    assert s["attrs_used"]["building_use"] == "residential"
    other = fr._suggest_one_ungated("municipal_infrastructure_fee", 40000.0,
                           {"land_scenario": "standard", "building_use": "non_residential",
                            "project_city": "hangzhou_core"})
    assert other["suggested"] == pytest.approx(880.0)  # 40000×220÷10000


def test_unknown_attr_value_falls_back_loudly():
    s = fr._suggest_one_ungated("site_preparation_fee", 12000.0, {"region": "mars"})
    assert "fee_attr_unknown_value" in {w["code"] for w in s["warnings"]}
    assert s["attrs_used"]["region"] == "urban"


def test_site_preparation_variants_differ():
    """场地准备费三个地区档必须给出不同数，别被默认值吃掉。"""
    got = {r: fr._suggest_one_ungated("site_preparation_fee", 12000.0, {"region": r})["suggested"]
           for r in ("urban", "county_town", "other")}
    assert got == {"urban": 90.0, "county_town": 102.0, "other": 120.0}


def test_matrix_dash_cell_is_not_applicable():
    """矩阵里的「—」表示该情形不适用 → 不出数、转人工，不许拿 0 或邻格顶替。"""
    s = fr._suggest_one_ungated("high_reliability_power_fee", 2000.0,
                       {"voltage_level": "35", "scenario": "distribution"})
    assert s["suggested"] is None
    assert s["unavailable_reason"] == "rule_not_applicable"
    assert "fee_matrix_not_applicable" in {w["code"] for w in s["warnings"]}


def test_min_fee_floor_applies():
    """造价咨询费「不足2000元按2000元收费」 —— 下限要生效且要说明。"""
    s = fr._suggest_one_ungated("cost_consulting_fee", 10.0,
                       {"consulting_service": "05_bill_budget_control_price"})
    assert s["suggested"] == pytest.approx(0.2)  # 万元
    assert "fee_min_fee_applied" in {w["code"] for w in s["warnings"]}


def test_supervision_out_of_table_is_extrapolated_with_flag():
    """监理费表外（<500 或 >1000000 万元）按比例外推，但必须打 flag。"""
    lo = fr._suggest_one_ungated("supervision_fee", 300.0)
    hi = fr._suggest_one_ungated("supervision_fee", 2000000.0)
    assert lo["suggested"] == pytest.approx(13.2 * 300 / 500)
    assert hi["suggested"] == pytest.approx(8312.1 * 2000000 / 1000000)
    for s in (lo, hi):
        assert "fee_base_out_of_table" in {w["code"] for w in s["warnings"]}
    assert lo["basis"]["extrapolated"] == "below_table"
    assert hi["basis"]["extrapolated"] == "above_table"


def test_open_ended_band_lower_bound_only():
    """环评报告书末档原表写「82.2以上」，只有下限 —— 给下限并说清可能更高。"""
    s = fr._suggest_one_ungated("eia_fee", 2_000_000.0, {"eia_doc_type": "report_book"})
    assert s["suggested"] == pytest.approx(82.2)
    assert s["range"] == [82.2, None]
    assert "fee_band_open_ended" in {w["code"] for w in s["warnings"]}


def test_open_ended_band_with_both_bounds_uses_midpoint():
    """可研费末档 500000 以上是 184.0~230.0，有区间无上界 → 取中值并给出区间。"""
    s = fr._suggest_one_ungated("feasibility_study_fee", 900_000.0, {"study_stage": "feasibility_report"})
    assert s["suggested"] == pytest.approx(207.0)
    assert s["range"] == pytest.approx([184.0, 230.0])
    assert "fee_band_open_ended" in {w["code"] for w in s["warnings"]}


def test_energy_paradigm_dispute_is_surfaced():
    """节能评估费的范式归类争议数据里就标了，求值器要把它抬到 warnings。"""
    s = fr._suggest_one_ungated("energy_assessment_fee", 12.0, {"building_category": "residential"})
    assert "fee_paradigm_disputed" in {w["code"] for w in s["warnings"]}


# ----------------------------------------------------------- 基数解析
def test_missing_base_still_yields_an_item():
    """查不到基数的条目照样出现在 items 里，带 fee_base_missing —— 少一条更危险。"""
    r = fr._suggest_all_ungated({"工程费用": 12000.0})
    assert len(r["items"]) == 16
    miss = {s["item_id"] for s in r["items"] if s["unavailable_reason"] == "no_base"}
    assert {"bidding_agency_fee", "high_reliability_power_fee", "patent_technology_fee"} <= miss
    for item_id in miss:
        s = [x for x in r["items"] if x["item_id"] == item_id][0]
        assert "fee_base_missing" in {w["code"] for w in s["warnings"]}


def test_base_is_never_substituted_across_meanings():
    """不许拿「工程费用」冒充「中标金额」「建安工程造价」「受电容量」这些不同口径的基数。"""
    r = fr._suggest_all_ungated({"工程费用": 12000.0})
    by = {s["item_id"]: s for s in r["items"]}
    for item_id in ("bidding_agency_fee", "cost_consulting_fee", "energy_assessment_fee",
                    "municipal_infrastructure_fee", "high_reliability_power_fee",
                    "patent_technology_fee"):
        assert by[item_id]["suggested"] is None, f"{item_id} 拿了别的口径的基数"


def test_item_id_key_overrides_base_name():
    """`bases[item_id]` 是最精确的键，优先于基数名。"""
    r = fr._suggest_all_ungated({"工程费用": 12000.0, "supervision_fee": 5000.0})
    by = {s["item_id"]: s for s in r["items"]}
    assert by["supervision_fee"]["basis"]["base_value"] == 5000.0
    assert by["supervision_fee"]["suggested"] == pytest.approx(96.6)  # 锚点原值
    assert by["site_preparation_fee"]["basis"]["base_value"] == 12000.0


def test_municipal_base_can_be_split_by_use():
    """市政配套费原表按用途分单价，基数支持 `建筑面积.residential` 这类拆分键。"""
    r = fr._suggest_all_ungated({"建筑面积.residential": 30000.0, "建筑面积.non_residential": 10000.0},
                       {"land_scenario": "standard", "project_city": "hangzhou_core"})
    m = [s for s in r["items"] if s["item_id"] == "municipal_infrastructure_fee"][0]
    assert m["suggested"] == pytest.approx(450.0 + 220.0)  # 30000×150 + 10000×220，÷10000
    assert m["basis"]["base_parts"] == {"residential": 30000.0, "non_residential": 10000.0}


def test_non_positive_base_yields_no_number():
    s = fr._suggest_one_ungated("supervision_fee", 0.0)
    assert s["suggested"] is None
    assert "fee_base_non_positive" in {w["code"] for w in s["warnings"]}


# ----------------------------------------------------------- 接线面
def test_covered_cells_leaves_the_unruled_inputs_to_the_caller():
    """C15/C24/C25/C26/C27 是输入位但无规则 → 不在覆盖集内，由 suggest 侧落 no_rule。"""
    cells = fr.covered_cells()
    assert len(cells) == 13
    for row in (15, 24, 25, 26, 27):
        assert f"{SHEET}!C{row}" not in cells
    assert f"{SHEET}!C6" not in cells and f"{SHEET}!C9" not in cells  # 公式格
    assert f"{SHEET}!C21" not in cells  # 工程保险费 manual


def test_unknown_item_and_ruleset_raise():
    with pytest.raises(fr.FeeRuleError):
        fr._suggest_one_ungated("no_such_fee", 100.0)
    with pytest.raises(fr.FeeRuleError):
        fr._suggest_all_ungated({}, {}, ruleset="no_such_ruleset")


def test_engine_is_deterministic():
    """同样输入必须同样输出（纯确定性，可复算）。"""
    a = fr._suggest_all_ungated(BASES, ATTRS)
    b = fr._suggest_all_ungated(BASES, ATTRS)
    assert [s["suggested"] for s in a["items"]] == [s["suggested"] for s in b["items"]]


def test_no_llm_and_no_db_in_source():
    """产品红线：LLM 不碰金额；引擎无状态不连 DB。用源码扫描把红线钉住。"""
    src = (Path(fr.__file__)).read_text(encoding="utf-8")
    forbidden = ("llm_client", "openai", "anthropic", "pymysql", "sqlalchemy",
                 "psycopg", "requests.post", "httpx")
    hits = [t for t in forbidden if t in src]
    assert not hits, f"fee_rules.py 出现禁用依赖：{hits}"


# ----------------------------------------------------------- 计费属性清单（O-08）
#
# 这组测试守的是一条**闭环**：`required_attrs()` 下发的每一个选项键，必须正好是
# `_select_key()` 认得的键。只断言「字段非空」是不够的 —— 引擎发一份自造的
# 选项，前端照着渲染，用户选了，引擎再按 `fee_attr_unknown_value` 回落默认列：
# 金额照出，没人知道用错了。那比不给下拉更坏。

def _all_bases():
    return {i["base_key"]: 12000.0 for i in fr.required_bases() if i["base_key"]}


def test_required_attrs_covers_every_controlled_choice():
    """每一个「选错就换一个金额」的属性都必须在清单里。

    判据不是数出几条，而是**没有属性清单时引擎发几条 fee_attr_defaulted**：
    该告警正是「我替你选了一个影响金额的值」。清单条数少于告警条数 = 有属性
    在静默取默认值，而调用方连问都问不出来。
    """
    defaulted = {
        w["item_id"] for w in fr._suggest_all_ungated(_all_bases(), {})["warnings"]
        if w["code"] == "fee_attr_defaulted"
    }
    assert defaulted, "求值器一条 fee_attr_defaulted 都没发，这条测试失去判据"
    covered = {i for s in fr.required_attrs() for i in s["item_ids"]}
    assert defaulted <= covered, (
        f"这些条目会静默取默认值，却不在 required_attrs 清单里："
        f"{sorted(defaulted - covered)}")


def test_required_attrs_defaults_silence_every_defaulted_warning():
    """把清单里的 default 原样回传 → 一条 fee_attr_defaulted 都不该剩。

    这条同时证明 `name` 与 `default` 两个键都是求值器真正认的口径：
    名字拼错、默认值写成 label 而不是 key，都会让告警剩下来。
    """
    bases = _all_bases()
    specs = fr.required_attrs()
    attrs = {s["name"]: s["default"] for s in specs}
    left = [w["item_id"] for w in fr._suggest_all_ungated(bases, attrs)["warnings"]
            if w["code"] == "fee_attr_defaulted"]
    assert not left, f"回传了清单里的默认值，这些项仍在按默认值算：{left}"


def test_every_offered_option_is_accepted_by_the_evaluator():
    """清单里的每个选项都必须能被求值器接受 —— 一个都不许是引擎自造的。

    22 个选项逐个回灌；只要有一个落进 `fee_attr_unknown_value`，说明引擎在
    「问用户」和「认答案」两处用了两套键，用户的选择被静默丢弃。
    """
    bases = _all_bases()
    specs = fr.required_attrs()
    base_attrs = {s["name"]: s["default"] for s in specs}
    rejected = []
    checked = 0
    for s in specs:
        for opt in s["options"]:
            attrs = dict(base_attrs, **{s["name"]: opt["value"]})
            checked += 1
            for w in fr._suggest_all_ungated(bases, attrs)["warnings"]:
                if w["code"] == "fee_attr_unknown_value":
                    rejected.append((s["name"], opt["value"], w["message"]))
    assert checked >= 20, f"只回灌了 {checked} 个选项，清单疑似塌成空壳"
    assert not rejected, f"这些选项引擎自己不认：{rejected[:5]}"


def test_offered_options_change_the_amount_so_the_dropdown_is_not_cosmetic():
    """至少要有属性能真的换出一个不同金额，否则这批下拉是装饰品。

    点名 building_use：住宅 150 / 非住宅 220 元/m²，差 47%。
    """
    bases = _all_bases()
    specs = {s["name"]: s for s in fr.required_attrs()}
    assert "building_use" in specs, "市政配套费的建筑用途没进清单（住宅/非住宅差 47%）"

    def _amount(use):
        attrs = {s["name"]: s["default"] for s in fr.required_attrs()}
        # 适用性属性没有默认值（WS10-P03）：给在允许值上，否则整条不求值、两边都是 None
        attrs.update(project_city="hangzhou_core", project_nature="production")
        attrs["building_use"] = use
        got = fr._suggest_all_ungated(bases, attrs)["items"]
        return next(i["suggested"] for i in got
                    if i["item_id"] == "municipal_infrastructure_fee")

    assert _amount("residential") != _amount("non_residential"), \
        "换了建筑用途金额没变 —— 属性没接到求值器上"


def test_required_attrs_never_invents_a_label_for_an_option():
    """选项的 label 只能来自数据；数据没有就给 None，不许代码编一个中文名。

    编出来的名字与费率原表对不上，造价员照着签字就是签了个不存在的口径。
    """
    raw = fr._load()
    labels_in_data: set[str] = set()
    def _walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("label"), str):
                labels_in_data.add(o["label"])
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)
    _walk(raw)
    for s in fr.required_attrs():
        for opt in s["options"]:
            if opt["label"] is not None:
                assert opt["label"] in labels_in_data, (
                    f"{s['name']}.{opt['value']} 的 label {opt['label']!r} 不在规则数据里")
