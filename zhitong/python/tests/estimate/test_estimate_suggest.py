# 来源：engine-service/tests/test_estimate_suggest.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""概算正向推算通道（I-2.3）—— estimate_suggest 模块测试。

本模块存在的意义：把「概算生成」从手填表单变成推算。所以测试的重心是
**能不能真的从 11 个经济技术指标推出金额**，以及**推不出来时会不会瞎猜**。

依赖说明：`estimate_engine.py` 与 `gsyz_v1.json` 由并行分支 feat/estimate-engine-w2a
提供。未合并时本文件整体 skip（不是伪造依赖硬跑）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

_TPL = (Path(__file__).resolve().parents[2] / "zt" / "estimate" / "data"
        / "estimate_templates" / "gsyz_v1.json")
pytestmark = pytest.mark.skipif(
    not _TPL.is_file(),
    reason="gsyz_v1.json / estimate_engine.py 由 feat/estimate-engine-w2a 提供，未合并时跳过",
)

if _TPL.is_file():  # 避免未合并时模块级 import 就炸
    from zt.estimate import policy as estimate_policy
    from zt.estimate.engine import load_template
    from zt.estimate.suggest import cost_quantity_map, suggest

# 契约 §3.3 的 11 个必填输入位；数值是本测试自造的规模，不是任何真实项目数据
ROOT_INPUTS = {
    "经济技术指标!D4": 12000.0,   # 用地面积
    "经济技术指标!D7": 5200.0,    # A区地下室
    "经济技术指标!D8": 3100.0,    # B区地下室
    "经济技术指标!D10": 8800.0,   # 1#楼
    "经济技术指标!D11": 7600.0,   # 2#楼
    "经济技术指标!D12": 6400.0,   # 3#楼
    "经济技术指标!D13": 5900.0,   # 4#楼
    "经济技术指标!D15": 4200.0,
    "经济技术指标!D16": 3300.0,
    "经济技术指标!D19": 260.0,
    "经济技术指标!D20": 140.0,
}
DIMS = {"region": None, "price_period": None, "project_type": "房屋建筑", "structure_type": None}
FEE_SHEETS = ["1.建筑工程费", "2.安装工程费", "3.专项工程费",
              "4.室外及配套工程费", "5.工程建设其他费用"]


def _quantity_input_cells() -> list[str]:
    """5 张费用表里自己就是数量输入位的格（3.专项 42 + 4.室外 3）。"""
    tpl = load_template()
    c2q = cost_quantity_map()
    declared = {i["cell"] for i in tpl["inputs"]}
    return sorted({q for c, q in c2q.items() if q in declared and c in declared})


# --------------------------------------------------------------- 反解与覆盖


def test_cost_quantity_map_reverses_all_224_unit_cost_formulas():
    """数量列靠反解 224 条单方指标公式得到，不是猜的、也不是另建映射表。"""
    tpl = load_template()
    uc = [f for f in tpl["formulas"] if f["class"] == "unit_cost"]
    assert len(uc) == 224
    c2q = cost_quantity_map()
    assert len(c2q) == 224            # 224 条全部解析成功，无一条漏网
    cost_inputs = [i["cell"] for i in tpl["inputs"] if i["kind"] == "cost"]
    assert len(cost_inputs) == 150
    assert set(cost_inputs) <= set(c2q)  # 150 个成本输入位全部反解得到数量格
    # 反解出来的必须是同表同行（原表形态 =C7/E7*10000）
    for cost, qty in c2q.items():
        assert cost.split("!")[0] == qty.split("!")[0]
        assert cost.split("!")[1][1:] == qty.split("!")[1][1:]


LUMP_SUM_4 = [f"4.室外及配套工程费!C{r}" for r in (27, 28, 29, 30, 31)]
SHEET5_COST = [f"5.工程建设其他费用!C{r}" for r in (7, 8, *range(10, 31))]


def test_zero_manual_entry_reaches_3_of_5_fee_sheets(concept_baselines):
    """验收主线：只给 11 个经济技术指标 + 项目类型，能推出多少建议金额。

    WS10-P02（issue #722）之后实测 **77/150**（原 105/150）：5 表 23 格与
    4 表 C27-C31 共 28 格在样本里是**包干额**（种子 unit_cost × 17 万㎡ = 整数），
    按本项目面积放大没有意义，改为 lump_sum 不做面积推算 —— 费率覆盖的 13 格看 fee[]，
    其余按 manual_hint 人工填。3.专项工程费 42 条仍推不出（数量是发电功率 kW /
    车位 / kWp 这类项目专属量，没有根输入可推导）。

    ⚠ 本条同时是 spec I-2.3 验收措辞的**回归闸**：
    docs/superpowers/specs/2026-08-28-概算能力与造价AI入口-design.md 的验收条
    逐字引了这里的数字。数字哪天变了，这条会红，届时**spec 必须同步改**。
    """
    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    cov = res["coverage"]
    assert cov["cost_inputs"] == 150
    assert cov["suggested"] == 77
    assert cov["unresolved"] == 73
    assert cov["rate"] == round(77 / 150, 4)
    by = cov["by_sheet"]
    assert by["1.建筑工程费"]["suggested"] == 29
    assert by["2.安装工程费"]["suggested"] == 38
    assert by["4.室外及配套工程费"]["suggested"] == 10
    assert by["5.工程建设其他费用"]["suggested"] == 0
    assert by["3.专项工程费"]["suggested"] == 0
    reasons = {}
    for u in res["unresolved"]:
        reasons.setdefault(u["reason"], set()).add(u["cell"])
    # 45 条缺数量（全部指得出该填哪一格），28 条包干额（13 看费率侧、15 人工填）
    assert len(reasons["no_quantity"]) == 45
    assert all(u["quantity_is_input"] for u in res["unresolved"] if u["reason"] == "no_quantity")
    assert len(reasons["baseline_not_scalable"]) == 13
    assert len(reasons["manual_required"]) == 15
    assert set(reasons) == {"no_quantity", "baseline_not_scalable", "manual_required"}


