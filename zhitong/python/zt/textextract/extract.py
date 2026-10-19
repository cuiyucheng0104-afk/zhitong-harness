"""统一抽取出口：按扩展名抽正文，PDF 扫描页回落到旁车，都没有则报 ``needs_vision``。

来源：/home/user/zhitong-cost-ai/engine-service/app/engine/textextract.py（统一出口，旧 WS04-P3）与
/home/user/zhitong-cost-ai/engine-service/app/text_chain.py（页级降级链，旧 WS04-P2；``cap_chars``）。
改动：

- 去掉 OCR 服务一档、OCR 预算 / 熔断 / 缓存、解析子进程隔离；降级链只剩
  ``文字层 → 旁车 → none``；
- 扫描页无旁车时该页记缺页，一页正文都没有时 ``text_source="none"``、失败码 ``needs_vision``，
  由调用方提示 agent 用 ``read_image`` 看图；
- 读文件改为 ``(root, rel_path)``，路径经 :mod:`zt.textextract.files` 收口。

两层出口：

- :func:`extract_document`：字节 + 扩展名 → :class:`~zt.textextract.model.DocText`，不查旁车；
- :func:`load_document`：项目目录 + 相对路径 → ``DocText``，PDF 与图片会查并列的旁车。

抽不出正文必须带失败码，不存在「空串 + 成功」。
"""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Optional

from zt.common import ZtError
from zt.sidecar.format import SidecarDoc, looks_like_paged_sidecar, parse_ocr_sidecar
from zt.sidecar.locate import is_sidecar_name, read_sidecar_doc
from zt.textextract.decode import decode_text
from zt.textextract.files import file_ext, resolve_project_file
from zt.textextract.model import (
    DocText,
    PageInfo,
    exc_detail as _exc_detail,
    failed_doc,
)
from zt.textextract.office import _docx_doc, _ole_failure, _pptx_doc, libreoffice_convert_ex
from zt.textextract.pdf import (
    _open_pdf,
    _pages_from_reader,
    _pdf_text_layer_doc,
    classify_pdf_pages,
    merge_pdf_pages,
    pdf_text,
)
from zt.textextract.xlsx import _xlsx_doc

log = logging.getLogger("zt.textextract")

# 任何会改变抽出文本的改动都要递增；落盘缓存键用它
EXTRACTOR_VERSION = "zt-1"

_TEXT_EXTS = ("txt", "csv", "md", "json")
IMAGE_EXTS = ("jpg", "jpeg", "png", "bmp", "gif", "tif", "tiff", "webp")
_INDEX_GENERATED_PREFIX = "<!-- generated-by: scripts/build_source_index.py"
NEEDS_VISION_HINT = "文件没有可用文字层，请用 read_image 看图"


def _base_name(file_name: Optional[str]) -> str:
    return (file_name or "").replace("\\", "/").rsplit("/", 1)[-1]


# =============================================================================
# 旁车 → DocText
# =============================================================================


def sidecar_doc_text(text: str) -> DocText:
    """把一份旁车正文（已解码）按格式解析成 DocText：页锚 ``[pN]``、失败页记缺页。

    :param text: 旁车文本。
    :returns: 抽取结果。
    """
    return doc_from_sidecar(parse_ocr_sidecar(text))


def doc_from_sidecar(doc: SidecarDoc) -> DocText:
    """:class:`~zt.sidecar.format.SidecarDoc` → DocText；旧式纯文本旁车整段一块（无页级明细）。

    :param doc: 解析后的旁车。
    :returns: 抽取结果；一页可用的都没有时带失败码 ``no_text``。
    """
    if doc.fmt == "legacy":
        text = (doc.legacy_text or "").strip()
        if not text:
            return failed_doc("no_text", "旁车为空")
        return DocText(text=text, text_source="ocr_sidecar", ocr_derived=True,
                       quality_flags=["sidecar_legacy"])
    pages = [
        PageInfo(p.no, "ocr_sidecar", p.text, list(p.flags))
        if p.usable else
        PageInfo(p.no, "missing", "", list(p.flags), missing_reason=p.missing_reason)
        for p in doc.pages
    ]
    flags = sorted({f for p in doc.pages for f in p.flags})
    if not doc.usable:
        counts = "、".join(f"{k}={v}" for k, v in sorted(doc.verdict_counts().items()))
        return failed_doc(
            "no_text", f"旁车一页可用的都没有（页判定：{counts or '无页'}）",
            pages=pages, pages_total=len(doc.pages) or None, quality_suspect=doc.quality_suspect,
            quality_flags=flags, ocr_derived=True,
        )
    merged = merge_pdf_pages(pages, pages_total=len(doc.pages), quality_flags=flags,
                             quality_suspect=doc.quality_suspect)
    merged.ocr_derived = True
    return merged


