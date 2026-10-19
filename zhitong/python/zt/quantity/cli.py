"""设计说明 → GB50854 清单框架 CLI（zt-quantity skill）。

三个子命令，全部零模型：

``prepare``  读设计说明、切片，给出待分类片段批次::

    python -m zt.quantity.cli prepare --files 资料/建筑设计说明.docx 资料/做法表.xlsx \\
        --project-name "某某项目III标" --out 工作/2026-10-19-清单/prepare/

  有 ``--out`` 时同目录另写 ``清单分类说明.md``（码表与分类规则）和 ``清单分类批次.md``（逐批片段）。

``finalize`` 读 agent 的回答，过闸、聚合、覆盖核算::

    python -m zt.quantity.cli finalize --prepare 工作/2026-10-19-清单/prepare/result.json \\
        --answers 工作/2026-10-19-清单/answers.json --out 工作/2026-10-19-清单/finalize/

  ``--prepare`` 从 prepare 结果里取回同一组输入参数与 ``prepare_fingerprint``；也可以像 prepare 一样直接给
  ``--files`` 等参数。answers：``{"r": [{"id","role","c","ex","why"}], "f": [{"k","v"}]}``。

``render``   finalize 结果 → 四页 xlsx::

    python -m zt.quantity.cli render --result 工作/2026-10-19-清单/finalize/result.json \\
        --xlsx 工作/2026-10-19-清单/清单框架.xlsx

文件路径都相对 ``--root``（项目目录，默认当前目录）。
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Optional

from zt import code_registry
from zt.common import Call, Cli, Envelope, WarningItem, ZtError, empty, ok, partial, read_json
from zt.common.paths import to_rel_posix
from zt.quantity import pipeline
from zt.quantity.render import render_xlsx
from zt.textextract.extract import load_document
from zt.textextract.files import file_ext, read_project_file

cli = Cli("zt.quantity", "设计说明 → GB50854 清单框架（prepare / finalize / render，零模型）")

INSTRUCTIONS_NAME = "清单分类说明.md"
BATCHES_NAME = "清单分类批次.md"
XLSX_NAME = "清单框架.xlsx"


# ---------------------------------------------------------------- 参数

def _input_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--root", help="项目目录（文件路径相对它），默认当前目录")
    p.add_argument("--files", nargs="+", metavar="资料/x.docx", help="设计说明 / 做法表（xlsx/docx/pdf/txt）")
    p.add_argument("--project-name", help="项目名称（解析标段，如「III标」）")
    p.add_argument("--eng-category", dest="eng_category_name", help="项目工程类别（仅供参考）")
    p.add_argument("--code-version", help="码表版本，默认 zj2025")
    p.add_argument("--max-segments", type=int, help="单次待分类片段上限，默认 800")
    p.add_argument("--batch-max-segments", type=int, help="每批片段数上限，默认 40")
    p.add_argument("--batch-max-chars", type=int, help="每批正文字数上限，默认 6000")


def _finalize_args(p: argparse.ArgumentParser) -> None:
    _input_args(p)
    p.add_argument("--prepare", dest="prepare_result", help="prepare 的 result.json（取回输入参数与指纹）")
    p.add_argument("--answers", help="agent 的回答 JSON：{\"r\": [...], \"f\": [...]}")
    p.add_argument("--prepare-fingerprint", help="prepare 给出的 prepare_fingerprint")


def _render_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--result", help="finalize 的 result.json")
    p.add_argument("--xlsx", help=f"xlsx 输出路径；缺省为 --out 目录下的 {XLSX_NAME}")


_REQUEST_KEYS = ("root", "files", "project_name", "eng_category_name", "code_version", "max_segments",
                 "batch_max_segments", "batch_max_chars")


def _merge_request(call: Call, base: Optional[dict] = None) -> dict:
    req: dict[str, Any] = dict(base or {})
    req.update({k: v for k, v in dict(call.request or {}).items() if v is not None})
    a = call.args
    for k in _REQUEST_KEYS:
        v = getattr(a, k, None)
        if v is not None:
            req[k] = v
    return req


def _file_list(req: dict) -> list[dict]:
    raw = req.get("files")
    if not raw:
        raise ZtError("no_files", "没有给出设计说明文件", hint="--files 资料/建筑设计说明.docx …")
    out: list[dict] = []
    for f in raw:
        if isinstance(f, str):
            f = {"rel_path": f}
        if not isinstance(f, dict) or not isinstance(f.get("rel_path"), str):
            raise ZtError("invalid_request", f"files 的每一项须是相对路径字符串或带 rel_path 的对象：{f!r}")
        out.append({"rel_path": to_rel_posix(f["rel_path"]), "file_id": f.get("file_id"),
                    "display_path": f.get("display_path") or to_rel_posix(f["rel_path"])})
    return out


def _version(req: dict) -> str:
    v = req.get("code_version") or code_registry.DEFAULT_VERSION
    if v not in code_registry.available_versions():
        raise ZtError("unknown_code_version", f"未知码表版本：{v}",
                      hint=f"可用版本：{'、'.join(code_registry.available_versions())}")
    return v


def _load(req: dict):
    root = Path(req.get("root") or ".")
    refs = _file_list(req)
    files = []
    for r in refs:
        name = r["rel_path"].rsplit("/", 1)[-1]
        files.append((read_project_file(root, r["rel_path"]), name, file_ext(name)))

    def pdf_loader(idx: int, _content: bytes, name: str):
        return load_document(root, refs[idx]["rel_path"], file_name=name)

    kw = dict(project_name=req.get("project_name"), eng_category_name=req.get("eng_category_name"),
              file_refs=refs, config=pipeline.QuantityConfig.from_request(req))
    return files, pdf_loader, kw


def _echo(req: dict) -> dict:
    return {k: req.get(k) for k in _REQUEST_KEYS if req.get(k) is not None}


def _warnings(items: list[dict]) -> list[WarningItem]:
    return [WarningItem(code=w["code"], level=w["level"], message=w["message"]) for w in items]


def _rejected(e: pipeline.QuantityRejected) -> Envelope:
    if isinstance(e, pipeline.InputTooLarge):
        raise ZtError(e.reason_code, e.detail, hint="按单体或专业拆分文件，分多次生成")
    data = {"detail": e.detail, "coverage_detail": e.coverage or {}}
    if e.unmatched is not None:
        data["unmatched"] = e.unmatched
    return empty(e.reason_code, warnings=_warnings(e.warning_items), data=data,
                 coverage={"practice_segments": (e.coverage or {}).get("practice_segments", 0)})


def _parse_failed(e: pipeline.ParseFailed) -> ZtError:
    return ZtError("no_text", str(e),
                   hint="扫描件请先用 read_image 看图，把识别文字写成并列旁车 <原件名>.ocr.txt 后再跑；"
                        ".doc/.xls 需本机装 LibreOffice 或另存为 docx/xlsx")


# ---------------------------------------------------------------- prepare

@cli.command("prepare", help="切片并给出待分类片段批次（agent 作答前）", arguments=_input_args)
def prepare_cmd(call: Call) -> Envelope:
    req = _merge_request(call)
    version = _version(req)
    files, loader, kw = _load(req)
    try:
        prep = pipeline.prepare(files, version, loader, **kw)
    except pipeline.ParseFailed as e:
        raise _parse_failed(e) from e
    except pipeline.QuantityRejected as e:
        return _rejected(e)
    data = {k: v for k, v in prep.items() if k not in ("status", "coverage", "warnings", "warning_items")}
    data["request"] = _echo(req)
    if call.out_dir is not None:
        call.out_dir.mkdir(parents=True, exist_ok=True)
        ins = call.out_dir / INSTRUCTIONS_NAME
        bat = call.out_dir / BATCHES_NAME
        ins.write_text(pipeline.instructions_text(prep), encoding="utf-8", newline="\n")
        bat.write_text(pipeline.batches_text(prep), encoding="utf-8", newline="\n")
        data["artifacts"] = {"instructions": ins.as_posix(), "batches": bat.as_posix()}
    return ok(data, coverage=prep["coverage"], warnings=_warnings(prep["warning_items"]))


# ---------------------------------------------------------------- finalize

@cli.command("finalize", help="按 agent 的回答过闸、聚合、覆盖核算", arguments=_finalize_args)
def finalize_cmd(call: Call) -> Envelope:
    base: dict = {}
    fingerprint = None
    prep_path = getattr(call.args, "prepare_result", None) or (call.request or {}).get("prepare_result")
    if prep_path:
        prep = read_json(prep_path)
        pdata = prep.get("data") if isinstance(prep, dict) else None
        if not isinstance(pdata, dict) or "prepare_fingerprint" not in pdata:
            raise ZtError("invalid_prepare", f"不是 prepare 的结果文件：{prep_path}")
        base = dict(pdata.get("request") or {})
        fingerprint = pdata["prepare_fingerprint"]
    req = _merge_request(call, base)
    fingerprint = call.args.prepare_fingerprint or req.get("prepare_fingerprint") or fingerprint
    answers = req.get("answers")
    if call.args.answers:
        answers = read_json(call.args.answers)
    if answers is None:
        raise ZtError("no_answers", "没有给出分类回答", hint="--answers answers.json（格式见 清单分类说明.md 的【输出】）")
    if not isinstance(answers, (dict, list)):
        raise ZtError("invalid_answers", "answers 须是 {\"r\": [...]} 对象或数组")
    version = _version(req)
    files, loader, kw = _load(req)
    try:
        res = pipeline.finalize(files, answers, version, loader, prepare_fingerprint=fingerprint, **kw)
    except pipeline.ParseFailed as e:
        raise _parse_failed(e) from e
    except pipeline.QuantityRejected as e:
        return _rejected(e)
    except pipeline.PrepareMismatch as e:
        raise ZtError("prepare_mismatch", str(e), hint="输入变了：重新跑 prepare，按新批次作答后再 finalize") from e
    except pipeline.AnswersMissing as e:
        raise ZtError("answers_missing", e.detail, hint="answers.r 里每个片段一条，id 照抄 prepare 的片段编号") from e
    except pipeline.CoverageInvariantError as e:
        raise ZtError("coverage_invariant", f"清单生成内部核算不成立，已中止（不出文件）：{e}") from e
    data = {k: v for k, v in res.items() if k not in ("status", "coverage", "warnings", "warning_items")}
    data["request"] = _echo(req)
    warns = _warnings(res["warning_items"])
    if res["status"] == "partial":
        return partial(data, coverage=res["coverage"], warnings=warns, reason="answers_incomplete")
    return ok(data, coverage=res["coverage"], warnings=warns)


# ---------------------------------------------------------------- render

@cli.command("render", help="finalize 结果 → 四页 xlsx", arguments=_render_args)
def render_cmd(call: Call) -> Envelope:
    src = call.args.result or (call.request or {}).get("result")
    env = read_json(src) if src else call.request
    if not isinstance(env, dict) or not isinstance(env.get("data"), dict) or "items" not in env["data"]:
        raise ZtError("invalid_result", "需要 finalize 的 result.json", hint="--result 工作/<日期>-清单/finalize/result.json")
    data = env["data"]
    target = call.args.xlsx or (call.request or {}).get("xlsx")
    if target:
        path = Path(target)
    elif call.out_dir is not None:
        path = call.out_dir / XLSX_NAME
    else:
        raise ZtError("no_output", "没有给出 xlsx 路径", hint="--xlsx 工作/<日期>-清单/清单框架.xlsx 或 --out 目录/")
    path.parent.mkdir(parents=True, exist_ok=True)
    result = {**data, "warning_items": env.get("warning_items") or []}
    path.write_bytes(render_xlsx(result))
    out = {"xlsx": path.as_posix(), "items": len(data.get("items") or []),
           "unmatched": len(data.get("unmatched") or []), "status_of_list": env.get("status")}
    warns = [WarningItem.model_validate(w) for w in env.get("warning_items") or []]
    if env.get("status") == "partial":
        return partial(out, coverage=env.get("coverage") or {"items": out["items"]}, warnings=warns,
                       reason=env.get("status_reason"))
    return ok(out, coverage=env.get("coverage") or {}, warnings=warns)


if __name__ == "__main__":
    raise SystemExit(cli.main())
