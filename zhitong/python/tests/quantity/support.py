"""清单用例的转接：旧用例调 ``quantity_list.run(files, …)``（内部打桩 LLM），这里换成 prepare → 假 agent 作答 → finalize。

:func:`run` 的返回值是 finalize 结果再加 ``xlsx_bytes``（render 的产物）与 ``prepare``（prepare 结果），
旧用例按键断言照旧写。拒绝类结果（out_of_scope / no_practice / no_items …）照旧抛
:class:`zt.quantity.pipeline.QuantityRejected`。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from zt.quantity import pipeline
from zt.quantity.render import render_xlsx

PYTHON_ROOT = Path(__file__).resolve().parents[2]


def run(files, version: str = "zj2025", pdf_loader=None, *, agent, **kw) -> dict:
    """prepare → agent 作答 → finalize（有特征任务且 agent 会摘录时再 finalize 一次）→ render。

    :param files: ``[(字节, 文件名, 扩展名)]``。
    :param version: 码表版本。
    :param pdf_loader: PDF 读取回调。
    :param agent: :class:`tests.quantity.fixtures.shapes.FakeAgent`。
    :returns: finalize 结果 + ``xlsx_bytes`` + ``prepare``。
    """
    prep = pipeline.prepare(files, version, pdf_loader, **kw)
    answers = agent.answer(prep)
    fp = prep["prepare_fingerprint"]
    out = pipeline.finalize(files, answers, version, pdf_loader, prepare_fingerprint=fp, **kw)
    if out["feature_tasks"] and agent.features is not None:
        answers = {**answers, "f": agent.answer_features(out["feature_tasks"])}
        out = pipeline.finalize(files, answers, version, pdf_loader, prepare_fingerprint=fp, **kw)
    out["xlsx_bytes"] = render_xlsx(out)
    out["prepare"] = prep
    out["answers"] = answers
    return out


def run_cli(module: str, *args: str, cwd: Optional[Path] = None) -> tuple[int, Any]:
    """以子进程跑 ``python -m <module>``：stdout 只有一个 JSON。

    :param module: 模块，例如 ``zt.quantity.cli``。
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
