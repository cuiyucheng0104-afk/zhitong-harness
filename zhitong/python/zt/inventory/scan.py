"""资料盘点：扫描项目目录，按文件名与目录核对资料清单，只报缺件，不给文件打标签。

流程：``scan_files`` 列出项目目录里的资料文件 → :class:`~zt.inventory.rules.ClassifyEngine` 按文件名与祖先目录
判类目（结果只在内存里喂给核查，不写出为文件标签）→ :func:`~zt.inventory.audit.check_checklist_graded`
按咨询类型与阶段口径核对清单 → :func:`inventory` 组装结果。

盘点只看文件名与目录，不读正文：命中强证据（文件名规则）算「已备」，只有弱证据（裸词、继承目录语境）算
「待确认」，需要 agent 打开候选文件确认；文件名不规范的资料会漏判，所以结果附带「没有判出类目的文件」，
让 agent 在报缺件之前先到这些文件里找一遍。
"""
from __future__ import annotations

import json
import os
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from zt.common import ZtError
from zt.common.paths import to_rel_posix
from zt.inventory import data as datafiles
from zt.inventory.audit import AuditRules, check_checklist_graded, load_conflicts
from zt.inventory.checklist import Checklist, load_checklist
from zt.inventory.rules import RULES_VERSION, ClassifyEngine, ClassifyInput, load_rules, system_artifact_kind
from zt.inventory.vocab import load_vocab

# 项目目录结构（spec §5）里的容器根：它们是目录规范，不是资料语境，不进祖先链
CONTAINER_ROOTS = ("资料", "图纸", "成果")
# 项目目录里不属于客户资料的顶层目录：我们自己的中间产物
DEFAULT_EXCLUDE_TOP = ("工作",)
# 项目根目录下的入口文件
ENTRY_FILES = ("项目说明.md", "案例索引.md")
_NOISE_NAMES = frozenset({".ds_store", "thumbs.db", "desktop.ini"})
_WORD_FAMILY = frozenset({"doc", "docx", "docm", "rtf"})
_SHEET_FAMILY = frozenset({"xls", "xlsx", "xlsm"})
MAX_UNCLASSIFIED_DEFAULT = 100


@dataclass(frozen=True)
class InventoryData:
    """盘点用的全部数据：分类引擎、清单、核查用折算表与冲突表。"""

    engine: ClassifyEngine
    checklist: Checklist
    audit_rules: AuditRules
    data_dir: Path


def load_inventory_data(override: Optional[str | Path] = None) -> InventoryData:
    """从 zt-project 数据目录加载盘点数据。

    :param override: 数据目录；None 时按 :func:`zt.inventory.data.data_dir` 的顺序定位。
    :returns: 盘点数据。
    :raises ZtError: 数据目录不完整或文件内容非法。
    """
    base = datafiles.data_dir(override)
    vocab = load_vocab(base / datafiles.CATEGORY_MAP)
    return InventoryData(
        engine=ClassifyEngine(load_rules(base / datafiles.CLASSIFY_RULES)),
        checklist=load_checklist(base / datafiles.CHECKLIST),
        audit_rules=AuditRules(vocab, load_conflicts(base / datafiles.EVIDENCE_RULES)),
        data_dir=base,
    )


@dataclass
class ScannedFile:
    """项目目录里的一个文件。

    :ivar rel_path: 相对项目目录、``/`` 分隔。
    :ivar ancestors: 祖先目录链，由近及远，已剔容器根。
    :ivar doc_key: 同一份文档的键（doc 与 docx、xls 与 xlsx 的转换件共用）。
    """

    rel_path: str
    name: str
    ext: str
    ancestors: list[str]
    doc_key: str


@dataclass
class ScanResult:
    """目录扫描结果。"""

    files: list[ScannedFile] = field(default_factory=list)
    ignored_system: int = 0
    ignored_temp: int = 0
    skipped_symlinks: list[str] = field(default_factory=list)
    stripped_prefix: Optional[str] = None  # 清单模式下去掉的前缀


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _doc_key(rel_dir: str, name: str, ext: str) -> str:
    stem = name[: -(len(ext) + 1)] if ext else name
    family = "word" if ext in _WORD_FAMILY else "sheet" if ext in _SHEET_FAMILY else ext
    return f"{rel_dir}/{stem}#{family}" if family in ("word", "sheet") else f"{rel_dir}/{name}"


