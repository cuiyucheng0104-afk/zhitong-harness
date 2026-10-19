# 来源：engine-service/tests/fixtures/reportform/make_compute_snapshot.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""生成 compute 的行为快照（WS25-b，issue #945）—— **在闸函数抽取之前**跑一次并入仓。

为什么要快照：WS25-b 把 compute 的四道闸与一串告警函数挪到 app/engine/ 下共用。
「行为不变」不能靠现有用例的子串断言（它们只查 detail 里含不含某几个字），
要逐字比：四条 422 的 detail、校验类 422 的 detail、几组 200 的整份响应（usage 除外）。

夹具全部由仓内模板与合成数值构造，不含客户资料。重新生成（zt 改动：经 tests/estimate/fixtures/endpoint.py 的转接）：
    cd zhitong/python && uv run python -m tests.estimate.fixtures.reportform.make_compute_snapshot
⚠ 只有在**有意**改变 compute 行为时才重生成，并在 PR 里写明为什么。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).with_name("compute_snapshot.json")

ROOT = {
    "经济技术指标!D4": 12000.0, "经济技术指标!D7": 5200.0, "经济技术指标!D8": 3100.0,
    "经济技术指标!D10": 8800.0, "经济技术指标!D11": 7600.0, "经济技术指标!D12": 6400.0,
    "经济技术指标!D13": 5900.0, "经济技术指标!D15": 4200.0, "经济技术指标!D16": 3300.0,
    "经济技术指标!D19": 260.0, "经济技术指标!D20": 140.0,
}
SLOT_SUM = 5200.0 + 3100.0 + 8800.0 + 7600.0 + 6400.0 + 5900.0
COST = {"1.建筑工程费!C7": 130.0, "5.工程建设其他费用!C15": 2000.0}
OUTDOOR = {"4.室外及配套工程费!C7": 800.0}


def _zero_area() -> dict:
    inp = {k: 0.0 for k in ROOT}
    inp["经济技术指标!D4"] = 12000.0
    return inp


def _synthetic() -> dict:
    p = Path(__file__).resolve().parents[1] / "estimate_gsyz_v1_synthetic.json"
    return json.loads(p.read_text(encoding="utf-8"))


def cases() -> list[tuple[str, dict]]:
    syn = _synthetic()
    partial = {k: v for k, v in ROOT.items() if k not in ("经济技术指标!D4", "经济技术指标!D20")}
    all_user = {k: {"source": "user"} for k in syn["inputs"]}
    return [
        # —— 四道闸 ——
        ("required_empty", {"inputs": {}, "render": False}),
        ("required_partial", {"inputs": dict(partial, **COST), "render": False}),
        ("area_gate_zero_area_with_outdoor", {"inputs": dict(_zero_area(), **OUTDOOR), "render": False}),
        ("area_reconcile_unacked", {"inputs": dict(ROOT, **COST), "render": False,
                                    "area_checks": {"gross_building_area": SLOT_SUM * 2}}),
        ("all_zero", {"inputs": dict(ROOT), "render": False}),
        # —— 顺序 ——
        ("order_required_before_context_validation",
         {"inputs": {}, "render": False, "area_checks": {"gross_building_area": -1}}),
        ("order_area_gate_before_all_zero", {"inputs": _zero_area(), "render": False}),
        ("order_area_gate_before_reconcile",
         {"inputs": dict(_zero_area(), **OUTDOOR), "render": False,
          "area_checks": {"gross_building_area": 99999.0}}),
        ("order_reconcile_before_all_zero",
         {"inputs": dict(ROOT), "render": False, "area_checks": {"gross_building_area": SLOT_SUM * 2}}),
        # —— 校验类 422（随抽取挪动的校验函数，文案同样不许变）——
        ("bad_area_checks", {"inputs": dict(ROOT, **COST), "render": False,
                             "area_checks": {"gross_building_area": True}}),
        ("ack_without_reason", {"inputs": dict(ROOT, **COST), "render": False,
                                "area_checks": {"gross_building_area": SLOT_SUM * 2},
                                "acknowledged_checks": [{"code": "area_total_mismatch", "reason": " "}]}),
        ("ack_unknown_code", {"inputs": dict(ROOT, **COST), "render": False,
                              "acknowledged_checks": [{"code": "x", "reason": "y"}]}),
        ("slot_label_not_a_slot", {"inputs": dict(ROOT, **COST), "render": False,
                                   "slot_labels": {"经济技术指标!D4": "用地"}}),
        ("slot_label_multiline", {"inputs": dict(ROOT, **COST), "render": False,
                                  "slot_labels": {"经济技术指标!D7": "地下\n室"}}),
        ("bad_input_source", {"inputs": dict(ROOT, **COST), "render": False,
                              "input_sources": {"1.建筑工程费!C7": {"source": "guess"}}}),
        ("bad_fee_base", {"inputs": dict(ROOT, **COST), "render": False, "fee_bases": {"工程费用": "1"}}),
        ("bad_fee_attr", {"inputs": dict(ROOT, **COST), "render": False, "fee_attrs": {"a": 1}}),
        ("bad_profile", {"inputs": dict(ROOT, **COST), "render": False,
                         "project_profile": {"building_function": ["x"]}}),
        ("bad_generated_at", {"inputs": dict(ROOT, **COST), "render": False, "generated_at": "昨天"}),
        ("bool_input", {"inputs": dict(ROOT, **{"1.建筑工程费!C7": True}), "render": False}),
        # —— 200：整份响应（usage 除外）——
        ("ok_cost_partial", {"inputs": dict(ROOT, **COST), "render": False}),
        ("ok_area_acked", {"inputs": dict(ROOT, **COST), "render": False,
                           "area_checks": {"gross_building_area": SLOT_SUM * 2},
                           "acknowledged_checks": [{"code": "area_total_mismatch",
                                                    "reason": "原文总面积含架空层与人防，模板不计"}]}),
        ("ok_ratio_suspect", {"inputs": dict(ROOT, **COST, **{"估概算总表!D48": 3.0}), "render": False}),
        ("ok_unknown_input", {"inputs": dict(ROOT, **COST, **{"不存在的表!Z9": 1.0}), "render": False}),
        ("ok_synthetic", {"inputs": syn["inputs"], "rates": syn["rates"], "render": False}),
        ("ok_synthetic_all_user_with_fee", {
            "inputs": syn["inputs"], "rates": {"reserve_rate": 0.01}, "render": False,
            "input_sources": dict(all_user, **{"5.工程建设其他费用!C7": {"source": "fee_rules"}}),
            "fee_bases": {"中标金额": 120000.0}, "fee_attrs": {},
            "project_profile": {"building_function": "residential", "project_city": "杭州"},
            "generated_at": "2026-10-05 10:00:00"}),
    ]


def run_all() -> list[dict]:
    from tests.estimate.fixtures.endpoint import HEADERS, client

    out = []
    for name, body in cases():
        r = client.post("/engine/estimate/compute", headers=HEADERS, json=body)
        rec: dict = {"name": name, "status": r.status_code}
        j = r.json()
        if r.status_code == 200:
            j.pop("usage", None)
            # sheets 是求值器 run() 的逐格结果，整份入仓太大；留指纹
            rec["sheets_sha256"] = hashlib.sha256(
                json.dumps(j.pop("sheets"), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            rec["response"] = j
        else:
            rec["detail"] = j.get("detail")
        out.append(rec)
    return out


if __name__ == "__main__":
    OUT.write_text(json.dumps(run_all(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT}")
