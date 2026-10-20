"""旧库 ``project`` / ``project_file`` / ``knowledge_file`` 行的读取与规范化，生成 ``projects.json`` 与 ``files.json``。

表结构依据旧仓 ``后端/sql/schema-tian_gong_intelligence-20260821.sql``（``project``、``project_file``）与
``后端/sql/knowledge-file-schema-20260823.sql``（``knowledge_file``）。路径约定依据旧仓
``ProjectFileServiceImpl``：项目文件在 ``<base>/project/<project.id>/<disk_relative_parent_folder>/<disk_file_name>``，
两个父目录字段都带前导分隔符，项目根是 ``/``。``file_info`` 是 Hutool ``FileUtil.readableFileSize`` 的可读串
（如 ``66.81 KB``），不是精确字节数，只能作近似对照；精确字节数由 relayout / verify 在 NAS 上现量。

输入两种：mysqldump 文件（:mod:`zt.migration.dump`），或 ``runbook.md`` 里那条 ``mysql -N -B -r`` 命令导出的
JSON Lines（每行一个 JSON 对象，``table`` 字段写表名）。两种输入规范化后的结果相同。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Optional

from zt.common import ZtError
from zt.migration.dump import iter_dump_rows, open_dump

TABLES = ("project", "project_file", "knowledge_file")
FORMAT_VERSION = 1

# project.eng_category 的取值（列注释原文）
ENG_CATEGORY = {
    1: "房屋建筑工程", 2: "安装工程", 3: "市政工程", 4: "园林绿化工程", 5: "古建筑工程", 6: "水利工程",
    7: "公路工程", 8: "电力工程", 9: "人防工程", 10: "石油工程", 11: "通信工程", 12: "其他工程",
}
PROJECT_NODE = {1: "进行中", 2: "已完成"}
FILE_SOURCE = {0: "模板", 1: "上传", 2: "AI审阅模块生成"}
_SIZE_RE = re.compile(r"^\s*([\d,]+(?:\.\d+)?)\s*([KMGTPE]?)i?B\s*$", re.I)
_UNITS = {"": 0, "K": 1, "M": 2, "G": 3, "T": 4, "P": 5, "E": 6}


def parse_readable_size(text: Optional[str]) -> Optional[tuple[int, int]]:
    """解析 ``66.81 KB`` 这类可读大小。

    :param text: ``file_info`` 原文。
    :returns: ``(近似字节数, 允许误差字节数)``；不是大小写法（如文件夹的「3 个文件」）时为 None。
    """
    m = _SIZE_RE.match(text or "")
    if not m:
        return None
    power = 1024 ** _UNITS[m.group(2).upper()]
    value = Decimal(m.group(1).replace(",", ""))
    # 两位小数四舍五入：误差不超过 0.005 个单位，再留 1 字节
    return int(value * power), int(power * Decimal("0.005")) + 1


def _int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(Decimal(str(v)))
    except InvalidOperation:
        return None


def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v)
    return s if s.strip() else None


def _num(v: Any) -> Optional[str]:
    """十进制列保留为字符串，避免二进制浮点误差。"""
    if v is None or v == "":
        return None
    try:
        return str(Decimal(str(v)))
    except InvalidOperation:
        return None


def _datetime(v: Any) -> Optional[str]:
    """``2025-03-04 10:00:00`` / ``2025-03-04 10:00:00.000000`` → ``2025-03-04T10:00:00``；日期列 → ``2025-03-04``。"""
    s = _str(v)
    if s is None:
        return None
    s = s.strip().replace("T", " ")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    m = re.match(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", s)
    return f"{m.group(1)}T{m.group(2)}" if m else s


def _json_value(v: Any) -> Any:
    if v is None or isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return None


def join_rel(parent: Optional[str], name: str) -> str:
    """父目录字段 + 文件名 → 项目内相对路径（``/`` 分隔，无前导分隔符）。

    :param parent: ``relative_parent_folder`` 或 ``disk_relative_parent_folder``（``/``、``/a/b``、空）。
    :param name: 文件名。
    :returns: 如 ``a/b/x.pdf``；父目录是根时为 ``x.pdf``。
    """
    parts = [p for p in re.split(r"[\\/]+", parent or "") if p not in ("", ".")]
    return "/".join([*parts, name])


def normalize_project(row: dict[str, Any]) -> dict[str, Any]:
    """``project`` 一行 → ``projects.json`` 的一项（金额、规模所在对象带 ``needs_manual: true``）。

    :param row: 原始行。
    :returns: 规范化后的项目。
    :raises ZtError: 缺 ``id``、``name`` 或 ``create_time``（``project_row_invalid``）。
    """
    pid, name, created = _str(row.get("id")), _str(row.get("name")), _datetime(row.get("create_time"))
    if not pid or not name or not created:
        raise ZtError("project_row_invalid", f"project 行缺 id/name/create_time：{ {k: row.get(k) for k in ('id', 'name', 'create_time')} }")
    eng = _int(row.get("eng_category"))
    node = _int(row.get("project_node"))
    return {
        "id": pid,
        "name": name,
        "sys_company_code": _str(row.get("sys_company_code")),
        "alias": _str(row.get("report_code")),
        "report_code": _str(row.get("report_code")),
        "entrusted_company": _str(row.get("entrusted_company")),
        "eng_category": eng,
        "eng_category_label": ENG_CATEGORY.get(eng) if eng is not None else None,
        "project_node": node,
        "project_node_label": PROJECT_NODE.get(node) if node is not None else None,
        "create_time": created,
        "modify_time": _datetime(row.get("modify_time")),
        "contract_begin_date": _datetime(row.get("contract_begin_date")),
        "contract_end_date": _datetime(row.get("contract_end_date")),
        "total_amount_wan": _num(row.get("total_amount")),
        "scale": _num(row.get("scale")),
        "scale_unit": _str(row.get("scale_unit_code")),
        "engineering_address": _str(row.get("engineering_address")),
        "folder_path": _str(row.get("folder_path")),
        "del_flag": _int(row.get("del_flag")) or 0,
        "needs_manual": True,
    }


def normalize_file(row: dict[str, Any], *, owner_key: str = "project_id") -> dict[str, Any]:
    """``project_file`` / ``knowledge_file`` 一行 → ``files.json`` 的一项。

    :param row: 原始行。
    :param owner_key: 归属列：``project_id``（项目文件）或 ``category_id``（知识库文件）。
    :returns: 规范化后的文件行。
    :raises ZtError: 缺 ``id``、归属列、``file_name`` 或 ``disk_file_name``（``file_row_invalid``）。
    """
    fid, owner = _str(row.get("id")), _str(row.get(owner_key))
    name, disk_name = _str(row.get("file_name")), _str(row.get("disk_file_name"))
    if not fid or owner is None or not name or not disk_name:
        raise ZtError("file_row_invalid", f"{owner_key} 文件行缺 id/归属/file_name/disk_file_name：id={fid!r}")
    display_parent = row.get("relative_parent_folder") or "/"
    disk_parent = row.get("disk_relative_parent_folder") or "/"
    size = parse_readable_size(_str(row.get("file_info")))
    history = []
    for h in _json_value(row.get("history_list")) or []:
        if isinstance(h, dict) and h.get("diskFileName"):
            history.append({
                "disk_path": join_rel(h.get("diskRelativeParentFolder"), str(h["diskFileName"])),
                "sha256": _str(h.get("sha256")),
                "size_text": _str(h.get("fileInfo")),
            })
    source = _int(row.get("source"))
    return {
        "id": fid,
        owner_key: owner,
        "item_type": _int(row.get("item_type")) or 0,
        "display_parent": str(display_parent),
        "disk_parent": str(disk_parent),
        "display_name": name,
        "disk_name": disk_name,
        "display_path": join_rel(str(display_parent), name),
        "disk_path": join_rel(str(disk_parent), disk_name),
        "suffix": _str(row.get("suffix")),
        "size_text": _str(row.get("file_info")),
        "size_approx": size[0] if size else None,
        "size_tolerance": size[1] if size else None,
        "sha256": (_str(row.get("sha256")) or "").lower() or None,
        "del_flag": _int(row.get("del_flag")) or 0,
        "source": source,
        "source_label": FILE_SOURCE.get(source) if source is not None else None,
        "sys_company_code": _str(row.get("sys_company_code")),
        "history": history,
    }


def iter_json_rows(path: Path) -> Iterable[tuple[Optional[str], str, dict[str, Any]]]:
    """读 JSON 行文件：JSON Lines（每行带 ``table``），或 ``{"project": [...], "project_file": [...]}``。

    :param path: 文件路径。
    :returns: ``(None, 表名, 行)`` 迭代器。
    :raises ZtError: 文件不存在（``rows_not_found``）或格式不对（``rows_invalid``）。
    """
    if not path.is_file():
        raise ZtError("rows_not_found", f"找不到行文件：{path}")
    text = path.read_text(encoding="utf-8").lstrip("﻿")
    try:
        whole = json.loads(text)
    except ValueError:
        whole = None
    if isinstance(whole, dict) and any(k in whole for k in TABLES):
        for table in TABLES:
            for row in whole.get(table) or []:
                yield None, table, row
        return
    for no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            raise ZtError("rows_invalid", f"{path} 第 {no} 行不是 JSON：{e}") from e
        if not isinstance(row, dict) or row.get("table") not in TABLES:
            raise ZtError("rows_invalid", f"{path} 第 {no} 行缺 table 字段或表名不认识（应为 {'/'.join(TABLES)}）")
        yield None, row.pop("table"), row


@dataclass
class ExportResult:
    """导出结果。"""

    projects: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    deleted_files: list[dict[str, Any]] = field(default_factory=list)
    knowledge_files: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    databases: list[str] = field(default_factory=list)
    company_codes: list[str] = field(default_factory=list)


def export_rows(rows: Iterable[tuple[Optional[str], str, dict[str, Any]]], *,
                database: Optional[str] = None, company_code: Optional[str] = None) -> ExportResult:
    """规范化三张表的行，跳过 ``del_flag=1`` 并计数。

    :param rows: ``(库名, 表名, 行)``；来自 dump 或 JSON 行文件。
    :param database: 只取这个库的行（dump 里有多个库时必须给）。
    :param company_code: 只取这个 ``sys_company_code`` 的行（库里有多个公司时必须给）。
    :returns: :class:`ExportResult`。
    :raises ZtError: 多个库或多个公司而没有指定（``ambiguous_database`` / ``ambiguous_company``）；
        没有任何有效项目（``no_projects``）；文件行指向不存在的项目时不报错，计入 ``file_of_unknown_project``。
    """
    raw: dict[str, list[dict[str, Any]]] = {t: [] for t in TABLES}
    dbs: set[str] = set()
    for db, table, row in rows:
        if db is not None:
            dbs.add(db)
        if database is not None and db is not None and db != database:
            continue
        raw[table].append(row)
    if database is None and len(dbs) > 1:
        raise ZtError("ambiguous_database", f"dump 里有多个库：{'、'.join(sorted(dbs))}", hint="用 --database 指定")
    codes = sorted({str(r.get("sys_company_code")) for t in TABLES for r in raw[t] if r.get("sys_company_code") is not None})
    if company_code is None and len(codes) > 1:
        raise ZtError("ambiguous_company", f"行里有多个 sys_company_code：{'、'.join(codes)}", hint="用 --company-code 指定")

    def mine(r: dict[str, Any]) -> bool:
        return company_code is None or str(r.get("sys_company_code")) == company_code

    res = ExportResult(databases=sorted(dbs), company_codes=[company_code] if company_code else codes)
    c = res.counts
    for k in ("project_rows", "project_deleted", "project_other_company", "file_rows", "folder_rows",
              "file_deleted", "file_other_company", "file_of_deleted_project", "file_of_unknown_project",
              "knowledge_rows", "knowledge_deleted", "knowledge_folder_rows"):
        c[k] = 0
    live: set[str] = set()
    deleted_projects: set[str] = set()
    for r in raw["project"]:
        if not mine(r):
            c["project_other_company"] += 1
            continue
        p = normalize_project(r)
        if p["del_flag"] == 1:
            c["project_deleted"] += 1
            deleted_projects.add(p["id"])
            continue
        c["project_rows"] += 1
        res.projects.append(p)
        live.add(p["id"])
    for r in raw["project_file"]:
        if not mine(r):
            c["file_other_company"] += 1
            continue
        f = normalize_file(r)
        if f["project_id"] in deleted_projects:
            c["file_of_deleted_project"] += 1
            continue
        if f["project_id"] not in live:
            c["file_of_unknown_project"] += 1
            continue
        if f["del_flag"] == 1:
            c["file_deleted"] += 1
            res.deleted_files.append({k: f[k] for k in ("id", "project_id", "disk_path", "display_path", "item_type")})
            continue
        c["file_rows" if f["item_type"] == 0 else "folder_rows"] += 1
        res.files.append(f)
    for r in raw["knowledge_file"]:
        if not mine(r):
            continue
        f = normalize_file(r, owner_key="category_id")
        if f["del_flag"] == 1:
            c["knowledge_deleted"] += 1
            continue
        c["knowledge_rows" if f["item_type"] == 0 else "knowledge_folder_rows"] += 1
        res.knowledge_files.append(f)
    if not res.projects:
        raise ZtError("no_projects", "没有读到任何有效的 project 行（del_flag=0）",
                      hint="确认 dump 是业务库的完整备份，或 --database / --company-code 是否写对")
    res.projects.sort(key=lambda p: (p["create_time"], p["id"]))
    res.files.sort(key=lambda f: (f["project_id"], f["display_path"], f["id"]))
    return res


def read_export(export_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """读 export-projects 的产物。

    :param export_dir: 含 ``projects.json`` 与 ``files.json`` 的目录。
    :returns: ``(projects 文档, files 文档)``。
    :raises ZtError: 文件缺失或版本不对（``export_invalid``）。
    """
    docs = []
    for name in ("projects.json", "files.json"):
        path = export_dir / name
        if not path.is_file():
            raise ZtError("export_invalid", f"缺少 {path}", hint="先运行 export-projects.py")
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("format_version") != FORMAT_VERSION:
            raise ZtError("export_invalid", f"{path} 的 format_version 不是 {FORMAT_VERSION}")
        docs.append(doc)
    return docs[0], docs[1]


def now_iso() -> str:
    """当前 UTC 时间（秒精度，ISO 8601）。

    :returns: 如 ``2026-10-20T08:00:00Z``。
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_source(mysql_dump: Optional[Path], json_rows: Optional[Path]):
    """按参数选择输入：dump 与 JSON 行文件二选一。

    :param mysql_dump: dump 文件。
    :param json_rows: JSON 行文件。
    :returns: ``(行迭代器, 来源描述)``。
    :raises ZtError: 两个都给或都没给（``usage``）。
    """
    if (mysql_dump is None) == (json_rows is None):
        raise ZtError("usage", "--mysql-dump 与 --json 二选一")
    if mysql_dump is not None:
        return iter_dump_rows(open_dump(mysql_dump), set(TABLES)), {"kind": "mysqldump", "path": str(mysql_dump)}
    assert json_rows is not None
    return iter_json_rows(json_rows), {"kind": "json", "path": str(json_rows)}
