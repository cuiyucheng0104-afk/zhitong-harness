"""PDF 文字层：逐页抽取、页状态判定、去页眉页码、页级合并。

来源：/home/user/zhitong-cost-ai/engine-service/app/engine/textextract.py（PDF 部分，旧 WS04-P2 / P11）。
改动：

- 表格页版面抽取的开关由环境变量 ``PDF_TABLE_LAYOUT`` 改为函数参数 ``table_layout``（默认关）；
- 扫描页没有旁车时记缺页，原因「扫描页，请用 read_image 看图」，失败码 ``needs_vision``；
  不再有 OCR 服务一档；
- 页级旁车合并在 :mod:`zt.textextract.extract`，不在本模块。
"""
from __future__ import annotations

import io
import logging
import math
import re
from collections import Counter
from typing import Optional

from zt.sidecar.format import PAGE_FLAG_NOTES
from zt.textextract.model import (
    DocText,
    ExtractFailure,
    PageInfo,
    PageStatus,
    PdfPage,
    TextSource,
    exc_detail as _exc_detail,
    failed_doc,
)

log = logging.getLogger("zt.textextract.pdf")

PROBE_PAGES = 2

# 扫描页（文字层不可用）在没有旁车时的缺页原因；agent 据此改用 read_image
SCANNED_PAGE_REASON = "扫描页，文字层无正文，请用 read_image 看图"

# =============================================================================
# PDF：整份文字层与逐页
# =============================================================================


