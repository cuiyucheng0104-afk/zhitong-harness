# 来源：engine-service/tests/test_estimate_policy.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""WS10-P01 / P02（issue #722）：模板策略驱动的基准推算口径。

P01 缺陷：推算基准只来自一个样本工作簿，按 (source_sheet, source_row) 位置对号后等比放大；
     仓储项目被套上幕墙和精装修；每条建议的区间恒为 ±20%；前端全量自动预填。
P02 缺陷：土地费、配套工程、其他费的「单方」实为样本包干额 ÷ 样本面积（17 万㎡），
     却按本项目总建筑面积放大 —— 本地复现 C15 = 35282.26 万元，真实 20703.78。

夹具纪律（CLAUDE.md §5.2）：每条用例的夹具都要够得到它声称钉住的那条分支 ——
「3 个来源才恢复预填」必须真的造 3 个 source；「位置键 vs 语义键」必须用三栋单方不同的格。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from zt.estimate import policy as estimate_policy
from zt.estimate.engine import load_template
from zt.estimate.suggest import suggest

ROOT_INPUTS = {
    "经济技术指标!D4": 12000.0, "经济技术指标!D7": 5200.0, "经济技术指标!D8": 3100.0,
    "经济技术指标!D10": 8800.0, "经济技术指标!D11": 7600.0, "经济技术指标!D12": 6400.0,
    "经济技术指标!D13": 5900.0, "经济技术指标!D15": 4200.0, "经济技术指标!D16": 3300.0,
    "经济技术指标!D19": 260.0, "经济技术指标!D20": 140.0,
}
DIMS = {"region": None, "price_period": None, "project_type": "房屋建筑", "structure_type": None}
CURTAIN = ["1.建筑工程费!C27", "1.建筑工程费!C33", "1.建筑工程费!C39"]
FINISH = ["1.建筑工程费!C13", "1.建筑工程费!C22", "1.建筑工程费!C28",
          "1.建筑工程费!C34", "1.建筑工程费!C40", "1.建筑工程费!C45"]
POLICY_FILE = (Path(__file__).resolve().parents[2] / "zt" / "estimate" / "data"
               / "estimate_templates" / "gsyz_v1.policy.json")


def _by_cell(res):
    return {s["cell"]: s for s in res["suggestions"]}


def _unresolved(res):
    return {u["cell"]: u for u in res["unresolved"]}


# =================================================================== P01 · 单样本

def test_real_seed_yields_reference_only_everywhere_and_says_so(concept_baselines):
    """真种子 224 行只来自一个工作簿（source 全为 gsyz_v1）→ 每条建议都只是参考（D47）。

    变异：把 reference_only 的阈值判断改成恒 False → 本条转红（前端会把单样本值全量预填）。
    """
    assert {b["source"] for b in concept_baselines} == {"gsyz_v1"}, "前置：真种子只有一个来源"
    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    assert res["suggestions"], "前置：真种子上必须有建议，否则下面是空断言"
    assert all(s["reference_only"] is True for s in res["suggestions"])
    assert all(s["evidence"]["n_sources"] == 1 for s in res["suggestions"])
    assert res["coverage"]["reference_only"] == len(res["suggestions"])
    codes = [w["code"] for w in res["warnings"]]
    assert codes.count("baseline_single_sample") == 1


def _three_source_rows(cell_row: int, costs: tuple[float, float, float]) -> list[dict]:
    """同一语义键（1.建筑工程费/above_ground/建筑工程）下 3 个不同来源的行。"""
    return [{
        "indicator_code": f"S{i}-R{cell_row}", "item_name": "建筑工程", "item_code": None,
        "unit": "㎡", "unit_cost": c, "base_metric": None,
        "source": f"sample_{i}", "source_sheet": "1.建筑工程费", "source_row": cell_row,
        "region": None, "price_period": None, "project_type": "房屋建筑", "structure_type": None,
    } for i, c in enumerate(costs)]