# =============================================================================
# 字节出口
# =============================================================================


def extract_document(content: bytes, ext: str, *, file_name: Optional[str] = None,
                     table_layout: bool = False) -> DocText:
    """按扩展名抽正文，返回 DocText；抽不出**必须带失败码**。本函数不抛异常，也不查旁车。

    PDF 在这里只取文字层，扫描页记缺页；要查并列旁车用 :func:`load_document`。

    :param content: 文件字节。
    :param ext: 扩展名，带不带点均可。
    :param file_name: 文件名，用于识别 ``INDEX.md`` 与旁车。
    :param table_layout: PDF 表格页是否做版面抽取（空格子留空位）。
    :returns: 抽取结果。
    """
    ext = (ext or "").lower().lstrip(".")
    name = _base_name(file_name)
    try:
        return _extract_document(content, ext, name, table_layout=table_layout)
    except Exception as e:  # noqa: BLE001 —— 任何意外都要以原因回报，不炸调用方
        log.warning("抽取异常：%s（.%s）%s", name, ext, _exc_detail(e))
        return failed_doc("parse_failed", f"抽取异常：{_exc_detail(e)}")


def _extract_document(content: bytes, ext: str, name: str, *, table_layout: bool) -> DocText:
    if not content:
        return failed_doc("empty_file", "文件大小为 0")
    if name == "INDEX.md" and content.lstrip(b"\xef\xbb\xbf").startswith(
        _INDEX_GENERATED_PREFIX.encode("utf-8")
    ):
        return failed_doc("derived_artifact", "INDEX.md 是语料管线生成的目录索引，不是客户资料")
    if is_sidecar_name(name):
        text = decode_text(content)
        if text is None:
            return failed_doc("undecodable", "旁车无法按 UTF-8/UTF-16/GB18030 解码")
        return sidecar_doc_text(text)
    if ext in _TEXT_EXTS:
        text = decode_text(content)
        if text is None:
            return failed_doc("undecodable", f".{ext} 无法按 UTF-8/UTF-16/GB18030 解码")
        if looks_like_paged_sidecar(text):
            # 旁车被当 txt 送进来：按旁车清洗，卷头不进正文
            return sidecar_doc_text(text)
        if not text.strip():
            return failed_doc("no_text", f".{ext} 只有空白字符")
        return DocText(text=text.strip(), text_source="text_layer")
    if ext == "pdf":
        return _pdf_text_layer_doc(content, table_layout=table_layout)
    if ext in ("xlsx", "xlsm"):
        ole = _ole_failure(content, ext)
        return ole if ole is not None else _xlsx_doc(content)
    if ext in ("docx", "docm"):
        return _docx_doc(content, ext)
    if ext == "pptx":
        return _pptx_doc(content)
    if ext in ("doc", "rtf"):
        conv, why = libreoffice_convert_ex(content, ext, "docx")
        if conv is None:
            return failed_doc("convert_failed", f".{ext}→.docx 转换失败：{why}", retryable=False)
        doc = _docx_doc(conv, "docx")
        doc.quality_flags.append(f"converted_from_{ext}")
        return doc
    if ext == "xls":
        conv, why = libreoffice_convert_ex(content, "xls", "xlsx")
        if conv is None:
            return failed_doc("convert_failed", f".xls→.xlsx 转换失败：{why}")
        doc = _xlsx_doc(conv)
        doc.quality_flags.append("converted_from_xls")
        return doc
    if ext in IMAGE_EXTS:
        return failed_doc("needs_vision", f".{ext} 是图片，没有文字层；{NEEDS_VISION_HINT}")
    return failed_doc("unsupported_format", f"不支持的格式：.{ext or '（无扩展名）'}")


