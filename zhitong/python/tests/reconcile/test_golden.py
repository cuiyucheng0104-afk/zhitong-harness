# 来源：engine-service/tests/test_golden.py（zhitong-cost-ai@991ff5cd）的 reconcile_run 用例
"""核对金标：``tests/costsheet/fixtures`` 的送审/审定样例 → 冻结输出（比对口径见 :mod:`tests.costsheet.fixtures.golden`）。"""
from __future__ import annotations

from pathlib import Path

from tests.costsheet.fixtures import golden
from tests.costsheet.fixtures.endpoint import client

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "reconcile_run.json"


def test_golden_reconcile_run():
    r = client.post("/engine/reconcile/run", json={
        "submitted_file": {"file_id": "a", "path": str(golden.FIXTURES / "送审-计价表.xlsx"),
                           "file_name": "送审-计价表.xlsx"},
        "approved_file": {"file_id": "b", "path": str(golden.FIXTURES / "审定-计价表.xlsx"),
                          "file_name": "审定-计价表.xlsx"},
    })
    assert r.status_code == 200, r.text[:300]
    golden.check(GOLDEN, r.json())


def test_golden_file_is_not_empty():
    golden.assert_not_empty(GOLDEN)
