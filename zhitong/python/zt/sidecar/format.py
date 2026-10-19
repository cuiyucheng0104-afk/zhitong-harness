"""`.ocr.txt` 旁车按格式解析（旧 WS04-P1；整改 spec 统一约定 C6：旁车只通过本模块解析）。

来源：/home/user/zhitong-cost-ai/engine-service/app/engine/sidecar_format.py（纯函数，逻辑未改）。
改动：只改头注与包名；写侧版式（sidecar_layout / OCR 补跑）不迁入，本仓不调用 OCR。

纯函数：不做 IO、不读配置。入口 `parse_ocr_sidecar(text) -> SidecarDoc`。

生产 NAS 上 2882 份旁车全是**分页格式**（2026-09-29 只读普查）：

    # 审核报告.pdf                                   ← 卷头：文件名
    > 原始路径: 投控项目/…/审核报告.pdf               ← 卷头：客户目录结构，不是正文
    > 类型: pdf(OCR) ｜ 引擎: paddleocr-vl-1.6 ｜ 页数: 7 ｜ OCR页: 7 ｜ 时间: …
    > ⚠ 本文件由扫描件 OCR 得到，…
    > ⚠ 质量存疑: 29 个 OCR 页里有 29 页（100.0%）…   ← 只在超过 30% 阈值时出现
    > 正文转义: 行首为 `#`、`@@`、`>` 的正文行落盘时行首多加了一个空格，…

    ## p1
    > 字符 9 ｜ 异常字符 0.0% ｜ 判定 thin              ← 逐页判定
    > ⚠ 本页只识别出 9 个字符（低于 25 字）。…          ← 页级警告（白名单）
    正文……                                            ← OTSL 表格标记、复读内容都在这里

旧实现只判 `text.strip()`：754 份**一页可用的都没有**的旁车（整份都是「本页 OCR 连续失败」
占位句）被当成正文命中，OCR 服务一次都没被调用；可用旁车的卷头、判定行、`<fcel>` 标记、
复读内容原样送进 LLM。本模块把这些按**白名单**剥掉，白名单以外的 `> ` 行一律当正文保留
（不猜：误删真实正文比留下一行噪声更糟，铁律 8）。

不是分页格式的旁车记为 `fmt="legacy"`：整段当一块，strip 后非空即可用，与旧行为逐字一致。

写侧（WS04-P8 补跑工具，issue #726）的版式在 `sidecar_layout.py`，但**格式词表只在本模块定义一次**：
锚点 / 判定行正则、卷头前缀、判定行写法（`format_page_meta`）、占位句全文（`PLACEHOLDER_BY_VERDICT`）
都从这里引入 —— 读写两侧不可能各改各的（C6；`test_textextract_shared_api` 的棘轮守标记串只出现在
本文件，`test_ocr_backfill` 的往返用例守「写出来的读得回」）。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal, Optional

__all__ = [
    "PAGE_FLAG_NOTES",
    "PLACEHOLDER_BY_VERDICT",
    "SidecarDoc",
    "SidecarPage",
    "USABLE_VERDICTS",
    "format_page_meta",
    "looks_like_paged_sidecar",
    "parse_ocr_sidecar",
]

USABLE_VERDICTS = frozenset({"ok", "thin", "repetitive"})

_ANCHOR_RE = re.compile(r"^## p(\d+)\s*$")
_META_RE = re.compile(r"^>\s*字符\s*(\d+)\s*｜\s*异常字符\s*([\d.]+)%\s*｜\s*判定\s*([a-z_]+)\s*$")
_ANCHOR_ANY = re.compile(r"(?m)^## p\d+\s*$")
_META_ANY = re.compile(r"(?m)^>\s*字符\s*\d+\s*｜\s*异常字符\s*[\d.]+%\s*｜\s*判定\s*[a-z_]+\s*$")


def format_page_meta(chars: int, bad_ratio: float, verdict: str) -> str:
    """逐页判定行的写法（`_META_RE` 的逆；写侧 = WS04-P8 补跑工具）。bad_ratio 是 0–1 的占比。"""
    return f"> 字符 {chars} ｜ 异常字符 {bad_ratio * 100:.1f}% ｜ 判定 {verdict}"


# —— 卷头白名单（第一个 `## pN` 之前）——
_H_PATH = "> 原始路径:"
_H_TYPE = "> 类型:"
_H_OCR_NOTICE = "> ⚠ 本文件由扫描件 OCR 得到"
_H_SUSPECT = "> ⚠ 质量存疑:"
_H_ESCAPE = "> 正文转义:"
_HEADER_SIGNATURES = (_H_PATH, _H_TYPE, _H_OCR_NOTICE, _H_ESCAPE)

# —— 页级警告白名单 ——
_PAGE_WARNINGS = (
    ("> ⚠ 疑似 OCR 复读退化", "repetitive"),
    ("> ⚠ 本页只识别出", "thin"),
    ("> ⚠ 金额大写小写不符", "amount_case_mismatch"),
)

# —— 占位句前缀白名单（管线写的，不是 OCR 识别出的正文）——
_PLACEHOLDERS = (
    ("（本页 OCR 连续失败未取得任何结果", "failed"),
    ("（本页 OCR 未能识别出可读文本", "unreadable"),
    ("（本页原 PDF 自带文字层，未做 OCR", "skipped"),
)
# 写侧按判定落盘的占位句全文：每句都以上面某个前缀开头，读回来才认得出
PLACEHOLDER_BY_VERDICT = {
    "failed": "（本页 OCR 连续失败未取得任何结果，请查看原件）",
    "empty": "（本页 OCR 未能识别出可读文本，可能是空白页或纯图片页）",
    "garbled": "（本页 OCR 未能识别出可读文本：异常字符占比过高，已丢弃乱码）",
    "skipped": "（本页原 PDF 自带文字层，未做 OCR）",
}

# 正文转义：落盘时给行首 `#` / `>` / `@@` 的正文行多垫了一个空格
_ESCAPED_PREFIXES = (" #", " >", " @@")

# —— OTSL（paddleocr-vl 的表格输出）——
_OTSL_CELL = re.compile(r"<(fcel|ecel|lcel|ucel|xcel)>")
_OTSL_ANY = re.compile(r"<(?:fcel|ecel|lcel|ucel|xcel|nl)>")
_INLINE_TAGS = re.compile(r"</?(?:sup|sub|underline)>")

# —— 复读 ——
_INLINE_REPEAT = re.compile(r"(.{6,200}?)\1{3,}")  # ≥6 字的片段连续出现 ≥4 次
_REPEAT_LINE_MAX = 20000  # 单行超长不跑正则：回溯代价随行长平方增长
_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_SUSPECT_MIN_COUNT = 20
_SUSPECT_MIN_SHARE = 0.6
_SUSPECT_MIN_CJK = 2

PageFlag = str
Fmt = Literal["paged", "legacy"]

# 渲染到锚点行上的标注（锚点行以 `#` 开头：classify_rules 的标题行提取会自然跳过）
PAGE_FLAG_NOTES = {
    "amount_case_mismatch": "⚠ 大写金额与小写金额不符，请核对原件",
    "repetitive": "⚠ OCR 复读退化，已折叠重复内容，请以原件为准",
    "thin": "⚠ 本页识别字数很少，可能漏识别，请核对原件",
    "suspected_repetition": "⚠ 疑似 OCR 复读，请以原件为准",
}


@dataclass
class SidecarPage:
    no: int
    verdict: Optional[str] = None
    chars: Optional[int] = None
    text: str = ""
    flags: list[PageFlag] = field(default_factory=list)
    placeholder: Optional[str] = None  # failed / unreadable / skipped

    @property
    def usable(self) -> bool:
        # 没有判定行的页（分页格式里罕见）按「有字就算」处理，不因缺元数据丢正文
        verdict_ok = self.verdict is None or self.verdict in USABLE_VERDICTS
        return verdict_ok and bool(self.text.strip())

    @property
    def missing_reason(self) -> str:
        if self.verdict == "skipped" or self.placeholder == "skipped":
            return "旁车未做 OCR（原件该页自带文字层）"
        if self.verdict in ("empty", "garbled") or self.placeholder == "unreadable":
            return "旁车 OCR 未识别出可读文本"
        return "旁车 OCR 未取得正文"


@dataclass
class SidecarDoc:
    fmt: Fmt
    pages: list[SidecarPage] = field(default_factory=list)
    title: Optional[str] = None
    source_path: Optional[str] = None
    declared_pages: Optional[int] = None
    ocr_pages: Optional[int] = None
    engine: Optional[str] = None
    quality_suspect: bool = False
    suspect_ratio: Optional[float] = None
    header_extra: list[str] = field(default_factory=list)
    header_lines: list[str] = field(default_factory=list)  # 卷头原文（留给 P8 逆渲染），不进正文
    legacy_text: Optional[str] = None

    @property
    def usable(self) -> bool:
        if self.fmt == "legacy":
            return bool((self.legacy_text or "").strip())
        return any(p.usable for p in self.pages)

    @property
    def usable_pages(self) -> list[int]:
        return [p.no for p in self.pages if p.usable]

    def page(self, no: int) -> Optional[SidecarPage]:
        for p in self.pages:
            if p.no == no:
                return p
        return None

    def verdict_counts(self) -> dict[str, int]:
        return dict(Counter((p.verdict or "unknown") for p in self.pages))

    def render_text(self) -> str:
        """清洗后的正文：每页 `## pN` 锚点 + 正文，标注写在锚点行上；连续不可用页合成一行。

        legacy 格式原样返回（与旧行为逐字一致）。
        """
        if self.fmt == "legacy":
            return self.legacy_text or ""
        out: list[str] = []
        if self.quality_suspect:
            ratio = f"（{self.suspect_ratio * 100:.1f}%）" if self.suspect_ratio is not None else ""
            out.append(f"# ⚠ OCR 质量存疑{ratio}：多页没识别出可读文本或疑似复读，内容不可全信")
        run: list[SidecarPage] = []

        def flush() -> None:
            if not run:
                return
            span = f"p{run[0].no}" if len(run) == 1 else f"p{run[0].no}–p{run[-1].no}"
            out.append(f"## {span} ｜{run[0].missing_reason}")
            run.clear()

        for p in self.pages:
            if not p.usable:
                if run and run[-1].missing_reason != p.missing_reason:
                    flush()
                run.append(p)
                continue
            flush()
            notes = [PAGE_FLAG_NOTES[f] for f in p.flags if f in PAGE_FLAG_NOTES]
            out.append(f"## p{p.no}" + "".join(f" ｜{n}" for n in notes))
            out.append(p.text.strip("\n"))
        flush()
        return "\n".join(out).strip()


def looks_like_paged_sidecar(text: str) -> bool:
    """同时有 `## pN` 锚点与逐页判定行，或卷头带管线签名 → 分页格式。"""
    if not text:
        return False
    if _ANCHOR_ANY.search(text) and _META_ANY.search(text):
        return True
    head = text.lstrip("\ufeff").splitlines()[:12]
    if not head or not head[0].startswith("# "):
        return False
    return any(line.startswith(_HEADER_SIGNATURES) for line in head[1:])


def parse_ocr_sidecar(text: str) -> SidecarDoc:
    text = (text or "").lstrip("\ufeff")
    if not looks_like_paged_sidecar(text):
        return SidecarDoc(fmt="legacy", legacy_text=text)

    doc = SidecarDoc(fmt="paged")
    lines = text.splitlines()
    i = 0
    # —— 卷头 ——
    while i < len(lines) and not _ANCHOR_RE.match(lines[i]):
        doc.header_lines.append(lines[i])
        _parse_header_line(doc, lines[i])
        i += 1
    # —— 逐页 ——
    cur: Optional[SidecarPage] = None
    body: list[str] = []
    for line in lines[i:]:
        m = _ANCHOR_RE.match(line)
        if m:
            if cur is not None:
                _finish_page(cur, body)
                doc.pages.append(cur)
            cur, body = SidecarPage(no=int(m.group(1))), []
            continue
        assert cur is not None
        _parse_page_line(cur, line, body)
    if cur is not None:
        _finish_page(cur, body)
        doc.pages.append(cur)
    return doc


def _parse_header_line(doc: SidecarDoc, line: str) -> None:
    s = line.strip()
    if not s:
        return
    if line.startswith("# ") and doc.title is None:
        doc.title = line[2:].strip()
    elif line.startswith(_H_PATH):
        doc.source_path = line[len(_H_PATH):].strip()
    elif line.startswith(_H_TYPE):
        m = re.search(r"页数:\s*(\d+)", line)
        doc.declared_pages = int(m.group(1)) if m else None
        m = re.search(r"OCR页:\s*(\d+)", line)
        doc.ocr_pages = int(m.group(1)) if m else None
        m = re.search(r"引擎:\s*([^｜]+)", line)
        doc.engine = m.group(1).strip() if m else None
    elif line.startswith(_H_SUSPECT):
        doc.quality_suspect = True
        m = re.search(r"（([\d.]+)%）", line)
        doc.suspect_ratio = float(m.group(1)) / 100 if m else None
    elif line.startswith((_H_OCR_NOTICE, _H_ESCAPE)):
        return
    else:
        # 不认识的卷头行：留档，不进正文（卷头是管线自述，不是客户资料）
        doc.header_extra.append(line)


def _parse_page_line(page: SidecarPage, line: str, body: list[str]) -> None:
    m = _META_RE.match(line)
    if m and page.verdict is None:
        page.chars = int(m.group(1))
        page.verdict = m.group(3)
        return
    for prefix, flag in _PAGE_WARNINGS:
        if line.startswith(prefix):
            if flag not in page.flags:
                page.flags.append(flag)
            return
    for prefix, kind in _PLACEHOLDERS:
        if line.startswith(prefix):
            page.placeholder = page.placeholder or kind
            return
    if line.startswith(_ESCAPED_PREFIXES):
        line = line[1:]
    body.append(line)


def _finish_page(page: SidecarPage, body: list[str]) -> None:
    raw = "\n".join(body)
    raw = _INLINE_TAGS.sub("", raw.replace("<br>", " "))
    if _OTSL_ANY.search(raw):
        raw = otsl_to_rows(raw)
        page.flags.append("otsl")
    if page.verdict == "repetitive":
        raw = _fold_repetition(raw)
    if _suspected_repetition(raw):
        page.flags.append("suspected_repetition")
    page.text = raw.strip("\n")


def otsl_to_rows(body: str) -> str:
    """OTSL → 每行一行、格间 ` | `。`<ecel>/<lcel>/<ucel>/<xcel>` 记为空格子（保列位）。

    表格第一格可能没有 `<fcel>` 前缀（生产样本如此），它是 `<nl>` 分段里首个格标记之前、
    最后一个换行之后的那段文字；再往前的是表前正文，原样保留。格内换行换成空格。
    """
    segments = body.split("<nl>")
    out: list[str] = []
    for seg in segments:
        if not _OTSL_CELL.search(seg):
            if seg.strip():
                out.append(seg.strip("\n"))
            continue
        parts = _OTSL_CELL.split(seg)
        lead, rest = parts[0], parts[1:]
        cells: list[str] = []
        if lead.strip():
            prose, _, first = lead.rstrip("\n").rpartition("\n")
            if prose.strip():
                out.append(prose.strip("\n"))
            cells.append(first.strip())
        for _tag, content in zip(rest[0::2], rest[1::2]):
            # 跨格标记（l/u/x）与空格（e）后面正常没有文字，有就照录，不丢
            cells.append(" ".join(content.split()))
        out.append(" | ".join(cells))
    return "\n".join(out)


def _fold_repetition(text: str) -> str:
    folded: list[str] = []
    prev = None
    for line in text.splitlines():
        if len(line) <= _REPEAT_LINE_MAX:
            line = _INLINE_REPEAT.sub(r"\1", line)
        key = line.strip()
        if key and key == prev:
            continue
        prev = key if key else prev
        folded.append(line)
    return "\n".join(folded)


def _suspected_repetition(text: str) -> bool:
    """去数字后同一模式 ≥20 次、占本页 ≥60% 的行、含 ≥2 个汉字 → 只打标，不删。

    在 ok 页上删会把钢筋表这类「同模板不同数字」的行吃掉（负控见 test_sidecar_format）。
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < _SUSPECT_MIN_COUNT:
        return False
    pattern, n = Counter(_DIGITS.sub("#", ln) for ln in lines).most_common(1)[0]
    return (
        n >= _SUSPECT_MIN_COUNT
        and n / len(lines) >= _SUSPECT_MIN_SHARE
        and len(_CJK.findall(pattern)) >= _SUSPECT_MIN_CJK
    )
