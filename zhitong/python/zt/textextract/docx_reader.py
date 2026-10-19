"""docx 正文按 XML 解析（旧 WS04-P5；整改 spec 统一约定 C6：docx 结构只来自本模块）。

来源：/home/user/zhitong-cost-ai/engine-service/app/engine/docx_reader.py（纯标准库，逻辑未改）。

旧实现（textextract.docx_text）用正则剥标签，三处错：

- 修订：`w:del` / `w:delText` 里**已删除**的文字被当成现行条款（生产 R02：『上浮50%』
  『或业主经济损失2%』×6 —— 定稿里早删了）；
- 域：`TOC \\o "1-1" … HYPERLINK … PAGEREF` 这类**域指令**进了正文开头；
- 实体：`&quot;` `&lt;` `&gt;` 不还原（#689：`<<规范>>` 变成 `&lt;&lt;规范&gt;&gt;`）。

本模块按「接受全部修订」的视图取文本：跳过 `w:del` / `w:moveFrom` 整棵子树与
`w:delText` / `w:delInstrText`，保留 `w:ins` / `w:moveTo`；域用一个跨段落的栈跟踪
（`fldChar begin` 进指令区、`separate` 起输出结果、`end` 出栈，可嵌套 —— TOC 里套
HYPERLINK 与 PAGEREF），`fldSimple` 只取子节点里的结果文字；实体交给 XML 解析器还原。

块级 API（`read_docx().blocks` / `docx_blocks()`）供 filetree（WS05）与工程量清单（WS11）
复用：段落一块、表格一行一块（格间制表符），块号从 1 起，与 C4 EvidenceRef.paragraph
同口径。

自动编号（WS04-P10）：Word 的「1、」「（三）」是 `w:numPr` → `numbering.xml` 渲染出来的，
不在 `w:t` 里（生产 R14：「（三）」「（四）」0 次、「3、竣工图纸」缺「3、」）。本模块按
num → abstractNum（含 lvlOverride / startOverride / numStyleLink）、每级 start / numFmt /
lvlText 还原序号，放进 `num_prefix`（`text` 仍是段落本身，filetree 的标题与 GREP 用它，
块号不受影响）。计数按 abstractNum 分开记，上级编号时下级归位（lvlRestart 另算）；样式上
挂的编号同样解析。不认识的 numFmt 按阿拉伯数字输出并打 `numbering_fallback`；numbering.xml
缺失 / 坏掉时正文照出、序号缺，打 `numbering_unresolved` / `numbering_parse_failed`（铁律 8：
退化要可见）。

安全：遇到 `<!DOCTYPE` / `<!ENTITY` 直接判解析失败（实体膨胀攻击），不交给解析器。
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterator, Literal, Optional

__all__ = [
    "DocxBlock",
    "DocxDoc",
    "DocxPara",
    "DocxParseError",
    "docx_blocks",
    "read_docx",
]

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"

_MAX_PART_BYTES = 256 * 1024 * 1024  # 解压后单个 XML 部件上限（zip 炸弹）
_DTD_RE = re.compile(rb"<!DOCTYPE|<!ENTITY", re.IGNORECASE)
_HEADING_NAME_RE = re.compile(r"^(?:heading|标题)\s*(\d)$", re.IGNORECASE)
_TOC_NAME_RE = re.compile(r"^(?:toc|目录)\s*\d$", re.IGNORECASE)


def _w(tag: str) -> str:
    return f"{{{_W}}}{tag}"


def _wattr(el: ET.Element, name: str) -> Optional[str]:
    return el.get(_w(name))


class DocxParseError(ValueError):
    """不是可解析的 docx（非 zip、缺 document.xml、XML 非良构、带 DTD、部件过大）。"""


@dataclass
class DocxPara:
    text: str
    style_id: Optional[str] = None
    heading_level: Optional[int] = None
    num_prefix: str = ""
    in_table: bool = False
    is_toc: bool = False


@dataclass
class DocxBlock:
    no: int
    kind: Literal["p", "row"]
    text: str
    cells: list[str] = field(default_factory=list)
    style_id: Optional[str] = None
    heading_level: Optional[int] = None
    num_prefix: str = ""
    is_toc: bool = False
    table_index: Optional[int] = None
    row_index: Optional[int] = None
    # R4F-d fix15：与 cells 逐格对应、逐字等长的「格内原文」——格内另起一段 / 软回车（w:br）处是换行，其余空白
    # 折成空格（cells 里全部折成空格）。工程量清单的存疑闸按它判合同句界（单元格内的硬换行是句界），
    # 切层与对外文本仍只用 cells，块号、格文字与既有调用方都不变
    cells_raw: list[str] = field(default_factory=list)


@dataclass
class DocxDoc:
    paragraphs: list[DocxPara]
    blocks: list[DocxBlock]
    has_revisions: bool = False
    has_fields: bool = False
    flags: list[str] = field(default_factory=list)

    def text(self) -> str:
        """非空块按 `num_prefix + text` 换行连接；表格一行一行、格间制表符。"""
        return "\n".join(
            b.num_prefix + b.text for b in self.blocks if (b.num_prefix + b.text).strip()
        ).strip()


def _read_part(z: zipfile.ZipFile, name: str, *, required: bool) -> Optional[bytes]:
    try:
        info = z.getinfo(name)
    except KeyError:
        if required:
            raise DocxParseError(f"docx 缺少 {name}")
        return None
    if info.file_size > _MAX_PART_BYTES:
        raise DocxParseError(f"{name} 解压后 {info.file_size} 字节，超过上限")
    raw = z.read(name)
    if _DTD_RE.search(raw):
        raise DocxParseError(f"{name} 带 DOCTYPE/ENTITY 声明，拒绝解析（实体膨胀防护）")
    return raw


def _parse_xml(raw: bytes, name: str) -> ET.Element:
    try:
        return ET.fromstring(raw)
    except ET.ParseError as e:
        raise DocxParseError(f"{name} 不是良构 XML：{e}") from e


@dataclass
class _Style:
    name: str = ""
    based_on: Optional[str] = None
    outline: Optional[int] = None
    num_id: Optional[str] = None      # 样式上挂的编号（pPr/numPr/numId）
    num_ilvl: Optional[int] = None


def _load_styles(root: Optional[ET.Element]) -> dict[str, _Style]:
    styles: dict[str, _Style] = {}
    if root is None:
        return styles
    for st in root.iter(_w("style")):
        sid = _wattr(st, "styleId")
        if not sid:
            continue
        s = _Style()
        name = st.find(_w("name"))
        if name is not None:
            s.name = _wattr(name, "val") or ""
        based = st.find(_w("basedOn"))
        if based is not None:
            s.based_on = _wattr(based, "val")
        lvl = st.find(f"{_w('pPr')}/{_w('outlineLvl')}")
        if lvl is not None:
            s.outline = _outline_to_level(_wattr(lvl, "val"))
        numpr = st.find(f"{_w('pPr')}/{_w('numPr')}")
        if numpr is not None:
            s.num_id, s.num_ilvl = _numpr_values(numpr)
        styles[sid] = s
    return styles


def _int_attr(el: Optional[ET.Element], name: str = "val") -> Optional[int]:
    if el is None:
        return None
    try:
        return int(_wattr(el, name) or "")
    except ValueError:
        return None


def _numpr_values(numpr: ET.Element) -> tuple[Optional[str], Optional[int]]:
    nid = numpr.find(_w("numId"))
    ilvl = _int_attr(numpr.find(_w("ilvl")))
    return (_wattr(nid, "val") if nid is not None else None), ilvl


# =============================================================================
# 自动编号（WS04-P10）
# =============================================================================

_MAX_LEVELS = 9
_LVL_REF_RE = re.compile(r"%([1-9])")

_CN_DIGITS = "零一二三四五六七八九"
_CN_UNITS = ("", "十", "百", "千")
_CN_LEGAL_SIMP = "零壹贰叁肆伍陆柒捌玖"
_CN_LEGAL_TRAD = "零壹貳參肆伍陸柒捌玖"
_CN_LEGAL_UNITS = ("", "拾", "佰", "仟")
_TIANGAN = "甲乙丙丁戊己庚辛壬癸"
_DIZHI = "子丑寅卯辰巳午未申酉戌亥"
_FULLWIDTH = str.maketrans("0123456789", "０１２３４５６７８９")
_ROMAN = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
          (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
# 中文小写计数（十一、二十）：Word 各地区的计数格式在中文文档里都渲染成这一套；
# .doc 经 soffice 往返后 chineseCounting 会变成 taiwaneseCountingThousand（本机实测）
_CN_COUNTING_FMTS = frozenset({
    "chineseCounting", "chineseCountingThousand", "taiwaneseCounting",
    "taiwaneseCountingThousand", "japaneseCounting",
})


@dataclass
class _Lvl:
    start: int = 0          # ECMA-376 17.9.25：缺省起始值是 0
    fmt: str = "decimal"
    custom: str = ""        # numFmt=custom 时的 w:format（「001, 002, …」）
    text: str = ""
    restart: Optional[int] = None
    is_lgl: bool = False
    suff: str = "tab"
    pstyle: Optional[str] = None
    pic_bullet: bool = False


@dataclass
class _AbstractNum:
    levels: dict[int, _Lvl] = field(default_factory=dict)
    num_style_link: Optional[str] = None


@dataclass
class _Num:
    abstract_id: str
    start_overrides: dict[int, int] = field(default_factory=dict)
    lvl_overrides: dict[int, _Lvl] = field(default_factory=dict)


def _numfmt_of(lvl_el: ET.Element) -> tuple[str, str]:
    direct = lvl_el.find(_w("numFmt"))
    if direct is not None:
        return _wattr(direct, "val") or "decimal", _wattr(direct, "format") or ""
    # Word 2010+ 把「001, 002」这类自定义格式放进 mc:AlternateContent：Choice 是 custom，
    # Fallback 是等价的标准格式。能认的 custom 用它，否则取 Fallback
    found: list[tuple[str, str]] = []
    for ac in lvl_el.findall(f"{{{_MC}}}AlternateContent"):
        for el in ac.iter(_w("numFmt")):
            found.append((_wattr(el, "val") or "decimal", _wattr(el, "format") or ""))
    for fmt, custom in found:
        if fmt == "custom" and _custom_width(custom):
            return fmt, custom
    for fmt, custom in found:
        if fmt != "custom":
            return fmt, custom
    return "decimal", ""


def _parse_lvl(el: ET.Element) -> _Lvl:
    lv = _Lvl()
    start = _int_attr(el.find(_w("start")))
    if start is not None:
        lv.start = start
    lv.fmt, lv.custom = _numfmt_of(el)
    text = el.find(_w("lvlText"))
    if text is not None:
        lv.text = _wattr(text, "val") or ""
    lv.restart = _int_attr(el.find(_w("lvlRestart")))
    lgl = el.find(_w("isLgl"))
    lv.is_lgl = lgl is not None and (_wattr(lgl, "val") or "1") not in ("0", "false", "off")
    suff = el.find(_w("suff"))
    if suff is not None:
        lv.suff = _wattr(suff, "val") or "tab"
    ps = el.find(_w("pStyle"))
    if ps is not None:
        lv.pstyle = _wattr(ps, "val")
    lv.pic_bullet = el.find(_w("lvlPicBulletId")) is not None
    return lv


def _custom_width(custom: str) -> int:
    """「001, 002, 003, ...」→ 3；认不出的自定义格式返回 0。"""
    first = custom.split(",", 1)[0].strip()
    return len(first) if re.fullmatch(r"0*1", first) else 0


def _cn_under_10000(n: int, digits: str, units: tuple[str, ...]) -> str:
    out: list[str] = []
    zero = False
    for pos in (3, 2, 1, 0):
        d = n // 10 ** pos % 10
        if d == 0:
            zero = bool(out)
            continue
        if zero:
            out.append(digits[0])
            zero = False
        out.append(digits[d] + units[pos])
    return "".join(out)


def _cn_number(n: int, digits: str, units: tuple[str, ...], *, drop_leading_one: bool) -> str:
    if n < 10000:
        s = _cn_under_10000(n, digits, units)
        # 计数写法「十一」不是「一十一」；大写「壹拾贰」保留「壹」
        if drop_leading_one and 10 <= n < 20:
            s = s[1:]
        return s
    hi, lo = divmod(n, 10000)
    s = _cn_number(hi, digits, units, drop_leading_one=drop_leading_one) + "万"
    if lo:
        s += (digits[0] if lo < 1000 else "") + _cn_under_10000(lo, digits, units)
    return s


def _letters(n: int, base: str) -> str:
    return chr(ord(base) + (n - 1) % 26) * ((n - 1) // 26 + 1)


def _roman(n: int) -> str:
    out = []
    for v, s in _ROMAN:
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


def _enclosed(n: int, ranges: tuple[tuple[int, int, int], ...]) -> Optional[str]:
    for lo, hi, base in ranges:
        if lo <= n <= hi:
            return chr(base + n - lo)
    return None


_CIRCLED = ((1, 20, 0x2460), (21, 35, 0x3251), (36, 50, 0x32B1))


def _format_number(n: int, fmt: str, custom: str = "") -> tuple[str, bool]:
    """按 numFmt 把计数格式化。返回 (文字, 是否认得这种格式)；认不得时按阿拉伯数字。"""
    if fmt == "none":
        return "", True
    if fmt in ("decimal", "decimalHalfWidth"):
        return str(n), True
    if fmt == "decimalZero":
        return f"{n:02d}" if n >= 0 else str(n), True
    if fmt in ("decimalFullWidth", "decimalFullWidth2"):
        return str(n).translate(_FULLWIDTH), True
    if fmt == "custom":
        width = _custom_width(custom)
        return (str(n).zfill(width), True) if width else (str(n), False)
    if n <= 0:
        return str(n), False
    if fmt in _CN_COUNTING_FMTS:
        return _cn_number(n, _CN_DIGITS, _CN_UNITS, drop_leading_one=True), True
    if fmt in ("ideographDigital", "taiwaneseDigital", "japaneseDigitalTenThousand"):
        return "".join("〇一二三四五六七八九"[int(d)] for d in str(n)), True
    if fmt == "chineseLegalSimplified":
        return _cn_number(n, _CN_LEGAL_SIMP, _CN_LEGAL_UNITS, drop_leading_one=False), True
    if fmt == "ideographLegalTraditional":
        return _cn_number(n, _CN_LEGAL_TRAD, _CN_LEGAL_UNITS, drop_leading_one=False), True
    if fmt == "ideographTraditional":
        return (_TIANGAN[n - 1], True) if n <= 10 else (str(n), False)
    if fmt == "ideographZodiac":
        return (_DIZHI[n - 1], True) if n <= 12 else (str(n), False)
    if fmt == "lowerLetter":
        return _letters(n, "a"), True
    if fmt == "upperLetter":
        return _letters(n, "A"), True
    if fmt in ("lowerRoman", "upperRoman"):
        if n >= 4000:
            return str(n), False
        r = _roman(n)
        return (r.lower() if fmt == "lowerRoman" else r), True
    # 圈码类超出字符集时 Word 也显示普通数字：这是既定行为，不算认不得
    if fmt in ("decimalEnclosedCircle", "decimalEnclosedCircleChinese"):
        return _enclosed(n, _CIRCLED) or str(n), True
    if fmt == "decimalEnclosedParen":
        return _enclosed(n, ((1, 20, 0x2474),)) or str(n), True
    if fmt == "decimalEnclosedFullstop":
        return _enclosed(n, ((1, 20, 0x2488),)) or str(n), True
    if fmt == "ideographEnclosedCircle":
        return _enclosed(n, ((1, 10, 0x3220),)) or str(n), True
    return str(n), False


def _bullet_text(lv: _Lvl) -> str:
    t = lv.text.strip()
    if lv.pic_bullet or not t:
        return "•"
    if t == "o":            # Courier New 的「o」是空心圆符号
        return "◦"
    # Symbol / Wingdings 字体的字形编码在私用区 U+F000–F0FF，离开字体就是乱码
    return "".join("•" if 0xF000 <= ord(ch) <= 0xF0FF else ch for ch in t)


def _joiner(marker: str, suff: str) -> str:
    """序号与正文之间：中文标点结尾（「3、」「（三）」「１．」）不加空格，与原文一致；
    其余加一个 —— 「1.」紧贴「5层」会读成 1.5（铁律 2/3：数字不能被读错）。"""
    if not marker or suff == "nothing":
        return ""
    c = ord(marker[-1])
    if 0x3000 <= c <= 0x303F or 0xFF00 <= c <= 0xFFEF:
        return ""
    return " "


class _Numbering:
    """numbering.xml 的解析结果 + 按文档顺序推进的计数器。"""

    def __init__(self, root: ET.Element, styles: dict[str, _Style]) -> None:
        self.styles = styles
        self.abstracts: dict[str, _AbstractNum] = {}
        self.nums: dict[str, _Num] = {}
        for an in root.findall(_w("abstractNum")):
            aid = _wattr(an, "abstractNumId")
            if aid is None:
                continue
            a = _AbstractNum()
            for el in an.findall(_w("lvl")):
                ilvl = _int_attr(el, "ilvl")
                if ilvl is not None and 0 <= ilvl < _MAX_LEVELS:
                    a.levels[ilvl] = _parse_lvl(el)
            link = an.find(_w("numStyleLink"))
            if link is not None:
                a.num_style_link = _wattr(link, "val")
            self.abstracts[aid] = a
        for n in root.findall(_w("num")):
            nid = _wattr(n, "numId")
            ref = n.find(_w("abstractNumId"))
            if nid is None or ref is None or _wattr(ref, "val") is None:
                continue
            num = _Num(abstract_id=_wattr(ref, "val") or "")
            for ov in n.findall(_w("lvlOverride")):
                ilvl = _int_attr(ov, "ilvl")
                if ilvl is None or not 0 <= ilvl < _MAX_LEVELS:
                    continue
                so = _int_attr(ov.find(_w("startOverride")))
                if so is not None:
                    num.start_overrides[ilvl] = so
                lv = ov.find(_w("lvl"))
                if lv is not None:
                    num.lvl_overrides[ilvl] = _parse_lvl(lv)
            self.nums[nid] = num
        self.counters: dict[str, list[Optional[int]]] = {}
        self._applied_overrides: set[tuple[str, int]] = set()

    def _resolve(self, num_id: str) -> Optional[tuple[str, dict[int, _Lvl]]]:
        num = self.nums.get(num_id)
        if num is None:
            return None
        aid = num.abstract_id
        absn = self.abstracts.get(aid)
        seen: set[str] = set()
        # numStyleLink：真正的级别定义在编号样式所指 num 的 abstractNum 里
        while absn is not None and absn.num_style_link and aid not in seen and len(seen) < 4:
            seen.add(aid)
            st = self.styles.get(absn.num_style_link)
            linked = self.nums.get(st.num_id) if st is not None and st.num_id else None
            if linked is None:
                break
            aid = linked.abstract_id
            absn = self.abstracts.get(aid)
        if absn is None:
            return None
        levels = dict(absn.levels)
        levels.update(num.lvl_overrides)
        return aid, levels

    def level_for_style(self, num_id: str, style_ids: list[str]) -> Optional[int]:
        res = self._resolve(num_id)
        if res is not None:
            for sid in style_ids:
                for ilvl, lv in sorted(res[1].items()):
                    if lv.pstyle == sid:
                        return ilvl
        return None

    def next_marker(self, num_id: str, ilvl: int) -> Optional[tuple[str, str, bool]]:
        """推进计数并渲染序号：返回 (序号文字, suff, 是否全部认得)；num 找不到返回 None。"""
        res = self._resolve(num_id)
        if res is None:
            return None
        aid, levels = res
        lv = levels.get(ilvl)
        if lv is None:
            return None
        counters = self.counters.setdefault(aid, [None] * _MAX_LEVELS)
        key = (num_id, ilvl)
        override = self.nums[num_id].start_overrides.get(ilvl)
        if override is not None and key not in self._applied_overrides:
            self._applied_overrides.add(key)
            counters[ilvl] = override
        elif counters[ilvl] is None:
            counters[ilvl] = lv.start
        else:
            counters[ilvl] += 1
        # 上级编号时下级归位；lvlRestart=k（1 基）只在 k 级及更上级编号时归位，0 = 从不归位
        # （ECMA-376 17.9.10；Word 照此，LibreOffice 忽略 lvlRestart —— 按 Word）
        for k in range(ilvl + 1, _MAX_LEVELS):
            restart = levels[k].restart if k in levels else None
            if restart is None or (restart != 0 and ilvl < restart):
                counters[k] = None

        if lv.fmt == "bullet" or lv.pic_bullet:
            return _bullet_text(lv), lv.suff, True
        exact = True

        def sub(m: re.Match) -> str:
            nonlocal exact
            j = int(m.group(1)) - 1
            ref = levels.get(j) or _Lvl(start=1)
            value = counters[j] if counters[j] is not None else ref.start
            fmt = ref.fmt
            if lv.is_lgl and fmt not in ("none", "bullet"):
                fmt = "decimal"
            s, ok = _format_number(value, fmt, ref.custom)
            exact = exact and ok
            return s

        return _LVL_REF_RE.sub(sub, lv.text), lv.suff, exact


def _outline_to_level(val: Optional[str]) -> Optional[int]:
    try:
        n = int(val or "")
    except ValueError:
        return None
    return n + 1 if 0 <= n <= 8 else None  # 9 = 正文级


class _Walker:
    def __init__(self, styles: dict[str, _Style], numbering: Optional[_Numbering] = None,
                 flags: Optional[list[str]] = None) -> None:
        self.styles = styles
        self.numbering = numbering
        self.fields: list[dict] = []  # {"phase": "instr"|"result", "instr": [str]}
        self.has_revisions = False
        self.has_fields = False
        self.flags: list[str] = list(flags or [])
        self.paragraphs: list[DocxPara] = []
        self.blocks: list[DocxBlock] = []
        self._tables = 0

    # —— 域状态 ——
    def _emitting(self) -> bool:
        return all(f["phase"] == "result" for f in self.fields)

    def _in_toc(self) -> bool:
        return any("".join(f["instr"]).strip().upper().startswith("TOC") for f in self.fields)

    # —— 样式 ——
    def _style_info(self, sid: Optional[str]) -> tuple[Optional[int], bool]:
        level: Optional[int] = None
        is_toc = False
        seen = set()
        cur = sid
        while cur and cur in self.styles and cur not in seen and len(seen) < 12:
            seen.add(cur)
            st = self.styles[cur]
            if cur == sid and _TOC_NAME_RE.match(st.name.strip()):
                is_toc = True
            m = _HEADING_NAME_RE.match(st.name.strip())
            if level is None and m:
                level = int(m.group(1))
            if level is None and st.outline is not None:
                level = st.outline
            if level is not None:
                break
            cur = st.based_on
        return level, is_toc

    # —— 块级容器 ——
    def container(self, el: ET.Element, *, in_table: bool = False) -> None:
        for child in el:
            tag = child.tag
            if tag == _w("p"):
                para = self.paragraph(child, in_table=in_table)
                if not in_table:
                    self._add_block("p", para.text, para=para)
            elif tag == _w("tbl"):
                if in_table:
                    # 嵌套表：拍平成段落文字，归入外层单元格
                    self._nested_table_as_paras(child)
                else:
                    self.table(child)
            elif tag in (_w("sdt"),):
                content = child.find(_w("sdtContent"))
                if content is not None:
                    self.container(content, in_table=in_table)
            elif tag in (_w("customXml"), _w("ins"), _w("moveTo")):
                if tag != _w("customXml"):
                    self.has_revisions = True
                self.container(child, in_table=in_table)
            elif tag in (_w("del"), _w("moveFrom")):
                self.has_revisions = True
            elif tag == f"{{{_MC}}}AlternateContent":
                pick = _pick_alternate(child)
                if pick is not None:
                    self.container(pick, in_table=in_table)

    def _add_block(self, kind: str, text: str, *, para: Optional[DocxPara] = None,
                   cells: Optional[list[str]] = None, table_index: Optional[int] = None,
                   row_index: Optional[int] = None, cells_raw: Optional[list[str]] = None) -> None:
        self.blocks.append(DocxBlock(
            no=len(self.blocks) + 1, kind=kind, text=text, cells=cells or [],
            style_id=para.style_id if para else None,
            heading_level=para.heading_level if para else None,
            num_prefix=para.num_prefix if para else "",
            is_toc=para.is_toc if para else False,
            table_index=table_index, row_index=row_index,
            cells_raw=cells_raw if cells_raw is not None else list(cells or []),
        ))

    def _flag(self, name: str) -> None:
        if name not in self.flags:
            self.flags.append(name)

    def _num_marker(self, ppr: Optional[ET.Element], style_id: Optional[str]) -> Optional[tuple[str, str]]:
        """段落的编号：先看段落 numPr，缺的 numId / ilvl 沿样式 basedOn 链补。
        每个带编号的段落都要调一次（空段落也计数，与 Word 一致）。返回 (序号, suff)。"""
        num_id: Optional[str] = None
        ilvl: Optional[int] = None
        if ppr is not None:
            numpr = ppr.find(_w("numPr"))
            if numpr is not None:
                num_id, ilvl = _numpr_values(numpr)
        from_style = num_id is None
        style_ilvl: Optional[int] = None
        chain: list[str] = []
        cur, seen = style_id, set()
        while cur and cur in self.styles and cur not in seen and len(seen) < 12:
            seen.add(cur)
            chain.append(cur)
            st = self.styles[cur]
            if num_id is None and st.num_id is not None:
                num_id = st.num_id
            if style_ilvl is None and st.num_ilvl is not None and num_id == st.num_id:
                style_ilvl = st.num_ilvl
            cur = st.based_on
        if num_id is None or num_id == "0":  # numId=0：显式去掉样式带来的编号
            return None
        if self.numbering is None:
            self._flag("numbering_unresolved")
            return None
        if ilvl is None and from_style:
            # ECMA-376 17.9.23：样式带来的编号，级别由 abstractNum 里 w:pStyle 指向该样式的
            # 那一级决定，样式自己的 ilvl 让位（LibreOffice 不认这条，Word 认；按 Word）
            ilvl = self.numbering.level_for_style(num_id, chain)
        if ilvl is None:
            ilvl = style_ilvl if style_ilvl is not None else 0
        ilvl = min(max(ilvl, 0), _MAX_LEVELS - 1)
        got = self.numbering.next_marker(num_id, ilvl)
        if got is None:
            self._flag("numbering_unresolved")
            return None
        marker, suff, exact = got
        if not exact:
            self._flag("numbering_fallback")
        return marker, suff

    def paragraph(self, p: ET.Element, *, in_table: bool) -> DocxPara:
        style_id: Optional[str] = None
        own_outline: Optional[int] = None
        ppr = p.find(_w("pPr"))
        if ppr is not None:
            ps = ppr.find(_w("pStyle"))
            if ps is not None:
                style_id = _wattr(ps, "val")
            ol = ppr.find(_w("outlineLvl"))
            if ol is not None:
                own_outline = _outline_to_level(_wattr(ol, "val"))
        marker = self._num_marker(ppr, style_id)
        toc_by_field = self._in_toc()
        out: list[str] = []
        self.inline(p, out)
        # 指令区跨不出段落：段末仍停在指令区的域按「结果开始」处理，避免一个坏域吞掉全文
        for f in self.fields:
            if f["phase"] == "instr":
                f["phase"] = "result"
                if "field_unterminated" not in self.flags:
                    self.flags.append("field_unterminated")
        level, toc_by_style = self._style_info(style_id)
        if own_outline is not None:
            level = own_outline
        text = "".join(out).strip()
        num_prefix = ""
        if marker is not None and marker[0]:
            num_prefix = marker[0] + (_joiner(marker[0], marker[1]) if text else "")
        para = DocxPara(
            text=text,
            style_id=style_id,
            heading_level=level,
            num_prefix=num_prefix,
            in_table=in_table,
            is_toc=toc_by_style or toc_by_field or self._in_toc(),
        )
        self.paragraphs.append(para)
        return para

    def inline(self, el: ET.Element, out: list[str]) -> None:
        for child in el:
            tag = child.tag
            if tag == _w("pPr"):
                continue
            if tag == _w("r"):
                self.run(child, out)
            elif tag in (_w("hyperlink"), _w("smartTag"), _w("customXml"), _w("fldSimple"),
                         _w("bdo"), _w("dir")):
                if tag == _w("fldSimple"):
                    self.has_fields = True
                self.inline(child, out)
            elif tag in (_w("ins"), _w("moveTo")):
                self.has_revisions = True
                self.inline(child, out)
            elif tag in (_w("del"), _w("moveFrom")):
                self.has_revisions = True
            elif tag == _w("sdt"):
                content = child.find(_w("sdtContent"))
                if content is not None:
                    self.inline(content, out)
            elif tag == f"{{{_MC}}}AlternateContent":
                pick = _pick_alternate(child)
                if pick is not None:
                    self.inline(pick, out)
            elif tag in (f"{{{_M}}}oMath", f"{{{_M}}}oMathPara"):
                if self._emitting():
                    out.append("".join(t.text or "" for t in child.iter(f"{{{_M}}}t")))

    def run(self, r: ET.Element, out: list[str]) -> None:
        for child in r:
            tag = child.tag
            if tag == _w("t"):
                if self._emitting():
                    out.append(child.text or "")
            elif tag == _w("fldChar"):
                self.has_fields = True
                kind = _wattr(child, "fldCharType")
                if kind == "begin":
                    self.fields.append({"phase": "instr", "instr": []})
                elif kind == "separate" and self.fields:
                    self.fields[-1]["phase"] = "result"
                elif kind == "end" and self.fields:
                    self.fields.pop()
            elif tag == _w("instrText"):
                self.has_fields = True
                if self.fields and self.fields[-1]["phase"] == "instr":
                    self.fields[-1]["instr"].append(child.text or "")
            elif tag in (_w("delText"), _w("delInstrText")):
                self.has_revisions = True
            elif tag == _w("tab"):
                if self._emitting():
                    out.append("\t")
            elif tag in (_w("br"), _w("cr")):
                if self._emitting():
                    out.append("\n")
            elif tag == _w("noBreakHyphen"):
                if self._emitting():
                    out.append("-")
            elif tag == _w("ruby"):
                # Word「拼音指南」：w:ruby 里 w:rubyBase 是正文里看得见的底字，w:rt 只是注音。改前整个 w:ruby 被跳过，
                # 「本层[未]采用」读成「本层采用」——底字连同否定一起丢了（R4F-d review15a K 族）。底字照正文取，注音丢弃
                base = child.find(_w("rubyBase"))
                if base is not None:
                    self.inline(base, out)
            elif tag in (_w("drawing"), _w("pict")) or tag == f"{{{_MC}}}AlternateContent":
                src = _pick_alternate(child) if tag == f"{{{_MC}}}AlternateContent" else child
                if src is not None and self._emitting():
                    box = self._textbox_text(src)
                    if box:
                        out.append(" " + box + " ")

    def _textbox_text(self, el: ET.Element) -> str:
        texts: list[str] = []
        for box in el.iter(_w("txbxContent")):
            for p in box.iter(_w("p")):
                buf: list[str] = []
                self.inline(p, buf)
                t = "".join(buf).strip()
                if t:
                    texts.append(t)
        return " ".join(texts)

    # —— 表格 ——
    def _rows(self, tbl: ET.Element) -> Iterator[ET.Element]:
        for child in tbl:
            if child.tag == _w("tr"):
                yield child
            elif child.tag == _w("sdt"):
                content = child.find(_w("sdtContent"))
                if content is not None:
                    yield from self._rows(content)
            elif child.tag in (_w("customXml"), _w("ins")):
                yield from self._rows(child)

    def _cells(self, tr: ET.Element) -> Iterator[ET.Element]:
        for child in tr:
            if child.tag == _w("tc"):
                yield child
            elif child.tag == _w("sdt"):
                content = child.find(_w("sdtContent"))
                if content is not None:
                    yield from self._cells(content)
            elif child.tag == _w("customXml"):
                yield from self._cells(child)

    def _row_deleted(self, tr: ET.Element) -> bool:
        trpr = tr.find(_w("trPr"))
        return trpr is not None and trpr.find(_w("del")) is not None

    def _cell_texts(self, tc: ET.Element) -> tuple[str, str]:
        """(格文字, 格内原文)。格文字：格内换行/制表符换成空格（一行一块、格间制表符的结构不能被格内容打乱）；
        格内原文：与格文字逐字等长，只是格内另起一段 / 软回车处保留为换行（R4F-d fix15，见 DocxBlock.cells_raw）。"""
        start = len(self.paragraphs)
        self.container(tc, in_table=True)
        # 格内段落的自动编号也是格子的内容（「序号」列常是自动编号，不拼上整列为空）
        parts = [p.num_prefix + p.text for p in self.paragraphs[start:] if p.num_prefix + p.text]
        text = " ".join(" ".join(parts).split())
        raw = _raw_join(parts)
        return text, (raw if raw.replace("\n", " ") == text else text)

    def _cell_text(self, tc: ET.Element) -> str:
        return self._cell_texts(tc)[0]

    def table(self, tbl: ET.Element) -> None:
        self._tables += 1
        tindex = self._tables
        for rindex, tr in enumerate(self._rows(tbl), start=1):
            if self._row_deleted(tr):
                self.has_revisions = True
                continue
            pairs = [self._cell_texts(tc) for tc in self._cells(tr)]
            cells = [t for t, _r in pairs]
            self._add_block("row", "\t".join(cells), cells=cells, cells_raw=[r for _t, r in pairs],
                            table_index=tindex, row_index=rindex)

    def _nested_table_as_paras(self, tbl: ET.Element) -> None:
        for tr in self._rows(tbl):
            if self._row_deleted(tr):
                self.has_revisions = True
                continue
            for tc in self._cells(tr):
                self.container(tc, in_table=True)


_LINE_BREAKS = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")


def _raw_join(parts: list[str]) -> str:
    """格内各段以换行相连，再把每一段连续空白折成一个字符：含换行的折成「\\n」，其余折成空格，去掉首尾空白。
    结果与 " ".join(" ".join(parts).split()) 逐字等长（只是部分空格是换行）。"""
    joined = "\n".join(parts)
    out: list[str] = []
    run: list[str] = []
    for ch in joined:
        if ch.isspace():
            run.append(ch)
            continue
        if run:
            out.append("\n" if any(c in _LINE_BREAKS for c in run) else " ")
            run = []
        out.append(ch)
    s = "".join(out)
    return s.strip()


def _pick_alternate(ac: ET.Element) -> Optional[ET.Element]:
    """mc:AlternateContent 的 Choice 与 Fallback 是同一内容的两份，只取一份，否则文字重复。"""
    choice = ac.find(f"{{{_MC}}}Choice")
    if choice is not None:
        return choice
    return ac.find(f"{{{_MC}}}Fallback")


def read_docx(content: bytes) -> DocxDoc:
    """解析 docx，失败抛 DocxParseError（调用方据此给出 parse_failed，不吞成空串）。"""
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, ValueError, OSError) as e:
        raise DocxParseError(f"不是 zip 容器：{e}") from e
    with z:
        doc_raw = _read_part(z, "word/document.xml", required=True)
        styles_raw = _read_part(z, "word/styles.xml", required=False)
        numbering_raw = _read_part(z, "word/numbering.xml", required=False)
    assert doc_raw is not None
    root = _parse_xml(doc_raw, "word/document.xml")
    styles = _load_styles(_parse_xml(styles_raw, "word/styles.xml") if styles_raw else None)
    body = root.find(_w("body"))
    if body is None:
        raise DocxParseError("word/document.xml 缺少 w:body")
    numbering: Optional[_Numbering] = None
    flags: list[str] = []
    if numbering_raw:
        # 编号是装饰：numbering.xml 坏了不能连累正文，照出正文、打标（铁律 8）。DTD 仍整份拒绝
        try:
            numbering = _Numbering(_parse_xml(numbering_raw, "word/numbering.xml"), styles)
        except DocxParseError:
            flags.append("numbering_parse_failed")
    walker = _Walker(styles, numbering, flags)
    walker.container(body)
    return DocxDoc(
        paragraphs=walker.paragraphs,
        blocks=walker.blocks,
        has_revisions=walker.has_revisions,
        has_fields=walker.has_fields,
        flags=walker.flags,
    )


def docx_blocks(content: bytes) -> list[DocxBlock]:
    """块级 API：段落一块、表格一行一块（块号 1 起）。解析失败抛 DocxParseError。"""
    return read_docx(content).blocks
