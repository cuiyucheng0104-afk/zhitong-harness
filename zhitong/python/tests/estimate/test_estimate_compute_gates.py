# 来源：engine-service/tests/test_estimate_compute_gates.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""WS10-P04 / P05 / P02 / P08（issue #722）：compute 的面积闸、单体对账、土地费与占地披露。

P04 缺陷：Ae_K、Ce_K 的总建筑面积 = 0，C47 = 1974.22 / 3748.84 万元（金额全部来自
     「室外面积 = 用地面积」的室外成本），接口 200 出表。必填闸只查键在不在（0 也算已填），
     全零闸只挡精确的 C47 == 0。
P05 缺陷：E3_B 原文总建筑面积 256944.18，槽位合计 128617.91（少 50%），compute 仍 200。
P02：请求里没有 C15 键时 compute 不吭声，土地费按 0 计入静态投资。
P08：占地面积为 0 时室外面积（D17 = D4 − D14）按整块用地计，多算约 86%。
"""
from __future__ import annotations

from io import BytesIO

import pytest
from openpyxl import load_workbook
from tests.estimate.fixtures.endpoint import HEADERS, client  # zt 改动：旧端点的转接




URL = "/engine/estimate/compute"

ROOT = {
    "经济技术指标!D4": 12000.0, "经济技术指标!D7": 5200.0, "经济技术指标!D8": 3100.0,
    "经济技术指标!D10": 8800.0, "经济技术指标!D11": 7600.0, "经济技术指标!D12": 6400.0,
    "经济技术指标!D13": 5900.0, "经济技术指标!D15": 4200.0, "经济技术指标!D16": 3300.0,
    "经济技术指标!D19": 260.0, "经济技术指标!D20": 140.0,
}
SLOT_SUM = 5200.0 + 3100.0 + 8800.0 + 7600.0 + 6400.0 + 5900.0       # = 经济技术指标!D5 = 37000
OUTDOOR = {"4.室外及配套工程费!C7": 800.0}                             # 非零室外成本
COST = {"1.建筑工程费!C7": 130.0, "5.工程建设其他费用!C15": 2000.0}


def _post(inputs, **kw):
    body = {"inputs": inputs, "render": False}
    body.update(kw)
    return client.post(URL, headers=HEADERS, json=body)


def _zero_area_inputs() -> dict:
    """Ae_K 形状：11 个必填键都在（必填闸照过），单体面积全 0，用地面积与室外成本非零。"""
    inp = {k: 0.0 for k in ROOT}
    inp["经济技术指标!D4"] = 12000.0
    inp.update(OUTDOOR)
    return inp


# =================================================================== P04 面积闸

def test_zero_total_area_is_422_even_with_outdoor_costs():
    """总建筑面积 = 0 → 422，哪怕 C47 ≠ 0。

    夹具必须带**非零室外成本**：否则 C47 = 0，全零闸先把它挡了，本闸的判据根本到不了。
    变异：删掉面积闸 → 200，本条转红。
    """
    r = _post(_zero_area_inputs())
    assert r.status_code == 422, r.text
    assert "总建筑面积" in r.json()["detail"]
    assert "第 2 步" in r.json()["detail"]


def test_positive_total_area_passes():
    r = _post(dict(ROOT, **COST))
    assert r.status_code == 200, r.text
    assert "area_gate_absent" not in {w["code"] for w in r.json()["warnings"]}


def test_area_gate_runs_before_the_all_zero_gate():
    """两闸顺序钉死：面积为 0 且成本全空时，报的是面积闸，不是全零闸。

    全零闸的文案叫人去填费用明细 —— 面积都是 0 时那是错误的指示。
    """
    inp = {k: 0.0 for k in ROOT}
    inp["经济技术指标!D4"] = 12000.0
    r = _post(inp)
    assert r.status_code == 422
    assert "总建筑面积" in r.json()["detail"]
    assert "全零" not in r.json()["detail"]


def test_template_without_area_gate_is_disclosed(monkeypatch):
    from zt.estimate import service as api
    from zt.estimate import policy as estimate_policy

    real = estimate_policy.load_policy("gsyz_v1")
    monkeypatch.setattr(api.estimate_policy, "load_policy",
                        lambda code="gsyz_v1": {k: v for k, v in real.items() if k != "area_gate"})
    r = _post(dict(ROOT, **COST))
    assert r.status_code == 200, r.text
    assert "area_gate_absent" in {w["code"] for w in r.json()["warnings"]}


# =================================================================== P05 单体对账

def test_area_mismatch_requires_ack():
    """槽位合计与原文总建筑面积差 >1%：未确认 → 422；确认并写理由 → 200 + 需复核告警。

    变异一：删对账闸 → 未确认也 200，第一段转红；
    变异二：删放行口（确认也 422）→ 第二段转红。
    """
    src = SLOT_SUM * 2                                   # 原文是槽位合计的两倍（E3_B 形状）
    r = _post(dict(ROOT, **COST), area_checks={"gross_building_area": src})
    assert r.status_code == 422, r.text
    assert "相差" in r.json()["detail"] and "单体归位" in r.json()["detail"]

    ok = _post(dict(ROOT, **COST), area_checks={"gross_building_area": src},
               acknowledged_checks=[{"code": "area_total_mismatch",
                                     "reason": "原文总面积含架空层与人防，模板不计"}])
    assert ok.status_code == 200, ok.text
    w = next(w for w in ok.json()["warnings"] if w["code"] == "area_mismatch_acknowledged")
    assert "原文总面积含架空层与人防" in w["message"]


def test_area_within_one_percent_needs_no_ack():
    r = _post(dict(ROOT, **COST), area_checks={"gross_building_area": SLOT_SUM * 1.009})
    assert r.status_code == 200, r.text
    assert "area_mismatch_acknowledged" not in {w["code"] for w in r.json()["warnings"]}


@pytest.mark.parametrize("ack", [
    [{"code": "area_total_mismatch", "reason": "  "}],      # 理由为空
    [{"code": "area_total_mismatch"}],                       # 没有理由
    [{"code": "something_else", "reason": "x"}],             # 不认识的确认项
    ["area_total_mismatch"],                                 # 形状不对
])
def test_ack_without_reason_or_unknown_code_is_422(ack):
    r = _post(dict(ROOT, **COST), area_checks={"gross_building_area": SLOT_SUM * 2},
              acknowledged_checks=ack)
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("bad", [
    {"area_checks": {"gross_building_area": True}},
    {"area_checks": {"gross_building_area": -1}},
    {"slot_labels": {"经济技术指标!D4": "用地"}},              # 不是槽位
    {"slot_labels": {"经济技术指标!D10": ""}},
    {"slot_labels": {"经济技术指标!D10": "a\nb"}},
    {"slot_labels": {"经济技术指标!D10": "x" * 41}},
])
def test_compute_context_is_validated(bad):
    assert _post(dict(ROOT, **COST), **bad).status_code == 422


def test_slot_labels_replace_the_sample_names_in_the_xlsx():
    """传 slot_labels 后，估概算总表!B12 等名称格写的是传入名称，不再是样本楼名「1#楼工程」。"""
    r = client.post(URL, headers=HEADERS, json={
        "inputs": dict(ROOT, **COST), "render": True,
        "slot_labels": {"经济技术指标!D10": "5#仓库", "经济技术指标!D13": "=HYPERLINK(\"x\")"}})
    assert r.status_code == 200, r.text
    import base64
    wb = load_workbook(BytesIO(base64.b64decode(r.json()["xlsx_base64"])))
    assert wb["估概算总表"]["B12"].value == "5#仓库工程"
    assert wb["经济技术指标"]["B10"].value == "5#仓库"
    assert wb["1.建筑工程费"]["B24"].value == "5#仓库工程"
    assert wb["2.安装工程费"]["B22"].value == "5#仓库工程"
    # 公式注入被中和：以 = 开头的名称写成文本（前缀 '），不会被 Excel 当公式执行
    assert str(wb["估概算总表"]["B21"].value).startswith("'=")
    # 没传的槽位保持模板原名
    assert wb["估概算总表"]["B15"].value == "2#楼工程"


