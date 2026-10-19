"""核对、指标、投控三个 CLI 共用的参数与附件写出。"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from zt.common import Call, Envelope
from zt.common.envelope import ResultStatus
from zt.costsheet import service as svc


def add_limit_args(p: argparse.ArgumentParser) -> None:
    """添加送检上限参数 ``--max-files`` 与 ``--max-total-mb``。

    :param p: 子命令解析器。
    """
    p.add_argument("--max-files", type=int, default=svc.MAX_FILES, help=f"送检份数上限，默认 {svc.MAX_FILES}")
    p.add_argument("--max-total-mb", type=float, default=svc.MAX_TOTAL_MB,
                   help=f"送检合计大小上限（MB），默认 {svc.MAX_TOTAL_MB:g}")


def artifacts(call: Call, env: Envelope, name: str, export: Callable[[dict, Path], Path]) -> Envelope:
    """给了 ``--out`` 且有结果（ok / partial）时，把工作底稿写到结果目录并在 ``data.artifacts`` 记下路径。

    :param call: 子命令调用。
    :param env: 结果信封。
    :param name: xlsx 文件名。
    :param export: 写出函数 ``(data, path) -> path``。
    :returns: 同一个信封。
    """
    if call.out_dir is None or env.status not in (ResultStatus.OK, ResultStatus.PARTIAL):
        return env
    path = export(env.data, call.out_dir / name)
    env.data["artifacts"] = {"xlsx": path.as_posix()}
    return env
