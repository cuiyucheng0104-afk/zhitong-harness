"""资料清单：阶段累计口径与咨询类型分套。

来源：/home/user/zhitong-cost-ai/后端/yidu-nas-server/src/main/java/com/yidu/nas/costai/support/AuditScopeResolver.java
（阶段累计口径，旧决策 D60）与 ``CostTagAuditRepository#listChecklistItemsForAudit``（咨询类型分套）。
数据在 data/checklist.yaml，整体【待签核】，见该文件头。

- 选阶段「X」= X 及其之前各阶段（``sort`` 不大于 X）的清单项；码表里查不到阶段直接失败，不猜；
  不选阶段 = 全部阶段，只能由调用方显式要求。
- 咨询类型有专属清单（20002、20003）就用专属的；没有（20001 全过程）才退回通用的 ``ALL``。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from zt.common import ZtError
from zt.inventory.data import read_yaml

ALL = "ALL"
BASIS_CUMULATIVE = "cumulative"
BASIS_ALL_STAGES = "all_stages"
_CODE_RE = re.compile(r"(?<!\d)(2000[123])(?!\d)")


@dataclass(frozen=True)
class Stage:
    """造价阶段码表的一行。"""

    code: str
    name: str
    sort: int


@dataclass(frozen=True)
class StageScope:
    """阶段口径解析结果。

    :ivar selected_stage: 用户选的阶段；None = 全部阶段。
    :ivar stage_codes: 实际纳入的阶段（码表顺序）。
    :ivar basis: ``cumulative`` 或 ``all_stages``。
    """

    selected_stage: Optional[str]
    stage_codes: tuple[str, ...]
    basis: str


@dataclass(frozen=True)
class ChecklistPick:
    """取清单的结果：条目 + 实际用的清单套 + 是否因没有专属清单而退回 ALL。"""

    items: list[dict[str, Any]]
    checklist_set: str
    fallback: bool


@dataclass
class Checklist:
    """加载后的清单。

    :ivar consulting_types: 咨询类型代码 → 名称。
    :ivar stages: 阶段码表（按 sort 升序）。
    :ivar items: 清单条目（字典，键见 data/checklist.yaml）。
    """

    consulting_types: dict[str, str]
    stages: list[Stage]
    items: list[dict[str, Any]] = field(default_factory=list)

    def resolve_consulting_type(self, value: Optional[str]) -> Optional[str]:
        """把咨询类型的代码或名称规整成代码。

        接受 ``20002``、``结算审核``、``结算审核（20002）``、``ALL``。

        :param value: 用户或项目说明里写的咨询类型；空串 / None 表示未指定。
        :returns: 代码（``20001``…）或 ``ALL``；未指定为 None。
        :raises ZtError: 认不出（``invalid_consulting_type``）。
        """
        text = (value or "").strip()
        if not text:
            return None
        if text.upper() == ALL:
            return ALL
        m = _CODE_RE.search(text)
        if m and m.group(1) in self.consulting_types:
            return m.group(1)
        for code, name in self.consulting_types.items():
            if name and name in text:
                return code
        valid = "、".join(f"{n}（{c}）" for c, n in self.consulting_types.items())
        raise ZtError("invalid_consulting_type", f"认不出咨询类型：{value!r}", hint=f"可用：{valid}，或 ALL")

    def stage_scope(self, selected: Optional[str]) -> StageScope:
        """解析阶段口径。

        :param selected: 选的阶段码；None = 全部阶段。
        :returns: 口径。
        :raises ZtError: 码表为空（``no_stages``）或阶段不在码表里（``unknown_stage``）。
        """
        if not self.stages:
            raise ZtError("no_stages", "清单里没有造价阶段码表，无法核查")
        ordered = sorted(self.stages, key=lambda s: s.sort)
        code = (selected or "").strip() or None
        if code is None:
            return StageScope(None, tuple(s.code for s in ordered), BASIS_ALL_STAGES)
        chosen = next((s for s in ordered if s.code == code), None)
        if chosen is None:
            raise ZtError("unknown_stage", f"阶段「{code}」不在阶段码表里",
                          hint="可用：" + "、".join(s.code for s in ordered))
        return StageScope(code, tuple(s.code for s in ordered if s.sort <= chosen.sort), BASIS_CUMULATIVE)

    def pick(self, consulting_code: Optional[str], stage_codes: tuple[str, ...]) -> ChecklistPick:
        """按咨询类型与阶段集合取清单；该类型没有专属清单时退回 ALL。

        :param consulting_code: :meth:`resolve_consulting_type` 的结果；None 或 ``ALL`` 取通用清单。
        :param stage_codes: 纳入的阶段。
        :returns: 清单条目与说明。
        """
        stages = set(stage_codes)

        def select(kind: str) -> list[dict[str, Any]]:
            return [it for it in self.items if it["consulting_type"] == kind and it["stage_code"] in stages]

        if consulting_code and consulting_code != ALL:
            own = select(consulting_code)
            if own:
                return ChecklistPick(own, consulting_code, False)
            return ChecklistPick(select(ALL), ALL, True)
        return ChecklistPick(select(ALL), ALL, False)


def load_checklist(path: Path) -> Checklist:
    """加载 checklist.yaml 并检查条目字段。

    :param path: 文件路径。
    :returns: 清单。
    :raises ZtError: 字段缺失或阶段 / 咨询类型引用不存在（``checklist_invalid``）。
    """
    raw = read_yaml(path)
    stages = [Stage(str(s["stage_code"]), str(s.get("stage_name") or s["stage_code"]), int(s["sort"]))
              for s in raw.get("stages") or []]
    types = {str(t["code"]): str(t["name"]) for t in raw.get("consulting_types") or []}
    stage_codes = {s.code for s in stages}
    items: list[dict[str, Any]] = []
    for it in raw.get("items") or []:
        for key in ("item_id", "consulting_type", "stage_code", "doc_category", "item_name", "requirement_level"):
            if not it.get(key):
                raise ZtError("checklist_invalid", f"清单条目缺字段 {key}：{it!r}")
        if it["stage_code"] not in stage_codes:
            raise ZtError("checklist_invalid", f"清单条目 {it['item_id']} 的阶段不在码表里：{it['stage_code']}")
        if it["consulting_type"] != ALL and it["consulting_type"] not in types:
            raise ZtError("checklist_invalid", f"清单条目 {it['item_id']} 的咨询类型未登记：{it['consulting_type']}")
        items.append({**it, "aliases": list(it.get("aliases") or [])})
    if not items:
        raise ZtError("checklist_invalid", f"清单里没有任何条目：{path}")
    return Checklist(types, sorted(stages, key=lambda s: s.sort), items)
