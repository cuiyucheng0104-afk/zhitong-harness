"""WS04 测试夹具：合成旁车（行格式逐字照抄生产落盘模板，不含客户数据）+ 现造 PDF 页型。

旁车模板来源：生产 `.ocr.txt` 普查（2026-09-29）里出现的每一种卷头行 / 逐页判定行 /
页级警告行 / 占位句，数值与路径全部替换成虚构值。
"""
from __future__ import annotations

import io

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

HEADER = (
    "# {name}\n"
    "> 原始路径: 投控项目/示例项目/{name}\n"
    "> 类型: pdf(OCR) ｜ 引擎: paddleocr-vl-1.6 ｜ 页数: {pages} ｜ OCR页: {pages} ｜ "
    "时间: 2026-08-12T04:31:22+08:00\n"
    "> ⚠ 本文件由扫描件 OCR 得到，可能有识别错误；**涉及金额/编号时请回原件核对**\n"
)
SUSPECT = (
    "> ⚠ 质量存疑: {pages} 个 OCR 页里有 {bad} 页（{ratio}%）没识别出可读文本或疑似复读退化，"
    "超过 30% 阈值 —— 本文件的内容**不可全信**，已记入语料根的 _OCR质量存疑.jsonl\n"
)
ESCAPE = "> 正文转义: 行首为 `#`、`@@`、`>` 的正文行落盘时行首多加了一个空格，还原时去掉一个即可\n"

FAILED_LINE = "（本页 OCR 连续失败未取得任何结果，不是空白页；请回原件核对或重跑 OCR）"
EMPTY_LINE = "（本页 OCR 未能识别出可读文本：可能是空白页，也可能是识别失败，请回原件核对）"
GARBLED_LINE = "（本页 OCR 未能识别出可读文本：识别结果为乱码，请回原件核对）"
SKIPPED_LINE = "（本页原 PDF 自带文字层，未做 OCR；请直接读原件该页）"
REPEAT_WARN = (
    "> ⚠ 疑似 OCR 复读退化：20 字滑窗去重率仅 0.8%（同一段文字反复出现）。"
    "开头一段多为真内容，后段基本是复读 —— **本页请以原件为准**"
)
THIN_WARN = (
    "> ⚠ 本页只识别出 9 个字符（低于 25 字）。正文照原样落在下面 —— 可能这页本来就只有"
    "这么一句，也可能是识别漏了，**请回原件核对**"
)
AMOUNT_WARN = (
    "> ⚠ 金额大写小写不符：本页大写金额与小写金额对不上，必有一处错，请回原件核对"
    "（本行判不出错的是哪一个）。共 1 处，例：「壹佰万元整」＝1000000 ↔ 同页小写 1000100"
    "（数字串第 6 位不同）"
)
REPEATED_SENTENCE = "请识别图像中的文字，准确识别出相应的文字内容。"


def meta(chars: int, verdict: str, bad: str = "0.0") -> str:
    return f"> 字符 {chars} ｜ 异常字符 {bad}% ｜ 判定 {verdict}"


def header(name: str, pages: int, *, suspect_bad: int | None = None) -> str:
    out = HEADER.format(name=name, pages=pages)
    if suspect_bad is not None:
        out += SUSPECT.format(pages=pages, bad=suspect_bad,
                              ratio=f"{suspect_bad / pages * 100:.1f}")
    return out + ESCAPE


def page(no: int, verdict: str, *lines: str, chars: int = 100, bad: str = "0.0") -> str:
    return "\n".join([f"## p{no}", meta(chars, verdict, bad), *lines]) + "\n"


# F1：两页全 failed，卷头带质量存疑
F1 = header("外架拆除完成时间确认表.pdf", 2, suspect_bad=2) + "\n" + "\n".join([
    page(1, "failed", FAILED_LINE, chars=0),
    page(2, "failed", FAILED_LINE, chars=0),
])

OTSL_TABLE = (
    "审定汇总<lcel><lcel><nl><fcel>序号<fcel>单位工程<fcel>审定金额（元）<nl>"
    "<fcel>1<fcel>土建<br>工程<fcel>18601<nl><fcel>合计<lcel><fcel>18601<sup>注</sup><nl>"
)

# F2：p1 ok（转义行 + OTSL）、p2 failed、p3 repetitive（一句话重复 54 次）、p4 skipped、p5 ok（金额警告）
F2 = header("结算审核报告.pdf", 5, suspect_bad=2) + "\n" + "\n".join([
    page(1, "ok", "工程造价审定单", " # 3楼", " > 引用行", " @@ 标记行", OTSL_TABLE, "审核人：示例"),
    page(2, "failed", FAILED_LINE, chars=0),
    page(3, "repetitive", REPEAT_WARN, "工程款支付申请表",
         REPEATED_SENTENCE * 30, *([REPEATED_SENTENCE] * 24), chars=1500),
    page(4, "skipped", SKIPPED_LINE, chars=0),
    page(5, "ok", AMOUNT_WARN, "审定金额大写 壹佰万元整", "审定金额小写 1000100"),
])

# F3：只有 empty 与 garbled 页
F3 = header("空白扫描.pdf", 2, suspect_bad=2) + "\n" + "\n".join([
    page(1, "empty", EMPTY_LINE, chars=0),
    page(2, "garbled", GARBLED_LINE, chars=12, bad="80.0"),
])

# F4：只有卷头，没有页
F4 = header("只有卷头.pdf", 3)

# F5：旧式纯文本
F5 = "本合同由甲方与乙方签订，合同金额 12,345,678.00 元。\n第二段正文。\n"

# 负控：ok 页上 30 行同模板不同数字的钢筋表
REBAR_ROWS = [f"钢筋 HRB400 Φ{12 + i % 7} t {1 + i * 0.137:.3f}" for i in range(30)]
REBAR = header("钢筋表.pdf", 1) + "\n" + page(1, "ok", "钢筋用量表", *REBAR_ROWS, chars=900)


