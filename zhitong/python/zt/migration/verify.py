"""镜像校验（spec §6 第 7 条）：镜像与 ``files.json``、NAS 源文件、``manifest.json`` 对账。

逐项检查（任何一项不过都以退出码 2 结束，完整问题清单写到 ``<out>/verify-problems.json``）：

1. manifest 里的每个文件在镜像里存在、字节数一致、sha256 一致（``--quick`` 时只比字节数）；镜像里没有 manifest 之外的文件；
2. 按项目对账：``files.json`` 里每条有效文件行要么迁入镜像，要么在删除清单里（带原因），要么登记为「NAS 上没有」
   （``--accept-missing-source`` 时降为告警）；文件数与总字节（NAS 上现量）= 迁入 + 删除；
3. 每个项目有 ``项目说明.md``，YAML 头可解析，``项目编号`` 与 ``旧系统项目ID`` 与分配结果一致；
4. ``案例索引.md`` 每个项目恰好一行。

一个文件都没有时不报成功（``no_files``）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zt.common import Envelope, WarningItem, WarningLevel, ZtError, ok
from zt.inventory.casebook import parse_casebook
from zt.inventory.projectdoc import read_project_doc
from zt.migration import fsops
from zt.migration.relayout import CASEBOOK, MANIFEST, MIRROR_DIR, PROJECT_DOC
from zt.migration.rows import read_export

PROBLEMS_FILE = "verify-problems.json"
_SHOWN = 20


def verify(export_dir: Path, nas: Path, out: Path, *, quick: bool = False,
           accept_missing_source: bool = False) -> Envelope:
    """对账。

    :param export_dir: ``projects.json`` / ``files.json`` 所在目录。
    :param nas: 旧 NAS 项目根（只读）。
    :param out: relayout 的 ``--out``（含 ``mirror/`` 与 ``manifest.json``）。
    :param quick: 只比字节数，不重算镜像文件的 sha256。
    :param accept_missing_source: 「库里有、NAS 上没有」只告警不判失败。
    :returns: 成功时的结果信封（``ok``）。
    :raises ZtError: 有任何不一致（``verify_failed``），或镜像为空（``no_files``）、输入缺失。
    """
    mpath = out / MANIFEST
    mirror = out / MIRROR_DIR
    if not mpath.is_file() or not mirror.is_dir():
        raise ZtError("manifest_not_found", f"找不到 {mpath} 或 {mirror}", hint="先运行 relayout.py（不带 --dry-run）")
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    projects_doc, files_doc = read_export(export_dir)
    problems: list[dict[str, Any]] = []
    warnings: list[WarningItem] = []

    def bad(code: str, **detail: Any) -> None:
        problems.append({"code": code, **detail})

    files = manifest["files"]
    if not any(f["kind"] != "generated" for f in files):
        raise ZtError("no_files", "镜像里一个迁入的文件都没有，不能判为校验通过")

    # 1. 镜像与 manifest
    listed = {f["path"]: f for f in files}
    for rel, f in listed.items():
        p = mirror / rel
        if not p.is_file():
            bad("mirror_file_missing", path=rel)
            continue
        size = p.stat().st_size
        if size != f["size"]:
            bad("mirror_size_mismatch", path=rel, expected=f["size"], actual=size)
        elif not quick and fsops.file_sha256(p) != f["sha256"]:
            bad("mirror_sha256_mismatch", path=rel)
    for rel in fsops.walk_files(mirror):
        if rel not in listed:
            bad("mirror_extra_file", path=rel)

    # 2. 按项目对账
    outputs_by_row: dict[str, dict[str, Any]] = {f["row_id"]: f for f in files if f.get("row_id")}
    deleted_by_row: dict[str, dict[str, Any]] = {d["row_id"]: d for d in manifest["deletions"] if d.get("row_id")}
    missing_by_row = {d["row_id"]: d for d in manifest["not_migrated"] if d.get("reason") == "missing_source"}
    rows_by_project: dict[str, list[dict[str, Any]]] = {}
    for r in files_doc["files"]:
        if r["item_type"] == 0:
            rows_by_project.setdefault(r["project_id"], []).append(r)
    per_project: list[dict[str, Any]] = []
    entries = {e["id"]: e for e in manifest["projects"]}
    missing_total = 0
    for p in projects_doc["projects"]:
        pid = p["id"]
        rows = rows_by_project.get(pid, [])
        n_src = b_src = n_out = b_out = n_del = b_del = n_missing = 0
        for r in rows:
            src = nas / pid / r["disk_path"]
            present = src.is_file()
            if r["id"] in missing_by_row:
                if present:
                    bad("missing_source_now_present", project=pid, row_id=r["id"], path=r["disk_path"])
                n_missing += 1
                continue
            if not present:
                bad("source_file_missing_unreported", project=pid, row_id=r["id"], path=r["disk_path"])
                continue
            n_src += 1
            b_src += src.stat().st_size
            if r["id"] in outputs_by_row:
                n_out += 1
                b_out += outputs_by_row[r["id"]]["size"]
            elif r["id"] in deleted_by_row:
                n_del += 1
                b_del += deleted_by_row[r["id"]]["size"] or 0
            else:
                bad("row_unaccounted", project=pid, row_id=r["id"], path=r["display_path"])
        if n_src != n_out + n_del:
            bad("project_count_mismatch", project=pid, source=n_src, migrated=n_out, deleted=n_del)
        if b_src != b_out + b_del:
            bad("project_bytes_mismatch", project=pid, source=b_src, migrated=b_out, deleted=b_del)
        missing_total += n_missing
        if n_missing and not accept_missing_source:
            bad("missing_source", project=pid, rows=n_missing,
                hint="NAS 上缺这些文件；确认后用 --accept-missing-source 重跑校验")
        # 3. 项目说明
        e = entries.get(pid)
        if e is None:
            bad("project_not_in_manifest", project=pid)
            continue
        doc = mirror / e["dir"] / PROJECT_DOC
        if not doc.is_file():
            bad("project_doc_missing", project=pid, path=f"{e['dir']}/{PROJECT_DOC}")
        else:
            try:
                fields = read_project_doc(doc.read_text(encoding="utf-8"), require=("项目编号", "工程名称"))
            except ZtError as ex:
                bad("project_doc_invalid", project=pid, path=f"{e['dir']}/{PROJECT_DOC}", message=ex.message)
            else:
                if fields.get("项目编号") != e["code"] or str(fields.get("旧系统项目ID")) != pid:
                    bad("project_doc_mismatch", project=pid, code=fields.get("项目编号"),
                        old_id=fields.get("旧系统项目ID"), expected_code=e["code"])
        per_project.append({"id": pid, "code": e["code"], "dir": e["dir"], "source_files": n_src, "source_bytes": b_src,
                            "migrated": n_out, "deleted": n_del, "missing_source": n_missing})
    if missing_total and accept_missing_source:
        warnings.append(WarningItem(code="missing_source_accepted", level=WarningLevel.WARN,
                                    message=f"{missing_total} 条库记录在 NAS 上没有文件（已按 --accept-missing-source 放行）"))

    # 4. 案例索引
    cb = mirror / CASEBOOK
    if not cb.is_file():
        bad("casebook_missing", path=CASEBOOK)
    else:
        try:
            book = parse_casebook(cb.read_text(encoding="utf-8"))
        except ZtError as ex:
            bad("casebook_invalid", message=ex.message)
        else:
            codes = [r.get("编号", "") for r in book.rows]
            for e in manifest["projects"]:
                if codes.count(e["code"]) != 1:
                    bad("casebook_mismatch", code=e["code"], rows=codes.count(e["code"]))

    orphans = sum(1 for d in manifest["not_migrated"] if d["reason"] == "orphan")
    if orphans:
        warnings.append(WarningItem(code="orphans_not_migrated", level=WarningLevel.INFO,
                                    message=f"{orphans} 个 NAS 上的未登记文件没有迁入（见整理报告「未迁移清单」）"))
    if problems:
        (out / PROBLEMS_FILE).write_text(json.dumps(problems, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        shown = "；".join(f"{p['code']} {p.get('path') or p.get('project') or ''}".strip() for p in problems[:_SHOWN])
        more = f"；另有 {len(problems) - _SHOWN} 项" if len(problems) > _SHOWN else ""
        raise ZtError("verify_failed", f"校验发现 {len(problems)} 处不一致：{shown}{more}",
                      hint=f"完整清单见 {out / PROBLEMS_FILE}")
    stale = out / PROBLEMS_FILE
    if stale.is_file():
        stale.unlink()
    kept = [f for f in files if f["kind"] != "generated"]
    return ok({
        "projects": per_project,
        "mirror_files": len(kept), "mirror_bytes": sum(f["size"] for f in kept),
        "generated_files": len(files) - len(kept),
        "deletions": len(manifest["deletions"]), "not_migrated": len(manifest["not_migrated"]),
        "sha256_checked": not quick,
    }, coverage={"projects": len(per_project), "files_checked": len(listed)}, warnings=warnings)
