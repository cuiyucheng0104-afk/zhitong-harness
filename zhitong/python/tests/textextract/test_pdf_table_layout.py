"""WS04-P11（issue #774 / QA:text-ocr-04 的 PDF 部分）：PDF 表格页按版面抽取，空列不再塌缩。

pypdf 默认抽取把表格里的空格子压掉：生产 R04 工程量、单价两列为空时合价直接贴在项目名后面；
R06 每行末尾的数值个数比表头列数少 —— 按表头读列就错位（铁律 2/3：金额读进了别的列）。

表格页（≥5 行、每行 ≥3 个数值）改用 `extraction_mode="layout"`，按数值行的版面位置切出
列网格，空格子留 ` |  | ` 空位。启发式方案，开关 `table_layout` 默认关（spec：生产抽样
达标前默认关闭）。PDF 全在测试里按坐标现造（Helvetica，不含客户数据）；版面文本的纯函数
用例照本机真实计价表 PDF 的 layout 输出形状手写（多行格、上标单位、本页小计行、末列空）。
"""
from __future__ import annotations

import io
import re

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject

from tests.textextract.ws04_fixtures import _font, _set_content, add_text_page
from zt.textextract.extract import extract_document, load_document
from zt.textextract.pdf import (
    classify_pdf_pages,
    pdf_page_text,
    pdf_page_texts,
)

COLS = [40, 90, 260, 330, 400, 480]
HEAD = ["No", "Item", "Unit", "Qty", "Price", "Amount"]
ROWS = [
    ["1", "Excavation", "m3", "120.50", "35.20", "4241.60"],
    ["2", "Backfill", "m3", "", "", "1830.00"],          # 工程量、单价两列空（R04 形状）
    ["3", "Concrete C30", "m3", "88.00", "512.00", "45056.00"],
    ["4", "Rebar HRB400", "t", "12.30", "4350.00", "53505.00"],
    ["5", "Formwork", "m2", "", "46.00", "9200.00"],
    ["6", "Waterproof", "m2", "310.00", "", "12400.00"],
]


def add_table_page(w: PdfWriter, rows: list[list[str]], *, head: list[str] | None = HEAD,
                   title: str | None = "BILL OF QUANTITIES", footer: str | None = "Page 1 of 2",
                   cols: list[int] = COLS) -> None:
    """按坐标画表：每个格子一个 BT…ET，空格子不画（真实计价表 PDF 就是这样）。"""
    pg = w.add_blank_page(595, 842)
    ops: list[bytes] = []
    y = 800
    if title:
        ops.append(f"BT /F1 12 Tf 200 {y} Td ({title}) Tj ET".encode())
        y -= 30
    for row in ([head] if head else []) + rows:
        for x, cell in zip(cols, row):
            if cell:
                ops.append(f"BT /F1 9 Tf {x} {y} Td ({cell}) Tj ET".encode())
        y -= 18
    if footer:
        ops.append(f"BT /F1 8 Tf 260 40 Td ({footer}) Tj ET".encode())
    res = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): _font(w)})})
    _set_content(w, pg, b"\n".join(ops), res)


def pdf_bytes(*builders) -> bytes:
    w = PdfWriter()
    for b in builders:
        b(w)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def table_pdf(rows=ROWS, **kw) -> bytes:
    return pdf_bytes(lambda w: add_table_page(w, rows, **kw))


_AMOUNT = re.compile(r"\d\.\d\d(?!\d)")


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.split("|")]


def texts(content: bytes, table_layout: bool = True):
    return pdf_page_texts(content, table_layout=table_layout)


# =============================================================================
# spec 验收：带空列的表输出空格位
# =============================================================================


def test_empty_columns_keep_slots():
    """spec P11 验收：按坐标造一张带空列的表，输出里出现空格位 ` |  | `。"""
    page = texts(table_pdf())[0]
    assert "layout_table" in page.flags
    lines = page.text.splitlines()
    backfill = next(ln for ln in lines if "Backfill" in ln)
    assert " |  | " in backfill
    assert cells(backfill) == ["2", "Backfill", "m3", "", "", "1830.00"]
    assert cells(next(ln for ln in lines if "Formwork" in ln)) == ["5", "Formwork", "m2", "", "46.00", "9200.00"]
    assert cells(next(ln for ln in lines if "Waterproof" in ln)) == [
        "6", "Waterproof", "m2", "310.00", "", "12400.00"]


def test_every_amount_row_has_header_column_count():
    """生产抽样口径的本机版：含金额的行，格子数与表头列数一致的占比（这里要求 100%）。"""
    text = texts(table_pdf())[0].text
    rows = [ln for ln in text.splitlines() if _AMOUNT.search(ln)]
    assert len(rows) == len(ROWS)
    assert all(len(cells(r)) == len(HEAD) for r in rows)


def test_default_extraction_collapses_empty_columns():
    """复现（开关关着 = 旧行为）：默认抽取把两列空格子压掉，看不出空的是哪两列。"""
    text = texts(table_pdf(), table_layout=False)[0].text
    assert "2 Backfill m3 1830.00" in text
    assert "|" not in text


