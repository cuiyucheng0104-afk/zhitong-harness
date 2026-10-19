"""zt 接线层（zt.costsheet.service）：.xls、解析失败、needs_manual、路径与文件标识。"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.costsheet.fixtures import costsheet_shapes as shapes
from zt.common import ZtError
from zt.common.envelope import ResultStatus
from zt.costsheet import service as svc
from zt.indicator import service as indicator
from zt.reconcile import service as reconcile
from zt.tk import service as tk


@pytest.mark.parametrize("name", ["旧版.xls", "OLD.XLS"])
def test_xls_anywhere_makes_the_whole_call_insufficient(tmp_path, name):
    """.xls 不转换：三件套整次 insufficient，提示另存为 xlsx；文件不必存在（不读字节）。"""
    good = shapes.put(shapes.priced_bill(), "控制价.xlsx")
    xls = str(tmp_path / name)
    for env in (
        reconcile.run(reconcile.ReconcileRequest(submitted_file=xls, approved_file=good)),
        indicator.run(indicator.IndicatorRequest(price_files=[good, xls])),
        tk.run(tk.TkRequest(submission_files=[good], baseline_files=[xls])),
    ):
        assert env.status is ResultStatus.INSUFFICIENT and env.status_reason == "xls_unsupported"
        (w,) = env.warning_items
        assert w.level.value == "error" and name in w.message and "另存为" in (w.hint or "")
        assert env.data["xls_files"] == [xls]


def test_parser_reports_xls_unsupported_instead_of_converting():
    from zt.costsheet.parser import parse_costsheet
    out = parse_costsheet(b"\xd0\xcf\x11\xe0", "旧.xls")
    assert out["items"] == []
    assert [w["code"] for w in out["warning_items"]] == ["xls_unsupported"]


def test_parse_failure_is_insufficient_with_the_old_detail():
    unpriced = shapes.put(shapes.unpriced_bill(), "招标清单.xlsx")
    env = indicator.run(indicator.IndicatorRequest(price_files=[unpriced]))
    assert env.status is ResultStatus.INSUFFICIENT and env.status_reason == "parse_failed"
    assert "清单无单价/金额" in env.data["detail"]["message"]
    assert env.warning_items[0].level.value == "error"


def test_basis_rejection_keeps_reason_code_as_status_reason():
    plain = shapes.put(shapes.detail_with_total(), "一标段.xlsx")
    env = tk.run(tk.TkRequest(submission_files=[plain], basis="current"))
    assert env.status is ResultStatus.INSUFFICIENT and env.status_reason == "basis_not_found"
    assert env.data["detail"]["basis_available"] == ["plain"]
    assert env.warning_items[0].hint


def test_amount_objects_carry_needs_manual():
    a = shapes.put(shapes.priced_bill(), "送审.xlsx")
    b = shapes.put(shapes.resaved(shapes.priced_bill()), "审定.xlsx")
    data = reconcile.run(reconcile.ReconcileRequest(submitted_file=a, approved_file=b)).to_json()["data"]
    assert all(r["needs_manual"] is True for r in data["rows"])
    assert all(c["needs_manual"] is True for c in data["chapters"])
    assert data["summary"]["needs_manual"] is True
    assert all(c["needs_manual"] is True for c in data["file_coverage"])


def test_mark_manual_only_marks_objects_with_numeric_amount_like_fields():
    obj = {"rules_run": {"duplicate": "all_rows"}, "rows": [{"amount": None}, {"name": "x"}],
           "summary": {"a_total": "1,234.50"}}
    svc.mark_manual(obj)
    assert "needs_manual" not in obj["rules_run"] and "needs_manual" not in obj["rows"][1]
    assert obj["rows"][0]["needs_manual"] is True and obj["summary"]["needs_manual"] is True


def test_partial_without_engine_warning_gets_a_coverage_warning():
    env = svc.build_envelope({"x": 1}, [], [{"status": "parsed", "level": "partial", "file": "a.xlsx"}], 3)
    assert env.status is ResultStatus.PARTIAL and env.status_reason == "coverage_partial"
    assert [w.code for w in env.warning_items] == ["coverage_partial"]


def test_paths_with_chinese_and_spaces_relative_to_cwd(tmp_path, monkeypatch):
    """路径相对当前目录解析；file_id 缺省为调用方写的路径原文，file_name 为文件名。"""
    folder = tmp_path / "项目 2026-007" / "资料 送审"
    folder.mkdir(parents=True)
    (folder / "送审 计价表.xlsx").write_bytes(shapes.priced_bill())
    monkeypatch.chdir(tmp_path)
    rel = str(Path("项目 2026-007") / "资料 送审" / "送审 计价表.xlsx")
    (f,) = svc.load_files([rel])
    assert f.file_name == "送审 计价表.xlsx" and f.file_id == rel
    env = indicator.run(indicator.IndicatorRequest(price_files=[rel], gross_area=100))
    assert env.status in (ResultStatus.OK, ResultStatus.PARTIAL)
    assert env.data["file_coverage"][0]["file_id"] == rel


def test_explicit_file_id_and_name_flow_into_locations():
    ref = shapes.put(shapes.priced_bill(), "a.xlsx", "资料/送审/a.xlsx")
    ref["file_name"] = "送审计价表.xlsx"
    env = tk.run(tk.TkRequest(submission_files=[ref], project_id="2026-007"))
    cov = env.data["file_coverage"][0]
    assert (cov["file"], cov["file_id"]) == ("送审计价表.xlsx", "资料/送审/a.xlsx")


@pytest.mark.parametrize("path,expected", [
    ("a.xls", True), ("A.XLS", True), ("dir\\b.xls", True), ("C:\\资料\\c.xls", True),
    ("a.xlsx", False), ("a.xlsm", False), ("xls/a.xlsx", False),
])
def test_is_xls_on_posix_and_windows_paths(path, expected):
    assert svc.is_xls(path) is expected


def test_invalid_request_field_is_an_error():
    with pytest.raises(ZtError) as exc:
        svc.parse_request(reconcile.ReconcileRequest, {"submitted_file": "a.xlsx", "approved_file": "b.xlsx",
                                                       "rel_path": "x"})
    assert exc.value.code == "invalid_request" and "rel_path" in exc.value.message
