"""WS04-P1：旁车按格式解析（QA:text-ocr-01 / R1:ENG-27 / R1:OCR-08 / QA:text-ocr-07）。

生产 2882 份 `.ocr.txt` 全是分页格式，754 份一页可用的都没有。旧实现只判 `text.strip()`：
全失败旁车被当成正文命中（OCR 服务一次都没调），可用旁车的卷头「原始路径」、逐页判定行、
占位句、OTSL `<fcel>` 标记、复读内容原样送进 LLM。

夹具见 tests/textextract/ws04_fixtures.py（行格式逐字照抄生产落盘模板，不含客户数据）：
F1 两页全 failed + 质量存疑；F2 混合五页；F3 只有 empty/garbled；F4 只有卷头；F5 旧式纯文本。
"""
from __future__ import annotations

import logging

import pytest

from tests.textextract import ws04_fixtures as fx
from zt.sidecar import parse_ocr_sidecar, read_sidecar_doc, read_sidecar_text


@pytest.fixture
def ocr_dir(tmp_path):
    return tmp_path


def read_ocr_sidecar(path):
    return read_sidecar_text(path, path.parent)


def read_ocr_sidecar_doc(path):
    return read_sidecar_doc(path, path.parent)


# ---------------------------------------------------------------- 可用性判定


@pytest.mark.parametrize("name,text", [("F1", fx.F1), ("F3", fx.F3), ("F4", fx.F4)])
def test_no_usable_page_means_unusable(name, text):
    doc = parse_ocr_sidecar(text)
    assert doc.fmt == "paged", name
    assert doc.usable is False, name
    assert doc.usable_pages == []


def test_f1_header_parsed():
    doc = parse_ocr_sidecar(fx.F1)
    assert doc.declared_pages == 2
    assert doc.ocr_pages == 2
    assert doc.engine == "paddleocr-vl-1.6"
    assert doc.quality_suspect is True
    assert doc.suspect_ratio == pytest.approx(1.0)
    assert doc.source_path == "投控项目/示例项目/外架拆除完成时间确认表.pdf"
    assert [p.verdict for p in doc.pages] == ["failed", "failed"]
    assert [p.placeholder for p in doc.pages] == ["failed", "failed"]


def test_f2_usable_pages():
    doc = parse_ocr_sidecar(fx.F2)
    assert doc.usable is True
    assert doc.usable_pages == [1, 3, 5]


def test_render_has_no_header_metadata():
    """卷头（原始路径 = 客户目录结构）、逐页判定行、占位句都不进正文。"""
    out = parse_ocr_sidecar(fx.F2).render_text()
    for banned in ("原始路径", "判定 ", "连续失败", "自带文字层，未做 OCR", "> 类型:",
                   "本文件由扫描件 OCR 得到", "正文转义"):
        assert banned not in out, banned
    assert "外架" not in out and "结算审核报告.pdf" not in out


def test_otsl_rendered_as_rows():
    out = parse_ocr_sidecar(fx.F2).render_text()
    for tag in ("<fcel>", "<lcel>", "<nl>", "<ecel>", "<br>", "<sup>"):
        assert tag not in out, tag
    assert "序号 | 单位工程 | 审定金额（元）" in out
    assert "1 | 土建 工程 | 18601" in out
    # <lcel> 是跨格：记为空格子，列位不塌
    assert "合计 |  | 18601注" in out
    assert "审定汇总 |  | " in out


def test_escaped_body_restored():
    out = parse_ocr_sidecar(fx.F2).render_text()
    lines = out.splitlines()
    assert "# 3楼" in lines
    assert "> 引用行" in lines
    assert "@@ 标记行" in lines
    assert " # 3楼" not in lines


def test_repetition_folded_on_repetitive_page():
    out = parse_ocr_sidecar(fx.F2).render_text()
    assert out.count(fx.REPEATED_SENTENCE) <= 2
    assert "工程款支付申请表" in out  # 复读前的真内容保留


def test_annotations_on_anchor_lines():
    out = parse_ocr_sidecar(fx.F2).render_text()
    lines = out.splitlines()
    assert "## p2 ｜旁车 OCR 未取得正文" in lines
    assert "## p4 ｜旁车未做 OCR（原件该页自带文字层）" in lines
    p5 = next(ln for ln in lines if ln.startswith("## p5"))
    assert "大写金额与小写金额不符" in p5
    p3 = next(ln for ln in lines if ln.startswith("## p3"))
    assert "复读" in p3
    assert lines[0].startswith("# ⚠ OCR 质量存疑")