def test_quantities_supplied_cover_every_area_scaled_cell(concept_baselines):
    """补上 45 个数量输入位后，122 个按面积推算的格全部出建议；28 个包干额格仍不推算。"""
    inputs = dict(ROOT_INPUTS)
    inputs.update({c: 1000.0 for c in _quantity_input_cells()})
    res = suggest(inputs, concept_baselines, dims=DIMS)
    assert res["coverage"]["suggested"] == 122
    assert {u["cell"] for u in res["unresolved"]} == set(LUMP_SUM_4 + SHEET5_COST)
    for sheet in FEE_SHEETS[:4]:
        assert res["coverage"]["by_sheet"][sheet]["suggested"] > 0, sheet


def test_forward_is_exact_inverse_of_the_original_reverse_formula(concept_baselines):
    """正向 unit_cost×qty/10000 与原表反向 cost/qty*10000 必须互为逆运算。"""
    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    for s in res["suggestions"]:
        assert s["suggested_cost"] == pytest.approx(
            s["unit_cost"] * s["quantity"] / 10000.0, rel=1e-9, abs=1e-4)
        # suggested_cost 按 4 位小数（万元→0.01 元）落值，反算回单方指标的残差
        # 上界是 5e-5 万元 ×10000/数量 = 0.5/数量 元，实测最小数量 140 → 0.004 元
        assert abs(s["suggested_cost"] * 10000.0 / s["quantity"] - s["unit_cost"]) < 0.01


def test_known_row_matches_hand_computation(concept_baselines):
    """钉一条可手算的：1.建筑工程费!C7 土石方工程（WS10-P01 语义键口径）。

    C7（A区地下室）与 C16（B区地下室）的叶子都是「土石方工程」，语义键同为
    `1.建筑工程费/basement/土石方工程`，种子 R07=250、R16=240 两行都是样本成员：
      单方 = 中位数 245；数量 1.建筑工程费!E7 = 经济技术指标!$D$7 = 5200 ㎡
      建议 = 245 × 5200 / 10000 = 127.4 万元；区间 = [240, 250] × 5200 / 10000 = [124.8, 130.0]
    审计指针取最接近中位数的一条（两条等距 → indicator_code 取小 = R07）。
    两行来源都是 gsyz_v1 → 只有 1 个来源 → reference_only（D47）。
    """
    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    row = next(s for s in res["suggestions"] if s["cell"] == "1.建筑工程费!C7")
    assert row["quantity_cell"] == "1.建筑工程费!E7"
    assert row["quantity"] == 5200.0
    assert row["unit_cost"] == 245.0
    assert row["suggested_cost"] == 127.4
    assert row["range"] == [124.8, 130.0]
    assert row["range_basis"] == "sample_min_max"
    assert row["match"] == "semantic"
    assert row["semantic_key"] == "1.建筑工程费/basement/土石方工程"
    assert row["baseline_ref"] == "GSYZ-F1-R07"
    assert row["evidence"] == {"n_values": 2, "n_sources": 1, "sources": ["gsyz_v1"],
                               "baseline_refs": ["GSYZ-F1-R07", "GSYZ-F1-R16"]}
    assert row["reference_only"] is True
    assert row["unit"] == "㎡"
    assert row["editable"] is True


def test_every_suggestion_is_traceable_and_overridable(concept_baselines):
    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    assert res["suggestions"]
    for s in res["suggestions"]:
        assert s["editable"] is True          # 建议值永远可覆盖，不是硬公式
        assert s["baseline_ref"]              # 每一分钱都追得回哪条基准
        assert s["baseline_ref"] in s["evidence"]["baseline_refs"]
        assert s["match"] in ("cell", "semantic", "item_code", "item_name")
        if s["range_basis"] == "single_value":
            assert s["range"] == [None, None]
        else:
            assert s["range"][0] <= s["suggested_cost"] <= s["range"][1]


# --------------------------------------------------------------- 严格查表


def test_empty_baselines_yields_zero_suggestions_not_guesses(concept_baselines):
    """新租户没灌种子是正常态：全部落 unresolved，绝不编一个金额出来（铁律 3）。"""
    res = suggest(ROOT_INPUTS, [], dims=DIMS)
    assert res["suggestions"] == []
    assert res["coverage"]["rate"] == 0.0
    assert len(res["unresolved"]) == 150
    # WS10-P02 起包干额 28 格不走基准查表：费率覆盖的 13 格 baseline_not_scalable，
    # 其余 15 格 manual_required；按面积推算的格查不到基准才是 no_baseline。
    assert {u["reason"] for u in res["unresolved"]} == {
        "no_baseline", "baseline_not_scalable", "manual_required"}
    manual = {u["cell"] for u in res["unresolved"] if u["reason"] == "manual_required"}
    assert manual == set(LUMP_SUM_4) | {f"5.工程建设其他费用!C{r}"
                                        for r in (7, 8, 10, 13, 15, 21, 24, 25, 26, 27)}


def test_dims_filter_drops_mismatched_project_type(concept_baselines):
    """维度不符要过滤掉；种子 224 条 project_type 全是「房屋建筑」。"""
    res = suggest(ROOT_INPUTS, concept_baselines, dims={"project_type": "市政基础设施"})
    assert res["suggestions"] == []
    assert {u["reason"] for u in res["unresolved"]} == {
        "no_baseline", "baseline_not_scalable", "manual_required"}


def test_dims_filter_treats_null_dimension_as_wildcard(concept_baselines):
    """种子四维里 region/price_period/structure_type 全 NULL —— 按等值过滤会全军覆没，
    必须当通配处理，否则正向推算在首批数据上直接归零。"""
    res = suggest(ROOT_INPUTS, concept_baselines,
                  dims={"region": "杭州", "price_period": "2026Q2",
                        "project_type": "房屋建筑", "structure_type": "框架"})
    assert res["coverage"]["suggested"] == 77