def pdf_text(content: bytes, max_pages: int | None = None) -> str:
    """pypdf 抽 PDF 文字层，不带页锚；解析失败返回空串。

    要逐页信息用 :func:`pdf_page_texts`。

    :param content: PDF 字节。
    :param max_pages: 只抽前 N 页；None 为全部。
    :returns: 文字层文本。
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        pages = reader.pages[:max_pages] if max_pages else reader.pages
        return "\n".join(pdf_page_text(p)[0] for p in pages).strip()
    except Exception as e:  # noqa: BLE001 —— 损坏/加密 PDF 不炸管线
        log.warning("PDF 文本层抽取失败:%s", e)
        return ""


# —— 表格页版面抽取（WS04-P11）——
#
# pypdf 默认抽取把表格里的空格子压掉（生产 R04：工程量、单价两列为空时合价贴在项目名后面；
# R06：行末数值个数比表头列数少），按表头读列就错位 —— 金额读进了别的列（铁律 2/3）。
# 表格页（≥5 行、每行 ≥3 个数值）改用 layout 模式：它按字符列摆放，空格子留成空白。
# 再按数值行的版面位置切出列网格，空格子写成 ` |  | ` 空位。
#
# 启发式，开关 ``table_layout`` 默认关（旧 spec P11：生产 R04/R06 抽样「格子数与表头列数一致
# 的行 ≥90%」达标前默认关闭）。两栏交错（R17）不在本期。
#
# 宁可不分列、不能分错列（铁律 2/3）：layout 模式丢字 / 把数粘连或拆开 → layout_table_mismatch；
# 各行列位漂移、一格挤进两个数 → layout_table_unaligned；这两种都整页退回默认抽取并打标。
# 已知限制：整页都空的列（这一页没有暂估价）不进网格，格子数会比表头少；多行格很多的页，
# 项目特征列可能被切成两列。本机 6 份真实计价 / 预算 PDF 的 159 个表格页实测：23 页出网格
# （其上含金额的行 394/399 在同一张网格里），92 页 mismatch、39 页 unaligned 退回。

_TABLE_MIN_ROWS = 5
_TABLE_MIN_NUMS = 3
# 独立的数：前后不贴字母 / 汉字 / 小数点（「m3」「C30」「第2页」「3.0mm」「1.构件」都不算）
_NUM_TOKEN_RE = re.compile(r"(?<![\w.])[-+]?\d[\d,]*(?:\.\d+)?%?(?![\w.])")
# 网格用细切分：两个以上空格就断（「B04.01.04  混凝土」编码与名称之间常只隔两格）；
# 不进网格的行用 spec 原文的粗切分：3 个以上空格换成 ` | `
_FINE_SEGMENT_RE = re.compile(r"\S+(?: \S+)*")
_COARSE_SEGMENT_RE = re.compile(r"\S+(?: {1,2}\S+)*")
# 某个字符列在 ≥20% 的数值行里有字才算「列里」：一行超长的项目特征伸进右边几列，不能把整页
# 的列缝填平（本机真实预算审核报告：一行「红黏土运输（运距自行考虑）」让 5 列并成 1 列）
_COL_VOTE = 0.2
_COL_GAP = 3            # 稀疏列离已有列至少隔这么多字符才自成一列
# 同一列里的数，左沿或右沿对齐到这么多字符以内。pypdf layout 模式按每段文字估字宽，干净的表
# 右对齐的数也会差 2–3 个字符（本机实测）；两列并成一列时差的是一整列宽（≥6）
_ALIGN_SLACK = 3
# 数值行里能干净切进网格的不到 80%：这页各行的列位漂移（layout 模式按每段文字估字宽），网格
# 不可信，整页退回默认抽取
_GRID_MIN_FIT = 0.8
# layout 模式把逐字定位的中文拆成「分 部 分 项」：两个中文字符之间的单个空格是版面产物
_CJK = r"\u3000-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef"
_CJK_GAP_RE = re.compile(f"(?<=[{_CJK}]) (?=[{_CJK}])")


def _numeric_count(line: str) -> int:
    return len(_NUM_TOKEN_RE.findall(line))


def looks_like_table_text(text: str) -> bool:
    """表格页判定（spec P11）：至少 5 行、每行至少 3 个数值。"""
    rows = 0
    for ln in text.splitlines():
        if _numeric_count(ln) >= _TABLE_MIN_NUMS:
            rows += 1
            if rows >= _TABLE_MIN_ROWS:
                return True
    return False


def _clean_cell(text: str) -> str:
    return _CJK_GAP_RE.sub("", " ".join(text.split()))


def _segments(line: str, pattern: "re.Pattern[str]") -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in pattern.finditer(line)]


def _vote_columns(numeric: list[list[tuple[int, int, str]]]) -> list[tuple[int, int]]:
    width = max(e for segs in numeric for _, e, _ in segs)
    occupied = [0] * width
    for segs in numeric:
        for s, e, _ in segs:
            for x in range(s, e):
                occupied[x] += 1
    need = max(3, math.ceil(_COL_VOTE * len(numeric)))
    cols: list[tuple[int, int]] = []
    x = 0
    while x < width:
        if occupied[x] >= need:
            s = x
            while x < width and occupied[x] >= need:
                x += 1
            cols.append((s, x))
        else:
            x += 1
    # 稀疏列：只有个别行有值（纵向合并的「楼号 26#」、个别行才有的暂估价）投票投不出来。
    # 带数、整段落在列缝里、离已有列都隔着 ≥3 个字符的片段，自成一列。只认带数的片段：
    # 「本页小计」这类居中的文字自成一列，会把后面每一格都错开一列（本机真实计价表实测）；
    # 它落不进网格，那一行照粗切分输出就是了
    sparse: list[list[int]] = []
    for segs in numeric:
        for s, e, t in segs:
            if not _numeric_count(t) or any(min(e, ce) + _COL_GAP > max(s, cs) for cs, ce in cols):
                continue
            for sp in sparse:
                if min(e, sp[1]) + _COL_GAP > max(s, sp[0]):
                    sp[0], sp[1] = min(sp[0], s), max(sp[1], e)
                    break
            else:
                sparse.append([s, e])
    return sorted(cols + [(s, e) for s, e in sparse])


def _place_cells(segs: list[tuple[int, int, str]],
                 cols: list[tuple[int, int]]) -> Optional[list[list[tuple[int, int, str]]]]:
    """片段归它唯一压到的那一列（合计金额比明细宽，右对齐后伸进左侧列缝，照样归本列）；
    压到两列、或一列都没压到 → None（这行不切网格，照粗切分输出 —— 不猜它该归哪列，
    把数放错列比不分列更糟，铁律 2/3）。一格里有两个独立的数 → None（版面把相邻两列挤在
    一起：本机真实预算审核报告里单价与合价只隔一个空格）。"""
    placed: list[list[tuple[int, int, str]]] = [[] for _ in cols]
    for s, e, t in segs:
        hit = [i for i, (cs, ce) in enumerate(cols) if min(e, ce) > max(s, cs)]
        if len(hit) != 1:
            return None
        placed[hit[0]].append((s, e, t))
    if any(sum(_numeric_count(t) for _, _, t in cell) >= 2 for cell in placed):
        return None
    return placed


def _columns_aligned(rows: list[list[list[tuple[int, int, str]]]], ncols: int) -> bool:
    """同一列里「整格就是一个数」的格子，左沿或右沿要对齐（±_ALIGN_SLACK 字符）。对不齐说明
    这一「列」其实是两列的数混在一起，或各行列位漂移 —— 按位置切出来的列号不可信。"""
    for i in range(ncols):
        spans = [(cell[0][0], cell[0][1]) for row in rows for cell in [row[i]]
                 if len(cell) == 1 and _NUM_TOKEN_RE.fullmatch(cell[0][2])]
        if len(spans) < 2:
            continue
        starts, ends = [s for s, _ in spans], [e for _, e in spans]
        if max(starts) - min(starts) > _ALIGN_SLACK and max(ends) - min(ends) > _ALIGN_SLACK:
            return False
    return True


class _GridUnaligned(Exception):
    """数值行切不进同一张网格：各行列位漂移，这页不按版面出。"""


def layout_table_text(layout: str) -> Optional[str]:
    """layout 模式的版面文本 → 带空格位的表格文本；数值行不足 5 行返回 None（不是表格页）；
    网格不可信时抛 `_GridUnaligned`（调用方退回默认抽取并打标）。

    列网格只由数值行（≥3 个数）的版面占位投票决定 —— 标题、表头、多行格的续行不参与，免得
    一行居中的标题把所有列缝填平。网格切给：片段都唯一落在某一列里、有数、且至少占两格的行
    （合计行常只有两个数）。其余行只把 3 个以上的连续空格换成 ` | `（spec 原文）。
    整页都空的列（这一页没有暂估价）在网格里没有位置 —— 表头居中、与数据列位对不齐，拿表头
    补列会插进一个假空列，把后面每一格都错开一列，比少一列更糟。
    """
    rows = [raw.rstrip() for raw in layout.splitlines() if raw.strip()]
    numeric = [_segments(ln, _FINE_SEGMENT_RE) for ln in rows if _numeric_count(ln) >= _TABLE_MIN_NUMS]
    if len(numeric) < _TABLE_MIN_ROWS:
        return None
    cols = _vote_columns(numeric)
    fitted = [c for c in (_place_cells(segs, cols) for segs in numeric) if c is not None]
    if len(fitted) < _GRID_MIN_FIT * len(numeric) or not _columns_aligned(fitted, len(cols)):
        raise _GridUnaligned
    out: list[str] = []
    for line in rows:
        placed = _place_cells(_segments(line, _FINE_SEGMENT_RE), cols) if _numeric_count(line) else None
        cells = [" ".join(_clean_cell(t) for _, _, t in cell) for cell in placed] if placed else None
        if cells is not None and sum(1 for c in cells if c) >= 2:
            out.append(" | ".join(cells).rstrip())
        else:
            out.append(" | ".join(_clean_cell(t) for _, _, t in _segments(line, _COARSE_SEGMENT_RE)))
    return "\n".join(out)


def _nonspace_chars(text: str) -> Counter:
    return Counter(ch for ch in text if not ch.isspace())


# 数字串：连续的数字 / 小数点 / 千分位。两种抽取的数字串多重集必须一致 —— layout 模式在列距
# 窄的 PDF 上会把相邻格子的数粘成一串（本机真实计价表实测「139.12」「6897.57」「2564.28」
# 粘成「139.126897.572564.28」），字符多重集不变、只少了空格，字符闸看不出来
_DIGIT_RUN_RE = re.compile(r"\d(?:[\d.,]*\d)?")


def pdf_page_text(page, *, table_layout: bool = False) -> tuple[str, tuple[str, ...]]:
    """一页的文字层：默认抽取；表格页（``table_layout`` 打开时）改用版面抽取。

    默认抽取的异常照常抛给调用方（各自有逐页容错）。版面抽取抛错 / 丢字或改了数 / 网格不可信
    → 退回默认抽取并打 `layout_table_failed` / `layout_table_mismatch` / `layout_table_unaligned`
    （退化要可见）。

    :param page: pypdf 的页对象。
    :param table_layout: 是否对表格页做版面抽取。
    :returns: ``(文本, 标记)``。
    """
    text = page.extract_text() or ""
    if not table_layout or not looks_like_table_text(text):
        return text, ()
    try:
        # 旋转文字不剥：剥了就丢字，下面的完整性闸会整页退回
        layout = page.extract_text(extraction_mode="layout", layout_mode_strip_rotated=False) or ""
    except Exception as e:  # noqa: BLE001 —— 版面模式失败不连累本页
        log.warning("PDF 表格页版面抽取失败，退回默认抽取：%s", _exc_detail(e))
        return text, ("layout_table_failed",)
    # 完整性闸（铁律 2/3：宁可列错位，不能把数读错）：版面模式只许挪位置 ——
    # ① 非空白字符多重集一致（本机 159 个真实表格页里 3 页 layout 模式整块丢字）；
    # ② 数字串多重集一致（不许把相邻格子的数粘成一串，也不许把一个数拆开）
    if (_nonspace_chars(layout) != _nonspace_chars(text)
            or Counter(_DIGIT_RUN_RE.findall(layout)) != Counter(_DIGIT_RUN_RE.findall(text))):
        return text, ("layout_table_mismatch",)
    try:
        table = layout_table_text(layout)
    except _GridUnaligned:
        return text, ("layout_table_unaligned",)
    if table is None:
        return text, ()
    return table, ("layout_table",)


def pdf_text_layer_chars(content: bytes) -> int:
    """探针(修正#2):前 2 页文本层字符数。"""
    return len(pdf_text(content, max_pages=PROBE_PAGES))


def _open_pdf(content: bytes):
    """返回 (reader, None) 或 (None, ExtractFailure)。带用户口令 → encrypted。"""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
    except Exception as e:  # noqa: BLE001
        return None, ExtractFailure("parse_failed", f"PDF 无法解析：{_exc_detail(e)}")
    try:
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception as e:  # noqa: BLE001 —— 缺解密依赖等
                return None, ExtractFailure("encrypted", f"PDF 已加密，无法解密：{_exc_detail(e)}")
            if not ok:
                return None, ExtractFailure("encrypted", "PDF 带打开口令，无法读取")
        len(reader.pages)
    except Exception as e:  # noqa: BLE001
        return None, ExtractFailure("parse_failed", f"PDF 页树无法解析：{_exc_detail(e)}")
    return reader, None


_INLINE_IMAGE_RE = re.compile(rb"(?:^|\s)BI\s")


def _resources_have_image(res, depth: int = 0) -> bool:
    if res is None or depth > 3:
        return False
    res = res.get_object()
    xobjs = res.get("/XObject") if hasattr(res, "get") else None
    if xobjs is None:
        return False
    xobjs = xobjs.get_object()
    for name in list(xobjs.keys()):
        x = xobjs[name].get_object()
        sub = x.get("/Subtype")
        if sub == "/Image":
            return True
        if sub == "/Form" and _resources_have_image(x.get("/Resources"), depth + 1):
            return True
    return False


def _page_raw(page) -> tuple[bool, int, bytes]:
    try:
        contents = page.get_contents()
        data = contents.get_data() if contents is not None else b""
    except Exception:  # noqa: BLE001
        data = b""
    try:
        has_image = _resources_have_image(page.get("/Resources"))
    except Exception:  # noqa: BLE001
        has_image = False
    if not has_image and data and _INLINE_IMAGE_RE.search(data):
        has_image = True
    return has_image, len(data), data


def pdf_page_texts(content: bytes, *, max_pages: Optional[int] = None,
                   table_layout: bool = False) -> Optional[list[PdfPage]]:
    """逐页抽文字层。

    :param content: PDF 字节。
    :param max_pages: 只抽前 N 页；None 为全部。
    :param table_layout: 是否对表格页做版面抽取。
    :returns: 逐页原料；打不开或带用户口令时为 None。
    """
    reader, _failure = _open_pdf(content)
    if reader is None:
        return None
    return _pages_from_reader(reader, max_pages, table_layout=table_layout)


def _pages_from_reader(reader, max_pages: Optional[int], *, table_layout: bool = False) -> list[PdfPage]:
    pages = reader.pages
    n = len(pages) if not max_pages else min(len(pages), max_pages)
    out: list[PdfPage] = []
    for i in range(n):
        page = pages[i]
        has_image, clen, _ = _page_raw(page)
        err = None
        flags: tuple[str, ...] = ()
        try:
            text, flags = pdf_page_text(page, table_layout=table_layout)
        except Exception as e:  # noqa: BLE001 —— 单页抽不出不连累整份
            text, err = "", _exc_detail(e)
        out.append(PdfPage(no=i + 1, text=text, has_image=has_image, content_len=clen, error=err,
                           flags=flags))
    return out


_UNI_ESCAPE_RE = re.compile(r"/uni([0-9A-Fa-f]{4})")
# 扫描 App 水印行（常量表）：它们让扫描页「有字」，挡住旁车与看图
SCAN_WATERMARKS = ("扫描全能王 创建", "CamScanner", "由扫描全能王扫描创建")
_WATERMARK_KEYS = tuple("".join(w.split()).lower() for w in SCAN_WATERMARKS)
_WATERMARK_SLACK = 16  # 「Scanned with CamScanner」这类带前后缀的水印行
_USABLE_MIN_CHARS = 20
_GARBLED_RATIO = 0.3
_BLANK_STREAM_MAX = 64
# 没图像、内容流小、有少量字（封面 / 签章页）的页按文字页算，不当扫描页：它的字就在文字层里。
# CAD 转曲页没图像但内容流很大，照旧判 scanned。
_SHORT_TEXT_STREAM_MAX = 4096

_PUA_LO, _PUA_HI = 0xE000, 0xF8FF
_REPLACEMENT = 0xFFFD


def _is_effective(ch: str) -> bool:
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF
        or 0x3400 <= o <= 0x4DBF
        or ("0" <= ch <= "9")
        or ("a" <= ch.lower() <= "z")
        or 0xFF10 <= o <= 0xFF19
        or 0xFF21 <= o <= 0xFF3A
        or 0xFF41 <= o <= 0xFF5A
    )


