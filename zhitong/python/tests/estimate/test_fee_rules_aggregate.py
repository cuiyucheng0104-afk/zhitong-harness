# 来源：engine-service/tests/test_fee_rules_aggregate.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""WS10-P11（issue #761）：汇总型费率规则与子项对账。

改前 C10-C13 子项之和 1446.57 是规则小计 451.18 的 3.2 倍，只有一句「须自行拆到子项」；
建设管理其他费（注 3：已含施工阶段全过程造价咨询）与 C12 工程造价咨询费可能重复计列，也没人说。
现在 `fee_rules.aggregate_checks` 对账、只报数：不给剩余额度、不平分、不给子项分配任何金额（铁律 3）。

夹具用真规则集（`suggest_all`，工程费用基数 20000 万元）：建设管理其他费小计 178.8、
项目建设管理费小计 281.0（均为仓主放行后的公开出口值，不是内部 ungated 入口）。
"""
from __future__ import annotations

import pytest

from zt.estimate import fee_rules as fr
from tests.estimate.fixtures.endpoint import HEADERS, client  # zt 改动：旧端点的转接

S = "5.工程建设其他费用"
MGMT_OTHER_CHILDREN = [f"{S}!C{r}" for r in (10, 11, 12, 13)]


@pytest.fixture(scope="module")
def items():
    out = fr.suggest_all({"工程费用": 20000.0}, {})
    by = {i["item_id"]: i for i in out["items"]}
    # 前置：两条汇总规则都真的出了小计参考值（否则下面每条都是空断言，铁律 8）
    assert by["management_other_fee"]["suggested"] == pytest.approx(178.8)
    assert by["project_management_fee"]["suggested"] == pytest.approx(281.0)
    return out["items"]


def _check(checks, item_id, status=None):
    return [c for c in checks if c["item_id"] == item_id and (status is None or c["status"] == status)]


def _codes(warnings):
    return [w["code"] for w in warnings]


def test_children_far_above_subtotal_is_a_mismatch(items):
    """子项全部已填、和是小计的 3.2 倍 → fee_aggregate_mismatch，数字写清。变异：删对账 → 转红。"""
    inputs = {MGMT_OTHER_CHILDREN[0]: 200.0, MGMT_OTHER_CHILDREN[1]: 150.0,
              MGMT_OTHER_CHILDREN[2]: 0.0, MGMT_OTHER_CHILDREN[3]: 222.16}   # 和 572.16 = 3.2×178.8
    checks, warnings = fr.aggregate_checks(items, inputs)
    c = _check(checks, "management_other_fee", "mismatch")
    assert len(c) == 1
    assert c[0]["children_sum"] == pytest.approx(572.16)
    assert c[0]["subtotal"] == pytest.approx(178.8)
    assert c[0]["deviation"] == pytest.approx(2.2, abs=1e-3)
    assert c[0]["aggregate_cell"] == f"{S}!C9"
    w = [w for w in warnings if w["code"] == "fee_aggregate_mismatch"]
    assert len(w) == 1 and "572.16" in w[0]["message"] and "178.8" in w[0]["message"]


def test_children_close_to_subtotal_is_consistent(items):
    inputs = {c: 45.0 for c in MGMT_OTHER_CHILDREN}                    # 180 vs 178.8，+0.7%
    checks, warnings = fr.aggregate_checks(items, inputs)
    assert _check(checks, "management_other_fee")[0]["status"] == "consistent"
    assert "fee_aggregate_mismatch" not in _codes(warnings)


def test_partial_children_only_report_the_filled_sum(items):
    """部分已填 → info：只报已填和与缺哪几格，不给剩余额度、不平分。"""
    inputs = {MGMT_OTHER_CHILDREN[0]: 30.0, MGMT_OTHER_CHILDREN[3]: 40.0}
    checks, warnings = fr.aggregate_checks(items, inputs)
    c = _check(checks, "management_other_fee")[0]
    assert c["status"] == "partial" and c["level"] == "info"
    assert c["children_sum"] == pytest.approx(70.0)
    assert c["missing_cells"] == [MGMT_OTHER_CHILDREN[1], MGMT_OTHER_CHILDREN[2]]
    assert "fee_aggregate_mismatch" not in _codes(warnings)
    assert "remaining" not in c and "deviation" not in c


def test_consulting_child_with_value_is_a_possible_double_count(items):
    """C12（工程造价咨询费）有值、而建设管理其他费小计已含全过程造价咨询（注 3）→ 可能重复计列。"""
    inputs = {MGMT_OTHER_CHILDREN[2]: 60.0}
    checks, warnings = fr.aggregate_checks(items, inputs)
    w = [w for w in warnings if w["code"] == "fee_possible_double_count"]
    assert len(w) == 1 and w[0]["cell"] == f"{S}!C12" and "注3" in w[0]["message"]
    assert _check(checks, "management_other_fee", "possible_double_count")
    # C12 = 0 视为不计列，不报
    _, w0 = fr.aggregate_checks(items, {MGMT_OTHER_CHILDREN[2]: 0.0})
    assert "fee_possible_double_count" not in _codes(w0)


def test_nothing_filled_means_nothing_to_reconcile(items):
    checks, warnings = fr.aggregate_checks(items, {})
    assert checks == [] and warnings == []


def test_checks_never_allocate_amounts_to_children(items):
    """任何情形下对账结果都不出「子项应填多少」（铁律 3：不平分、不编金额）。"""
    for inputs in ({c: 45.0 for c in MGMT_OTHER_CHILDREN},
                   {MGMT_OTHER_CHILDREN[0]: 30.0},
                   {MGMT_OTHER_CHILDREN[2]: 60.0}):
        checks, _ = fr.aggregate_checks(items, inputs)
        for c in checks:
            assert not ({"suggested", "allocation", "remaining", "per_child"} & set(c)), c
            assert not any(isinstance(v, dict) for v in c.values()), c


def test_withheld_subtotal_is_not_reconciled(items):
    """小计参考值被扣留（suggested=None）时不对账 —— 拿 None 当 0 对账会报一条假的 +∞% 差异。"""
    held = [dict(i, suggested=None) if i["write_target"] == "aggregate" else i for i in items]
    checks, warnings = fr.aggregate_checks(held, {c: 45.0 for c in MGMT_OTHER_CHILDREN})
    assert checks == [] and warnings == []


def test_suggest_endpoint_returns_aggregate_checks():
    """端点接线：suggest 响应带 aggregate_checks，告警同步进 warnings（Cm_S2 形状：带工程费用基数）。"""
    inputs = {"经济技术指标!D4": 12000.0, "经济技术指标!D7": 5000.0, "经济技术指标!D10": 20000.0}
    inputs.update({MGMT_OTHER_CHILDREN[0]: 200.0, MGMT_OTHER_CHILDREN[1]: 150.0,
                   MGMT_OTHER_CHILDREN[2]: 0.0, MGMT_OTHER_CHILDREN[3]: 222.16})
    r = client.post("/engine/estimate/suggest", headers=HEADERS,
                    json={"inputs": inputs, "baselines": [], "fee_bases": {"工程费用": 20000.0}})
    assert r.status_code == 200, r.text
    body = r.json()
    c = [x for x in body["aggregate_checks"] if x["item_id"] == "management_other_fee"]
    assert c and c[0]["status"] == "mismatch"
    assert "fee_aggregate_mismatch" in [w["code"] for w in body["warnings"]]