def test_null_dims_wildcard_is_disclosed_not_silent(concept_baselines):
    """#129：NULL 通配可以，但不许静默。首批种子三维（region/price_period/
    structure_type）全 NULL——每条命中都是「通配」而非「适配」，必须：
    ① 逐条建议带 dims_unasserted 明细；② 出一条 baseline_dims_unasserted 聚合告警。"""
    res = suggest(ROOT_INPUTS, concept_baselines,
                  dims={"region": "杭州", "price_period": "2026Q2",
                        "project_type": "房屋建筑", "structure_type": "框架"})
    assert res["suggestions"], "前置：真种子上必须有建议（105 条）"
    for s in res["suggestions"]:
        assert "region" in s["dims_unasserted"], f"{s['cell']} 应披露 region 未断言"
        assert "price_period" in s["dims_unasserted"]
        assert "structure_type" in s["dims_unasserted"]
        assert "project_type" not in s["dims_unasserted"], "种子断言了 project_type，不许误报"
    agg = [w for w in res["warnings"] if w["code"] == "baseline_dims_unasserted"]
    assert len(agg) == 1, "应恰有一条聚合告警（不是每格刷一条）"
    assert str(len(res["suggestions"])) in agg[0]["message"], "聚合告警应带命中条数"


def test_fully_asserted_dims_do_not_warn():
    """四维齐全的基准行不许误报——披露的是「数据没断言」，不是「用了维度过滤」。"""
    base = [{
        "indicator_code": "X-9", "item_name": None, "unit": "㎡", "unit_cost": 300.0,
        "source_sheet": "1.建筑工程费", "source_row": 7, "item_code": None,
        "region": "杭州", "price_period": "2026Q2",
        "project_type": "房屋建筑", "structure_type": "框架",
    }]
    res = suggest(ROOT_INPUTS, base,
                  dims={"region": "杭州", "price_period": "2026Q2",
                        "project_type": "房屋建筑", "structure_type": "框架"})
    hit = [s for s in res["suggestions"] if s["cell"] == "1.建筑工程费!C7"]
    assert hit, "前置：该基准行应命中 C7"
    assert "dims_unasserted" not in hit[0]
    assert not [w for w in res["warnings"] if w["code"] == "baseline_dims_unasserted"]


def test_quantity_zero_is_flagged_not_divided(concept_baselines):
    """某单体面积填 0（比如没有 B 区地下室）→ 该组落 quantity_zero，不是 0 元建议。"""
    inputs = dict(ROOT_INPUTS, **{"经济技术指标!D8": 0.0})
    res = suggest(inputs, concept_baselines, dims=DIMS)
    zeros = [u for u in res["unresolved"] if u["reason"] == "quantity_zero"]
    assert zeros, "面积为 0 的单体应落 quantity_zero"
    assert all(u["cell"] not in {s["cell"] for s in res["suggestions"]} for u in zeros)


def test_item_name_fallback_when_source_cell_absent():
    """基准行没带 source_sheet/source_row 时退到 item_name 全等——只全等，不模糊。"""
    base = [
        {"indicator_code": "X-1", "item_name": "土石方工程", "unit": "㎡", "unit_cost": 300.0,
         "source_sheet": None, "source_row": None, "item_code": None,
         "region": None, "price_period": None, "project_type": None, "structure_type": None},
        {"indicator_code": "X-2", "item_name": "土石方", "unit": "㎡", "unit_cost": 999.0,
         "source_sheet": None, "source_row": None, "item_code": None,
         "region": None, "price_period": None, "project_type": None, "structure_type": None},
    ]
    res = suggest(ROOT_INPUTS, base, dims=DIMS)
    hits = [s for s in res["suggestions"] if s["match"] == "item_name"]
    assert {s["baseline_ref"] for s in hits} == {"X-1"}   # 「土石方」不会被当成「土石方工程」
    assert all(s["unit_cost"] == 300.0 for s in hits)


def test_item_code_fallback_uses_item_dictionary():
    """item_code 回链要靠 concept_indicator_item，不是靠猜（契约 §3.2 的 items 字段）。"""
    base = [{"indicator_code": "Y-1", "item_name": "别名对不上", "item_code": "GSJZ-01-007",
             "unit": "㎡", "unit_cost": 400.0, "source_sheet": None, "source_row": None,
             "region": None, "price_period": None, "project_type": None, "structure_type": None}]
    items = [{"item_code": "GSJZ-01-007", "item_name": "土石方工程"}]
    res = suggest(ROOT_INPUTS, base, dims=DIMS, items=items)
    hits = [s for s in res["suggestions"] if s["match"] == "item_code"]
    assert hits and all(s["baseline_ref"] == "Y-1" for s in hits)
    # 不给 items 就回链不上 —— 严格查表，不靠名字近似脑补
    assert suggest(ROOT_INPUTS, base, dims=DIMS)["suggestions"] == []


def test_ambiguous_item_name_is_refused_not_arbitrated():
    """同名两条基准、单方指标不一致 → 不二选一，落 unresolved。"""
    base = [
        {"indicator_code": "A", "item_name": "土石方工程", "unit": "㎡", "unit_cost": 100.0,
         "source_sheet": None, "source_row": None, "item_code": None,
         "region": None, "price_period": None, "project_type": None, "structure_type": None},
        {"indicator_code": "B", "item_name": "土石方工程", "unit": "㎡", "unit_cost": 900.0,
         "source_sheet": None, "source_row": None, "item_code": None,
         "region": None, "price_period": None, "project_type": None, "structure_type": None},
    ]
    res = suggest(ROOT_INPUTS, base, dims=DIMS)
    assert res["suggestions"] == []
    bad = next(u for u in res["unresolved"] if u["cell"] == "1.建筑工程费!C7")
    assert bad["reason"] == "no_baseline"
    assert "多义" in bad["detail"]


