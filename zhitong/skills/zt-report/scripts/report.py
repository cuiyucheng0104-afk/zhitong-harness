#!/usr/bin/env python3
"""zt-report 薄 CLI：报告初稿的取材、金额事实、逐章 prepare / finalize、导出与套正式模板。

用法见 ../SKILL.md；等价于 ``python -m zt.report.cli``，并把数据目录指向本 skill 的 ``data/``。
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("ZT_REPORT_DATA", str(Path(__file__).resolve().parent.parent / "data"))

from zt.report.cli import cli  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cli.main())
