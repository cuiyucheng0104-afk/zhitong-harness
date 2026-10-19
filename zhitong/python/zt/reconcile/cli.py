"""送审 vs 审定计价表核对 CLI。

用法::

    python -m zt.reconcile.cli run --submitted 送审.xlsx --approved 审定.xlsx [--basis auto] --out 工作/<日期>-核对/

也可以 ``--in request.json``（字段见 :class:`zt.reconcile.service.ReconcileRequest`），命令行参数优先。
给了 ``--out`` 时，完整结果写到 ``<out>/result.json``，工作底稿写到同目录 ``核对结果.xlsx``，
stdout 只输出摘要；没给 ``--out`` 时 stdout 输出完整信封、不写 xlsx。
"""
from __future__ import annotations

import argparse

from zt.common import Call, Cli, Envelope
from zt.costsheet import service as svc
from zt.costsheet.cli_args import add_limit_args, artifacts
from zt.reconcile import service

cli = Cli("zt.reconcile", "送审与审定计价表核对（零模型）")


def _args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--submitted", help="送审计价表 xlsx/xlsm")
    p.add_argument("--approved", help="审定计价表 xlsx/xlsm")
    p.add_argument("--basis", choices=svc.BASIS_CHOICES, help="对比口径，默认 auto")
    add_limit_args(p)


@cli.command("run", help="核对两张计价表", arguments=_args)
def run(call: Call) -> Envelope:
    req = dict(call.request or {})
    a = call.args
    if a.submitted:
        req["submitted_file"] = a.submitted
    if a.approved:
        req["approved_file"] = a.approved
    if a.basis:
        req["basis"] = a.basis
    request = svc.parse_request(service.ReconcileRequest, req)
    env = service.run(request, max_files=a.max_files, max_total_mb=a.max_total_mb)
    return artifacts(call, env, service.XLSX_NAME, service.export_xlsx)


if __name__ == "__main__":
    raise SystemExit(cli.main())