# =================================================================== P02 / P08 披露

def test_land_cost_absent_is_disclosed():
    """请求里没有 C15 键 → land_cost_unfilled；显式填 0（划拨 / 不计列）→ 不告警。"""
    r = _post(dict(ROOT, **{"1.建筑工程费!C7": 130.0}))
    assert r.status_code == 200, r.text
    assert "land_cost_unfilled" in {w["code"] for w in r.json()["warnings"]}
    r0 = _post(dict(ROOT, **{"1.建筑工程费!C7": 130.0, "5.工程建设其他费用!C15": 0.0}))
    assert "land_cost_unfilled" not in {w["code"] for w in r0.json()["warnings"]}


def test_missing_footprint_warns_outdoor_equals_site():
    """占地面积 D15 / D16 都是 0 → footprint_missing（室外面积按整块用地计）。

    变异：删掉这条披露 → 本条转红。夹具的用地面积必须 > 0，否则判据不成立。
    """
    inp = dict(ROOT, **COST)
    inp["经济技术指标!D15"] = 0.0
    inp["经济技术指标!D16"] = 0.0
    r = _post(inp)
    assert r.status_code == 200, r.text
    w = [w for w in r.json()["warnings"] if w["code"] == "footprint_missing"]
    assert len(w) == 1 and "12000" in w[0]["message"]
    ok = _post(dict(ROOT, **COST))
    assert "footprint_missing" not in {w["code"] for w in ok.json()["warnings"]}
