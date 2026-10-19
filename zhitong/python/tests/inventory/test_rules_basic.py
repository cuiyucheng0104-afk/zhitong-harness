"""迁移自旧仓 engine-service/tests/test_classify_rules.py；未迁移其中依赖 FastAPI 端点与 LLM 兜底的用例。

分类规则引擎缺陷回归：archive_ext 截胡 + 无类目关键词压过有类目关键词。

缺陷一（archive_ext 截胡）：classify_one 的 archive_ext 循环命中即 return，而
jpg/jpeg/png 在 YAML 里 doc_category=None 又不在 cad_drawing_exts → 任何图片一律
cat=None 直接返回，永远走不到 archive_keyword 步骤 → 齐套核查按类目匹配不上，缺件误报。

缺陷二（无类目关键词截胡有类目关键词，YAML 真数据已实证）：
「建筑」priority 40 无类目排在「施工许可」priority 87 有类目之前，
`建筑工程施工许可证.pdf` 命中「建筑」即返回 cat=None。修正为：命中时优先选带
doc_category 的那条。

端点级测试断言 source == "rule"：环境里配了 DeepSeek key 时，规则层退化会被 LLM
兜底"猜对答案"掩盖——这里把 classify_llm.suggest 打成毒丸（返回可识别的假类目），
规则层一旦退化 source 会翻成 "llm"、类目变成毒丸值，测试必然红。
"""
from __future__ import annotations

import pytest

from tests.inventory._support import engine
from zt.inventory.rules import ClassifyInput


def _one(name: str, ext: str, parent: str | None = None):
    return engine.classify_one(ClassifyInput("f1", name, ext, parent_dir=parent))


# ---------- 缺陷一：图片扩展名须补查 archive_keyword ----------

@pytest.mark.parametrize("name,ext,want_cat", [
    ("现场照片001.jpg", "jpg", "前期现场照片"),
    ("隐蔽工程验收照片.png", "png", "隐蔽记录"),        # 同时命中「照片」(无类目)与「隐蔽」(有类目)
    ("竣工图-总平面.jpeg", "jpeg", "竣工图"),
    ("地勘报告扫描件.jpg", "jpg", "地质勘察报告"),
    ("会议纪要2026-05.png", "png", "会议纪要·联系函"),
])
def test_image_ext_falls_through_to_archive_keyword(name, ext, want_cat):
    o = _one(name, ext)
    assert o.disposition == "archive"
    assert o.doc_category == want_cat
    assert o.confidence == pytest.approx(0.95)


@pytest.mark.parametrize("name,ext", [
    ("IMG_20260601_1234.jpg", "jpg"),
    ("DSC00123.png", "png"),
])
def test_image_without_keyword_stays_uncategorized(name, ext):
    """不瞎补：图片名里没有任何归档关键词时，类目仍为 None、照旧归档。"""
    o = _one(name, ext)
    assert o.disposition == "archive"
    assert o.doc_category is None


# ---------- 缺陷二：有类目关键词须压过先命中的无类目关键词 ----------

def test_keyword_with_category_beats_earlier_categoryless():
    # 「建筑」p40 无类目 vs 「施工许可」p87 有类目（YAML 真数据）
    o = _one("建筑工程施工许可证.pdf", "pdf")
    assert o.disposition == "archive"
    assert o.doc_category == "施工许可"


def test_categoryless_keyword_alone_is_explicitly_manual():
    """只命中无类目关键词：仍归档、类目 None（pdf 不在 archive_kw_ext_skip），但**不再自信**。

    WS13-P01（issue #720）之前这里钉的是 archive/None/0.95/needs_manual=False —— 一条
    「很确定地没有类目」的标签；而同一个「建筑」会把 `某某建筑工程结算书.pdf` 截成空类目。
    现在无类目专业词不终止判定（排到 ⑫），只命中它时 conf=0、明示待复核。"""
    o = _one("建筑做法参考.pdf", "pdf")
    assert o.disposition == "archive"
    assert o.doc_category is None
    assert o.confidence == 0.0
    assert o.needs_manual is True
    assert "建筑" in o.reason


# ---------- 回归：CAD / needs_export / 黑名单行为不变 ----------

def test_cad_subtype_unchanged():
    o = _one("建筑平面图.dwg", "dwg")
    assert o.disposition == "archive"
    assert o.doc_category == "建筑平面图"
    o2 = _one("随手拍.dwg", "dwg")
    assert o2.doc_category == "设计图纸"  # 无专业词 → CAD 默认类目，不走关键词补查


def test_needs_export_unchanged():
    o = _one("某项目.gbq7", "gbq7")
    assert o.disposition == "pending_export"
    assert o.doc_category is None


def test_blacklist_unchanged():
    o = _one("施工日志.docx", "docx")
    assert o.disposition == "skip"
