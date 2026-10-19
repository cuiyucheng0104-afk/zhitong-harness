"""归档：核对 ``成果/`` 与 ``工作/`` 完整，更新 ``项目说明.md`` 与 ``案例索引.md``。

``check_archive`` 只读：返回阻断项（不修好不能归档）、提醒项和要推送的文件清单（含大小与 SHA-256，推送后
与 ``tos_push`` 的回读结果对照）。``apply_archive`` 在检查没有阻断项时改写本机副本：``已出成果`` 小节、
项目说明的 ``状态``、案例索引里本项目那一行；推送由 agent 用 ``tos_push`` 完成。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from zt.common import ZtError
from zt.common.paths import PROJECT_CODE
from zt.inventory.casebook import Casebook, parse_casebook
from zt.inventory.projectdoc import (
    UNDECIDED_VALUES,
    read_project_doc,
    replace_section,
    section_bullets,
    set_front_matter_fields,
    write_text_atomic,
)

RESULT_DIR = "成果"
WORK_DIR = "工作"
PROJECT_DOC = "项目说明.md"
TODO_FILE = "待确认清单.md"
ARCHIVED = "已归档"
_WORK_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}-.+")
_OPEN_BOX = re.compile(r"^\s*[-*]\s*\[ \]", re.M)
_TEMP_PREFIXES = ("~$", ".")
_TEMP_SUFFIXES = (".tmp", ".bak", ".swp")
_HASH_CHUNK = 1 << 20


@dataclass
class Finding:
    """一条核对发现。"""

    code: str
    message: str
    hint: Optional[str] = None
    paths: list[str] = field(default_factory=list)


@dataclass
class ArchiveReport:
    """归档核对结果。

    :ivar blocking: 阻断项：修好才能归档。
    :ivar warnings: 提醒项：不阻断，但要告诉用户。
    :ivar fields: 项目说明的 YAML 头（读不出时为空）。
    :ivar deliverables: ``成果/`` 下的文件（相对项目目录）。
    :ivar listed: 项目说明「已出成果」里登记的路径。
    :ivar work_dirs: ``工作/`` 下的任务目录及文件数。
    :ivar push_list: 要推送的文件：相对项目目录的路径、大小、SHA-256。
    :ivar casebook_row: 案例索引里本项目的行；没有为 None。
    """

    blocking: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    fields: dict[str, Any] = field(default_factory=dict)
    deliverables: list[str] = field(default_factory=list)
    listed: list[str] = field(default_factory=list)
    work_dirs: list[dict[str, Any]] = field(default_factory=list)
    push_list: list[dict[str, Any]] = field(default_factory=list)
    casebook_row: Optional[dict[str, str]] = None


def _files_under(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*") if p.is_file())


def _is_temp(path: Path) -> bool:
    return path.name.startswith(_TEMP_PREFIXES) or path.name.lower().endswith(_TEMP_SUFFIXES)


def sha256_file(path: Path) -> str:
    """流式计算文件 SHA-256。

    :param path: 文件路径。
    :returns: 十六进制摘要。
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base)
    except (ValueError, OSError):
        return False
    return True


def _rel(path: Path, project_dir: Path) -> str:
    return path.relative_to(project_dir).as_posix()


def _clean_bullet(item: str) -> str:
    """登记项可以带反引号和括号备注：`成果/报告.docx`（2026-10-19） → 成果/报告.docx。"""
    m = re.match(r"^`?([^`（(]+?)`?\s*(?:[（(].*)?$", item.strip())
    return (m.group(1) if m else item).strip()


