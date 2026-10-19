#!/usr/bin/env python3
"""zt-ask：在项目里按字面量检索 docx / xlsx / PDF / 文本，返回文件 + 页 / 工作表行 / 段落定位。

等价于 ``python -m zt.textextract.cli search``，调用者只写参数。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
import zt_launch  # noqa: E402  解释器与 zt 定位：../../_shared/zt_launch.py

zt_launch.ensure(__file__)

from zt.textextract.cli import cli

if __name__ == "__main__":
    raise SystemExit(cli.main(["search", *sys.argv[1:]]))
