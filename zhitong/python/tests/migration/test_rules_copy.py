"""migration/data/classify_rules.yaml 是 zt-project 那份的副本：除文件头两行外逐字相同。"""
from __future__ import annotations

from zt.migration.relayout import DEFAULT_RULES, ZHITONG_ROOT


def test_rules_copy_matches_zt_project() -> None:
    copy = DEFAULT_RULES.read_text(encoding="utf-8").splitlines(keepends=True)
    origin = (ZHITONG_ROOT / "skills" / "zt-project" / "data" / "classify_rules.yaml").read_text(encoding="utf-8")
    assert copy[0].startswith("# W8 迁移副本") and copy[1].startswith("# relayout.py")
    assert "".join(copy[2:]) == origin
