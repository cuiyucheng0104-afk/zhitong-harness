"""报告初稿 CLI（零模型）：取材、金额事实、逐章 prepare / finalize、导出 docx、套正式模板。

子命令（调用形态 ``python -m zt.report.cli <子命令> [--in request.json] [--out 结果] [参数]``）::

    templates        [--template 模板码]                                  列模板；给模板码时列章节、确认事项、需要的金额
    context          --root 项目目录 --files 资料/a.pdf 资料/b.xlsx [--finished 成果/旧报告.docx]
    facts            --root 项目目录 (--files … | --context ctx.json) [--template 模板码]
    section_prepare  --context ctx.json --template 模板码 --section 章节码
                     [--facts facts.json] [--confirmed key …] [--project-name 名称]
    section_finalize --prepare 本章/result.json --draft 本章.md [--facts facts.json] [--truncated]
    export           (--sections 010-x/final.json … | --sections-dir 章节/) --docx 成果/x.docx
                     [--title] [--context] [--facts]
    fill_template    --template-docx 名称.docx --values values.json --docx 成果/x.docx

``--in request.json`` 可代替命令行参数（键名与参数同名，``-`` 换成 ``_``），命令行优先。
``section_prepare`` 给了 ``--out`` 且本章有可读资料时，另写 ``prompt.md``（系统提示词 + 本章输入，原样）供 agent 读。
数据目录（``report_templates.yaml``、``docx-templates/``）用 ``--data-dir`` 或环境变量 ``ZT_REPORT_DATA`` 指定，
缺省是源码树里的 ``zhitong/skills/zt-report/data``。
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

from zt.common import Call, Cli, Envelope, ZtError, ok, partial, read_json
from zt.common.envelope import WarningItem
from zt.report import service
from zt.report.docx_template import load_manifest, render
from zt.report.templates import DOCX_DIR, data_dir, find_template, load_templates

cli = Cli("zt.report", "报告初稿：取材、金额事实、逐章 prepare / finalize、导出 docx（零模型）")

PROMPT_FILE = "prompt.md"
FINAL_FILE = "final.json"


def _req(call: Call) -> dict:
    req = call.request if isinstance(call.request, dict) else {}
    return dict(req)


def _pick(call: Call, req: dict, name: str, default: Any = None) -> Any:
    v = getattr(call.args, name, None)
    if v not in (None, [], False):
        return v
    return req.get(name, default)


def _data_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--data-dir", help="zt-report 数据目录（含 report_templates.yaml 与 docx-templates/）")


def _root(call: Call, req: dict, ctx: Optional[dict] = None) -> Path:
    raw = _pick(call, req, "root") or (ctx or {}).get("root")
    if not raw:
        raise ZtError("invalid_request", "没有给项目目录", hint="用 --root 指定本机缓存里的项目目录")
    root = Path(raw)
    if not root.is_dir():
        raise ZtError("root_not_found", f"项目目录不存在：{root}")
    return root


def _json_file(path: Optional[str], what: str) -> Any:
    if not path:
        return None
    try:
        return read_json(path)
    except ZtError as e:
        raise ZtError(e.code, f"{what}：{e.message}", hint=e.hint) from None


# ---------------------------------------------------------------- templates


def _templates_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--template", help="模板码；给了只列这一套的章节、确认事项与需要的金额事实")
    _data_arg(p)


@cli.command("templates", help="列报告模板（24 套 AI 初稿模板与 docx 正式模板）", arguments=_templates_args)
def templates_cmd(call: Call) -> Envelope:
    req = _req(call)
    base = data_dir(_pick(call, req, "data_dir"))
    return service.template_summary(load_templates(base), _pick(call, req, "template"),
                                    load_manifest(base / DOCX_DIR))


# ---------------------------------------------------------------- context


def _context_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", help="项目目录（本机缓存里的 项目/<编号>-<工程名>/）")
    p.add_argument("--files", nargs="+", help="资料：项目目录内相对路径")
    p.add_argument("--finished", nargs="+", help="已成稿报告（只供参考体例，护栏查转写）：相对路径")
    p.add_argument("--max-chars", type=int, help=f"单份正文上限，默认 {service.REPORT_FILE_MAX_CHARS}")


@cli.command("context", help="读资料正文，逐份回报读取结果（[资料n] 编号在这一步定下）", arguments=_context_args)
def context_cmd(call: Call) -> Envelope:
    req = _req(call)
    root = _root(call, req)
    refs = service.source_refs(_pick(call, req, "files") or [], _pick(call, req, "finished") or [])
    max_chars = _pick(call, req, "max_chars") or service.REPORT_FILE_MAX_CHARS
    return service.build_context(root, refs, max_chars=int(max_chars))


# ---------------------------------------------------------------- facts


def _facts_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", help="项目目录；给了 --context 时可省（取 context 的 root）")
    p.add_argument("--files", nargs="+", help="表格资料：项目目录内相对路径")
    p.add_argument("--context", help="context 的 result.json：取其中全部资料（含读不出的）")
    p.add_argument("--template", help="模板码：模板需要金额而一个都没读到时给提示")
    p.add_argument("--deadline-ms", type=int, help="总时限，默认 60000")
    _data_arg(p)


@cli.command("facts", help="读表格里的金额事实（审定单合计行、项目级费用表合计），不派生", arguments=_facts_args)
def facts_cmd(call: Call) -> Envelope:
    req = _req(call)
    ctx = None
    ctx_path = _pick(call, req, "context")
    if ctx_path:
        ctx = service.context_data(_json_file(ctx_path, "context"))
    root = _root(call, req, ctx)
    files = list(_pick(call, req, "files") or [])
    if ctx is not None:
        for group in ("files", "unreadable", "duplicates"):
            files.extend({"rel_path": f["rel_path"], "file_name": f["file_name"]}
                         for f in ctx.get(group) or [] if f.get("rel_path"))
    if not files:
        raise ZtError("invalid_request", "没有给资料文件", hint="用 --files 或 --context 指定")
    refs = service.source_refs(files)
    code = _pick(call, req, "template")
    template = None
    if code:
        template = find_template(load_templates(data_dir(_pick(call, req, "data_dir"))), code)
    deadline = _pick(call, req, "deadline_ms") or service.FACTS_DEADLINE_MS
    return service.build_facts(root, refs, template=template, deadline_ms=int(deadline))


# ---------------------------------------------------------------- section_prepare


def _prepare_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--context", help="context 的 result.json")
    p.add_argument("--template", help="模板码")
    p.add_argument("--section", help="章节码")
    p.add_argument("--facts", help="facts 的 result.json（可选）")
    p.add_argument("--confirmed", nargs="+", help="用户确认属实的程序性陈述 key")
    p.add_argument("--project-name", help="项目名称（只作口径提示，正文里的工程名称以资料原文为准）")
    _data_arg(p)


@cli.command("section_prepare", help="一章的写作输入：选材、提示词、护栏证据", arguments=_prepare_args)
def section_prepare_cmd(call: Call) -> Envelope:
    req = _req(call)
    ctx_path, code, sec = (_pick(call, req, k) for k in ("context", "template", "section"))
    if not (ctx_path and code and sec):
        raise ZtError("invalid_request", "section_prepare 需要 --context、--template、--section")
    ctx = service.context_data(_json_file(ctx_path, "context"))
    facts = service.facts_list(_json_file(_pick(call, req, "facts"), "facts"))
    env = service.section_prepare(load_templates(data_dir(_pick(call, req, "data_dir"))), code, sec, ctx,
                                  facts=facts, confirmed_claims=_pick(call, req, "confirmed") or [],
                                  project_name=_pick(call, req, "project_name"))
    if call.out_dir is not None and env.status.value == "ok":
        path = call.out_dir / PROMPT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(service.prompt_markdown(env.data), encoding="utf-8", newline="\n")
        env.data["prompt_file"] = path.as_posix()
    return env


# ---------------------------------------------------------------- section_finalize


def _finalize_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--prepare", help="本章 section_prepare 的 result.json")
    p.add_argument("--draft", help="agent 写的本章正文（UTF-8 文本）")
    p.add_argument("--facts", help="facts 的 result.json（与 prepare 用同一份）")
    p.add_argument("--truncated", action="store_true", help="本章没写完（篇幅超限），截到句末并标「未写完」")


@cli.command("section_finalize", help="一章的护栏、金额占位符替换与质量态", arguments=_finalize_args)
def section_finalize_cmd(call: Call) -> Envelope:
    req = _req(call)
    prep_path = _pick(call, req, "prepare")
    if not prep_path:
        raise ZtError("invalid_request", "section_finalize 需要 --prepare")
    prep = service.prepare_data(_json_file(prep_path, "prepare"))
    draft = _pick(call, req, "draft")
    content = None
    if draft:
        try:
            content = Path(draft).read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            raise ZtError("input_not_found", f"找不到本章正文：{draft}") from None
        except UnicodeDecodeError:
            raise ZtError("invalid_draft", f"本章正文不是 UTF-8 文本：{draft}") from None
    elif isinstance(req.get("content"), str):
        content = req["content"]
    facts = service.facts_list(_json_file(_pick(call, req, "facts"), "facts"))
    return service.section_finalize(prep, content, facts=facts,
                                    output_truncated=bool(_pick(call, req, "truncated", False)))


# ---------------------------------------------------------------- export


def _export_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sections", nargs="+", help="各章 section_finalize 的 result.json，按章节顺序")
    p.add_argument("--sections-dir", help=f"章节目录：取其中每个子目录的 {FINAL_FILE}，按子目录名排序（不依赖 shell 通配）")
    p.add_argument("--docx", help="输出 docx 路径（如 成果/结算审核报告-初稿.docx）")
    p.add_argument("--title", help="报告标题")
    p.add_argument("--disclaimer", help="页眉文字，默认「AI 初稿，金额未经人工核对，不得直接出具」")
    p.add_argument("--context", help="context 的 result.json（附录列来源文件与读不出的资料）")
    p.add_argument("--facts", help="facts 的 result.json（附录写金额提示）")


@cli.command("export", help="各章导出为 docx（页眉免责声明 + 附录：资料来源与完成度）", arguments=_export_args)
def export_cmd(call: Call) -> Envelope:
    req = _req(call)
    paths = list(_pick(call, req, "sections") or [])
    sec_dir = _pick(call, req, "sections_dir")
    if sec_dir:
        if not Path(sec_dir).is_dir():
            raise ZtError("input_not_found", f"章节目录不存在：{sec_dir}")
        found = sorted(Path(sec_dir).glob(f"*/{FINAL_FILE}"), key=lambda q: q.parent.name)
        if not found:
            raise ZtError("input_not_found", f"章节目录里没有 */{FINAL_FILE}：{sec_dir}",
                          hint="每章 section_finalize 用 --out <章节目录>/<seq>-<code>/final.json")
        paths.extend(str(q) for q in found)
    docx = _pick(call, req, "docx")
    if not paths or not docx:
        raise ZtError("invalid_request", "export 需要 --sections（或 --sections-dir）与 --docx")
    sections = [service.section_for_export(p if isinstance(p, dict) else _json_file(p, "section")) for p in paths]
    ctx_path, facts_path = _pick(call, req, "context"), _pick(call, req, "facts")
    ctx = service.context_data(_json_file(ctx_path, "context")) if ctx_path else None
    facts_raw = _json_file(facts_path, "facts") if facts_path else None
    facts_result = None
    if facts_raw is not None:
        facts_result = facts_raw.get("data") if isinstance(facts_raw, dict) and "status" in facts_raw else facts_raw
    return service.export_docx(sections, Path(docx), title=_pick(call, req, "title") or service.DEFAULT_TITLE,
                               disclaimer=_pick(call, req, "disclaimer"), ctx=ctx, facts_result=facts_result)


# ---------------------------------------------------------------- fill_template


def _fill_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--template-docx", help="正式模板文件名（templates 子命令列出的 file），或本机 docx 路径")
    p.add_argument("--values", help="占位符取值 JSON：{\"工程名称\": \"…\", …}")
    p.add_argument("--docx", help="输出 docx 路径")
    _data_arg(p)


@cli.command("fill_template", help="按项目信息替换正式 docx 模板的 {名称} 占位符", arguments=_fill_args)
def fill_template_cmd(call: Call) -> Envelope:
    req = _req(call)
    name, values_path, docx = (_pick(call, req, k) for k in ("template_docx", "values", "docx"))
    if not (name and docx):
        raise ZtError("invalid_request", "fill_template 需要 --template-docx 与 --docx")
    src = Path(name)
    if not src.is_file():
        src = data_dir(_pick(call, req, "data_dir")) / DOCX_DIR / name
    if not src.is_file():
        raise ZtError("template_not_found", f"找不到 docx 模板：{name}", hint="用 templates 子命令列出可用的模板文件")
    values = _json_file(values_path, "values") if values_path else req.get("values") or {}
    if not isinstance(values, dict):
        raise ZtError("invalid_request", "values 应为 {名称: 值} 的 JSON 对象")
    res = render(src, values, Path(docx))
    data = {"docx": Path(docx).as_posix(), "template": src.name, "replaced": res.replaced, "missing": res.missing,
            "unsupported": res.unsupported, "unused_values": res.unused_values, "occurrences": res.occurrences,
            "needs_manual": True}
    coverage = {"placeholders": len(res.replaced) + len(res.missing), "replaced": len(res.replaced)}
    warnings = []
    if res.unused_values:
        warnings.append(WarningItem(code="unused_values", level="info",
                                    message="这些值模板里没有对应的占位符：" + "、".join(res.unused_values)))
    if res.unsupported:
        warnings.append(WarningItem(code="unsupported_tags", level="warn",
                                    message="循环 / 条件标签不支持，原样保留：" + "、".join(res.unsupported)))
    if res.missing:
        warnings.append(WarningItem(code="placeholders_missing", level="warn", message=(
            f"{len(res.missing)} 个占位符没有值，已写成 ###名称###：" + "、".join(res.missing[:20])),
            hint="在项目说明里补齐这些信息后重新套模板，或在 Word 里手填"))
    if res.missing or res.unsupported:
        return partial(data, coverage=coverage, warnings=warnings)
    return ok(data, coverage=coverage, warnings=warnings)


if __name__ == "__main__":
    raise SystemExit(cli.main())
