#!/usr/bin/env python3
"""zt-project：读项目说明 / 给没有项目说明的目录生成草稿。

- ``show``：读 ``项目说明.md`` 的 YAML 头、关键文件指引和已出成果，缺必填字段时 ``insufficient``；
- ``draft``：目录里没有 ``项目说明.md`` 时，按目录名、目录结构和文件名规则生成草稿（咨询类型、阶段写「待确认」）。
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

os.environ.setdefault("ZT_PROJECT_DATA", str(Path(__file__).resolve().parent.parent / "data"))

from zt.common import Call, Cli, Envelope, WarningItem, WarningLevel, ZtError, insufficient, ok  # noqa: E402
from zt.inventory.draft import draft_project_doc  # noqa: E402
from zt.inventory.projectdoc import (  # noqa: E402
    REQUIRED_FIELDS,
    UNDECIDED_VALUES,
    read_project_doc,
    section_bullets,
    section_table,
    write_text_atomic,
)
from zt.inventory.scan import load_inventory_data  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "项目说明.md"

cli = Cli("zt-project.project_doc", "读项目说明 / 生成草稿")


@cli.command("show", help="读项目说明", arguments=lambda p: p.add_argument("--file", required=True, help="项目说明.md 的本机路径"))
def show(call: Call) -> Envelope:
    """读项目说明。

    :param call: 调用上下文。
    :returns: YAML 头字段、关键文件指引、已出成果；缺必填字段或有「待确认」时 ``insufficient``。
    :raises ZtError: 文件不存在、YAML 头坏、编号格式错。
    """
    path = Path(call.args.file)
    if not path.is_file():
        raise ZtError("file_not_found", f"项目说明不存在：{path}", hint="用 project_doc.py draft 生成草稿")
    text = path.read_text(encoding="utf-8")
    fields = read_project_doc(text)
    key_files = [r for r in section_table(text, "关键文件指引") if r.get("位置", "").strip()]
    data: dict[str, Any] = {
        "fields": fields, "key_files": key_files, "deliverables": section_bullets(text, "已出成果"),
    }
    problems = [k for k in REQUIRED_FIELDS if fields.get(k) in (None, "") or fields.get(k) in UNDECIDED_VALUES]
    if problems:
        data["unresolved_fields"] = problems
        warn = WarningItem(code="project_doc_incomplete", level=WarningLevel.WARN,
                           message=f"项目说明里这些字段缺失或还是「待确认」：{'、'.join(problems)}",
                           hint="问用户确认后补进项目说明，再做盘点和核对")
        return insufficient("project_doc_incomplete", warnings=[warn], data=data)
    return ok(data)


def _draft_args(p: Any) -> None:
    p.add_argument("--project-dir", required=True, help="本机项目目录")
    p.add_argument("--code", default=None, help="项目编号；缺省取目录名前缀")
    p.add_argument("--name", default=None, help="工程名称；缺省取目录名去掉编号的部分")
    p.add_argument("--consulting-type", default=None, help="咨询类型；缺省「待确认」")
    p.add_argument("--stage", default=None, help="阶段；缺省「待确认」")
    p.add_argument("--data-dir", default=None)


@cli.command("draft", help="给没有项目说明的目录生成草稿", arguments=_draft_args)
def draft(call: Call) -> Envelope:
    """生成项目说明草稿并写到项目目录。

    :param call: 调用上下文。
    :returns: 草稿路径和要推送的文件。
    :raises ZtError: 目录不存在或项目说明已存在。
    """
    a = call.args
    project_dir = Path(a.project_dir)
    if not project_dir.is_dir():
        raise ZtError("project_dir_not_found", f"项目目录不存在：{project_dir}")
    target = project_dir / "项目说明.md"
    if target.exists():
        raise ZtError("project_doc_exists", f"项目说明已存在，不覆盖：{target}", hint="用 show 读它；要重写先让用户确认")
    data = load_inventory_data(a.data_dir)
    text = draft_project_doc(project_dir, data, TEMPLATE.read_text(encoding="utf-8"), code=a.code, name=a.name,
                             consulting_type=a.consulting_type, stage=a.stage, today=date.today())
    write_text_atomic(target, text)
    fields = read_project_doc(text)
    undecided = [k for k in ("项目编号", "咨询类型", "阶段") if fields.get(k) in UNDECIDED_VALUES]
    warnings = []
    if undecided:
        warnings.append(WarningItem(code="draft_needs_confirmation", level=WarningLevel.WARN,
                                    message=f"草稿里这些字段需要跟用户确认：{'、'.join(undecided)}",
                                    hint="确认后直接改项目说明的 YAML 头；关键文件指引里的候选路径要打开核对"))
    rel = f"项目/{project_dir.resolve().name}/项目说明.md"
    return ok({"project_doc": str(target), "fields": fields, "files_to_push": [{"local_path": str(target), "path": rel}]},
              warnings=warnings)


if __name__ == "__main__":
    raise SystemExit(cli.main())
