"""问答回答的出处核对：无出处的数字、引用指向没读过的资料或不存在的位置。"""
from __future__ import annotations

import io
import json
from typing import Any

import pytest

from zt.textextract.answer_check import Source, check_answer, read_source
from zt.textextract.cli import cli

CONTRACT = Source("资料/合同.pdf", "[p1]\n合同价款为 1,198.00 万元，工期 365 日历天。\n[p2]\n预付款比例 20%。")
LIST_XLSX = Source("资料/清单.xlsx", "[工作表] 汇总\n[R5] A:土建\tB:12345678.90\n[R6] A:安装\tB:2345678.00")


def numbers(ans: str, *sources: Source) -> list[str]:
    return [u.raw for u in check_answer(ans, list(sources)).unattributed]


def test_attributed_numbers_pass_including_unit_conversion():
    ans = "合同价款 1198 万元（即 11,980,000 元），工期 365 日历天，预付款 20%。〔资料/合同.pdf p1〕"
    assert numbers(ans, CONTRACT) == []
    assert check_answer(ans, [CONTRACT]).passed


def test_unattributed_numbers_are_flagged_with_context():
    res = check_answer("合同价款 1,299.00 万元，预付款 25%。", [CONTRACT])
    assert [u.raw for u in res.unattributed] == ["1299.00万元", "25%"]
    assert "合同价款" in res.unattributed[0].context and not res.passed


def test_computed_numbers_have_no_source():
    """模型心算的合计在资料里没有出处，必须被标出（旧缺陷：心算 459.79 写成汇总）。"""
    assert numbers("土建与安装合计 14,690,000 元", LIST_XLSX) == ["14690000元"]


def test_excluded_fragments_are_not_numbers():
    ans = ("依据 GB 50854-2013 第 3 条，清单编码 010502002，条文 4.2.1，见 `1234.5`，文件 2026-001-某工程/合同第3版.pdf，"
           "项目号 2026003 ID 123456789012345678。")
    # 2026003 是 7 位普通数字：不在排除模式里，应被标出，其余都不应被标出
    assert numbers(ans, CONTRACT) == ["2026003"]


def test_dates_and_ordinals_are_skipped_by_the_number_finder():
    assert numbers("2026 年 10 月 19 日，第 3 章，第 5 页。", CONTRACT) == []


def test_ordinals_in_sources_count_as_sources():
    src = Source("资料/说明.txt", "见源文件第 1716 行。")
    assert numbers("见第 1716 行", src) == []


def test_citation_must_point_to_a_source_that_was_read():
    ans = "工期 365 日历天〔资料/合同.pdf p1〕，另见〔资料/没读过.pdf p2〕和〔合同.pdf p9〕。"
    res = check_answer(ans, [CONTRACT])
    kinds = {i.cite: i.problem for i in res.citation_issues}
    assert kinds == {"〔资料/没读过.pdf p2〕": "citation_not_read", "〔合同.pdf p9〕": "citation_locator_missing"}
    assert res.citations_total == 3


def test_citation_matches_by_unique_basename_and_row_locator():
    ans = "土建 12345678.90〔清单.xlsx 汇总!R5〕，安装 2345678.00〔资料/清单.xlsx R6〕，错行〔资料/清单.xlsx R99〕。"
    res = check_answer(ans, [LIST_XLSX])
    assert [i.cite for i in res.citation_issues] == ["〔资料/清单.xlsx R99〕"]
    assert res.unattributed == []


def test_duplicate_basenames_do_not_guess():
    a, b = Source("资料/甲/合同.pdf", "[p1]"), Source("资料/乙/合同.pdf", "[p1]")
    assert check_answer("〔合同.pdf p1〕", [a, b]).citation_issues[0].problem == "citation_not_read"
    assert check_answer("〔资料/甲/合同.pdf p1〕", [a, b]).citation_issues == []


SPACED_DOCX = Source("资料/1 合同及协议/施工合同及补充协议.docx", "[p1]\n合同价款……\n[p3]\n工期 365 日历天。")
SPACED_XLSX = Source("资料/4 结算资料/送审计价表.xlsx", "[工作表] 土建\n[R28] A:土方\tB:120.00")


