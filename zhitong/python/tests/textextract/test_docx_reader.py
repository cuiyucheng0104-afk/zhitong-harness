"""WS04-P5：docx 改用 XML 解析 —— 修订、域指令、实体（QA:text-ocr-03，含 #689）。

生产 R02《违约处罚条款-监理(0619改).docx》：引擎抽出 13014 字，定稿视图只有 8724 字。
多出来的是修订里已删除的文字（『上浮50%』『或业主经济损失2%』×6）、正文开头的
`TOC \\o &quot;1-1&quot; … HYPERLINK … PAGEREF` 域指令、12 处 `&quot;`。R01 的 `&lt;` `&gt;`
各 19 处没还原（#689）。docx 全在测试里现造。
"""
from __future__ import annotations

import io
import zipfile

import pytest

from zt.textextract.docx_reader import DocxParseError, docx_blocks, read_docx
from zt.textextract.extract import extract_document
from zt.textextract.office import docx_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(body: str, *, styles: str | None = None, doctype: bool = False) -> bytes:
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    if doctype:
        head += '<!DOCTYPE w:document [<!ENTITY a "aaaaaaaaaa">]>'
    doc = f'{head}<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
        if styles:
            z.writestr("word/styles.xml", f'<w:styles xmlns:w="{W}">{styles}</w:styles>')
    return buf.getvalue()


def r(text: str) -> str:
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def p(*runs: str, style: str | None = None, extra_ppr: str = "") -> str:
    ppr = ""
    if style or extra_ppr:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "") + extra_ppr + "</w:pPr>"
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def fld(kind: str) -> str:
    return f'<w:r><w:fldChar w:fldCharType="{kind}"/></w:r>'


def instr(text: str) -> str:
    return f'<w:r><w:instrText xml:space="preserve">{text}</w:instrText></w:r>'


# ---------------------------------------------------------------- 实体（#689）


def test_entities_restored_issue_689():
    content = _docx(p(r("1．本工程执行&lt;&lt;高层民用建筑设计防火规范&gt;&gt;。")))
    assert docx_text(content) == "1．本工程执行<<高层民用建筑设计防火规范>>。"


# ---------------------------------------------------------------- 修订


def test_deleted_revision_skipped():
    body = p(r("违约金"), '<w:del w:id="1" w:author="a"><w:r><w:delText>上浮50%</w:delText></w:r></w:del>',
             '<w:ins w:id="2" w:author="a">' + r("上浮20%") + "</w:ins>")
    doc = read_docx(_docx(body))
    assert doc.blocks[0].text == "违约金上浮20%"
    assert doc.has_revisions is True


def test_inserted_revision_kept():
    body = p(r("执行"), '<w:ins w:id="3" w:author="a">' + r("新规范") + "</w:ins>")
    assert docx_text(_docx(body)) == "执行新规范"


def test_move_from_skipped_move_to_kept():
    body = (
        p('<w:moveFrom w:id="4" w:author="a">' + r("或业主经济损失2%") + "</w:moveFrom>")
        + p('<w:moveTo w:id="5" w:author="a">' + r("或发包人经济损失2%") + "</w:moveTo>")
    )
    out = docx_text(_docx(body))
    assert "或业主经济损失2%" not in out
    assert "或发包人经济损失2%" in out


def test_deleted_paragraph_level_and_table_row():
    body = (
        '<w:del w:id="6" w:author="a">' + p(r("整段删除")) + "</w:del>"
        + "<w:tbl><w:tr><w:trPr><w:del w:id=\"7\" w:author=\"a\"/></w:trPr>"
        + "<w:tc>" + p(r("删掉的行")) + "</w:tc></w:tr>"
        + "<w:tr><w:tc>" + p(r("留下的行")) + "</w:tc></w:tr></w:tbl>"
    )
    out = docx_text(_docx(body))
    assert "整段删除" not in out and "删掉的行" not in out
    assert "留下的行" in out


# ---------------------------------------------------------------- 域


