"""``python -m zt.textextract.cli extract`` 的信封映射与进程形态。"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.textextract import ws04_fixtures as fx
from zt.textextract.cli import cli

PYTHON_ROOT = Path(__file__).resolve().parents[2]


def run(argv: list[str]) -> tuple[int, Any]:
    out = io.StringIO()
    code = cli.main(argv, stdout=out)
    text = out.getvalue()
    assert text.count("\n") == 1, "stdout 只输出一个 JSON 文档"
    return code, json.loads(text)


def extract(root: Path, rel: str, *extra: str) -> tuple[int, Any]:
    return run(["extract", "--root", str(root), "--file", rel, *extra])


def test_complete_text_pdf_is_ok(tmp_path):
    (tmp_path / "a.pdf").write_bytes(fx.build_pdf(["text", "text"]))
    code, env = extract(tmp_path, "a.pdf")
    assert code == 0 and env["status"] == "ok" and env["needs_manual"] is True
    assert env["data"]["text_source"] == "text_layer" and env["data"]["complete"] is True
    assert fx.text_line(2) in env["data"]["text"]
    assert env["warning_items"] == []


def test_scanned_pdf_without_sidecar_is_insufficient_with_read_image_hint(tmp_path):
    (tmp_path / "扫描.pdf").write_bytes(fx.build_pdf(["image", "image"]))
    code, env = extract(tmp_path, "扫描.pdf")
    assert code == 0
    assert env["status"] == "insufficient" and env["status_reason"] == "needs_vision"
    assert env["data"]["text_source"] == "none" and env["data"]["text"] == ""
    warn = env["warning_items"][0]
    assert warn["code"] == "needs_vision" and warn["level"] == "warn" and "read_image" in warn["hint"]


def test_mixed_pdf_is_partial_and_lists_missing_pages(tmp_path):
    (tmp_path / "混合.pdf").write_bytes(fx.build_pdf(["text", "image", "text", "vector"]))
    code, env = extract(tmp_path, "混合.pdf")
    assert env["status"] == "partial"
    assert env["coverage"]["pages_missing"] == [2, 4] and env["coverage"]["pages_ok"] == [1, 3]
    warn = next(w for w in env["warning_items"] if w["code"] == "scanned_pages_need_vision")
    assert "p2" in warn["message"] and "p4" in warn["message"] and "read_image" in warn["hint"]


def test_sidecar_text_is_ok_with_info_warning(tmp_path):
    (tmp_path / "扫描.pdf").write_bytes(fx.build_pdf(["image"]))
    (tmp_path / "扫描.pdf.ocr.txt").write_text(fx.paged_sidecar([("ok", ["旁车正文 合同金额"])]), encoding="utf-8")
    _, env = extract(tmp_path, "扫描.pdf")
    assert env["status"] == "ok" and env["data"]["text_source"] == "ocr_sidecar"
    assert [w["code"] for w in env["warning_items"]] == ["text_from_sidecar"]
    assert env["warning_items"][0]["level"] == "info"


def test_no_sidecar_flag(tmp_path):
    (tmp_path / "扫描.pdf").write_bytes(fx.build_pdf(["image"]))
    (tmp_path / "扫描.pdf.ocr.txt").write_text(fx.paged_sidecar([("ok", ["旁车正文"])]), encoding="utf-8")
    _, env = extract(tmp_path, "扫描.pdf", "--no-sidecar")
    assert env["status"] == "insufficient"


def test_unsupported_format_is_error_level_insufficient(tmp_path):
    (tmp_path / "x.dwg").write_bytes(b"AC1027")
    _, env = extract(tmp_path, "x.dwg")
    assert env["status"] == "insufficient" and env["status_reason"] == "unsupported_format"
    assert env["warning_items"][0]["level"] == "error"


def test_truncated_is_partial(tmp_path):
    (tmp_path / "a.pdf").write_bytes(fx.build_pdf(["text"] * 4))
    _, env = extract(tmp_path, "a.pdf", "--page-limit", "2")
    assert env["status"] == "partial" and env["coverage"]["truncated"] is True
    assert "text_truncated" in [w["code"] for w in env["warning_items"]]


def test_text_out_writes_file_and_omits_inline_text(tmp_path):
    (tmp_path / "a.txt").write_text("合同金额 100 万元", encoding="utf-8")
    target = tmp_path / "工作" / "a.txt"
    _, env = extract(tmp_path, "a.txt", "--text-out", str(target))
    assert "text" not in env["data"] and env["data"]["text_path"] == str(target)
    assert target.read_text(encoding="utf-8") == "合同金额 100 万元\n"


def test_out_file_writes_envelope_and_summary(tmp_path):
    (tmp_path / "a.txt").write_text("正文", encoding="utf-8")
    result = tmp_path / "r.json"
    _, summary = extract(tmp_path, "a.txt", "--out", str(result))
    assert summary["status"] == "ok" and summary["out"] == str(result)
    assert json.loads(result.read_text(encoding="utf-8"))["data"]["text"] == "正文"


def test_errors_exit_2_with_error_json(tmp_path):
    code, payload = extract(tmp_path, "../etc/passwd")
    assert (code, payload["error"]["code"]) == (2, "invalid_path")
    code, payload = extract(tmp_path, "不存在.pdf")
    assert (code, payload["error"]["code"]) == (2, "file_not_found")
    code, payload = run(["extract", "--root", str(tmp_path / "无此目录"), "--file", "a.pdf"])
    assert (code, payload["error"]["code"]) == (2, "root_not_found")


def test_real_process_with_chinese_and_space_paths(tmp_path):
    d = tmp_path / "项目 一" / "资料"
    d.mkdir(parents=True)
    (d / "合同 终稿.txt").write_text("合同金额 100 万元", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "zt.textextract.cli", "extract", "--root", str(tmp_path / "项目 一"),
         "--file", "资料/合同 终稿.txt"],
        cwd=PYTHON_ROOT, capture_output=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    env = json.loads(proc.stdout.decode("utf-8"))
    assert env["status"] == "ok" and env["data"]["text"] == "合同金额 100 万元"
