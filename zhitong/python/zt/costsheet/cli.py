"""计价表预检 CLI：只回答「这份 Excel 是不是计价表」，不读金额、不调模型。

用法::

    python -m zt.costsheet.cli probe --files a.xlsx b.xlsx c.xls

每份文件一个标签：``kind`` ∈ costsheet（认出了清单表头）/ other（读过了，没有清单表头）/
unknown（没读或没读完，``reason`` 写原因；``.xls`` 不读，提示另存为 xlsx）。
"""
from __future__ import annotations

import argparse

from zt.common import Call, Cli, Envelope
from zt.costsheet import probe_files
from zt.costsheet.service import parse_request

cli = Cli("zt.costsheet", "计价表预检（不读金额、零模型）")


def _args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--files", nargs="+", help="待预检的 Excel 文件")
    p.add_argument("--deadline-ms", type=int, help="总预算毫秒，最多 8000")


@cli.command("probe", help="预检文件是不是计价表", arguments=_args)
def probe(call: Call) -> Envelope:
    req = dict(call.request or {})
    if call.args.files:
        req["files"] = call.args.files
    if call.args.deadline_ms is not None:
        req["deadline_ms"] = call.args.deadline_ms
    return probe_files.run(parse_request(probe_files.ProbeRequest, req))


if __name__ == "__main__":
    raise SystemExit(cli.main())
