"""CLI 基类：子命令分发、--in/--out、错误 JSON 与退出码。"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from zt.common import Call, Cli, Envelope, ZtError, empty, manual, ok

PYTHON_ROOT = Path(__file__).resolve().parents[2]


def make_cli() -> Cli:
    cli = Cli("zt.demo", "演示")

    @cli.command("sum", help="求和", arguments=lambda p: p.add_argument("--scale", type=int, default=1))
    def _sum(call: Call) -> Envelope:
        values = call.request.get("values", [])
        if not values:
            return empty("no_values")
        return ok({"total": manual({"value": sum(values) * call.args.scale})})

    @cli.command("fail", help="可预期失败")
    def _fail(call: Call) -> Envelope:
        raise ZtError("missing_input", "缺少送审计价表", hint="在项目说明里指明送审计价表")

    @cli.command("crash", help="未预期失败")
    def _crash(call: Call) -> Envelope:
        raise RuntimeError("boom")

    @cli.command("dict-empty", help="返回空 ok 的字典")
    def _dict_empty(call: Call) -> dict[str, Any]:
        return {"status": "ok", "data": {}}

    @cli.command("dict-ok", help="返回字典")
    def _dict_ok(call: Call) -> dict[str, Any]:
        return {"status": "ok", "data": {"n": 1}}

    return cli


def run(argv: list[str]) -> tuple[int, Any]:
    out = io.StringIO()
    code = make_cli().main(argv, stdout=out)
    text = out.getvalue()
    assert text.count("\n") == 1, "stdout 只输出一个 JSON 文档"
    return code, json.loads(text)


def test_success_to_stdout(tmp_path: Path) -> None:
    req = tmp_path / "request.json"
    req.write_text(json.dumps({"values": [1, 2]}), encoding="utf-8")
    code, payload = run(["sum", "--in", str(req), "--scale", "10"])
    assert code == 0
    assert payload["status"] == "ok"
    assert payload["data"]["total"] == {"value": 30, "needs_manual": True}


def test_empty_result_is_not_success_with_empty_data() -> None:
    code, payload = run(["sum"])
    assert code == 0
    assert payload["status"] == "empty"
    assert payload["status_reason"] == "no_values"


def test_out_file_and_summary(tmp_path: Path) -> None:
    req = tmp_path / "request.json"
    req.write_text(json.dumps({"values": [4]}), encoding="utf-8")
    target = tmp_path / "工作" / "结果.json"
    code, payload = run(["sum", "--in", str(req), "--out", str(target)])
    assert code == 0
    assert payload == {"status": "ok", "status_reason": None, "warning_items": [], "out": str(target)}
    assert json.loads(target.read_text(encoding="utf-8"))["data"]["total"]["value"] == 4


def test_out_directory(tmp_path: Path) -> None:
    out_dir = tmp_path / "work"
    out_dir.mkdir()
    code, payload = run(["sum", "--out", str(out_dir)])
    assert code == 0
    assert payload["out"] == str(out_dir / "result.json")
    code, payload = run(["sum", "--out", str(tmp_path / "new") + "/"])
    assert payload["out"] == str(tmp_path / "new" / "result.json")
    assert (tmp_path / "new" / "result.json").is_file()


def test_expected_failure_exit_2() -> None:
    code, payload = run(["fail"])
    assert code == 2
    assert payload == {"error": {"code": "missing_input", "message": "缺少送审计价表", "hint": "在项目说明里指明送审计价表"}}


def test_unexpected_failure_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = run(["crash"])
    assert code == 2
    assert payload["error"]["code"] == "internal_error"
    assert "boom" in payload["error"]["message"]
    assert "RuntimeError" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [[], ["nope"], ["sum", "--scale", "x"]])
def test_usage_errors_are_json(argv: list[str]) -> None:
    code, payload = run(argv)
    assert code == 2
    assert payload["error"]["code"] == "usage"


def test_missing_and_invalid_input(tmp_path: Path) -> None:
    code, payload = run(["sum", "--in", str(tmp_path / "missing.json")])
    assert (code, payload["error"]["code"]) == (2, "input_not_found")
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    code, payload = run(["sum", "--in", str(bad)])
    assert (code, payload["error"]["code"]) == (2, "invalid_json")


def test_dict_results_are_validated() -> None:
    code, payload = run(["dict-empty"])
    assert (code, payload["error"]["code"]) == (2, "invalid_result")
    code, payload = run(["dict-ok"])
    assert code == 0 and payload["needs_manual"] is True


def test_duplicate_command_rejected() -> None:
    cli = Cli("zt.x", "x")
    cli.command("a", help="a")(lambda call: ok({"a": 1}))
    with pytest.raises(ValueError):
        cli.command("a", help="a")(lambda call: ok({"a": 1}))


def test_real_process_stdout_is_utf8_json(tmp_path: Path) -> None:
    script = tmp_path / "demo_cli.py"
    script.write_text(
        "from zt.common import Cli, ok\n"
        "cli = Cli('zt.demo', 'demo')\n"
        "@cli.command('hello', help='hello')\n"
        "def hello(call):\n"
        "    import logging\n"
        "    logging.getLogger('zt.demo').info('日志只进 stderr')\n"
        "    return ok({'问候': '你好'})\n"
        "raise SystemExit(cli.main())\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(script), "hello"],
        capture_output=True,
        cwd=PYTHON_ROOT,
        env={**os.environ, "PYTHONPATH": str(PYTHON_ROOT), "PYTHONIOENCODING": "ascii"},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert json.loads(proc.stdout.decode("utf-8"))["data"] == {"问候": "你好"}
    assert "日志只进 stderr".encode("utf-8") in proc.stderr
