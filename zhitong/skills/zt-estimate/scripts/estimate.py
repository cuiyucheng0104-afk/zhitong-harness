"""zt-estimate 薄 CLI：参数与 ``python -m zt.estimate.cli`` 相同（extract_prepare / extract_finalize / suggest / compute / template，见 ../SKILL.md）。"""
from zt.estimate.cli import cli

if __name__ == "__main__":
    raise SystemExit(cli.main())
