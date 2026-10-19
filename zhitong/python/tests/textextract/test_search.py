"""项目内字面量检索：docx / xlsx / PDF（含旁车）/ 文本 / pptx，定位与「没搜到不等于没有」。"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from openpyxl import Workbook

from tests.textextract import ws04_fixtures as fx
from zt.common import ZtError
from zt.textextract.cli import cli
from zt.textextract.search import search_project


def run(argv: list[str]) -> tuple[int, Any]:
    out = io.StringIO()
    code = cli.main(argv, stdout=out)
    return code, json.loads(out.getvalue())


def _docx(paragraphs: list[str]) -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def _xlsx(sheets: dict[str, list[list[object]]], hidden: tuple[str, ...] = ()) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
        if name in hidden:
            ws.sheet_state = "hidden"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def project(tmp_path) -> Path:
    r = tmp_path / "项目"
    (r / "资料" / "合同").mkdir(parents=True)
    (r / "资料" / "合同" / "施工合同.docx").write_bytes(_docx(["第一条 总则", "第二条 合同价款 按固定单价调整", "第三条 工期"]))
    (r / "资料" / "清单.xlsx").write_bytes(_xlsx({
        "分部分项": [["编码", "名称"], ["010101001", "平整场地 调整系数"]],
        "隐藏表": [["合同价款调整"]]}, hidden=("隐藏表",)))
    (r / "资料" / "说明.txt").write_text("项目概况\n合同价款 调整 方式见合同\n", encoding="utf-8")
    (r / "资料" / "文字.pdf").write_bytes(fx.build_pdf(["text", "text"]))
    (r / "工作").mkdir()
    (r / "工作" / "中间.txt").write_text("合同价款 调整 中间产物", encoding="utf-8")
    return r


def test_hits_across_formats_carry_precise_locators(project):
    res = search_project(project, ["合同价款", "调整"])
    got = {(h.rel_path, tuple(sorted(h.locator.items()))) for h in res.hits}
    assert got == {
        ("资料/合同/施工合同.docx", (("paragraph", 2),)),
        ("资料/说明.txt", (("row", 2), ("row_label", "行"))),
    }, got
    assert not any(h.rel_path.startswith("工作/") for h in res.hits)


def test_xlsx_row_locator_and_hidden_sheet_not_searched(project):
    res = search_project(project, ["调整系数"])
    [hit] = res.hits
    assert (hit.rel_path, hit.locator) == ("资料/清单.xlsx", {"sheet": "分部分项", "row": 2})
    hidden = search_project(project, ["合同价款调整"])
    assert hidden.hits == []
    assert any(s.reason == "hidden_sheets" for s in hidden.skipped)


def test_pdf_page_locator(project):
    res = search_project(project, ["PAGE-TEXT", "page 2"])
    assert [(h.rel_path, h.locator) for h in res.hits] == [("资料/文字.pdf", {"page": 2})]


def test_scanned_pdf_pages_found_through_sidecar_and_missing_pages_reported(project):
    (project / "资料" / "扫描.pdf").write_bytes(fx.build_pdf(["image", "image"]))
    (project / "资料" / "扫描.pdf.ocr.txt").write_text(
        fx.paged_sidecar([("ok", ["变更签证 金额 2000 元"]), ("failed", [])]), encoding="utf-8")
    res = search_project(project, ["变更签证"])
    assert [(h.rel_path, h.locator) for h in res.hits] == [("资料/扫描.pdf", {"page": 1})]
    note = next(s for s in res.skipped if s.rel_path == "资料/扫描.pdf")
    assert note.reason == "needs_vision" and note.pages == [2]


def test_keywords_and_vs_any_and_case(project):
    assert search_project(project, ["合同价款", "不存在的词"]).hits == []
    assert len(search_project(project, ["合同价款", "不存在的词"], any_mode=True).hits) >= 2
    assert search_project(project, ["page-text"]).hits and not search_project(project, ["page-text"], ignore_case=False).hits


def test_max_hits_truncates_and_flags(project):
    res = search_project(project, ["合同价款"], max_hits=1)
    assert len(res.hits) == 1 and res.truncated_hits


def test_subdir_limits_scope_and_rejects_escape(project):
    assert {h.rel_path for h in search_project(project, ["合同价款"], subdir="资料/合同").hits} == {"资料/合同/施工合同.docx"}
    with pytest.raises(ZtError) as e:
        search_project(project, ["x"], subdir="../x")
    assert e.value.code == "invalid_path"
    with pytest.raises(ZtError) as e:
        search_project(project, ["x"], subdir="资料/无此目录")
    assert e.value.code == "subdir_not_found"


def test_no_keywords_is_an_error(project):
    with pytest.raises(ZtError) as e:
        search_project(project, ["  ", ""])
    assert e.value.code == "no_keywords"


# ---------------------------------------------------------------- CLI 信封


def test_cli_ok_when_everything_searched(project):
    code, env = run(["search", "--root", str(project), "--keyword", "合同价款", "--keyword", "调整"])
    assert code == 0 and env["status"] == "ok" and env["data"]["hit_count"] == 2
    docx_hit = next(h for h in env["data"]["hits"] if h["rel_path"].endswith("施工合同.docx"))
    assert {k: v for k, v in docx_hit.items() if k != "quote"} == {"rel_path": "资料/合同/施工合同.docx", "paragraph": 2}
    assert "固定单价调整" in docx_hit["quote"]


def test_cli_empty_only_when_all_files_were_searched(project):
    code, env = run(["search", "--root", str(project), "--keyword", "绝对没有的词"])
    assert env["status"] == "empty" and env["status_reason"] == "no_match"


def test_cli_unreadable_files_make_no_match_partial_not_empty(project):
    (project / "资料" / "现场.jpg").write_bytes(b"\xff\xd8")
    (project / "图纸").mkdir()
    (project / "图纸" / "a.dwg").write_bytes(b"AC10")
    code, env = run(["search", "--root", str(project), "--keyword", "绝对没有的词"])
    assert env["status"] == "partial" and env["status_reason"] == "no_match_in_readable_files"
    codes = {w["code"] for w in env["warning_items"]}
    assert {"unsearched_need_vision", "files_not_searched"} <= codes
    assert {s["reason"] for s in env["coverage"]["skipped"]} == {"needs_vision", "unsupported_format"}


def test_cli_hits_plus_unreadable_is_partial(project):
    (project / "资料" / "现场.png").write_bytes(b"x")
    _, env = run(["search", "--root", str(project), "--keyword", "合同价款"])
    assert env["status"] == "partial" and env["data"]["hit_count"] >= 2


def test_cli_usage_errors(project, tmp_path):
    code, payload = run(["search", "--root", str(project)])
    assert (code, payload["error"]["code"]) == (2, "no_keywords")
    code, payload = run(["search", "--root", str(tmp_path / "无"), "--keyword", "x"])
    assert (code, payload["error"]["code"]) == (2, "root_not_found")


def test_symlink_pointing_outside_is_not_read(project, tmp_path):
    outside = tmp_path / "别处.txt"
    outside.write_text("合同价款 调整 机密", encoding="utf-8")
    import os

    try:
        os.symlink(outside, project / "资料" / "链接.txt")
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不允许创建符号链接")
    res = search_project(project, ["机密"])
    assert res.hits == [] and any(s.reason == "symlink_outside_project" for s in res.skipped)