def test_trailing_empty_column_keeps_slot():
    """末列（暂估价）只有一行有值：投票投不出来，按稀疏列自成一列；其余行末尾留空位，格子数一致。"""
    cols = COLS + [535]
    rows = [r + (["500.00"] if i == 0 else [""]) for i, r in enumerate(ROWS)]
    text = texts(table_pdf(rows, head=HEAD + ["Prov"], cols=cols))[0].text
    amount_rows = [ln for ln in text.splitlines() if "m3" in ln or "m2" in ln or " t " in f" {ln} "]
    assert amount_rows and all(len(cells(ln)) == 7 for ln in amount_rows)
    assert cells(next(ln for ln in text.splitlines() if "Backfill" in ln))[-1] == ""


def test_title_and_footer_lines_not_gridded():
    text = texts(table_pdf())[0].text
    assert "BILL OF QUANTITIES" in text
    assert "Page 1 of 2" in text


# =============================================================================
# 表格页判定：≥5 行、每行 ≥3 个数值
# =============================================================================


def test_four_numeric_rows_is_not_a_table():
    """恰好 4 行各有 ≥3 个数（Backfill 那行只有 2 个数，不能算进来，否则夹具到不了边界）。"""
    four = [ROWS[0], ROWS[2], ROWS[3], ROWS[4]]
    assert sum(1 for r in four if sum(bool(c) and c[0].isdigit() for c in r) >= 3) == 4
    page = texts(table_pdf(four))[0]
    assert "layout_table" not in page.flags
    assert "|" not in page.text


def test_prose_page_untouched():
    content = pdf_bytes(lambda w: add_text_page(w, "Contract terms 2026", extra_lines=[
        "Payment within 30 days of invoice.", "Retention 5 percent.", "Warranty 2 years."]))
    page = texts(content)[0]
    assert page.flags == () and "|" not in page.text


def test_switch_off_by_default():
    assert "layout_table" not in pdf_page_texts(table_pdf())[0].flags
    assert "layout_table" not in extract_document(table_pdf(), "pdf").quality_flags


def test_explicit_flag_turns_layout_on():
    """按调用显式打开，不依赖环境变量。"""
    page = PdfReader(io.BytesIO(table_pdf())).pages[0]
    text, flags = pdf_page_text(page, table_layout=True)
    assert flags == ("layout_table",) and " |  | " in text


# =============================================================================
# 完整性闸：layout 模式丢字就退回默认抽取（铁律 8：退化要可见）
# =============================================================================


def test_layout_losing_characters_falls_back(monkeypatch):
    """layout 模式整块丢字（本机 159 个真实表格页里有 3 页）：丢的是文字、数字一个没少 ——
    只有字符闸拦得住（数字串闸看不出来）。"""
    page = PdfReader(io.BytesIO(table_pdf())).pages[0]
    real = page.extract_text

    def lossy(*a, **kw):
        out = real(*a, **kw)
        return out.replace("Excavation", "") if kw.get("extraction_mode") == "layout" else out

    monkeypatch.setattr(page, "extract_text", lossy)
    text, flags = pdf_page_text(page, table_layout=True)
    assert flags == ("layout_table_mismatch",)
    assert "Excavation" in text and "|" not in text


def test_layout_exception_falls_back(monkeypatch):
    page = PdfReader(io.BytesIO(table_pdf())).pages[0]
    real = page.extract_text

    def boom(*a, **kw):
        if kw.get("extraction_mode") == "layout":
            raise ValueError("font widths missing")
        return real(*a, **kw)

    monkeypatch.setattr(page, "extract_text", boom)
    text, flags = pdf_page_text(page, table_layout=True)
    assert flags == ("layout_table_failed",) and "1830.00" in text


# =============================================================================
# 表格跨页 + 各出口
# =============================================================================


def two_page_table() -> bytes:
    """表格跨页：第 2 页续表没有表头、行数也够 5 行。"""
    more = [[str(7 + i), f"Item{7 + i}", "m2", "" if i % 2 else f"{10 + i}.00", "8.00", f"{80 + i}.00"]
            for i in range(5)]
    return pdf_bytes(lambda w: add_table_page(w, ROWS),
                     lambda w: add_table_page(w, more, head=None, title=None, footer="Page 2 of 2"))


def test_cross_page_table_each_page_gridded():
    pages = texts(two_page_table())
    assert [("layout_table" in p.flags) for p in pages] == [True, True]
    p2 = [ln for ln in pages[1].text.splitlines() if "Item" in ln]
    assert len(p2) == 5 and all(len(cells(ln)) == 6 for ln in p2)
    assert cells(next(ln for ln in p2 if "Item8" in ln)) == ["8", "Item8", "m2", "", "8.00", "81.00"]


def test_page_flag_reaches_doc_quality_flags():
    infos, flags = classify_pdf_pages(texts(two_page_table()))
    assert all("layout_table" in p.flags for p in infos)
    assert "layout_table_pages:2" in flags
    doc = extract_document(two_page_table(), "pdf", table_layout=True)
    assert "layout_table_pages:2" in doc.quality_flags
    assert "8 | Item8 | m2 |  | 8.00 | 81.00" in doc.text


def test_load_document_carries_layout_flag(tmp_path):
    (tmp_path / "计价表.pdf").write_bytes(two_page_table())
    doc = load_document(tmp_path, "计价表.pdf", table_layout=True)
    assert doc.failure is None and doc.pages_text_layer == [1, 2]
    assert "layout_table_pages:2" in doc.quality_flags
    assert "2 | Backfill | m3 |  |  | 1830.00" in doc.text
