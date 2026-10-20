"""verify：整理后对账通过；镜像缺文件、内容被改、行没有去向、项目说明坏、NAS 缺文件时都以退出码 2 失败。

每个失败用例先在同一份夹具上确认校验通过，再做一处破坏，确保失败来自那处破坏而不是夹具本身。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.migration import _support as S

P1_DIR = "项目/2024-001-某某医院住院楼改造"


@pytest.fixture()
def done(tmp_path: Path) -> dict:
    w = S.write_world(tmp_path)
    w["export"] = S.export(w)
    code, res = S.relayout(w, w["export"])
    assert code == 0, res
    w["mirror"] = tmp_path / "out" / "mirror"
    code, res = S.verify(w, w["export"])
    assert code == 0, res
    return w


def _codes(w: dict) -> set[str]:
    problems = json.loads((w["root"] / "out" / "verify-problems.json").read_text(encoding="utf-8"))
    return {p["code"] for p in problems}


def test_clean_mirror_passes_with_counts(done: dict) -> None:
    code, res = S.verify(done, done["export"])
    assert code == 0 and res["status"] == "ok"
    p1 = next(p for p in res["data"]["projects"] if p["id"] == S.P1)
    assert p1["source_files"] == p1["migrated"] + p1["deleted"] == 16
    assert res["data"]["mirror_files"] > 0 and res["data"]["sha256_checked"] is True


def test_missing_mirror_file_fails(done: dict) -> None:
    (done["mirror"] / P1_DIR / "资料" / "合同" / "施工合同.pdf").unlink()
    code, res = S.verify(done, done["export"])
    assert code == 2 and res["error"]["code"] == "verify_failed"
    assert "mirror_file_missing" in res["error"]["message"]
    assert _codes(done) == {"mirror_file_missing"}


def test_changed_content_fails_unless_quick_and_same_size(done: dict) -> None:
    target = done["mirror"] / P1_DIR / "资料" / "表" / "汇总.xlsx"
    data = target.read_bytes()
    target.unlink()  # 断开硬链接，不改源文件
    target.write_bytes(bytes(reversed(data)))
    code, _ = S.verify(done, done["export"])
    assert code == 2 and _codes(done) == {"mirror_sha256_mismatch"}
    code, _ = S.verify(done, done["export"], "--quick")
    assert code == 0


def test_row_without_destination_fails(done: dict) -> None:
    mpath = done["root"] / "out" / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    victim = next(f for f in m["files"] if f.get("row_id") == "f03")
    m["files"].remove(victim)
    (done["mirror"] / victim["path"]).unlink()
    mpath.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    code, _ = S.verify(done, done["export"])
    assert code == 2
    assert {"row_unaccounted", "project_count_mismatch", "project_bytes_mismatch"} <= _codes(done)


def test_extra_file_in_mirror_fails(done: dict) -> None:
    (done["mirror"] / P1_DIR / "资料" / "手工放进来的.txt").write_text("x", encoding="utf-8")
    code, _ = S.verify(done, done["export"])
    assert code == 2 and _codes(done) == {"mirror_extra_file"}


def test_broken_project_doc_fails(done: dict) -> None:
    doc = done["mirror"] / P1_DIR / "项目说明.md"
    mpath = done["root"] / "out" / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    text = doc.read_text(encoding="utf-8").replace('项目编号: "2024-001"', '项目编号: "2024-1"')
    doc.write_text(text, encoding="utf-8")
    entry = next(f for f in m["files"] if f["path"] == f"{P1_DIR}/项目说明.md")
    entry["size"] = doc.stat().st_size
    mpath.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    code, _ = S.verify(done, done["export"], "--quick")
    assert code == 2 and _codes(done) == {"project_doc_invalid"}


def test_missing_source_needs_explicit_acceptance(tmp_path: Path) -> None:
    files = [*S.FILES, S.F(S.P2, "缺失/只有记录.pdf", "缺失/只有记录.pdf", None, "f22")]
    w = S.write_world(tmp_path, files=files)
    export = S.export(w)
    code, res = S.relayout(w, export)
    assert code == 0, res
    code, res = S.verify(w, export)
    assert code == 2 and _codes(w) == {"missing_source"}
    code, res = S.verify(w, export, "--accept-missing-source")
    assert code == 0 and "missing_source_accepted" in {x["code"] for x in res["warning_items"]}


def test_source_disappearing_after_relayout_fails(done: dict) -> None:
    src = done["nas"] / S.P2 / "招标文件" / "招标文件.docx"
    src.unlink()
    code, _ = S.verify(done, done["export"], "--quick")
    assert code == 2 and _codes(done) == {"source_file_missing_unreported"}


def test_empty_mirror_is_not_success(done: dict) -> None:
    mpath = done["root"] / "out" / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["files"] = [f for f in m["files"] if f["kind"] == "generated"]
    mpath.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    code, res = S.verify(done, done["export"])
    assert code == 2 and res["error"]["code"] == "no_files"
