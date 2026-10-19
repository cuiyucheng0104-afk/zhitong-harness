"""旁车查找：命名、软链逃逸、编码。

迁移自旧仓 engine-service/tests/test_ocr_sidecar.py 的查找 / 软链 / 编码三组用例（D-01）。
未迁移：依赖 FastAPI 端点（extract/fields、tag/classify）、字段合并与 ``pdf_text_with_sidecar`` 的用例，
本仓没有这些模块。
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path

import pytest
from pypdf import PdfWriter

from tests.textextract import ws04_fixtures as fx
from zt.sidecar import (
    find_sidecar,
    is_sidecar_name,
    iter_sidecars,
    read_sidecar_doc,
    read_sidecar_text,
    sidecar_names,
)
from zt.textextract.pdf import pdf_text_layer_chars


def _blank_pdf() -> bytes:
    """一页空白 PDF，没有文字层，等价于扫描件在 pypdf 眼里的样子。"""
    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _put(root: Path, name: str, data: bytes | str) -> Path:
    p = root / name
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return p


def _symlink_or_skip(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as e:  # Windows 无权限创建符号链接
        pytest.skip(f"当前环境不能创建符号链接：{e}")


def test_blank_pdf_really_has_no_text_layer():
    """负控：先证明夹具本身确实无文字层，否则下面全部用例都在测一个假前提。"""
    assert pdf_text_layer_chars(_blank_pdf()) == 0


# ---------------------------------------------------------------- 命名


def test_sidecar_names_order():
    assert sidecar_names("合同.pdf") == ["合同.pdf.ocr.txt", "合同.ocr.txt"]
    # 无扩展名时两种写法相同，只留一个
    assert sidecar_names("合同") == ["合同.ocr.txt"]


@pytest.mark.parametrize("name,expected", [
    ("a.pdf.ocr.txt", True), ("A.OCR.TXT", True), ("a.txt", False), ("ocr.txt.bak", False),
])
def test_is_sidecar_name(name, expected):
    assert is_sidecar_name(name) is expected


# ---------------------------------------------------------------- 查找


def test_sidecar_appended_naming(tmp_path):
    pdf = _put(tmp_path, "施工合同.pdf", _blank_pdf())
    _put(tmp_path, "施工合同.pdf.ocr.txt", "本合同由甲方与乙方签订，合同金额 12,345,678.00 元。")
    text, name = read_sidecar_text(pdf, tmp_path)
    assert "12,345,678.00" in text
    assert name == "施工合同.pdf.ocr.txt"


def test_sidecar_replaced_naming(tmp_path):
    pdf = _put(tmp_path, "补充协议.pdf", _blank_pdf())
    _put(tmp_path, "补充协议.ocr.txt", "补充协议正文。")
    assert read_sidecar_text(pdf, tmp_path)[1] == "补充协议.ocr.txt"


def test_appended_naming_wins_when_both_exist(tmp_path):
    pdf = _put(tmp_path, "双份.pdf", _blank_pdf())
    _put(tmp_path, "双份.pdf.ocr.txt", "追加式内容")
    _put(tmp_path, "双份.ocr.txt", "替换式内容")
    assert read_sidecar_text(pdf, tmp_path) == ("追加式内容", "双份.pdf.ocr.txt")
    assert find_sidecar(pdf, tmp_path).name == "双份.pdf.ocr.txt"
    assert [c.name for c, _ in iter_sidecars(pdf, tmp_path)] == ["双份.pdf.ocr.txt", "双份.ocr.txt"]


def test_no_sidecar_returns_none(tmp_path):
    pdf = _put(tmp_path, "光杆.pdf", _blank_pdf())
    assert read_sidecar_text(pdf, tmp_path) is None
    assert find_sidecar(pdf, tmp_path) is None
    assert read_sidecar_doc(pdf, tmp_path) is None


@pytest.mark.parametrize("blank", ["", "   \n\t  \n"])
def test_blank_sidecar_is_not_a_hit(tmp_path, blank):
    """空旁车不算命中：否则会把「有旁车」误报成「有正文」，比没有旁车更糟。"""
    pdf = _put(tmp_path, "空旁车.pdf", _blank_pdf())
    _put(tmp_path, "空旁车.pdf.ocr.txt", blank)
    assert read_sidecar_text(pdf, tmp_path) is None


def test_chinese_and_space_paths(tmp_path):
    d = tmp_path / "资料 一期" / "合同 (1)"
    d.mkdir(parents=True)
    pdf = _put(d, "施工 合同.pdf", _blank_pdf())
    _put(d, "施工 合同.pdf.ocr.txt", "含空格路径的旁车")
    assert read_sidecar_text(pdf, tmp_path) == ("含空格路径的旁车", "施工 合同.pdf.ocr.txt")


# ---------------------------------------------------------------- 软链逃逸


def test_symlink_sidecar_escaping_root_is_rejected(tmp_path):
    """旁车是指向根目录之外的符号链接时必须拒认（返回 None），不抛错。"""
    root = tmp_path / "root"
    root.mkdir()
    pdf = _put(root, "软链主件.pdf", _blank_pdf())
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("根目录之外的内容，绝不允许被当正文读出", encoding="utf-8")
    _symlink_or_skip(outside, root / "软链主件.pdf.ocr.txt")
    assert read_sidecar_text(pdf, root) is None
    assert list(iter_sidecars(pdf, root)) == []


def test_symlink_sidecar_inside_root_is_accepted(tmp_path):
    """正控：指向根目录之内的软链是合法旁车，防护不能一刀切。"""
    pdf = _put(tmp_path, "链内主件.pdf", _blank_pdf())
    real = _put(tmp_path, "真实旁车.txt", "链内旁车正文")
    _symlink_or_skip(real, tmp_path / "链内主件.pdf.ocr.txt")
    assert read_sidecar_text(pdf, tmp_path)[0] == "链内旁车正文"


# ---------------------------------------------------------------- 编码


def test_utf16_bom_sidecar_decodes(tmp_path):
    pdf = _put(tmp_path, "utf16旁车.pdf", _blank_pdf())
    _put(tmp_path, "utf16旁车.pdf.ocr.txt", "合同金额 999 万元".encode("utf-16"))
    text = read_sidecar_text(pdf, tmp_path)[0]
    assert "999" in text and "合同金额" in text


def test_utf16le_no_bom_sidecar_returns_none_with_warning(tmp_path, caplog):
    """无 BOM 的 UTF-16LE 会被 gb18030 解成含 NUL 的乱码；必须判废，并点名文件。"""
    pdf = _put(tmp_path, "utf16le旁车.pdf", _blank_pdf())
    _put(tmp_path, "utf16le旁车.pdf.ocr.txt", "合同金额 999 万元".encode("utf-16-le"))
    with caplog.at_level(logging.WARNING, logger="zt.sidecar"):
        assert read_sidecar_text(pdf, tmp_path) is None
    assert "utf16le旁车.pdf.ocr.txt" in caplog.text


def test_gb18030_sidecar_decodes(tmp_path):
    pdf = _put(tmp_path, "gbk旁车.pdf", _blank_pdf())
    _put(tmp_path, "gbk旁车.pdf.ocr.txt", "本合同金额壹佰万元整。".encode("gb18030"))
    assert "壹佰万元整" in read_sidecar_text(pdf, tmp_path)[0]


# ---------------------------------------------------------------- 结构化入口


def test_all_failed_sidecar_visible_through_doc_api(tmp_path):
    """全失败旁车：文本入口判未命中，结构化入口仍能拿到（页级降级要知道「有旁车但每页都失败」）。"""
    pdf = _put(tmp_path, "外架.pdf", _blank_pdf())
    _put(tmp_path, "外架.pdf.ocr.txt", fx.F1)
    assert read_sidecar_text(pdf, tmp_path) is None
    doc, name = read_sidecar_doc(pdf, tmp_path)
    assert doc.usable is False and name == "外架.pdf.ocr.txt"
