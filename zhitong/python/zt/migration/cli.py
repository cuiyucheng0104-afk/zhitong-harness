"""``zhitong/migration/`` 三个脚本的命令行：参数解析 → 调用本包 → stdout 一个 JSON。

约定同 ``zhitong/CONVENTIONS.md``「Python」：成功时 stdout 是结果信封；失败退出码 2，stdout 为
``{"error": {"code", "message", "hint"?}}``；日志走 stderr。脚本只是 ``raise SystemExit(<x>_main())``。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path
from typing import IO, Callable, NoReturn, Optional, Sequence

from zt.common import EXIT_ERROR, Envelope, WarningItem, WarningLevel, ZtError, ok
from zt.common.jsonio import emit
from zt.migration import relayout as rl
from zt.migration.fsops import walk_files
from zt.migration.knowledge import load_knowledge_map
from zt.migration.rows import FORMAT_VERSION, export_rows, load_source, now_iso

log = logging.getLogger("zt.migration")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ZtError("usage", message, hint=self.format_usage().strip())


def _run(build: Callable[[argparse.ArgumentParser], None], handler: Callable[[argparse.Namespace], Envelope],
         prog: str, description: str, argv: Optional[Sequence[str]], stdout: Optional[IO[str]]) -> int:
    out = stdout if stdout is not None else sys.stdout
    if stdout is None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    root = logging.getLogger("zt")
    if not root.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(h)
        root.setLevel(logging.INFO)
    try:
        parser = _Parser(prog=prog, description=description)
        build(parser)
        args = parser.parse_args(argv)
        emit(handler(args).to_json(), out)
        return 0
    except ZtError as exc:
        emit(exc.to_json(), out)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - 最外层：任何异常都要变成错误 JSON + 退出码 2
        traceback.print_exc(file=sys.stderr)
        emit(ZtError("internal_error", f"{type(exc).__name__}: {exc}").to_json(), out)
        return EXIT_ERROR


# —— export-projects ——

def _export_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--mysql-dump", type=Path, help="mysqldump 文件（.sql 或 .sql.gz）")
    p.add_argument("--json", dest="json_rows", type=Path, help="runbook 里 mysql -N -B -r 命令导出的 JSON Lines")
    p.add_argument("--database", help="dump 里有多个库时只取这个库")
    p.add_argument("--company-code", help="只取这个 sys_company_code 的行")
    p.add_argument("--out", type=Path, required=True, help="输出目录：写 projects.json 与 files.json")


def _export(args: argparse.Namespace) -> Envelope:
    rows, source = load_source(args.mysql_dump, args.json_rows)
    res = export_rows(rows, database=args.database, company_code=args.company_code)
    args.out.mkdir(parents=True, exist_ok=True)
    meta = {"format_version": FORMAT_VERSION, "exported_at": now_iso(), "source": source,
            "databases": res.databases, "company_codes": res.company_codes, "counts": res.counts}
    (args.out / "projects.json").write_text(
        json.dumps(meta | {"projects": res.projects}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (args.out / "files.json").write_text(json.dumps(
        meta | {"files": res.files, "deleted_files": res.deleted_files, "knowledge_files": res.knowledge_files},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    warnings = []
    if res.counts["file_rows"] == 0:
        warnings.append(WarningItem(code="no_file_rows", level=WarningLevel.WARN,
                                    message="没有任何有效的 project_file 文件行", hint="确认 dump 包含 project_file 表"))
    if res.counts["file_of_unknown_project"]:
        warnings.append(WarningItem(code="file_of_unknown_project", level=WarningLevel.WARN,
                                    message=f"{res.counts['file_of_unknown_project']} 条文件行指向不存在的项目，已跳过"))
    return ok({"out": str(args.out), "counts": res.counts, "databases": res.databases,
               "company_codes": res.company_codes}, warnings=warnings)


def export_main(argv: Optional[Sequence[str]] = None, stdout: Optional[IO[str]] = None) -> int:
    """``export-projects.py`` 入口。

    :param argv: 参数；默认 ``sys.argv[1:]``。
    :param stdout: 输出流（测试注入）。
    :returns: 退出码。
    """
    return _run(_export_args, _export, "export-projects.py", "从 mysqldump 或 JSON 行导出 project / project_file", argv, stdout)


# —— relayout ——

def _relayout_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--export-dir", type=Path, required=True, help="export-projects.py 的输出目录")
    p.add_argument("--nas", type=Path, required=True, help="旧 NAS 项目根（其下是 <project.id>/ 子目录），只读")
    p.add_argument("--out", type=Path, required=True, help="工作目录：写 mirror/、manifest.json、整理报告.md、.state/")
    p.add_argument("--link", choices=("hard", "copy"), default="hard",
                   help="hard：硬链接（同一文件系统，不额外占盘，默认）；copy：复制")
    p.add_argument("--dry-run", action="store_true", help="只算计划并输出，不写任何文件")
    p.add_argument("--plan-out", type=Path, help="dry-run 时把完整计划写到这个文件，stdout 只给摘要")
    p.add_argument("--include-orphans", action="store_true", help="库里没有记录的 NAS 文件也迁入 资料/未登记文件/")
    p.add_argument("--knowledge", type=Path, action="append", default=[],
                   help="旧知识库目录（如 <base>/knowledge/1），可重复")
    p.add_argument("--knowledge-map", type=Path, default=rl.DEFAULT_KNOWLEDGE_MAP, help="知识库一级目录映射 YAML")
    p.add_argument("--knowledge-seed", type=Path, help="zhitong/knowledge-seed：一并放进 知识库/（不含 _tools/；总是复制，不硬链接）")
    p.add_argument("--templates-dir", type=Path, default=rl.DEFAULT_TEMPLATES, help="项目说明与案例索引模板目录")
    p.add_argument("--rules", type=Path, default=rl.DEFAULT_RULES, help="classify_rules.yaml")


def _relayout(args: argparse.Namespace) -> Envelope:
    opts = rl.Options(
        export_dir=args.export_dir, nas=args.nas, out=args.out, link=args.link, dry_run=args.dry_run,
        include_orphans=args.include_orphans, knowledge_roots=list(args.knowledge),
        knowledge_map=load_knowledge_map(args.knowledge_map) if args.knowledge else None,
        knowledge_seed=args.knowledge_seed, templates_dir=args.templates_dir, rules_path=args.rules,
    )
    plan = rl.build_plan(opts)
    summary = rl.summarize(plan)
    if opts.dry_run:
        mirror = opts.out / rl.MIRROR_DIR
        gen = rl.generated_paths(plan)
        actions = [{"op": "place", "path": o["path"], "from": o["old_path"]} for o in plan.outputs]
        actions += [{"op": "generate", "path": g} for g in gen]
        if mirror.is_dir():
            keep = {o["path"] for o in plan.outputs} | set(gen)
            actions += [{"op": "remove_stale", "path": r} for r in walk_files(mirror) if r not in keep]
        full = {"summary": summary, "projects": plan.projects, "actions": actions, "deletions": plan.deletions,
                "not_migrated": plan.not_migrated, "renames": plan.renames, "empty_folders": plan.empty_folders}
        if args.plan_out:
            args.plan_out.parent.mkdir(parents=True, exist_ok=True)
            args.plan_out.write_text(json.dumps(full, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            data = {"dry_run": True, "summary": summary, "plan_out": str(args.plan_out)}
        else:
            data = {"dry_run": True} | full
        return ok(data, warnings=plan.warnings)
    stats = rl.execute(plan, opts)
    return ok({"dry_run": False, "summary": summary, "stats": stats, "mirror": str(opts.out / rl.MIRROR_DIR),
               "manifest": str(opts.out / rl.MANIFEST), "report": str(opts.out / rl.REPORT)}, warnings=plan.warnings)


def relayout_main(argv: Optional[Sequence[str]] = None, stdout: Optional[IO[str]] = None) -> int:
    """``relayout.py`` 入口。

    :param argv: 参数；默认 ``sys.argv[1:]``。
    :param stdout: 输出流（测试注入）。
    :returns: 退出码。
    """
    return _run(_relayout_args, _relayout, "relayout.py", "旧 NAS 资料整理成桶目录规范的镜像", argv, stdout)


# —— verify ——

def _verify_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--export-dir", type=Path, required=True, help="export-projects.py 的输出目录")
    p.add_argument("--nas", type=Path, required=True, help="旧 NAS 项目根，只读")
    p.add_argument("--out", type=Path, required=True, help="relayout.py 的 --out")
    p.add_argument("--quick", action="store_true", help="只比字节数，不重算镜像文件 sha256")
    p.add_argument("--accept-missing-source", action="store_true", help="「库里有、NAS 上没有」只告警")


def _verify(args: argparse.Namespace) -> Envelope:
    from zt.migration.verify import verify

    return verify(args.export_dir, args.nas, args.out, quick=args.quick, accept_missing_source=args.accept_missing_source)


def verify_main(argv: Optional[Sequence[str]] = None, stdout: Optional[IO[str]] = None) -> int:
    """``verify.py`` 入口。

    :param argv: 参数；默认 ``sys.argv[1:]``。
    :param stdout: 输出流（测试注入）。
    :returns: 退出码。
    """
    return _run(_verify_args, _verify, "verify.py", "镜像与 files.json、NAS 对账", argv, stdout)
