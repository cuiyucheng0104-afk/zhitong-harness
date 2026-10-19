"""zt-reconcile 薄 CLI：送审 vs 审定计价表核对，参数与 ``python -m zt.reconcile.cli`` 相同（见 ../SKILL.md）。"""
from zt.reconcile.cli import cli

if __name__ == "__main__":
    raise SystemExit(cli.main())
