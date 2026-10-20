"""项目编号：当年流水、客户编号直接用、非 YYYY-NNN 的客户编号进别名、重跑沿用状态。"""
from __future__ import annotations

import pytest

from zt.common import ZtError
from zt.migration.numbering import assign_codes


def _p(pid: str, created: str, alias: str | None = None) -> dict:
    return {"id": pid, "create_time": created, "alias": alias}


def test_sequence_within_year_by_create_time() -> None:
    codes = assign_codes([_p("b", "2024-05-01T00:00:00"), _p("a", "2024-03-01T00:00:00"),
                          _p("c", "2025-01-01T00:00:00")], {})
    assert {k: v.code for k, v in codes.items()} == {"a": "2024-001", "b": "2024-002", "c": "2025-001"}


def test_client_code_used_and_sequence_continues_after_it() -> None:
    codes = assign_codes([_p("x", "2025-01-01T00:00:00", "2025-010"), _p("y", "2025-02-01T00:00:00"),
                          _p("z", "2025-03-01T00:00:00", "HT-2025-18")], {})
    assert codes["x"].code == "2025-010" and codes["x"].origin == "client"
    assert codes["y"].code == "2025-011" and codes["z"].code == "2025-012"
    assert codes["z"].origin == "allocated"


def test_duplicate_client_code_only_first_keeps_it() -> None:
    codes = assign_codes([_p("x", "2025-01-01T00:00:00", "2025-001"), _p("y", "2025-02-01T00:00:00", "2025-001")], {})
    assert codes["x"].code == "2025-001" and codes["y"].code == "2025-002"


def test_state_is_reused_and_new_projects_follow() -> None:
    state = {"old": "2024-007"}
    codes = assign_codes([_p("new", "2024-01-01T00:00:00"), _p("old", "2024-09-01T00:00:00")], state)
    assert codes["old"].code == "2024-007" and codes["old"].origin == "state"
    assert codes["new"].code == "2024-008"


def test_state_conflict_and_overflow_fail_loud() -> None:
    with pytest.raises(ZtError) as e:
        assign_codes([], {"a": "2024-001", "b": "2024-001"})
    assert e.value.code == "numbering_state_conflict"
    with pytest.raises(ZtError) as e:
        assign_codes([_p("n", "2024-01-01T00:00:00")], {"full": "2024-999"})
    assert e.value.code == "numbering_overflow"