def test_three_sources_give_median_and_min_max_and_are_prefillable():
    """3 个不同来源 → 中位数 + [min, max] 区间 + 不再是参考值。

    夹具必须真有 3 个 source 才到得了「恢复预填」那条分支：只造 2 个的话
    reference_only 恒 True，本条就是空断言。
    """
    rows = _three_source_rows(25, (1600.0, 1800.0, 2400.0))
    res = suggest(ROOT_INPUTS, rows, dims=DIMS)
    by = _by_cell(res)
    # 语义键归并：三栋楼的「建筑工程」都拿到同一个样本池（C25 / C31 / C37）
    for cell, qty in (("1.建筑工程费!C25", 8800.0), ("1.建筑工程费!C31", 7600.0),
                      ("1.建筑工程费!C37", 6400.0)):
        s = by[cell]
        assert s["unit_cost"] == 1800.0, cell
        assert s["suggested_cost"] == round(1800.0 * qty / 10000.0, 4)
        assert s["range"] == [round(1600.0 * qty / 10000.0, 2), round(2400.0 * qty / 10000.0, 2)]
        assert s["range_basis"] == "sample_min_max"
        assert s["reference_only"] is False
        assert s["evidence"]["n_sources"] == 3
        assert s["baseline_ref"] == "S1-R25"          # 最接近中位数的那一条
    assert "baseline_single_sample" not in {w["code"] for w in res["warnings"]}


def test_two_sources_are_still_reference_only():
    rows = _three_source_rows(25, (1600.0, 1800.0, 2400.0))[:2]
    s = _by_cell(suggest(ROOT_INPUTS, rows, dims=DIMS))["1.建筑工程费!C25"]
    assert s["reference_only"] is True and s["evidence"]["n_sources"] == 2


def test_curtain_wall_cells_share_the_semantic_median(concept_baselines):
    """1.建筑工程费!C27 / C33 / C39（三栋楼的幕墙）单方相等，且等于种子 R27/R33/R39 的中位数。

    变异：退回位置键（(source_sheet, source_row) 对号）→ 三格单方分别是 357.14 / 350 / 400，转红。
    """
    seed = {b["source_row"]: b["unit_cost"] for b in concept_baselines
            if b["source_sheet"] == "1.建筑工程费" and b["source_row"] in (27, 33, 39)}
    assert len(set(seed.values())) == 3, "前置：三栋的样本单方互不相同，位置键与语义键才分得开"
    median = sorted(seed.values())[1]
    by = _by_cell(suggest(ROOT_INPUTS, concept_baselines, dims=DIMS))
    got = {c: by[c]["unit_cost"] for c in CURTAIN}
    assert set(got.values()) == {round(median, 4)}, got
    assert all(by[c]["match"] == "semantic" for c in CURTAIN)


def test_structure_block_single_member_has_no_range(concept_baselines):
    by = _by_cell(suggest(ROOT_INPUTS, concept_baselines, dims=DIMS))
    for cell in ("1.建筑工程费!C43", "1.建筑工程费!C44", "1.建筑工程费!C45",
                 "2.安装工程费!C50", "2.安装工程费!C54"):
        assert by[cell]["range"] == [None, None], cell
        assert by[cell]["range_basis"] == "single_value", cell


def test_semantic_key_ambiguity_keeps_the_old_criterion():
    """同语义键下单方不同且维度不同 → 多义，不猜（保留「灌了第二个价期而 dims 未收窄」的判据）。"""
    rows = _three_source_rows(25, (1600.0, 1800.0, 2400.0))
    rows[2]["price_period"] = "2026Q3"
    res = suggest(ROOT_INPUTS, rows, dims=DIMS)
    assert "1.建筑工程费!C25" not in _by_cell(res)
    u = _unresolved(res)["1.建筑工程费!C25"]
    assert u["reason"] == "no_baseline" and "多义" in u["detail"]


# =================================================================== P01 · 业态

