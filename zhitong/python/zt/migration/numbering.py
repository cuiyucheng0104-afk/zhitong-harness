"""迁移时给旧项目分配项目编号（spec §5、§6 第 1 条）。

规则：

1. 已分配过的（状态文件 ``numbering.json`` 里有的旧 ``project.id``）沿用原编号：重跑不改号；
2. 客户现有编号（``project.report_code``，见 :data:`ALIAS_FIELD`）本身就是 ``YYYY-NNN`` 且未被占用的，直接用作编号；
3. 其余按建项目年份（``create_time`` 的年）+ 当年流水号分配，流水号取当年已用最大值加一，按
   ``(create_time, id)`` 排序依次分配；超过 999 报错。

客户编号不是 ``YYYY-NNN`` 时不进目录名（spec §5），只记在项目说明的「别名」里：目录名与 ``项目说明.md``
的 ``项目编号`` 字段由 ``zt.common.paths.PROJECT_CODE`` 校验，其他格式的编号会让 zt-project / zt-archive 拒收。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from zt.common import ZtError
from zt.common.paths import PROJECT_CODE

ALIAS_FIELD = "alias"


@dataclass(frozen=True)
class Assignment:
    """一个项目的编号。

    :ivar code: 项目编号 ``YYYY-NNN``。
    :ivar origin: ``state``（沿用上次）/ ``client``（客户编号）/ ``allocated``（按年流水分配）。
    """

    code: str
    origin: str


def assign_codes(projects: list[dict[str, Any]], state: dict[str, str]) -> dict[str, Assignment]:
    """给每个项目定编号。

    :param projects: ``projects.json`` 的项目（含 ``id``、``create_time``、``alias``）。
    :param state: 上次运行保存的 ``{project.id: 编号}``。
    :returns: ``{project.id: Assignment}``。
    :raises ZtError: 状态文件里两个项目同号（``numbering_state_conflict``），或某年流水号超过 999
        （``numbering_overflow``）。
    """
    used: dict[str, str] = {}
    out: dict[str, Assignment] = {}
    live_ids = {p["id"] for p in projects}
    for pid, code in sorted(state.items()):
        if not PROJECT_CODE.match(code):
            raise ZtError("numbering_state_conflict", f"编号状态文件里的编号格式不对：{pid} → {code!r}")
        if code in used and used[code] != pid:
            raise ZtError("numbering_state_conflict", f"编号状态文件里 {used[code]} 与 {pid} 都是 {code}")
        used[code] = pid
        if pid in live_ids:
            out[pid] = Assignment(code, "state")
    ordered = sorted(projects, key=lambda p: (p["create_time"], p["id"]))
    for p in ordered:
        if p["id"] in out:
            continue
        alias = (p.get(ALIAS_FIELD) or "").strip()
        if PROJECT_CODE.match(alias) and alias not in used:
            used[alias] = p["id"]
            out[p["id"]] = Assignment(alias, "client")
    for p in ordered:
        if p["id"] in out:
            continue
        year = int(str(p["create_time"])[:4])
        seq = max((int(c[5:]) for c in used if c.startswith(f"{year}-")), default=0) + 1
        if seq > 999:
            raise ZtError("numbering_overflow", f"{year} 年的项目编号超过 999")
        code = f"{year}-{seq:03d}"
        used[code] = p["id"]
        out[p["id"]] = Assignment(code, "allocated")
    return out
