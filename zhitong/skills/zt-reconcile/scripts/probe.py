"""zt-reconcile 薄 CLI：计价表预检，参数与 ``python -m zt.costsheet.cli`` 相同（见 ../SKILL.md）。"""
from zt.costsheet.cli import cli

if __name__ == "__main__":
    raise SystemExit(cli.main())
