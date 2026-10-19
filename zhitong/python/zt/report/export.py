# 来源：engine-service/app/engine/report_export.py（zhitong-cost-ai@991ff5c，W3 搬入 zt；只改了 import）
"""docx 导出:零依赖手写 OOXML(python-docx 未装亦可部署)。

移植自素材仓 app/pipeline/report_export.py 的 build_docx()(纯函数，无 DB/store 耦合)。

WS12-B（P09，issue #758）重写：改前导出件 47 段里 19 段是空段、章标题重复、只有 Normal 一种段落
样式、没有任何「AI 初稿」标记，正文里一个 `\\x0b` 就能让整份 docx 打不开。现在：

- 部件：[Content_Types].xml、_rels/.rels、word/document.xml、word/styles.xml（Normal / Title / Heading1，
  均显式设 eastAsia 字体）、word/header1.xml（页眉 = disclaimer）、word/_rels/document.xml.rels；
- 正文段落用 pStyle 引用样式；空行不成段；正文首行等于章标题时再防御性地剥一次；
- 文末附录「资料来源与完成度」：来源文件、各章质量态、待补清单、待核清单；
- 所有文本先过 `_xml_safe`：XML 1.0 不允许的控制字符（\\x00-\\x08、\\x0b、\\x0c、\\x0e-\\x1f）直接剔除。

中文字体铁律(踩过坑):每个 run 的 w:rPr 必须带 w:rFonts 且**显式设 w:eastAsia**——
只设西文名(w:ascii/w:hAnsi)时中文会回落到日文字体(MS 明朝等),Mac/WPS 下字号忽大忽小。
标题=黑体,正文/表格=宋体。
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Optional, Sequence
from xml.sax.saxutils import escape

from zt.report.guard import (
    INSUFFICIENT_MIN_CHARS,
    MARK_TRUNCATED,
    is_mostly_todo,
    meaningful_chars,
    title_key,
    todo_count,
)

DEFAULT_DISCLAIMER = "AI 初稿，金额未经人工核对，不得直接出具"
APPENDIX_TITLE = "资料来源与完成度"

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
</Relationships>"""

# 字体名:黑体=标题,宋体=正文/表格。ascii/hAnsi 一并设同名,eastAsia 是中文回落的关键那一栏。
_FONT_HEI = "黑体"
_FONT_SONG = "宋体"

# 占位标注:无真实业务数据源的报表行统一打此标,严禁编造数字(列入 deferred)。
PLACEHOLDER_MARK = "(待接入真实业务数据)"

# XML 1.0 合法字符之外的控制字符（\t \n \r 合法）
_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _xml_safe(text: object) -> str:
    """剔除 XML 非法控制字符后再转义。所有进 docx 的文本都必须过这里。"""
    return escape(_XML_ILLEGAL.sub("", "" if text is None else str(text)))


def _fonts(font: str) -> str:
    f = _xml_safe(font)
    return f'<w:rFonts w:ascii="{f}" w:eastAsia="{f}" w:hAnsi="{f}"/>'


def _style(style_id: str, name: str, *, font: str, size: int, bold: bool, extra_ppr: str = "",
           default: bool = False) -> str:
    default_attr = ' w:default="1"' if default else ""
    based = "" if default else '<w:basedOn w:val="Normal"/><w:next w:val="Normal"/>'
    bold_tag = "<w:b/>" if bold else ""
    return (
        f'<w:style w:type="paragraph"{default_attr} w:styleId="{style_id}">'
        f'<w:name w:val="{name}"/>{based}'
        f"<w:pPr>{extra_ppr}</w:pPr>"
        f'<w:rPr>{bold_tag}{_fonts(font)}<w:sz w:val="{size}"/></w:rPr>'
        "</w:style>"
    )


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:styles xmlns:w="{_W_NS}">'
    + _style("Normal", "Normal", font=_FONT_SONG, size=24, bold=False,
             extra_ppr='<w:spacing w:after="120" w:line="360" w:lineRule="auto"/>', default=True)
    + _style("Title", "Title", font=_FONT_HEI, size=36, bold=True,
             extra_ppr='<w:jc w:val="center"/><w:spacing w:after="240"/>')
    + _style("Heading1", "heading 1", font=_FONT_HEI, size=28, bold=True,
             extra_ppr='<w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="0"/>')
    + "</w:styles>"
)


