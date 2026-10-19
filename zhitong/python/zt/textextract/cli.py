"""``python -m zt.textextract.cli extract|search``：读项目文件正文 / 在项目里按字面量检索。

用法::

    $ZT_PYTHON -m zt.textextract.cli extract --root <项目目录> --file 资料/合同.pdf \
        [--page-limit 20] [--max-chars 30000] [--text-out 工作/合同.txt] [--out result.json]

状态映射：

- ``ok``：取得全部正文；来源是旁车时带 info 级告警 ``text_from_sidecar``；
- ``partial``：有正文但缺页 / 被截断 / 页级明细不可信；``coverage`` 列出缺哪些页，
  告警 ``scanned_pages_need_vision`` 的 ``hint`` 说明用 ``read_image`` 看这些页；
- ``insufficient``：一个字都没取到，``status_reason`` 是失败码（扫描件为 ``needs_vision``），
  ``data.text_source`` 为 ``none``；
- 路径越界 / 文件不存在：退出码 2。

``search`` 在项目目录里按字面量检索 docx / xlsx / PDF / 文本（见 :mod:`zt.textextract.search`）::

    $ZT_PYTHON -m zt.textextract.cli search --root <项目目录> --keyword 合同价款 --keyword 调整 [--any] [--subdir 资料]

``check-answer`` 核对问答回答的出处（见 :mod:`zt.textextract.answer_check`）::

    $ZT_PYTHON -m zt.textextract.cli check-answer --answer 工作/问答/答案.md \
        --source 资料/合同.pdf=工作/问答/合同.txt --source 资料/清单.xlsx=工作/问答/清单.txt

答案里找不到出处的数字、指向没读过的资料的引用都以 warn 级告警列出，``data.passed`` 为 false。

``search`` 状态：``ok`` 有命中且全部文件都搜完；``partial`` 有些文件没能完整搜索（图片、DWG、加密、扫描页无旁车），
命中为空时同样是 ``partial``（``status_reason=no_match_in_readable_files``），不是「没有」；
``empty``（``no_match``）才表示所有文件都搜过、确实没有命中。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from zt.common import (
    Call,
    Cli,
    Envelope,
    WarningItem,
    WarningLevel,
    ZtError,
    empty,
    insufficient,
    ok,
    partial,
)
from zt.textextract.answer_check import check_answer, read_source
from zt.textextract.extract import load_document
from zt.textextract.search import SearchResult, search_project
from zt.textextract.model import DocText

cli = Cli("zt.textextract", "读取项目文件正文（文字层 / 旁车），扫描件提示看图")


def _args(p: Any) -> None:
    p.add_argument("--root", required=True, help="项目目录（本机缓存里的 项目/<编号>-<工程名>/）")
    p.add_argument("--file", required=True, help="项目内相对路径")
    p.add_argument("--page-limit", type=int, default=None, help="只处理前 N 页")
    p.add_argument("--max-chars", type=int, default=None, help="正文字数上限，按页边界截断")
    p.add_argument("--text-out", default=None, help="把正文写到这个文件，data 里只留路径与字数")
    p.add_argument("--no-sidecar", action="store_true", help="不查并列的 .ocr.txt 旁车")
    p.add_argument("--table-layout", action="store_true", help="PDF 表格页按版面抽取，空格子留空位")


def _page_list(pages: list[int]) -> str:
    return "、".join(f"p{n}" for n in pages)


def _warnings(doc: DocText, rel_path: str) -> list[WarningItem]:
    out: list[WarningItem] = []
    if doc.failure is not None:
        vision = doc.failure.code == "needs_vision"
        out.append(WarningItem(
            code=doc.failure.code,
            level=WarningLevel.WARN if vision else WarningLevel.ERROR,
            message=doc.failure.detail,
            hint=f"用 read_image 看图读取 {rel_path}" if vision else None,
        ))
        return out
    if doc.pages_missing:
        out.append(WarningItem(
            code="scanned_pages_need_vision",
            level=WarningLevel.WARN,
            message=f"{rel_path} 有 {len(doc.pages_missing)} 页没有取得正文：{_page_list(doc.pages_missing)}",
            hint=f"用 read_image 看这些页（{_page_list(doc.pages_missing)}），不要凭其余页推测它们的内容",
        ))
    if doc.truncated:
        out.append(WarningItem(code="text_truncated", level=WarningLevel.WARN,
                               message="正文被截断（页数或字数上限），后面的内容没有读到",
                               hint="需要后面的内容时放宽 --page-limit / --max-chars 再读"))
    if not doc.page_mapped:
        out.append(WarningItem(code="sidecar_pages_unmapped", level=WarningLevel.WARN,
                               message="旁车与 PDF 页数对不上，页级明细不可信；正文整份取自旁车",
                               hint="引用页码前先核对原件"))
    if doc.quality_suspect:
        out.append(WarningItem(code="sidecar_quality_suspect", level=WarningLevel.WARN,
                               message="旁车 OCR 质量存疑（多页未识别或疑似复读），内容不可全信",
                               hint="关键数字回原件核对，必要时用 read_image 看图"))
    if doc.text_source == "ocr_sidecar" or doc.pages_sidecar:
        out.append(WarningItem(code="text_from_sidecar", level=WarningLevel.INFO,
                               message="正文（至少部分）来自 OCR 旁车，不是文件自带文字层",
                               hint="金额与数量需对照原件"))
    return out


def _coverage(doc: DocText) -> dict[str, Any]:
    return {
        "pages_total": doc.pages_total,
        "pages_ok": doc.pages_ok,
        "pages_missing": doc.pages_missing,
        "pages_blank": doc.pages_blank,
        "truncated": doc.truncated,
        "page_mapped": doc.page_mapped,
    }


@cli.command("extract", help="读一份文件的正文", arguments=_args)
def extract(call: Call) -> Envelope:
    """读项目目录内一份文件的正文并按信封输出。

    :param call: 调用上下文。
    :returns: 结果信封。
    :raises ZtError: 路径越界或文件不存在。
    """
    a = call.args
    root = Path(a.root)
    if not root.is_dir():
        raise ZtError("root_not_found", f"项目目录不存在：{a.root}")
    doc = load_document(root, a.file, page_limit=a.page_limit, max_chars=a.max_chars,
                        table_layout=a.table_layout, use_sidecar=not a.no_sidecar)
    warnings = _warnings(doc, a.file)
    data: dict[str, Any] = {"rel_path": a.file, **doc.provenance(), "text_chars": len(doc.text)}
    if doc.failure is not None:
        data["text"] = ""
        return insufficient(doc.failure.code, coverage=_coverage(doc), warnings=warnings, data=data)
    if a.text_out:
        target = Path(a.text_out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc.text + "\n", encoding="utf-8", newline="\n")
        data["text_path"] = str(target)
    else:
        data["text"] = doc.text
    if doc.complete:
        return ok(data, coverage=_coverage(doc), warnings=warnings)
    return partial(data, coverage=_coverage(doc), warnings=warnings)


def _search_args(p: Any) -> None:
    p.add_argument("--root", required=True, help="项目目录")
    p.add_argument("--keyword", action="append", default=[], help="关键词，可重复；默认同一单元内全部出现才算命中")
    p.add_argument("--any", action="store_true", help="任一关键词出现即命中")
    p.add_argument("--subdir", default=None, help="只搜项目内这个子目录")
    p.add_argument("--case-sensitive", action="store_true", help="区分大小写")
    p.add_argument("--max-hits", type=int, default=50, help="命中条数上限")
    p.add_argument("--max-files", type=int, default=500, help="最多读多少个文件")
    p.add_argument("--no-sidecar", action="store_true", help="PDF 不读并列的 .ocr.txt 旁车")
    p.add_argument("--table-layout", action="store_true", help="PDF 表格页按版面抽取")


def _search_warnings(res: SearchResult, keywords: list[str]) -> list[WarningItem]:
    out: list[WarningItem] = []
    vision = [s for s in res.skipped if s.reason == "needs_vision"]
    if vision:
        listing = "；".join(s.rel_path + (f"（{'、'.join(f'p{n}' for n in s.pages)}）" if s.pages else "")
                           for s in vision[:10])
        out.append(WarningItem(
            code="unsearched_need_vision", level=WarningLevel.WARN,
            message=f"{len(vision)} 个文件（或其中几页）没有文字层，没搜到不代表没有：{listing}",
            hint="需要时用 read_image 看这些文件；回答里要说明它们没被搜索"))
    other = [s for s in res.skipped if s.reason not in ("needs_vision", "hidden_sheets")]
    if other:
        listing = "；".join(f"{s.rel_path}（{s.reason}）" for s in other[:10])
        out.append(WarningItem(code="files_not_searched", level=WarningLevel.WARN,
                               message=f"{len(other)} 个文件没能搜索：{listing}",
                               hint="格式不支持或文件损坏；需要时单独打开确认"))
    hidden = [s for s in res.skipped if s.reason == "hidden_sheets"]
    if hidden:
        out.append(WarningItem(code="hidden_sheets_skipped", level=WarningLevel.INFO,
                               message=f"{len(hidden)} 个 xlsx 的隐藏工作表未搜索"))
    if res.truncated_hits:
        out.append(WarningItem(code="hits_truncated", level=WarningLevel.WARN,
                               message="命中条数达到上限，后面的命中没有列出",
                               hint="加关键词收窄，或用 --subdir 限定范围"))
    if res.truncated_files:
        out.append(WarningItem(code="files_truncated", level=WarningLevel.WARN,
                               message=f"文件数超过上限，只搜了前 {res.files_searched} 个",
                               hint="用 --subdir 分目录搜"))
    return out


@cli.command("search", help="在项目里按字面量检索 docx / xlsx / PDF / 文本", arguments=_search_args)
def search(call: Call) -> Envelope:
    """在项目目录里检索关键词。

    :param call: 调用上下文。
    :returns: 结果信封，命中带 EvidenceRef 字段的定位与 200 字内引文。
    :raises ZtError: 没有关键词、目录或子目录不存在、路径越界。
    """
    a = call.args
    res = search_project(Path(a.root), a.keyword, subdir=a.subdir, any_mode=a.any,
                         ignore_case=not a.case_sensitive, max_hits=a.max_hits, max_files=a.max_files,
                         use_sidecar=not a.no_sidecar, table_layout=a.table_layout)
    warnings = _search_warnings(res, a.keyword)
    coverage = {
        "files_total": res.files_total, "files_used": res.files_searched,
        "skipped": [{"rel_path": s.rel_path, "reason": s.reason, **({"pages": s.pages} if s.pages else {})}
                    for s in res.skipped if s.reason != "hidden_sheets"],
    }
    data = {
        "keywords": a.keyword, "mode": "any" if a.any else "all",
        "hits": [{"rel_path": h.rel_path, **h.locator, "quote": h.text[:200]} for h in res.hits],
        "hit_count": len(res.hits),
    }
    incomplete = bool([s for s in res.skipped if s.reason != "hidden_sheets"]) or res.truncated_files or res.truncated_hits
    if res.hits:
        return partial(data, coverage=coverage, warnings=warnings) if incomplete else ok(data, coverage=coverage, warnings=warnings)
    if incomplete:
        return partial(data, coverage=coverage, warnings=warnings, reason="no_match_in_readable_files")
    return empty("no_match", coverage=coverage, data=data, warnings=warnings)


def _check_args(p: Any) -> None:
    p.add_argument("--answer", required=True, help="答案文本文件")
    p.add_argument("--source", action="append", default=[],
                   help="读过的资料：<项目内相对路径>=<文本文件>，可重复；文本通常来自 extract --text-out")
    p.add_argument("--max-report", type=int, default=20, help="最多列出多少条无出处的数")


@cli.command("check-answer", help="核对回答里的数字与引用是否有出处", arguments=_check_args)
def check_answer_cmd(call: Call) -> Envelope:
    """核对回答里的数字回链与引用。

    :param call: 调用上下文。
    :returns: 结果信封；``data.passed`` 为 false 时 ``warning_items`` 逐条列出问题。
    :raises ZtError: 答案或资料文本文件不存在、无法按 UTF-8 读取。
    """
    a = call.args
    answer_path = Path(a.answer)
    if not answer_path.is_file():
        raise ZtError("file_not_found", f"答案文件不存在：{answer_path}")
    sources = []
    for spec in a.source:
        try:
            sources.append(read_source(spec))
        except (OSError, UnicodeDecodeError) as e:
            raise ZtError("source_unreadable", f"读不了资料文本 {spec!r}：{e}",
                          hint="用 extract --text-out 把读过的资料写成文本文件再传入") from e
    res = check_answer(answer_path.read_text(encoding="utf-8"), sources)
    warnings: list[WarningItem] = []
    for u in res.unattributed[: a.max_report]:
        warnings.append(WarningItem(
            code="unattributed_number", level=WarningLevel.WARN,
            message=f"数字「{u.raw}」在读过的资料里找不到出处：…{u.context}…",
            hint="补上读过的出处；找不到就明确写成「资料中未找到出处」，金额不得自行推算"))
    if len(res.unattributed) > a.max_report:
        warnings.append(WarningItem(code="more_unattributed", level=WarningLevel.WARN,
                                    message=f"另有 {len(res.unattributed) - a.max_report} 个数字也没有出处"))
    for issue in res.citation_issues:
        warnings.append(WarningItem(code=issue.problem, level=WarningLevel.WARN,
                                    message=f"{issue.cite}：{issue.detail}",
                                    hint="引用只指向读过的文件与位置；先读再引，或删掉这条引用"))
    if res.numbers_checked and not res.citations_total:
        warnings.append(WarningItem(code="no_citations", level=WarningLevel.WARN,
                                    message="回答里有数字，但没有任何〔文件 位置〕形式的引用",
                                    hint="事实句末标出处，例如〔资料/合同.pdf p3〕"))
    data = {
        "passed": res.passed and not (res.numbers_checked and not res.citations_total),
        "numbers_checked": res.numbers_checked,
        "unattributed": [{"raw": u.raw, "kind": u.kind, "context": u.context} for u in res.unattributed],
        "citations_total": res.citations_total,
        "citation_issues": [{"cite": i.cite, "problem": i.problem, "detail": i.detail} for i in res.citation_issues],
        "sources": [s.rel_path for s in sources],
    }
    return ok(data, warnings=warnings)


if __name__ == "__main__":
    raise SystemExit(cli.main())
