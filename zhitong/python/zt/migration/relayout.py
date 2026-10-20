"""旧 NAS 资料 → 桶目录规范的镜像目录（spec §5；§6 第 1–6 条）。

输入：``export-projects.py`` 的 ``projects.json`` / ``files.json``，旧 NAS 的项目根（``<base>/project``）与可选的知识库根。
输出（``--out`` 目录）：

.. code-block:: text

    <out>/mirror/                 与 tos://<bucket>/<公司前缀>/ 同构，upload.sh 上传的就是它
        项目/<编号>-<工程名>/项目说明.md、资料/、图纸/
        知识库/<规范|定额|费率|模板|公司经验>/README.md …
        案例索引.md
    <out>/manifest.json           镜像里每个文件：新路径、旧路径、字节数、sha256；以及删除、未迁移清单
    <out>/整理报告.md              给人读：计数、删除与原因、改名
    <out>/.state/                 编号分配（重跑不改号）与 sha256 缓存

源目录只读（见 :mod:`zt.migration.fsops`）；``--out`` 不能在源目录里，源目录也不能在 ``--out`` 里。镜像文件用硬链接
（同一文件系统，不额外占盘）或复制。重复运行结果相同：已就位的文件不动，生成文件内容相同不重写，镜像里不在本次
计划内的文件删除（只删 ``<out>/mirror`` 里的）。

每个旧文件的去向由显示名决定：显示路径来自 ``project_file.relative_parent_folder`` + ``file_name``，磁盘上的
``(n)`` 后缀与冲突改名按库里的行还原，不按名字猜。清理规则与原因码见 :data:`REASONS`。
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional

from zt.common import WarningItem, WarningLevel, ZtError
from zt.common.paths import project_dir_name
from zt.inventory.casebook import parse_casebook
from zt.inventory.draft import draft_project_doc
from zt.inventory.projectdoc import replace_section, set_front_matter_fields
from zt.inventory.rules import ClassifyEngine, ClassifyInput, CAD_SUBTYPE_DEFAULT, load_rules, system_artifact_kind
from zt.inventory.scan import CONTAINER_ROOTS, InventoryData, load_inventory_data
from zt.migration import fsops
from zt.migration.knowledge import ROOT_KEY, SUBDIRS, KnowledgeMap, render_readme, strip_category_id
from zt.migration.numbering import assign_codes
from zt.sidecar.format import parse_ocr_sidecar
from zt.sidecar.locate import OCR_SIDECAR_SUFFIX, is_sidecar_name
from zt.textextract.decode import decode_text

log = logging.getLogger("zt.migration")

MIRROR_DIR = "mirror"
MANIFEST = "manifest.json"
REPORT = "整理报告.md"
STATE_DIR = ".state"
NUMBERING_STATE = "numbering.json"
HASH_CACHE = "hash-cache.json"
PROJECTS_ROOT = "项目"
KNOWLEDGE_ROOT = "知识库"
CASEBOOK = "案例索引.md"
PROJECT_DOC = "项目说明.md"
DRAWINGS, MATERIALS = "图纸", "资料"
ORPHAN_DIR = "未登记文件"
KNOWLEDGE_GROUP = "知识库"
SEED_TOOLS_DIR = "_tools"           # knowledge-seed 的生成器与快照，不上传（knowledge-seed/README.md「上传」）
MANIFEST_VERSION = 1

# zhitong/python/zt/migration/relayout.py → parents[3] = zhitong/
ZHITONG_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TEMPLATES = ZHITONG_ROOT / "skills" / "zt-project" / "templates"
DEFAULT_RULES = ZHITONG_ROOT / "migration" / "data" / "classify_rules.yaml"
DEFAULT_KNOWLEDGE_MAP = ZHITONG_ROOT / "migration" / "data" / "knowledge_map.yaml"

# 删除原因（spec §6 第 3 条）。键是机器码，值是报告里的说明。
REASONS = {
    "system_junk": "系统生成物（.DS_Store、Thumbs.db、~$ 临时文件、AutoCAD 锁文件、@eaDir 等系统目录）",
    "index_md": "旧系统生成的 INDEX.md",
    "old_format_twin": "旧格式 .doc/.xls，同目录已有同名 .docx/.xlsx",
    "duplicate_sha256": "与保留件内容相同（sha256 一致），保留路径最短的一份",
    "duplicate_row": "两条库记录指向同一个磁盘文件，只迁一份",
    "ocr_placeholder_sidecar": "OCR 旁车一页可用的都没有（整份是「OCR 连续失败」等占位句）",
    "empty_sidecar": "OCR 旁车没有任何文本",
    "sidecar_shadowed": "同一原件的第二份旁车（读取时只认第一份）",
    "sidecar_of_removed_original": "原件已在本次整理中删除，旁车随之删除",
}
NOT_MIGRATED = {
    "missing_source": "库里有记录、NAS 上没有文件",
    "orphan": "NAS 上有文件、库里没有记录（未登记文件；--include-orphans 时迁入 资料/未登记文件/）",
    "history_version": "旧系统保留的历史版本（project_file.history_list），桶开版本控制，不迁历史版本",
    "deleted_row_file": "旧系统已删除（del_flag=1）的记录仍留在 NAS 上的文件",
    "orphan_sidecar": "找不到原件的 OCR 旁车",
    "unencodable_name": "文件名不是合法 UTF-8，无法写进清单（需手工改名后重跑）",
}
DRAWING_EXTS = frozenset({"dwg", "dxf", "dwf"})
DRAWING_CATEGORIES = (frozenset(cat for _kw, cat in CAD_SUBTYPE_DEFAULT) - {"设计说明图"}) | {
    "设计图纸", "初步设计图", "扩初设计图", "招标图纸", "施工图", "竣工图"}
DRAWING_NAME_KEYWORDS = ("图纸", "施工图", "竣工图", "平面图", "立面图", "剖面图", "详图", "大样图", "节点图", "系统图")
_OLD_FORMAT = {"doc": "docx", "xls": "xlsx"}


@dataclass
class Options:
    """一次整理的参数（与 ``relayout.py`` 的命令行参数一一对应）。"""

    export_dir: Path
    nas: Path
    out: Path
    link: str = "hard"
    dry_run: bool = False
    include_orphans: bool = False
    knowledge_roots: list[Path] = field(default_factory=list)
    knowledge_map: Optional[KnowledgeMap] = None
    knowledge_seed: Optional[Path] = None
    templates_dir: Path = DEFAULT_TEMPLATES
    rules_path: Path = DEFAULT_RULES


@dataclass
class Sidecar:
    """一份 OCR 旁车。"""

    src: Path
    old_rel: str
    size: int
    sha256: str
    usable: Optional[bool]          # None = 解码失败，按可用保留
    fmt: str
    verdicts: dict[str, int]
    row_id: Optional[str] = None
    appended: bool = True           # 追加式命名 <原件名>.ocr.txt
    new_rel: Optional[str] = None
    removed: Optional[str] = None
    kept: Optional[str] = None


@dataclass
class Item:
    """一个要迁移的原件（库里的文件行、未登记文件或 knowledge-seed 文件）。"""

    group: str
    src: Path
    old_rel: str
    display_rel: str
    row_id: Optional[str]
    size: int
    sha256: str
    kind: str = "file"              # file / orphan / seed
    db_sha256: Optional[str] = None
    db_size: Optional[tuple[int, int]] = None
    sidecars: list[Sidecar] = field(default_factory=list)
    new_rel: Optional[str] = None
    removed: Optional[str] = None
    kept_by: Optional["Item"] = None
    rename_reasons: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return PurePosixPath(self.display_rel).name

    @property
    def ext(self) -> str:
        n = self.name
        return n.rsplit(".", 1)[-1].lower() if "." in n else ""


@dataclass
class Plan:
    """整理计划：执行前算好，dry-run 只输出它。"""

    outputs: list[dict[str, Any]] = field(default_factory=list)
    deletions: list[dict[str, Any]] = field(default_factory=list)
    not_migrated: list[dict[str, Any]] = field(default_factory=list)
    renames: list[dict[str, Any]] = field(default_factory=list)
    empty_folders: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    knowledge: dict[str, Any] = field(default_factory=dict)
    warnings: list[WarningItem] = field(default_factory=list)
    numbering: dict[str, str] = field(default_factory=dict)
    sources: dict[str, Path] = field(default_factory=dict)       # 镜像相对路径 → 源文件


def _warn(plan: Plan, code: str, message: str, hint: Optional[str] = None) -> None:
    plan.warnings.append(WarningItem(code=code, level=WarningLevel.WARN, message=message, hint=hint))


def _sidecar(src: Path, old_rel: str, hasher: fsops.HashCache, row_id: Optional[str] = None) -> Sidecar:
    size, digest = hasher.sha256(src)
    text = decode_text(src.read_bytes())
    if text is None:
        return Sidecar(src, old_rel, size, digest, None, "undecodable", {}, row_id)
    doc = parse_ocr_sidecar(text)
    return Sidecar(src, old_rel, size, digest, doc.usable, doc.fmt, doc.verdict_counts() if doc.fmt == "paged" else {},
                   row_id)


def is_drawing(item: Item, engine: ClassifyEngine) -> bool:
    """原件是否归 ``图纸/``：DWG/DXF/DWF；或 PDF 按分类规则判成图纸类目，或文件名带图纸词且没有被规则判成别的类目。

    :param item: 原件。
    :param engine: 分类引擎（``classify_rules.yaml``）。
    :returns: 归 ``图纸/`` 时为 True。
    """
    if item.ext in DRAWING_EXTS:
        return True
    if item.ext != "pdf":
        return False
    outcome = engine.classify_one(ClassifyInput(item.display_rel, item.name, item.ext, ancestors=_ancestors(item.display_rel)))
    if outcome.doc_category in DRAWING_CATEGORIES:
        return True
    if outcome.doc_category and outcome.evidence == "filename_rule":
        return False
    return any(k in item.name for k in DRAWING_NAME_KEYWORDS)


def _ancestors(rel: str) -> list[str]:
    parts = [fsops.nfc(p) for p in PurePosixPath(rel).parts[:-1]]
    if parts and parts[0] in CONTAINER_ROOTS:
        parts = parts[1:]
    return list(reversed(parts))


def _attach_sidecars(items: list[Item], pending: list[tuple[str, Path, Optional[str]]], hasher: fsops.HashCache,
                     plan: Plan, group: str, label: str) -> list[Item]:
    """把旁车挂到同目录的原件上；返回找不到原件、但本身有库记录的旁车（按普通文件迁移）。"""
    by_dir: dict[str, dict[str, Item]] = {}
    for it in items:
        d, _, n = it.old_rel.rpartition("/")
        by_dir.setdefault(fsops.nfc(d), {})[fsops.nfc(n)] = it
    leftovers: list[Item] = []
    for rel, src, row_id in pending:
        d, _, n = rel.rpartition("/")
        base = fsops.nfc(n[: -len(OCR_SIDECAR_SUFFIX)])
        siblings = by_dir.get(fsops.nfc(d), {})
        sc = _sidecar(src, rel, hasher, row_id)
        owner = siblings.get(base)
        if owner is None:
            stems = sorted((it for nm, it in siblings.items() if PurePosixPath(nm).stem == base),
                           key=lambda it: (it.ext != "pdf", it.old_rel))
            owner = stems[0] if stems else None
            sc.appended = False
        if owner is not None:
            owner.sidecars.append(sc)
            continue
        if row_id is not None:
            leftovers.append(Item(group, src, rel, rel, row_id, sc.size, sc.sha256))
            continue
        plan.not_migrated.append({"group": group, "label": label, "reason": "orphan_sidecar", "old_path": str(src),
                                  "old_rel": rel, "size": sc.size})
    return leftovers


def _is_system(it: Item) -> bool:
    return (fsops.is_junk_name(it.name) or fsops.in_junk_dir(it.display_rel) or fsops.in_junk_dir(it.old_rel)
            or system_artifact_kind(it.name) == "system_index")


def _remove(item: Item, reason: str, kept: Optional[Item] = None) -> None:
    item.removed = reason
    item.kept_by = kept


def _clean(items: list[Item]) -> None:
    """清理规则（spec §6 第 3 条），按顺序：系统生成物 → INDEX.md → 旧格式双份 → 同 sha256 重复。"""
    for it in items:
        if it.removed or it.kind == "seed":
            continue
        if fsops.is_junk_name(it.name) or fsops.in_junk_dir(it.display_rel) or fsops.in_junk_dir(it.old_rel):
            _remove(it, "system_junk")
        elif system_artifact_kind(it.name) == "system_index":
            _remove(it, "index_md")
    alive = [it for it in items if not it.removed and it.kind != "seed"]
    by_stem: dict[tuple[str, str], dict[str, Item]] = {}
    for it in alive:
        parent = str(PurePosixPath(fsops.nfc(it.display_rel)).parent)
        by_stem.setdefault((parent, PurePosixPath(fsops.nfc(it.name)).stem.casefold()), {}).setdefault(it.ext, it)
    for it in alive:
        twin_ext = _OLD_FORMAT.get(it.ext)
        if twin_ext is None:
            continue
        parent = str(PurePosixPath(fsops.nfc(it.display_rel)).parent)
        twin = by_stem[(parent, PurePosixPath(fsops.nfc(it.name)).stem.casefold())].get(twin_ext)
        if twin is not None and not twin.removed:
            _remove(it, "old_format_twin", twin)
    by_sha: dict[str, list[Item]] = {}
    for it in items:
        if not it.removed and it.kind != "seed":
            by_sha.setdefault(it.sha256, []).append(it)
    for group in by_sha.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda it: (len(it.display_rel), it.display_rel, it.old_rel))
        for dup in group[1:]:
            _remove(dup, "duplicate_sha256", group[0])


def _place(items: list[Item], place: Callable[[Item], str]) -> None:
    """定新路径；同目录下（不分大小写）重名时在文件名后加 `` (2)``、`` (3)``。"""
    taken: set[str] = set()
    for it in sorted((i for i in items if not i.removed), key=lambda i: (i.display_rel, i.old_rel)):
        rel = place(it)
        if fsops.safe_rel(it.display_rel) != fsops.nfc(it.display_rel).strip("/"):
            it.rename_reasons.append("unsafe_chars")
        cand, k = rel, 2
        while cand.casefold() in taken:
            p = PurePosixPath(rel)
            cand = str(p.with_name(f"{p.stem} ({k}){p.suffix}"))
            k += 1
        if cand != rel:
            it.rename_reasons.append("name_collision")
        taken.add(cand.casefold())
        it.new_rel = cand


def _resolve_sidecars(items: list[Item]) -> list[Sidecar]:
    """旁车去向：不可用的删除；原件删了的跟着删，或转给内容相同的保留件；同一原件只留一份。"""
    claims: dict[int, list[tuple[tuple[int, int, str], Sidecar]]] = {}
    out: list[Sidecar] = []
    for it in items:
        for sc in it.sidecars:
            out.append(sc)
            if sc.usable is False:
                sc.removed = "ocr_placeholder_sidecar" if sc.fmt == "paged" else "empty_sidecar"
                continue
            target, own = it, 0
            if it.removed == "duplicate_sha256" and it.kept_by is not None:
                target, own = it.kept_by, 1
            elif it.removed:
                sc.removed = "sidecar_of_removed_original"
                continue
            claims.setdefault(id(target), []).append(((own, 0 if sc.appended else 1, sc.old_rel), sc))
    by_id = {id(it): it for it in items}
    for tid, cands in claims.items():
        target = by_id[tid]
        cands.sort(key=lambda c: c[0])
        first = cands[0][1]
        first.new_rel = f"{target.new_rel}{OCR_SIDECAR_SUFFIX}"
        for _key, sc in cands[1:]:
            sc.removed = "duplicate_sha256" if sc.sha256 == first.sha256 else "sidecar_shadowed"
            sc.kept = first.new_rel
    return out


def _emit(plan: Plan, items: list[Item], sidecars: list[Sidecar], group: str, label: str) -> None:
    for it in items:
        base = {"group": group, "label": label, "old_path": str(it.src), "old_rel": it.old_rel,
                "display_path": it.display_rel, "size": it.size, "sha256": it.sha256, "row_id": it.row_id}
        if it.removed:
            entry = base | {"reason": it.removed}
            if it.kept_by is not None:
                entry["kept"] = it.kept_by.new_rel
            plan.deletions.append(entry)
            continue
        assert it.new_rel is not None
        plan.outputs.append({"path": it.new_rel, "old_path": str(it.src), "old_rel": it.old_rel, "size": it.size,
                             "sha256": it.sha256, "kind": it.kind, "group": group, "row_id": it.row_id})
        plan.sources[it.new_rel] = it.src
        restored = it.kind == "file" and fsops.nfc(it.old_rel) != fsops.nfc(it.display_rel)
        if restored or it.rename_reasons:
            reasons = (["display_name_restored"] if restored else []) + it.rename_reasons
            plan.renames.append({"group": group, "label": label, "old_rel": it.old_rel, "new": it.new_rel,
                                 "reasons": reasons})
        if it.db_sha256 and it.db_sha256 != it.sha256:
            _warn(plan, "sha256_differs_from_db", f"{label}：{it.display_rel} 的 sha256 与库里登记的不同",
                  "库里的 sha256 可能过期；镜像按 NAS 上的实际内容")
        if it.db_size is not None and abs(it.db_size[0] - it.size) > it.db_size[1]:
            _warn(plan, "size_differs_from_db", f"{label}：{it.display_rel} 实际 {it.size} 字节，库里登记约 {it.db_size[0]}")
    for sc in sidecars:
        base = {"group": group, "label": label, "old_path": str(sc.src), "old_rel": sc.old_rel, "size": sc.size,
                "sha256": sc.sha256, "row_id": sc.row_id, "sidecar": True}
        if sc.removed:
            entry = base | {"reason": sc.removed}
            if sc.verdicts:
                entry["verdicts"] = sc.verdicts
            if sc.kept:
                entry["kept"] = sc.kept
            plan.deletions.append(entry)
            continue
        assert sc.new_rel is not None
        if sc.usable is None:
            _warn(plan, "sidecar_undecodable", f"{label}：旁车 {sc.old_rel} 无法解码，原样保留")
        plan.outputs.append({"path": sc.new_rel, "old_path": str(sc.src), "old_rel": sc.old_rel, "size": sc.size,
                             "sha256": sc.sha256, "kind": "sidecar", "group": group, "row_id": sc.row_id})
        plan.sources[sc.new_rel] = sc.src


def _collect_project(project: dict[str, Any], rows: list[dict[str, Any]], deleted: list[dict[str, Any]],
                     opts: Options, hasher: fsops.HashCache, plan: Plan, label: str) -> list[Item]:
    pid = project["id"]
    root = opts.nas / pid
    files = [r for r in rows if r["item_type"] == 0]
    by_disk: dict[str, dict[str, Any]] = {}
    dup_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for r in files:
        key = fsops.nfc(r["disk_path"])
        if key in by_disk:
            dup_rows.append((r, by_disk[key]))
        else:
            by_disk[key] = r
    history = {fsops.nfc(h["disk_path"]) for r in files for h in r.get("history") or []}
    gone = {fsops.nfc(d["disk_path"]) for d in deleted if d.get("item_type", 0) == 0}
    items: list[Item] = []
    pending: list[tuple[str, Path, Optional[str]]] = []
    seen: set[str] = set()
    disk = list(fsops.walk_files(root)) if root.is_dir() else []
    if not root.is_dir():
        _warn(plan, "project_dir_missing", f"{label}：NAS 上没有项目目录 {root}")
    for rel in disk:
        src = root / rel
        if not fsops.encodable(rel):
            plan.not_migrated.append({"group": pid, "label": label, "reason": "unencodable_name",
                                      "old_path": repr(str(src)), "old_rel": repr(rel), "size": src.stat().st_size})
            continue
        key = fsops.nfc(rel)
        row = by_disk.get(key)
        if row is not None:
            seen.add(key)
        if is_sidecar_name(PurePosixPath(rel).name):
            pending.append((rel, src, row["id"] if row else None))
            continue
        if row is not None:
            size, digest = hasher.sha256(src)
            items.append(Item(pid, src, rel, row["display_path"], row["id"], size, digest,
                              db_sha256=row.get("sha256"),
                              db_size=(row["size_approx"], row["size_tolerance"]) if row.get("size_approx") is not None else None))
            continue
        reason = ("history_version" if key in history else "deleted_row_file" if key in gone else None)
        if reason is None:
            orphan = Item(pid, src, rel, rel, None, src.stat().st_size, "", kind="orphan")
            if opts.include_orphans or _is_system(orphan):  # 不迁的未登记文件不读内容
                orphan.size, orphan.sha256 = hasher.sha256(src)
            items.append(orphan)
            continue
        plan.not_migrated.append({"group": pid, "label": label, "reason": reason, "old_path": str(src),
                                  "old_rel": rel, "size": src.stat().st_size})
    for r in files:
        if fsops.nfc(r["disk_path"]) not in seen:
            plan.not_migrated.append({"group": pid, "label": label, "reason": "missing_source", "row_id": r["id"],
                                      "old_path": str(root / r["disk_path"]), "old_rel": r["disk_path"],
                                      "display_path": r["display_path"], "size": None})
    for r, first in dup_rows:
        if fsops.nfc(r["disk_path"]) in seen:
            src = root / r["disk_path"]
            size, digest = hasher.sha256(src)
            plan.deletions.append({"group": pid, "label": label, "reason": "duplicate_row", "row_id": r["id"],
                                   "old_path": str(src), "old_rel": r["disk_path"], "display_path": r["display_path"],
                                   "size": size, "sha256": digest, "kept_row": first["id"]})
    items += _attach_sidecars(items, pending, hasher, plan, pid, label)
    # 未登记的系统生成物留给清理去删（记进删除清单）；其余未登记文件只有 --include-orphans 才迁
    migrate: list[Item] = []
    for it in items:
        if it.kind == "orphan" and not _is_system(it):
            if not opts.include_orphans:
                plan.not_migrated.append({"group": pid, "label": label, "reason": "orphan", "old_path": str(it.src),
                                          "old_rel": it.old_rel, "size": it.size,
                                          "sidecars": [sc.old_rel for sc in it.sidecars]})
                continue
            it.display_rel = f"{ORPHAN_DIR}/{it.old_rel}"
        migrate.append(it)
    return migrate


def _empty_folders(rows: list[dict[str, Any]], kept_rows: set[str], label: str, pid: str) -> list[dict[str, Any]]:
    """库里的文件夹行中，下面没有任何迁入文件的（空目录，不迁移）。"""
    nonempty: set[str] = set()
    for r in rows:
        if r["item_type"] == 0 and r["id"] in kept_rows:
            nonempty.update(str(a) for a in PurePosixPath(fsops.nfc(r["display_path"])).parents)
    return [{"group": pid, "label": label, "display_path": r["display_path"]} for r in rows
            if r["item_type"] == 1 and fsops.nfc(r["display_path"]).strip("/") not in nonempty]


def build_plan(opts: Options) -> Plan:
    """算整理计划，不写镜像。

    :param opts: 参数。
    :returns: 计划。
    :raises ZtError: 输入缺失、目录关系不安全、知识库有未映射的目录等。
    """
    from zt.migration.rows import read_export

    if not opts.nas.is_dir():
        raise ZtError("nas_not_found", f"旧 NAS 项目根不存在：{opts.nas}")
    for src_root in [opts.nas, *opts.knowledge_roots]:
        if fsops.is_within(opts.out, src_root) or fsops.is_within(src_root, opts.out):
            raise ZtError("unsafe_out_dir", f"--out {opts.out} 与源目录 {src_root} 互相包含",
                          hint="镜像目录必须与源目录分开（runbook 用 /opt/zhitong/migration-out）")
    projects_doc, files_doc = read_export(opts.export_dir)
    projects = projects_doc["projects"]
    rows_by_project: dict[str, list[dict[str, Any]]] = {}
    for f in files_doc["files"]:
        rows_by_project.setdefault(f["project_id"], []).append(f)
    deleted_by_project: dict[str, list[dict[str, Any]]] = {}
    for d in files_doc.get("deleted_files") or []:
        deleted_by_project.setdefault(d["project_id"], []).append(d)

    state_dir = opts.out / STATE_DIR
    state_file = state_dir / NUMBERING_STATE
    state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else {}
    codes = assign_codes(projects, state)
    hasher = fsops.HashCache.load(state_dir / HASH_CACHE)
    hasher.path = None if opts.dry_run else state_dir / HASH_CACHE
    engine = ClassifyEngine(load_rules(opts.rules_path))

    plan = Plan()
    plan.numbering = {pid: a.code for pid, a in codes.items()}
    for p in projects:
        a = codes[p["id"]]
        try:
            dirname = project_dir_name(a.code, p["name"])
        except ZtError:
            dirname = f"{a.code}-项目{p['id']}"
            _warn(plan, "project_name_empty_after_sanitize", f"工程名 {p['name']!r} 清洗后为空，目录名用 {dirname}")
        label = dirname
        aliases = [p["alias"]] if p.get("alias") and p["alias"] != a.code else []
        plan.projects.append({"id": p["id"], "code": a.code, "code_origin": a.origin, "dir": f"{PROJECTS_ROOT}/{dirname}",
                              "name": p["name"], "aliases": aliases})
        rows = rows_by_project.get(p["id"], [])
        items = _collect_project(p, rows, deleted_by_project.get(p["id"], []), opts, hasher, plan, label)
        _clean(items)
        prefix = f"{PROJECTS_ROOT}/{dirname}"

        def place(it: Item, prefix: str = prefix) -> str:
            top = DRAWINGS if is_drawing(it, engine) else MATERIALS
            segs = fsops.safe_rel(it.display_rel).split("/")
            if len(segs) > 1 and segs[0] == top:
                segs = segs[1:]
            return f"{prefix}/{top}/" + "/".join(segs)

        _place(items, place)
        sidecars = _resolve_sidecars(items)
        _emit(plan, items, sidecars, p["id"], label)
        kept_rows = {o["row_id"] for o in plan.outputs if o["group"] == p["id"] and o["row_id"]}
        plan.empty_folders += _empty_folders(rows, kept_rows, label, p["id"])
    _plan_knowledge(opts, files_doc.get("knowledge_files") or [], hasher, plan)
    if not plan.outputs:
        raise ZtError("nothing_to_migrate", "整理计划里一个文件都没有",
                      hint="检查 --nas 是否指向旧 NAS 的 project 目录（其下是以 project.id 命名的子目录）")
    if not opts.dry_run:
        hasher.save()
    return plan


def _plan_knowledge(opts: Options, krows: list[dict[str, Any]], hasher: fsops.HashCache, plan: Plan) -> None:
    if not opts.knowledge_roots and opts.knowledge_seed is None:
        return
    kmap = opts.knowledge_map
    if opts.knowledge_roots and kmap is None:
        raise ZtError("knowledge_map_invalid", "给了 --knowledge 但没有知识库映射")
    display = {fsops.nfc(r["disk_path"]): r for r in krows if r["item_type"] == 0}
    items: list[Item] = []
    pending: list[tuple[str, Path, Optional[str]]] = []
    unmapped: dict[str, int] = {}
    sub_of: dict[int, str] = {}
    for root in opts.knowledge_roots:
        if not root.is_dir():
            raise ZtError("knowledge_not_found", f"知识库目录不存在：{root}")
        for rel in fsops.walk_files(root):
            if not fsops.encodable(rel):
                plan.not_migrated.append({"group": KNOWLEDGE_GROUP, "label": KNOWLEDGE_GROUP, "reason": "unencodable_name",
                                          "old_path": repr(str(root / rel)), "old_rel": repr(rel), "size": None})
                continue
            parts = rel.split("/")
            top = parts[0] if len(parts) > 1 else None
            assert kmap is not None
            sub = kmap.resolve(top)
            if sub == "":
                continue
            if sub is None:
                unmapped[top or ROOT_KEY] = unmapped.get(top or ROOT_KEY, 0) + 1
                continue
            src = root / rel
            if is_sidecar_name(parts[-1]):
                pending.append((rel, src, None))
                continue
            row = display.get(fsops.nfc(rel))
            name = row["display_name"] if row else parts[-1]
            disp = "/".join([*(strip_category_id(s) for s in parts[:-1]), name])
            size, digest = hasher.sha256(src)
            it = Item(KNOWLEDGE_GROUP, src, rel, disp, row["id"] if row else None, size, digest)
            sub_of[id(it)] = sub
            items.append(it)
    if unmapped:
        listing = "、".join(f"{k}（{n} 个文件）" for k, n in sorted(unmapped.items()))
        raise ZtError("knowledge_unmapped", f"知识库有未映射的一级目录：{listing}",
                      hint="在 migration/data/knowledge_map.yaml 的 exact 里逐个写明去向（规范/定额/费率/模板/公司经验）或列入 exclude")
    leftovers = _attach_sidecars(items, pending, hasher, plan, KNOWLEDGE_GROUP, KNOWLEDGE_GROUP)
    assert not leftovers  # 知识库旁车没有库记录
    seed_readmes: dict[str, str] = {}
    if opts.knowledge_seed is not None:
        seed = opts.knowledge_seed
        if not seed.is_dir():
            raise ZtError("knowledge_seed_not_found", f"knowledge-seed 目录不存在：{seed}")
        for sub in SUBDIRS:
            sdir = seed / sub
            if not sdir.is_dir():
                continue
            for rel in fsops.walk_files(sdir):
                if SEED_TOOLS_DIR in rel.split("/")[:-1]:
                    continue
                if rel == "README.md":
                    seed_readmes[sub] = (sdir / rel).read_text(encoding="utf-8")
                    continue
                size, digest = hasher.sha256(sdir / rel)
                it = Item(KNOWLEDGE_GROUP, sdir / rel, f"knowledge-seed/{sub}/{rel}", rel, None, size, digest, kind="seed")
                sub_of[id(it)] = sub
                items.append(it)
    _clean(items)
    _place(items, lambda it: f"{KNOWLEDGE_ROOT}/{sub_of[id(it)]}/{fsops.safe_rel(it.display_rel)}")
    sidecars = _resolve_sidecars(items)
    _emit(plan, items, sidecars, KNOWLEDGE_GROUP, KNOWLEDGE_GROUP)
    cats: dict[str, dict[str, int]] = {s: {} for s in SUBDIRS}
    no_text: dict[str, list[str]] = {s: [] for s in SUBDIRS}
    for it in items:
        if it.removed or it.kind == "seed":
            continue
        sub = sub_of[id(it)]
        rel_in_sub = it.new_rel[len(f"{KNOWLEDGE_ROOT}/{sub}/"):] if it.new_rel else it.display_rel
        top = rel_in_sub.split("/")[0] if "/" in rel_in_sub else "(根目录)"
        cats[sub][top] = cats[sub].get(top, 0) + 1
        if it.ext == "pdf" and not any(sc.new_rel for sc in it.sidecars):
            no_text[sub].append(rel_in_sub)
    plan.knowledge = {"roots": [str(r) for r in opts.knowledge_roots], "categories": cats, "no_text_pdfs": no_text,
                      "seed_readmes": seed_readmes, "seed": str(opts.knowledge_seed) if opts.knowledge_seed else None}


# —— 执行 ——

def _project_doc(project: dict[str, Any], entry: dict[str, Any], mirror: Path, template: str, data: InventoryData) -> str:
    created = date.fromisoformat(project["create_time"][:10])
    text = draft_project_doc(mirror / entry["dir"], data, template, code=entry["code"], name=project["name"],
                             today=created)
    eng = project.get("eng_category_label") or ""
    scale = f"{project['scale']} {project.get('scale_unit') or ''}".strip() if project.get("scale") else ""
    status = "已完成" if project.get("project_node") == 2 else "进行中"
    text = set_front_matter_fields(text, {"别名": entry["aliases"], "旧系统项目ID": project["id"], "业态": eng,
                                          "规模": scale, "状态": status})
    # 草稿的「基本信息」表按空值渲染了业态、规模，补成与 YAML 头相同的值
    for key, value in (("业态", eng), ("规模", scale)):
        text = text.replace(f"| {key} |  |", f"| {key} | {value.replace('|', '／')} |", 1)
    rows = [
        ("旧系统项目ID", project["id"]), ("报告书编号", project.get("report_code") or ""),
        ("委托单位", project.get("entrusted_company") or ""), ("工程分类", eng),
        ("项目节点", project.get("project_node_label") or ""),
        ("合约起止", f"{project.get('contract_begin_date') or ''} ~ {project.get('contract_end_date') or ''}".strip(" ~")),
        ("建设规模", scale), ("工程造价（万元）", project.get("total_amount_wan") or ""),
        ("工程地址", project.get("engineering_address") or ""),
    ]
    table = ["| 项 | 值 |", "|---|---|", *(f"| {k} | {str(v).replace('|', '／')} |" for k, v in rows)]
    intro = ("迁移时从旧系统 `project` 表带过来的登记值，从未经人工核对（工程造价、规模尤其如此，needs_manual）；"
             "用到时先对照资料原件。业态取自旧「工程分类」，咨询类型与阶段旧系统没有，写「待确认」。\n\n")
    return replace_section(text, "旧系统登记信息", intro + "\n".join(table))


def _casebook(projects: dict[str, dict[str, Any]], entries: list[dict[str, Any]], template: str) -> str:
    book = parse_casebook(template)
    for e in sorted(entries, key=lambda e: e["code"]):
        p = projects[e["id"]]
        scale = f"{p['scale']} {p.get('scale_unit') or ''}".strip() if p.get("scale") else ""
        book.upsert({"编号": e["code"], "工程名": p["name"], "业态": p.get("eng_category_label") or "", "规模": scale,
                     "咨询类型": "待确认", "关键指标": "", "成果链接": "",
                     "状态": "已完成" if p.get("project_node") == 2 else "进行中"})
    return book.render()


def generated_paths(plan: Plan) -> list[str]:
    """计划里会生成的文件（镜像相对路径）。

    :param plan: 计划。
    :returns: 项目说明、案例索引与知识库各子目录 README 的路径。
    """
    paths = [f"{e['dir']}/{PROJECT_DOC}" for e in plan.projects] + [CASEBOOK]
    if plan.knowledge:
        paths += [f"{KNOWLEDGE_ROOT}/README.md"] + [f"{KNOWLEDGE_ROOT}/{sub}/README.md" for sub in SUBDIRS]
        paths += [f"{d}/README.md" for d in sorted(_knowledge_dirs_without_readme(plan))]
    return paths


def _knowledge_dirs_without_readme(plan: Plan) -> dict[str, list[dict[str, Any]]]:
    """``知识库/<子目录>/`` 之下、迁入了旧文件却没有 README.md 的目录 → 直接放在其中的文件。

    zt-knowledge 的 ``check_knowledge.py`` 要求知识库每个目录都有 README.md；knowledge-seed 的目录自带，
    旧系统迁入的分类目录由这里补一份。
    """
    outputs = [o for o in plan.outputs if o["path"].startswith(f"{KNOWLEDGE_ROOT}/")]
    have = {str(PurePosixPath(o["path"]).parent) for o in outputs if PurePosixPath(o["path"]).name == "README.md"}
    dirs: dict[str, list[dict[str, Any]]] = {}
    for o in outputs:
        parent = PurePosixPath(o["path"]).parent
        if len(parent.parts) < 3:
            continue  # 直接在 知识库/<子目录>/ 下：子目录 README 另行生成
        dirs.setdefault(str(parent), []).append(o)
        for d in parent.parents:
            if len(d.parts) < 3:
                break
            dirs.setdefault(str(d), [])
    return {d: files for d, files in dirs.items() if d not in have}


def _knowledge_dir_readme(path: str, files: list[dict[str, Any]]) -> str:
    olds = sorted({str(PurePosixPath(o["old_rel"]).parent) for o in files if o["kind"] != "seed"})
    lines = [f"# {PurePosixPath(path).name}", "",
             "旧系统知识库迁入的目录（迁移整理时生成本说明）。文件名已还原为旧系统的显示名；去向规则与各分类文件数见上级子目录 README 的「旧系统迁入」一节。"]
    if olds:
        lines += ["", "旧位置（相对旧知识库目录）：", ""] + [f"- `{o}/`" for o in olds]
    return "\n".join(lines) + "\n"


KNOWLEDGE_ROOT_README = """# 知识库

