"""迁移自旧仓 engine-service/tests/test_classify_ws13_rules.py。

WS13-P01 / P10：规则层裸词截胡、判定顺序、黑名单误杀、计价扩展名（issue #720）。

复现基线（origin/dev d25a4637，零 LLM 直接实例化 ClassifyEngine）：
  施工图预算书.xlsx           → archive/施工图/0.95/needs_manual=False（归档词「施工图」截走 whitelist「施工图预算」）
  某某建筑工程结算书.pdf      → archive/None/0.95/False（无类目专业词「建筑」终止判定）
  定级表及报价单.docx         → rag/投标报价书/0.85/False（裸词「报价」不看语境）
  招标代理合同.pdf            → rag/招标文件/0.85/False
  桩基检测费用签证单.pdf      → skip/None/0.9/False（黑名单裸词「检测」误杀）
  X.SSQ6                      → skip/None/0.0（未收录的计价扩展名，生产上会走 LLM）
每条都是「自信地错」—— 错标签带 0.85/0.95、needs_manual=False 出厂。

本文件逐条钉住新口径下的 类目 / 阶段 / needs_manual / evidence。
类目按 **分类器原始产出** 比对（映射到清单口径是 P14 的事，见 test_category_vocabulary_gate）。
"""
from __future__ import annotations

import pytest

from tests.inventory._support import RULES as _RULES
from tests.inventory._support import engine
from zt.inventory.rules import ClassifyInput, Rule, rule_hit as _hit

RULE, BARE, INHERIT = "filename_rule", "filename_bareword", "ancestor_inherit"


def _one(name: str, ext: str, ancestors=None):
    return engine.classify_one(ClassifyInput("f1", name, ext, ancestors=ancestors, has_text_layer=True))


# (文件名, 扩展名, 祖先由近及远, 期望类目, 期望阶段, 期望 needs_manual, 期望 evidence)
# 期望阶段写 ... 表示本用例不关心阶段（阶段口径另见 test_classify_stage_policy）
CASES = [
    # —— 归档词「施工图」不再截走「施工图预算」（⑥ specific 先于 ⑦ 带类目归档词）——
    ("施工图预算书.xlsx", "xlsx", None, "施工图预算", "概算", False, RULE),
    ("给排水施工图预算.pdf", "pdf", None, "施工图预算", "概算", False, RULE),
    # —— 无类目专业词不再终止判定：后面的文档类型词照样生效 ——
    ("某某建筑工程结算书.pdf", "pdf", None, "结算价文件", "结算", True, BARE),
    ("XX市政道路工程控制价.pdf", "pdf", None, "招标控制价", "招标控制价", True, BARE),
    ("XX建筑工程审定单.pdf", "pdf", None, "审定单", "审定", False, RULE),
    # —— 只命中无类目专业词：空类目、置信度 0、明示待复核 ——
    ("建筑做法参考.pdf", "pdf", None, None, None, True, None),
    # design_indicator_keywords 新增「图纸」：否则无类目归档词「图纸」(p30) 先记下、⑧ 又认不出
    # 设计词，按专业命名的图纸 PDF 落到 ⑫ 成了空类目
    ("结构图纸.pdf", "pdf", None, "结构图纸", None, False, RULE),
    # —— 裸词语境约束 ——
    ("定级表及报价单.docx", "docx", None, None, None, True, None),
    ("前期咨询报价单.pdf", "pdf", None, None, None, True, None),
    ("施工报价单.pdf", "pdf", None, "投标报价书", "招标控制价", True, BARE),
    ("代理机构招标合同.pdf", "pdf", None, None, None, True, None),   # 招标 exclude_any:[代理]
    ("勘察费用预算表.xlsx", "xlsx", None, None, None, True, None),   # 预算 exclude_any:[勘察…]
    ("关于调整预算的请示.pdf", "pdf", None, "施工图预算", "概算", True, BARE),
    ("审计服务采购合同.pdf", "pdf", None, None, None, True, None),   # 审计 exclude_any:[合同,采购,服务…]
    ("规划审定意见书.pdf", "pdf", None, None, None, True, None),     # 审定 exclude_any:[规划,意见书]
    ("汇总表.xlsx", "xlsx", None, None, None, True, None),           # 汇总 require_any 不满足
    ("汇总表.xlsx", "xlsx", ["造价审核资料"], "汇总表", ..., True, BARE),  # require_any 由祖先满足
    ("投标人须知.pdf", "pdf", None, "投标文件", "招标控制价", True, BARE),
    # —— 新增 specific 行 ——
    ("验工计价建议书.pdf", "pdf", None, "进度款支付", "施工过程", False, RULE),
    ("第3期计量支付汇总表.xlsx", "xlsx", None, "进度款支付", "施工过程", False, RULE),
    ("第5期工程款支付审核报告.docx", "docx", None, "进度款支付", "施工过程", False, RULE),
    ("进度款审核意见.docx", "docx", None, "进度款支付", "施工过程", False, RULE),
    ("招标代理合同.pdf", "pdf", None, "咨询服务合同", None, False, RULE),
    ("补遗书二.pdf", "pdf", None, "答疑补遗", "招标控制价", False, RULE),
    ("图纸会审及答疑纪要.pdf", "pdf", None, "图纸会审", None, False, RULE),  # 答疑 exclude_any:[会审]
    ("竣工验收报告.pdf", "pdf", None, "竣工验收报告", "结算", False, RULE),
    ("可研批复.pdf", "pdf", None, "项目立项", "概算", False, RULE),
    ("初步设计概算批复.pdf", "pdf", None, "项目立项", "概算", False, RULE),
    ("结算定案表.xlsx", "xlsx", None, "审定单", "审定", False, RULE),
    ("结算审核报告.pdf", "pdf", None, "审核报告", "审定", False, RULE),     # #210 不回退
    # —— 黑名单：升档词补「签证/费用/合同价/合同」、疑词降为待复核 ——
    ("桩基检测费用签证单.pdf", "pdf", None, "变更签证费用", "施工过程", True, BARE),
    ("专业分包工程合同.pdf", "pdf", None, None, None, True, None),
    ("桩基检测报价单.pdf", "pdf", None, None, None, True, None),     # 黑名单+疑词「价」→ skip/0.6/待复核
    ("见证取样费.pdf", "pdf", None, None, None, True, None),         # 黑名单+疑词「费」
    ("施工日志.docx", "docx", None, None, None, False, None),        # 纯黑名单 → 确定跳过(不变)
    # —— 回归：已有行为不变 ——
    ("建筑工程施工许可证.pdf", "pdf", None, "施工许可", None, False, RULE),
    ("现场照片001.jpg", "jpg", None, "前期现场照片", None, False, RULE),
    ("招标控制价编制说明.docx", "docx", None, "招标控制价", "招标控制价", False, RULE),
]