# ---- cell 级歧义：三级查表的第一级也必须判歧义（对抗复核第 2 轮 #3 回归） ----

_AMB_CELL = "1.建筑工程费!C7"
# 刻意与模板里该行的 label（土石方工程）不同名：把匹配路径钉死在 cell 一级，
# 避免测试被 item_name 回退路径掩盖。
_AMB_NAME = "本测试自造·与模板行名刻意不同"


def _cell_dup(indicator_code: str, unit_cost: float, region: str | None) -> dict:
    """两条 (source_sheet, source_row) 完全相同、只差地区维与单方指标的基准行。"""
    return {
        "indicator_code": indicator_code, "item_name": _AMB_NAME, "item_code": None,
        "unit": "㎡", "unit_cost": unit_cost, "base_metric": None,
        "source_sheet": "1.建筑工程费", "source_row": 7,
        "region": region, "price_period": None,
        "project_type": None, "structure_type": None,
    }


def test_ambiguous_source_cell_is_refused_not_arbitrated():
    """同 (source_sheet, source_row) 两条基准、单方指标不一致 → 不出建议，落 unresolved。

    缺陷本体（对抗复核第 2 轮 #3）：`by_cell` 曾用 `setdefault` 静默取列表首行，
    而 item_code / item_name 两级都判歧义。DB 侧 (source_sheet, source_row) 无唯一
    约束（后端/sql/concept-indicator-schema-20260829.sql:96-100 唯一键只有
    uk_company_indicator_code），契约 §3.5 的 listConceptIndicatorBaselines 也未规定
    ORDER BY —— 灌入第二个价期或第二个地区就撞键，建议金额随 DB 行序变化。
    """
    base = [_cell_dup("GEN", 1000.0, None), _cell_dup("HZ", 2000.0, "杭州")]
    dims = {"region": "杭州", "price_period": None,
            "project_type": None, "structure_type": None}

    res = suggest(ROOT_INPUTS, base, dims=dims)
    assert _AMB_CELL not in {s["cell"] for s in res["suggestions"]}
    bad = next(u for u in res["unresolved"] if u["cell"] == _AMB_CELL)
    assert bad["reason"] == "no_baseline"
    assert "多义" in bad["detail"]


def test_ambiguous_source_cell_result_is_independent_of_row_order():
    """同一份基准、只把行序倒过来，结果必须逐字节相同。

    这是缺陷的可观测后果：修复前正序出 unit_cost=1000、倒序出 2000（差 2 倍），
    且 warnings 全空 —— 造价员看不出自己拿到的是哪一条。
    """
    base = [_cell_dup("GEN", 1000.0, None), _cell_dup("HZ", 2000.0, "杭州")]
    dims = {"region": "杭州", "price_period": None,
            "project_type": None, "structure_type": None}

    forward = suggest(ROOT_INPUTS, base, dims=dims)
    backward = suggest(ROOT_INPUTS, list(reversed(base)), dims=dims)
    assert forward == backward


def test_duplicate_source_cell_with_identical_unit_cost_still_suggests():
    """撞键但单方指标一致 → 不是歧义，照常出建议（与 item_code/item_name 两级同一口径）。

    边界必须钉住：否则「判歧义」很容易被改成「只要撞键就拒」，把同一条基准被
    两个价期重复登记的正常情形也一起毙掉。
    """
    base = [_cell_dup("GEN", 1000.0, None), _cell_dup("HZ", 1000.0, "杭州")]
    dims = {"region": "杭州", "price_period": None,
            "project_type": None, "structure_type": None}

    res = suggest(ROOT_INPUTS, base, dims=dims)
    hit = next(s for s in res["suggestions"] if s["cell"] == _AMB_CELL)
    assert hit["match"] == "cell"
    assert hit["unit_cost"] == 1000.0
    # baseline_ref 是审计指针，撞键时也不许随行序摆动（按 indicator_code 定序取小）
    assert hit["baseline_ref"] == "GEN"
    assert suggest(ROOT_INPUTS, list(reversed(base)), dims=dims) == res


# --------------------------------------------------------------- 其他契约点


def test_fee_items_are_passed_through_untouched(concept_baselines):
    """fee_rules 引擎的产出原样并进 fee 段，本模块不改写、不重算。"""
    fee = [{"item_id": "supervision_fee", "suggested": 128.4, "editable": True}]
    res = suggest(ROOT_INPUTS, concept_baselines, fee_items=fee, dims=DIMS)
    assert res["fee"] == fee


def test_unknown_input_key_surfaces_as_warning(concept_baselines):
    res = suggest(dict(ROOT_INPUTS, **{"经济技术指标!ZZ99": 1.0}), concept_baselines, dims=DIMS)
    assert any(w["code"] == "unknown_input" for w in res["warnings"])


def test_div_by_zero_noise_is_not_leaked_into_suggest(concept_baselines):
    """未填数量时求值器会刷出上百条 #DIV/0!，那是 compute 端的披露，
    查询接口不该被淹没——只透传 unknown_input。"""
    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    assert not [w for w in res["warnings"] if w["code"] == "div_by_zero"]


def test_tolerance_is_carried_by_the_range_not_by_a_server_side_checker():
    """O-22：`check_deviation()` 已删（全程无调用方，前端另有一份本地实现）。

    删掉的是**校核**，不是**阈值**：阈值仍由引擎单点下发，形态就是每条建议的
    `range = [suggested×(1−t), suggested×(1+t)]`。前端据此本地判 info/warn，
    不重复硬编码 0.20。这条守住"删了实现别把口径也删了"。
    """
    from zt.estimate import suggest as es

    assert not hasattr(es, "check_deviation"), "check_deviation 应已删除"
    assert es.DEFAULT_TOLERANCE == 0.20