企业知识库，对所有项目可见（spec §5）。子目录各有 README.md 说明内容与来源：

- `规范/`：标准、规范、清单计价与计量规范、清单编码资料
- `定额/`：消耗量定额、计价定额及说明
- `费率/`：取费标准、费率表、其他费用定额
- `模板/`：报告、函件与表格模板
- `公司经验/`：工作中形成的口径与经验，由 agent 回写

目录规范、条目格式与回写纪律见 zt-knowledge skill。初版内容来自 knowledge-seed 与旧系统知识库迁移。
"""


def generated_files(plan: Plan, opts: Options) -> dict[str, str]:
    """生成文件（项目说明、案例索引、知识库 README）的全文；项目说明要扫描镜像，必须在原件就位后调用。

    :param plan: 计划。
    :param opts: 参数。
    :returns: ``{镜像相对路径: 全文}``。
    """
    from zt.migration.rows import read_export

    projects_doc, _files = read_export(opts.export_dir)
    projects = {p["id"]: p for p in projects_doc["projects"]}
    mirror = opts.out / MIRROR_DIR
    data = dataclasses.replace(load_inventory_data(), engine=ClassifyEngine(load_rules(opts.rules_path)))
    doc_tpl = (opts.templates_dir / PROJECT_DOC).read_text(encoding="utf-8")
    book_tpl = (opts.templates_dir / CASEBOOK).read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for e in plan.projects:
        (mirror / e["dir"]).mkdir(parents=True, exist_ok=True)
        out[f"{e['dir']}/{PROJECT_DOC}"] = _project_doc(projects[e["id"]], e, mirror, doc_tpl, data)
    out[CASEBOOK] = _casebook(projects, plan.projects, book_tpl)
    if plan.knowledge:
        k = plan.knowledge
        out[f"{KNOWLEDGE_ROOT}/README.md"] = KNOWLEDGE_ROOT_README
        for d, files in _knowledge_dirs_without_readme(plan).items():
            out[f"{d}/README.md"] = _knowledge_dir_readme(d, files)
        for sub in SUBDIRS:
            out[f"{KNOWLEDGE_ROOT}/{sub}/README.md"] = render_readme(
                sub, k["seed_readmes"].get(sub), k["categories"][sub],
                ["/".join(Path(r).parts[-2:]) for r in k["roots"]], k["no_text_pdfs"][sub])
    return out


def execute(plan: Plan, opts: Options) -> dict[str, Any]:
    """按计划写镜像、生成文件、删掉镜像里的陈旧文件，写 manifest、整理报告与编号状态。

    :param plan: :func:`build_plan` 的结果。
    :param opts: 参数（``dry_run`` 必须为 False）。
    :returns: 执行统计。
    """
    from zt.migration.report import render_report

    assert not opts.dry_run
    mirror = opts.out / MIRROR_DIR
    mirror.mkdir(parents=True, exist_ok=True)
    stats = {"kept": 0, "linked": 0, "copied": 0, "replaced": 0, "generated_written": 0, "stale_removed": 0}
    for o in plan.outputs:
        # knowledge-seed 在代码目录里，通常与 NAS 不在同一文件系统，总是复制（几 MB）
        mode = "copy" if o["kind"] == "seed" else opts.link
        stats[fsops.place_file(plan.sources[o["path"]], mirror / o["path"], mode)] += 1
    gen = generated_files(plan, opts)
    gen_entries = []
    for rel, text in sorted(gen.items()):
        if fsops.write_text_if_changed(mirror / rel, text):
            stats["generated_written"] += 1
        data = text.encode("utf-8")
        gen_entries.append({"path": rel, "old_path": None, "size": len(data),
                            "sha256": fsops.bytes_sha256(data), "kind": "generated", "group": None, "row_id": None})
    planned = {o["path"] for o in plan.outputs} | set(gen)
    stale = []
    for rel in fsops.walk_files(mirror):
        if rel not in planned:
            (mirror / rel).unlink()
            stale.append(rel)
    for dirpath, _dirs, _files in sorted(os.walk(mirror, topdown=False), key=lambda t: -len(t[0])):
        d = Path(dirpath)
        if d != mirror and not any(d.iterdir()):
            d.rmdir()
    stats["stale_removed"] = len(stale)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "generated_by": "zt.migration.relayout",
        "mirror": str(mirror), "nas": str(opts.nas), "export_dir": str(opts.export_dir), "link": opts.link,
        "include_orphans": opts.include_orphans,
        "knowledge_roots": [str(r) for r in opts.knowledge_roots],
        "knowledge_seed": str(opts.knowledge_seed) if opts.knowledge_seed else None,
        "projects": plan.projects,
        "files": sorted(plan.outputs + gen_entries, key=lambda e: e["path"]),
        "deletions": plan.deletions, "not_migrated": plan.not_migrated, "renames": plan.renames,
        "empty_folders": plan.empty_folders, "stale_removed": stale,
    }
    (opts.out / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    fsops.write_text_if_changed(opts.out / REPORT, render_report(plan, manifest, stats))
    state_dir = opts.out / STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / NUMBERING_STATE).write_text(json.dumps(plan.numbering, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                             encoding="utf-8")
    return stats


def summarize(plan: Plan) -> dict[str, Any]:
    """计划的计数摘要。

    :param plan: 计划。
    :returns: 计数字典。
    """
    by_reason: dict[str, int] = {}
    for d in plan.deletions:
        by_reason[d["reason"]] = by_reason.get(d["reason"], 0) + 1
    nm: dict[str, int] = {}
    for d in plan.not_migrated:
        nm[d["reason"]] = nm.get(d["reason"], 0) + 1
    kinds: dict[str, int] = {}
    for o in plan.outputs:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
    return {
        "projects": len(plan.projects),
        "outputs": len(plan.outputs), "output_bytes": sum(o["size"] for o in plan.outputs), "outputs_by_kind": kinds,
        "drawings": sum(1 for o in plan.outputs if f"/{DRAWINGS}/" in o["path"] and o["kind"] != "sidecar"),
        "deletions": len(plan.deletions), "deletion_bytes": sum(d["size"] or 0 for d in plan.deletions),
        "deletions_by_reason": by_reason, "not_migrated_by_reason": nm,
        "renames": len(plan.renames), "empty_folders": len(plan.empty_folders),
    }