def extract_text(content: bytes, file_ext: str) -> str:
    """只要正文字符串的出口：抽不出返回空串，调用方自行决定如何拒绝。

    PDF 返回不带页锚的文字层（:func:`~zt.textextract.pdf.pdf_text`）；其余走 :func:`extract_document`。

    :param content: 文件字节。
    :param file_ext: 扩展名。
    :returns: 正文；抽不出为空串。
    """
    ext = (file_ext or "").lower().lstrip(".")
    if ext == "pdf":
        return pdf_text(content)
    return extract_document(content, ext).text


# =============================================================================
# 项目目录出口（带旁车）
# =============================================================================


def load_document(root: Path, rel_path: str, *, file_name: Optional[str] = None,
                  page_limit: Optional[int] = None, max_chars: Optional[int] = None,
                  table_layout: bool = False, use_sidecar: bool = True) -> DocText:
    """读项目目录内一份文件的正文，返回 DocText（正文 + 页级来源 + 缺页 / 截断 / 失败原因）。

    降级链：文字层 → 并列旁车 → none。PDF 按页判定：文字层可用的页直接用，真空白页不补，
    其余页取旁车对应页（旁车卷头页数与 PDF 不一致就不按页对位）；仍缺的页记缺页，原因含
    「请用 read_image 看图」。

    :param root: 项目目录。
    :param rel_path: 项目内相对路径。
    :param file_name: 文件名；缺省取 ``rel_path`` 的末段。
    :param page_limit: 只处理前 N 页，超出记 ``truncated``。
    :param max_chars: 按页边界截断，打 ``char_capped``。
    :param table_layout: PDF 表格页是否做版面抽取。
    :param use_sidecar: False 时不查旁车。
    :returns: 抽取结果。
    :raises zt.common.ZtError: 路径越界、非法或文件不存在。
    """
    path = resolve_project_file(root, rel_path)
    try:
        content = path.read_bytes()
    except OSError as e:
        raise ZtError("read_failed", f"读取文件失败：{rel_path}（{e}）") from e
    name = file_name or path.name
    ext = file_ext(name) or file_ext(rel_path)
    if ext == "pdf":
        doc = _load_pdf(path, root, name, content, page_limit=page_limit,
                        table_layout=table_layout, use_sidecar=use_sidecar)
    elif ext in IMAGE_EXTS:
        doc = _load_image(path, root, ext, use_sidecar=use_sidecar)
    else:
        doc = extract_document(content, ext, file_name=name, table_layout=table_layout)
    if max_chars is not None and max_chars > 0:
        doc = cap_chars(doc, max_chars)
    return doc


def _load_image(path: Path, root: Path, ext: str, *, use_sidecar: bool) -> DocText:
    hit = read_sidecar_doc(path, root) if use_sidecar else None
    if hit is not None and hit[0].usable:
        whole = doc_from_sidecar(hit[0])
        return dataclasses.replace(whole, quality_flags=whole.quality_flags + ["image_sidecar"])
    return failed_doc("needs_vision", f".{ext} 是图片，没有文字层，也没有可用旁车；{NEEDS_VISION_HINT}")


def _sidecar_matches(sdoc: SidecarDoc, total: int) -> bool:
    if sdoc.fmt != "paged" or not sdoc.pages:
        return False
    if sdoc.declared_pages is not None:
        return sdoc.declared_pages == total
    return max(p.no for p in sdoc.pages) <= total