def test_baseline_range_comes_from_samples_not_from_the_tolerance(concept_baselines):
    """WS10-P01：基准侧 range 由样本成员的 [min, max] 给出，单成员不给区间。

    原先每条恒为 ±DEFAULT_TOLERANCE —— 单样本的 ±20% 是凭空造的区间，
    看着像统计结论。构筑物块只有一个单体 → 每个叶子都是单成员 → [None, None]。
    """
    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    by = {s["cell"]: s for s in res["suggestions"]}
    for cell in ("1.建筑工程费!C43", "1.建筑工程费!C44", "1.建筑工程费!C45"):
        assert by[cell]["range"] == [None, None], cell
        assert by[cell]["range_basis"] == "single_value", cell
        assert by[cell]["evidence"]["n_values"] == 1
    c7 = by["1.建筑工程费!C7"]
    assert c7["range"] != [round(c7["suggested_cost"] * 0.8, 2), round(c7["suggested_cost"] * 1.2, 2)]


def test_result_is_deterministic(concept_baselines):
    """纯规则、零 LLM：同样输入两次必须逐字节一致。"""
    a = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    b = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    assert a == b


# --------------------------------------------- 双源冲突并列披露（O-07 / 裁决 3）

DUAL_SOURCE_CELLS = [f"5.工程建设其他费用!C{r}" for r in
                     (11, 12, 14, 16, 17, 18, 19, 20, 22, 23, 28, 29, 30)]

# WS10-P02：真策略下 5 表 23 格全是 lump_sum，双源仲裁这条保留分支走不到。
# 这批用例把 5 表临时改成可缩放（spec：用策略覆盖夹具），否则它们会静默变成空断言。
_SCALABLE_5 = None


def _scalable():
    global _SCALABLE_5
    if _SCALABLE_5 is None:
        _SCALABLE_5 = estimate_policy.with_scaling(
            estimate_policy.load_policy("gsyz_v1"), SHEET5_COST, "area")
    return _SCALABLE_5


# WS10-P03：三条带适用性的规则给在允许值上，否则它们在费率侧就被扣留、
# 不进双源分支（那是另一条用例 test_fee_rules_applicability 的事）
_APPLICABLE = {"project_city": "hangzhou_core", "project_nature": "production"}


def _fee_items():
    from zt.estimate import fee_rules as fr
    return fr.suggest_all({"工程费用": 12000.0}, dict(_APPLICABLE))["items"]


def test_thirteen_dual_source_cells_are_disclosed_side_by_side(concept_baselines):
    """其他费表的 13 个格**两个来源各出一套值**，必须并列交出来，不许代码替人选。

    此前谁生效取决于前端 forEach 的先后顺序 —— 让渲染顺序仲裁金额，
    是这条链路上最不该默默发生的一件事。
    """
    res = suggest(ROOT_INPUTS, concept_baselines, fee_items=_fee_items(), dims=DIMS,
                  policy=_scalable())
    conflicted = [s for s in res["suggestions"] if s.get("conflict")]
    assert sorted(s["cell"] for s in conflicted) == sorted(DUAL_SOURCE_CELLS)

    for s in conflicted:
        alt = s["alternative"]
        assert alt["source"] == "fee_rules"
        assert alt["item_id"], f"{s['cell']} 的费率侧没接上具体条目"
        # 归属裁决：费率优先（有文号可追溯）；但费率侧这次到底有没有数如实标出
        assert s["preferred_source"] == "fee_rules"
        assert s["preferred_available"] is (alt["suggested_cost"] is not None)
        # baseline 侧的值一分不少地留着 —— 不删任何一侧
        assert s["source"] == "baseline" and s["suggested_cost"] is not None

    codes = [w for w in res["warnings"] if w["code"] == "fee_cell_dual_source"]
    assert sorted(w["cell"] for w in codes) == sorted(DUAL_SOURCE_CELLS)


def test_alternative_carries_the_traceable_document_number(concept_baselines):
    """费率侧之所以被定为优先来源，是因为它有文号可追溯 —— 那个文号必须真的在响应里。"""
    res = suggest(ROOT_INPUTS, concept_baselines, fee_items=_fee_items(), dims=DIMS,
                  policy=_scalable())
    by_cell = {s["cell"]: s for s in res["suggestions"]}
    alt = by_cell["5.工程建设其他费用!C11"]["alternative"]
    assert alt["item_id"] == "bidding_agency_fee"
    assert alt["basis"]["source_ref"] == "计价格〔2002〕1980号"


def test_non_conflicting_cells_carry_no_alternative(concept_baselines):
    """只有一个来源的格不该被塞一个空的 alternative —— 前端会照着渲染出一个空对照列。"""
    res = suggest(ROOT_INPUTS, concept_baselines, fee_items=_fee_items(), dims=DIMS,
                  policy=_scalable())
    for s in res["suggestions"]:
        if s["cell"] not in DUAL_SOURCE_CELLS:
            assert s["conflict"] is False
            assert "alternative" not in s


def test_engine_does_not_hard_depend_on_fee_rules(concept_baselines, monkeypatch):
    """费率泳道缺席时正推算照跑，只是退化成"只有基准一个来源"（软降级）。"""
    import importlib

    real = importlib.import_module

    def _blocked(name, *a, **kw):
        if name == "zt.estimate.fee_rules":
            raise ImportError("simulated: fee_rules not merged")
        return real(name, *a, **kw)

    monkeypatch.setattr(importlib, "import_module", _blocked)
    # 用可缩放策略：只有 5 表走得到基准查表时，「没接费率就没有冲突格」这句话才有判据
    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS, policy=_scalable())
    assert res["coverage"]["suggested"] == 100       # 主产出不受影响（77 + 5 表 23）
    assert not [s for s in res["suggestions"] if s.get("conflict")]
    assert not [w for w in res["warnings"] if w["code"] == "fee_cell_dual_source"]
    # 没有费率规则可参照时，其他费的落空一律回到 no_baseline（不冒充 no_rule）
    assert "no_rule" not in {u["reason"] for u in res["unresolved"]}


# ------------------------------- 「本次用了哪一侧」是字段，不是推论（#132）

