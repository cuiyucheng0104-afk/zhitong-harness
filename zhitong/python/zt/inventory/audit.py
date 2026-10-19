"""清单齐备度核查（规则层）：按证据定级，只有强证据进「已备」。

来源：/home/user/zhitong-cost-ai/engine-service/app/engine/audit_check.py（``check_checklist_graded``，
旧 WS13-B 定级逻辑）。冲突表数据在 data/audit_evidence_rules.yaml。

改动：类目折算表与冲突表由调用方传入（:class:`AuditRules`），不在导入时读文件；除此以外判定逻辑未改。

语义：

- 一个清单项「命中」= 至少一份文件的类目（经 :meth:`~zt.inventory.vocab.Vocab.canonical` 折算后）等于该项的类目，
  或落在该项的别名集里；清单项带阶段、文件也带阶段时两者必须一致，任一侧缺省阶段则只按类目匹配并记为降级
  （``stage_checked=False``）；
- 证据定级 ``grade_of``：confirmed（人工确认过或来源是 manual）> strong（``evidence == filename_rule``）>
  weak（其余，包括缺 evidence 的行）。**不按 needs_manual 定级**；
- 冲突表：strong 命中的目录段撞上冲突词（进度款 / 产值 / 付款…）降为 weak，并记 ``conflict``；
- 按项汇总：最高级别 confirmed / strong → ``covered``；只有 weak → ``pending``（待确认，不进分子）；
  没有命中 → 必备项进 ``missing``，重要项进 ``advisory``，可选项进 ``optional_missing``；
- 系统生成物不当证据，计入 ``ignored_system``；同一 ``doc_key`` 只算一份文档；
- ``coverage_rate`` 只统计必备项；没有必备项或没有可用输入时为 ``None``，不是 1.0。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from zt.inventory.data import read_yaml
from zt.inventory.rules import system_artifact_kind
from zt.inventory.vocab import Vocab

GRADE_CONFIRMED = "confirmed"
GRADE_STRONG = "strong"
GRADE_WEAK = "weak"
_GRADE_RANK = {GRADE_CONFIRMED: 3, GRADE_STRONG: 2, GRADE_WEAK: 1}

LEVEL_REQUIRED = "required"
LEVEL_IMPORTANT = "important"
LEVEL_OPTIONAL = "optional"


@dataclass(frozen=True)
class AuditRules:
    """核查用的两张数据表。

    :ivar vocab: 类目折算表。
    :ivar conflicts: 清单口径类目 → 目录段里出现即冲突的词。
    """

    vocab: Vocab = field(default_factory=Vocab)
    conflicts: dict[str, tuple[str, ...]] = field(default_factory=dict)


def load_conflicts(path: Path) -> dict[str, tuple[str, ...]]:
    """加载 audit_evidence_rules.yaml 的冲突表。

    :param path: 文件路径。
    :returns: ``{清单类目: (冲突词, ...)}``。
    """
    raw = read_yaml(path)
    return {str(k): tuple(str(w) for w in (v or []) if str(w).strip())
            for k, v in (raw.get("conflicts") or {}).items()}


def requirement_level(item: dict) -> str:
    """清单项的必备级别：``required`` / ``important`` / ``optional``。

    :param item: 清单项。
    :returns: 级别；认不出的值按可选处理。
    """
    v = str(item.get("requirement_level", "")).strip().lower()
    if v in ("required", "must", "★", "1"):
        return LEVEL_REQUIRED
    if v in ("important", "2"):
        return LEVEL_IMPORTANT
    return LEVEL_OPTIONAL


def grade_of(f: dict) -> str:
    """一条文件记录的证据级别。只看来源、确认状态与 evidence，不看 needs_manual。

    :param f: 文件记录。
    :returns: ``confirmed`` / ``strong`` / ``weak``。
    """
    if str(f.get("confirm_state") or "") == "confirmed" or str(f.get("source") or "") == "manual":
        return GRADE_CONFIRMED
    if str(f.get("evidence") or "") == "filename_rule":
        return GRADE_STRONG
    return GRADE_WEAK


def _file_label(f: dict) -> str:
    return str(f.get("file_name") or PurePosixPath(str(f.get("rel_path") or "")).name or "")


def _dir_segments(f: dict) -> list[str]:
    """冲突判定用的目录段：优先 ``ancestors``；没传时退回 ``rel_path`` 的目录。"""
    anc = f.get("ancestors")
    if isinstance(anc, list):
        return [str(a) for a in anc if a]
    path = str(f.get("rel_path") or "")
    return [p for p in PurePosixPath(path.replace("\\", "/")).parent.parts if p not in ("", "/", ".")]


def _conflict(f: dict, item_category: Optional[str], rules: AuditRules) -> Optional[dict]:
    words = rules.conflicts.get(rules.vocab.canonical(item_category) or "")
    if not words:
        return None
    for seg in _dir_segments(f):
        for w in words:
            if w in seg:
                return {"word": w, "segment": seg,
                        "message": f"文件在「{seg}」目录下（含「{w}」），不像本项要的那一份"}
    return None


def _doc_key(f: dict) -> str:
    return str(f.get("doc_key") or f.get("file_id") or "")


def _hit_entry(f: dict, grade: str, conflict: Optional[dict]) -> dict:
    e = {
        "file_id": f.get("file_id"),
        "file_name": _file_label(f) or None,
        "rel_path": f.get("rel_path"),
        "doc_key": _doc_key(f),
        "doc_category": f.get("doc_category"),
        "cost_stage": f.get("cost_stage"),
        "source": f.get("source"),
        "evidence": f.get("evidence"),
        "confirm_state": f.get("confirm_state"),
        "grade": grade,
    }
    if conflict:
        e["conflict"] = conflict
    return e


def check_checklist_graded(files: list[dict], checklist: list[dict], rules: AuditRules) -> dict[str, Any]:
    """按证据定级的核查。

    :param files: 文件记录，键见 :func:`grade_of` / :func:`_hit_entry`（``doc_category``、``cost_stage``、
        ``evidence``、``ancestors``、``doc_key``、``rel_path``…）。
    :param checklist: 清单项（``item_id``、``stage_code``、``doc_category``、``aliases``、``requirement_level``…）。
    :param rules: 类目折算表与冲突表。
    :returns: 核查结果，键：``missing`` / ``pending`` / ``advisory`` / ``optional_missing`` / ``covered`` /
        ``coverage_rate`` / ``coverage_rate_upper`` / ``required_total`` / ``required_covered`` /
        ``required_pending`` / ``important_total`` / ``optional_total`` / ``degraded_matches`` /
        ``input_empty`` / ``input_stats``。
    """
    canon = rules.vocab.canonical
    usable: list[dict] = []
    ignored_system = ignored_rejected = ignored_uncategorized = 0
    for f in files or []:
        if system_artifact_kind(_file_label(f)) or system_artifact_kind(PurePosixPath(str(f.get("rel_path") or "")).name):
            ignored_system += 1
            continue
        if str(f.get("confirm_state") or "") == "rejected":
            ignored_rejected += 1
            continue
        if not f.get("doc_category"):
            ignored_uncategorized += 1
            continue
        usable.append(f)

    missing: list[dict] = []
    pending: list[dict] = []
    advisory: list[dict] = []
    optional_missing: list[dict] = []
    covered: list[dict] = []
    degraded_count = 0
    required_total = required_covered = required_pending = 0
    important_total = optional_total = 0

    for item in checklist or []:
        level = requirement_level(item)
        want_cat = item.get("doc_category")
        # 两侧都折算成清单口径再比：分类器产出「建筑图纸」「结算审定稿」这类细分类目，清单只认「施工图」「审定单」
        names = {canon(n) for n in {want_cat, *(item.get("aliases") or [])} if n}
        stage_code = item.get("stage_code")
        # 阶段校验按文件记：True 两侧都有阶段且一致；False 只有一侧有阶段、校验被跳过（降级）；
        # None 两侧都没有，无从校验（不算降级）。
        by_doc: dict[str, dict] = {}
        twins: dict[str, list] = {}
        for f in usable:
            if canon(f.get("doc_category")) not in names:
                continue
            f_stage = f.get("cost_stage")
            if stage_code and f_stage:
                if f_stage != stage_code:
                    continue
                stage_checked: Optional[bool] = True
            elif stage_code or f_stage:
                stage_checked = False
            else:
                stage_checked = None
            grade = grade_of(f)
            conflict = None
            if grade == GRADE_STRONG:
                conflict = _conflict(f, want_cat, rules)
                if conflict:
                    grade = GRADE_WEAK
            entry = _hit_entry(f, grade, conflict)
            entry["stage_checked"] = stage_checked
            key = entry["doc_key"]
            twins.setdefault(key, []).append(f.get("file_id"))
            prev = by_doc.get(key)
            if prev is None or _GRADE_RANK[grade] > _GRADE_RANK[prev["grade"]]:
                by_doc[key] = entry
        # 同一 doc_key（b.doc + b.docx）只算一份文档；代表条目取级别最高的那份
        hits = sorted(by_doc.values(), key=lambda e: (-_GRADE_RANK[e["grade"]], str(e.get("file_name") or "")))
        for e in hits:
            others = [i for i in twins.get(e["doc_key"], []) if i != e["file_id"]]
            if others:
                e["twin_file_ids"] = others
        best = hits[0]["grade"] if hits else None

        if level == LEVEL_REQUIRED:
            required_total += 1
        elif level == LEVEL_IMPORTANT:
            important_total += 1
        else:
            optional_total += 1

        if not hits:
            if level == LEVEL_REQUIRED:
                missing.append({**item, "matched_files": []})
            elif level == LEVEL_IMPORTANT:
                advisory.append({**item, "matched_files": []})
            else:
                optional_missing.append({**item, "matched_files": []})
            continue

        # matched_by 只看撑起这一项结论的命中：已备看 confirmed / strong，待确认看全部
        support = [e for e in hits if e["grade"] != GRADE_WEAK] if best in (GRADE_CONFIRMED, GRADE_STRONG) else hits
        degraded = all(e["stage_checked"] is False for e in support)
        matched_by = "category_only" if degraded else "stage_and_category"
        if degraded:
            degraded_count += 1
        row = {**item, "matched_files": hits, "matched_docs": len(hits), "matched_total": len(hits),
               "matched_by": matched_by, "best_grade": best}
        if best in (GRADE_CONFIRMED, GRADE_STRONG):
            covered.append(row)
            if level == LEVEL_REQUIRED:
                required_covered += 1
        else:
            pending.append(row)
            if level == LEVEL_REQUIRED:
                required_pending += 1

    # 分母为 0 → 没有比例可言：返回 None 而不是 1.0
    if required_total == 0:
        rate = upper = None
    else:
        rate = round(required_covered / required_total, 4)
        upper = round((required_covered + required_pending) / required_total, 4)
    input_empty = not usable
    if input_empty:
        rate = upper = None
    return {
        "missing": missing,
        "pending": pending,
        "advisory": advisory,
        "optional_missing": optional_missing,
        "covered": covered,
        "coverage_rate": rate,
        "coverage_rate_upper": upper,
        "required_total": required_total,
        "required_covered": required_covered,
        "required_pending": required_pending,
        "important_total": important_total,
        "optional_total": optional_total,
        "degraded_matches": degraded_count,
        "input_empty": input_empty,
        "input_stats": {
            "files_received": len(files or []),
            "files_used": len(usable),
            "ignored_system": ignored_system,
            "ignored_rejected": ignored_rejected,
            "ignored_uncategorized": ignored_uncategorized,
            "checklist_items": len(checklist or []),
        },
    }