def paged_sidecar(pages: list[tuple[str, list[str]]], name: str = "扫描件.pdf") -> str:
    """按页判定造旁车：[(verdict, 正文行)]。failed 页自动带占位句。"""
    parts = [header(name, len(pages)), ""]
    for i, (verdict, lines) in enumerate(pages, start=1):
        body = list(lines) or ([FAILED_LINE] if verdict == "failed" else [])
        parts.append(page(i, verdict, *body))
    return "\n".join(parts)


# =============================================================================
# PDF 页型（pypdf 现造）
# =============================================================================

def _font(w: PdfWriter, to_unicode: bytes | None = None):
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    if to_unicode is not None:
        cmap = DecodedStreamObject()
        cmap.set_data(to_unicode)
        font[NameObject("/ToUnicode")] = w._add_object(cmap)
    return w._add_object(font)


def _set_content(w: PdfWriter, pg, data: bytes, resources: DictionaryObject | None = None):
    stream = DecodedStreamObject()
    stream.set_data(data)
    pg[NameObject("/Contents")] = w._add_object(stream)
    pg[NameObject("/Resources")] = resources or DictionaryObject()


def add_text_page(w: PdfWriter, text: str, *, extra_lines: list[str] = ()) -> None:
    pg = w.add_blank_page(595, 842)
    ops = [b"BT /F1 12 Tf 72 780 Td 14 TL"]
    for line in [text, *extra_lines]:
        esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({esc}) Tj T*".encode("latin-1"))
    ops.append(b"ET")
    res = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): _font(w)})})
    _set_content(w, pg, b"\n".join(ops), res)


def add_blank(w: PdfWriter) -> None:
    w.add_blank_page(595, 842)


def add_image_page(w: PdfWriter) -> None:
    pg = w.add_blank_page(595, 842)
    img = DecodedStreamObject()
    img.set_data(b"\xff\xff\xff")
    img.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(1),
        NameObject("/Height"): NumberObject(1),
        NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
        NameObject("/BitsPerComponent"): NumberObject(8),
    })
    res = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): w._add_object(img)})})
    _set_content(w, pg, b"q 500 0 0 700 40 60 cm /Im0 Do Q", res)


def add_vector_page(w: PdfWriter) -> None:
    """只有矢量路径、内容流远超 64 字节（CAD 转曲页的形状）。"""
    pg = w.add_blank_page(595, 842)
    ops = b"".join(f"{10 + i} 10 m {20 + i} 800 l S\n".encode() for i in range(60))
    _set_content(w, pg, ops)


def add_watermark_page(w: PdfWriter) -> None:
    """只有扫描 App 水印文字（CamScanner），没有正文。"""
    pg = w.add_blank_page(595, 842)
    res = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): _font(w)})})
    _set_content(w, pg, b"BT /F1 9 Tf 450 20 Td (CamScanner) Tj ET", res)


_PUA_CMAP = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CMapName /Adobe-Identity-UCS def
/CMapType 2 def
1 begincodespacerange
<00> <FF>
endcodespacerange
1 beginbfrange
<20> <7E> <E000>
endbfrange
endcmap
CMapName currentdict /CMap defineresource pop
end
end"""


def add_garbled_page(w: PdfWriter) -> None:
    """文字层全是私用区字符（ToUnicode 把 ASCII 码映射到 U+E000 起）—— 乱码页。"""
    pg = w.add_blank_page(595, 842)
    res = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/F1"): _font(w, to_unicode=_PUA_CMAP)})})
    _set_content(w, pg, b"BT /F1 12 Tf 72 700 Td (ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef) Tj ET", res)


def to_bytes(w: PdfWriter) -> bytes:
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def text_line(no: int) -> str:
    return f"PAGE-TEXT 28.78 control resource volume page {no}"


LEDGER_HEADER = "Zhejiang Cost Consulting Report 2025"
LEDGER_SUBTOTALS = ["1,204,356.78", "86,210.00", "455,102.35", "3,300,000.00", "12,000.50", "98,765.43"]


def ledger_lines(no: int) -> list[str]:
    """计价表续页版式：页眉 + 3 行清单 + 本页小计 + 页码。

    清单行和小计行都 ≤40 字、落在首尾 2 行里、逐页数值不同 —— 数字一归一就撞成同一行，
    能走进页眉去重的删除分支（text_line 44 字，超过 40 字门槛，够不到那条分支）。
    """
    return [
        LEDGER_HEADER,
        f"Item {3 * no - 2} earthwork m3 {100 + no}.5",
        f"Item {3 * no - 1} backfill m3 {200 + no}.25",
        f"Item {3 * no} disposal m3 {30 + no}.75",
        f"Subtotal {LEDGER_SUBTOTALS[(no - 1) % len(LEDGER_SUBTOTALS)]}",
        f"- {no} -",
    ]


def build_pdf(kinds: list[str]) -> bytes:
    """kinds 取值：text / ledger / blank / image / vector / watermark / garbled。"""
    w = PdfWriter()
    for i, kind in enumerate(kinds, start=1):
        if kind == "text":
            add_text_page(w, text_line(i))
        elif kind == "ledger":
            first, *rest = ledger_lines(i)
            add_text_page(w, first, extra_lines=rest)
        elif kind == "blank":
            add_blank(w)
        elif kind == "image":
            add_image_page(w)
        elif kind == "vector":
            add_vector_page(w)
        elif kind == "watermark":
            add_watermark_page(w)
        elif kind == "garbled":
            add_garbled_page(w)
        else:  # pragma: no cover
            raise ValueError(kind)
    return to_bytes(w)
