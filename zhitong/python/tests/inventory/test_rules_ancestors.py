"""迁移自旧仓 engine-service/tests/test_classify_ancestors.py；未迁移其中按 rel_path 走 /engine/tag/classify 端点的用例。

WS13-P02：只看直属父目录、继承词表过窄、「控制价」抢在「招标」前面（issue #720）。

复现基线（origin/dev d25a4637）：
  - tag.py 只取 Path(rel_path).parent.name —— 真正有语义的「22 进度款审核及付款建议」
    在三层之上时用不上；
  - `说明.pdf` 放在「4 招标文件及清单(控制价)」下 → 继承成 **招标控制价**（控制价 p53 先于 招标 p55）；
  - `保电费用联系单.pdf` 放在「11 工程联系单及工程签证」下 → skip/None（继承词表里没有签证/联系单）。

三种形态都要够到：三层深且中间隔一层 .zip.解压、同一段里特指先于泛指、新词表。
"""
from __future__ import annotations

import pytest

from tests.inventory._support import engine
from zt.inventory.rules import ClassifyInput


def _one(name: str, ext: str, ancestors):
    return engine.classify_one(ClassifyInput("f1", name, ext, ancestors=ancestors, has_text_layer=True))


def test_three_levels_deep_through_zip_folder():
    """验工计价文件直属父目录是「…计价报告整理（第1-18期）」，中间还隔一层 .zip.解压；
    有语义的「22 进度款审核及付款建议」在第 3 层。只看 ancestors[0] 就判不出来。"""
    anc = ["某广场03.zip.解压", "某广场计价报告整理（第1-18期）", "22 进度款审核及付款建议"]
    o = _one("某广场03.xlsx", "xlsx", anc)
    assert (o.doc_category, o.cost_stage) == ("进度款支付", "施工过程"), o.reason
    assert o.needs_manual is True
    assert o.evidence == "ancestor_inherit"
    assert o.confidence == pytest.approx(0.6)          # max(0.6, 0.7 − 0.05×2)
    assert "第3层" in o.reason and "22 进度款审核及付款建议" in o.reason


def test_specific_folder_word_beats_generic_within_one_segment():
    """同一段里「招标文件」(p10) 先于「控制价」(p20)：说明.pdf 是招标文件，不是招标控制价。"""
    o = _one("说明.pdf", "pdf", ["4 招标文件及清单(控制价)"])
    assert o.doc_category == "招标文件", o.reason
    assert o.cost_stage == "招标控制价"
    assert o.needs_manual is True
    assert o.confidence == pytest.approx(0.7)          # 直属父目录，深度 0


def test_new_inherit_vocabulary_visa_folder():
    o = _one("保电费用联系单.pdf", "pdf", ["11 工程联系单及工程签证"])
    assert (o.doc_category, o.cost_stage, o.needs_manual) == ("变更签证费用", "施工过程", True), o.reason
    assert o.evidence == "ancestor_inherit"


@pytest.mark.parametrize("folder,cat", [
    ("5 付款支付审核", "进度款支付"),
    ("3 招标控制价", "招标控制价"),
    ("6 投标文件", "投标文件"),
    ("4 合同及协议", "施工合同及补充协议"),
    ("8 结算审核", "结算价文件"),
])
def test_inherit_vocabulary(folder, cat):
    o = _one("附件1.pdf", "pdf", [folder])
    assert o.doc_category == cat, o.reason


def test_nearest_ancestor_wins():
    """由近及远，第一个命中就用：近处的「签证」压过远处的「进度款」。"""
    o = _one("附件1.pdf", "pdf", ["2 签证单", "22 进度款审核及付款建议"])
    assert o.doc_category == "变更签证费用", o.reason


def test_parent_dir_only_still_works():
    """旧调用方只传 parent_dir：等价于 ancestors=[parent_dir]。"""
    o = engine.classify_one(ClassifyInput("f1", "附件1.pdf", "pdf", parent_dir="11 工程联系单及工程签证"))
    assert o.doc_category == "变更签证费用"


def test_whitelist_stage_inherits_along_ancestor_chain():
    """规则行没写阶段（如「造价咨询」）时，阶段沿祖先链取，而不是只看直属父目录。"""
    o = _one("造价咨询意见.docx", "docx", ["往来函件", "8 结算审核"])
    assert o.doc_category == "造价综合文件"
    assert o.cost_stage == "结算", o.reason
