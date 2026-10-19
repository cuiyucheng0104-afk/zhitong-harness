"""zt-project / zt-archive / zt-ask 的脚本：编号分配、开项目、项目说明草稿、归档核对与更新。

脚本按文件路径加载（单元）并以真实进程运行（端到端，中文与空格路径）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.inventory._support import SAMPLE_PROJECT
from zt.common import ZtError
from zt.inventory.casebook import parse_casebook
from zt.inventory.projectdoc import read_project_doc, section_bullets

SKILLS = Path(__file__).resolve().parents[3] / "skills"
PYTHON_ROOT = Path(__file__).resolve().parents[2]


def load_script(skill: str, name: str):
    path = SKILLS / skill / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{skill}_{name}".replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_script(skill: str, name: str, *args: str) -> tuple[int, Any]:
    proc = subprocess.run([sys.executable, str(SKILLS / skill / "scripts" / f"{name}.py"), *args],
                          cwd=PYTHON_ROOT, capture_output=True, check=False)
    out = proc.stdout.decode("utf-8")
    assert out.count("\n") == 1, (out, proc.stderr.decode("utf-8", "replace"))
    return proc.returncode, json.loads(out)


new_project = load_script("zt-project", "new_project")


# ---------------------------------------------------------------- 编号分配（zt-project/scripts/new_project.py）


@pytest.mark.parametrize("index,known,year,seq", [
    ([], [], 2026, 1),                                              # 空索引从 001 开始
    (["2026-001", "2026-007", "2025-099"], [], 2026, 8),            # 取当年最大值加一，不补空洞
    (["2026-001"], ["2026-005-某工程", "2026-003-别的"], 2026, 6),  # 目录比索引新：以更大者为准
    (["2025-099"], [], 2026, 1),                                    # 跨年归零
    (["2026-999"], [], 2025, 1),
])
def test_allocate_code(index, known, year, seq):
    assert new_project.allocate_code(index, known, year)["seq"] == seq


def test_allocate_code_exhausted():
    with pytest.raises(ZtError) as e:
        new_project.allocate_code(["2026-999"], [], 2026)
    assert e.value.code == "project_code_exhausted"


def test_known_names_accept_ls_paths_and_separators():
    assert new_project._known(["项目/2026-003-甲/, 项目/2026-004-乙", "2026-005-丙\n项目\\2026-006-丁\\"]) == [
        "2026-003-甲", "2026-004-乙", "2026-005-丙", "2026-006-丁"]


INDEX_2026 = """# 案例索引

