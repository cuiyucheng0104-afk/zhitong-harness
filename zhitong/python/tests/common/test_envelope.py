"""结果信封的组合约束。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from zt.common import (
    Envelope,
    FileCoverage,
    WarningItem,
    WarningLevel,
    empty,
    insufficient,
    manual,
    ok,
    partial,
)

WARN = WarningItem(code="missing_sheet", level=WarningLevel.WARN, message="缺少汇总表")


def test_ok_requires_data() -> None:
    with pytest.raises(ValidationError, match="空 data"):
        Envelope(status="ok")
    env = ok({"total": manual({"amount": "12.30"})})
    assert env.to_json() == {
        "status": "ok",
        "status_reason": None,
        "coverage": {},
        "warning_items": [],
        "data": {"total": {"amount": "12.30", "needs_manual": True}},
        "needs_manual": True,
    }


def test_partial_requires_coverage_and_warning() -> None:
    with pytest.raises(ValidationError, match="coverage"):
        Envelope(status="partial", data={"a": 1}, warning_items=[WARN])
    with pytest.raises(ValidationError, match="level≥warn"):
        Envelope(
            status="partial",
            data={"a": 1},
            coverage={"files_total": 2, "files_used": 1},
            warning_items=[WarningItem(code="note", level="info", message="提示")],
        )
    env = partial({"a": 1}, coverage=FileCoverage(files_total=2, files_used=1).model_dump(), warnings=[WARN])
    assert env.status.value == "partial"


@pytest.mark.parametrize("factory", [empty, insufficient])
def test_empty_and_insufficient_require_reason(factory) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValidationError, match="status_reason"):
        Envelope(status=factory.__name__)
    env = factory("no_source_files")
    assert env.to_json()["status_reason"] == "no_source_files"


def test_status_reason_and_codes_are_machine_codes() -> None:
    with pytest.raises(ValidationError):
        empty("没有文件")
    with pytest.raises(ValidationError):
        WarningItem(code="Bad-Code", level="warn", message="x")


def test_needs_manual_is_forced_true() -> None:
    env = Envelope(status="empty", status_reason="nothing", needs_manual=False)  # type: ignore[arg-type]
    assert env.needs_manual is True


def test_extra_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        Envelope.model_validate({"status": "ok", "data": {"a": 1}, "surprise": 1})


def test_file_coverage_bounds() -> None:
    with pytest.raises(ValidationError, match="files_used"):
        FileCoverage(files_total=1, files_used=2)


def test_warning_evidence_rejects_absolute_paths() -> None:
    for bad in ["/etc/passwd", "C:\\work\\a.xlsx", "\\\\nas\\share\\a.xlsx", "D:/x.pdf"]:
        with pytest.raises(ValidationError, match="绝对路径"):
            WarningItem(code="x", level="warn", message="m", evidence=[{"rel_path": bad}])
    item = WarningItem(code="x", level="warn", message="m", evidence=[{"rel_path": "资料/合同.pdf", "page": 3, "quote": "甲" * 250}])
    assert item.evidence is not None
    assert len(item.evidence[0].quote or "") == 200