def test_citation_path_may_contain_spaces():
    """``资料/<n> <类别>/`` 目录名带空格：路径按读过的资料认出，不在第一个空格处截断。"""
    res = check_answer("工期 365 日历天〔资料/1 合同及协议/施工合同及补充协议.docx p3〕。", [SPACED_DOCX])
    assert res.citation_issues == [] and res.passed
    assert check_answer("〔资料/1 合同及协议/施工合同及补充协议.docx〕", [SPACED_DOCX]).citation_issues == []
    missing = check_answer("〔资料/1 合同及协议/施工合同及补充协议.docx p9〕", [SPACED_DOCX]).citation_issues
    assert [i.problem for i in missing] == ["citation_locator_missing"]


def test_unread_spaced_path_is_reported_whole():
    issues = check_answer("〔资料/1 合同及协议/施工合同及补充协议.docx p3〕", [CONTRACT]).citation_issues
    assert [i.problem for i in issues] == ["citation_not_read"]
    assert issues[0].detail == "引用的 资料/1 合同及协议/施工合同及补充协议.docx 不在读过的资料里"


def test_sheet_row_locator_after_spaced_path():
    ans = "土方 120.00〔资料/4 结算资料/送审计价表.xlsx 土建!R28〕，错行〔资料/4 结算资料/送审计价表.xlsx 土建!R99〕。"
    res = check_answer(ans, [SPACED_XLSX])
    assert [(i.cite, i.problem) for i in res.citation_issues] == [
        ("〔资料/4 结算资料/送审计价表.xlsx 土建!R99〕", "citation_locator_missing")]
    assert res.unattributed == []


def test_read_source_forms(tmp_path):
    f = tmp_path / "文本 1.txt"
    f.write_text("正文", encoding="utf-8")
    assert read_source(f"资料\\合同.pdf={f}") == Source("资料/合同.pdf", "正文")
    assert read_source(str(f)) == Source("文本 1.txt", "正文")


# ---------------------------------------------------------------- CLI


def run(argv: list[str]) -> tuple[int, Any]:
    out = io.StringIO()
    code = cli.main(argv, stdout=out)
    return code, json.loads(out.getvalue())


@pytest.fixture
def files(tmp_path):
    (tmp_path / "合同.txt").write_text(CONTRACT.text, encoding="utf-8")
    return tmp_path


def test_cli_clean_answer_passes(files):
    ans = files / "答案.md"
    ans.write_text("合同价款 1198 万元〔资料/合同.pdf p1〕。", encoding="utf-8")
    code, env = run(["check-answer", "--answer", str(ans), "--source", f"资料/合同.pdf={files / '合同.txt'}"])
    assert code == 0 and env["status"] == "ok" and env["data"]["passed"] is True and env["warning_items"] == []


def test_cli_reports_unattributed_citation_and_missing_citations(files):
    ans = files / "答案.md"
    ans.write_text("合同价款 999 万元。", encoding="utf-8")
    _, env = run(["check-answer", "--answer", str(ans), "--source", f"资料/合同.pdf={files / '合同.txt'}"])
    assert env["data"]["passed"] is False
    assert {w["code"] for w in env["warning_items"]} == {"unattributed_number", "no_citations"}
    ans.write_text("合同价款 1198 万元〔资料/别的.pdf p1〕。", encoding="utf-8")
    _, env = run(["check-answer", "--answer", str(ans), "--source", f"资料/合同.pdf={files / '合同.txt'}"])
    assert [w["code"] for w in env["warning_items"]] == ["citation_not_read"] and env["data"]["passed"] is False


def test_cli_caps_the_report_and_handles_errors(files):
    ans = files / "答案.md"
    ans.write_text("、".join(f"{100 + i}.5 万元" for i in range(30)) + "〔资料/合同.pdf p1〕", encoding="utf-8")
    _, env = run(["check-answer", "--answer", str(ans), "--source", f"资料/合同.pdf={files / '合同.txt'}",
                  "--max-report", "5"])
    assert len(env["data"]["unattributed"]) == 30
    assert sum(w["code"] == "unattributed_number" for w in env["warning_items"]) == 5
    assert any(w["code"] == "more_unattributed" for w in env["warning_items"])
    code, payload = run(["check-answer", "--answer", str(files / "无.md")])
    assert (code, payload["error"]["code"]) == (2, "file_not_found")
    code, payload = run(["check-answer", "--answer", str(ans), "--source", str(files / "无.txt")])
    assert (code, payload["error"]["code"]) == (2, "source_unreadable")