def _rpr(*, bold: bool, size: int, font: str) -> str:
    """run 属性:粗体 + 三名字体(含 eastAsia 中文回落) + 字号(半磅)。"""
    bold_tag = "<w:b/>" if bold else ""
    return f'<w:rPr>{bold_tag}{_fonts(font)}<w:sz w:val="{size}"/></w:rPr>'


def _para(text: str, *, style: str = "Normal", bold: bool = False, size: int = 24,
          font: str = _FONT_SONG) -> str:
    """一个 w:p 段落，引用 pStyle；run 上仍显式带字体（WPS 不一定读样式里的 eastAsia）。"""
    return (
        f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
        f"<w:r>{_rpr(bold=bold, size=size, font=font)}"
        f'<w:t xml:space="preserve">{_xml_safe(text)}</w:t></w:r></w:p>'
    )


_TBL_BORDERS = (
    "<w:tblBorders>"
    '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
    '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
    '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
    '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
    '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
    '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
    "</w:tblBorders>"
)


def _tc(text: object, *, bold: bool = False) -> str:
    """一个表格单元格 w:tc(内含一个宋体段落)。"""
    return (
        '<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>'
        f"<w:p><w:r>{_rpr(bold=bold, size=24, font=_FONT_SONG)}"
        f'<w:t xml:space="preserve">{_xml_safe(text)}</w:t></w:r></w:p></w:tc>'
    )


def _tr(cells: list, *, bold: bool = False) -> str:
    return "<w:tr>" + "".join(_tc(c, bold=bold) for c in cells) + "</w:tr>"


def _table(headers: list[str], rows: list[list]) -> str:
    """带边框的真 Word 表格 w:tbl:表头行加粗 + 数据行。产物为 well-formed OOXML 片段。"""
    grid = "<w:tblGrid>" + "<w:gridCol w:w=\"1200\"/>" * len(headers) + "</w:tblGrid>"
    tbl_pr = f'<w:tblPr><w:tblW w:w="0" w:type="auto"/>{_TBL_BORDERS}</w:tblPr>'
    body = [_tr(headers, bold=True)]
    for r in rows:
        body.append(_tr(list(r)))
    return f"<w:tbl>{tbl_pr}{grid}{''.join(body)}</w:tbl>"


def _body_lines(title: str, content: str) -> list[str]:
    """正文 → 段落文本：空行不成段；首个非空行与章标题同键（序号不算，见 report_guard.title_key）时剥掉
    （P09 防御层，护栏里已剥过一次；WS24-g 起「三、编制依据」下的「一、编制依据」也剥）。"""
    lines = [ln.strip() for ln in (content or "").replace("\r\n", "\n").split("\n")]
    lines = [ln for ln in lines if ln]
    if lines and title and title_key(title) and title_key(lines[0]) == title_key(title):
        lines = lines[1:]
    return lines


# ---------------------------------------------------------------- 附录（WS24-g，R24-37 / R24-08）
#
# 改前：各章质量写「含待核」，下一行却是「待核清单：无」（标签按 flags 有没有、清单按 flags 拼）；待补清单取的是
# missing_items —— 它只在元话语改写时才有内容，运行 A 正文 29 处【待补】，附录写「待补清单：无」。
# 现在三样都从正文数：标签与界面同一套口径（前端 sectionView.ts 的 sectionTag），清单就是正文里的那些标记。