def _is_garbage(ch: str) -> bool:
    o = ord(ch)
    return _PUA_LO <= o <= _PUA_HI or o == _REPLACEMENT


def decode_uni_escapes(text: str) -> str:
    """损坏 ToUnicode 的文字层抽出来是 /uniXXXX 转义串（真实语料），可逆，解回原字符。"""
    if "/uni" not in text:
        return text
    return _UNI_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)


def _strip_watermarks(text: str) -> tuple[str, bool]:
    kept: list[str] = []
    hit = False
    for line in text.splitlines():
        key = "".join(line.split()).lower()
        if key and len(key) <= max(len(w) for w in _WATERMARK_KEYS) + _WATERMARK_SLACK and any(
            w in key for w in _WATERMARK_KEYS
        ):
            hit = True
            continue
        kept.append(line)
    return "\n".join(kept), hit


def page_status(text: str, has_image: bool, content_len: int) -> PageStatus:
    """判一页文字层能不能用（WS04-P2）。

    - usable：有效字符（汉字、字母、数字）≥ 20，且私用区字符 + 替换符占比 < 30%；
    - blank：一个字都没有、没有图像 XObject、内容流 < 64 字节 —— 真空白页，不当扫描页；
    - scanned：其余一律。水印页标 watermark_only，乱码页标 garbled。
    """
    cleaned, had_watermark = _strip_watermarks(decode_uni_escapes(text or ""))
    visible = [c for c in cleaned if not c.isspace()]
    effective = sum(1 for c in visible if _is_effective(c))
    garbage = sum(1 for c in visible if _is_garbage(c))
    ratio = garbage / len(visible) if visible else 0.0
    if effective >= _USABLE_MIN_CHARS and ratio < _GARBLED_RATIO:
        return PageStatus("usable", (), cleaned)
    if not visible:
        if had_watermark:
            return PageStatus("scanned", ("watermark_only",), "")
        if not has_image and content_len < _BLANK_STREAM_MAX:
            return PageStatus("blank", (), "")
        return PageStatus("scanned", (), "")
    if ratio >= _GARBLED_RATIO or effective == 0:
        return PageStatus("scanned", ("garbled",), cleaned)
    if not has_image and content_len < _SHORT_TEXT_STREAM_MAX:
        return PageStatus("usable", ("short_text",), cleaned)
    return PageStatus("scanned", (), cleaned)