def check_archive(project_dir: Path, *, index_text: Optional[str] = None) -> ArchiveReport:
    """核对项目目录是否可以归档。

    :param project_dir: 项目目录（本机镜像里的 ``项目/<编号>-<工程名>/``）。
    :param index_text: 案例索引全文；None 时不核对案例索引。
    :returns: 核对结果。
    :raises ZtError: 项目目录不存在（``project_dir_not_found``）。
    """
    if not project_dir.is_dir():
        raise ZtError("project_dir_not_found", f"项目目录不存在：{project_dir}")
    base = project_dir.resolve()
    rep = ArchiveReport()

    doc_path = base / PROJECT_DOC
    doc_text = ""
    if not doc_path.is_file():
        rep.blocking.append(Finding("project_doc_missing", "项目目录里没有项目说明.md",
                                    "先用 zt-project 的 project_doc.py draft 生成草稿并补全"))
    else:
        doc_text = doc_path.read_text(encoding="utf-8")
        try:
            rep.fields = read_project_doc(doc_text, require=("项目编号", "工程名称", "咨询类型", "阶段"))
        except ZtError as e:
            rep.blocking.append(Finding(e.code, e.message, e.hint))
        for key in ("咨询类型", "阶段"):
            if rep.fields.get(key) in UNDECIDED_VALUES:
                rep.blocking.append(Finding("project_doc_undecided", f"项目说明的「{key}」还没确认",
                                            "问用户后填进项目说明"))
        code = str(rep.fields.get("项目编号") or "")
        if code and not base.name.startswith(code):
            rep.warnings.append(Finding("code_dir_mismatch", f"项目说明的编号 {code} 与目录名 {base.name} 不一致",
                                        "确认哪个是对的，别让索引和目录对不上"))

    results = [p for p in _files_under(base / RESULT_DIR)]
    temp_results = [p for p in results if _is_temp(p)]
    results = [p for p in results if not _is_temp(p)]
    rep.deliverables = [_rel(p, base) for p in results]
    if not results:
        rep.blocking.append(Finding("no_deliverables", "成果/ 下没有任何成果文件",
                                    "确认成果是否已保存到项目的 成果/ 目录"))
    if temp_results:
        rep.warnings.append(Finding("temp_file_in_deliverables", "成果/ 下有临时文件，不会被登记",
                                    "确认后删除", [_rel(p, base) for p in temp_results]))

    rep.listed = [_clean_bullet(x) for x in section_bullets(doc_text, "已出成果")] if doc_text else []
    missing = [x for x in rep.listed if x and not (base / x).is_file()]
    if missing:
        rep.blocking.append(Finding("deliverable_listed_but_missing", "项目说明「已出成果」登记的文件在 成果/ 里找不到",
                                    "补回文件，或从项目说明里删掉这一行", missing))
    unlisted = [x for x in rep.deliverables if x not in rep.listed]
    if unlisted and rep.listed:
        rep.warnings.append(Finding("deliverable_unlisted", "成果/ 下有文件没有登记在项目说明「已出成果」里",
                                    "归档更新时会补登记", unlisted))

    work_root = base / WORK_DIR
    loose = []
    if work_root.is_dir():
        for child in sorted(work_root.iterdir()):
            if child.is_file():
                if not child.name.startswith("."):
                    loose.append(_rel(child, base))
                continue
            files = [p for p in child.rglob("*") if p.is_file() and not _is_temp(p)]
            entry = {"name": child.name, "files": len(files)}
            rep.work_dirs.append(entry)
            if not _WORK_NAME.match(child.name):
                rep.warnings.append(Finding("work_dir_name", f"工作目录名不是「日期-任务」：{child.name}",
                                            "按 工作/YYYY-MM-DD-任务 命名", [_rel(child, base)]))
            if not files:
                rep.warnings.append(Finding("work_dir_empty", f"工作目录是空的：{child.name}",
                                            "没有产物就不必保留", [_rel(child, base)]))
            todo = child / TODO_FILE
            if todo.is_file():
                n = len(_OPEN_BOX.findall(todo.read_text(encoding="utf-8", errors="replace")))
                if n:
                    entry["open_items"] = n
                    rep.warnings.append(Finding("open_items", f"{child.name}/{TODO_FILE} 还有 {n} 条未勾选的待确认事项",
                                                "逐条问用户；确认不处理的在项目说明里写明遗留", [_rel(todo, base)]))
    if loose:
        rep.warnings.append(Finding("work_loose_files", "工作/ 根下有不在任务目录里的文件",
                                    "放进 工作/YYYY-MM-DD-任务/", loose))

    push = [*results, *[p for p in _files_under(work_root) if not _is_temp(p)]]
    escaping = [p for p in push if p.is_symlink() and not _inside(p, base)]
    if escaping:
        rep.warnings.append(Finding("symlink_outside_project", "有符号链接指向项目目录之外，不会推送",
                                    "把真实文件复制进项目目录", [_rel(p, base) for p in escaping]))
        push = [p for p in push if p not in escaping]
        rep.deliverables = [d for d in rep.deliverables if d not in {_rel(p, base) for p in escaping}]
    if doc_path.is_file():
        push.append(doc_path)
    rep.push_list = [{"rel_path": _rel(p, base), "size": p.stat().st_size, "sha256": sha256_file(p)} for p in push]

    if index_text is not None and rep.fields.get("项目编号"):
        rep.casebook_row = parse_casebook(index_text).find(str(rep.fields["项目编号"]))
        if rep.casebook_row is None:
            rep.warnings.append(Finding("casebook_row_missing", "案例索引里还没有本项目的行", "归档更新时会追加"))
        elif rep.casebook_row.get("工程名", "").strip() != str(rep.fields.get("工程名称") or "").strip():
            rep.warnings.append(Finding("casebook_name_mismatch",
                                        f"案例索引里的工程名「{rep.casebook_row.get('工程名')}」与项目说明不一致",
                                        "确认哪个是对的"))
    return rep