def _resolutions(concept_baselines, fee_items):
    res = suggest(ROOT_INPUTS, concept_baselines, fee_items=fee_items, dims=DIMS,
                  policy=_scalable())
    conflicted = [s for s in res["suggestions"] if s.get("conflict")]
    assert conflicted, "夹具没造出双源格，下面的断言全是空转（铁律 8）"
    return res, conflicted


def test_resolution_states_the_used_side_without_the_caller_deriving_it(concept_baselines,
                                                                        unsigned_ruleset):
    """#132：签署闸未解时 13 格全部回落基准侧，而响应里**没有一个键**说得出这件事。

    修之前调用方要 join 四个键（`source` / `preferred_source` / `preferred_available` /
    `alternative.suggested_cost`）才推得出结论，少读一个就把「已回落到基准侧」读成
    「按裁决 3 取了费率侧」。现在引擎直接下发 `resolution.used_source`。
    """
    res, conflicted = _resolutions(concept_baselines, _fee_items())
    assert len(conflicted) == 13
    for s in conflicted:
        r = s["resolution"]
        # 首选侧仍是费率侧（裁决 3 没变），但本次真正用的是基准侧
        assert r["preferred_source"] == "fee_rules"
        assert r["used_source"] == "baseline", s["cell"]
        assert r["is_fallback"] is True, s["cell"]
        # used_cost 必须真的等于它自称那一侧的金额，不能是个装饰性的键
        assert r["used_cost"] == s["suggested_cost"]
        assert s["alternative"]["suggested_cost"] is None
        # 两侧的值仍原样并列 —— 不删任何一侧
        assert s["source"] == "baseline" and s["suggested_cost"] is not None


def test_resolution_names_signoff_as_the_blocker_even_when_no_base_masks_it(concept_baselines,
                                                                           unsigned_ruleset):
    """🔴 本条是 #132 的核心：`no_base` 把「规则集没签」盖住了。

    `_withhold()` 明写「已有的不可用原因（no_base / manual_paradigm / …）不覆盖」。
    实测（工程费用=12000，就是前端第二段的真实调法）13 格里 6 格报 `no_base`：
    造价员照着去补「中标金额 / 建筑面积 / 受电容量」，补齐后原因才变成
    `ruleset_unsigned`，金额**照样 null** —— 可执行但无效的指示。
    `signoff_blocking` 必须在**同一条记录上**把这件事说清楚。
    """
    res, conflicted = _resolutions(concept_baselines, _fee_items())
    masked = [s for s in conflicted
              if s["alternative"]["unavailable_reason"] == "no_base"]
    # 夹具必须真的走到被掩盖的那条分支，否则这条用例是空转
    assert len(masked) == 6, [s["cell"] for s in masked]
    for s in masked:
        assert s["resolution"]["signoff_blocking"] is True, s["cell"]
        assert s["resolution"]["unavailable_reason"] == "no_base"
    # 另一条分支（原因就是签署闸本身）同样要标上，两条分支都被夹具覆盖
    direct = [s for s in conflicted
              if s["alternative"]["unavailable_reason"] == "ruleset_unsigned"]
    assert len(direct) == 7, [s["cell"] for s in direct]
    for s in direct:
        assert s["resolution"]["signoff_blocking"] is True, s["cell"]

    # 告警正文也要说破「补基数没用」+「本次展示的是基准侧」
    w = next(w for w in res["warnings"]
             if w["code"] == "fee_cell_dual_source" and w["cell"] == masked[0]["cell"])
    assert "补齐计费基数本次也不会出值" in w["message"]
    assert "展示与预填的是基准侧值" in w["message"]


_ALL_FEE_BASES = {
    "工程费用": 12000.0, "中标金额": 6000.0, "建安工程造价": 10000.0,
    "总建筑面积": 6.0, "建筑面积": 60000.0, "受电容量": 2000.0,
    "专利计费基数": 500.0,
}


def test_owner_release_fills_twelve_of_the_thirteen_cells_and_withholds_the_closure_gap(
        concept_baselines):
    """🔴 #159 的**落地判据**：仓主放行后，13 个双源格里 12 格真的拿到了费率侧金额，
    只有「勘察设计费」(C17) 仍被扣留。

    这一条同时钉死两件相反的事，缺哪一件这次改动都算没做到位：
      ① 放行确实生效 —— 否则 13 格照样全 null，issue #159 一个字没解决；
      ② 放行**不是**无差别放行 —— C17 的档界闭开性原表没写，档界处该用哪一档
         费率不可推测，给它一个金额就是在档界上编数（铁律 3）。

    夹具用全套基数（不是只给「工程费用」）：只给一个基数时 6 格会因 `no_base`
    没有值，那样 ① 这一半就成了空转 —— 分不清"没放行"和"没给基数"。
    """
    from zt.estimate import fee_rules as fr

    assert fr.is_signed(), (
        "费率规则集回到了未签署态。若这是有意撤销 #159 的放行，请把本条一并改掉："
        "它钉的是「放行后 12/13 格有值、C17 仍扣留」这条性质，不是环境前提。")

    items = fr.suggest_all(_ALL_FEE_BASES, dict(_APPLICABLE))["items"]
    res, conflicted = _resolutions(concept_baselines, items)
    assert len(conflicted) == 13, [s["cell"] for s in conflicted]

    priced = [s for s in conflicted if s["alternative"]["suggested_cost"] is not None]
    withheld = [s for s in conflicted if s["alternative"]["suggested_cost"] is None]
    assert len(priced) == 12, f"只有 {len(priced)} 格拿到费率侧金额：{[s['cell'] for s in priced]}"
    assert [s["cell"] for s in withheld] == ["5.工程建设其他费用!C17"], \
        [s["cell"] for s in withheld]
    assert withheld[0]["alternative"]["unavailable_reason"] == "band_closure_unconfirmed", (
        "C17 被扣留了，但原因不是「档界闭开性未确认」—— 那说明扣它的是别的东西"
        f"（{withheld[0]['alternative']['unavailable_reason']}），本条失去判据")

    for s in priced:
        r = s["resolution"]
        assert r["used_source"] == "fee_rules", s["cell"]
        assert r["used_cost"] == s["alternative"]["suggested_cost"], s["cell"]
        assert r["is_fallback"] is False, s["cell"]
        # 闸已解 ⇒ 不许再下发「先去签规则集」这条指示
        assert r["signoff_blocking"] is None, s["cell"]

    # C17 回落基准侧，且 signoff_blocking 不许是 True —— 规则集已经放行了，
    # 让人去催签规则集是个可执行但无效的指示（正是 #132 修掉的那种）
    assert withheld[0]["resolution"]["used_source"] == "baseline"
    assert withheld[0]["resolution"]["signoff_blocking"] is not True