@pytest.mark.parametrize("name,ext,anc,cat,stage,manual,evidence", CASES,
                         ids=[f"{c[0]}|{'/'.join(c[2] or [])}" for c in CASES])
def test_ws13_rule_cases(name, ext, anc, cat, stage, manual, evidence):
    o = _one(name, ext, anc)
    got = (o.doc_category, o.needs_manual, o.evidence)
    assert got == (cat, manual, evidence), f"{name}: 实 {got} reason={o.reason}"
    if stage is not ...:
        assert o.cost_stage == stage, f"{name}: 阶段实 {o.cost_stage} reason={o.reason}"


def test_categoryless_outcomes_never_carry_confidence():
    """空类目（除确定跳过外）一律 conf=0、needs_manual=True：
    旧口径是 archive/None/0.95/False —— 一个「很确定地没有类目」的自信标签。"""
    for name, ext in [("建筑做法参考.pdf", "pdf"), ("IMG_20260601_1234.jpg", "jpg"),
                      ("专业分包工程合同.pdf", "pdf"), ("X.SSQ6", "SSQ6")]:
        o = _one(name, ext)
        assert o.doc_category is None
        assert o.confidence == 0.0, f"{name} conf={o.confidence}"
        assert o.needs_manual is True, name


def test_categoryless_professional_word_reason_is_explicit():
    o = _one("建筑做法参考.pdf", "pdf")
    assert o.disposition == "archive"
    assert "仅命中专业词「建筑」" in o.reason


def test_bare_tier_confidence_band():
    """bare 层出厂 0.65 + 待复核；specific 仍 0.85 + 直出。"""
    bare = _one("某某建筑工程结算书.pdf", "pdf")
    spec = _one("施工图预算书.xlsx", "xlsx")
    assert bare.confidence == pytest.approx(0.65)
    assert spec.confidence == pytest.approx(0.85)


def test_blacklist_doubt_is_manual_skip():
    o = _one("桩基检测报价单.pdf", "pdf")
    assert (o.disposition, o.confidence, o.needs_manual) == ("skip", pytest.approx(0.6), True)
    assert "疑词" in o.reason


def test_blacklist_plain_skip_unchanged():
    o = _one("施工日志.docx", "docx")
    assert (o.disposition, o.confidence, o.needs_manual) == ("skip", pytest.approx(0.9), False)


# ---------- _hit 的语境判断（规则层单元）----------

def _rule(pattern: str, kind: str = "whitelist") -> Rule:
    rows = [r for r in _RULES[kind] if r.pattern == pattern]
    assert len(rows) == 1, f"规则「{pattern}」应恰好 1 条，实 {len(rows)}"
    return rows[0]


def test_hit_exclude_any():
    r = _rule("招标")
    assert r.tier == "bare"
    assert _hit(r, "招标文件.pdf")
    assert not _hit(r, "招标代理合同.pdf")


def test_hit_veto_ancestors():
    r = _rule("清单")
    assert _hit(r, "分部分项清单.xlsx", ("4 招标文件及清单(控制价)",))
    assert not _hit(r, "分部分项清单.xlsx", ("第3期", "22 进度款审核及付款建议"))


def test_hit_require_any_reads_ancestors():
    r = _rule("汇总")
    assert not _hit(r, "汇总表.xlsx")
    assert _hit(r, "汇总表.xlsx", ("结算审核",))


# ---------- P10：计价软件扩展名 ----------

@pytest.mark.parametrize("name,ext,anc,cat,stage", [
    ("(10月进度款)XX工程.清单审计", "清单审计", ["22 进度款审核及付款建议"], "进度款支付", "施工过程"),
    ("X.yss", "yss", ["5 投标文件"], "投标文件", "招标控制价"),
    ("X.SSQ6", "SSQ6", None, None, None),
])
def test_pricing_software_exts_pending_export(name, ext, anc, cat, stage):
    o = _one(name, ext, anc)
    assert o.disposition == "pending_export", f"{name}: {o.disposition} {o.reason}"
    assert o.doc_category == cat
    assert o.cost_stage == stage
    assert o.needs_manual is True
    assert o.evidence == (INHERIT if cat else None)
