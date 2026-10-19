"""投控异常检测与复核记录 CLI。

用法::

    python -m zt.tk.cli detect --files 送审1.xlsx 送审2.xlsx [--baseline-files 合同清单.xlsx] \\
        [--basis auto] [--project-id 2026-007] --out 工作/<日期>-投控/
    python -m zt.tk.cli review --result 工作/<日期>-投控/result.json --log 工作/<日期>-投控/复核.jsonl \\
        --anomaly-id <id> --state dismissed --reason "合同清单第 12 行单价相同，属同价分行"
    python -m zt.tk.cli progress --result 工作/<日期>-投控/result.json --log 工作/<日期>-投控/复核.jsonl

``detect`` 也可以 ``--in request.json``（字段见 :class:`zt.tk.service.TkRequest`），命令行参数优先；
``--rules`` 换用另一份阈值配置（默认随包的 ``zt/tk/data/tk_detect.yaml``，版本 v1-20260711，客户侧仍为 draft）。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from zt.common import Call, Cli, Envelope, ZtError, ok
from zt.common.jsonio import read_json
from zt.costsheet import service as svc
from zt.costsheet.cli_args import add_limit_args, artifacts
from zt.tk import review, service

cli = Cli("zt.tk", "投控异常检测（零模型）与人工复核记录")


def _detect_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--files", nargs="+", help="送审计价表 xlsx/xlsm，可多份")
    p.add_argument("--baseline-files", nargs="+", help="合同/中标清单 xlsx/xlsm，可多份")
    p.add_argument("--basis", choices=svc.BASIS_CHOICES, help="送审文件的期次口径，默认 auto")
    p.add_argument("--project-id", help="项目编号（进入异常身份 anomaly_id）")
    p.add_argument("--rules", help="阈值配置 YAML；默认随包的 tk_detect.yaml")
    add_limit_args(p)


@cli.command("detect", help="检测送审计价表里的疑似异常", arguments=_detect_args)
def detect(call: Call) -> Envelope:
    req = dict(call.request or {})
    a = call.args
    if a.files:
        req["submission_files"] = a.files
    if a.baseline_files:
        req["baseline_files"] = a.baseline_files
    if a.basis:
        req["basis"] = a.basis
    if a.project_id is not None:
        req["project_id"] = a.project_id
    request = svc.parse_request(service.TkRequest, req)
    rules = Path(a.rules) if a.rules else None
    if rules is not None and not rules.is_file():
        raise ZtError("input_not_found", f"找不到阈值配置：{a.rules}")
    env = service.run(request, rules_path=rules, max_files=a.max_files, max_total_mb=a.max_total_mb)
    return artifacts(call, env, service.XLSX_NAME, service.export_xlsx)


def _log_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--result", required=True, help="detect 写出的 result.json")
    p.add_argument("--log", required=True, help="复核日志 复核.jsonl（只追加）")


def _review_args(p: argparse.ArgumentParser) -> None:
    _log_args(p)
    p.add_argument("--anomaly-id", required=True, help="异常 ID")
    p.add_argument("--state", required=True, choices=review.STATES, help="confirmed / dismissed / pending")
    p.add_argument("--reason", required=True, help="复核理由")
    p.add_argument("--reviewer", help="复核人")


def _load_result(path: str) -> dict:
    result = read_json(path)
    if not isinstance(result, dict) or "data" not in result:
        raise ZtError("invalid_result_file", f"{path} 不是 detect 写出的完整结果（缺 data）",
                      hint="detect 给 --out 时完整结果在 <out>/result.json")
    return result


@cli.command("review", help="追加一条人工复核决定", arguments=_review_args)
def review_cmd(call: Call) -> Envelope:
    a = call.args
    index = service.anomaly_index(_load_result(a.result))
    if a.anomaly_id not in index:
        raise ZtError("anomaly_not_found", f"本轮检测结果里没有异常 {a.anomaly_id}",
                      hint="anomaly_id 从 result.json 的 data.anomalies[].anomaly_id 复制")
    log_path = Path(a.log)
    rec = review.append_decision(log_path, a.anomaly_id, a.state, a.reason,
                                 anomaly=index[a.anomaly_id], reviewer=a.reviewer)
    return ok(svc.mark_manual({"record": rec, "progress": review.progress(list(index), review.read_log(log_path))}))


@cli.command("progress", help="查看本轮异常的复核进度", arguments=_log_args)
def progress_cmd(call: Call) -> Envelope:
    a = call.args
    ids = list(service.anomaly_index(_load_result(a.result)))
    return ok({"progress": review.progress(ids, review.read_log(Path(a.log)))})


if __name__ == "__main__":
    raise SystemExit(cli.main())
