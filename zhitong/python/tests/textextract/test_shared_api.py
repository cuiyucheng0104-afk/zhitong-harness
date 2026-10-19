"""共享读取件：``decode_text`` / 逐页读取 / docx 块与 xlsx 行出口 / 单一读取出口棘轮。

迁移自旧仓 engine-service/tests/test_textextract_shared_api.py（旧 WS04-P7）。
未迁移：``ocr_pages_for_path``（OCR 服务）、``find_ocr_sidecar`` 的软链用例（已在 tests/sidecar/test_locate.py）。

棘轮（旧统一约定 C6）：document.xml 解析与 ``.ocr.txt`` 卷头解析只许出现在读取件里。本仓只扫描
``zt/textextract``、``zt/sidecar``、``zt/inventory``，别的分区（如写 docx 的 ``zt/report``）不在此处约束。
"""
from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest

from tests.textextract import ws04_fixtures as fx
from zt.textextract.decode import decode_text
from zt.textextract.docx_reader import docx_blocks
from zt.textextract.pdf import page_status, pdf_page_texts
from zt.textextract.xlsx import xlsx_lines

R19_GBK = "取土及动探孔\t1234567.890\t7654321.012".encode("gbk")


# ---------------------------------------------------------------- decode_text


@pytest.mark.parametrize("raw,expected", [
    (R19_GBK, "取土及动探孔\t1234567.890\t7654321.012"),
    ("合同金额 999 万元".encode("utf-8"), "合同金额 999 万元"),
    ("合同金额 999 万元".encode("utf-8-sig"), "合同金额 999 万元"),
    ("合同金额 999 万元".encode("utf-16"), "合同金额 999 万元"),
    (b"", ""),
])
def test_decode_text_ok(raw, expected):
    assert decode_text(raw) == expected


def test_decode_text_gbk_starts_with_expected_prefix():
    """R19：结果应以「取土及动探孔」开头，而不是 errors=ignore 得到的 `ȡ̽`。"""
    assert decode_text(R19_GBK).startswith("取土及动探孔")


def test_decode_text_utf16le_without_bom_is_none():
    """无 BOM 的 UTF-16LE：gb18030 会解成含 NUL 的乱码 —— 必须返回 None，与空文件区分。"""
    assert decode_text("合同金额 999 万元".encode("utf-16-le")) is None


# ---------------------------------------------------------------- pdf_page_texts / page_status


def test_pdf_page_texts_covers_every_page_status():
    raw = pdf_page_texts(fx.build_pdf(["text", "blank", "image", "vector", "watermark", "garbled"]))
    assert [p.no for p in raw] == [1, 2, 3, 4, 5, 6]
    statuses = [page_status(p.text, p.has_image, p.content_len).status for p in raw]
    assert statuses == ["usable", "blank", "scanned", "scanned", "scanned", "scanned"]
    assert raw[2].has_image is True and raw[3].content_len > 64


def test_pdf_page_texts_none_for_unreadable_and_encrypted():
    import io

    from pypdf import PdfWriter

    assert pdf_page_texts(b"not a pdf") is None
    w = PdfWriter()
    w.add_blank_page(100, 100)
    w.encrypt(user_password="pw", owner_password="o", algorithm="RC4-128")
    buf = io.BytesIO()
    w.write(buf)
    assert pdf_page_texts(buf.getvalue()) is None


def test_pdf_page_texts_max_pages():
    raw = pdf_page_texts(fx.build_pdf(["text"] * 5), max_pages=2)
    assert [p.no for p in raw] == [1, 2]


# ---------------------------------------------------------------- 其余共享件


def test_docx_blocks_and_xlsx_lines_exported():
    import zipfile

    from openpyxl import Workbook

    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body>'
                   "<w:p><w:r><w:t>段一</w:t></w:r></w:p></w:body></w:document>")
    assert [b.text for b in docx_blocks(buf.getvalue())] == ["段一"]
    wb = Workbook()
    wb.active["C5"] = "值"
    out = io.BytesIO()
    wb.save(out)
    assert xlsx_lines(out.getvalue())[-1] == "[R5] C:值"


# ---------------------------------------------------------------- C6 棘轮：读取只有一个出口

_PY_ROOT = Path(__file__).resolve().parents[2]
_SCANNED = ("zt/textextract", "zt/sidecar", "zt/inventory")
# 标记 → 允许出现的文件（相对 zhitong/python/）
_RULES = {
    "word/document.xml": {"zt/textextract/docx_reader.py"},
    "异常字符": {"zt/sidecar/format.py"},
    "原始路径:": {"zt/sidecar/format.py"},
}
_BASELINE: set[tuple[str, str]] = set()


def _string_constants(tree: ast.AST):
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node.value


def test_single_reader_ratchet():
    hits = set()
    for path in (p for d in _SCANNED for p in (_PY_ROOT / d).rglob("*.py")):
        rel = path.relative_to(_PY_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for value in _string_constants(tree):
            for marker in _RULES:
                if marker in value:
                    hits.add((marker, rel))
    illegal = {(m, f) for m, f in hits if f not in _RULES[m] and (m, f) not in _BASELINE}
    assert not illegal, (
        f"C6：以下文件自己解析 docx / 旁车卷头，应改用 zt.textextract.docx_reader / zt.sidecar.format：{sorted(illegal)}"
    )
    # 棘轮自检：规则确实扫得到（否则上面的断言永远为真，铁律 8）
    assert ("word/document.xml", "zt/textextract/docx_reader.py") in hits
    assert ("异常字符", "zt/sidecar/format.py") in hits


def test_ratchet_catches_a_new_violation():
    """负控：造一份自己读 document.xml 的模块，棘轮的扫描逻辑必须认得出来。"""
    src = 'import zipfile\ndef f(b):\n    return zipfile.ZipFile(b).read("word/document.xml")\n'
    values = list(_string_constants(ast.parse(src)))
    assert "word/document.xml" in values
