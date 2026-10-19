#!/usr/bin/env python3
"""zt-ask：读项目里一份文件的正文（文字层 / 旁车），扫描件提示用 read_image 看图。

等价于 ``python -m zt.textextract.cli extract``，调用者只写参数。
"""
from __future__ import annotations

import sys

from zt.textextract.cli import cli

if __name__ == "__main__":
    raise SystemExit(cli.main(["extract", *sys.argv[1:]]))
