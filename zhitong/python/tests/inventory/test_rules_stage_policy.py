"""迁移自旧仓 engine-service/tests/test_classify_stage_policy.py；未迁移 stage_for_category 与 LLM 兜底相关用例（本仓无 LLM 兜底）。

WS13-P09：cost_stage 是规则行常量，不看期次和目录；LLM 结果无阶段（issue #720）。

复现基线（origin/dev d25a4637）：
  验工计价审核对比汇总表第10期.xlsx → 价款对比分析 / **审定**
  商务标封面.pdf（放在「5 投标文件」下）→ 封面 / **审定**
  第5期工程款支付审核报告.docx       → 审核报告 / **审定**
  勘察费用预算表.xlsx                → 施工图预算 / **概算**
  LLM 判出的类目                      → 阶段一律 None
这些「审定」票正是驾驶舱默认阶段被推到审定的来源（P15）。

修法：_resolve_stage 按「文件名期次 → 语境行取最近带阶段的祖先 → 规则常量 → 祖先链」判定；
stage_for_category 给 LLM 结果用（期次 → 祖先 → 类目在规则里唯一的阶段 → None）。
「审核+报告」仍判审定（#210 裁定，test_checklist_stage_decision2 的锚点不动）。
"""
from __future__ import annotations

import pytest

from tests.inventory._support import engine
from zt.inventory.rules import ClassifyInput


def _one(name: str, ext: str, ancestors=None):
    return engine.classify_one(ClassifyInput("f1", name, ext, ancestors=ancestors, has_text_layer=True))


@pytest.mark.parametrize("name,ext,anc,cat,stage", [
    ("验工计价审核对比汇总表第10期.xlsx", "xlsx", None, "进度款支付", "施工过程"),
    ("第3期审核汇总表.xlsx", "xlsx", ["22 进度款审核及付款建议"], "进度款支付", "施工过程"),
    ("土建审核对比表（第12期）.xlsx", "xlsx", None, "土建对比表", "施工过程"),   # 期次覆盖常量「审定」
    ("商务标封面.pdf", "pdf", ["5 投标文件"], "封面", "招标控制价"),
    ("商务标封面.pdf", "pdf", None, "封面", None),
    ("投标文件目录.pdf", "pdf", ["5 投标文件"], "目录", "招标控制价"),
    # 语境行的期次覆盖：封面/目录/扉页不在 _PERIOD_CATEGORIES 里，只有 stage_policy: context
    # 让它们也吃期次。语境行的常量已置空，这一例是 stage_policy 唯一可观测的差别 —— 没有它，
    # 把 stage_policy 整个失效掉本文件照样全绿（变异验收实测过）。
    ("第3期封面.pdf", "pdf", None, "封面", "施工过程"),
    ("第5期工程款支付审核报告.docx", "docx", None, "进度款支付", "施工过程"),
    ("结算审核报告.pdf", "pdf", None, "审核报告", "审定"),                  # #210 不回退
    ("结算审核汇总表.xlsx", "xlsx", None, "汇总表", None),                  # 语境行，无目录信号 → 未定
    ("土建审核对比表.xlsx", "xlsx", None, "土建对比表", "审定"),            # 无期次 → 规则常量
])
def test_stage_policy(name, ext, anc, cat, stage):
    o = _one(name, ext, anc)
    assert (o.doc_category, o.cost_stage) == (cat, stage), o.reason


def test_period_override_is_explained_in_reason():
    o = _one("土建审核对比表（第12期）.xlsx", "xlsx")
    assert "期次" in o.reason