def _is_temp_name(name: str) -> bool:
    return name.startswith(".") or name.startswith("~$") or name.lower() in _NOISE_NAMES


def _make_file(out: ScanResult, dir_parts: tuple[str, ...], name: str) -> bool:
    """按目录段与文件名登记一个文件；返回 False 表示它被计数跳过（系统生成物 / 临时文件）。"""
    if _is_temp_name(name):
        out.ignored_temp += 1
        return False
    rel = "/".join((*dir_parts, name))
    if system_artifact_kind(name) is not None:
        out.ignored_system += 1
        return False
    parts = [_nfc(p) for p in dir_parts]
    ancestors_top_down = parts[1:] if parts and parts[0] in CONTAINER_ROOTS else parts
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    out.files.append(ScannedFile(
        rel_path=rel, name=name, ext=ext,
        ancestors=list(reversed(ancestors_top_down)),
        doc_key=_doc_key("/".join(parts), name, ext),
    ))
    return True


def scan_files(project_dir: Path, *, exclude_top: tuple[str, ...] = DEFAULT_EXCLUDE_TOP) -> ScanResult:
    """列出项目目录里的资料文件。

    跳过：点开头的文件与目录、Office 临时锁文件（``~$``）、``.DS_Store`` 等；顶层 ``exclude_top`` 目录（默认
    ``工作``）；项目根目录的 ``项目说明.md`` / ``案例索引.md``；系统生成物（``INDEX.md``、``.ocr.txt`` 旁车）只计数。
    不跟随目录符号链接；解析后落在项目目录之外的文件符号链接不读，记入 ``skipped_symlinks``。

    :param project_dir: 项目目录。
    :param exclude_top: 顶层排除目录名。
    :returns: 扫描结果，文件按路径排序。
    :raises ZtError: 项目目录不存在（``project_dir_not_found``）。
    """
    if not project_dir.is_dir():
        raise ZtError("project_dir_not_found", f"项目目录不存在：{project_dir}")
    base = project_dir.resolve()
    out = ScanResult()
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        rel_dir_parts = tuple(_nfc(p) for p in PurePosixPath(Path(dirpath).relative_to(base).as_posix()).parts)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                             and not (not rel_dir_parts and _nfc(d) in exclude_top))
        for fname in sorted(filenames):
            name = _nfc(fname)
            if not rel_dir_parts and name in ENTRY_FILES:
                continue
            full = Path(dirpath) / fname
            if full.is_symlink() and not _is_temp_name(name) and system_artifact_kind(name) is None:
                try:
                    full.resolve().relative_to(base)
                except (ValueError, OSError):
                    out.skipped_symlinks.append("/".join((*rel_dir_parts, name)))
                    continue
            _make_file(out, rel_dir_parts, name)
    out.files.sort(key=lambda f: f.rel_path)
    return out


def parse_listing(text: str) -> list[str]:
    """解析文件清单文本：每行一个路径，或 JSON（字符串数组、``{"path": …}`` 数组、``tos_ls`` 的 ``{"files": […]}``，
    也可以是由多页 JSON 拼成的数组）。

    :param text: 清单全文。
    :returns: 路径列表（未规范化）。
    :raises ZtError: JSON 形态认不出（``listing_invalid``）。
    """
    body = text.lstrip("\ufeff").strip()
    if not body:
        return []
    if body[0] not in "[{":
        return [ln.strip() for ln in body.splitlines() if ln.strip()]
    try:
        raw = json.loads(body)
    except json.JSONDecodeError as e:
        raise ZtError("listing_invalid", f"文件清单不是合法 JSON：第 {e.lineno} 行 {e.msg}") from e
    items = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for it in items:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict) and isinstance(it.get("files"), list):
            out.extend(parse_listing(json.dumps(it["files"], ensure_ascii=False)))
        elif isinstance(it, dict) and isinstance(it.get("path"), str):
            out.append(it["path"])
        else:
            raise ZtError("listing_invalid", f"文件清单里有认不出的条目：{str(it)[:80]}")
    return out


