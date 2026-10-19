#!/usr/bin/env python3
"""zt-archive：归档核对与更新。

- ``check``：只读。核对 成果/ 与 工作/ 是否完整、项目说明是否可用，列出要推送的文件（含 SHA-256）；
- ``apply``：检查没有阻断项时，改写本机的项目说明（已出成果、状态）和案例索引（本项目一行），输出要推送的文件。

推送由 agent 用 ``tos_push`` 完成，推送后用本脚本给出的 SHA-256 对照回读结果。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PROJECT_SKILL = Path(__file__).resolve().parent.parent.parent / "zt-project"
os.environ.setdefault("ZT_PROJECT_DATA", str(PROJECT_SKILL / "data"))

from zt.common import Call, Cli, Envelope, WarningItem, WarningLevel, insufficient, ok  # noqa: E402
from zt.inventory.archive import ARCHIVED, Finding, apply_archive, check_archive  # noqa: E402

INDEX_TEMPLATE = PROJECT_SKILL / "templates" / "案例索引.md"

cli = Cli("zt-archive.archive", "项目归档核对与更新")


def _warning(f: Finding, level: WarningLevel) -> WarningItem:
    suffix = f"：{'、'.join(f.paths[:5])}" if f.paths else ""
    return WarningItem(code=f.code, level=level, message=f.message + suffix, hint=f.hint)


def _check_args(p: Any) -> None:
    p.add_argument("--project-dir", required=True, help="本机项目目录")
    p.add_argument("--index", default=None, help="本机的案例索引.md；给了就同时核对本项目的行")


@cli.command("check", help="核对成果/ 与 工作/ 是否完整（只读）", arguments=_check_args)
def check(call: Call) -> Envelope:
    """归档核对。

    :param call: 调用上下文。
    :returns: 有阻断项为 ``insufficient``（``not_ready_to_archive``），否则 ``ok``（可能带提醒）。
    """
    a = call.args
    index_text = Path(a.index).read_text(encoding="utf-8") if a.index and Path(a.index).is_file() else None
    rep = check_archive(Path(a.project_dir), index_text=index_text)
    data = {
        "fields": rep.fields, "deliverables": rep.deliverables, "listed_in_project_doc": rep.listed,
        "work_dirs": rep.work_dirs, "push_list": rep.push_list, "casebook_row": rep.casebook_row,
        "blocking": [f.code for f in rep.blocking],
    }
    warnings = [_warning(f, WarningLevel.ERROR) for f in rep.blocking]
    warnings += [_warning(f, WarningLevel.WARN) for f in rep.warnings]
    if rep.blocking:
        return insufficient("not_ready_to_archive", warnings=warnings, data=data)
    return ok(data, warnings=warnings)


def _apply_args(p: Any) -> None:
    p.add_argument("--project-dir", required=True, help="本机项目目录")
    p.add_argument("--index", required=True, help="本机的案例索引.md（先 tos_pull）；不存在时按模板新建")
    p.add_argument("--status", default=ARCHIVED, help="写进项目说明与案例索引的状态，缺省「已归档」")
    p.add_argument("--key-metrics", default=None, help="案例索引「关键指标」列的文字；缺省保持原值")


@cli.command("apply", help="更新项目说明与案例索引（本机副本）", arguments=_apply_args)
def apply(call: Call) -> Envelope:
    """改写项目说明与案例索引。

    :param call: 调用上下文。
    :returns: 要推送的文件和案例索引里本项目的行。
    :raises zt.common.ZtError: 检查有阻断项（``not_ready_to_archive``）。
    """
    a = call.args
    template = INDEX_TEMPLATE.read_text(encoding="utf-8") if INDEX_TEMPLATE.is_file() else None
    result = apply_archive(Path(a.project_dir), Path(a.index), status=a.status, key_metrics=a.key_metrics,
                           index_template=template)
    warning = WarningItem(
        code="push_after_apply", level=WarningLevel.INFO,
        message="项目说明和案例索引只改了本机副本",
        hint="用 tos_push 推送 files 里的两个文件；案例索引回读提示 remoteChangedSincePull 时，"
             "重新拉取后再 apply，不要覆盖别人的行")
    return ok(result, warnings=[warning])


if __name__ == "__main__":
    raise SystemExit(cli.main())
