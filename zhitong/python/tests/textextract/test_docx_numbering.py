"""WS04-P10（issue #774 / QA:text-ocr-11）：docx 自动编号渲染（numbering.xml → num_prefix）。

生产 R14《结算审核报告》（.doc，经 soffice 转 docx 后走 docx_reader）：抽出的正文里「（三）」
「（四）」0 次，「公装部分造价核减分析」前面没有序号，「竣工图纸…」前面缺「3、」——
序号是 Word 自动编号（段落 `w:numPr` → `numbering.xml`），不是正文里的字，旧实现不读它。

夹具按「.doc 经 LibreOffice 转回 docx」的真实版式构造（本机 soffice 7.x 往返实测）：
中文计数存成 `taiwaneseCountingThousand`；一级编号挂在 Heading1 样式上（样式 numPr 只给
numId、级别由 `w:lvl/w:pStyle` 认领）；二、三级是段落直挂 numPr；同一 abstractNum 被多个
w:num 引用（续编号）；`lvlOverride/startOverride` 重新起号。不含客户正文。
"""
from __future__ import annotations

import html
import io
import zipfile

import pytest

from zt.textextract import office as textextract
from zt.textextract.docx_reader import DocxParseError, docx_blocks, read_docx
from zt.textextract.extract import extract_document
from zt.textextract.office import docx_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


# =============================================================================
# 夹具
# =============================================================================


def lvl(ilvl: int, fmt: str, text: str, *, start: int | None = 1, extra: str = "",
        pstyle: str | None = None) -> str:
    """一个 `w:lvl`，形状照 LibreOffice 往返后的产物（带 lvlJc / pPr / tabs）。"""
    parts = [f'<w:lvl w:ilvl="{ilvl}">']
    if start is not None:
        parts.append(f'<w:start w:val="{start}"/>')
    if fmt:
        parts.append(f'<w:numFmt w:val="{fmt}"/>')
    if pstyle:
        parts.append(f'<w:pStyle w:val="{pstyle}"/>')
    parts.append(f'<w:lvlText w:val="{html.escape(text)}"/>')
    parts.append(extra)
    parts.append('<w:lvlJc w:val="start"/><w:pPr><w:tabs><w:tab w:val="num" w:pos="0"/></w:tabs>'
                 f'<w:ind w:start="{420 * (ilvl + 1)}" w:hanging="420"/></w:pPr></w:lvl>')
    return "".join(parts)


def abstract(aid: int, *levels: str, extra: str = "") -> str:
    return f'<w:abstractNum w:abstractNumId="{aid}">{extra}{"".join(levels)}</w:abstractNum>'


def num(nid: int, aid: int, overrides: str = "") -> str:
    return f'<w:num w:numId="{nid}"><w:abstractNumId w:val="{aid}"/>{overrides}</w:num>'


def start_override(ilvl: int, value: int) -> str:
    return f'<w:lvlOverride w:ilvl="{ilvl}"><w:startOverride w:val="{value}"/></w:lvlOverride>'


def numbering(*parts: str) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:numbering xmlns:w="{W}" xmlns:mc="{MC}">{"".join(parts)}</w:numbering>')


def p(text: str, num_id: int | None = None, ilvl: int | None = None, *,
      style: str | None = None) -> str:
    ppr = ""
    if style or num_id is not None or ilvl is not None:
        ppr = "<w:pPr>" + (f'<w:pStyle w:val="{style}"/>' if style else "")
        if num_id is not None or ilvl is not None:
            ppr += "<w:numPr>"
            if ilvl is not None:
                ppr += f'<w:ilvl w:val="{ilvl}"/>'
            if num_id is not None:
                ppr += f'<w:numId w:val="{num_id}"/>'
            ppr += "</w:numPr>"
        ppr += '<w:bidi w:val="0"/><w:jc w:val="start"/></w:pPr>'
    run = f'<w:r><w:t xml:space="preserve">{html.escape(text, quote=False)}</w:t></w:r>' if text else ""
    return f"<w:p>{ppr}{run}</w:p>"


STYLES_R14 = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:numPr><w:numId w:val="5"/></w:numPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2Child"><w:name w:val="Heading 2 child"/>
    <w:basedOn w:val="Heading2"/></w:style>
