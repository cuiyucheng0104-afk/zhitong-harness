#!/usr/bin/env python3
"""W8 迁移：从 mysqldump 或 JSON 行文件导出旧系统 project / project_file（及 knowledge_file），写 projects.json 与 files.json。

在 ECS 上运行，用法与参数见 runbook.md 与 `--help`。本脚本只做 `zt` 定位：把旁边的 `../python`
放进 `sys.path` 后调用 `zt.migration.cli.export_main`；需要 Python ≥ 3.11 与 zt 的依赖（runbook 第 1 步）。
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print('{"error": {"code": "python_too_old", "message": "需要 Python 3.11 或更高", '
          '"hint": "按 runbook 第 1 步用 uv run 或 python3.11 运行"}}')
    raise SystemExit(2)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from zt.migration.cli import export_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(export_main())