_PAGE_NO_RE = re.compile(
    r"^[\s\-—–·\[\(（]*(?:第\s*)?\d{1,4}\s*(?:页)?\s*(?:[/／]\s*\d{1,4}|共\s*\d{1,4}\s*页|of\s*\d{1,4})?"
    r"\s*(?:页)?[\s\-—–·\]\)）]*$",
    re.IGNORECASE,
)
_PAGE_WORD_RE = re.compile(r"^\s*page\s*\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\s*$", re.IGNORECASE)
_HEADER_EDGE_LINES = 2
_HEADER_MIN_PAGES = 4
_HEADER_MIN_SHARE = 0.5
_HEADER_MAX_CHARS = 40
# 页号偏移至少要在 3 页上对得上：4 页文档按 50% 只要 2 页，两页恰好差同一个常数太容易撞上
_PAGE_TRACK_MIN_PAGES = 3
# 独立整数（不是小数、千分位的一截）：只有这种数字才可能是页号
_INT_TOKEN_RE = re.compile(r"(?<![\d.,，])\d+(?![.,，]?\d)")
# 带金额 / 小数 / 千分位的行只做逐字去重：数字一归一，逐页不同的「本页小计」就撞成同一行
_AMOUNT_HINT_RE = re.compile(r"\d[.,，]\d|[￥¥%％]|小计|合计|总计|累计|金额|单价|合价|\d\s*万?元")