def test_consecutive_unusable_pages_merged():
    text = fx.paged_sidecar([("ok", ["第一页正文足够长的一句话"])]
                            + [("failed", [])] * 7
                            + [("ok", ["第九页正文"])])
    out = parse_ocr_sidecar(text).render_text()
    assert "## p2–p8 ｜旁车 OCR 未取得正文" in out.splitlines()


def test_f5_legacy_verbatim():
    doc = parse_ocr_sidecar(fx.F5)
    assert doc.fmt == "legacy"
    assert doc.usable is True
    assert doc.render_text() == fx.F5


def test_ok_numeric_rows_not_collapsed():
    """负控：ok 页上 30 行「钢筋 HRB400 Φ1x t n.nnn」同模板不同数字，一行都不许删。"""
    doc = parse_ocr_sidecar(fx.REBAR)
    out = doc.render_text()
    for row in fx.REBAR_ROWS:
        assert row in out, row
    # 只打标，不删
    assert "suspected_repetition" in doc.pages[0].flags


def test_placeholder_only_page_without_meta_is_unusable():
    """缺判定行的页（罕见的畸形旁车）只剩占位句时，占位句不能被当正文让整份「命中」。"""
    text = fx.header("畸形.pdf", 1) + "\n## p1\n" + fx.FAILED_LINE + "\n"
    doc = parse_ocr_sidecar(text)
    assert doc.fmt == "paged"
    assert doc.pages[0].verdict is None
    assert doc.pages[0].placeholder == "failed"
    assert doc.usable is False


def test_non_whitelisted_quote_lines_kept_as_body():
    """白名单以外的 `> ` 行一律当正文保留，不猜。"""
    text = fx.paged_sidecar([("ok", ["> 这行没有被转义但也不在白名单里", "正文"])])
    out = parse_ocr_sidecar(text).render_text()
    assert "> 这行没有被转义但也不在白名单里" in out


# ---------------------------------------------------------------- read_ocr_sidecar（自动生效层）


def test_all_failed_not_a_hit(ocr_dir, caplog):
    """F1 形状的旁车（生产 754 份）：read_ocr_sidecar 判未命中，并点名各类页数。"""
    (ocr_dir / "外架拆除完成时间确认表.pdf").write_bytes(b"%PDF-1.4 stub")
    (ocr_dir / "外架拆除完成时间确认表.pdf.ocr.txt").write_text(fx.F1, encoding="utf-8")
    rel = ocr_dir / "外架拆除完成时间确认表.pdf"
    with caplog.at_level(logging.WARNING, logger="zt.sidecar"):
        assert read_ocr_sidecar(rel) is None
    assert "failed" in caplog.text
    # 结构化入口仍能拿到它（页级降级链要知道「有旁车但每页都失败」）
    hit = read_ocr_sidecar_doc(rel)
    assert hit is not None and hit[0].usable is False


def test_usable_sidecar_hit_returns_cleaned_text(ocr_dir):
    (ocr_dir / "结算审核报告.pdf").write_bytes(b"%PDF-1.4 stub")
    (ocr_dir / "结算审核报告.pdf.ocr.txt").write_text(fx.F2, encoding="utf-8")
    hit = read_ocr_sidecar(ocr_dir / "结算审核报告.pdf")
    assert hit is not None
    text, name = hit
    assert name == "结算审核报告.pdf.ocr.txt"
    assert "原始路径" not in text and "<fcel>" not in text and "判定 " not in text
    assert "工程造价审定单" in text


def test_unusable_appended_falls_back_to_replaced_candidate(ocr_dir):
    """追加式候选一页可用都没有时，仍看替换式候选（与旧实现「空白旁车找下一个」一致）。"""
    (ocr_dir / "双份.pdf").write_bytes(b"%PDF-1.4 stub")
    (ocr_dir / "双份.pdf.ocr.txt").write_text(fx.F1, encoding="utf-8")
    (ocr_dir / "双份.ocr.txt").write_text("替换式旧旁车正文", encoding="utf-8")
    hit = read_ocr_sidecar(ocr_dir / "双份.pdf")
    assert hit == ("替换式旧旁车正文", "双份.ocr.txt")
