#!/usr/bin/env python3
"""zt-project：分配项目编号 ``YYYY-NNN`` 并开新项目。

编号规则（spec §5）：建项目年份 + 当年三位流水号，在案例索引里取当年最大值加一；目录名 ``<编号>-<工程名>``，
工程名去掉空格与 ``/\\:*?"<>|``。分配逻辑就在本文件的 :func:`allocate_code`，可事后修改。

子命令：

- ``allocate``：只算下一个编号，不写任何文件；
- ``create``：算编号、建本机项目目录、写 ``项目说明.md``、在案例索引里追加本项目一行，输出要推送的两个文件。

案例索引是桶里的共享文件：调用前先 ``tos_pull 案例索引.md`` 拿到最新的，``create`` 之后**立刻**推送项目说明和案例索引，
编号才算占住。两个人同时开项目时后推送的人会在回读时发现别人改过（``remoteChangedSincePull``），此时重新拉取、重新分配。
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("ZT_PROJECT_DATA", str(Path(__file__).resolve().parent.parent / "data"))

from zt.common import Call, Cli, Envelope, WarningItem, WarningLevel, ZtError, ok  # noqa: E402
from zt.common.paths import project_dir_name  # noqa: E402
from zt.inventory import data as datafiles  # noqa: E402
from zt.inventory.casebook import max_seq_in_codes, parse_casebook  # noqa: E402
from zt.inventory.checklist import load_checklist  # noqa: E402
from zt.inventory.projectdoc import render_template, write_text_atomic  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_DIR / "templates"
SUBDIRS = ("资料", "图纸", "工作", "成果")
MAX_SEQ = 999

cli = Cli("zt-project.new_project", "分配项目编号并开新项目")


def allocate_code(index_codes: Iterable[str], known_names: Iterable[str], year: int) -> dict[str, int]:
    """取当年最大流水号加一。

    :param index_codes: 案例索引「编号」列的值。
    :param known_names: 桶里 ``项目/`` 下已有的目录名（防索引漏登记）。
    :param year: 项目建立年份。
    :returns: ``{"year", "seq", "index_max", "known_max"}``，``seq`` 是新流水号。
    :raises ZtError: 当年流水号已用到 999（``project_code_exhausted``）。
    """
    index_max = max_seq_in_codes(index_codes, year)
    known_max = max_seq_in_codes(known_names, year)
    seq = max(index_max, known_max) + 1
    if seq > MAX_SEQ:
        raise ZtError("project_code_exhausted", f"{year} 年的项目编号已经用到 {MAX_SEQ}",
                      hint="编号格式 YYYY-NNN 只有三位流水号，需要先改编号规则")
    return {"year": year, "seq": seq, "index_max": index_max, "known_max": known_max}


def _known(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        out.extend(x.strip().replace("\\", "/").rstrip("/").split("/")[-1] for x in re.split(r"[,\n]", v) if x.strip())
    return out


def _common_args(p: Any) -> None:
    p.add_argument("--index", required=True, help="本机的案例索引.md（先 tos_pull 到本机）；不存在时按模板新建")
    p.add_argument("--year", type=int, default=None, help="项目年份，缺省今年")
    p.add_argument("--known", action="append", default=[],
                   help="桶里 项目/ 下已有的目录名（逗号或换行分隔，可重复；可直接给 tos_ls 的路径）")


def _index_text(index: Path) -> str:
    if index.is_file():
        return index.read_text(encoding="utf-8")
    return (TEMPLATE_DIR / "案例索引.md").read_text(encoding="utf-8")


def _allocation(args: Any, name: str) -> tuple[dict[str, int], str, str]:
    year = args.year or date.today().year
    book = parse_casebook(_index_text(Path(args.index)))
    alloc = allocate_code((r.get("编号", "") for r in book.rows), _known(args.known), year)
    code = f"{alloc['year']}-{alloc['seq']:03d}"
    return alloc, code, project_dir_name(code, name)


@cli.command("allocate", help="算下一个项目编号（不写文件）",
             arguments=lambda p: (_common_args(p), p.add_argument("--name", required=True, help="工程名称")))
def allocate(call: Call) -> Envelope:
    """算下一个项目编号。

    :param call: 调用上下文。
    :returns: 编号与目录名。
    """
    alloc, code, dir_name = _allocation(call.args, call.args.name)
    return ok({"project_code": code, "dir_name": dir_name, "basis": alloc})


def _create_args(p: Any) -> None:
    _common_args(p)
    p.add_argument("--name", required=True, help="工程名称")
    p.add_argument("--consulting-type", required=True, help="咨询类型：全过程造价咨询 / 结算审核 / 招标控制价编制")
    p.add_argument("--stage", required=True, help="阶段：概算 / 招标控制价 / 施工过程 / 结算 / 审定")
    p.add_argument("--root", required=True, help="本机镜像根（tos_pull 返回的本机路径所在的根，如 ~/zhitong）")
    p.add_argument("--business", default="", help="业态")
    p.add_argument("--scale", default="", help="规模")
    p.add_argument("--alias", action="append", default=[], help="别名（客户合同号等），可重复")
    p.add_argument("--legacy-id", default="", help="旧系统项目 ID（迁移用）")


@cli.command("create", help="开新项目：建目录、写项目说明、登记案例索引", arguments=_create_args)
def create(call: Call) -> Envelope:
    """开新项目。

    :param call: 调用上下文。
    :returns: 编号、本机目录和要推送的文件。
    :raises ZtError: 咨询类型或阶段非法、目录已存在、案例索引格式坏。
    """
    a = call.args
    checklist = load_checklist(datafiles.data_dir() / datafiles.CHECKLIST)
    code_type = checklist.resolve_consulting_type(a.consulting_type)
    if code_type in (None, "ALL"):
        raise ZtError("invalid_consulting_type", f"咨询类型必须是具体类型：{a.consulting_type!r}",
                      hint="全过程造价咨询 / 结算审核 / 招标控制价编制")
    checklist.stage_scope(a.stage)  # 阶段严格查表
    alloc, code, dir_name = _allocation(a, a.name)
    root = Path(a.root).expanduser()
    project_dir = root / "项目" / dir_name
    if project_dir.exists():
        raise ZtError("project_exists", f"本机已有项目目录：{project_dir}",
                      hint="可能是别人刚开了同名项目：重新 tos_pull 案例索引后再分配")
    today = date.today().isoformat()
    values = {"项目编号": code, "工程名称": a.name.strip(), "咨询类型": checklist.consulting_types[code_type],
              "阶段": a.stage.strip(), "业态": a.business, "规模": a.scale, "别名": a.alias,
              "旧系统项目ID": a.legacy_id, "状态": "进行中", "建立日期": today}
    doc = render_template((TEMPLATE_DIR / "项目说明.md").read_text(encoding="utf-8"), values)
    book = parse_casebook(_index_text(Path(a.index)))
    book.upsert({"编号": code, "工程名": values["工程名称"], "业态": a.business, "规模": a.scale,
                 "咨询类型": values["咨询类型"], "关键指标": "", "成果链接": "", "状态": "进行中"})
    try:
        for sub in SUBDIRS:
            (project_dir / sub).mkdir(parents=True, exist_ok=True)
        doc_path = write_text_atomic(project_dir / "项目说明.md", doc)
        index_path = write_text_atomic(Path(a.index), book.render())
    except BaseException:
        shutil.rmtree(project_dir, ignore_errors=True)  # 只清理本次新建的目录（上面已确认它原先不存在）
        raise
    return ok(
        {
            "project_code": code, "dir_name": dir_name, "project_dir": str(project_dir), "basis": alloc,
            "files_to_push": [
                {"local_path": str(doc_path), "path": f"项目/{dir_name}/项目说明.md"},
                {"local_path": str(index_path), "path": "案例索引.md"},
            ],
        },
        warnings=[WarningItem(
            code="push_now_to_reserve_code", level=WarningLevel.INFO,
            message=f"编号 {code} 只在本机登记，推送项目说明和案例索引后才算占住",
            hint="立即 tos_push 这两个文件；回读提示 remoteChangedSincePull 时重新拉取案例索引并重新分配")],
    )


if __name__ == "__main__":
    raise SystemExit(cli.main())
