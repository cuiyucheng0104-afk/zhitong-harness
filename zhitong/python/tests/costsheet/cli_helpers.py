"""以子进程跑 ``python -m zt.<area>.cli``：stdout 只有一个 JSON，退出码按约定。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PYTHON_ROOT = Path(__file__).resolve().parents[2]


def run_cli(module: str, *args: str, cwd: Path | None = None) -> tuple[int, Any]:
    """运行 CLI 并解析 stdout。

    :param module: 模块，例如 ``zt.reconcile.cli``。
    :param args: 子命令与参数。
    :param cwd: 工作目录；默认 python 项目根。
    :returns: ``(退出码, stdout 的 JSON)``。
    """
    env = {**os.environ, "PYTHONPATH": str(PYTHON_ROOT), "PYTHONIOENCODING": "ascii"}
    proc = subprocess.run([sys.executable, "-m", module, *args], capture_output=True, cwd=cwd or PYTHON_ROOT,
                          env=env, check=False)
    lines = proc.stdout.decode("utf-8").splitlines()
    assert len(lines) == 1, (lines, proc.stderr.decode("utf-8", "replace"))
    return proc.returncode, json.loads(lines[0])
