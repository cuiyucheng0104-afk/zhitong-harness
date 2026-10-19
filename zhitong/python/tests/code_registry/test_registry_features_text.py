# 来源：engine-service/tests/test_registry_features_text.py（zhitong-cost-ai@991ff5cd）
"""码表 features_text 编号 lint（WS08-A，承接 WS11 QTY-14 的数据修正；issue #724）。

gb50854_zj2025.yaml 的特征模板曾有：56 条从 1 重新起编（「1.建筑做法名称：\\n1.防水膜品种…」）、
011102003 缺 9（8 之后直接 10）、010502028 有两个 3、010601001 一行里并列三个槽、
若干条整条没有编号。工程量清单生成（quantity_list.py:278）原样写进交付物 D 列。

修正口径：每条编码的槽位从 1 连续编号、一行一个槽，标签文字逐字保留（只动编号与分隔空白）。
变异验收：把任一条改回旧编号（如 011102003 的「10.防护层要求」）→ 本文件转红。
"""
from __future__ import annotations

import re

from zt.code_registry import registry as code_registry

_SLOT = re.compile(r"^(\d{1,2})\.(.+)$")


def _slots(ft: str) -> list[tuple[int, str]]:
    out = []
    for line in ft.split("\n"):
        if not line.strip():
            continue
        m = _SLOT.match(line)
        assert m, f"特征行没有「N.」编号：{line!r}"
        out.append((int(m.group(1)), m.group(2)))
    return out


def test_slot_numbering_consecutive_for_all_registry_codes():
    reg = code_registry.load_registry("zj2025")
    assert len(reg) == 490
    bad = {}
    for code, item in reg.items():
        ft = item["features_text"] or ""
        if not ft.strip():
            continue
        nums = [n for n, _ in _slots(ft)]
        if nums != list(range(1, len(nums) + 1)):
            bad[code] = nums
    assert not bad, f"这些编码的特征编号不连续：{dict(list(bad.items())[:10])}"


def test_one_slot_per_line():
    """一行只能有一个槽：010601001 曾把三个槽写在同一行，渲染后编号错位。"""
    reg = code_registry.load_registry("zj2025")
    for code, item in reg.items():
        for line in (item["features_text"] or "").split("\n"):
            assert len(re.findall(r"(?:^|\s)\d{1,2}\.(?!\d)", line)) <= 1, f"{code} 一行多个槽：{line!r}"


def test_known_defects_are_fixed():
    reg = code_registry.load_registry("zj2025")
    assert len(_slots(reg["011102003"]["features_text"])) == 9, "011102003 应输出 9 个槽"
    assert [n for n, _ in _slots(reg["010502028"]["features_text"])] == list(range(1, 10))
    assert _slots(reg["010601001"]["features_text"])[:3] == [
        (1, "结构形式 、跨度"), (2, "杆件钢材品种及规格"), (3, "节点形式 、连接方式")]
    assert _slots(reg["010905002"]["features_text"])[:2] == [(1, "建筑做法名称："), (2, "防水膜品种")]
    assert reg["010202011"]["features_text"] == "1.构件部位"