_TODO_MARK = re.compile(r"【待补([^】\n]*)】")
_VERIFY_MARK = re.compile(r"【待核([^】\n]*)】")
_ANY_MARK = re.compile(r"【[^】\n]*】|\[资料\s*\d+\]")
# 待核清单每条取标记前同一小句的字：「…，较送审减少1935元【待核…】」只取「较送审减少1935元」
_CLAUSE_BREAK = re.compile(r"[。！？!?；;，,、：:\n]")
# 不插标记、只记在 flags 里的两类：待核清单里也要列出来，读者才找得到
_UNMARKED_FLAG_KINDS = ("transcribed", "unknown_citation")
VERIFY_LIST_MAX = 200
VERIFY_CONTEXT_CHARS = 24


def _inner(m: re.Match) -> str:
    return m.group(1).lstrip("：:").strip()


def _count(rx: re.Pattern, content: str) -> int:
    return len(rx.findall(content or ""))


def section_label(sec: dict) -> str:
    """一章的质量标签，与界面（sectionView.ts sectionTag）同一套口径：「含待核 N 处」的 N 是正文里【待核】的处数，
    不是 flags 的条数（transcribed、unknown_citation 不插标记）。"""
    q = sec.get("quality") or ""
    content = sec.get("content") or ""
    flags = [f for f in (sec.get("flags") or []) if isinstance(f, dict)]
    n = _count(_VERIFY_MARK, content)
    if q == "failed":
        return "未生成"
    if MARK_TRUNCATED in content:
        return "未写完" + (f" · 含待核 {n} 处" if n else "")
    if q in ("insufficient", "empty"):
        mostly = (q == "insufficient" and meaningful_chars(content) >= INSUFFICIENT_MIN_CHARS
                  and is_mostly_todo(content))
        return f"资料不足（待补 {todo_count(content)} 处）" if mostly else "资料不足"
    transcribed = any(f.get("kind") == "transcribed" for f in flags)
    if n:
        return f"含待核 {n} 处" + (" · 疑似转写" if transcribed else "")
    if transcribed:
        return "疑似转写"
    bad_cites = sum(1 for f in flags if f.get("kind") == "unknown_citation")
    if bad_cites:
        return f"引用编号有误 {bad_cites} 处"
    return "AI 初稿·待核"


def _todo_items(content: str) -> list[str]:
    """正文里的【待补：…】，同章去重、按出现顺序。"""
    out: list[str] = []
    for m in _TODO_MARK.finditer(content or ""):
        item = _inner(m) or "（未写明缺什么）"
        if item not in out:
            out.append(item)
    return out


def _verify_items(content: str) -> list[str]:
    """正文里每一处【待核：…】一条：标记前同一小句里的字（去掉别的标记，最多 24 个）+ 原因。"""
    out: list[str] = []
    for m in _VERIFY_MARK.finditer(content or ""):
        # 先去掉别的标记再切小句：【待补：资料《x》无法读取】里的「：」不是小句的边界
        head = _ANY_MARK.sub("", content[:m.start()])
        cut = max((x.end() for x in _CLAUSE_BREAK.finditer(head)), default=0)
        ctx = head[cut:].strip()
        if len(ctx) > VERIFY_CONTEXT_CHARS:
            ctx = "…" + ctx[-VERIFY_CONTEXT_CHARS:]
        reason = _inner(m) or "待核"
        out.append(f"{ctx}（{reason}）" if ctx else reason)
    return out


