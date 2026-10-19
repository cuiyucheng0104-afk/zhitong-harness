"""``python -m zt.inventory.cli scan``：资料盘点，只报缺件，不打标签。

用法::

    $ZT_PYTHON -m zt.inventory.cli scan --project-dir ~/zhitong/项目/2026-007-某某医院 \
        [--consulting-type 结算审核] [--stage 审定 | --all-stages] [--out 工作/2026-10-19-盘点/result.json]

文件来源二选一：本机项目目录（``--project-dir``），或文件清单（``--listing``，每行一个路径或 ``tos_ls``
的 JSON；盘点只看文件名，所以不必把图纸拉到本机）。清单模式下 ``--project-dir`` / ``--project-doc`` 只用来读
``项目说明.md``。

咨询类型与阶段缺省时读 ``项目说明.md`` 的 YAML 头（``咨询类型``、``阶段``）。阶段不猜：
两处都没有、也没加 ``--all-stages`` 就以退出码 2 失败。

状态：

- ``ok``：盘点完成；缺件在 ``data.missing``，同时每个必备缺件有一条 warn 级告警；
- ``empty``（``no_source_files``）：项目目录里没有任何资料文件；
- ``insufficient``（``no_categorized_files``）：有文件，但文件名与目录都判不出类目，缺件清单不可信。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from zt.common import (
    Call,
    Cli,
    Envelope,
    EvidenceRef,
    WarningItem,
    WarningLevel,
    ZtError,
    empty,
    insufficient,
    ok,
)
from zt.inventory.projectdoc import read_project_doc
from zt.inventory.scan import (
    MAX_UNCLASSIFIED_DEFAULT,
    ScanResult,
    files_from_listing,
    inventory,
    load_inventory_data,
    parse_listing,
)

cli = Cli("zt.inventory", "资料盘点：按资料清单报缺件（不打标签）")


def _scan_args(p: Any) -> None:
    p.add_argument("--project-dir", default=None, help="项目目录（本机缓存里的 项目/<编号>-<工程名>/）")
    p.add_argument("--listing", default=None, help="文件清单：每行一个路径或 tos_ls 的 JSON；- 表示 stdin")
    p.add_argument("--strip-prefix", default=None, help="清单路径要去掉的前缀，如 项目/2026-007-某工程/；缺省自动识别")
    p.add_argument("--project-doc", default=None, help="项目说明.md 的路径（清单模式且没有 --project-dir 时用）")
    p.add_argument("--consulting-type", default=None, help="咨询类型：代码或名称；缺省读项目说明")
    p.add_argument("--stage", default=None, help="阶段：概算/招标控制价/施工过程/结算/审定；缺省读项目说明")
    p.add_argument("--all-stages", action="store_true", help="显式按全部阶段核查")
    p.add_argument("--data-dir", default=None, help="zt-project 数据目录，缺省按环境变量 ZT_PROJECT_DATA 或源码树")
    p.add_argument("--max-unclassified", type=int, default=MAX_UNCLASSIFIED_DEFAULT,
                   help="最多列出多少个没判出类目的文件")


def _from_project_doc(doc_path: Optional[Path], consulting: Optional[str], stage: Optional[str],
                      all_stages: bool) -> tuple[Optional[str], Optional[str], dict[str, str]]:
    """缺省的咨询类型和阶段从项目说明补齐；返回 (咨询类型, 阶段, 来源说明)。"""
    source = {"consulting_type": "arg" if consulting else "none", "stage": "arg" if stage else "none"}
    if consulting and (stage or all_stages):
        return consulting, stage, source
    if doc_path is None or not doc_path.is_file():
        return consulting, stage, source
    fields = read_project_doc(doc_path.read_text(encoding="utf-8"))
    if not consulting and fields.get("咨询类型"):
        consulting, source["consulting_type"] = str(fields["咨询类型"]), "project_doc"
    if not stage and not all_stages and fields.get("阶段"):
        stage, source["stage"] = str(fields["阶段"]), "project_doc"
    return consulting, stage, source


def _read_listing(path: str) -> list[str]:
    if path == "-":
        import sys

        return parse_listing(sys.stdin.read())
    p = Path(path)
    if not p.is_file():
        raise ZtError("listing_not_found", f"文件清单不存在：{p}")
    return parse_listing(p.read_text(encoding="utf-8"))


def _warnings(result: dict[str, Any]) -> list[WarningItem]:
    out: list[WarningItem] = []
    for it in result["missing"]:
        out.append(WarningItem(
            code="required_item_missing", level=WarningLevel.WARN,
            message=f"必备资料未找到：{it['item_name']}（{it['stage_code']}阶段，类目「{it['doc_category']}」）",
            hint="先看 unclassified_files 和资料目录里有没有文件名不规范的同类资料；确认没有再告诉用户需要补件",
        ))
    for row in result["pending"]:
        if row["requirement_level"] != "required":
            continue
        out.append(WarningItem(
            code="required_item_unconfirmed", level=WarningLevel.WARN,
            message=f"必备资料只有弱证据，尚未确认：{row['item_name']}（{row['stage_code']}阶段）",
            hint="打开候选文件确认它是不是这一项；不要仅凭文件名就说已齐备",
            evidence=[EvidenceRef(rel_path=f["rel_path"]) for f in row["files"][:5]],
        ))
    for it in result["advisory"]:
        out.append(WarningItem(
            code="important_item_missing", level=WarningLevel.INFO,
            message=f"重要资料未找到：{it['item_name']}（{it['stage_code']}阶段），不影响齐备率",
        ))
    if result["scope"]["checklist_fallback"]:
        out.append(WarningItem(
            code="checklist_fallback_to_all", level=WarningLevel.INFO,
            message=f"咨询类型「{result['scope']['consulting_type_name']}」没有专属清单，按通用清单核查",
        ))
    if result["input_stats"]["skipped_symlinks"]:
        out.append(WarningItem(
            code="symlink_skipped", level=WarningLevel.WARN,
            message=f"{result['input_stats']['skipped_symlinks']} 个符号链接指向项目目录之外，已跳过",
        ))
    if result["scope"]["consulting_type"] is None:
        out.append(WarningItem(
            code="consulting_type_unspecified", level=WarningLevel.INFO,
            message="没有指定咨询类型，按通用清单核查",
            hint="项目说明里有咨询类型就读它；全过程、结算审核、招标控制价编制的清单不同"))
    if result["scope"]["stage_basis"] == "all_stages":
        out.append(WarningItem(code="all_stages_scope", level=WarningLevel.INFO,
                               message="按全部阶段核查（用户显式要求）"))
    return out


@cli.command("scan", help="盘点项目资料，报缺件", arguments=_scan_args)
def scan(call: Call) -> Envelope:
    """盘点一个项目目录。

    :param call: 调用上下文。
    :returns: 结果信封。
    :raises ZtError: 目录不存在、阶段 / 咨询类型非法、阶段未指定、数据目录不完整。
    """
    a = call.args
    if not a.project_dir and not a.listing:
        raise ZtError("usage", "需要 --project-dir 或 --listing", hint="本机已有项目目录用 --project-dir；只有 tos_ls 清单用 --listing")
    project_dir = Path(a.project_dir) if a.project_dir else None
    if project_dir is not None and not project_dir.is_dir():
        raise ZtError("project_dir_not_found", f"项目目录不存在：{project_dir}")
    doc_path = Path(a.project_doc) if a.project_doc else (project_dir / "项目说明.md" if project_dir else None)
    consulting, stage, source = _from_project_doc(doc_path, a.consulting_type, a.stage, a.all_stages)
    data = load_inventory_data(a.data_dir)
    scan: Optional[ScanResult] = None
    name: Optional[str] = project_dir.resolve().name if project_dir else None
    if a.listing:
        listing_paths = _read_listing(a.listing)
        scan = files_from_listing(listing_paths, strip_prefix=a.strip_prefix)
        if name is None and scan.stripped_prefix:
            name = scan.stripped_prefix.replace("\\", "/").strip("/").split("/")[-1]
    result = inventory(project_dir, data, consulting_type=consulting, stage=stage, all_stages=a.all_stages,
                       max_unclassified=a.max_unclassified, scan=scan, project_name=name)
    result["scope"]["source"] = source
    stats = result.pop("input_stats")
    input_empty = result.pop("audit")["input_empty"]
    result["input_stats"] = stats
    coverage = {"files_total": stats["files_listed"], "files_used": stats["files_used"],
                "ignored_system": stats["ignored_system"], "unclassified": result["unclassified_total"]}
    if stats["files_listed"] == 0:
        return empty("no_source_files", coverage=coverage, data={"project": result["project"]},
                     warnings=[WarningItem(code="no_source_files", level=WarningLevel.WARN,
                                           message="项目目录里没有任何资料文件",
                                           hint="先用 tos_ls 和 tos_pull 把资料拉到本机项目目录")])
    if input_empty:
        warn = WarningItem(code="no_categorized_files", level=WarningLevel.WARN,
                           message=f"{stats['files_listed']} 个文件的文件名与目录都判不出类目，缺件清单不可信",
                           hint="逐个看 unclassified_files 的文件名；不要把清单项当成「全部缺失」报告")
        return insufficient("no_categorized_files", coverage=coverage, warnings=[warn], data=result)
    return ok(result, coverage=coverage, warnings=_warnings(result))


if __name__ == "__main__":
    raise SystemExit(cli.main())