def test_warehouse_drops_curtain_wall_and_fit_out(concept_baselines):
    """业态 = 仓储物流 → 9 个幕墙 / 精装修格落 not_applicable_for_use，不出参考值（D48）。

    变异：删掉业态屏蔽 → 9 格回到 suggestions，本条转红。
    """
    dims = dict(DIMS, building_function="warehouse_logistics")
    res = suggest(ROOT_INPUTS, concept_baselines, dims=dims)
    by, un = _by_cell(res), _unresolved(res)
    for cell in CURTAIN + FINISH:
        assert cell not in by, cell
        assert un[cell]["reason"] == "not_applicable_for_use", cell
        assert "仓储物流" in un[cell]["detail"]
    assert "building_use_unconfirmed" not in {w["code"] for w in res["warnings"]}
    # 住宅不受影响：同一批格照出参考值
    by_res = _by_cell(suggest(ROOT_INPUTS, concept_baselines,
                              dims=dict(DIMS, building_function="residential")))
    assert all(c in by_res for c in CURTAIN + FINISH)


def test_missing_building_function_is_disclosed(concept_baselines):
    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    assert "building_use_unconfirmed" in {w["code"] for w in res["warnings"]}


def test_block_kinds_cover_exactly_every_single_project_row():
    """块表里每一个单项工程行（level 2）恰好命中一条 block_kinds 规则 —— 不多不少。

    漏一行：那一块的叶子退成「{表}/{块名}/{叶子}」独立成键，不并入任何 kind；
    命中两条：同一块归到两个 kind，语义键不唯一。两种都要在这里红。
    """
    pol = estimate_policy.load_policy("gsyz_v1")
    rows = estimate_policy.block_rows("gsyz_v1")
    assert len(rows) == 12, rows
    for sheet, row, label in rows:
        hits = [r["kind"] for r in pol["block_kinds"]["rules"]
                if __import__("re").search(r["pattern"], label)]
        assert len(hits) == 1, (sheet, row, label, hits)
    # 每条规则至少命中一行（否则规则是死的）
    kinds = {estimate_policy.block_kind_of(pol, label) for _, _, label in rows}
    assert kinds == {r["kind"] for r in pol["block_kinds"]["rules"]}


# =================================================================== P02 · 包干额

LUMP_SUM = ([f"4.室外及配套工程费!C{r}" for r in range(27, 32)]
            + [f"5.工程建设其他费用!C{r}" for r in (7, 8, *range(10, 31))])


def test_lump_sum_cells_never_get_area_scaled_baseline(concept_baselines):
    """28 个包干额格不在 suggestions；费率覆盖的 13 格 baseline_not_scalable，其余 manual_required。

    变异：删掉 scaling 判断（lump_sum 照常走基准查表）→ C15 回到 suggestions，本条转红。
    """
    from zt.estimate import fee_rules as fr

    res = suggest(ROOT_INPUTS, concept_baselines, dims=DIMS)
    by, un = _by_cell(res), _unresolved(res)
    assert not set(LUMP_SUM) & set(by)
    covered = fr.covered_cells()
    for cell in LUMP_SUM:
        u = un[cell]
        if cell in covered:
            assert u["reason"] == "baseline_not_scalable" and u["covered_by_fee_rule"] is True, cell
            assert "fee[]" in u["detail"]
        else:
            assert u["reason"] == "manual_required" and u["covered_by_fee_rule"] is False, cell
            assert u["detail"], cell
    assert un["5.工程建设其他费用!C15"]["detail"] == "填出让合同价或挂牌价（万元）；划拨/本概算不计列填 0"
    assert un["4.室外及配套工程费!C27"]["detail"] == "按配套合同或报价填（万元）"
    assert sum(1 for c in LUMP_SUM if c in covered) == 13


def test_every_cost_cell_has_explicit_scaling(concept_baselines):
    """模板每个成本位都显式归入 area / lump_sum 之一，且 lump_sum 集合与种子数据自洽。

    自洽判据：种子里「单方不是整数、单方 × 17（样本总建筑面积 17 万㎡）却是整数」的成本格
    正是样本包干额 ÷ 样本面积的痕迹 —— 这批格必须恰好是 lump_sum，多一格少一格都红。
    """
    pol = estimate_policy.load_policy("gsyz_v1")
    tpl = load_template("gsyz_v1")
    cost = {i["cell"] for i in tpl["inputs"] if i["kind"] == "cost"}
    lump = set(estimate_policy.lump_sum_cells(pol))
    assert lump <= cost, sorted(lump - cost)
    assert all(estimate_policy.scaling_of(pol, c) in ("area", "lump_sum") for c in cost)
    assert lump == set(LUMP_SUM)

    def _is_lump_trace(u):
        return abs(u - round(u)) > 1e-6 and abs(u * 17 - round(u * 17)) < 1e-3

    traced = {f"{b['source_sheet']}!C{b['source_row']}" for b in concept_baselines
              if _is_lump_trace(b["unit_cost"])} & cost
    assert traced == lump, (sorted(traced - lump), sorted(lump - traced))


