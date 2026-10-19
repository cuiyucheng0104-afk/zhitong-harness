"""概算 CLI（zt-estimate skill）：两段式，抽取不出数、计算才出数。全部零模型。

``extract_prepare``  读设计说明 / 可研，取关键词窗口，给出抽取说明::

    python -m zt.estimate.cli extract_prepare --files 资料/可研报告.pdf --project-name "某项目一标段" \\
        --out 工作/2026-10-19-概算/extract/

  有 ``--out`` 时同目录另写 ``概算抽取说明.md`` 与每份文件的 ``概算抽取正文-NN.txt``（文件头写 file_id）。

``extract_finalize`` agent 的回答 → 候选 / 未落定 / 单体 / 原文总量（引文回原文、倍率由代码乘、单体归位、面积对账）::

    python -m zt.estimate.cli extract_finalize --prepare 工作/.../extract/result.json --answers 工作/.../extract_answers.json \\
        --out 工作/2026-10-19-概算/extract_final/

``suggest``  规模 + 指标基准 → 各成本位建议值与其他费建议（``--in`` 请求 JSON，``--baselines`` 基准 JSON）。

``compute``  用户确认过的 inputs → 515 条公式求值 + 真公式 xlsx（``--in`` 请求 JSON；``--out`` 目录写 ``概算.xlsx``）。
  四道闸按 必填 → 面积 → 面积对账 → 全零 的顺序拒算，输出 ``insufficient`` 信封。

``template`` 模板元数据（行树、输入位、必填位、告警码字典、策略）。
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

from zt.common import Call, Cli, Envelope, WarningItem, ZtError, empty, insufficient, manual, ok, partial, read_json
from zt.estimate import service
from zt.estimate import warning_codes

cli = Cli("zt.estimate", "概算：抽取规模量（两半式）、正向推算、公式求值与真公式 xlsx（零模型）")

INSTRUCTIONS_NAME = "概算抽取说明.md"
XLSX_NAME = "概算.xlsx"


# ---------------------------------------------------------------- 公共

def warning_items(warnings: list[dict]) -> list[WarningItem]:
    """概算告警（带 cell 等领域键的字典）→ 信封告警（code / level / message）；完整告警留在 data.warnings。

    级别取告警自带的 level，没有就按 :mod:`zt.estimate.warning_codes` 登记的严重度，未登记按 warn。

    :param warnings: 概算告警列表。
    :returns: 信封告警。
    """
    out: list[WarningItem] = []
    for w in warnings or []:
        code = str(w.get("code") or "estimate_warning")
        meta = warning_codes.describe(code) or {}
        level = w.get("level") or meta.get("severity") or "warn"
        if level not in ("info", "warn", "error"):
            level = "warn"
        out.append(WarningItem(code=code, level=level, message=str(w.get("message") or meta.get("label") or code)))
    return out


def _template_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--template-code", help="模板编码，默认 gsyz_v1")


def _extract_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", help="项目目录（文件路径相对它），默认当前目录")
    p.add_argument("--files", nargs="+", metavar="资料/x.pdf", help="设计说明 / 可研 / 指标表")
    p.add_argument("--project-name", help="项目名称（解析标段，提示全地块口径）")
    _template_arg(p)


def _extract_request(call: Call, base: Optional[dict] = None) -> tuple[dict, Path]:
    req = dict(base or {})
    req.update({k: v for k, v in dict(call.request or {}).items() if k not in ("root", "answers", "prepare_result")})
    a = call.args
    if getattr(a, "files", None):
        req["files"] = [{"rel_path": f} for f in a.files]
    if getattr(a, "project_name", None):
        req["project_name"] = a.project_name
    if getattr(a, "template_code", None):
        req["template_code"] = a.template_code
    files = req.get("files") or []
    req["files"] = [{"rel_path": f} if isinstance(f, str) else f for f in files]
    root = Path(getattr(a, "root", None) or (call.request or {}).get("root") or (base or {}).get("root") or ".")
    return req, root


# ---------------------------------------------------------------- extract

@cli.command("extract_prepare", help="读文件、取关键词窗口，给出抽取说明（不出数）", arguments=_extract_args)
def extract_prepare_cmd(call: Call) -> Envelope:
    req, root = _extract_request(call)
    prep = service.extract_prepare(req, root)
    data = dict(prep)
    data["request"] = {**prep["request"], "root": str(root)}
    if call.out_dir is not None:
        call.out_dir.mkdir(parents=True, exist_ok=True)
        ins = call.out_dir / INSTRUCTIONS_NAME
        ins.write_text(f"<!-- prompt_version: {prep['prompt_version']} · prepare_fingerprint: "
                       f"{prep['prepare_fingerprint']} -->\n\n{prep['instructions']}\n", encoding="utf-8", newline="\n")
        texts = []
        for n, f in enumerate(prep["files"], start=1):
            path = call.out_dir / f"概算抽取正文-{n:02d}.txt"
            path.write_text(f"file_id: {f['file_id']}\nfile_name: {f['file_name']}\n"
                            f"window_sha256: {f['window_sha256']}\n\n正文：\n{f['window']}\n",
                            encoding="utf-8", newline="\n")
            texts.append(path.as_posix())
        data["artifacts"] = {"instructions": ins.as_posix(), "texts": texts}
    total = len(req.get("files") or [])
    coverage = {"files_total": total, "files_used": len(prep["files"]),
                "skipped": [{"file_name": u["label"], "stage": "extract", "reason": u["detail"]}
                            for u in prep["unresolved"]]}
    warns = warning_items(prep["warnings"])
    if prep["unresolved"]:
        warns.append(WarningItem(code="source_no_text", level="warn",
                                 message=f"{len(prep['unresolved'])} 份文件读不出正文，未纳入抽取：见 data.unresolved"))
        return partial(data, coverage=coverage, warnings=warns, reason="source_no_text")
    return ok(data, coverage=coverage, warnings=warns)


def _finalize_args(p: argparse.ArgumentParser) -> None:
    _extract_args(p)
    p.add_argument("--prepare", dest="prepare_result", help="extract_prepare 的 result.json（取回输入与指纹）")
    p.add_argument("--answers", help="agent 的回答 JSON：{\"files\": [{file_id, buildings, checks, cells}]}")


@cli.command("extract_finalize", help="按 agent 的回答核引文、解析数值、单体归位、合并", arguments=_finalize_args)
def extract_finalize_cmd(call: Call) -> Envelope:
    base: dict = {}
    fingerprint = None
    prep_path = call.args.prepare_result or (call.request or {}).get("prepare_result")
    if prep_path:
        env = read_json(prep_path)
        pdata = env.get("data") if isinstance(env, dict) else None
        if not isinstance(pdata, dict) or "prepare_fingerprint" not in pdata:
            raise ZtError("invalid_prepare", f"不是 extract_prepare 的结果文件：{prep_path}")
        base = dict(pdata.get("request") or {})
        fingerprint = pdata["prepare_fingerprint"]
    req, root = _extract_request(call, base)
    req.pop("root", None)
    answers = read_json(call.args.answers) if call.args.answers else (call.request or {}).get("answers")
    if answers is None:
        raise ZtError("no_answers", "没有给出抽取回答", hint="--answers answers.json（格式见 概算抽取说明.md 末尾）")
    res = service.extract_finalize(req, root, answers, fingerprint)
    files_total = len(req.get("files") or [])
    used = len({c.get("file_id") for c in res["text_stats"]})
    no_text = [u for u in res["unresolved"] if u.get("reason") == "no_text"]
    coverage = {"files_total": files_total, "files_used": used,
                "candidates": len(res["candidates"]), "unresolved": len(res["unresolved"]),
                "skipped": [{"file_name": u["label"], "stage": "extract", "reason": u["detail"]} for u in no_text]}
    warns = warning_items(res["warnings"])
    if not res["candidates"]:
        return empty("no_candidates", coverage=coverage, warnings=warns, data=res)
    if no_text:
        warns.append(WarningItem(code="source_no_text", level="warn",
                                 message=f"{len(no_text)} 份文件读不出正文，未纳入抽取：见 data.unresolved"))
        return partial(res, coverage=coverage, warnings=warns, reason="source_no_text")
    return ok(res, coverage=coverage, warnings=warns)


# ---------------------------------------------------------------- suggest

def _suggest_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--baselines", help="指标基准 JSON（数组，或带 rows 的对象）；覆盖请求里的 baselines")
    _template_arg(p)


@cli.command("suggest", help="规模 + 指标基准 → 成本位建议值与其他费建议", arguments=_suggest_args)
def suggest_cmd(call: Call) -> Envelope:
    req = dict(call.request or {})
    if call.args.baselines:
        b = read_json(call.args.baselines)
        req["baselines"] = b.get("rows") if isinstance(b, dict) else b
    if call.args.template_code:
        req["template_code"] = call.args.template_code
    defaulted = "baselines" not in req
    if defaulted:
        req["baselines"] = service.default_baselines(req.get("template_code") or "gsyz_v1")
    res = service.suggest(req)
    if defaulted:
        res["warnings"].insert(0, {"code": "baselines_default_sample", "cell": None, "level": "info",
                                   "message": f"未给指标基准，用随包样本基准（{len(req['baselines'])} 行，单一来源 gsyz_v1）："
                                              "建议值只作单样本参考，不自动预填"})
    for s in res["suggestions"]:
        manual(s)
    for f in res["fee"]:
        manual(f)
    coverage = dict(res["coverage"]) or {"suggestions": 0}
    warns = warning_items(res["warnings"])
    if not res["suggestions"] and not res["fee"]:
        reason = "no_baselines" if not req.get("baselines") else "no_suggestions"
        return empty(reason, coverage=coverage, warnings=warns, data=res)
    return ok(res, coverage=coverage, warnings=warns)


# ---------------------------------------------------------------- compute

def _compute_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--xlsx", help=f"xlsx 输出路径；缺省为 --out 目录下的 {XLSX_NAME}")
    p.add_argument("--no-render", action="store_true", help="只求值、不出 xlsx")
    _template_arg(p)


@cli.command("compute", help="确认过的 inputs → 公式求值 + 真公式 xlsx", arguments=_compute_args)
def compute_cmd(call: Call) -> Envelope:
    req = dict(call.request or {})
    if call.args.template_code:
        req["template_code"] = call.args.template_code
    if call.args.no_render:
        req["render"] = False
    target: Optional[Path] = Path(call.args.xlsx) if call.args.xlsx else (
        call.out_dir / XLSX_NAME if call.out_dir is not None else None)
    if req.get("render", True) and target is None:
        raise ZtError("no_output", "要出 xlsx 但没有给出路径", hint="--out 工作/<日期>-概算/ 或 --xlsx 路径，或 --no-render")
    try:
        res, xlsx = service.compute(req)
    except service.GateRejected as e:
        return insufficient(e.code, data={"detail": e.detail, "gate": e.code},
                            warnings=[WarningItem(code=e.code, level="error", message=e.detail)])
    for t in res["totals"].values():
        manual(t)
    for i in res["indicators"]:
        manual(i)
    if xlsx is not None and target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(xlsx)
        res["artifacts"] = {"xlsx": target.as_posix()}
    level = (res.get("quality") or {}).get("review_level")
    reason = level if level and level != "ok" else None
    env = ok(res, coverage=res["input_coverage"], warnings=warning_items(res["warnings"]))
    env.status_reason = reason
    return env


# ---------------------------------------------------------------- template

@cli.command("template", help="模板元数据（行树、输入位、必填位、告警码字典、策略）", arguments=_template_arg)
def template_cmd(call: Call) -> Envelope:
    code = call.args.template_code or (call.request or {}).get("template_code") or "gsyz_v1"
    payload: dict[str, Any] = service.template(code)
    return ok(payload, coverage={"inputs": len(payload["inputs"]), "required_inputs": len(payload["required_inputs"])})


if __name__ == "__main__":
    raise SystemExit(cli.main())
