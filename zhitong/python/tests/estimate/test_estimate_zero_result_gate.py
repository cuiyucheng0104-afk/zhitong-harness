# 来源：engine-service/tests/test_estimate_zero_result_gate.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""compute 的全零闸（对抗复核 #1 的连带后果）。

复核实证的链路：向导第 3 步调 /estimate/suggest 拿建议金额 —— 但那个端点当时
根本不存在，必然 404；第 5 步只校验 11 个必填根输入位就放行 compute；引擎按
「空格 = 0」把 515 条公式全算成 0；端点 200 + 一份七项合计全 0.0 的 xlsx；
Java 落一条 state=done 的任务。造价员拿到的是一份"生成成功"的空表。

契约 §5.2 对 extract 写死了「绝不 200+空结果（空结果对造价员是误导性成功）」，
这条纪律在 compute 上同样成立，只是原实现漏了。本文件把闸钉死。

单开文件而不是并进 tests/test_estimate_api.py：那是 api 泳道的交付物，
同一轮修复里对方大概率也在改，分开写把冲突面压到 0。
"""
from __future__ import annotations

import pytest
from tests.estimate.fixtures.endpoint import HEADERS, client  # zt 改动：旧端点的转接





REQUIRED_11 = [
    "经济技术指标!D4", "经济技术指标!D7", "经济技术指标!D8", "经济技术指标!D10",
    "经济技术指标!D11", "经济技术指标!D12", "经济技术指标!D13", "经济技术指标!D15",
    "经济技术指标!D16", "经济技术指标!D19", "经济技术指标!D20",
]
# 实测的 kind=="cost" 输入位，直接汇进 估概算总表!C5 工程费用
ONE_COST_CELL = "1.建筑工程费!C7"


def _roots(v: float = 1000.0) -> dict:
    return {c: v for c in REQUIRED_11}


def _compute(inputs: dict, **kw) -> object:
    body = {"inputs": inputs, "render": False}
    body.update(kw)
    return client.post("/engine/estimate/compute", headers=HEADERS, json=body)


# ------------------------------------------------------------------ 闸本身

def test_only_root_inputs_is_rejected_not_a_zero_xlsx():
    """只填 11 个必填位、150 个成本位一个不填 → 422，不许出全零表。"""
    r = _compute(_roots())
    assert r.status_code == 422, \
        f"全零概算被当成成功返回了：{r.text[:300]}"
    detail = r.json()["detail"]
    assert "全零" in detail
    # 报错必须可行动：告诉用户去哪一步、用哪个端点补数
    assert "suggest" in detail


def test_all_cost_inputs_explicitly_zero_is_also_rejected():
    """闸设在产出侧，所以「填了但全填 0」同样挡得住（输入侧闸挡不住这种）。"""
    inputs = _roots()
    inputs[ONE_COST_CELL] = 0.0
    r = _compute(inputs)
    assert r.status_code == 422
    assert "全零" in r.json()["detail"]


def test_one_non_zero_cost_passes():
    """有一分钱真实成本就放行——闸只挡全零，不挡"填得少"。"""
    inputs = _roots()
    inputs[ONE_COST_CELL] = 1.0
    r = _compute(inputs)
    assert r.status_code == 200, r.text
    totals = r.json()["totals"]
    assert totals["project_cost"]["value"] == 1.0
    assert totals["static_total"]["value"] == 1.05    # 1.0 + 0 + 1.0*5% 预备费


def test_zero_result_is_rejected_before_rendering():
    """render=true 时也必须在渲染前就拒——绝不落一份全零 xlsx 出去。"""
    r = _compute(_roots(), render=True)
    assert r.status_code == 422
    assert r.json().get("xlsx_base64") is None


def test_other_cost_only_project_still_passes():
    """只填「工程建设其他费用」而工程费为 0 的项目要放行。

    闸卡的是静态投资合计（C47 = C5 工程费 + C45 其他费 + C46 预备费），不是 C5。
    卡 C5 会把这类项目误伤成 422 —— 这条用例就是防止有人把闸改窄。
    """
    inputs = _roots()
    inputs["5.工程建设其他费用!C14"] = 8.0     # 工程监理费，kind=="cost"
    r = _compute(inputs)
    assert r.status_code == 200, r.text
    totals = r.json()["totals"]
    assert totals["project_cost"]["value"] == 0.0
    assert totals["other_cost"]["value"] == 8.0
    assert totals["static_total"]["value"] > 0


# ------------------------------------------------------------------ 不许误伤

def test_missing_required_gate_still_fires_first():
    """必填闸（裁决 C）优先级不变：缺必填位报的还是"缺少必填输入位"，不是全零。"""
    inputs = _roots()
    inputs.pop("经济技术指标!D7")
    r = _compute(inputs)
    assert r.status_code == 422
    assert "缺少必填输入位" in r.json()["detail"]


@pytest.mark.parametrize("rate", [0.01, 0.08])
def test_rate_edge_values_unaffected(rate):
    """铁律 7：预备费率不设硬闸。全零闸不得顺手把 1% 也拦了。"""
    inputs = _roots()
    inputs[ONE_COST_CELL] = 100.0
    r = _compute(inputs, rates={"reserve_rate": rate})
    assert r.status_code == 200, r.text
