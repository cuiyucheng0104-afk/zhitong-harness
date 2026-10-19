# 来源：engine-service/tests/test_estimate_gates_refactor.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""WS25-b（issue #945）：概算四道闸与告警函数抽成共用函数 —— compute 的行为一个字都不许变。

快照 `fixtures/reportform/compute_snapshot.json` 在闸函数抽取**之前**生成并入仓（本 PR 第一个提交），
这里逐字比对：四道闸的 422 detail、闸的先后顺序、随抽取挪动的校验函数的 422 detail、
六组 200 的整份响应（usage 除外；sheets 是求值器 run() 的逐格结果，比指纹）。

WS29-q（issue #1000）有意加了一条需复核理由 sheet_unfilled_review（专项 / 室外整表没填时点名，U18）：
快照里 4 个 200 用例的 quality.reasons 只在 sheet_unfilled 后面补了这一条，其余逐字未动。

为什么不靠现有用例：test_estimate_compute_gates.py 等只断言 detail「含」某几个字，
把文案改掉一半、或把两道闸的顺序调换，它们大多照样绿。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest



from tests.estimate.fixtures.reportform.make_compute_snapshot import cases  # noqa: E402
from tests.estimate.fixtures.endpoint import HEADERS, PASSTHROUGH, client  # zt 改动：旧端点的转接

SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures" / "reportform" / "compute_snapshot.json").read_text(encoding="utf-8"))
BY_NAME = {r["name"]: r for r in SNAPSHOT}
CASES = dict(cases())


def test_snapshot_and_case_list_agree():
    """快照与用例清单一一对应 —— 新加用例却忘了重生成快照，下面的参数化会静默少跑一条。"""
    assert set(BY_NAME) == set(CASES)
    assert sum(1 for r in SNAPSHOT if r["status"] == 422) >= 18
    assert sum(1 for r in SNAPSHOT if r["status"] == 200) >= 6


@pytest.mark.parametrize("name", sorted(CASES))
def test_compute_matches_pre_refactor_snapshot(name):
    want = BY_NAME[name]
    r = client.post("/engine/estimate/compute", headers=HEADERS, json=CASES[name])
    assert r.status_code == want["status"], r.text
    j = r.json()
    if want["status"] != 200:
        assert j["detail"] == want["detail"]
        return
    j.pop("usage", None)
    sheets = j.pop("sheets")
    # zt 改动：没有透传字段（sys_company_code / project_id / operator_id），快照里那三个 null 不比
    want = {**want, "response": {k: v for k, v in want["response"].items() if k not in PASSTHROUGH}}
    assert hashlib.sha256(json.dumps(sheets, ensure_ascii=False, sort_keys=True).encode()).hexdigest() \
        == want["sheets_sha256"]
    assert j == want["response"]


def test_the_four_gates_are_all_in_the_snapshot():
    """四道闸各自至少有一条 422 快照，且文案是那道闸自己的（夹具够得到每一道闸）。"""
    detail = {n: (BY_NAME[n].get("detail") or "") for n in BY_NAME}
    assert detail["required_empty"].startswith("缺少必填输入位：")
    assert "总建筑面积（经济技术指标!D5）" in detail["area_gate_zero_area_with_outdoor"]
    assert "相差" in detail["area_reconcile_unacked"] and "单体归位" in detail["area_reconcile_unacked"]
    assert detail["all_zero"].startswith("概算结果为全零")
    # 顺序：必填 → 校验 → 面积 → 对账 → 全零
    assert detail["order_required_before_context_validation"].startswith("缺少必填输入位")
    assert "总建筑面积" in detail["order_area_gate_before_all_zero"]
    assert "总建筑面积" in detail["order_area_gate_before_reconcile"]
    assert "相差" in detail["order_reconcile_before_all_zero"]


# ------------------------------------------------------------------ 闸函数本身（不经端点）

def test_required_cells_match_the_extract_candidate_pool():
    """estimate_gates 不 import estimate_extract（后者模块级带 LLM 客户端），自己按表名取必填位；
    两边必须是同一份清单，否则「抽 11 个、算要 12 个」的漂移会回来。"""
    from zt.estimate import extract as estimate_extract
    from zt.estimate import gates as estimate_gates

    want = [s["cell"] for s in estimate_extract.root_input_specs("gsyz_v1")]
    assert list(estimate_gates.required_cells("gsyz_v1")) == want
    assert len(want) == 11


def test_gate_functions_return_findings_instead_of_raising():
    """四道闸都是不抛异常的纯函数：不通过回 GateFinding（code、cell、message），通过回 None。"""
    from zt.estimate import gates as g
    from zt.estimate import policy as estimate_policy
    from zt.estimate.engine import run

    pol = estimate_policy.load_policy("gsyz_v1")
    zero_area = run(CASES["area_gate_zero_area_with_outdoor"]["inputs"])
    f = g.area_gate(pol, zero_area)
    assert f.code == g.AREA_GATE and f.cell == "经济技术指标!D5"
    assert f.message == BY_NAME["area_gate_zero_area_with_outdoor"]["detail"]

    ok = run(CASES["ok_cost_partial"]["inputs"])
    assert g.area_gate(pol, ok) is None and g.all_zero(ok) is None
    mis = g.area_reconcile(pol, ok, {"gross_building_area": 74000.0})
    assert mis.code == "area_total_mismatch" and mis.message == BY_NAME["area_reconcile_unacked"]["detail"]
    assert g.area_reconcile(pol, ok, {}) is None

    zero = run(CASES["all_zero"]["inputs"])
    assert g.all_zero(zero).message == BY_NAME["all_zero"]["detail"]
    assert g.required(g.required_cells("gsyz_v1"), set()).message == BY_NAME["required_empty"]["detail"]
    assert g.ORDER == (g.REQUIRED, g.AREA_GATE, g.AREA_MISMATCH, g.ALL_ZERO)
