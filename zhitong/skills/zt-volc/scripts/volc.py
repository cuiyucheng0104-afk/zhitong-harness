"""zt-volc 薄 CLI：火山引擎运维，参数与 ``python -m zt.volc.cli`` 相同（见 ../SKILL.md）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
import zt_launch  # noqa: E402  解释器与 zt 定位：../../_shared/zt_launch.py

zt_launch.ensure(__file__)

from zt.volc.cli import cli

if __name__ == "__main__":
    raise SystemExit(cli.main())
