#!/usr/bin/env python3
"""zt-ask：核对回答里的数字与引用是否有出处（数字回链到读过的资料文本，引用指向读过的文件与位置）。

等价于 ``python -m zt.textextract.cli check-answer``，调用者只写参数。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
import zt_launch  # noqa: E402  解释器与 zt 定位：../../_shared/zt_launch.py

zt_launch.ensure(__file__)

from zt.textextract.cli import cli  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cli.main(["check-answer", *sys.argv[1:]]))