def _edge_indexes(lines: list[str]) -> list[int]:
    nonempty = [i for i, ln in enumerate(lines) if ln.strip()]
    return sorted(set(nonempty[:_HEADER_EDGE_LINES] + nonempty[-_HEADER_EDGE_LINES:]))


def is_page_number_line(line: str) -> bool:
    """只看形状：「3」「- 3 -」「第 3 页 共 6 页」「3/6」「Page 3 of 6」。是不是真页码还要看
    数字跟页序对不对得上（strip_running_headers 里判）。"""
    s = line.strip()
    return bool(s) and (bool(_PAGE_NO_RE.match(s)) or bool(_PAGE_WORD_RE.match(s)))


def _page_offsets(split: list[list[str]], page_nos: list[int], need: int) -> set[int]:
    """页边行里「数字 − 页号」在 ≥need 页上相同的那些偏移：这个数字随页号走，是页码。
    封面不编号时印刷页码 = 物理页号 − 2，偏移就是 −2。"""
    counter: Counter[int] = Counter()
    for lines, no in zip(split, page_nos):
        offs = {int(m.group()) - no for i in _edge_indexes(lines)
                for m in _INT_TOKEN_RE.finditer(lines[i])}
        counter.update(offs)
    return {k for k, n in counter.items() if n >= need}


