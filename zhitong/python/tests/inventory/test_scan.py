"""资料盘点：扫描项目目录、报缺件、不打标签。夹具见 fixtures/sample-project（合成，生成脚本同目录）。"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.inventory._support import DATA, SAMPLE_PROJECT
from zt.common import ZtError
from zt.inventory.cli import cli
from zt.inventory.scan import inventory, scan_files

PYTHON_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path) -> Path:
    dst = tmp_path / "项目 示例" / "2026-001-示例住院楼"
    shutil.copytree(SAMPLE_PROJECT, dst)
    return dst


def run(argv: list[str]) -> tuple[int, Any]:
    out = io.StringIO()
    code = cli.main(argv, stdout=out)
    assert out.getvalue().count("\n") == 1, "stdout 只输出一个 JSON 文档"
    return code, json.loads(out.getvalue())


def scan(project: Path, *extra: str) -> Any:
    code, env = run(["scan", "--project-dir", str(project), *extra])
    assert code == 0, env
    return env


# ---------------------------------------------------------------- 样例项目


def test_sample_project_reads_scope_from_project_doc():
    env = scan(SAMPLE_PROJECT)
    scope = env["data"]["scope"]
    assert scope["consulting_type"] == "20002" and scope["checklist_set"] == "20002" and not scope["checklist_fallback"]
    assert scope["selected_stage"] == "审定" and scope["stage_basis"] == "cumulative"
    assert scope["source"] == {"consulting_type": "project_doc", "stage": "project_doc"}


def test_sample_project_result():
    env = scan(SAMPLE_PROJECT)
    d = env["data"]
    assert env["status"] == "ok" and env["needs_manual"] is True
    s = d["summary"]
    assert (s["required_total"], s["required_covered"], s["required_pending"], s["required_missing"]) == (7, 6, 1, 0)
    assert s["coverage_rate"] == pytest.approx(0.8571) and s["coverage_rate_upper"] == 1.0
    assert d["missing"] == []
    assert {c["item_name"] for c in d["covered"]} == {
        "施工合同及补充协议", "竣工图纸", "结算送审书", "结算审核报告", "结算审定单", "审核汇总表", "施工图纸", "工程量清单"}
    pending = {p["item_name"]: p for p in d["pending"]}
    assert set(pending) == {"变更签证费用", "招标控制价文件"}
    assert [f["rel_path"] for f in pending["变更签证费用"]["files"]] == ["资料/5 变更资料/签证单汇总.xlsx"]
    assert [a["item_name"] for a in d["advisory"]] == ["投标报价文件"]
    assert [o["item_name"] for o in d["optional_missing"]] == ["造价指标分析"]


def test_result_has_no_per_file_labels():
    """只报缺件，不打标签：结果里不出现任何文件的 doc_category / cost_stage 标注。"""
    env = scan(SAMPLE_PROJECT)
    text = json.dumps(env["data"], ensure_ascii=False)
    assert '"cost_stage"' not in text
    for row in [*env["data"]["covered"], *env["data"]["pending"]]:
        assert set(row["files"][0]) <= {"rel_path", "grade", "conflict"}
    assert set(env["data"]) == {"project", "scope", "summary", "missing", "pending", "advisory", "covered",
                                "optional_missing", "unclassified_files", "unclassified_total", "input_stats",
                                "rules_version"}


def test_unclassified_lists_the_scanned_pdf_but_not_decided_non_cost_files():
    d = scan(SAMPLE_PROJECT)["data"]
    assert d["unclassified_files"] == ["资料/6 其他/扫描件0001.pdf"]
    assert d["input_stats"]["skipped_non_cost"] == 1                    # 施工日志.docx：黑名单，确定非造价资料
    assert d["input_stats"]["ignored_system"] == 2                      # INDEX.md、扫描件0001.pdf.ocr.txt
    assert d["input_stats"]["files_listed"] == 12                       # 工作/ 与 项目说明.md 不在其内


def test_pending_required_item_warns_with_evidence_and_missing_important_is_info():
    w = {x["code"]: x for x in scan(SAMPLE_PROJECT)["warning_items"]}
    assert w["required_item_unconfirmed"]["level"] == "warn"
    assert w["required_item_unconfirmed"]["evidence"][0]["rel_path"] == "资料/5 变更资料/签证单汇总.xlsx"
    assert w["important_item_missing"]["level"] == "info"


def test_rel_paths_use_forward_slashes_and_are_relative():
    d = scan(SAMPLE_PROJECT)["data"]
    paths = [f["rel_path"] for r in [*d["covered"], *d["pending"]] for f in r["files"]] + d["unclassified_files"]
    assert paths and all("\\" not in p and not p.startswith("/") and ":" not in p for p in paths)


# ---------------------------------------------------------------- 变化场景（在副本上改）


def test_removing_a_required_document_reports_it_missing(project):
    (project / "资料" / "1 合同及协议" / "施工合同及补充协议.docx").unlink()
    env = scan(project)
    assert [m["item_name"] for m in env["data"]["missing"]] == ["施工合同及补充协议"]
    assert env["data"]["summary"]["required_missing"] == 1
    w = next(x for x in env["warning_items"] if x["code"] == "required_item_missing")
    assert w["level"] == "warn" and "施工合同及补充协议" in w["message"] and "unclassified_files" in w["hint"]


def test_progress_payment_directory_does_not_fake_a_quantity_list(project):
    """旧缺陷回归：「22 进度款…」目录下的清单不是招标阶段的工程量清单（分类器 veto 与核查冲突表两道闸）。"""
    for p in (project / "资料" / "2 招标资料").iterdir():
        p.unlink()
    pay = project / "资料" / "22 进度款审核及付款建议" / "第10期"
    pay.mkdir(parents=True)
    (pay / "分部分项工程量清单.xlsx").write_bytes(b"x")
    d = scan(project, "--stage", "招标控制价")["data"]
    assert "工程量清单" not in {c["item_name"] for c in [*d["covered"], *d["pending"]] if c["requirement_level"]}
    assert "工程量清单" in {m["item_name"] for m in [*d["missing"], *d["advisory"]]}


def test_doc_and_docx_twins_count_as_one_document(project):
    d = project / "成果"
    (d / "结算审定单.xls").write_bytes(b"x")
    covered = {c["item_name"]: c for c in scan(project)["data"]["covered"]}
    assert len(covered["结算审定单"]["files"]) == 1


def test_project_without_files_is_empty(tmp_path):
    p = tmp_path / "空项目"
    (p / "资料").mkdir(parents=True)
    env = scan(p, "--consulting-type", "结算审核", "--stage", "审定")
    assert env["status"] == "empty" and env["status_reason"] == "no_source_files"


def test_unrecognizable_names_are_insufficient_not_all_missing(tmp_path):
    p = tmp_path / "杂项"
    (p / "资料").mkdir(parents=True)
    (p / "资料" / "IMG_0001.jpg").write_bytes(b"x")
    (p / "资料" / "新建文本文档.txt").write_bytes(b"x")
    env = scan(p, "--consulting-type", "结算审核", "--stage", "审定")
    assert env["status"] == "insufficient" and env["status_reason"] == "no_categorized_files"
    assert env["data"]["unclassified_total"] == 2
    assert "不可信" in env["warning_items"][0]["message"]


def test_work_dir_dot_dirs_office_locks_are_ignored(project):
    (project / "工作" / "2026-10-20-盘点").mkdir(parents=True)
    (project / "工作" / "2026-10-20-盘点" / "结算审定单.xlsx").write_bytes(b"x")
    (project / "图纸" / ".cache").mkdir()
    (project / "图纸" / ".cache" / "施工图.png").write_bytes(b"x")
    (project / "资料" / "~$合同.docx").write_bytes(b"x")
    (project / "资料" / ".DS_Store").write_bytes(b"x")
    names = {f.rel_path for f in scan_files(project).files}
    assert not any(n.startswith("工作/") or ".cache" in n or "~$" in n or ".DS_Store" in n for n in names)
    assert scan_files(project).ignored_temp == 2


def test_symlink_escaping_project_is_skipped_with_warning(project, tmp_path):
    outside = tmp_path / "别处.pdf"
    outside.write_bytes(b"x")
    try:
        os.symlink(outside, project / "资料" / "合同.pdf")
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不允许创建符号链接")
    env = scan(project)
    assert any(w["code"] == "symlink_skipped" for w in env["warning_items"])
    assert "资料/合同.pdf" not in {f.rel_path for f in scan_files(project).files}


def test_scan_does_not_modify_the_project(project):
    before = sorted((p.relative_to(project).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                    for p in project.rglob("*") if p.is_file())
    scan(project)
    after = sorted((p.relative_to(project).as_posix(), p.stat().st_size, p.stat().st_mtime_ns)
                   for p in project.rglob("*") if p.is_file())
    assert before == after


# ---------------------------------------------------------------- 口径参数


def test_stage_is_never_guessed(project):
    (project / "项目说明.md").unlink()
    code, payload = run(["scan", "--project-dir", str(project), "--consulting-type", "结算审核"])
    assert (code, payload["error"]["code"]) == (2, "stage_required")
    assert "--all-stages" in payload["error"]["hint"]


def test_stage_and_all_stages_conflict(project):
    code, payload = run(["scan", "--project-dir", str(project), "--stage", "审定", "--all-stages"])
    assert (code, payload["error"]["code"]) == (2, "stage_conflict")


def test_all_stages_is_explicit_and_flagged(project):
    env = scan(project, "--all-stages")
    assert env["data"]["scope"]["stage_basis"] == "all_stages"
    assert any(w["code"] == "all_stages_scope" for w in env["warning_items"])


def test_args_override_project_doc_and_fallback_is_disclosed(project):
    env = scan(project, "--consulting-type", "全过程造价咨询", "--stage", "结算")
    scope = env["data"]["scope"]
    assert scope["consulting_type"] == "20001" and scope["checklist_set"] == "ALL" and scope["checklist_fallback"]
    assert scope["source"] == {"consulting_type": "arg", "stage": "arg"}
    assert any(w["code"] == "checklist_fallback_to_all" for w in env["warning_items"])


@pytest.mark.parametrize("args,code", [
    (["--stage", "竣工"], "unknown_stage"),
    (["--consulting-type", "工程审计"], "invalid_consulting_type"),
])
def test_bad_scope_values_fail(project, args, code):
    c, payload = run(["scan", "--project-dir", str(project), *args])
    assert (c, payload["error"]["code"]) == (2, code)


def test_missing_project_dir_and_broken_data_dir(tmp_path, project):
    c, payload = run(["scan", "--project-dir", str(tmp_path / "无"), "--stage", "审定"])
    assert (c, payload["error"]["code"]) == (2, "project_dir_not_found")
    c, payload = run(["scan", "--project-dir", str(project), "--data-dir", str(tmp_path)])
    assert (c, payload["error"]["code"]) == (2, "data_dir_invalid")


def test_invalid_project_doc_head_fails_loudly(project):
    (project / "项目说明.md").write_text("---\n项目编号: [oops\n---\n", encoding="utf-8")
    c, payload = run(["scan", "--project-dir", str(project)])
    assert (c, payload["error"]["code"]) == (2, "project_doc_invalid")


def test_inventory_function_requires_a_stage_choice(project):
    with pytest.raises(ZtError) as e:
        inventory(project, DATA, consulting_type="结算审核", stage=None)
    assert e.value.code == "stage_required"


def test_data_dir_override_uses_modified_checklist(project, tmp_path):
    """数据文件是普通文件，改了立即生效：删掉 20002 的所有专属行，应退回通用清单。"""
    data = tmp_path / "data"
    shutil.copytree(DATA.data_dir, data)
    text = (data / "checklist.yaml").read_text(encoding="utf-8")
    kept = [ln for ln in text.splitlines() if '"consulting_type": "20002"' not in ln]
    (data / "checklist.yaml").write_text("\n".join(kept) + "\n", encoding="utf-8")
    env = scan(project, "--data-dir", str(data))
    assert env["data"]["scope"]["checklist_set"] == "ALL" and env["data"]["scope"]["checklist_fallback"]


def test_env_var_selects_data_dir(project, tmp_path, monkeypatch):
    monkeypatch.setenv("ZT_PROJECT_DATA", str(tmp_path / "不存在"))
    c, payload = run(["scan", "--project-dir", str(project)])
    assert (c, payload["error"]["code"]) == (2, "data_dir_invalid")


def test_real_process_with_chinese_space_paths_and_out_file(project, tmp_path):
    out = tmp_path / "工作 输出" / "盘点结果.json"
    proc = subprocess.run(
        [sys.executable, "-m", "zt.inventory.cli", "scan", "--project-dir", str(project), "--out", str(out)],
        cwd=PYTHON_ROOT, capture_output=True, check=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    summary = json.loads(proc.stdout.decode("utf-8"))
    assert summary["status"] == "ok" and summary["out"] == str(out)
    full = json.loads(out.read_text(encoding="utf-8"))
    assert full["data"]["summary"]["required_total"] == 7


# ---------------------------------------------------------------- 文件清单模式（tos_ls 的结果，不必拉到本机）


def _listing_paths(prefix: str = "项目/2026-001-示例住院楼/") -> list[str]:
    return [prefix + p.relative_to(SAMPLE_PROJECT).as_posix()
            for p in sorted(SAMPLE_PROJECT.rglob("*")) if p.is_file()]


def _write(tmp_path: Path, name: str, text: str) -> Path:
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return f


def test_listing_gives_the_same_result_as_scanning_the_directory(tmp_path):
    listing = _write(tmp_path, "清单.txt", "\n".join(_listing_paths()) + "\n")
    from_listing = scan_via_listing(listing, "--project-doc", str(SAMPLE_PROJECT / "项目说明.md"))
    from_dir = scan(SAMPLE_PROJECT)
    for key in ("summary", "missing", "pending", "advisory", "covered", "optional_missing", "unclassified_files"):
        assert from_listing["data"][key] == from_dir["data"][key], key
    assert from_listing["data"]["project"] == "2026-001-示例住院楼"
    assert from_listing["data"]["input_stats"]["files_listed"] == from_dir["data"]["input_stats"]["files_listed"]


def scan_via_listing(listing: Path, *extra: str) -> Any:
    code, env = run(["scan", "--listing", str(listing), *extra])
    assert code == 0, env
    return env


def test_listing_json_pages_from_tos_ls_and_windows_separators(tmp_path):
    pages = [
        {"path": "项目/2026-001-示例住院楼/", "dirs": [], "files": [
            {"path": "项目/2026-001-示例住院楼/资料/1 合同及协议/施工合同及补充协议.docx", "size": 1, "modified": "x", "cached": False}]},
        {"files": [{"path": "项目\\2026-001-示例住院楼\\图纸\\建筑施工图.dwg", "size": 1, "modified": "x", "cached": False}]},
    ]
    listing = _write(tmp_path, "清单.json", json.dumps(pages, ensure_ascii=False))
    env = scan_via_listing(listing, "--consulting-type", "结算审核", "--stage", "审定")
    names = {c["item_name"] for c in env["data"]["covered"]}
    assert names == {"施工合同及补充协议", "施工图纸"}                    # 图纸不用拉到本机也能参与盘点
    assert env["data"]["input_stats"]["files_listed"] == 2


def test_listing_strips_explicit_prefix_and_rejects_mismatch(tmp_path):
    listing = _write(tmp_path, "l.txt", "客户A/资料/施工合同.pdf\n客户A/图纸/建筑施工图.dwg\n")
    env = scan_via_listing(listing, "--strip-prefix", "客户A/", "--consulting-type", "结算审核", "--stage", "审定")
    assert {c["item_name"] for c in env["data"]["covered"]} == {"施工合同及补充协议", "施工图纸"}
    bad = _write(tmp_path, "b.txt", "客户A/资料/施工合同.pdf\n别处/x.pdf\n")
    code, payload = run(["scan", "--listing", str(bad), "--strip-prefix", "客户A/", "--stage", "审定"])
    assert (code, payload["error"]["code"]) == (2, "listing_prefix_mismatch")


def test_listing_filters_work_dir_dot_dirs_system_files_and_directories(tmp_path):
    listing = _write(tmp_path, "l.txt", "\n".join([
        "资料/", "资料/施工合同.pdf", "工作/2026-10-19-核对/结算审定单.xlsx", "图纸/.cache/建筑施工图.png",
        "资料/INDEX.md", "资料/施工合同.pdf.ocr.txt", "项目说明.md", "资料/~$合同.docx"]))
    env = scan_via_listing(listing, "--consulting-type", "结算审核", "--stage", "审定")
    stats = env["data"]["input_stats"]
    assert stats["files_listed"] == 1 and stats["ignored_system"] == 2 and stats["ignored_temp"] == 1


@pytest.mark.parametrize("line", ["/etc/passwd", "C:\\x\\a.pdf", "资料/../../x.pdf"])
def test_listing_rejects_absolute_and_parent_paths(tmp_path, line):
    code, payload = run(["scan", "--listing", str(_write(tmp_path, "l.txt", line)), "--stage", "审定"])
    assert (code, payload["error"]["code"]) == (2, "invalid_path")


def test_listing_needs_scope_from_somewhere(tmp_path):
    listing = _write(tmp_path, "l.txt", "资料/施工合同.pdf\n")
    code, payload = run(["scan", "--listing", str(listing)])
    assert (code, payload["error"]["code"]) == (2, "stage_required")
    code, payload = run(["scan"])
    assert (code, payload["error"]["code"]) == (2, "usage")
    code, payload = run(["scan", "--listing", str(tmp_path / "无.txt"), "--stage", "审定"])
    assert (code, payload["error"]["code"]) == (2, "listing_not_found")
    code, payload = run(["scan", "--listing", str(_write(tmp_path, "j.json", "[{oops")), "--stage", "审定"])
    assert (code, payload["error"]["code"]) == (2, "listing_invalid")


def test_empty_listing_is_empty_status(tmp_path):
    env = scan_via_listing(_write(tmp_path, "l.txt", ""), "--consulting-type", "结算审核", "--stage", "审定")
    assert env["status"] == "empty" and env["status_reason"] == "no_source_files"


def test_listing_with_several_projects_is_rejected(tmp_path):
    listing = _write(tmp_path, "l.txt", "项目/2026-001-甲/资料/a.pdf\n项目/2026-002-乙/资料/b.pdf\n")
    code, payload = run(["scan", "--listing", str(listing), "--stage", "审定"])
    assert (code, payload["error"]["code"]) == (2, "listing_multiple_projects")


def test_unspecified_consulting_type_is_disclosed(project):
    (project / "项目说明.md").unlink()
    env = scan(project, "--stage", "审定")
    assert env["data"]["scope"]["checklist_set"] == "ALL" and env["data"]["scope"]["consulting_type"] is None
    assert any(w["code"] == "consulting_type_unspecified" for w in env["warning_items"])