| 编号 | 工程名 | 业态 | 规模 | 咨询类型 | 关键指标 | 成果链接 | 状态 |
|---|---|---|---|---|---|---|---|
| 2026-001 | 甲 | | | 结算审核 | | | 已归档 |
| 2026-004 | 乙 | | | 结算审核 | | | 进行中 |
"""


@pytest.fixture
def cache(tmp_path) -> Path:
    root = tmp_path / "zhitong 缓存"
    root.mkdir()
    (root / "案例索引.md").write_text(INDEX_2026, encoding="utf-8")
    return root


def test_allocate_subcommand_does_not_write(cache):
    before = (cache / "案例索引.md").read_text(encoding="utf-8")
    code, env = run_script("zt-project", "new_project", "allocate", "--index", str(cache / "案例索引.md"),
                           "--name", " 某某 医院/住院楼 ", "--year", "2026")
    assert code == 0 and env["status"] == "ok"
    assert env["data"]["project_code"] == "2026-005" and env["data"]["dir_name"] == "2026-005-某某医院住院楼"
    assert env["data"]["basis"] == {"year": 2026, "seq": 5, "index_max": 4, "known_max": 0}
    assert (cache / "案例索引.md").read_text(encoding="utf-8") == before


def test_create_builds_project_registers_row_and_lists_files_to_push(cache):
    code, env = run_script(
        "zt-project", "new_project", "create", "--index", str(cache / "案例索引.md"), "--root", str(cache),
        "--name", "某某:医院 住院楼", "--consulting-type", "结算审核（20002）", "--stage", "审定",
        "--business", "医疗", "--scale", "1.2 万平", "--alias", "合同号 HT-9", "--year", "2026",
        "--known", "项目/2026-007-别人刚开的/")
    assert code == 0, env
    d = env["data"]
    assert d["project_code"] == "2026-008" and d["dir_name"] == "2026-008-某某医院住院楼"
    proj = Path(d["project_dir"])
    assert proj == cache / "项目" / "2026-008-某某医院住院楼"
    assert all((proj / s).is_dir() for s in ("资料", "图纸", "工作", "成果"))
    fields = read_project_doc((proj / "项目说明.md").read_text(encoding="utf-8"),
                              require=("项目编号", "工程名称", "咨询类型", "阶段"))
    assert fields["咨询类型"] == "结算审核" and fields["阶段"] == "审定" and fields["工程名称"] == "某某:医院 住院楼"
    assert fields["别名"] == ["合同号 HT-9"] and fields["状态"] == "进行中"
    row = parse_casebook((cache / "案例索引.md").read_text(encoding="utf-8")).find("2026-008")
    assert row["工程名"] == "某某:医院 住院楼" and row["咨询类型"] == "结算审核" and row["状态"] == "进行中"
    assert [f["path"] for f in d["files_to_push"]] == ["项目/2026-008-某某医院住院楼/项目说明.md", "案例索引.md"]
    assert env["warning_items"][0]["code"] == "push_now_to_reserve_code"


def test_create_then_scan_uses_the_new_project_doc(cache):
    run_script("zt-project", "new_project", "create", "--index", str(cache / "案例索引.md"), "--root", str(cache),
               "--name", "示例", "--consulting-type", "招标控制价编制", "--stage", "招标控制价", "--year", "2026")
    proj = cache / "项目" / "2026-005-示例"
    code, env = run_script("zt-project", "inventory", "scan", "--project-dir", str(proj))
    assert code == 0 and env["status"] == "empty" and env["status_reason"] == "no_source_files"


def test_create_creates_index_from_template_when_missing(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    code, env = run_script("zt-project", "new_project", "create", "--index", str(root / "案例索引.md"),
                           "--root", str(root), "--name", "首个项目", "--consulting-type", "全过程造价咨询",
                           "--stage", "概算", "--year", "2026")
    assert code == 0 and env["data"]["project_code"] == "2026-001"
    text = (root / "案例索引.md").read_text(encoding="utf-8")
    assert text.startswith("# 案例索引") and parse_casebook(text).find("2026-001")["工程名"] == "首个项目"


@pytest.mark.parametrize("extra,err", [
    (["--consulting-type", "工程审计", "--stage", "审定"], "invalid_consulting_type"),
    (["--consulting-type", "ALL", "--stage", "审定"], "invalid_consulting_type"),
    (["--consulting-type", "结算审核", "--stage", "竣工"], "unknown_stage"),
])
def test_create_validates_scope(cache, extra, err):
    code, payload = run_script("zt-project", "new_project", "create", "--index", str(cache / "案例索引.md"),
                               "--root", str(cache), "--name", "x", "--year", "2026", *extra)
    assert (code, payload["error"]["code"]) == (2, err)
    assert not (cache / "项目").exists() and (cache / "案例索引.md").read_text(encoding="utf-8") == INDEX_2026


def test_create_refuses_existing_dir_and_empty_name(cache):
    (cache / "项目" / "2026-005-示例").mkdir(parents=True)
    args = ["create", "--index", str(cache / "案例索引.md"), "--root", str(cache), "--consulting-type", "结算审核",
            "--stage", "审定", "--year", "2026"]
    code, payload = run_script("zt-project", "new_project", *args, "--name", "示例")
    assert (code, payload["error"]["code"]) == (2, "project_exists")
    code, payload = run_script("zt-project", "new_project", *args, "--name", " /\\:*?\"<>| ")
    assert (code, payload["error"]["code"]) == (2, "invalid_project_name")


# ---------------------------------------------------------------- 项目说明：show / draft


def test_show_reads_fields_key_files_and_flags_missing(tmp_path):
    code, env = run_script("zt-project", "project_doc", "show", "--file", str(SAMPLE_PROJECT / "项目说明.md"))
    assert code == 0 and env["status"] == "ok"
    assert env["data"]["fields"]["咨询类型"] == "结算审核"
    assert [r["资料"] for r in env["data"]["key_files"]] == ["施工合同", "结算送审书"]
    assert env["data"]["deliverables"] == ["成果/结算审核报告.docx", "成果/结算审定单.xlsx", "成果/审核汇总表.xlsx"]
    bad = tmp_path / "项目说明.md"
    bad.write_text("---\n项目编号: 2026-001\n工程名称: x\n咨询类型: 待确认\n---\n", encoding="utf-8")
    code, env = run_script("zt-project", "project_doc", "show", "--file", str(bad))
    assert env["status"] == "insufficient" and env["status_reason"] == "project_doc_incomplete"
    assert set(env["data"]["unresolved_fields"]) == {"咨询类型", "阶段"}
    code, payload = run_script("zt-project", "project_doc", "show", "--file", str(tmp_path / "无.md"))
    assert (code, payload["error"]["code"]) == (2, "file_not_found")


@pytest.fixture
def bare_project(tmp_path) -> Path:
    dst = tmp_path / "项目" / "2026-009-示例医院 住院楼"
    shutil.copytree(SAMPLE_PROJECT, dst)
    (dst / "项目说明.md").unlink()
    return dst


def test_draft_generates_doc_with_candidates_and_undecided_scope(bare_project):
    code, env = run_script("zt-project", "project_doc", "draft", "--project-dir", str(bare_project))
    assert code == 0 and env["status"] == "ok"
    assert env["data"]["fields"]["项目编号"] == "2026-009" and env["data"]["fields"]["工程名称"] == "示例医院 住院楼"
    assert env["data"]["fields"]["咨询类型"] == "待确认" and env["data"]["fields"]["阶段"] == "待确认"
    assert env["warning_items"][0]["code"] == "draft_needs_confirmation"
    assert env["data"]["files_to_push"][0]["path"] == "项目/2026-009-示例医院 住院楼/项目说明.md"
    text = (bare_project / "项目说明.md").read_text(encoding="utf-8")
    assert "资料/1 合同及协议/施工合同及补充协议.docx" in text and "按文件名判断，待确认" in text
    assert "## 目录概览" in text and "`资料/1 合同及协议/` 1 个文件" in text
    # 草稿里的「待确认」会让盘点明确失败，不会悄悄按通用清单跑
    code, payload = run_script("zt-project", "inventory", "scan", "--project-dir", str(bare_project))
    assert (code, payload["error"]["code"]) == (2, "invalid_consulting_type")
    # 不覆盖已有项目说明
    code, payload = run_script("zt-project", "project_doc", "draft", "--project-dir", str(bare_project))
    assert (code, payload["error"]["code"]) == (2, "project_doc_exists")


def test_draft_with_explicit_scope_feeds_inventory(bare_project):
    code, env = run_script("zt-project", "project_doc", "draft", "--project-dir", str(bare_project),
                           "--consulting-type", "结算审核", "--stage", "审定")
    assert code == 0 and env["warning_items"] == []
    code, env = run_script("zt-project", "inventory", "scan", "--project-dir", str(bare_project))
    assert code == 0 and env["status"] == "ok" and env["data"]["summary"]["required_total"] == 7


def test_inventory_script_uses_the_skill_data_dir_without_env(tmp_path):
    import os

    env_vars = {k: v for k, v in os.environ.items() if k != "ZT_PROJECT_DATA"}
    proc = subprocess.run([sys.executable, str(SKILLS / "zt-project" / "scripts" / "inventory.py"), "scan",
                           "--project-dir", str(SAMPLE_PROJECT)],
                          cwd=tmp_path, capture_output=True, env=env_vars, check=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert json.loads(proc.stdout.decode("utf-8"))["data"]["scope"]["checklist_set"] == "20002"


# ---------------------------------------------------------------- zt-archive


@pytest.fixture
def archive_project(tmp_path) -> tuple[Path, Path]:
    proj = tmp_path / "项目 缓存" / "2026-001-示例住院楼"
    shutil.copytree(SAMPLE_PROJECT, proj)
    (proj / "工作" / "2026-10-19-核对" / "待确认清单.md").write_text("- [x] 已处理\n", encoding="utf-8")
    index = tmp_path / "案例索引.md"
    index.write_text(INDEX_2026.replace("2026-001", "2025-050").replace("2026-004", "2026-001")
                     .replace("| 乙 |", "| 示例住院楼 |"), encoding="utf-8")
    return proj, index


def archive(*args: str) -> tuple[int, Any]:
    return run_script("zt-archive", "archive", *args)


def test_check_passes_and_lists_push_files_with_sha256(archive_project):
    proj, index = archive_project
    code, env = archive("check", "--project-dir", str(proj), "--index", str(index))
    assert code == 0 and env["status"] == "ok", env
    push = {p["rel_path"]: p for p in env["data"]["push_list"]}
    assert "成果/结算审核报告.docx" in push and "项目说明.md" in push and "工作/2026-10-19-核对/核对结果.json" in push
    assert push["项目说明.md"]["sha256"] == hashlib.sha256((proj / "项目说明.md").read_bytes()).hexdigest()
    assert env["data"]["deliverables"] == sorted(["成果/审核汇总表.xlsx", "成果/结算审核报告.docx", "成果/结算审定单.xlsx"])
    assert env["data"]["casebook_row"]["工程名"] == "示例住院楼"
    assert env["warning_items"] == []


def test_check_blocks_when_results_missing_or_listed_file_gone(archive_project):
    proj, _ = archive_project
    (proj / "成果" / "结算审定单.xlsx").unlink()
    code, env = archive("check", "--project-dir", str(proj))
    assert env["status"] == "insufficient" and env["status_reason"] == "not_ready_to_archive"
    assert env["data"]["blocking"] == ["deliverable_listed_but_missing"]
    assert "成果/结算审定单.xlsx" in env["warning_items"][0]["message"] and env["warning_items"][0]["level"] == "error"
    shutil.rmtree(proj / "成果")
    _, env = archive("check", "--project-dir", str(proj))
    assert "no_deliverables" in env["data"]["blocking"]


def test_check_warns_about_open_items_unlisted_results_bad_work_names_and_temp_files(archive_project):
    proj, _ = archive_project
    (proj / "工作" / "2026-10-19-核对" / "待确认清单.md").write_text("- [ ] 问用户A\n- [ ] 问用户B\n- [x] 完成\n", encoding="utf-8")
    (proj / "工作" / "随手记").mkdir()
    (proj / "工作" / "随手记" / "a.txt").write_text("x", encoding="utf-8")
    (proj / "工作" / "2026-10-20-空任务").mkdir()
    (proj / "工作" / "散落.xlsx").write_bytes(b"x")
    (proj / "成果" / "新增报告.docx").write_bytes(b"x")
    (proj / "成果" / "~$新增报告.docx").write_bytes(b"x")
    code, env = archive("check", "--project-dir", str(proj))
    assert code == 0 and env["status"] == "ok"
    codes = {w["code"]: w for w in env["warning_items"]}
    assert set(codes) == {"open_items", "work_dir_name", "work_dir_empty", "work_loose_files",
                          "deliverable_unlisted", "temp_file_in_deliverables"}
    assert "2 条未勾选" in codes["open_items"]["message"]
    assert all(w["level"] == "warn" for w in env["warning_items"])
    assert "成果/~$新增报告.docx" not in [p["rel_path"] for p in env["data"]["push_list"]]


def test_check_blocks_undecided_scope_and_missing_doc(archive_project):
    proj, _ = archive_project
    text = (proj / "项目说明.md").read_text(encoding="utf-8").replace("阶段: 审定", "阶段: 待确认")
    (proj / "项目说明.md").write_text(text, encoding="utf-8")
    _, env = archive("check", "--project-dir", str(proj))
    assert env["data"]["blocking"] == ["project_doc_undecided"]
    (proj / "项目说明.md").unlink()
    _, env = archive("check", "--project-dir", str(proj))
    assert "project_doc_missing" in env["data"]["blocking"]


def test_apply_updates_project_doc_and_casebook_and_lists_push_files(archive_project):
    proj, index = archive_project
    (proj / "成果" / "新增报告.docx").write_bytes(b"x")
    code, env = archive("apply", "--project-dir", str(proj), "--index", str(index), "--key-metrics", "单方 3200 元/㎡")
    assert code == 0 and env["status"] == "ok", env
    doc = (proj / "项目说明.md").read_text(encoding="utf-8")
    assert read_project_doc(doc)["状态"] == "已归档"
    assert section_bullets(doc, "已出成果") == sorted(
        ["成果/新增报告.docx", "成果/审核汇总表.xlsx", "成果/结算审核报告.docx", "成果/结算审定单.xlsx"])
    row = parse_casebook(index.read_text(encoding="utf-8")).find("2026-001")
    assert row["状态"] == "已归档" and row["关键指标"] == "单方 3200 元/㎡"
    assert row["成果链接"] == "项目/2026-001-示例住院楼/成果/" and row["咨询类型"] == "结算审核"
    assert [f["path"] for f in env["data"]["files"]] == ["项目/2026-001-示例住院楼/项目说明.md", "案例索引.md"]
    # 其他项目的行不动
    assert parse_casebook(index.read_text(encoding="utf-8")).find("2026-001")["工程名"] == "示例住院楼"
    # 幂等：再 apply 一次内容不变
    before = (doc, index.read_text(encoding="utf-8"))
    archive("apply", "--project-dir", str(proj), "--index", str(index), "--key-metrics", "单方 3200 元/㎡")
    assert (proj / "项目说明.md").read_text(encoding="utf-8") == before[0] and index.read_text(encoding="utf-8") == before[1]


def test_apply_refuses_when_blocked_and_leaves_files_untouched(archive_project):
    proj, index = archive_project
    shutil.rmtree(proj / "成果")
    snapshot = ((proj / "项目说明.md").read_bytes(), index.read_bytes())
    code, payload = archive("apply", "--project-dir", str(proj), "--index", str(index))
    assert (code, payload["error"]["code"]) == (2, "not_ready_to_archive")
    assert ((proj / "项目说明.md").read_bytes(), index.read_bytes()) == snapshot


def test_apply_creates_casebook_when_missing(archive_project, tmp_path):
    proj, _ = archive_project
    new_index = tmp_path / "全新" / "案例索引.md"
    code, env = archive("apply", "--project-dir", str(proj), "--index", str(new_index))
    assert code == 0, env
    assert parse_casebook(new_index.read_text(encoding="utf-8")).find("2026-001")["状态"] == "已归档"
    assert new_index.read_text(encoding="utf-8").startswith("# 案例索引")


# ---------------------------------------------------------------- zt-ask 脚本是 textextract 子命令的薄封装


def test_ask_scripts_forward_to_textextract_cli(tmp_path):
    (tmp_path / "说明.txt").write_text("合同价款 调整", encoding="utf-8")
    code, env = run_script("zt-ask", "read_doc", "--root", str(tmp_path), "--file", "说明.txt")
    assert code == 0 and env["data"]["text"] == "合同价款 调整"
    code, env = run_script("zt-ask", "find_text", "--root", str(tmp_path), "--keyword", "合同价款")
    assert code == 0 and env["data"]["hit_count"] == 1


def test_create_cleans_up_when_it_fails_midway(cache, monkeypatch):
    """写项目说明或案例索引失败时，不留下半成品目录；已存在的同名目录不受影响（先于清理被拒绝）。"""
    mod = load_script("zt-project", "new_project")
    import io as _io

    def boom(path, text):
        raise OSError("磁盘已满")

    monkeypatch.setattr(mod, "write_text_atomic", boom)
    out = _io.StringIO()
    code = mod.cli.main(["create", "--index", str(cache / "案例索引.md"), "--root", str(cache), "--name", "示例",
                         "--consulting-type", "结算审核", "--stage", "审定", "--year", "2026"], stdout=out)
    assert code == 2 and json.loads(out.getvalue())["error"]["code"] == "internal_error"
    assert not (cache / "项目" / "2026-005-示例").exists()
    assert (cache / "案例索引.md").read_text(encoding="utf-8") == INDEX_2026


def test_check_ignores_symlinks_pointing_outside(archive_project, tmp_path):
    import os

    proj, _ = archive_project
    outside = tmp_path / "别处.xlsx"
    outside.write_bytes(b"x")
    try:
        os.symlink(outside, proj / "成果" / "链接.xlsx")
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不允许创建符号链接")
    _, env = archive("check", "--project-dir", str(proj))
    assert any(w["code"] == "symlink_outside_project" for w in env["warning_items"])
    assert "成果/链接.xlsx" not in [p["rel_path"] for p in env["data"]["push_list"]]
    assert "成果/链接.xlsx" not in env["data"]["deliverables"]
