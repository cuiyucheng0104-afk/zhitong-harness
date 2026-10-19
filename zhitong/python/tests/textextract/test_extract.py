"""统一出口 ``extract_document``：各格式、失败码、旁车文件当文本送入。

新写（旧仓无对应文件，旧用例散在 test_textextract_*）。
"""
from __future__ import annotations

import io
import zipfile

import pytest
from openpyxl import Workbook
from pypdf import PdfWriter

from tests.textextract import ws04_fixtures as fx
from zt.textextract.extract import cap_chars, extract_document, extract_text
from zt.textextract.model import DocText, PageInfo
from zt.textextract.office import _soffice_bin


def _docx(paragraphs: list[str]) -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def _pptx(slides: list[list[str]]) -> bytes:
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, paras in enumerate(slides, start=1):
            body = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in paras)
            z.writestr(f"ppt/slides/slide{i}.xml", f'<p:sld xmlns:p="x" xmlns:a="{a}"><p:cSld>{body}</p:cSld></p:sld>')
    return buf.getvalue()


def _xlsx(rows: list[list[object]]) -> bytes:
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- 成功路径


def test_txt_utf8_and_gbk():
    assert extract_document("合同金额 100 万元\n".encode("utf-8"), "txt").text == "合同金额 100 万元"
    doc = extract_document("取土及动探孔".encode("gb18030"), ".TXT")
    assert doc.text == "取土及动探孔" and doc.text_source == "text_layer"


def test_docx_text_layer():
    doc = extract_document(_docx(["第一段", "第二段"]), "docx", file_name="a.docx")
    assert doc.text == "第一段\n第二段" and doc.complete and doc.text_source == "text_layer"


def test_xlsx_column_coordinates_and_hidden_sheet():
    doc = extract_document(_xlsx([["项目", None, "金额"], [None, "x", 12.5]]), "xlsx")
    assert "[R1] A:项目\tC:金额" in doc.text and "[R2] B:x\tC:12.5" in doc.text


def test_pptx_slides():
    doc = extract_document(_pptx([["封面标题"], ["第二页", "要点"]]), "pptx")
    assert doc.text.splitlines() == ["## 幻灯片 1", "封面标题", "## 幻灯片 2", "第二页", "要点"]


def test_pdf_text_layer_only():
    doc = extract_document(fx.build_pdf(["text", "text"]), "pdf")
    assert doc.pages_text_layer == [1, 2] and doc.complete
    assert "[p1]" in doc.text and "[p2]" in doc.text


def test_sidecar_file_sent_as_document_is_cleaned():
    doc = extract_document(fx.F2.encode("utf-8"), "txt", file_name="结算审核报告.pdf.ocr.txt")
    assert doc.text_source == "ocr_sidecar" and doc.ocr_derived
    assert "原始路径" not in doc.text and "工程造价审定单" in doc.text
    # 被当作普通 .txt 送进来的旁车同样按旁车清洗
    doc2 = extract_document(fx.F2.encode("utf-8"), "txt", file_name="x.txt")
    assert doc2.text_source == "ocr_sidecar"


# ---------------------------------------------------------------- 失败码（抽不出必须带原因）


@pytest.mark.parametrize("content,ext,name,code", [
    (b"", "pdf", "空.pdf", "empty_file"),
    (b"\xff\xfe\x00", "txt", "坏.txt", "undecodable"),
    (b"   \n ", "txt", "空白.txt", "no_text"),
    (b"MZ", "exe", "x.exe", "unsupported_format"),
    (b"", "", "", "empty_file"),
    (b"\xff\xd8\xff", "jpg", "现场.jpg", "needs_vision"),
    (b"not a zip", "docx", "坏.docx", "parse_failed"),
    (b"not a pdf", "pdf", "坏.pdf", "parse_failed"),
])
def test_failure_codes(content, ext, name, code):
    doc = extract_document(content, ext, file_name=name)
    assert doc.text == "" and doc.text_source == "none"
    assert doc.failure is not None and doc.failure.code == code, doc.failure


def test_index_md_is_derived_artifact():
    body = "<!-- generated-by: scripts/build_source_index.py -->\n# 目录\n".encode("utf-8")
    doc = extract_document(body, "md", file_name="INDEX.md")
    assert doc.failure.code == "derived_artifact"
    assert extract_document("# 手写笔记\n内容".encode("utf-8"), "md", file_name="笔记.md").text.startswith("# 手写笔记")


def test_encrypted_pdf_reports_encrypted():
    w = PdfWriter()
    w.add_blank_page(100, 100)
    w.encrypt(user_password="pw", owner_password="o", algorithm="RC4-128")
    buf = io.BytesIO()
    w.write(buf)
    assert extract_document(buf.getvalue(), "pdf").failure.code == "encrypted"


def test_ole_disguised_as_docx():
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    assert extract_document(ole, "docx").failure.code == "parse_failed"
    assert extract_document(ole, "xlsx").failure.code == "parse_failed"


def test_all_empty_docx_is_no_text():
    assert extract_document(_docx([]), "docx").failure.code == "no_text"


@pytest.mark.skipif(_soffice_bin() is None, reason="本机没有 soffice：跳过 ≠ 通过")
def test_legacy_doc_and_xls_through_soffice():
    from zt.textextract.office import libreoffice_convert_ex

    import docx  # python-docx：soffice 需要完整的 OOXML 包，手拼的最小 zip 打不开

    d = docx.Document()
    d.add_paragraph("老格式正文")
    buf = io.BytesIO()
    d.save(buf)
    doc_bytes, why = libreoffice_convert_ex(buf.getvalue(), "docx", "doc")
    assert doc_bytes is not None, why
    doc = extract_document(doc_bytes, "doc", file_name="a.doc")
    assert doc.failure is None and "老格式正文" in doc.text and "converted_from_doc" in doc.quality_flags
    xls_bytes, why = libreoffice_convert_ex(_xlsx([["甲", 1]]), "xlsx", "xls")
    assert xls_bytes is not None, why
    sheet = extract_document(xls_bytes, "xls", file_name="a.xls")
    assert sheet.failure is None and "A:甲" in sheet.text and "converted_from_xls" in sheet.quality_flags


def test_soffice_missing_reports_convert_failed(monkeypatch):
    monkeypatch.setattr("zt.textextract.office._soffice_bin", lambda: None)
    doc = extract_document(b"\xd0\xcf\x11\xe0 fake doc", "doc")
    assert doc.failure.code == "convert_failed" and "soffice" in doc.failure.detail


# ---------------------------------------------------------------- 兼容出口与字数上限


def test_extract_text_returns_empty_string_on_failure():
    assert extract_text(b"MZ", "exe") == ""
    assert extract_text(_docx(["正文"]), "docx") == "正文"


def test_cap_chars_plain_text_cuts_at_line_and_flags():
    doc = DocText(text="\n".join(f"第{i}行内容内容内容" for i in range(100)), text_source="text_layer")
    cut = cap_chars(doc, 100)
    assert cut.truncated and "char_capped" in cut.quality_flags
    assert len(cut.text) <= 100 and cut.text.endswith("内容")
    assert cap_chars(doc, 10 ** 6) is doc


def test_cap_chars_keeps_page_boundary_for_paged_docs():
    pages = [PageInfo(i, "text_layer", f"第{i}页" + "字" * 50) for i in range(1, 5)]
    doc = DocText(text="x" * 400, text_source="text_layer", pages=pages, pages_total=4)
    cut = cap_chars(doc, 150)
    assert cut.pages_missing and cut.truncated
    assert all(p.text for p in cut.pages if p.source == "text_layer")