def files_from_listing(paths: list[str], *, strip_prefix: Optional[str] = None,
                       exclude_top: tuple[str, ...] = DEFAULT_EXCLUDE_TOP) -> ScanResult:
    """从文件清单（如 ``tos_ls`` 递归列出的路径）登记资料文件，过滤规则与 :func:`scan_files` 相同。

    清单不必拉到本机：盘点只看文件名与目录，图纸（``tos_pull`` 目录拉取默认跳过）也能参与。

    :param paths: 路径列表，``/`` 或 ``\\`` 分隔；以 ``/`` 结尾的目录条目忽略。
    :param strip_prefix: 要去掉的前缀（如 ``项目/2026-001-某工程/``）；None 时，若全部路径都以 ``项目/<目录>/``
        开头就自动去掉这两段。
    :param exclude_top: 顶层排除目录名。
    :returns: 扫描结果，文件按路径排序。
    :raises ZtError: 路径含 ``..`` 或是绝对路径（``invalid_path``）；去前缀后有路径不在前缀之下（``listing_prefix_mismatch``）。
    """
    entries = [p for p in (x.strip() for x in paths) if p and not p.endswith(("/", "\\"))]
    rels = [to_rel_posix(p) for p in entries]
    if strip_prefix is None and rels and all(r.startswith("项目/") and r.count("/") >= 2 for r in rels):
        tops = {"/".join(r.split("/")[:2]) for r in rels}
        if len(tops) > 1:
            raise ZtError("listing_multiple_projects", f"清单里有多个项目目录：{'、'.join(sorted(tops)[:3])}",
                          hint="一次盘点一个项目；用 tos_ls 只列这个项目的目录")
        strip_prefix = tops.pop()
    if strip_prefix:
        pre = to_rel_posix(strip_prefix).rstrip("/") + "/"
        bad = [r for r in rels if not r.startswith(pre)]
        if bad:
            raise ZtError("listing_prefix_mismatch", f"清单里有路径不在前缀 {pre} 之下：{bad[0]}")
        rels = [r[len(pre):] for r in rels]
    out = ScanResult(stripped_prefix=strip_prefix or None)
    for rel in sorted(set(rels)):
        parts = tuple(_nfc(p) for p in rel.split("/"))
        dir_parts, name = parts[:-1], parts[-1]
        if any(d.startswith(".") for d in dir_parts) or (dir_parts and dir_parts[0] in exclude_top):
            continue
        if not dir_parts and name in ENTRY_FILES:
            continue
        _make_file(out, dir_parts, name)
    out.files.sort(key=lambda f: f.rel_path)
    return out


def _slim_item(it: dict[str, Any]) -> dict[str, Any]:
    return {k: it.get(k) for k in ("item_id", "stage_code", "doc_category", "item_name",
                                    "requirement_level", "aliases", "signoff") if k in it}


def _with_files(row: dict[str, Any]) -> dict[str, Any]:
    files = [{"rel_path": e["rel_path"], "grade": e["grade"],
              **({"conflict": e["conflict"]["message"]} if e.get("conflict") else {})}
             for e in row["matched_files"]]
    return {**_slim_item(row), "best_grade": row["best_grade"], "matched_by": row["matched_by"], "files": files}


