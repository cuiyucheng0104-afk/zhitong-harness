"""单方造价、章节占比与对标 CLI。

用法::

    python -m zt.indicator.cli run --files 计价表1.xlsx 计价表2.xlsx --gross-area 12000 --out 工作/<日期>-指标/

``--baseline baseline.json`` 给对标输入（``indicator_baselines`` 或 ``peer_library``，见
:class:`zt.indicator.service.IndicatorRequest`）；也可以整份请求放进 ``--in``，命令行参数优先。
"""
from __future__ import annotations

import argparse

from zt.common import Call, Cli, Envelope
from zt.common.jsonio import read_json
from zt.costsheet import service as svc
from zt.costsheet.cli_args import add_limit_args, artifacts
from zt.indicator import service

cli = Cli("zt.indicator", "单方造价、章节占比与同类对标（零模型）")


def _args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--files", nargs="+", help="计价表 xlsx/xlsm，可多份")
    p.add_argument("--gross-area", type=float, help="总建筑面积（㎡）")
    p.add_argument("--area-source", help="面积来源说明，例如 项目说明 / 用户提供")
    p.add_argument("--total-amount", type=float, help="用户给定的含税总造价（元），优先于费用表合计")
    p.add_argument("--baseline", help="对标输入 JSON 文件")
    add_limit_args(p)


@cli.command("run", help="计算指标", arguments=_args)
def run(call: Call) -> Envelope:
    req = dict(call.request or {})
    a = call.args
    if a.files:
        req["price_files"] = a.files
    for key in ("gross_area", "area_source", "total_amount"):
        if getattr(a, key) is not None:
            req[key] = getattr(a, key)
    if a.baseline:
        req["baseline"] = read_json(a.baseline)
    request = svc.parse_request(service.IndicatorRequest, req)
    env = service.run(request, max_files=a.max_files, max_total_mb=a.max_total_mb)
    return artifacts(call, env, service.XLSX_NAME, service.export_xlsx)


if __name__ == "__main__":
    raise SystemExit(cli.main())
