#!/usr/bin/env python3
"""zt-project：资料盘点。只报缺件，不打标签。

用法见 ../SKILL.md；等价于 ``python -m zt.inventory.cli scan``，并把数据目录指向本 skill 的 ``data/``。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
import zt_launch  # noqa: E402  解释器与 zt 定位：../../_shared/zt_launch.py

zt_launch.ensure(__file__)

import os

os.environ.setdefault("ZT_PROJECT_DATA", str(Path(__file__).resolve().parent.parent / "data"))

from zt.inventory.cli import cli  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cli.main())
