# 来源：engine-service/tests/test_estimate_lane_reconciliation.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""两条泳道对同一份 estimate 端点的独立重写 —— 合并后特性必须全在（对抗复核第 2 轮 #2）。

背景（实测）：`feat/phase-i-engine-core-fix1` 与 `feat/phase-i-api-fix1` 各自独立重写了
`app/api/estimate.py` 与 `app/schemas.py`，`git merge` 在这两个文件上硬冲突；且两侧携带
的是**互斥的上一轮修复**：

    engine 泳道独有：compute 的全零闸（static_total==0 → 422）
                     suggest 的 with_deviation → deviations/tolerance 出口
                     （⚠ 其中 with_deviation/deviations 已按 O-22 **有意删除**，
                       只留 tolerance；见 test_suggest_out_schema_keeps_the_tolerance_single_source）
    api  泳道独有：compute 的 optional_input_missing 披露
                     suggest 的 fee_bases_absent 披露、fee_bases/fee_attrs 真被消费
                     template 的 optional_input_specs 录入元数据

人工二选一必丢一侧。本文件钉死"并集还在"，让任何一次"挑一边留下"的合并当场转红。

另钉一条 `git merge` 自己制造的坑：两侧的 suggest 端点函数**同名同路径**，自动合并把
它们并成了两个函数注册同一条路由 —— Python 后定义的覆盖前者、FastAPI 路由表里出现两
条重复项，engine 侧的偏离校核出口被静默吃掉，而全部既有用例照样全绿。
所以"路由不重复"必须单独有断言。
"""
from __future__ import annotations

import inspect
import sys
import types
from pathlib import Path

import pytest



from zt.estimate import service as estimate_api  # noqa: E402  # zt 改动：旧端点模块 → 接线层
from tests.estimate.fixtures.endpoint import HEADERS, client  # zt 改动：旧端点的转接


_TPL = (Path(__file__).resolve().parents[2] / "zt" / "estimate" / "data"
        / "estimate_templates" / "gsyz_v1.json")
pytestmark = pytest.mark.skipif(
    not _TPL.is_file(), reason="gsyz_v1.json 属引擎泳道，未合并时跳过")

ROOT_INPUTS = {
    "经济技术指标!D4": 12000.0, "经济技术指标!D7": 5200.0, "经济技术指标!D8": 3100.0,
    "经济技术指标!D10": 8800.0, "经济技术指标!D11": 7600.0, "经济技术指标!D12": 6400.0,
    "经济技术指标!D13": 5900.0, "经济技术指标!D15": 4200.0, "经济技术指标!D16": 3300.0,
    "经济技术指标!D19": 260.0, "经济技术指标!D20": 140.0,
}


# ------------------------------------------------------- git merge 自己制造的坑

def test_each_service_entry_is_defined_once():
    """zt 改动：没有路由表；改为同一份源码里每个入口函数只定义一次（重复 def 会静默覆盖前者）。"""
    src = Path(inspect.getsourcefile(estimate_api)).read_text(encoding="utf-8")
    for name in ("suggest", "compute", "extract_prepare", "extract_finalize", "template"):
        assert src.count(f"\ndef {name}(") == 1, f"{name} 定义了不止一次"
    assert "<<<<<<<" not in src and ">>>>>>>" not in src


# ------------------------------------------------------- compute：两侧的闸都要在

def test_compute_keeps_both_the_zero_gate_and_the_optional_disclosure():
    """全零闸（engine 侧）与 optional_input_missing 披露（api 侧）是两件事，不是二选一。

    只填 11 个必填位 → 必填闸放行、run() 把 515 条公式全算成 0 → 必须 422，
    而不是 200 + 七项合计全 0 的"生成成功"。
    """
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": dict(ROOT_INPUTS), "render": False})
    assert r.status_code == 422, r.text
    assert "全零" in r.json()["detail"]


def test_compute_discloses_missing_optional_inputs_when_it_does_produce_a_result():
    """出得了数的正常请求里，未填的可选输入位必须有 optional_input_missing 披露。

    可选位不填按 0 参与求值，C50 `=C47+C48+C49` 照样算得出数 —— 「动态总投资」于是
    恒等于「静态总投资」。这是静默的错误合计，比报错危险，必须响亮。
    """
    inputs = dict(ROOT_INPUTS)
    inputs["1.建筑工程费!C7"] = 5000.0          # 让 static_total 非 0，绕过全零闸
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": inputs, "render": False})
    assert r.status_code == 200, r.text
    codes = [w["code"] for w in r.json()["warnings"]]
    assert "optional_input_missing" in codes


# ------------------------------------------------------- suggest：两侧的出口都要在

def test_suggest_out_schema_keeps_the_tolerance_single_source():
    """⚠ O-22 改判：`deviations` / `with_deviation` 是**故意删掉**的，不是被合并吃掉的。

    本文件其余各条守的是「两条泳道合并时哪一侧的特性被静默丢了」。这一条反过来：
    记录一次**有意的**移除，免得后人看见 engine 侧曾有这两个字段，
    误以为又是一次合并事故而把它们加回来。

    删的理由（裁决 R12 / O-22）：服务端 `check_deviation()` 从 Java 到前端
    全程无调用方（实测 grep 零命中），而前端 estimateModel.ts 另有一份本地实现
    在真的跑。两份会漂移的实现 + 其中一份没人调，是最差的形态。

    没删的是**阈值**：tolerance 仍在出口里，且恒有值（不再是"要了才给"）——
    前端本地判 info/warn 时从这里取，不重复硬编码 0.20。
    """
    # zt 改动：没有响应模型，按 suggest 的返回键判
    fields = set(estimate_api.suggest({"inputs": dict(ROOT_INPUTS), "baselines": []}))
    assert "tolerance" in fields, "阈值的单一真源不能跟着校核一起删"
    assert "deviations" not in fields, "deviations 已按 O-22 删除，不要加回来"


def test_suggest_in_schema_keeps_the_api_side_fields():
    """api 侧的入参一个都不能丢；with_deviation 已按 O-22 删除。"""
    fields = set(estimate_api.SuggestRequest.model_fields)
    assert {"fee_bases", "fee_attrs", "items", "dims"} <= fields, "api 侧的入参丢了"
    assert "with_deviation" not in fields, "with_deviation 已按 O-22 删除，不要加回来"


def test_tolerance_is_always_present_now():
    """阈值恒下发：前端每次都要用它判 info/warn，不该"要了才给"。"""
    baselines = [{
        "indicator_code": "T-1", "item_name": "土石方工程", "item_code": None,
        "unit": "㎡", "unit_cost": 300.0, "base_metric": None,
        "source_sheet": None, "source_row": None,
        "region": None, "price_period": None, "project_type": None, "structure_type": None,
    }]
    body = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "inputs": dict(ROOT_INPUTS), "baselines": baselines,
    }).json()
    assert body["tolerance"] == pytest.approx(0.20)
    # WS10-P01：基准侧 range 不再按 tolerance 放缩 —— 单成员（本夹具只有一条基准）没有区间，
    # 前端据 range_basis 显示「单样本，无区间」，而不是一个凭空造的 ±20%
    row = next(s for s in body["suggestions"] if s["cell"] == "1.建筑工程费!C7")
    assert row["range"] == [None, None]
    assert row["range_basis"] == "single_value"


def test_suggest_keeps_the_api_side_fee_disclosure():
    """fee[] 为空的两种原因各有各的 warning（api 侧的 fee_bases_absent 不能丢）。"""
    body = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "inputs": dict(ROOT_INPUTS), "baselines": [],
    }).json()
    assert body["fee"] == []
    assert "fee_bases_absent" in [w["code"] for w in body["warnings"]]


def test_suggest_really_consumes_fee_bases_and_fee_attrs():
    """带了 fee_bases 就必须真的调费率引擎，且不再报 fee_bases_absent。"""
    seen: dict = {}
    mod = types.ModuleType("zt.estimate.fee_rules")

    def suggest_all(bases, attrs=None, ruleset="fee_rules_zj2018"):
        seen["bases"], seen["attrs"] = bases, attrs
        return {"items": [{"item_id": "supervision_fee", "suggested": 128.4}],
                "warnings": [{"code": "fee_rules_unsigned", "cell": None, "message": "待复核"}]}

    mod.suggest_all = suggest_all
    saved = sys.modules.get("zt.estimate.fee_rules")
    sys.modules["zt.estimate.fee_rules"] = mod
    try:
        body = client.post("/engine/estimate/suggest", headers=HEADERS, json={
            "inputs": dict(ROOT_INPUTS), "baselines": [],
            "fee_bases": {"工程费用": 12000.0}, "fee_attrs": {"region": "urban"},
        }).json()
    finally:
        if saved is None:
            sys.modules.pop("zt.estimate.fee_rules", None)
        else:
            sys.modules["zt.estimate.fee_rules"] = saved

    assert seen["bases"] == {"工程费用": 12000.0}
    assert seen["attrs"] == {"region": "urban"}
    assert [i["item_id"] for i in body["fee"]] == ["supervision_fee"]
    codes = [w["code"] for w in body["warnings"]]
    assert "fee_rules_unsigned" in codes        # 费率数据未签署，UI 要标"待复核"
    assert "fee_bases_absent" not in codes


# ------------------------------------------------------- template：api 侧的元数据

def test_template_keeps_the_api_side_optional_input_specs():
    """4 个可选输入位的 label/unit 补齐只在 api 侧 —— 丢了前端就是 4 个光秃秃的格号。"""
    payload = client.get("/engine/estimate/template", headers=HEADERS).json()
    specs = payload["optional_input_specs"]
    assert len(specs) == 4
    assert all(s["label"] for s in specs), "label 全空说明 optional_input_specs 退回成了 setdefault"