def _edge_keys(line: str, no: int, offsets: set[int]) -> tuple[str, ...]:
    """一行页边文字的去重键：逐字键；不带金额迹象时再加一个「页码数字换成 #」的键。
    只归一随页号走的数字 —— 金额、数量、序号逐页不同，归一了就会被当成页眉删掉。"""
    raw = " ".join(line.split())
    if not raw or _AMOUNT_HINT_RE.search(raw):
        return (raw,) if raw else ()
    norm = _INT_TOKEN_RE.sub(lambda m: "#" if int(m.group()) - no in offsets else m.group(), raw)
    return (raw,) if norm == raw else (raw, norm)


def _tracks_page(line: str, no: int, offsets: set[int]) -> bool:
    m = _INT_TOKEN_RE.search(line)
    return bool(m) and is_page_number_line(line) and int(m.group()) - no in offsets


def strip_running_headers(
    pages: list[str], page_nos: Optional[list[int]] = None,
) -> tuple[list[str], int]:
    """去页眉页脚（WS04-P2）：只在 ≥4 页的文档上做，只看每页首尾各 2 行。返回 (新页文本, 删除行数)。

    - 纯页码行：形状像页码，**且数字 − 页号**在 ≥3 页、≥50% 的页上是同一个常数，才删。
      页边上单独成行的工程量（1200、36）对不上页序，不删。
    - 页眉页脚：同一行在 ≥50% 的页上出现、且不超过 40 字，删掉（首次出现的那页保留一份：
      续页表头这类行删光了，LLM 就不知道列是什么）。「同一行」按逐字比；只有随页号走的数字
      归一成 #。带小数点、千分位、金额词的行只逐字比 —— 逐页不同的「本页小计」必须全部保留。
    - 非空行 ≤4 行的短页，每一行都落在首尾 2 行里，不做页眉去重（只删页码）；
      任何一页都不会被删空 —— 删空的页仍记 text_layer，complete 会假报 True。

    `page_nos`：各页的真实页号（混合 PDF 里文字层页不连续），缺省 1..n。
    """
    if len(pages) < _HEADER_MIN_PAGES:
        return list(pages), 0
    nos = list(page_nos) if page_nos is not None else list(range(1, len(pages) + 1))
    if len(nos) != len(pages):
        raise ValueError("page_nos 与 pages 长度不一致")
    split = [p.splitlines() for p in pages]
    need = max(2, math.ceil(len(pages) * _HEADER_MIN_SHARE))
    offsets = _page_offsets(split, nos, max(_PAGE_TRACK_MIN_PAGES, need))
    counter: Counter[str] = Counter()
    for lines, no in zip(split, nos):
        counter.update({k for i in _edge_indexes(lines) for k in _edge_keys(lines[i], no, offsets)})
    frequent = {k for k, n in counter.items() if n >= need and 0 < len(k) <= _HEADER_MAX_CHARS}
    seen_first: set[str] = set()
    removed = 0
    out: list[str] = []
    for lines, no in zip(split, nos):
        nonempty = [i for i, ln in enumerate(lines) if ln.strip()]
        short = len(nonempty) <= 2 * _HEADER_EDGE_LINES
        drop: set[int] = set()
        for i in _edge_indexes(lines):
            if _tracks_page(lines[i], no, offsets):
                drop.add(i)
                continue
            hit = [k for k in _edge_keys(lines[i], no, offsets) if k in frequent]
            if not hit:
                continue
            if any(k in seen_first for k in hit) and not short:
                drop.add(i)
            seen_first.update(hit)
        if len(drop) >= len(nonempty):
            drop = set()
        removed += len(drop)
        out.append("\n".join(ln for i, ln in enumerate(lines) if i not in drop))
    return out, removed