</w:styles>"""


def make_docx(body: str, *, numbering_xml: str | None = None, styles: str | None = None) -> bytes:
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           f'<w:document xmlns:w="{W}"><w:body>{body}<w:sectPr/></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml", doc)
        if numbering_xml is not None:
            z.writestr("word/numbering.xml", numbering_xml)
        z.writestr("word/styles.xml", styles or STYLES_R14)
    return buf.getvalue()


# 让 soffice 也能打开（下方与 LibreOffice 渲染对照的用例要用）
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""


def lines(content: bytes) -> list[str]:
    return docx_text(content).split("\n")


# R14 形状：一级「一、」挂在 Heading1 样式上（lvl pStyle 认领），二级「（一）」、三级「1、」
# 段落直挂；中文计数是 .doc 往返后的 taiwaneseCountingThousand。
R14_NUMBERING = numbering(
    abstract(1,
             lvl(0, "taiwaneseCountingThousand", "%1、", pstyle="Heading1"),
             lvl(1, "taiwaneseCountingThousand", "（%2）"),
             lvl(2, "decimal", "%3、"),
             lvl(3, "decimal", "%3.%4")),
    num(1, 1),
)


def r14_body() -> str:
    return "".join([
        p("审核依据", style="Heading1"),
        p("委托合同", 1, 1),
        p("施工合同", 1, 1),
        p("审核结论", style="Heading1"),
        p("土建部分造价核减分析", 1, 1),
        p("安装部分造价核减分析", 1, 1),
        p("公装部分造价核减分析", 1, 1),
        p("其他部分造价核减分析", 1, 1),
        p("审定金额见附表。"),
        p("竣工结算书", 1, 2),
        p("签证单", 1, 2),
        p("竣工图纸及设计变更", 1, 2),
        p("图纸会审记录", 1, 3),
    ])


# =============================================================================
# spec 验收用例：上级递增后下级归位
# =============================================================================


def test_spec_case_child_level_restarts_after_parent_increments():
    """spec P10 验收：一级 `%1、`、二级 `（%2）`（中文计数）；最后那个「（一）」验证二级计数
    在上级递增后归位（不归位就会是「（三）」）。"""
    body = "".join([p("甲", 1, 0), p("乙", 1, 1), p("丙", 1, 1), p("丁", 1, 0), p("戊", 1, 1)])
    nx = numbering(abstract(0, lvl(0, "decimal", "%1、"), lvl(1, "chineseCounting", "（%2）")),
                   num(1, 0))
    assert lines(make_docx(body, numbering_xml=nx)) == ["1、甲", "（一）乙", "（二）丙", "2、丁", "（一）戊"]


def test_r14_shape_numbers_rendered():
    """生产 R14 的三处缺口：「（三）公装部分」「（四）」「3、竣工图纸」。"""
    out = lines(make_docx(r14_body(), numbering_xml=R14_NUMBERING))
    assert out == [
        "一、审核依据",
        "（一）委托合同",
        "（二）施工合同",
        "二、审核结论",
        "（一）土建部分造价核减分析",
        "（二）安装部分造价核减分析",
        "（三）公装部分造价核减分析",
        "（四）其他部分造价核减分析",
        "审定金额见附表。",
        "1、竣工结算书",
        "2、签证单",
        "3、竣工图纸及设计变更",
        "3.1 图纸会审记录",
    ]


def test_blocks_carry_num_prefix_and_keep_text_clean():
    """块级 API：序号只进 num_prefix，text 仍是段落本身（filetree 的标题/GREP 用 text）。"""
    blocks = docx_blocks(make_docx(r14_body(), numbering_xml=R14_NUMBERING))
    b = next(b for b in blocks if b.text == "公装部分造价核减分析")
    assert b.num_prefix == "（三）"
    h = next(b for b in blocks if b.text == "审核结论")
    assert h.num_prefix == "二、" and h.heading_level == 1


# =============================================================================
# 续编号 / 重新起号
# =============================================================================


def test_numbering_continues_across_unnumbered_paragraphs_and_num_instances():
    """续编号：中间夹不编号的段落、两个 w:num 引用同一 abstractNum —— 按 abstractNum 连续计数。"""
    nx = numbering(abstract(0, lvl(0, "decimal", "%1.")), num(1, 0), num(2, 0))
    body = "".join([p("一项", 1, 0), p("说明文字"), p("二项", 1, 0), p("三项", 2, 0)])
    assert lines(make_docx(body, numbering_xml=nx)) == ["1. 一项", "说明文字", "2. 二项", "3. 三项"]


def test_start_override_restarts_once_then_continues():
    nx = numbering(abstract(0, lvl(0, "decimal", "%1、")), num(1, 0), num(2, 0, start_override(0, 5)))
    body = "".join([p("甲", 1, 0), p("乙", 1, 0), p("丙", 2, 0), p("丁", 2, 0), p("戊", 1, 0)])
    assert lines(make_docx(body, numbering_xml=nx)) == ["1、甲", "2、乙", "5、丙", "6、丁", "7、戊"]


def test_lvl_override_replaces_level_definition():
    over = '<w:lvlOverride w:ilvl="0">' + lvl(0, "upperLetter", "%1)", start=1) + "</w:lvlOverride>"
    nx = numbering(abstract(0, lvl(0, "decimal", "%1.")), num(1, 0), num(2, 0, over))
    body = p("一", 1, 0) + p("二", 2, 0)
    assert lines(make_docx(body, numbering_xml=nx)) == ["1. 一", "B) 二"]


def test_empty_numbered_paragraph_still_counts():
    nx = numbering(abstract(0, lvl(0, "decimal", "%1、")), num(1, 0))
    body = p("甲", 1, 0) + p("", 1, 0) + p("丙", 1, 0)
    assert lines(make_docx(body, numbering_xml=nx)) == ["1、甲", "2、", "3、丙"]


def test_lvl_restart_zero_never_restarts():
    """lvlRestart=0：上级编号也不归位（ECMA-376 17.9.10，Word 照此；LibreOffice 不认这条，
    所以这条不进下方的 LibreOffice 对照用例）。"""
    nx = numbering(abstract(0, lvl(0, "decimal", "%1."),
                            lvl(1, "decimal", "(%2)", extra='<w:lvlRestart w:val="0"/>')), num(1, 0))
    body = p("a", 1, 0) + p("b", 1, 1) + p("c", 1, 0) + p("d", 1, 1)
    assert lines(make_docx(body, numbering_xml=nx)) == ["1. a", "(1) b", "2. c", "(2) d"]


def test_multilevel_compound_text_and_is_lgl():
    """`%1.%2` 复合序号；isLgl 让上级的中文计数也按阿拉伯数字显示。"""
    nx = numbering(abstract(0, lvl(0, "chineseCounting", "第%1章"),
                            lvl(1, "decimal", "%1.%2", extra="<w:isLgl/>")), num(1, 0))
    body = p("总则", 1, 0) + p("范围", 1, 1) + p("术语", 1, 1) + p("计价", 1, 0) + p("规定", 1, 1)
    assert lines(make_docx(body, numbering_xml=nx)) == [
        "第一章 总则", "1.1 范围", "1.2 术语", "第二章 计价", "2.1 规定"]


# =============================================================================
# 通过样式挂上的编号
# =============================================================================


def test_style_numbering_level_from_lvl_pstyle_and_based_on():
    """Heading2 样式只给 numId，级别由 abstractNum 里 `w:pStyle=Heading2` 的那一级认领
    （ECMA-376 17.9.23，Word 照此；LibreOffice 渲染成第 0 级，不进对照用例）；
    Heading2Child 经 basedOn 继承同一编号。"""
    nx = numbering(abstract(3, lvl(0, "decimal", "%1、"),
                            lvl(1, "chineseCounting", "（%2）", pstyle="Heading2")),
                   num(5, 3))
    body = p("概况", style="Heading2") + p("依据", style="Heading2Child")
    assert lines(make_docx(body, numbering_xml=nx)) == ["（一）概况", "（二）依据"]


def test_num_id_zero_removes_style_numbering():
    body = p("编号标题", style="Heading1") + p("去掉编号的标题", 0, None, style="Heading1")
    assert lines(make_docx(body, numbering_xml=R14_NUMBERING)) == ["一、编号标题", "去掉编号的标题"]


def test_num_style_link_resolves_to_style_linked_abstract():
    """abstractNum 用 numStyleLink 指向编号样式，真正的级别定义在 styleLink 那个 abstractNum 里。"""
    styles = f"""<w:styles xmlns:w="{W}">
      <w:style w:type="numbering" w:styleId="ListStyleA"><w:name w:val="List A"/>
        <w:pPr><w:numPr><w:numId w:val="7"/></w:numPr></w:pPr></w:style></w:styles>"""
    nx = numbering(
        abstract(10, lvl(0, "decimal", "%1、"), extra='<w:styleLink w:val="ListStyleA"/>'),
        abstract(11, extra='<w:numStyleLink w:val="ListStyleA"/>'),
        num(7, 10), num(8, 11))
    body = p("甲", 8, 0) + p("乙", 8, 0)
    assert lines(make_docx(body, numbering_xml=nx, styles=styles)) == ["1、甲", "2、乙"]


# =============================================================================
# 编号格式
# =============================================================================


@pytest.mark.parametrize("fmt,value,expect", [
    ("decimal", 12, "12"),
    ("decimalZero", 7, "07"),
    ("decimalFullWidth", 3, "３"),
    ("decimalFullWidth2", 12, "１２"),
    ("chineseCounting", 1, "一"),
    ("chineseCounting", 10, "十"),
    ("chineseCounting", 11, "十一"),
    ("chineseCounting", 20, "二十"),
    ("chineseCounting", 34, "三十四"),
    ("chineseCountingThousand", 101, "一百零一"),
    ("chineseCountingThousand", 110, "一百一十"),
    ("taiwaneseCountingThousand", 4, "四"),
    ("japaneseCounting", 13, "十三"),
    ("ideographDigital", 10, "一〇"),
    ("chineseLegalSimplified", 12, "壹拾贰"),
    ("ideographLegalTraditional", 3, "參"),
    ("ideographTraditional", 3, "丙"),
    ("ideographZodiac", 2, "丑"),
    ("lowerLetter", 2, "b"),
    ("upperLetter", 28, "BB"),
    ("lowerRoman", 9, "ix"),
    ("upperRoman", 14, "XIV"),
    ("decimalEnclosedCircle", 3, "③"),
    ("decimalEnclosedCircleChinese", 21, "㉑"),
    ("decimalEnclosedParen", 2, "⑵"),
    ("decimalEnclosedFullstop", 5, "⒌"),
    ("ideographEnclosedCircle", 4, "㈣"),
    ("decimalEnclosedCircle", 60, "60"),       # 超出圈码字符集：Word 也显示普通数字
])
def test_number_formats(fmt, value, expect):
    nx = numbering(abstract(0, lvl(0, fmt, "[%1]", start=value)), num(1, 0))
    doc = read_docx(make_docx(p("正文", 1, 0), numbering_xml=nx))
    assert doc.blocks[0].num_prefix.strip() == f"[{expect}]"
    assert "numbering_fallback" not in doc.flags


def test_custom_zero_padded_format_via_alternate_content():
    """Word 2010+ 的 `001, 002` 自定义格式写在 mc:AlternateContent 里，Fallback 是 decimalZero。"""
    alt = (f'<mc:AlternateContent><mc:Choice Requires="w14"><w:numFmt w:val="custom" '
           f'w:format="001, 002, 003, ..."/></mc:Choice><mc:Fallback><w:numFmt w:val="decimalZero"/>'
           f'</mc:Fallback></mc:AlternateContent>')
    nx = numbering(abstract(0, lvl(0, "", "%1", extra=alt)), num(1, 0))
    assert lines(make_docx(p("甲", 1, 0) + p("乙", 1, 0), numbering_xml=nx)) == ["001 甲", "002 乙"]


def test_bullet_symbol_font_glyph_mapped():
    """项目符号：Symbol 字体私用区字形（U+F0B7）换成「•」；项目符号不带计数。"""
    nx = numbering(abstract(0, lvl(0, "bullet", "")), num(1, 0))
    assert lines(make_docx(p("要点甲", 1, 0) + p("要点乙", 1, 0), numbering_xml=nx)) == [
        "• 要点甲", "• 要点乙"]


def test_none_format_has_no_prefix():
    nx = numbering(abstract(0, lvl(0, "none", "")), num(1, 0))
    assert lines(make_docx(p("无编号", 1, 0), numbering_xml=nx)) == ["无编号"]


def test_unknown_format_falls_back_to_arabic_with_flag():
    nx = numbering(abstract(0, lvl(0, "thaiNumbers", "%1.")), num(1, 0))
    content = make_docx(p("甲", 1, 0) + p("乙", 1, 0), numbering_xml=nx)
    assert lines(content) == ["1. 甲", "2. 乙"]
    assert "numbering_fallback" in extract_document(content, "docx").quality_flags


def test_ascii_marker_gets_space_so_it_does_not_glue_to_leading_digits():
    """「1.」紧贴「5层以上」会读成 1.5 —— ASCII 结尾的序号与正文之间留一个空格；
    中文标点结尾（「3、」「（三）」）不加，与原文排版一致。"""
    nx = numbering(abstract(0, lvl(0, "decimal", "%1.")), num(1, 0))
    assert lines(make_docx(p("5层以上按超高计", 1, 0), numbering_xml=nx)) == ["1. 5层以上按超高计"]


def test_suffix_nothing_glues_marker():
    nx = numbering(abstract(0, lvl(0, "decimal", "%1.", extra='<w:suff w:val="nothing"/>')), num(1, 0))
    assert lines(make_docx(p("甲", 1, 0), numbering_xml=nx)) == ["1.甲"]


# =============================================================================
# 表格里的自动编号（序号列）
# =============================================================================


def test_numbering_inside_table_cells():
    """表格「序号」列常用自动编号：旧实现序号列整列为空。"""
    nx = numbering(abstract(0, lvl(0, "decimal", "%1")), num(1, 0))
    tbl = ("<w:tbl>"
           + "<w:tr><w:tc>" + p("序号") + "</w:tc><w:tc>" + p("项目") + "</w:tc></w:tr>"
           + "<w:tr><w:tc>" + p("", 1, 0) + "</w:tc><w:tc>" + p("土方开挖") + "</w:tc></w:tr>"
           + "<w:tr><w:tc>" + p("", 1, 0) + "</w:tc><w:tc>" + p("回填") + "</w:tc></w:tr>"
           + "</w:tbl>")
    blocks = docx_blocks(make_docx(tbl, numbering_xml=nx))
    assert [b.cells for b in blocks] == [["序号", "项目"], ["1", "土方开挖"], ["2", "回填"]]


# =============================================================================
# 退化必须可见（铁律 8）
# =============================================================================


def test_missing_numbering_part_flags_unresolved():
    content = make_docx(p("甲", 1, 0))
    assert lines(content) == ["甲"]
    assert "numbering_unresolved" in read_docx(content).flags


def test_broken_numbering_xml_degrades_with_flag():
    content = make_docx(p("甲", 1, 0), numbering_xml="<w:numbering xmlns:w='x'><oops")
    doc = read_docx(content)
    assert doc.text() == "甲"
    assert "numbering_parse_failed" in doc.flags


def test_doctype_in_numbering_rejected():
    bad = ('<?xml version="1.0"?><!DOCTYPE w:numbering [<!ENTITY a "aaaa">]>'
           f'<w:numbering xmlns:w="{W}"/>')
    with pytest.raises(DocxParseError):
        read_docx(make_docx(p("甲", 1, 0), numbering_xml=bad))


def test_extract_document_text_carries_numbering():
    doc = extract_document(make_docx(r14_body(), numbering_xml=R14_NUMBERING), "docx")
    assert "（三）公装部分造价核减分析" in doc.text
    assert "3、竣工图纸及设计变更" in doc.text


# =============================================================================
# 与 LibreOffice 的渲染对照（本机有 soffice 才跑；生产镜像里 .doc 就是经它转 docx 的）
# =============================================================================

_needs_soffice = pytest.mark.skipif(textextract._soffice_bin() is None,
                                    reason="本机没有 soffice：跳过 ≠ 通过")


def _norm(line: str) -> str:
    return "".join(line.split())


@_needs_soffice
def test_matches_libreoffice_rendering():
    """LibreOffice 当参照实现：同一份 docx，它导出的纯文本与本模块逐行一致（空白不计）。"""
    nx = numbering(
        R14_NUMBERING[R14_NUMBERING.index("<w:abstractNum"):R14_NUMBERING.index("</w:numbering>")],
        abstract(2, lvl(0, "bullet", "")), num(2, 2),
        num(3, 1, start_override(2, 1)),
    )
    body = r14_body() + p("重新起号的三级", 3, 2) + p("接着", 3, 2) + p("要点", 2, 0)
    content = make_docx(body, numbering_xml=nx)
    ref, why = textextract.libreoffice_convert_ex(content, "docx", "txt")
    assert ref is not None, why
    ref_lines = [_norm(x) for x in ref.decode("utf-8-sig").splitlines() if x.strip()]
    ours = [_norm(x) for x in lines(content)]
    assert ours == ref_lines


@_needs_soffice
def test_r14_doc_path_through_soffice():
    """生产 R14 的真实路径：.doc →（soffice）→ docx → docx_reader。取证串与 spec 一致。"""
    doc_bytes, why = textextract.libreoffice_convert_ex(
        make_docx(r14_body(), numbering_xml=R14_NUMBERING), "docx", "doc")
    assert doc_bytes is not None, why
    out = extract_document(doc_bytes, "doc", file_name="结算审核报告.doc")
    assert out.failure is None
    assert "（三）公装部分" in out.text
    assert "3、竣工图纸" in out.text
