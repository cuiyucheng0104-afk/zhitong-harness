#!/usr/bin/env python3
"""W8 迁移：镜像与 files.json、NAS 源文件、manifest.json 对账；有任何不一致退出码 2。

在 ECS 上运行，用法与参数见 runbook.md 与 `--help`。本脚本只做 `zt` 定位：把旁边的 `../python`
放进 `sys.path` 后调用 `zt.migration.cli.verify_main`；需要 Python ≥ 3.11 与 zt 的依赖（runbook 第 1 步）。
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print('{"error": {"code": "python_too_old", "message": "需要 Python 3.11 或更高", '
          '"hint": "按 runbook 第 1 步用 uv run 或 python3.11 运行"}}')
    raise SystemExit(2)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from zt.migration.cli import verify_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(verify_main())
