"""zt-estimate 薄 CLI：参数与 ``python -m zt.estimate.cli`` 相同（extract_prepare / extract_finalize / suggest / compute / template，见 ../SKILL.md）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
import zt_launch  # noqa: E402  解释器与 zt 定位：../../_shared/zt_launch.py

zt_launch.ensure(__file__)

from zt.estimate.cli import cli

if __name__ == "__main__":
    raise SystemExit(cli.main())