def apply_archive(project_dir: Path, index_path: Path, *, status: str = ARCHIVED,
                  key_metrics: Optional[str] = None, index_template: Optional[str] = None) -> dict[str, Any]:
    """检查通过后改写本机的项目说明与案例索引。

    :param project_dir: 项目目录。
    :param index_path: 本机的案例索引文件路径（先 ``tos_pull`` 到本机）；不存在时从 ``index_template`` 新建。
    :param status: 写进项目说明与案例索引的状态。
    :param key_metrics: 案例索引「关键指标」列；None 保持原值。
    :param index_template: 案例索引模板全文，仅在 ``index_path`` 不存在时用。
    :returns: ``{"dir_name", "code", "files": [{"local_path", "path"}], "casebook_row": {...}, "listed": [...]}``，
        ``path`` 是相对公司前缀的桶内路径。
    :raises ZtError: 检查有阻断项（``not_ready_to_archive``）。
    """
    index_text = index_path.read_text(encoding="utf-8") if index_path.is_file() else (index_template or "")
    rep = check_archive(project_dir, index_text=index_text)
    if rep.blocking:
        raise ZtError("not_ready_to_archive", "；".join(f.message for f in rep.blocking),
                      hint="先修好阻断项再归档（用 check 子命令看明细）")
    base = project_dir.resolve()
    code = str(rep.fields["项目编号"])
    if not PROJECT_CODE.match(code):
        raise ZtError("invalid_project_code", f"项目编号应为 YYYY-NNN：{code!r}")

    doc_path = base / PROJECT_DOC
    text = doc_path.read_text(encoding="utf-8")
    bullets = "\n".join(f"- {p}" for p in rep.deliverables)
    text = replace_section(text, "已出成果", bullets)
    text = set_front_matter_fields(text, {"状态": status})
    write_text_atomic(doc_path, text)

    book: Casebook = parse_casebook(index_text)
    link = f"项目/{base.name}/{RESULT_DIR}/"
    row = {"编号": code, "工程名": str(rep.fields["工程名称"]), "业态": str(rep.fields.get("业态") or ""),
           "规模": str(rep.fields.get("规模") or ""), "咨询类型": str(rep.fields["咨询类型"]),
           "成果链接": link, "状态": status}
    if key_metrics is not None:
        row["关键指标"] = key_metrics
    book.upsert(row)
    write_text_atomic(index_path, book.render())
    return {
        "dir_name": base.name, "code": code, "listed": rep.deliverables,
        "casebook_row": book.find(code),
        "files": [
            {"local_path": str(doc_path), "path": f"项目/{base.name}/{PROJECT_DOC}"},
            {"local_path": str(index_path), "path": "案例索引.md"},
        ],
    }
