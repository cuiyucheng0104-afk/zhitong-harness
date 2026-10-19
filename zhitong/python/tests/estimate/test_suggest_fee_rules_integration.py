# 来源：engine-service/tests/test_suggest_fee_rules_integration.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""**不打桩**的 fee_rules 集成用例（阶段 I 优化设计 O-02）。

本仓已有的 fee 相关用例全部用 `monkeypatch.setitem(sys.modules, ...)` 打桩，
因此它们证明的是"接线代码长得对"，**不证明真模块在场时这条链真的通**。

这个区别不是学术的：并集树建成之前，`app/api/estimate.py` 里写的是
`from zt.estimate import fee_rules` —— from-import 在函数首次执行时就把模块对象
绑进局部名字，打桩落不进来。真模块（PR #113）一入仓，三条打桩用例立刻转红，
而没有任何一条用例覆盖"真模块在场"这条路径。

本文件补上那条路径：真 fee_rules、真规则数据、真 HTTP 往返。
"""
from __future__ import annotations

import pytest
from tests.estimate.fixtures.endpoint import HEADERS, client  # zt 改动：旧端点的转接




SUGGEST_URL = "/engine/estimate/suggest"

ROOT_INPUTS = {
    "经济技术指标!D4": 12000.0, "经济技术指标!D7": 5200.0, "经济技术指标!D8": 3100.0,
    "经济技术指标!D10": 8800.0, "经济技术指标!D11": 7600.0, "经济技术指标!D12": 6400.0,
    "经济技术指标!D13": 5900.0, "经济技术指标!D15": 4200.0, "经济技术指标!D16": 3300.0,
    "经济技术指标!D19": 260.0, "经济技术指标!D20": 140.0,
}
DIMS = {"region": None, "price_period": None,
        "project_type": "房屋建筑", "structure_type": None}


@pytest.fixture(scope="module")
def real_fee_rules():
    """确认真模块真的在场——不在场就 skip，绝不让本文件空转成绿。"""
    pytest.importorskip("zt.estimate.fee_rules",
                        reason="真 fee_rules 未入仓（PR #113 未合），本文件无意义")
    from zt.estimate import fee_rules
    return fee_rules


def _post(**kw):
    body = {"inputs": dict(ROOT_INPUTS), "baselines": [], "dims": dict(DIMS)}
    body.update(kw)
    r = client.post(SUGGEST_URL, headers=HEADERS, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_real_fee_rules_is_reached_not_stubbed(real_fee_rules):
    """带 fee_bases 时，真 fee_rules 必须被调到并出满 16 条。

    16 = 13 input + 2 aggregate + 1 manual（契约 §1.4 实测分布）。
    数量不对说明规则集被截断或落点归类走形。
    """
    body = _post(fee_bases={"工程费用": 12000.0})
    fee = body.get("fee") or []
    assert len(fee) == 16, f"真 fee_rules 应出 16 条，实得 {len(fee)}"
    wt = {}
    for f in fee:
        wt[f.get("write_target")] = wt.get(f.get("write_target"), 0) + 1
    assert wt == {"input": 13, "aggregate": 2, "manual": 1}, wt


def test_unavailable_warning_is_gone_when_module_is_present(real_fee_rules):
    """真模块在场时绝不能再报 fee_rules_unavailable。

    那条告警的语义是「引擎没接上」（部署侧的事）。模块在场还报它，
    等于把一个已解决的问题继续告警——比不报更糟，会掩盖真实的部署缺失。
    """
    codes = {w["code"] for w in _post(fee_bases={"工程费用": 12000.0}).get("warnings", [])}
    assert "fee_rules_unavailable" not in codes, codes


def test_signoff_state_is_surfaced(real_fee_rules):
    """签署状态必须一路透到 suggest 响应，不许在中间层被吞掉。

    铁律 2 的延伸：这批费率是 LLM 转录的，UI 必须能标出它的成色。
    中间任何一层把它过滤掉，造价员就看不到了。

    三个态各有各的码，**没有"什么都不发"这一档**（#159）：
      pending                    → fee_rules_unsigned    「本次不出金额」
      signed + owner_release     → fee_rules_owner_released「出金额，但没人对图核过」
      signed + cost_engineer     → 无告警（造价员背书，这时才是干净的）
    """
    doc = real_fee_rules._load()
    codes = {w["code"] for w in _post(fee_bases={"工程费用": 12000.0}).get("warnings", [])}
    if doc["signoff_status"] != "signed":
        assert "fee_rules_unsigned" in codes, f"未签署告警未透出：{codes}"
    elif doc.get("signoff_kind") != "cost_engineer":
        assert "fee_rules_owner_released" in codes, (
            f"仓主默认放行的告警未透出：{codes} —— 建议值出来了却没人说这批数字"
            "没经造价员核过，这正是铁律 2 说的「因为难看就藏起来」")
    else:
        assert "fee_rules_unsigned" not in codes
        assert "fee_rules_owner_released" not in codes


def test_absent_and_unavailable_are_different_warnings(real_fee_rules):
    """不给 fee_bases → fee_bases_absent（请求侧）；模块缺失 → fee_rules_unavailable（部署侧）。

    两者文案在前端第 6 组完全不同，混用就会把「你没填基数」说成「系统没接上」。
    真模块在场时，不给基数只能是前者。
    """
    codes = {w["code"] for w in _post().get("warnings", [])}
    assert "fee_bases_absent" in codes, codes
    assert "fee_rules_unavailable" not in codes, codes


# ------------------------------------------------------------------ WS10-P07（issue #722）
#
# 缺陷原形：`bases = body.fee_bases or _derive_fee_bases(...)` —— 二选一。用户只要补任一
# 基数（比如中标金额），「工程费用」兜底整条失效：7 条以工程费用为基数的规则全部 no_base，
# 双源格静默回退基准侧（监理费 890.87 → 1058.47）。前端注释与占位文字写的却是
# 「留空由服务端兜底」—— 前后端契约相反。

# 带一个成本位，让估概算总表!C5（工程费用合计）> 0，兜底才有值可取
_WITH_COST = dict(ROOT_INPUTS, **{"1.建筑工程费!C7": 5000.0, "1.建筑工程费!C25": 7000.0})


def _spec(body, base_key):
    return next(s for s in body["required_fee_bases"] if s["base_key"] == base_key)


def _fee(body, item_id):
    return next(f for f in body["fee"] if f["item_id"] == item_id)


def test_partial_fee_bases_keep_project_cost_fallback(real_fee_rules):
    """只给一个**非**工程费用的基数时，工程费用照样兜底，监理费等 7 条照常出值。

    夹具必须带非工程费用基数（中标金额）：不带的话走的是「fee_bases 为空」那条老路，
    二选一的缺陷分支根本到不了。变异：改回 `fee_bases or derive` → 本条转红。
    """
    body = _post(inputs=_WITH_COST, fee_bases={"中标金额": 6000.0})
    sup = _fee(body, "supervision_fee")
    assert sup["suggested"] is not None, sup["unavailable_reason"]
    assert sup["basis"]["base_key"] == "工程费用"
    assert sup["basis"]["base_value"] == pytest.approx(12000.0)
    assert _fee(body, "bidding_agency_fee")["basis"]["base_value"] == 6000.0   # 用户值照常参与
    spec = _spec(body, "工程费用")
    assert spec["satisfied"] is True and spec["derived"] is True and spec["derivable"] is True
    assert _spec(body, "中标金额")["derived"] is False
    assert "fee_base_derived" in {w["code"] for w in body["warnings"]}
    assert "fee_bases_absent" not in {w["code"] for w in body["warnings"]}


def test_user_project_cost_wins_over_derived(real_fee_rules):
    """用户给了工程费用 → 用户值优先，不出 fee_base_derived（没替人补任何值）。

    变异：把合并顺序反过来（兜底值覆盖用户值）→ 监理费的基数变成 12000，本条转红。
    """
    body = _post(inputs=_WITH_COST, fee_bases={"工程费用": 5000.0, "中标金额": 6000.0})
    assert _fee(body, "supervision_fee")["basis"]["base_value"] == 5000.0
    spec = _spec(body, "工程费用")
    assert spec["satisfied"] is True and spec["derived"] is False
    assert "fee_base_derived" not in {w["code"] for w in body["warnings"]}


def test_fallback_still_absent_when_nothing_can_be_derived(real_fee_rules):
    """成本位一个没填（C5 = 0）、也没给基数 → fee_bases_absent（不是「算过了但没结果」）。"""
    body = _post()
    assert "fee_bases_absent" in {w["code"] for w in body["warnings"]}
    assert body["fee"] == []