def test_resolution_flips_to_fee_rules_once_the_fee_side_has_a_number(concept_baselines):
    """闸解开后 `used_source` 必须真的翻到费率侧 —— 否则这个字段是个常量。

    不改 JSON 里的 signoff_status（那是要造价员签字的东西），直接喂一份带金额的
    fee_items：`suggest()` 只读 `fee_items` 里的 `suggested`，与闸在哪一层无关。
    """
    items = _fee_items()
    for f in items:
        if f.get("target_cell") in DUAL_SOURCE_CELLS:
            f["suggested"] = 88.0
            f["unavailable_reason"] = None
    res, conflicted = _resolutions(concept_baselines, items)
    assert len(conflicted) == 13
    for s in conflicted:
        r = s["resolution"]
        assert r["used_source"] == "fee_rules", s["cell"]
        assert r["used_cost"] == 88.0
        assert r["is_fallback"] is False
        assert r["unavailable_reason"] is None
        # 出得了数就没有「补基数有没有用」这个问题 —— 不下发一个假的 False
        assert r["signoff_blocking"] is None
        # 基准侧仍在原位
        assert s["suggested_cost"] is not None and s["suggested_cost"] != 88.0


def test_resolution_covers_the_first_stage_where_fee_was_never_evaluated(concept_baselines,
                                                                        unsigned_ruleset):
    """第一段 suggest 不带 fee_bases（成本位还没收敛），`fee[]` 整个是空的。

    `covered_cells()` 是规则集的静态属性，所以 13 格照样标 conflict，
    只是费率侧连一条记录都没有 —— 这一段同样要说清「用的是基准侧」。
    """
    res, conflicted = _resolutions(concept_baselines, [])
    assert len(conflicted) == 13
    for s in conflicted:
        assert s["alternative"]["unavailable_reason"] == "fee_not_evaluated"
        assert s["resolution"]["used_source"] == "baseline"
        assert s["resolution"]["is_fallback"] is True
        # 「重调一次就有了」是错的：闸没解，带上基数也一样没有
        assert s["resolution"]["signoff_blocking"] is True


def test_resolution_does_not_invent_a_signoff_verdict_it_cannot_read(concept_baselines,
                                                                     monkeypatch,
                                                                     unsigned_ruleset):
    """问不出闸的状态时回 None，**不回 False** —— False 的语义是「已签署」。

    夹具要真的走到「有冲突格、但闸的状态读不出来」那一格，所以只让 `is_signed`
    炸，`covered_cells()` 照常工作；`_fee_rules_mod` 整个置 None 的话 13 格连
    conflict 都不成立，这条断言就落不到 `signoff_blocking` 上（空转）。
    """
    from zt.estimate import suggest as es

    items = _fee_items()  # 先取，取完再让 is_signed 炸

    def _boom(*a, **kw):
        raise RuntimeError("simulated: ruleset metadata unreadable")

    # 打在 `_fee_rules_mod()` 真正返回的那个对象上。写成
    # `from zt.estimate import fee_rules as fr; setattr(fr, ...)` 在整套跑时会漏 ——
    # test_estimate_lane_reconciliation 往 `sys.modules` 塞过一个同名桩再摘掉，
    # 包属性与 sys.modules 里的可以不是同一个对象（实测整套跑时本条断言拿到 True）。
    monkeypatch.setattr(es._fee_rules_mod(), "is_signed", _boom)
    assert es._fee_signoff_pending() is None

    res = suggest(ROOT_INPUTS, concept_baselines, fee_items=items, dims=DIMS,
                  policy=_scalable())
    conflicted = [s for s in res["suggestions"] if s.get("conflict")]
    assert len(conflicted) == 13, "夹具没造出双源格，下面的断言全是空转（铁律 8）"
    for s in conflicted:
        assert s["resolution"]["signoff_blocking"] is None, s["cell"]
        # 「用了哪一侧」不依赖闸的状态，照样说得出来
        assert s["resolution"]["used_source"] == "baseline"
    # 读不出闸 ⇒ 告警正文里不许出现「补齐计费基数本次也不会出值」这句断言性的话
    w = next(w for w in res["warnings"] if w["code"] == "fee_cell_dual_source")
    assert "补齐计费基数本次也不会出值" not in w["message"]


def test_no_rule_fires_only_when_both_sources_miss():
    """`no_rule` 的语义闸：基准库和费率规则**都**没有，才配叫「这一格谁也管不了」。

    ⚠ 实测记录（与阶段 I 契约的原始说法不符，见 PR 说明）：契约点名 C15/C24/C25/C26/C27
    应落 no_rule，前提是"基准又命不中"。但入仓的 224 条种子基准对
    5.工程建设其他费用 的 23 个成本位**全部命中**（实跑复验），所以在当前种子下
    这 5 格拿的是基准值，no_rule 一条也不会发。本用例用空 baselines 触发该分支，
    证明代码路径存在且判据正确 —— 而不是把它伪装成"生产上会发生"。
    """
    res = suggest(ROOT_INPUTS, [], dims=DIMS, fee_items=_fee_items(), policy=_scalable())
    no_rule = {u["cell"] for u in res["unresolved"] if u["reason"] == "no_rule"}
    other = [f"5.工程建设其他费用!C{r}" for r in (7, 8, 10, 13, 15, 21, 24, 25, 26, 27)]
    assert sorted(no_rule) == sorted(other)
    # 费率规则覆盖的 13 格：基准落空但另一个来源在，标 no_baseline + covered_by_fee_rule
    covered = [u for u in res["unresolved"] if u.get("covered_by_fee_rule")]
    assert sorted(u["cell"] for u in covered) == sorted(DUAL_SOURCE_CELLS)