def _appendix(sections: Sequence[dict], appendix: Optional[dict]) -> list[str]:
    body = [_para(APPENDIX_TITLE, style="Heading1", bold=True, size=28, font=_FONT_HEI)]
    ap = appendix or {}
    src = ap.get("source_files") or []
    body.append(_para("来源文件：" + ("、".join(src) if src else "（未提供）")))
    unread = ap.get("unreadable_files") or []
    if unread:
        body.append(_para("无法读取的资料：" + "、".join(unread)))
    hidden = ap.get("hidden_sheets") or []
    if hidden:
        body.append(_para("已跳过隐藏工作表：" + "、".join(hidden)))
    # WS24-j：金额没有程序取数时的提示，与界面第四步顶部同一份文字（Java 从 report_instance.context_facts 拼）
    for note in ap.get("amount_notes") or []:
        body.append(_para("金额：" + str(note)))
    for s in sections:
        body.append(_para(f"{s.get('title') or ''}：{section_label(s)}"))

    # 待补清单：按章一行，同章去重。一处都没有才写「无」（missing_items 不再进附录：它存的是被改写前的原句，
    # 比如「资料1至资料24未提供正文…」，正是要从正文里去掉的那种话，WS24-f 评审遗留）
    todo_lines = [f"{s.get('title') or ''}：{'；'.join(items)}"
                  for s in sections for items in [_todo_items(s.get("content") or "")] if items]
    if todo_lines:
        body.append(_para("待补清单："))
        body.extend(_para(line) for line in todo_lines)
    else:
        body.append(_para("待补清单：无"))

    # 待核清单：每条一行（改前用「；」把 55 条挤成一段）
    verify: list[str] = []
    for s in sections:
        title = s.get("title") or ""
        verify.extend(f"{title}：{item}" for item in _verify_items(s.get("content") or ""))
        verify.extend(f"{title}：{f.get('text')}（{f.get('message')}）"
                      for f in (s.get("flags") or []) if isinstance(f, dict)
                      and f.get("kind") in _UNMARKED_FLAG_KINDS)
    if verify:
        body.append(_para("待核清单："))
        body.extend(_para(line) for line in verify[:VERIFY_LIST_MAX])
        if len(verify) > VERIFY_LIST_MAX:
            body.append(_para(f"（另有 {len(verify) - VERIFY_LIST_MAX} 条未列出，见各章正文里的【待核】）"))
    else:
        body.append(_para("待核清单：无"))
    return body


def build_docx(title: str, sections: list, *, disclaimer: Optional[str] = None,
               appendix: Optional[dict] = None) -> bytes:
    """sections 每项是 (章节标题, 正文) / (章节标题, 正文, table)，或 dict
    {title, content, table?, quality?, missing_items?, flags?}；table={'headers':[...], 'rows':[[...]]}。

    有 table 的章节在正文后渲染成真 Word 表格(非段落)。传了 dict 形态的 sections 时文末追加附录。
    """
    norm: list[dict] = []
    for sec in sections:
        if isinstance(sec, dict):
            norm.append(sec)
        else:
            norm.append({"title": sec[0], "content": sec[1], "table": sec[2] if len(sec) > 2 else None})
    body: list[str] = [_para(title, style="Title", bold=True, size=36, font=_FONT_HEI)]
    for sec in norm:
        sec_title = sec.get("title") or ""
        body.append(_para(sec_title, style="Heading1", bold=True, size=28, font=_FONT_HEI))
        for line in _body_lines(sec_title, sec.get("content") or ""):
            body.append(_para(line))
        table = sec.get("table")
        if table and table.get("headers"):
            body.append(_table(table["headers"], table.get("rows") or []))
    if any(isinstance(sec, dict) for sec in sections) or appendix:
        body.extend(_appendix(norm, appendix))
    sect_pr = (
        '<w:sectPr><w:headerReference w:type="default" r:id="rId2"/>'
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="851" w:footer="992" w:gutter="0"/>'
        "</w:sectPr>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}" xmlns:r="{_R_NS}">'
        f"<w:body>{''.join(body)}{sect_pr}</w:body></w:document>"
    )
    header = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:hdr xmlns:w="{_W_NS}" xmlns:r="{_R_NS}">'
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
        f"<w:r>{_rpr(bold=False, size=18, font=_FONT_SONG)}"
        f'<w:t xml:space="preserve">{_xml_safe(disclaimer or DEFAULT_DISCLAIMER)}</w:t></w:r></w:p>'
        "</w:hdr>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/header1.xml", header)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
    return buf.getvalue()
