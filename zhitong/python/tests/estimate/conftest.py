# 来源：engine-service/tests/conftest.py 的概算部分（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""概算用例的会话级夹具：指标基准种子、费率规则「未签署」态。"""
from __future__ import annotations

import pytest

from zt.estimate import service


@pytest.fixture(scope="session")
def concept_baselines() -> list[dict]:
    """概算指标基准（旧版解析入仓种子 SQL；zt 改动：读随包的 concept_baselines_gsyz_v1.json，同一份数据）。

    文件在但一行都没有是缺陷（不是「没有种子」），响亮失败，不降级成 skip。
    """
    rows = service.default_baselines("gsyz_v1")
    assert rows, "随包指标基准 concept_baselines_gsyz_v1.json 一行都读不出 —— 数据文件坏了，不许降级成 skip"
    return rows


# ---------------------------------------------------------------- 签署闸的两个态
#
# 仓里的 fee_rules_zj2018.json 是 signoff_status="signed"（signoff_kind=owner_release，仓主默认放行）。
# 「未签署 → 恒 null」那道闸的判据不能跟着数据一起消失：把「未签署」做成显式构造的夹具。
@pytest.fixture
def unsigned_ruleset(monkeypatch):
    """把默认规则集强制回到「未签署」态，返回 fee_rules 模块本身。"""
    import sys as _sys

    import zt.estimate as _pkg

    targets = []
    for obj in (_sys.modules.get("zt.estimate.fee_rules"), getattr(_pkg, "fee_rules", None)):
        if obj is not None and not any(obj is t for t in targets):
            targets.append(obj)
    if not targets:
        from zt.estimate import fee_rules as _fr
        targets.append(_fr)

    for mod in targets:
        real_load = mod._load

        def _pending(ruleset=None, _real=real_load, _mod=mod) -> dict:
            doc = dict(_real(_mod.DEFAULT_RULESET if ruleset is None else ruleset))
            doc["signoff_status"] = "pending"
            doc["signoff_kind"] = None
            doc["signoff_by"] = None
            doc["signoff_at"] = None
            return doc

        monkeypatch.setattr(mod, "_load", _pending)
        assert not mod.is_signed(), "夹具没生效：强制未签署失败，闸测会退化成空转"
    return targets[0]