def inventory(project_dir: Optional[Path], data: InventoryData, *, consulting_type: Optional[str],
              stage: Optional[str], all_stages: bool = False,
              max_unclassified: int = MAX_UNCLASSIFIED_DEFAULT,
              scan: Optional[ScanResult] = None, project_name: Optional[str] = None) -> dict[str, Any]:
    """盘点一个项目的资料齐备情况。

    :param project_dir: 项目目录；``scan`` 已给出时可为 None。
    :param data: 盘点数据。
    :param consulting_type: 咨询类型（代码或名称）；None 取通用清单。
    :param stage: 阶段码；与 ``all_stages`` 二选一。
    :param all_stages: 显式按全部阶段核查。
    :param max_unclassified: 结果里最多列出多少个没判出类目的文件。
    :param scan: 已登记好的文件（如 :func:`files_from_listing` 的结果）；None 时扫描 ``project_dir``。
    :param project_name: 结果里的项目名；缺省取 ``project_dir`` 的目录名。
    :returns: 结果字典：``scope`` / ``summary`` / ``missing`` / ``pending`` / ``advisory`` / ``covered`` /
        ``optional_missing`` / ``unclassified_files`` / ``input_stats`` / ``rules_version`` 与内部用的 ``audit``。
    :raises ZtError: 既没选阶段也没要求全部阶段（``stage_required``）；阶段或咨询类型非法；目录不存在。
    """
    if stage and all_stages:
        raise ZtError("stage_conflict", "--stage 与 --all-stages 不能同时给")
    if not stage and not all_stages:
        raise ZtError("stage_required", "没有指定阶段：不猜阶段，也不默认按全部阶段核查",
                      hint="读项目说明里的「阶段」传 --stage；确实要按全部阶段才加 --all-stages")
    checklist = data.checklist
    code = checklist.resolve_consulting_type(consulting_type)
    scope = checklist.stage_scope(None if all_stages else stage)
    pick = checklist.pick(code, scope.stage_codes)

    if scan is None:
        if project_dir is None:
            raise ZtError("project_dir_required", "需要项目目录或文件清单")
        scan = scan_files(project_dir)
    records: list[dict[str, Any]] = []
    unclassified: list[str] = []
    non_cost: list[str] = []
    for f in scan.files:
        o = data.engine.classify_one(ClassifyInput(
            file_id=f.rel_path, file_name=f.name, file_ext=f.ext, ancestors=list(f.ancestors)))
        if o.doc_category is None:
            # 黑名单确定跳过(施工日志、监理月报…)是判定不是没判出:不进「没判出类目」名单
            (non_cost if o.disposition == "skip" and not o.needs_manual else unclassified).append(f.rel_path)
        records.append({
            "file_id": f.rel_path, "rel_path": f.rel_path, "file_name": f.name, "doc_key": f.doc_key,
            "ancestors": list(f.ancestors), "doc_category": o.doc_category, "cost_stage": o.cost_stage,
            "evidence": o.evidence,
        })
    audit = check_checklist_graded(records, pick.items, data.audit_rules)

    req_missing = len(audit["missing"])
    return {
        "project": project_name or (project_dir.resolve().name if project_dir else None),
        "scope": {
            "consulting_type": code,
            "consulting_type_name": checklist.consulting_types.get(code) if code and code != "ALL" else None,
            "checklist_set": pick.checklist_set,
            "checklist_fallback": pick.fallback,
            "selected_stage": scope.selected_stage,
            "stage_codes": list(scope.stage_codes),
            "stage_basis": scope.basis,
        },
        "summary": {
            "required_total": audit["required_total"],
            "required_covered": audit["required_covered"],
            "required_pending": audit["required_pending"],
            "required_missing": req_missing,
            "coverage_rate": audit["coverage_rate"],
            "coverage_rate_upper": audit["coverage_rate_upper"],
            "important_missing": len(audit["advisory"]),
            "optional_missing": len(audit["optional_missing"]),
            "degraded_matches": audit["degraded_matches"],
        },
        "missing": [_slim_item(r) for r in audit["missing"]],
        "pending": [_with_files(r) for r in audit["pending"]],
        "advisory": [_slim_item(r) for r in audit["advisory"]],
        "covered": [_with_files(r) for r in audit["covered"]],
        "optional_missing": [_slim_item(r) for r in audit["optional_missing"]],
        "unclassified_files": unclassified[:max_unclassified],
        "unclassified_total": len(unclassified),
        "input_stats": {
            **audit["input_stats"],
            "files_listed": len(scan.files),
            "ignored_system": scan.ignored_system,
            "ignored_temp": scan.ignored_temp,
            "skipped_non_cost": len(non_cost),
            "skipped_symlinks": len(scan.skipped_symlinks),
        },
        "rules_version": RULES_VERSION,
        "audit": {"input_empty": audit["input_empty"]},
    }