def _load_pdf(path: Path, root: Path, name: str, content: bytes, *, page_limit: Optional[int],
              table_layout: bool, use_sidecar: bool) -> DocText:
    reader, failure = _open_pdf(content)
    if reader is None:
        assert failure is not None
        if failure.code == "encrypted":
            return failed_doc(failure.code, failure.detail)
        # pypdf 打不开的 PDF 整份当扫描件：有旁车就整份采用
        hit = read_sidecar_doc(path, root) if use_sidecar else None
        if hit is not None and hit[0].usable:
            whole = doc_from_sidecar(hit[0])
            return dataclasses.replace(whole, page_mapped=False,
                                       quality_flags=whole.quality_flags + ["pdf_unparseable"])
        return failed_doc(failure.code, f"{failure.detail}；{NEEDS_VISION_HINT}")

    total = len(reader.pages)
    infos, flags = classify_pdf_pages(_pages_from_reader(reader, page_limit, table_layout=table_layout))
    truncated = bool(page_limit and total > page_limit)
    if truncated:
        flags.append(f"page_limit:{page_limit}")
    quality_suspect = False

    # 空白页也查旁车：旁车是逐页渲染后的判定，比「无图像、内容流短」的启发式更有证据
    need = [p for p in infos if p.source in ("missing", "blank")]
    hit = read_sidecar_doc(path, root) if (need and use_sidecar) else None
    if hit is not None:
        sdoc, sname = hit
        if _sidecar_matches(sdoc, total):
            used = 0
            for info in need:
                sp = sdoc.page(info.no)
                if sp is None:
                    continue
                if sp.usable:
                    info.source, info.text = "ocr_sidecar", sp.text
                    info.flags = list(sp.flags)
                    info.missing_reason = None
                    used += 1
                elif info.source == "missing":
                    info.missing_reason = sp.missing_reason
                elif sp.verdict == "failed":
                    # 旁车说「识别失败、不是空白页」：这页不是白纸，仍需看图
                    info.source, info.missing_reason = "missing", sp.missing_reason
            if used:
                flags.append(f"sidecar_pages:{used}")
                quality_suspect = quality_suspect or sdoc.quality_suspect
        elif sdoc.usable and not any(p.source == "text_layer" for p in infos):
            # 页数对不上 / 旧式旁车：只有文字层整份为空时才整份采用，页级明细不可信
            whole = doc_from_sidecar(sdoc)
            flag = "sidecar_page_count_mismatch" if sdoc.fmt == "paged" else "sidecar_legacy_whole"
            log.info("旁车与 PDF 页数不能对位，整份采用：%s ← %s（%s）", name, sname, flag)
            return dataclasses.replace(
                whole, pages=[], pages_total=total, page_mapped=False,
                quality_flags=whole.quality_flags + [flag],
                quality_suspect=whole.quality_suspect or sdoc.quality_suspect,
            )
        elif any(p.source == "missing" for p in infos):
            flags.append("sidecar_page_count_mismatch")

    return merge_pdf_pages(
        infos, pages_total=total, truncated=truncated, quality_flags=flags,
        quality_suspect=quality_suspect,
    )


# =============================================================================
# 字数上限
# =============================================================================


def cap_chars(doc: DocText, max_chars: int) -> DocText:
    """按页边界截断到 ``max_chars``，打 ``char_capped`` + ``truncated``；被截掉的页记缺页（原因：字数上限）。

    首页自身就超限时只能页内截断（否则正文为空，反而报成失败）。

    :param doc: 抽取结果。
    :param max_chars: 字数上限。
    :returns: 截断后的新结果；未超限时原样返回。
    """
    if not doc.text or len(doc.text) <= max_chars:
        return doc
    flags = doc.quality_flags + ["char_capped"]
    if doc.pages and doc.page_mapped:
        pages = [dataclasses.replace(p, flags=list(p.flags)) for p in doc.pages]
        body = [p for p in pages if p.source in ("text_layer", "ocr_sidecar") and p.text.strip()]
        used = 0
        for i, p in enumerate(body):
            cost = len(p.text) + 16  # 锚点行
            if used + cost > max_chars:
                if i == 0:
                    p.text = p.text[:max_chars]
                    used = max_chars  # 首页已占满预算，后面的页都算超限
                    continue
                p.source, p.text, p.missing_reason = "missing", "", "超过本次调用的字数上限"
                continue
            used += cost
        merged = merge_pdf_pages(pages, pages_total=doc.pages_total, truncated=True,
                                 quality_flags=flags, quality_suspect=doc.quality_suspect,
                                 page_mapped=doc.page_mapped)
        return dataclasses.replace(merged, hidden_sheets=doc.hidden_sheets, ocr_derived=doc.ocr_derived)
    cut = doc.text[:max_chars]
    nl = cut.rfind("\n")
    if nl > max_chars // 2:
        cut = cut[:nl]
    return dataclasses.replace(doc, text=cut.rstrip(), truncated=True, quality_flags=flags)
