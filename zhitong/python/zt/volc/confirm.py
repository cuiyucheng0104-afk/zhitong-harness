"""危险操作的确认闸：没有 ``--yes`` 就以结构化错误结束，错误信息写明将要发生什么。

确认本身发生在对话里（SKILL.md 要求先用 ``user-questions`` 向用户展示 ``--dry-run`` 的计划），
本模块只保证脚本不会在没有显式 ``--yes`` 时执行。
"""
from __future__ import annotations

from zt.common.errors import ZtError


def require_confirmation(*, yes: bool, summary: str) -> None:
    """要求显式确认。

    :param yes: 命令行是否带了 ``--yes``。
    :param summary: 一句话说明将要执行的变更及影响，原样进入错误信息。
    :raises ZtError: 未确认（``confirmation_required``）。
    """
    if yes:
        return
    raise ZtError(
        "confirmation_required",
        f"该操作需要确认：{summary}",
        hint="先加 --dry-run 取得计划，用 user-questions 把计划和影响告诉用户；用户同意后原命令加 --yes 重跑",
    )
