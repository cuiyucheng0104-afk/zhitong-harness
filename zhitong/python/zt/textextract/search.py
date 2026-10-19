"""项目目录内的字面量检索：docx / xlsx / pdf / pptx / 文本类，带定位。

harness 自带的 ``grep`` 只能搜纯文本；资料多是 docx、xlsx、PDF。本模块把每份文件拆成检索单元，
按字面量匹配，返回「哪份文件的哪一页 / 哪个工作表的哪一行 / 哪一段」。

来源：旧仓 engine-service/app/filetree/tools.py 的 GREP 语义（字面量、多关键词在同一检索单元内 AND；
txt 一行、docx 一段或表格行、xlsx 一行、PDF 一行），去掉 LLM 导航与 DSL。

检索单元与定位（对应 :class:`zt.common.EvidenceRef`）：

=========  ====================================  ==========================
文件       检索单元                              定位
=========  ====================================  ==========================
txt/md…    一行                                  ``row`` = 行号，``row_label="行"``
docx       一段或表格的一行（块号从 1 起）        ``paragraph`` = 块号
xlsx       一个工作表的一行（隐藏表跳过）        ``sheet`` + ``row``
pdf        文字层 / 旁车里的一行                  ``page``
pptx       一张幻灯片里的一段                     ``paragraph``（页内段号）+ ``heading="幻灯片 N"``
=========  ====================================  ==========================

未命中不等于没有：读不了的文件（图片、DWG、加密、扫描页无旁车）如实列在 ``skipped``，
调用方必须在回答里说明「这些没搜到、需要看图」。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from zt.common import ZtError
from zt.common.paths import resolve_within
from zt.sidecar.locate import is_sidecar_name
from zt.textextract.decode import decode_text
from zt.textextract.docx_reader import docx_blocks
from zt.textextract.extract import IMAGE_EXTS, extract_document, load_document
from zt.textextract.files import file_ext
from zt.textextract.model import DocText
from zt.textextract.xlsx import read_xlsx

log = logging.getLogger("zt.textextract.search")

DEFAULT_EXCLUDE_TOP = ("工作",)
TEXT_EXTS = ("txt", "md", "csv", "json")
SEARCHABLE_EXTS = (*TEXT_EXTS, "docx", "docm", "xlsx", "xlsm", "pdf", "pptx", "doc", "xls", "rtf")
SNIPPET_CHARS = 300


@dataclass
class Hit:
    """一条命中。``locator`` 的键是 :class:`~zt.common.EvidenceRef` 的字段。"""

    rel_path: str
    locator: dict[str, Any]
    text: str


@dataclass
class Skipped:
    """没能完整搜索的文件。"""

    rel_path: str
    reason: str
    detail: str = ""
    pages: list[int] = field(default_factory=list)


@dataclass
class SearchResult:
    """检索结果。"""

    hits: list[Hit] = field(default_factory=list)
    files_total: int = 0
    files_searched: int = 0
    skipped: list[Skipped] = field(default_factory=list)
    truncated_hits: bool = False
    truncated_files: bool = False


def _matches(text: str, keywords: list[str], any_mode: bool, ignore_case: bool) -> bool:
    hay = text.lower() if ignore_case else text
    needles = [k.lower() for k in keywords] if ignore_case else keywords
    return any(k in hay for k in needles) if any_mode else all(k in hay for k in needles)


def _snippet(text: str) -> str:
    one = " ".join(text.split())
    return one if len(one) <= SNIPPET_CHARS else one[:SNIPPET_CHARS]


def _units(path: Path, rel: str, ext: str, content: bytes, *, root: Path, use_sidecar: bool,
           table_layout: bool) -> tuple[list[tuple[dict[str, Any], str]], Optional[Skipped]]:
    """文件 → [(定位, 单元文本)]，以及不完整时的 Skipped 说明。"""
    if ext in TEXT_EXTS:
        text = decode_text(content)
        if text is None:
            return [], Skipped(rel, "undecodable", "无法按 UTF-8/UTF-16/GB18030 解码")
        return [({"row": i, "row_label": "行"}, ln) for i, ln in enumerate(text.splitlines(), start=1)], None
    if ext in ("docx", "docm"):
        try:
            blocks = docx_blocks(content)
        except Exception as e:  # noqa: BLE001 —— 坏文件如实记，不炸整次检索
            return [], Skipped(rel, "parse_failed", f"{type(e).__name__}: {str(e)[:120]}")
        return [({"paragraph": b.no}, b.num_prefix + b.text) for b in blocks if (b.num_prefix + b.text).strip()], None
    if ext in ("xlsx", "xlsm"):
        try:
            book = read_xlsx(content)
        except Exception as e:  # noqa: BLE001
            return [], Skipped(rel, "parse_failed", str(e)[:160])
        units = [({"sheet": s.name, "row": rno}, "\t".join(v for _c, v in cells))
                 for s in book.sheets if s.state == "visible" for rno, cells in s.rows]
        note = Skipped(rel, "hidden_sheets", "已跳过隐藏工作表：" + "、".join(book.hidden_sheets)) if book.hidden_sheets else None
        return units, note
    # pdf / pptx / 老格式：走统一出口，PDF 带旁车
    doc: DocText = (load_document(root, rel, use_sidecar=use_sidecar, table_layout=table_layout)
                    if ext == "pdf" else extract_document(content, ext, file_name=path.name))
    if doc.failure is not None:
        return [], Skipped(rel, doc.failure.code, doc.failure.detail, pages=doc.pages_missing)
    units: list[tuple[dict[str, Any], str]] = []
    if doc.pages:
        for p in doc.pages:
            if p.source in ("text_layer", "ocr_sidecar"):
                units += [({"page": p.no}, ln) for ln in p.text.splitlines() if ln.strip()]
    elif ext == "pdf":
        units += [({"row": i, "row_label": "行"}, ln) for i, ln in enumerate(doc.text.splitlines(), start=1)]
    elif ext == "pptx":
        slide, para = 0, 0
        for ln in doc.text.splitlines():
            if ln.startswith("## 幻灯片 "):
                slide, para = int(ln.rsplit(" ", 1)[-1]), 0
                continue
            para += 1
            units.append(({"paragraph": para, "heading": f"幻灯片 {slide}"}, ln))
    else:
        units += [({"row": i, "row_label": "行"}, ln) for i, ln in enumerate(doc.text.splitlines(), start=1)]
    incomplete = None
    if doc.pages_missing:
        incomplete = Skipped(rel, "needs_vision", "部分页没有文字层也没有旁车，需用 read_image 看图", pages=doc.pages_missing)
    elif doc.truncated:
        incomplete = Skipped(rel, "truncated", "正文被截断")
    return units, incomplete


def _walk(root: Path, subdir: Optional[str], exclude_top: tuple[str, ...]) -> list[Path]:
    base = root.resolve()
    start = base
    if subdir:
        start = resolve_within(root, subdir)
        if not start.is_dir():
            raise ZtError("subdir_not_found", f"子目录不存在：{subdir}")
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
        rel_parts = Path(dirpath).relative_to(base).parts
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and not (not rel_parts and d in exclude_top))
        for fname in sorted(filenames):
            if fname.startswith((".", "~$")) or is_sidecar_name(fname) or fname == "INDEX.md":
                continue
            if not rel_parts and fname in ("项目说明.md", "案例索引.md"):
                continue
            out.append(Path(dirpath) / fname)
    return out


def search_project(root: Path, keywords: list[str], *, subdir: Optional[str] = None, any_mode: bool = False,
                   ignore_case: bool = True, max_hits: int = 50, max_files: int = 500,
                   use_sidecar: bool = True, table_layout: bool = False,
                   exclude_top: tuple[str, ...] = DEFAULT_EXCLUDE_TOP) -> SearchResult:
    """在项目目录里按字面量检索。

    :param root: 项目目录。
    :param keywords: 关键词（非空）；默认同一检索单元内全部出现才算命中。
    :param subdir: 只搜这个子目录（项目内相对路径）。
    :param any_mode: True 时任一关键词出现即命中。
    :param ignore_case: 是否忽略大小写。
    :param max_hits: 命中条数上限，超出置 ``truncated_hits``。
    :param max_files: 最多读多少个文件，超出置 ``truncated_files``。
    :param use_sidecar: PDF 是否读并列旁车。
    :param table_layout: PDF 表格页是否做版面抽取。
    :param exclude_top: 顶层排除目录名。
    :returns: 检索结果；``skipped`` 列出没能完整搜索的文件。
    :raises ZtError: 关键词为空（``no_keywords``）、项目目录或子目录不存在、路径越界。
    """
    words = [k for k in (w.strip() for w in keywords) if k]
    if not words:
        raise ZtError("no_keywords", "没有给出关键词")
    if not root.is_dir():
        raise ZtError("root_not_found", f"项目目录不存在：{root}")
    result = SearchResult()
    base = root.resolve()
    files = _walk(root, subdir, exclude_top)
    result.files_total = len(files)
    for path in files:
        rel = path.relative_to(base).as_posix()
        ext = file_ext(path.name)
        if ext in IMAGE_EXTS:
            result.skipped.append(Skipped(rel, "needs_vision", "图片没有文字层，需用 read_image 看图"))
            continue
        if ext not in SEARCHABLE_EXTS:
            result.skipped.append(Skipped(rel, "unsupported_format", f".{ext or '（无扩展名）'}"))
            continue
        if result.files_searched >= max_files:
            result.truncated_files = True
            break
        try:
            path.resolve().relative_to(base)
        except (ValueError, OSError):
            result.skipped.append(Skipped(rel, "symlink_outside_project", "符号链接指向项目目录之外，未读取"))
            continue
        try:
            content = path.read_bytes()
        except OSError as e:
            result.skipped.append(Skipped(rel, "unreadable", str(e)[:120]))
            continue
        units, note = _units(path, rel, ext, content, root=root, use_sidecar=use_sidecar, table_layout=table_layout)
        if note is not None:
            result.skipped.append(note)
        if not units and note is not None and note.reason != "hidden_sheets":
            continue  # 一个单元都没读到：不算搜过
        result.files_searched += 1
        for locator, text in units:
            if _matches(text, words, any_mode, ignore_case):
                if len(result.hits) >= max_hits:
                    result.truncated_hits = True
                    return result
                result.hits.append(Hit(rel, locator, _snippet(text)))
    return result