# —— 页锚（C6：送给 LLM 的页锚统一写成 `[pN]`）——


def page_anchor(first: int, last: Optional[int] = None, note: Optional[str] = None) -> str:
    span = f"p{first}" if last is None or last == first else f"p{first}–p{last}"
    return f"[{span}]" + (f" ｜{note}" if note else "")


def _source_of(pages: list[PageInfo]) -> TextSource:
    kinds = {p.source for p in pages}
    if "ocr_sidecar" in kinds:
        return "ocr_sidecar"
    if "text_layer" in kinds:
        return "text_layer"
    return "none"


def render_pages(pages: list[PageInfo], *, anchors: bool) -> str:
    """多页：每页 `[pN]` 锚点，旁车页带 `｜OCR`，缺页连续合并成一行；空白页不出现。"""
    out: list[str] = []
    run: list[PageInfo] = []

    def flush() -> None:
        if run:
            reason = run[0].missing_reason or "原因未知"
            out.append(page_anchor(run[0].no, run[-1].no, f"未取得正文（{reason}）"))
            run.clear()

    for p in pages:
        if p.source == "missing":
            if run and run[-1].missing_reason != p.missing_reason:
                flush()
            run.append(p)
            continue
        flush()
        if p.source == "blank" or not p.text.strip():
            continue
        if anchors:
            notes = ["OCR"] if p.source == "ocr_sidecar" else []
            notes += [PAGE_FLAG_NOTES[f] for f in p.flags if f in PAGE_FLAG_NOTES]
            out.append(page_anchor(p.no, note=" ｜".join(notes) or None))
        out.append(p.text.strip("\n"))
    flush()
    return "\n".join(out).strip()


