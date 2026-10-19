# 来源：engine-service/app/api/report.py 的编排逻辑（report_context / report_facts / report_section / report_export、
# cut_to_last_sentence、_FLAG_WARN_TEXT、质量态判定）（zhitong-cost-ai@991ff5c，W3 搬入 zt）。
"""报告初稿的编排：取材、金额事实、逐章 prepare / finalize、导出 docx。

旧仓 ``POST /engine/report/section`` 在一个请求里做「选材 → 调模型 → 护栏 → 事实替换」。zt 不调模型，拆成两半
（spec §4.1）：

- :func:`section_prepare`：解析章节定义、选材、组装提示词（系统提示词九条 + 用户消息分块），把送入的原文切片
  （护栏证据）一并写进结果；
- agent 按提示词写本章（中间那步）；
- :func:`section_finalize`：对 agent 写的正文跑确定性护栏，再把〔Fn〕换成单元格原值并带来源，判质量态。

其余改动：

- 文件来自本机项目目录（``root`` + 相对路径），经 :mod:`zt.textextract` 读正文；没有 OCR 服务，扫描件没有旁车时
  记为读不出（原因提示用 ``read_image`` 看图并补旁车）；
- 旧端点的 HTTP 错误改为 :class:`zt.common.ZtError`（退出码 2）；越界路径同样是错误，不吞；
- 模型用量、``reasoning``、``model`` 字段去掉；
- 金额事实不再由 Java 存库：``facts`` 子命令写一份 JSON，每章 prepare / finalize 读同一份。
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from zt.common import Envelope, FileCoverage, SkippedFile, WarningItem, ZtError, empty, insufficient, manual, ok, partial
from zt.common.paths import to_rel_posix
from zt.report.compose import (
    SYSTEM_PROMPT,
    CorpusFile,
    Selection,
    UsedFile,
    build_messages,
    select_files_for_section,
)
from zt.report.export import build_docx, section_label
from zt.report.facts import FACT_LABELS, FACTS_DEADLINE_MS, collect_facts, needed_notice, substitute_facts
from zt.report.guard import (
    DEFAULT_CLAIMS,
    MARK_META,
    MARK_TRUNCATED,
    MOSTLY_TODO_CHARS_PER_TODO,
    INSUFFICIENT_MIN_CHARS,
    EvidenceFile,
    GuardFlag,
    cited_indexes,
    guard_section,
    is_mostly_todo,
    meaningful_chars,
    todo_count,
)
from zt.report.templates import find_template, resolve_section, spec_of, template_fact_keys
from zt.textextract.extract import load_document
from zt.textextract.files import file_ext, resolve_project_file

log = logging.getLogger("zt.report.service")

# 单份正文上限（按页边界截断、标 truncated）
REPORT_FILE_MAX_CHARS = 200_000

KIND_SOURCE = "source"
KIND_FINISHED = "finished_report"
KINDS = (KIND_SOURCE, KIND_FINISHED)

# 格式不支持时给导出指引（广联达计价、算量文件与清单审计文件读不了）
_EXPORT_HINTS = (
    (("gbq7", "gbq6", "gbq5", "gbq4", "gbq", "gtj", "gcl", "gqi", "gbq9", "清单审计"),
     "这是广联达等造价软件的工程文件，请在软件里导出为 Excel（xlsx）或 PDF 后再给"),
    (("zip", "rar", "7z", "tar", "gz"), "这是压缩包，请解压后给其中的文件"),
    (("dwg", "dxf", "rvt"), "这是图纸源文件，请用 zt-cad 看图，或导出为 PDF 后再给"),
)


def _export_hint(file_name: str) -> str:
    name = (file_name or "").lower()
    ext = file_ext(file_name) or ""
    for exts, hint in _EXPORT_HINTS:
        if ext in exts or any(name.endswith("." + e) for e in exts):
            return hint
    return "请另存为 PDF、Word（docx）或 Excel（xlsx）后再给"


# ================================================================ 请求里的文件


@dataclass(frozen=True)
class SourceRef:
    """一份资料：项目目录内相对路径（``/`` 分隔）+ 文件名 + 种类（资料 / 已成稿报告）。"""

    rel_path: str
    file_name: str
    kind: str = KIND_SOURCE

    @property
    def file_id(self) -> str:
        """文件标识就是规范后的相对路径。"""
        return self.rel_path


def source_refs(files: Iterable[Any], finished: Iterable[str] = ()) -> list[SourceRef]:
    """请求里的文件列表 → 规范后的 :class:`SourceRef`，按相对路径排序、去重。

    排序决定 ``[资料n]`` 的 n：同一批资料不论传入顺序如何，编号都相同。

    :param files: 字符串（相对路径），或 ``{"rel_path", "file_name"?, "kind"?}``。
    :param finished: 额外的已成稿报告相对路径（``kind=finished_report``）。
    :returns: 资料列表。
    :raises ZtError: 路径非法（``invalid_path``）或 kind 不认识（``invalid_request``）。
    """
    out: dict[str, SourceRef] = {}

    def add(raw: Any, kind_default: str) -> None:
        if isinstance(raw, str):
            rel, name, kind = raw, None, kind_default
        elif isinstance(raw, dict) and isinstance(raw.get("rel_path"), str):
            rel, name, kind = raw["rel_path"], raw.get("file_name"), raw.get("kind") or kind_default
        else:
            raise ZtError("invalid_request", f"文件项应为相对路径字符串或带 rel_path 的对象：{raw!r}")
        if kind not in KINDS:
            raise ZtError("invalid_request", f"kind 只能是 {' / '.join(KINDS)}：{kind!r}")
        norm = to_rel_posix(rel)
        out[norm] = SourceRef(norm, name or norm.rsplit("/", 1)[-1], kind)

    for f in files or ():
        add(f, KIND_SOURCE)
    for f in finished or ():
        add(f, KIND_FINISHED)
    return [out[k] for k in sorted(out)]


# ================================================================ context


def build_context(root: Path, refs: Sequence[SourceRef], *, max_chars: int = REPORT_FILE_MAX_CHARS) -> Envelope:
    """读每份资料的正文，逐份回报读取结果。

    - 读出正文的进 ``data.files``（``index`` = ``[资料n]`` 的 n）；正文与前面一份逐字相同的进 ``data.duplicates``；
    - 读不出（格式不支持、扫描件无旁车、文件不存在、空文件）的进 ``data.unreadable``，带原因；
    - 单份超过 ``max_chars`` 按页截断，标 ``truncated``。

    :param root: 项目目录。
    :param refs: :func:`source_refs` 的结果。
    :param max_chars: 单份正文上限。
    :returns: 信封：全部读出 ok；有读不出的 partial；一份都读不出 empty（``no_readable_sources``）。
    :raises ZtError: 没给文件（``invalid_request``）或路径越界（``invalid_path``）。
    """
    if not refs:
        raise ZtError("invalid_request", "没有给资料文件", hint="用 --files 列出项目目录内的相对路径")
    files: list[dict] = []
    unreadable: list[dict] = []
    duplicates: list[dict] = []
    hidden: list[str] = []
    first_by_sha: dict[str, str] = {}
    for ref in refs:
        base = {"file_id": ref.file_id, "rel_path": ref.rel_path, "file_name": ref.file_name, "kind": ref.kind}
        try:
            resolve_project_file(root, ref.rel_path)
        except ZtError as e:
            if e.code != "file_not_found":
                raise
            unreadable.append({**base, "extract_status": "missing", "failure_code": "file_missing",
                               "reason": "项目目录里没有这份文件，先用 tos_pull 拉到本机缓存"})
            continue
        doc = load_document(root, ref.rel_path, file_name=ref.file_name, max_chars=max_chars)
        hidden.extend(f"《{ref.file_name}》{s}" for s in doc.hidden_sheets)
        text = doc.text or ""
        common = {
            **base,
            "text_source": doc.text_source,
            "text_source_detail": doc.text_source_detail,
            "ocr_risk": bool(doc.ocr_derived or doc.text_source_detail in ("ocr_sidecar", "mixed")),
            "quality_suspect": bool(doc.quality_suspect),
            "truncated": bool(doc.truncated),
            "pages_missing": list(doc.pages_missing),
            "hidden_sheets_skipped": list(doc.hidden_sheets),
        }
        if text.strip():
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            dup_of = first_by_sha.get(sha)
            if dup_of is not None:
                duplicates.append({**common, "text_sha256": sha, "duplicate_of": dup_of, "char_count": len(text),
                                   "extract_status": "duplicate",
                                   "reason": "正文与前面一份资料逐字相同，不重复送入"})
                continue
            first_by_sha[sha] = ref.file_id
            files.append({**common, "index": len(files) + 1, "extract_status": "ok", "text_sha256": sha,
                          "char_count": len(text), "text": text,
                          "reason": "正文超过单份上限，已按页截断" if doc.truncated else None})
            continue
        failure = doc.failure
        code = failure.code if failure is not None else "no_text"
        detail = failure.detail if failure is not None else "没有取到正文"
        if code == "unsupported_format":
            status, reason = "unsupported", f"{detail}。{_export_hint(ref.file_name)}"
        else:
            status, reason = "empty_or_failed", detail
        unreadable.append({**common, "extract_status": status, "failure_code": code, "reason": reason})

    data = {"root": root.resolve().as_posix(), "max_chars": max_chars, "files": files, "unreadable": unreadable,
            "duplicates": duplicates, "hidden_sheets": hidden}
    coverage = FileCoverage(
        files_total=len(refs), files_used=len(files),
        skipped=[SkippedFile(rel_path=u["rel_path"], file_name=u["file_name"], reason=u["reason"]) for u in unreadable]
        + [SkippedFile(rel_path=d["rel_path"], file_name=d["file_name"], reason=d["reason"]) for d in duplicates],
    ).model_dump()
    warnings: list[WarningItem] = []
    if unreadable:
        warnings.append(WarningItem(code="unreadable_files", level="warn", message=(
            f"{len(unreadable)} 份资料读不出正文：" + _names([u["file_name"] for u in unreadable])),
            hint="扫描件先用 read_image 看图并补 <原件名>.ocr.txt 旁车；造价软件工程文件请导出为 xlsx 或 PDF"))
    if duplicates:
        warnings.append(WarningItem(code="duplicate_files", level="info",
                                    message=f"{len(duplicates)} 份资料与前面的资料正文逐字相同，不重复送入"))
    capped = [f["file_name"] for f in files if f["truncated"]]
    if capped:
        warnings.append(WarningItem(code="source_capped", level="warn", message=(
            f"{_names(capped)}正文超过 {max_chars // 10000} 万字，只读了前 {max_chars // 10000} 万字")))
    if not files:
        return empty("no_readable_sources", coverage=coverage, warnings=warnings, data=data)
    if unreadable or capped:
        return partial(data, coverage=coverage, warnings=warnings)
    return ok(data, coverage=coverage, warnings=warnings)


def _names(names: Sequence[str], limit: int = 5) -> str:
    out = "、".join(f"《{n}》" for n in names[:limit])
    return out + (f"等 {len(names)} 份" if len(names) > limit else "")


def context_data(raw: Any) -> dict:
    """读 ``context`` 的结果（信封或其 ``data``）。

    :param raw: JSON。
    :returns: ``data`` 字典。
    :raises ZtError: 不是 context 结果（``invalid_context``）。
    """
    data = raw.get("data") if isinstance(raw, dict) and "status" in raw else raw
    if not isinstance(data, dict) or not isinstance(data.get("files"), list) or "unreadable" not in data:
        raise ZtError("invalid_context", "不是 context 子命令的结果", hint="先运行 context 子命令，再把它的 result.json 传进来")
    return data


# ================================================================ facts


def build_facts(root: Path, refs: Sequence[SourceRef], *, template: Optional[dict] = None,
                deadline_ms: int = FACTS_DEADLINE_MS) -> Envelope:
    """勾选资料里的表格 → 金额事实（审定单通道 + 项目级费用表通道）。

    单份读坏了只记 notes；路径越界整批拒绝。金额只取资料里写着的一格并带来源；多于一个候选是冲突，不取舍；不派生。

    :param root: 项目目录。
    :param refs: 资料列表（表格以外的文件不读）。
    :param template: 本份报告用的模板；给了才能判断「模板需要金额、一个都没读到」。
    :param deadline_ms: 总时限。
    :returns: 信封：读到事实 ok；有跳过的文件 partial；没有表格或没读到 empty。
    """
    started = time.monotonic()
    sizes: dict[str, int] = {}
    files = []
    for ref in refs:
        files.append((ref.file_id, ref.file_name, (lambda r=ref: resolve_project_file(root, r.rel_path).read_bytes())))

    def size(fid: str) -> int:
        if fid not in sizes:
            sizes[fid] = resolve_project_file(root, fid).stat().st_size
        return sizes[fid]

    res = collect_facts(files, deadline_ms=deadline_ms, size=size)
    needed = template_fact_keys(template) if template else []
    warnings: list[WarningItem] = []
    notice = needed_notice(res.facts, needed)
    if notice:
        warnings.append(WarningItem(code="facts_none", level="warn", message=notice))
    if res.timed_out:
        warnings.append(WarningItem(code="facts_timeout", level="warn", message=(
            f"金额事实读取超时，{len(res.timed_out)} 份资料没有读：" + _names(res.timed_out))))
    other_skips = [s for s in res.skipped if s[1] not in res.timed_out]
    if other_skips:
        warnings.append(WarningItem(code="facts_files_skipped", level="warn", message=(
            f"{len(other_skips)} 份表格没有读金额：" + "；".join(f"《{n}》{why}" for _i, n, why in other_skips[:5]))))
    conflicts = [f for f in res.facts if f.get("conflict")]
    if conflicts:
        warnings.append(WarningItem(code="fact_conflict", level="warn", message=(
            "几份资料写的金额不一致，程序不取舍：" + "、".join(f["label"] for f in conflicts))))
    coverage = FileCoverage(files_total=res.files_total, files_used=res.files_read,
                            skipped=[SkippedFile(rel_path=i, file_name=n, reason=why) for i, n, why in res.skipped]
                            ).model_dump()
    elapsed = int((time.monotonic() - started) * 1000)
    data = {"facts": [_manual_fact(f) for f in res.facts], "notes": res.notes, "needed_keys": needed,
            "files_read": res.files_read, "elapsed_ms": elapsed,
            "template_code": template["template_code"] if template else None}
    log.info("报告金额事实：文件 %d 份（表格 %d 份，读了 %d 份），事实 %d 条，耗时 %d ms",
             len(refs), res.files_total, res.files_read, len(res.facts), elapsed)
    if res.skipped:
        # 跳过的文件都已有 facts_timeout 或 facts_files_skipped（warn）
        return partial(data, coverage=coverage, warnings=warnings)
    if res.facts:
        return ok(data, coverage=coverage, warnings=warnings)
    return empty("no_amount_facts" if res.files_total else "no_spreadsheet_files",
                 coverage=coverage, warnings=warnings, data=data)


def _manual_fact(f: dict) -> dict:
    out = manual(dict(f))
    out["candidates"] = [manual(dict(c)) for c in f.get("candidates") or []]
    return out


def facts_list(raw: Any) -> list[dict]:
    """读 ``facts`` 的结果（信封、其 ``data``，或事实列表本身）。

    :param raw: JSON；None 表示没有事实。
    :returns: 事实列表。
    :raises ZtError: 格式不对（``invalid_facts``）。
    """
    if raw is None:
        return []
    data = raw.get("data") if isinstance(raw, dict) and "status" in raw else raw
    facts = data.get("facts") if isinstance(data, dict) else data
    if not isinstance(facts, list) or not all(isinstance(f, dict) and {"id", "key", "label"} <= set(f) for f in facts):
        raise ZtError("invalid_facts", "不是 facts 子命令的结果", hint="传 facts 子命令写出的 result.json")
    return facts


# ================================================================ section_prepare


def _corpus(ctx: dict) -> tuple[list[CorpusFile], list[dict]]:
    corpus = [CorpusFile(index=int(f["index"]), file_id=f["file_id"], file_name=f.get("file_name") or f["file_id"],
                         text=f.get("text") or "", text_source=f.get("text_source"),
                         ocr_risk=bool(f.get("ocr_risk")), quality_suspect=bool(f.get("quality_suspect")),
                         truncated=bool(f.get("truncated")), kind=f.get("kind") or KIND_SOURCE)
              for f in ctx["files"]]
    unreadable = [{"file_id": u.get("file_id"), "file_name": u.get("file_name"), "reason": u.get("reason")}
                  for u in ctx["unreadable"]]
    return corpus, unreadable


def _ref(f: CorpusFile) -> dict:
    return {"index": f.index, "file_id": f.file_id, "file_name": f.file_name, "chars": len(f.text),
            "truncated": f.truncated}


def _used_ref(u: UsedFile) -> dict:
    return {"index": u.file.index, "file_id": u.file.file_id, "file_name": u.file.file_name, "chars": len(u.text),
            "truncated": u.file.truncated, "chars_total": u.chars_total, "blocks_used": u.blocks_used,
            "blocks_total": u.blocks_total}


SKIP_NO_ROOM = "篇幅不够"
SKIP_NOT_RELEVANT = "没有与本章相关的内容"


def _omitted_ref(sel: Selection, f: CorpusFile) -> dict:
    return {"index": f.index, "file_id": f.file_id, "file_name": f.file_name, "chars": len(f.text),
            "truncated": f.truncated, "chars_total": len(f.text), "blocks_used": 0,
            "blocks_total": sel.blocks_total.get(f.index, 0),
            "skip_reason": SKIP_NO_ROOM if sel.scores.get(f.index, 0) > 0 else SKIP_NOT_RELEVANT}


EMPTY_SECTION_CONTENT = "【待补：本章没有可读取的资料，未调用 AI 生成】"


def section_prepare(templates: list[dict], template_code: str, section_code: str, ctx: dict, *,
                    facts: Sequence[dict] = (), confirmed_claims: Sequence[str] = (),
                    project_name: Optional[str] = None) -> Envelope:
    """一章的写作输入：章节定义、选材、提示词、护栏证据。

    :param templates: 模板列表。
    :param template_code: 模板码。
    :param section_code: 章节码。
    :param ctx: context 结果的 ``data``。
    :param facts: facts 结果里的事实列表（只把本章允许的编号、名称、来源写进提示词，不给数值）。
    :param confirmed_claims: 用户确认属实的程序性陈述 key。
    :param project_name: 项目名称（项目说明里的工程名称），只作口径提示。
    :returns: 信封：有可读资料 ok；没有 empty（``no_readable_sources``，本章不写）。
    """
    sec = resolve_section(templates, template_code, section_code)
    spec = spec_of(sec)
    corpus, unreadable = _corpus(ctx)
    selection = select_files_for_section(corpus, spec.rag_query)
    allowed = list(spec.facts_allowed)
    section_facts = [f for f in facts if f["key"] in set(allowed)]
    # 确认事项是整份报告一次问完的：每章都传同一份 key；提示词只写本章的（build_messages 按 spec.claims 过滤），
    # 护栏认全部 key（另一章的「现场踏勘」用户确认过，本章写到也不标）
    known_claims = [k for k in dict.fromkeys(confirmed_claims or ()) if k]
    template_keys = {c["key"] for s in find_template(templates, template_code)["sections"] for c in s["claims"]}
    template_keys |= {c["key"] for c in DEFAULT_CLAIMS}
    messages = build_messages(spec, selection, unreadable=unreadable, confirmed_claims=known_claims,
                              project_name=project_name, facts=section_facts)
    evidence = [{"index": u.file.index, "file_id": u.file.file_id, "file_name": u.file.file_name,
                 "kind": u.file.kind, "text": u.text} for u in selection.used]
    file_names = [f.file_name for f in corpus] + [u.get("file_name") or "" for u in unreadable] \
        + [d.get("file_name") or "" for d in ctx.get("duplicates") or []]
    data: dict[str, Any] = {
        "template_code": template_code, "section_code": spec.code, "title": spec.title, "seq": sec["seq"],
        "prompt_version": sec["prompt_version"],
        "messages": messages,
        "write_rules": {"max_chars": 1800, "cite": "[资料n]", "amount_placeholder": "〔Fn〕",
                        "todo": "【待补：缺什么】"},
        "facts_allowed": allowed,
        "section_fact_ids": [f["id"] for f in section_facts],
        "claims": list(spec.claims),
        "confirmed_claims": known_claims,
        "confirmed_in_section": [c["text"] for c in spec.claims if c["key"] in set(known_claims)],
        "project_name": project_name,
        "gen_prompt": spec.gen_prompt,
        "evidence": evidence,
        "file_names": file_names,
        "corpus": [_ref(f) for f in corpus],
        "unreadable": unreadable,
        "used_files": [_used_ref(u) for u in selection.used],
        "omitted_files": [_omitted_ref(selection, f) for f in selection.omitted],
        "relevant_dropped": {"chars": selection.relevant_dropped_chars, "files": [
            {"index": d.file.index, "file_id": d.file.file_id, "file_name": d.file.file_name, "chars": d.chars}
            for d in selection.relevant_dropped]},
        "selection": {
            "trimmed": [u.file.index for u in selection.trimmed],
            "source_capped": [u.file.index for u in selection.source_capped],
            "relevant_omitted": [f.index for f in selection.relevant_omitted],
        },
    }
    coverage = _section_coverage(corpus, unreadable, selection.used, selection.omitted, selection.scores)
    warnings: list[WarningItem] = []
    unknown = [k for k in known_claims if k not in template_keys]
    if unknown:
        warnings.append(WarningItem(code="unknown_claims", level="warn", message=(
            "这些确认事项的 key 不在这套模板里，没有用上：" + "、".join(unknown)),
            hint="key 取自 templates --template <模板码> 的 claims_to_confirm"))
    sel_warnings = _selection_warnings(selection, unreadable)
    data["selection_warnings"] = [w.model_dump(mode="json") for w in sel_warnings]
    warnings.extend(sel_warnings)
    if not selection.used:
        data["content"] = EMPTY_SECTION_CONTENT
        warnings.append(WarningItem(code="no_readable_sources", level="warn",
                                    message="所选资料都读不出正文，本章不写"))
        return empty("no_readable_sources", coverage=coverage, warnings=warnings, data=data)
    return ok(data, coverage=coverage, warnings=warnings)


def _section_coverage(corpus: Sequence[CorpusFile], unreadable: Sequence[dict], used: Sequence[UsedFile],
                      omitted: Sequence[CorpusFile], scores: dict[int, int]) -> dict:
    skipped = [SkippedFile(rel_path=f.file_id, file_name=f.file_name,
                           reason="超出本章篇幅预算" if scores.get(f.index, 0) > 0 else "没有与本章相关的内容")
               for f in omitted]
    skipped += [SkippedFile(rel_path=u.get("file_id"), file_name=u.get("file_name"),
                            reason=u.get("reason") or "无法读取") for u in unreadable]
    return FileCoverage(files_total=len(corpus) + len(unreadable), files_used=len(used), skipped=skipped).model_dump()


def _selection_warnings(selection: Selection, unreadable: Sequence[dict]) -> list[WarningItem]:
    out: list[WarningItem] = []
    if selection.trimmed:
        out.append(WarningItem(code="files_trimmed", level="info",
                               message=f"{len(selection.trimmed)} 份资料只送入了与本章相关的片段"))
    if selection.relevant_dropped_chars:
        out.append(WarningItem(code="relevant_dropped", level="warn", message=(
            f"有与本章相关的内容因篇幅没送入（约 {selection.relevant_dropped_chars} 字，"
            f"来自：{_names([d.file.file_name for d in selection.relevant_dropped])}）")))
    if selection.source_capped:
        out.append(WarningItem(code="source_capped", level="warn", message=(
            f"{_names([u.file.file_name for u in selection.source_capped])}超过 {REPORT_FILE_MAX_CHARS // 10000} 万字，"
            f"只读了前 {REPORT_FILE_MAX_CHARS // 10000} 万字")))
    if selection.omitted:
        out.append(WarningItem(code="files_omitted", level="warn" if selection.relevant_omitted else "info",
                               message=f"{len(selection.omitted)} 份资料因本章篇幅预算未送入"))
    if unreadable:
        out.append(WarningItem(code="unreadable_files", level="warn",
                               message=f"{len(unreadable)} 份资料读不出正文，本章可能缺内容"))
    return out


def prompt_markdown(data: dict) -> str:
    """prepare 结果 → 给 agent 读的提示词文本（系统提示词 + 用户消息，原样）。

    :param data: :func:`section_prepare` 结果的 ``data``。
    :returns: Markdown 文本。
    """
    system = next(m["content"] for m in data["messages"] if m["role"] == "system")
    user = next(m["content"] for m in data["messages"] if m["role"] == "user")
    return (f"# {data['title']}（{data['template_code']} / {data['section_code']}，prompt_version {data['prompt_version']}）\n\n"
            "## 系统提示词（硬性规则）\n\n" + system + "\n\n## 本章输入\n\n" + user + "\n")


# ================================================================ section_finalize

TRUNCATED_MARK = MARK_TRUNCATED
TRUNCATED_MISSING = "本章内容超出篇幅上限，后面没有写完"

# 可以截断的位置：句末标点（连同紧跟的右引号 / 右括号和挂在句号后面的 [资料n]），或换行
_CUT_POINT_RE = re.compile(r"[。！？；!?;][」』”’）)]*(?:[ \t]*\[资料\s*\d+\])*|\n")


def cut_to_last_sentence(text: str) -> str:
    """把没写完的正文截到最后一个完整句子（或最后一个整行），去掉停在句子中间的半句。

    不落在没闭合的【…】里。一个可截的位置都没有时返回空串（调用方据此判 insufficient）。

    :param text: 正文。
    :returns: 截好的正文。
    """
    t = text or ""
    cut = 0
    for m in _CUT_POINT_RE.finditer(t):
        head = t[:m.end()]
        if head.rfind("【") <= head.rfind("】"):
            cut = m.end()
    return t[:cut].rstrip()


FLAG_WARN_TEXT = {
    "unbacked_number": "处数字在资料原文中找不到，已就地标【待核】",
    "unreadable_claim": "处「未列示 / 未载明」类断言可能只是资料读不出，已标【待核】",
    "unconfirmed_claim": "处程序性陈述未经确认、资料中未见同样说法，已标【待核】",
    "unsupported_negation": "处全称否定的结论资料中没有依据，已标【待核】",
    "transcribed": "处与成稿报告逐字重合 30 字以上，疑似转写",
    "unknown_citation": "处 [资料n] 引用的编号不存在",
    "template_echo": "处照抄了模板写作要求、资料中未见，已标【待核】；整句照抄的去掉了引用",
    "raw_placeholder": "处模板占位符没有替换，已换成【待补】",
    "cited_number": "处数字在所引的资料里找不到，已标【待核】",
    "blank_quantity": "处数量或名称是空的，已标【待核】",
    "unbacked_code": "处清单编码在送入的资料里找不到，已标【待核】",
    "bad_placeholder": "处金额占位符没有程序取数，已换成【待补：金额】",
    "transcribed_amount": "处金额是 AI 从资料里转写的、不是程序取数，已标【待核】",
    "out_of_scope_amount": "处金额不是本章该写的，已标【待核】",
    "fact_conflict": "处金额在几份资料里写的不一致，已列出各处的值并标【待核】",
}


def prepare_data(raw: Any) -> dict:
    """读 ``section_prepare`` 的结果（信封或其 ``data``）。

    :param raw: JSON。
    :returns: ``data`` 字典。
    :raises ZtError: 不是 section_prepare 的结果（``invalid_prepare``）。
    """
    data = raw.get("data") if isinstance(raw, dict) and "status" in raw else raw
    need = {"template_code", "section_code", "title", "prompt_version", "evidence", "gen_prompt", "corpus"}
    if not isinstance(data, dict) or not need <= set(data):
        raise ZtError("invalid_prepare", "不是 section_prepare 子命令的结果",
                      hint="传本章 section_prepare 写出的 result.json")
    return data


def section_finalize(prep: dict, content: Optional[str], *, facts: Sequence[dict] = (),
                     output_truncated: bool = False) -> Envelope:
    """对 agent 写的一章跑护栏、替换金额占位符、判质量态。

    顺序：（没写完时截到句末）→ 护栏（只看 agent 写的字）→〔Fn〕换成单元格原值 → 挂「未写完」标记 → 引用编号核对。

    :param prep: :func:`section_prepare` 结果的 ``data``。
    :param content: agent 写的正文；prepare 为 empty 时忽略。
    :param facts: facts 结果里的事实列表（与 prepare 用的是同一份）。
    :param output_truncated: agent 没写完（篇幅超限）时为 True。
    :returns: 信封：status 即本章质量态（ok / partial / insufficient / empty）。
    :raises ZtError: prepare 有资料而正文为空（``empty_draft``）；事实编号与 prepare 时不一致（``facts_mismatch``）。
    """
    head = {k: prep[k] for k in ("template_code", "section_code", "title", "seq", "prompt_version") if k in prep}
    refs = {k: prep.get(k) for k in ("used_files", "omitted_files", "relevant_dropped", "unreadable")}
    corpus = prep["corpus"]
    unreadable = prep.get("unreadable") or []
    coverage = FileCoverage(
        files_total=len(corpus) + len(unreadable), files_used=len(prep["evidence"]),
        skipped=[SkippedFile(rel_path=f["file_id"], file_name=f["file_name"],
                             reason="超出本章篇幅预算" if f.get("skip_reason") == SKIP_NO_ROOM else "没有与本章相关的内容")
                 for f in prep.get("omitted_files") or []]
        + [SkippedFile(rel_path=u.get("file_id"), file_name=u.get("file_name"), reason=u.get("reason") or "无法读取")
           for u in unreadable]).model_dump()
    if not prep["evidence"]:
        return empty("no_readable_sources", coverage=coverage, warnings=[
            WarningItem(code="no_readable_sources", level="warn", message="所选资料都读不出正文，本章不写")],
            data={**head, **refs, "content": EMPTY_SECTION_CONTENT, "quality": "empty", "flags": [],
                  "amount_refs": [], "cited_files": [], "missing_items": ["本章没有可读取的资料"],
                  "output_truncated": False})
    if content is None or not content.strip():
        raise ZtError("empty_draft", "本章正文是空的", hint="按 prepare 的提示词写完本章，存成文本文件再传 --draft")
    missing_ids = [i for i in prep.get("section_fact_ids") or [] if i not in {f["id"] for f in facts}]
    if missing_ids:
        raise ZtError("facts_mismatch", f"prepare 时给本章的金额事实 {'、'.join(missing_ids)} 不在这份 facts 里",
                      hint="finalize 要传与 section_prepare 同一份 facts 结果")

    if output_truncated:
        content = cut_to_last_sentence(content)
    allowed = set(prep.get("facts_allowed") or [])
    evidence = [EvidenceFile(e["file_id"], e["file_name"], e["text"], e.get("kind") or KIND_SOURCE, index=e["index"])
                for e in prep["evidence"]]
    claims = prep.get("claims") or []
    g = guard_section(content, title=prep["title"], evidence=evidence, unreadable=unreadable,
                      claims=claims, confirmed=prep.get("confirmed_claims") or [], gen_prompt=prep["gen_prompt"],
                      file_names=prep.get("file_names") or [], known_facts=[f["id"] for f in facts],
                      transcribed_amounts=bool(allowed))
    substituted, fact_flags, fact_refs = substitute_facts(g.content, facts, allowed)
    final_content = substituted
    if output_truncated:
        final_content = (substituted + "\n" if substituted else "") + TRUNCATED_MARK

    by_index = {f["index"]: f for f in corpus}
    flags: list[GuardFlag] = list(g.flags) + fact_flags
    cited: list[dict] = []
    for n in cited_indexes(final_content):
        f = by_index.get(n)
        if f is None:
            flags.append(GuardFlag("unknown_citation", f"[资料{n}]", f"引用了不存在的资料编号 {n}"))
        else:
            cited.append({k: f[k] for k in ("index", "file_id", "file_name", "chars", "truncated")})

    warnings: list[WarningItem] = []
    if output_truncated:
        warnings.append(WarningItem(code="output_truncated", level="warn", message="本章内容太长，没有写完"))
    by_kind: dict[str, int] = {}
    for fl in flags:
        by_kind[fl.kind] = by_kind.get(fl.kind, 0) + 1
    for kind, n in by_kind.items():
        warnings.append(WarningItem(code=kind, level="warn", message=f"{n} {FLAG_WARN_TEXT.get(kind, '处待核')}"))
    sel = prep.get("selection") or {}
    dropped = (prep.get("relevant_dropped") or {}).get("chars") or 0
    # 选材的告警在 prepare 时已算好（files_trimmed / relevant_dropped / source_capped / files_omitted / unreadable_files）
    warnings.extend(WarningItem.model_validate(w) for w in prep.get("selection_warnings") or [])

    if meaningful_chars(final_content) < INSUFFICIENT_MIN_CHARS:
        status, reason = "insufficient", "too_little_content"
        warnings.append(WarningItem(code="too_little_content", level="warn",
                                    message=f"去掉待补/待核标注后正文不足 {INSUFFICIENT_MIN_CHARS} 字"))
    elif is_mostly_todo(final_content):
        status, reason = "insufficient", "mostly_todo"
        t = todo_count(final_content)
        warnings.append(WarningItem(code="mostly_todo", level="warn", message=(
            f"正文有 {t} 处【待补】，去掉标记后只有 {meaningful_chars(final_content)} 个字"
            f"（平均每处不足 {MOSTLY_TODO_CHARS_PER_TODO} 字），按资料不足处理")))
    elif output_truncated:
        status, reason = "partial", "output_truncated"
    elif flags or dropped or sel.get("source_capped") or sel.get("relevant_omitted"):
        status, reason = "partial", None
    else:
        status, reason = "ok", None

    missing = list(g.missing_items)
    if not missing and MARK_META in final_content:
        missing.append("资料未载明本段所需信息")
    if output_truncated:
        missing.append(TRUNCATED_MISSING)
    data = {**head, **refs, "content": final_content, "quality": status,
            "flags": [fl.as_dict() for fl in flags],
            "amount_refs": [manual(dict(r)) for r in fact_refs + g.amount_refs],
            "cited_files": cited, "missing_items": missing, "output_truncated": output_truncated,
            "label": section_label({"quality": status, "content": final_content,
                                    "flags": [fl.as_dict() for fl in flags]})}
    if status == "insufficient":
        return insufficient(reason, coverage=coverage, warnings=warnings, data=data)
    if status == "partial":
        return partial(data, coverage=coverage, warnings=warnings, reason=reason)
    return ok(data, coverage=coverage, warnings=warnings)


# ================================================================ export

DEFAULT_TITLE = "报告初稿"


def section_for_export(raw: Any) -> dict:
    """一章 finalize 的结果（信封或其 ``data``）→ 导出用的章节字典。

    :param raw: JSON。
    :returns: ``{title, content, quality, missing_items, flags, seq}``。
    :raises ZtError: 不是 section_finalize 的结果（``invalid_section``）。
    """
    data = raw.get("data") if isinstance(raw, dict) and "status" in raw else raw
    if not isinstance(data, dict) or "content" not in data or "title" not in data:
        raise ZtError("invalid_section", "不是 section_finalize 子命令的结果",
                      hint="传每章 section_finalize 写出的 result.json")
    return {"title": data["title"], "content": data["content"], "quality": data.get("quality") or "",
            "missing_items": data.get("missing_items") or [], "flags": data.get("flags") or [],
            "seq": data.get("seq"), "section_code": data.get("section_code"),
            "template_code": data.get("template_code")}


def export_docx(sections: Sequence[dict], out: Path, *, title: str = DEFAULT_TITLE,
                disclaimer: Optional[str] = None, ctx: Optional[dict] = None,
                facts_result: Optional[dict] = None) -> Envelope:
    """各章 → 带样式、页眉免责声明、附录「资料来源与完成度」的 docx。

    :param sections: :func:`section_for_export` 的结果，按出现顺序。
    :param out: docx 路径（父目录不存在时创建）。
    :param title: 报告标题。
    :param disclaimer: 页眉文字；None 用「AI 初稿，金额未经人工核对，不得直接出具」。
    :param ctx: context 结果的 ``data``（附录的来源文件、读不出的资料、隐藏工作表）。
    :param facts_result: facts 结果的 ``data``（模板需要金额而一个都没读到时，附录写一句提示）。
    :returns: 信封：各章都是 ok 时 ok；否则 partial（列出资料不足 / 含待核的章）。
    :raises ZtError: 没有章节（``invalid_request``）。
    """
    if not sections:
        raise ZtError("invalid_request", "没有章节可导出", hint="传每章 section_finalize 的 result.json")
    appendix: dict[str, Any] = {}
    if ctx is not None:
        appendix["source_files"] = [f["file_name"] for f in ctx.get("files") or []]
        appendix["unreadable_files"] = [f"{u['file_name']}（{u.get('reason') or '无法读取'}）"
                                        for u in ctx.get("unreadable") or []]
        appendix["hidden_sheets"] = list(ctx.get("hidden_sheets") or [])
    if facts_result is not None:
        notice = needed_notice(facts_result.get("facts") or [], facts_result.get("needed_keys") or [])
        if notice:
            appendix["amount_notes"] = [notice]
    blob = build_docx(title, [dict(s) for s in sections], disclaimer=disclaimer, appendix=appendix or None)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    labels = [{"title": s["title"], "quality": s["quality"], "label": section_label(s)} for s in sections]
    data = {"docx": out.as_posix(), "bytes": len(blob), "title": title, "sections": labels,
            "todo_total": sum(todo_count(s["content"]) for s in sections),
            "verify_total": sum(len(re.findall(r"【待核[^】\n]*】", s["content"])) for s in sections)}
    weak = [lb for lb in labels if lb["quality"] != "ok"]
    if weak:
        return partial(data, coverage={"sections_total": len(sections), "sections_ok": len(sections) - len(weak)},
                       warnings=[WarningItem(code="sections_not_ok", level="warn", message=(
                           f"{len(weak)} 章不是完整初稿：" + "；".join(f"{w['title']}（{w['label']}）" for w in weak[:8])))])
    return ok(data, coverage={"sections_total": len(sections), "sections_ok": len(sections)})


def template_summary(templates: list[dict], template_code: Optional[str] = None,
                     docx_manifest: Optional[dict] = None) -> Envelope:
    """列模板，或一套模板的章节、确认事项与需要的金额事实。

    :param templates: 模板列表。
    :param template_code: 给了只看这一套。
    :param docx_manifest: docx 模板登记清单（``data/docx-templates/manifest.json``）。
    :returns: 信封。
    """
    from zt.report.templates import claims_to_confirm

    if template_code is None:
        data = {"templates": [{"template_code": t["template_code"], "name": t["name"], "note_user": t["note_user"],
                               "sections": len(t["sections"])} for t in templates]}
        if docx_manifest is not None:
            data["docx_templates"] = [{"file": d["file"], "pack": d["pack"], "report_templates": d.get("report_templates") or []}
                                      for d in docx_manifest.get("templates") or []]
        return ok(data, coverage={"templates": len(templates)})
    t = find_template(templates, template_code)
    data = {
        "template_code": t["template_code"], "name": t["name"], "note_user": t["note_user"],
        "sections": [{k: s[k] for k in ("code", "title", "seq", "claims", "facts_allowed", "attachment_hints",
                                         "excludes", "prompt_version")} for s in t["sections"]],
        "claims_to_confirm": claims_to_confirm(t),
        "fact_keys": [{"key": k, "label": FACT_LABELS.get(k, k)} for k in template_fact_keys(t)],
    }
    if docx_manifest is not None:
        data["docx_templates"] = [d["file"] for d in docx_manifest.get("templates") or []
                                  if template_code in (d.get("report_templates") or [])]
    return ok(data, coverage={"sections": len(t["sections"])})


__all__ = [
    "EMPTY_SECTION_CONTENT",
    "REPORT_FILE_MAX_CHARS",
    "SYSTEM_PROMPT",
    "SourceRef",
    "build_context",
    "build_facts",
    "context_data",
    "cut_to_last_sentence",
    "export_docx",
    "facts_list",
    "prepare_data",
    "prompt_markdown",
    "section_finalize",
    "section_for_export",
    "section_prepare",
    "source_refs",
    "template_summary",
]
