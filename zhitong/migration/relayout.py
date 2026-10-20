#!/usr/bin/env python3
"""W8 迁移：只读旧 NAS，按 spec §6 把资料整理成与桶同构的镜像目录，写 manifest.json 与 整理报告.md。

在 ECS 上运行，用法与参数见 runbook.md 与 `--help`。本脚本只做 `zt` 定位：把旁边的 `../python`
放进 `sys.path` 后调用 `zt.migration.cli.relayout_main`；需要 Python ≥ 3.11 与 zt 的依赖（runbook 第 1 步）。
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print('{"error": {"code": "python_too_old", "message": "需要 Python 3.11 或更高", '
          '"hint": "按 runbook 第 1 步用 uv run 或 python3.11 运行"}}')
    raise SystemExit(2)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from zt.migration.cli import relayout_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(relayout_main())
