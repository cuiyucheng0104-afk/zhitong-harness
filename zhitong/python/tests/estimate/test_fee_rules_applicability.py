# 来源：engine-service/tests/test_fee_rules_applicability.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""WS10-P03（issue #722）：费率规则的适用性判断。

缺陷原形：`fee_rules._evaluate` 对 16 条规则一律求值。市政配套费的单价是杭州市区口径
（原表注「杭州市城市规划（不含余杭、萧山）」），却被套到义乌项目（3298.89 vs 真实
1199.60 万元）；联合试运转费、生产准备及开办费只对有工艺设备的生产性项目计列，仓储
项目照样出值，并在 suggest 里作为首选侧预填。

修法：数据加 `applicability`，`_evaluate` 在调用求值器之前检查 —— 只扣留金额，
不产生新金额，**不回落默认值**（默认杭州 / 默认生产性就是原缺陷本身）。
"""
from __future__ import annotations

import pytest

from zt.estimate import fee_rules as fr

APPLICABLE_IDS = {
    "municipal_infrastructure_fee": "project_city",
    "joint_commissioning_fee": "project_nature",
    "production_preparation_fee": "project_nature",
}
BASES = {"工程费用": 12000.0, "建筑面积": 60000.0}


def _items(attrs):
    return {s["item_id"]: s for s in fr.suggest_all(BASES, attrs)["items"]}


# ---------------------------------------------------------------- 数据自洽

def test_applicability_is_declared_exactly_on_the_three_items():
    declared = {i["item_id"]: [a["attr"] for a in i.get("applicability") or []]
                for i in fr._load()["items"] if i.get("applicability")}
    assert declared == {k: [v] for k, v in APPLICABLE_IDS.items()}


def test_allowed_is_a_subset_of_options():
    """allowed ⊆ options：否则某个允许值在下拉里选不出来，规则永远到不了「适用」态。"""
    for item in fr._load()["items"]:
        for rule in item.get("applicability") or []:
            values = {o["value"] for o in rule["options"]}
            assert rule["allowed"], item["item_id"]
            assert set(rule["allowed"]) <= values, item["item_id"]
            assert len(values) > len(rule["allowed"]), \
                f"{item['item_id']} 的选项全是允许值 —— 那这道闸永远不会判「不适用」"


# ---------------------------------------------------------------- 三态

def test_municipal_fee_unconfirmed_not_applicable_and_hangzhou_core():
    """未确认 → applicability_unconfirmed；浙江其他地市 → rule_not_applicable；杭州市区 → 出值。"""
    un = _items({})["municipal_infrastructure_fee"]
    assert un["suggested"] is None and un["range"] == [None, None]
    assert un["unavailable_reason"] == "applicability_unconfirmed"
    assert "fee_applicability_unconfirmed" in {w["code"] for w in un["warnings"]}

    na = _items({"project_city": "zhejiang_other"})["municipal_infrastructure_fee"]
    assert na["suggested"] is None
    assert na["unavailable_reason"] == "rule_not_applicable"
    msg = next(w["message"] for w in na["warnings"] if w["code"] == "fee_rule_not_applicable")
    assert "该标准适用于杭州市区，本项目按当地文件人工填报" in msg

    ok = _items({"project_city": "hangzhou_core"})["municipal_infrastructure_fee"]
    assert ok["suggested"] == pytest.approx(900.0)   # 60000 m² × 150 元/m² ÷ 10000
    assert ok["unavailable_reason"] is None


@pytest.mark.parametrize("item_id", ["joint_commissioning_fee", "production_preparation_fee"])
def test_production_items_follow_project_nature(item_id):
    assert _items({})[item_id]["unavailable_reason"] == "applicability_unconfirmed"
    na = _items({"project_nature": "non_production"})[item_id]
    assert na["suggested"] is None and na["unavailable_reason"] == "rule_not_applicable"
    assert _items({"project_nature": "production"})[item_id]["suggested"] is not None


def test_unknown_value_is_unconfirmed_not_silently_applicable():
    s = _items({"project_city": "hangzhou"})["municipal_infrastructure_fee"]
    assert s["unavailable_reason"] == "applicability_unconfirmed"
    assert "不认识的取值" in next(w["message"] for w in s["warnings"]
                             if w["code"] == "fee_applicability_unconfirmed")


def test_items_without_applicability_are_untouched():
    """适用性只扣留声明了它的 3 条，其余条目的金额与之前完全一样。"""
    a = _items({})
    b = _items({"project_city": "hangzhou_core", "project_nature": "production"})
    for item_id in set(a) - set(APPLICABLE_IDS):
        assert a[item_id]["suggested"] == b[item_id]["suggested"], item_id


def test_ungated_path_also_checks_applicability():
    """闸在 `_evaluate` 里，不在签署闸 `_gate` 里：内部入口同样不许给不适用的规则算钱。"""
    raw = fr._suggest_one_ungated("municipal_infrastructure_fee", 60000.0,
                                  {"project_city": "outside_zhejiang"})
    assert raw["suggested"] is None and raw["unavailable_reason"] == "rule_not_applicable"


# ---------------------------------------------------------------- 受控下拉

def test_required_attrs_carry_the_two_applicability_attrs_without_default():
    specs = {s["name"]: s for s in fr.required_attrs()}
    for name, items in (("project_city", {"municipal_infrastructure_fee"}),
                        ("project_nature", {"joint_commissioning_fee", "production_preparation_fee"})):
        assert name in specs, f"{name} 没作为受控属性下发，前端下拉出不来"
        s = specs[name]
        assert s["applicability"] is True
        # 没有默认值：默认杭州 / 默认生产性就是原缺陷
        assert s["default"] is None
        assert set(s["item_ids"]) == items
        assert all(set(o) == {"value", "label"} and o["label"] for o in s["options"])


# ---------------------------------------------------------------- 与 suggest 的集成

ROOT_INPUTS = {
    "经济技术指标!D4": 12000.0, "经济技术指标!D7": 5200.0, "经济技术指标!D8": 3100.0,
    "经济技术指标!D10": 8800.0, "经济技术指标!D11": 7600.0, "经济技术指标!D12": 6400.0,
    "经济技术指标!D13": 5900.0, "经济技术指标!D15": 4200.0, "经济技术指标!D16": 3300.0,
    "经济技术指标!D19": 260.0, "经济技术指标!D20": 140.0,
}


def test_cf_s3_shaped_suggest_does_not_prefill_c22_from_either_side(concept_baselines):
    """集成：Cf_S3 形状（带基数、不选所在地 / 项目性质）下，C22 / C28 / C30 两侧都不出值。

    基准侧那个值同样没回答「这条费用本项目该不该计」，拿它顶上就是把「杭州标准套义乌」
    换成「样本包干额套义乌」。所以这三格落 unresolved，且 fee[] 里对应条目 suggested=None。
    """
    from zt.estimate.suggest import suggest

    fee = fr.suggest_all(dict(BASES, 中标金额=6000.0), {})["items"]
    res = suggest(ROOT_INPUTS, concept_baselines, fee_items=fee,
                  dims={"project_type": "房屋建筑"})
    cells = {"5.工程建设其他费用!C22", "5.工程建设其他费用!C28", "5.工程建设其他费用!C30"}
    assert not cells & {s["cell"] for s in res["suggestions"]}
    un = {u["cell"]: u for u in res["unresolved"] if u["cell"] in cells}
    assert set(un) == cells
    assert {u["reason"] for u in un.values()} == {"applicability_unconfirmed"}
    assert all(u["covered_by_fee_rule"] for u in un.values())
    assert all(f["suggested"] is None for f in res["fee"] if f.get("target_cell") in cells)


def test_applicability_blocks_the_baseline_side_even_when_it_is_scalable(concept_baselines):
    """把 5 表临时改成可缩放（双源分支可达）时，适用性扣留的格仍然两侧都不出值。

    这条造的是「基准侧有值、费率侧因适用性为空」的形状 —— 修法之前这一格会回落到
    基准侧并被预填（resolution.used_source = baseline）。
    """
    from zt.estimate import policy as estimate_policy
    from zt.estimate.suggest import suggest

    pol = estimate_policy.with_scaling(
        estimate_policy.load_policy("gsyz_v1"),
        [f"5.工程建设其他费用!C{r}" for r in range(7, 31)], "area")
    fee = fr.suggest_all(BASES, {"project_city": "zhejiang_other"})["items"]
    res = suggest(ROOT_INPUTS, concept_baselines, fee_items=fee,
                  dims={"project_type": "房屋建筑"}, policy=pol)
    by = {s["cell"]: s for s in res["suggestions"]}
    # 前置：可缩放策略下 5 表确实出了基准侧值（否则下面的断言是空转）
    assert "5.工程建设其他费用!C14" in by
    c22 = next(u for u in res["unresolved"] if u["cell"] == "5.工程建设其他费用!C22")
    assert c22["reason"] == "rule_not_applicable"
    assert "5.工程建设其他费用!C22" not in by
