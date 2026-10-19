"""``python -m zt.sidecar.cli parse|locate``。"""
from __future__ import annotations

import io
import json
from typing import Any

from tests.textextract import ws04_fixtures as fx
from zt.sidecar.cli import cli


def run(argv: list[str]) -> tuple[int, Any]:
    out = io.StringIO()
    code = cli.main(argv, stdout=out)
    return code, json.loads(out.getvalue())


def test_parse_usable_sidecar(tmp_path):
    f = tmp_path / "报告.pdf.ocr.txt"
    f.write_text(fx.F2, encoding="utf-8")
    code, env = run(["parse", "--file", str(f)])
    assert code == 0 and env["status"] == "ok"
    assert env["data"]["usable_pages"] == [1, 3, 5] and "工程造价审定单" in env["data"]["text"]
    assert [w["code"] for w in env["warning_items"]] == ["sidecar_quality_suspect"]


def test_parse_all_failed_is_insufficient(tmp_path):
    f = tmp_path / "x.pdf.ocr.txt"
    f.write_text(fx.F1, encoding="utf-8")
    _, env = run(["parse", "--file", str(f)])
    assert env["status"] == "insufficient" and env["status_reason"] == "sidecar_unusable"
    assert "read_image" in env["warning_items"][0]["hint"]


def test_parse_errors(tmp_path):
    code, payload = run(["parse", "--file", str(tmp_path / "无.ocr.txt")])
    assert (code, payload["error"]["code"]) == (2, "file_not_found")
    bad = tmp_path / "bad.ocr.txt"
    bad.write_bytes("合同金额 999 万元".encode("utf-16-le"))
    code, payload = run(["parse", "--file", str(bad)])
    assert (code, payload["error"]["code"]) == (2, "undecodable")


def test_locate(tmp_path):
    (tmp_path / "资料").mkdir()
    (tmp_path / "资料" / "a.pdf").write_bytes(b"%PDF")
    code, env = run(["locate", "--root", str(tmp_path), "--file", "资料/a.pdf"])
    assert code == 0 and env["status"] == "empty" and env["status_reason"] == "no_sidecar"
    (tmp_path / "资料" / "a.pdf.ocr.txt").write_text(fx.F2, encoding="utf-8")
    _, env = run(["locate", "--root", str(tmp_path), "--file", "资料\\a.pdf", "--with-text"])
    assert env["status"] == "ok" and env["data"]["sidecar"] == "a.pdf.ocr.txt"
    assert "工程造价审定单" in env["data"]["text"]
    code, payload = run(["locate", "--root", str(tmp_path), "--file", "../x.pdf"])
    assert (code, payload["error"]["code"]) == (2, "invalid_path")
