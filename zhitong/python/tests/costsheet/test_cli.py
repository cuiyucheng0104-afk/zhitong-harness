"""python -m zt.costsheet.cli probe：逐份标签，不出金额。"""
from __future__ import annotations

from tests.costsheet.cli_helpers import run_cli
from tests.costsheet.fixtures.golden import FIXTURES


def test_probe_labels_each_file(tmp_path):
    code, env = run_cli("zt.costsheet.cli", "probe", "--files", str(FIXTURES / "送审-计价表.xlsx"),
                        str(FIXTURES / "不可解析-样例.xlsx"), str(tmp_path / "旧.xls"), str(tmp_path / "无.xlsx"))
    assert code == 0 and env["status"] == "ok"
    kinds = [(f["kind"], f["reason_code"]) for f in env["data"]["files"]]
    assert kinds == [("costsheet", None), ("other", "no_list_header"), ("unknown", "xls"), ("unknown", "missing")]
    assert "另存为" in env["data"]["files"][2]["reason"]


def test_probe_without_files_is_empty():
    code, env = run_cli("zt.costsheet.cli", "probe")
    assert code == 0 and (env["status"], env["status_reason"]) == ("empty", "no_source_files")