def test_nested_toc_hyperlink_pageref_only_results():
    body = (
        p(fld("begin"), instr(' TOC \\o "1-1" \\h \\z \\u '), fld("separate"), r("目录"))
        + p(fld("begin"), instr(' HYPERLINK \\l "_Toc1" '), fld("separate"),
            r("第一章 总则"), r("\t"),
            fld("begin"), instr(" PAGEREF _Toc1 \\h "), fld("separate"), r("3"), fld("end"),
            fld("end"))
        + p(fld("end"))
        + p(r("第一章 总则正文"))
    )
    doc = read_docx(_docx(body))
    out = doc.text()
    assert "TOC" not in out and "PAGEREF" not in out and "HYPERLINK" not in out
    assert "&quot;" not in out and '"1-1"' not in out
    assert "目录" in out
    assert "第一章 总则" in out
    assert doc.has_fields is True
    assert doc.blocks[1].is_toc is True
    assert doc.blocks[-1].is_toc is False


def test_fld_simple_keeps_result_only():
    body = p(r("共 "), '<w:fldSimple w:instr=" NUMPAGES "><w:r><w:t>12</w:t></w:r></w:fldSimple>', r(" 页"))
    out = docx_text(_docx(body))
    assert out == "共 12 页"
    assert "NUMPAGES" not in out


def test_unterminated_field_does_not_swallow_rest():
    body = p(fld("begin"), instr(" MERGEFIELD 甲方 ")) + p(r("后续正文仍在"))
    doc = read_docx(_docx(body))
    assert "后续正文仍在" in doc.text()
    assert "field_unterminated" in doc.flags


# ---------------------------------------------------------------- 版式


def test_tab_and_break():
    body = p(r("甲"), "<w:r><w:tab/></w:r>", r("乙"), "<w:r><w:br/></w:r>", r("丙"))
    assert docx_text(_docx(body)) == "甲\t乙\n丙"


def test_table_two_rows_three_cols():
    row = "<w:tr>" + "".join(f"<w:tc>{p(r(c))}</w:tc>" for c in ("{0}1", "{0}2", "{0}3")) + "</w:tr>"
    body = p(r("表前")) + "<w:tbl>" + row.format("A") + row.format("B") + "</w:tbl>" + p(r("表后"))
    blocks = docx_blocks(_docx(body))
    assert [b.kind for b in blocks] == ["p", "row", "row", "p"]
    assert blocks[1].text == "A1\tA2\tA3"
    assert blocks[2].cells == ["B1", "B2", "B3"]
    assert (blocks[1].table_index, blocks[1].row_index) == (1, 1)
    assert [b.no for b in blocks] == [1, 2, 3, 4]
    assert docx_text(_docx(body)) == "表前\nA1\tA2\tA3\nB1\tB2\tB3\n表后"


def test_cell_with_multiple_paragraphs_stays_one_row():
    cell = f"<w:tc>{p(r('第一段'))}{p(r('第二段'))}</w:tc>"
    body = f"<w:tbl><w:tr>{cell}<w:tc>{p(r('x'))}</w:tc></w:tr></w:tbl>"
    blocks = docx_blocks(_docx(body))
    assert blocks[0].text == "第一段 第二段\tx"


# ---------------------------------------------------------------- 标题级别


def test_heading_level_from_styles_and_outline():
    styles = (
        '<w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="2"><w:name w:val="标题 2"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="X"><w:name w:val="My Heading"/>'
        '<w:basedOn w:val="1"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="T"><w:name w:val="Table Text"/></w:style>'
    )
    body = (p(r("第一章"), style="1") + p(r("第一节"), style="2") + p(r("派生"), style="X")
            + p(r("表格文字"), style="T")
            + p(r("大纲三级"), extra_ppr='<w:outlineLvl w:val="2"/>'))
    blocks = docx_blocks(_docx(body, styles=styles))
    assert [b.heading_level for b in blocks] == [1, 2, 1, None, 3]


# ---------------------------------------------------------------- 安全 / 失败


def test_doctype_rejected():
    with pytest.raises(DocxParseError):
        read_docx(_docx(p(r("x")), doctype=True))
    doc = extract_document(_docx(p(r("x")), doctype=True), "docx", file_name="炸弹.docx")
    assert doc.failure.code == "parse_failed"


def test_not_a_zip_is_parse_error():
    with pytest.raises(DocxParseError):
        read_docx(b"not a zip")
    assert docx_text(b"not a zip") == ""


def test_revision_flag_reported_in_quality_flags():
    body = p(r("a"), '<w:del w:id="1" w:author="x"><w:r><w:delText>b</w:delText></w:r></w:del>')
    doc = extract_document(_docx(body), "docx", file_name="修订.docx")
    assert "has_revisions" in doc.quality_flags
    assert doc.text == "a"