def merge_pdf_pages(
    pages: list[PageInfo],
    *,
    pages_total: Optional[int] = None,
    truncated: bool = False,
    quality_flags: Optional[list[str]] = None,
    quality_suspect: bool = False,
    empty_failure: Optional[ExtractFailure] = None,
    page_mapped: bool = True,
) -> DocText:
    """逐页结果 → DocText（纯函数）。一页正文都没有时 text 为空并带 failure（缺页锚点
    不算正文：否则全失败的扫描件会以一串「未取得正文」锚点冒充非空正文）。"""
    total = pages_total if pages_total is not None else (max((p.no for p in pages), default=0) or None)
    has_body = any(p.text.strip() for p in pages if p.source not in ("blank", "missing"))
    flags = list(quality_flags or [])
    if not has_body:
        failure = empty_failure
        if failure is None:
            if any(p.source == "missing" for p in pages):
                reasons = sorted({p.missing_reason or "原因未知" for p in pages if p.source == "missing"})
                failure = ExtractFailure("needs_vision", "扫描页未取得正文：" + "；".join(reasons))
            else:
                failure = ExtractFailure("no_text", "PDF 解析成功但没有任何文字（空白页）")
        return DocText(
            text="", text_source="none", pages=pages, pages_total=total, truncated=truncated,
            quality_flags=flags, quality_suspect=quality_suspect, failure=failure,
            page_mapped=page_mapped,
        )
    multi = (total or len(pages)) > 1
    text = render_pages(pages, anchors=multi)
    return DocText(
        text=text, text_source=_source_of(pages), pages=pages, pages_total=total,
        truncated=truncated, quality_flags=flags, quality_suspect=quality_suspect,
        page_mapped=page_mapped,
        ocr_derived=any(p.source == "ocr_sidecar" for p in pages),
    )


def classify_pdf_pages(raw: list[PdfPage]) -> tuple[list[PageInfo], list[str]]:
    """文字层逐页判状态 + 去页眉页码。scanned 页先记为 missing（原因见 ``SCANNED_PAGE_REASON``），由编排层查旁车补。"""
    infos: list[PageInfo] = []
    flags: list[str] = []
    layout_pages: Counter = Counter()
    for pg in raw:
        st = page_status(pg.text, pg.has_image, pg.content_len)
        if pg.error:
            flags.append("page_extract_error")
        if st.status == "usable":
            infos.append(PageInfo(pg.no, "text_layer", st.text, list(st.flags) + list(pg.flags)))
            layout_pages.update(pg.flags)
        elif st.status == "blank":
            infos.append(PageInfo(pg.no, "blank", "", list(st.flags)))
        else:
            infos.append(PageInfo(pg.no, "missing", "", list(st.flags), missing_reason=SCANNED_PAGE_REASON))
        for f in st.flags:
            if f in ("watermark_only", "garbled") and f not in flags:
                flags.append(f)
    # WS04-P11：按版面抽取 / 退回默认抽取的页数，文档级可查
    for f in ("layout_table", "layout_table_mismatch", "layout_table_unaligned", "layout_table_failed"):
        if layout_pages[f]:
            flags.append(f"{f}_pages:{layout_pages[f]}")
    text_pages = [p for p in infos if p.source == "text_layer"]
    if len(infos) >= _HEADER_MIN_PAGES and text_pages:
        new_texts, removed = strip_running_headers(
            [p.text for p in text_pages], [p.no for p in text_pages])
        for p, t in zip(text_pages, new_texts):
            p.text = t
        if removed:
            flags.append(f"running_headers_removed:{removed}")
    return infos, flags


def _pdf_text_layer_doc(content: bytes, *, max_pages: Optional[int] = None,
                        table_layout: bool = False) -> DocText:
    reader, failure = _open_pdf(content)
    if reader is None:
        assert failure is not None
        return failed_doc(failure.code, failure.detail)
    raw = _pages_from_reader(reader, max_pages, table_layout=table_layout)
    infos, flags = classify_pdf_pages(raw)
    total = len(reader.pages)
    return merge_pdf_pages(
        infos, pages_total=total, quality_flags=flags,
        truncated=bool(max_pages and total > max_pages),
    )