# ------------------------------------------------------------------ O-08 软降级
#
# `required_fee_attrs` 与 `required_fee_bases` 同一条纪律：并行泳道给的 fee_rules
# 版本较老（没有 `required_attrs` 出口）时**如实出一条告警**，不许 AttributeError
# 把整个 suggest 打成 500，也不许静默回空 —— 静默回空的后果是前端不渲染下拉、
# 引擎按默认取费列算钱，全链路零信号。

def test_missing_required_attrs_exit_degrades_softly(monkeypatch, concept_baselines):
    """老版 fee_rules 没有 required_attrs → 一条 fee_attrs_spec_unsupported，不是 500。"""
    from zt.estimate import suggest as es
    from zt.estimate import fee_rules as real

    class _Old:
        """只少了 required_attrs 这一个出口，其余照旧。"""
        def __getattr__(self, name):
            if name == "required_attrs":
                raise AttributeError(name)
            return getattr(real, name)

    monkeypatch.setattr(es, "_fee_rules_mod", lambda: _Old())
    res = es.suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    assert res["required_fee_attrs"] == []
    assert "fee_attrs_spec_unsupported" in {w["code"] for w in res["warnings"]}, \
        "缺出口却零告警 —— 前端不渲染下拉、引擎按默认列算钱，全链路没有任何信号"


def test_absent_fee_rules_module_says_so_instead_of_silently_empty(monkeypatch,
                                                                   concept_baselines):
    from zt.estimate import suggest as es
    monkeypatch.setattr(es, "_fee_rules_mod", lambda: None)
    res = es.suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    assert res["required_fee_attrs"] == []
    assert "fee_rules_unavailable" in {w["code"] for w in res["warnings"]}


def test_no_rule_does_not_fire_under_the_real_seed(concept_baselines):
    """把 O-07 验收措辞的**前提**钉住：`no_rule` 在现行种子与真策略下不出现。

    WS10-P02 之后更进一步：5 表 23 格全是 lump_sum，根本不走基准查表 ——
    费率覆盖的 13 格落 baseline_not_scalable（看 fee[]），其余 10 格落 manual_required
    （带 manual_hint）。no_rule 这条分流只在策略把 5 表改成可缩放时可达，
    由下面那条用可缩放策略的用例钉住。
    """
    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    by_sheet = res["coverage"]["by_sheet"]["5.工程建设其他费用"]
    assert by_sheet == {"cost_inputs": 23, "suggested": 0, "unresolved": 23}
    assert not [u for u in res["unresolved"] if u["reason"] == "no_rule"], \
        "真策略下落出了 no_rule —— 5 表不该再走基准查表"
    sheet5 = [u for u in res["unresolved"] if u["cell"].startswith("5.工程建设其他费用!")]
    assert {u["reason"] for u in sheet5} == {"baseline_not_scalable", "manual_required"}
    c15 = next(u for u in sheet5 if u["cell"] == "5.工程建设其他费用!C15")
    assert c15["reason"] == "manual_required"
    assert c15["detail"] == "填出让合同价或挂牌价（万元）；划拨/本概算不计列填 0"


def test_no_rule_still_fires_when_both_sources_are_actually_absent(concept_baselines):
    """反向：把基准库抽空，C15/C24-C27 必须真的落 no_rule。

    没有这条，上一条在「no_rule 这条分流整个坏掉」时也会全绿 —— 那是误导性成功。
    """
    res = suggest(ROOT_INPUTS, [], dims=DIMS, policy=_scalable())
    no_rule = {u["cell"] for u in res["unresolved"] if u["reason"] == "no_rule"}
    for coord in ("C15", "C24", "C25", "C26", "C27"):
        assert f"5.工程建设其他费用!{coord}" in no_rule, \
            f"{coord} 没落 no_rule —— 验收点名的那几格分流坏了"
    assert all(u["covered_by_fee_rule"] is False
               for u in res["unresolved"] if u["reason"] == "no_rule")


def test_renamed_template_label_still_backlinks_by_the_recorded_before_name():
    """WS10-P14（issue #761）：模板把「海棉城市工程」改成「海绵城市工程」后，基准库 / 条目库里存的仍是
    原表名。没有源格的基准行走 item_name 这一级：按模板 fixes[static_text_fixes] 留痕的「修正前」
    精确别名再查一次 —— 不是模糊匹配，别的写法照样查不到（铁律 3）。

    变异：去掉别名（只按修正后的名字查）→ 该格落 no_baseline → 本条转红。
    """
    base = [{"indicator_code": "X-HM", "item_name": "海棉城市工程", "unit": "㎡",
             "unit_cost": 120.0, "source": "s1"}]
    res = suggest(ROOT_INPUTS, base, dims=DIMS)
    row = next((s for s in res["suggestions"] if s["cell"] == "4.室外及配套工程费!C13"), None)
    assert row is not None, [u for u in res["unresolved"] if u["cell"] == "4.室外及配套工程费!C13"]
    assert row["match"] == "item_name" and row["baseline_ref"] == "X-HM"
    # 对照：留痕里没有的写法不认
    res2 = suggest(ROOT_INPUTS, [dict(base[0], item_name="海面城市工程")], dims=DIMS)
    assert all(s["cell"] != "4.室外及配套工程费!C13" for s in res2["suggestions"])
