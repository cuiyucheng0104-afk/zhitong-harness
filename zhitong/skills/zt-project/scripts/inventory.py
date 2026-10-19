#!/usr/bin/env python3
"""zt-project：资料盘点。只报缺件，不打标签。

用法见 ../SKILL.md；等价于 ``python -m zt.inventory.cli scan``，并把数据目录指向本 skill 的 ``data/``。
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("ZT_PROJECT_DATA", str(Path(__file__).resolve().parent.parent / "data"))

from zt.inventory.cli import cli  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cli.main())