def test_with_scaling_override_does_not_mutate_the_cached_policy():
    pol = estimate_policy.load_policy("gsyz_v1")
    before = copy.deepcopy(pol)
    over = estimate_policy.with_scaling(pol, ["5.工程建设其他费用!C15"], "area")
    assert "5.工程建设其他费用!C15" not in estimate_policy.lump_sum_cells(over)
    assert pol == before


# =================================================================== 策略文件本身

def test_policy_file_is_valid_json_and_versioned():
    doc = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    assert doc["template_code"] == "gsyz_v1"
    assert doc["policy_version"]
    assert doc["min_sources_for_prefill"] == 3


@pytest.mark.parametrize("bad", ["../gsyz_v1", "gsyz_v1.policy", "a/b", ""])
def test_load_policy_rejects_unsafe_codes(bad):
    from zt.estimate.engine import EstimateTemplateError
    with pytest.raises(EstimateTemplateError):
        estimate_policy.load_policy(bad)


def test_template_endpoint_ships_policy_options_from_the_server():
    """前端业态下拉的选项只来自服务端（GET /engine/estimate/template 的 policy）。"""
    # zt 改动：经 template 子命令的服务函数（旧版经 GET /engine/estimate/template）
    from zt.estimate import service

    body = service.template("gsyz_v1")
    pol = body["policy"]
    assert pol["min_sources_for_prefill"] == 3
    # WS29-d：策略加了楼号表锚点、输出预算、建筑密度提示项，版本跟着升
    assert pol["policy_version"] == "gsyz_v1.policy.2026-10-06"
    values = [o["value"] for o in pol["building_functions"]]
    assert "warehouse_logistics" in values and "industrial_plant" in values
    assert [s["cell"] for s in pol["slots"]] == [
        "经济技术指标!D7", "经济技术指标!D8", "经济技术指标!D10",
        "经济技术指标!D11", "经济技术指标!D12", "经济技术指标!D13"]
    assert pol["land_cost_cell"] == "5.工程建设其他费用!C15"
    assert pol["footprint"] == {"site_cell": "经济技术指标!D4",
                                "input_cells": ["经济技术指标!D15", "经济技术指标!D16"]}


# =================================================================== WS29-d（issue #1010）

def test_extract_policy_has_building_table_anchors_budget_and_density():
    """楼号表锚点、输出预算 6000（D-R119）、建筑密度提示项都在策略文件里，代码不写死。"""
    pol = estimate_policy.load_policy("gsyz_v1")
    for a in ("楼号", "栋号", "单体", "子项"):
        assert a in estimate_policy.extract_anchors(pol)
    assert estimate_policy.extract_max_tokens(pol) == 6000
    d = estimate_policy.density_check(pol)
    assert d is not None and d["key"] == "building_density" and d["hint_for"] == "footprint"
    # 密度是百分数提示项，不是总量：不进 check_values 那一组
    assert "building_density" not in [c["key"] for c in estimate_policy.quantity_checks(pol)]
    assert "building_density" in [c["key"] for c in estimate_policy.extract_checks(pol)]


def test_extract_max_tokens_falls_back_when_the_policy_has_none():
    assert estimate_policy.extract_max_tokens({}) == estimate_policy.DEFAULT_EXTRACT_MAX_TOKENS == 6000
    assert estimate_policy.extract_max_tokens({"extract_max_tokens": True}) == 6000
    assert estimate_policy.extract_max_tokens({"extract_max_tokens": 4000}) == 4000
    assert estimate_policy.density_check({}) is None
