"""relayout：显示名还原、清理规则、旁车、图纸分离、编号、项目说明与案例索引、幂等、源目录只读、dry-run。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from zt.inventory.casebook import parse_casebook
from zt.inventory.projectdoc import read_project_doc, section_table

from tests.migration import _support as S

P1_DIR = "项目/2024-001-某某医院住院楼改造"


@pytest.fixture()
def world(tmp_path: Path) -> dict:
    w = S.write_world(tmp_path)
    w["export"] = S.export(w)
    return w


@pytest.fixture()
def done(world: dict) -> dict:
    code, res = S.relayout(world, world["export"])
    assert code == 0, res
    world["result"] = res
    world["manifest"] = S.manifest(world)
    world["mirror"] = world["root"] / "out" / "mirror"
    return world


def _paths(done: dict) -> set[str]:
    return {f["path"] for f in done["manifest"]["files"]}


def _deletion(done: dict, old_rel: str) -> dict:
    return next(d for d in done["manifest"]["deletions"] if d["old_rel"] == old_rel)


def test_display_names_restored_from_rows_not_from_suffix(done: dict) -> None:
    paths = _paths(done)
    assert f"{P1_DIR}/资料/合同/施工合同.pdf" in paths            # 磁盘 合同(1)/施工合同(1).pdf
    assert f"{P1_DIR}/资料/结算/报价(1).xlsx" in paths            # 显示名本身带 (1)，只去掉磁盘冲突后缀
    assert not any("报价.xlsx" in p for p in paths)
    renamed = {r["old_rel"]: r["new"] for r in done["manifest"]["renames"]}
    assert renamed["结算/报价(1)(1).xlsx"] == f"{P1_DIR}/资料/结算/报价(1).xlsx"


def test_duplicate_sha256_keeps_shortest_path(done: dict) -> None:
    d = _deletion(done, "照片/备份/旧/现场副本.jpg")
    assert d["reason"] == "duplicate_sha256" and d["kept"] == f"{P1_DIR}/资料/照片/现场.jpg"
    assert f"{P1_DIR}/资料/照片/现场.jpg" in _paths(done)


def test_old_format_removed_only_with_new_format_twin(done: dict) -> None:
    assert _deletion(done, "说明/方案.doc")["reason"] == "old_format_twin"
    assert _deletion(done, "表/汇总.xls")["reason"] == "old_format_twin"
    paths = _paths(done)
    assert f"{P1_DIR}/资料/说明/单独.doc" in paths and f"{P1_DIR}/资料/说明/方案.docx" in paths


def test_placeholder_sidecar_removed_paged_sidecar_follows_original(done: dict) -> None:
    d = _deletion(done, "扫描/报告.pdf.ocr.txt")
    assert d["reason"] == "ocr_placeholder_sidecar" and d["verdicts"] == {"failed": 2}
    paths = _paths(done)
    assert f"{P1_DIR}/资料/扫描/报告.pdf" in paths
    # 原件磁盘名 审定单(1).pdf 还原为 审定单.pdf，旁车跟着改名并与原件并列
    assert f"{P1_DIR}/资料/扫描/审定单.pdf.ocr.txt" in paths
    side = next(f for f in done["manifest"]["files"] if f["path"].endswith("审定单.pdf.ocr.txt"))
    assert side["kind"] == "sidecar" and side["old_path"].endswith("扫描/审定单(1).pdf.ocr.txt")


def test_drawings_separated(done: dict) -> None:
    paths = _paths(done)
    assert f"{P1_DIR}/图纸/建筑/一层平面.dwg" in paths           # 客户自己的「图纸/」一层不重复
    assert f"{P1_DIR}/图纸/施工图/一层平面图.pdf" in paths
    assert f"{P1_DIR}/资料/预算/施工图预算.pdf" in paths          # 施工图预算不是图纸
    assert "项目/2024-003-某厂房/图纸/总平面.dxf" in paths


def test_system_junk_index_and_not_migrated_lists(done: dict) -> None:
    reasons = {d["old_rel"]: d["reason"] for d in done["manifest"]["deletions"]}
    assert reasons[".DS_Store"] == "system_junk"
    assert reasons["INDEX.md"] == "index_md"
    assert reasons["合同(1)/~$施工合同.docx"] == "system_junk"
    assert reasons["照片/@eaDir/现场.jpg/SYNOPHOTO_THUMB_S.jpg"] == "system_junk"
    nm = {d["old_rel"]: d["reason"] for d in done["manifest"]["not_migrated"]}
    assert nm == {"未知/多出来.txt": "orphan", "结算/送审计价表(2).xlsx": "history_version"}
    assert [e["display_path"] for e in done["manifest"]["empty_folders"]] == ["空目录"]


def test_numbering_and_aliases(done: dict) -> None:
    dirs = {p["id"]: (p["dir"], p["code_origin"], p["aliases"]) for p in done["manifest"]["projects"]}
    assert dirs[S.P1] == (P1_DIR, "allocated", [])
    assert dirs[S.P2][0] == "项目/2024-002-某小学操场"
    assert dirs[S.P4] == ("项目/2024-003-某厂房", "allocated", ["HT-2024-18"])
    assert dirs[S.P3] == ("项目/2025-010-某道路", "client", [])
    assert dirs[S.P5][0] == "项目/2025-011-某公园"
    assert "1999" not in dirs


def test_project_doc_matches_w1_format(done: dict) -> None:
    text = (done["mirror"] / P1_DIR / "项目说明.md").read_text(encoding="utf-8")
    fields = read_project_doc(text, require=("项目编号", "工程名称", "咨询类型", "阶段"))
    assert fields["项目编号"] == "2024-001" and fields["工程名称"] == "某某医院 住院楼/改造"
    assert fields["旧系统项目ID"] == S.P1 and fields["业态"] == "房屋建筑工程" and fields["状态"] == "已完成"
    assert fields["咨询类型"] == "待确认" and fields["建立日期"] == "2024-03-01"
    guide = {r["资料"]: r["位置"] for r in section_table(text, "关键文件指引")}
    assert guide["合同"] == "资料/合同/施工合同.pdf"
    assert guide["图纸"] == "图纸/"
    template = (S.Path(__file__).resolve().parents[3] / "skills" / "zt-project" / "templates" / "项目说明.md").read_text(encoding="utf-8")
    for heading in [ln for ln in template.splitlines() if ln.startswith("## ")]:
        assert heading in text
    alias = read_project_doc((done["mirror"] / "项目/2024-003-某厂房/项目说明.md").read_text(encoding="utf-8"))
    assert alias["别名"] == ["HT-2024-18"]


def test_casebook_one_row_per_project(done: dict) -> None:
    book = parse_casebook((done["mirror"] / "案例索引.md").read_text(encoding="utf-8"))
    assert [r["编号"] for r in book.rows] == ["2024-001", "2024-002", "2024-003", "2025-010", "2025-011"]
    assert book.find("2024-001")["工程名"] == "某某医院 住院楼/改造"


def test_hardlinks_share_inode_with_source(done: dict) -> None:
    f = next(f for f in done["manifest"]["files"] if f["path"].endswith("施工合同.pdf"))
    assert os.stat(f["old_path"]).st_ino == (done["mirror"] / f["path"]).stat().st_ino


def test_second_run_is_idempotent_and_source_untouched(world: dict) -> None:
    before = S.snapshot(world["nas"])
    code, first = S.relayout(world, world["export"])
    assert code == 0
    m1 = S.manifest(world)
    code, second = S.relayout(world, world["export"])
    assert code == 0
    stats = second["data"]["stats"]
    assert stats["linked"] == 0 and stats["copied"] == 0 and stats["replaced"] == 0
    assert stats["kept"] == first["data"]["summary"]["outputs"] and stats["generated_written"] == 0
    assert S.manifest(world)["files"] == m1["files"]
    assert S.snapshot(world["nas"]) == before


def test_stale_mirror_file_removed_on_rerun(done: dict) -> None:
    stray = done["mirror"] / P1_DIR / "资料" / "上次留下的.txt"
    stray.write_text("x", encoding="utf-8")
    code, res = S.relayout(done, done["export"])
    assert code == 0 and res["data"]["stats"]["stale_removed"] == 1 and not stray.exists()


def test_numbering_stable_when_earlier_project_appears(world: dict) -> None:
    code, _ = S.relayout(world, world["export"])
    assert code == 0
    rows = world["rows"].read_text(encoding="utf-8")
    rows += json.dumps({"table": "project", "id": "1000", "name": "后补的老项目", "sys_company_code": "1",
                        "create_time": "2024-01-15 09:00:00", "modify_time": "2024-01-15 09:00:00", "del_flag": 0},
                       ensure_ascii=False) + "\n"
    world["rows"].write_text(rows, encoding="utf-8")
    export = S.export(world)
    code, _ = S.relayout(world, export)
    assert code == 0
    dirs = {p["id"]: p["code"] for p in S.manifest(world)["projects"]}
    assert dirs[S.P1] == "2024-001" and dirs["1000"] == "2024-004"


def test_dry_run_writes_nothing(world: dict) -> None:
    code, res = S.relayout(world, world["export"], "--dry-run")
    assert code == 0
    assert not (world["root"] / "out").exists()
    ops = {a["op"] for a in res["data"]["actions"]}
    assert ops == {"place", "generate"}
    assert res["data"]["summary"]["deletions_by_reason"]["old_format_twin"] == 2


def test_out_inside_source_refused(world: dict) -> None:
    code, res = S.run(S.relayout_main, "--export-dir", str(world["export"]), "--nas", str(world["nas"]),
                      "--out", str(world["nas"] / "mirror-out"))
    assert code == 2 and res["error"]["code"] == "unsafe_out_dir"


def test_include_orphans_copies_them_under_unregistered_dir(world: dict) -> None:
    code, _ = S.relayout(world, world["export"], "--include-orphans", "--link", "copy")
    assert code == 0
    paths = {f["path"] for f in S.manifest(world)["files"]}
    assert f"{P1_DIR}/资料/未登记文件/未知/多出来.txt" in paths
    f = world["root"] / "out" / "mirror" / P1_DIR / "资料" / "未登记文件" / "未知" / "多出来.txt"
    assert f.stat().st_ino != (world["nas"] / S.P1 / "未知" / "多出来.txt").stat().st_ino


def test_empty_nas_is_an_error(tmp_path: Path) -> None:
    w = S.write_world(tmp_path, files=[S.F(S.P1, "a.pdf", "a.pdf", None, "r1")])
    export = S.export(w)
    (w["nas"]).mkdir(parents=True, exist_ok=True)
    code, res = S.relayout(w, export)
    assert code == 2 and res["error"]["code"] == "nothing_to_migrate"
