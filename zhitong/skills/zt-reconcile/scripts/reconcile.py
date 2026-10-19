"""zt-reconcile 薄 CLI：送审 vs 审定计价表核对，参数与 ``python -m zt.reconcile.cli`` 相同（见 ../SKILL.md）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
import zt_launch  # noqa: E402  解释器与 zt 定位：../../_shared/zt_launch.py

zt_launch.ensure(__file__)

from zt.reconcile.cli import cli

if __name__ == "__main__":
    raise SystemExit(cli.main())
