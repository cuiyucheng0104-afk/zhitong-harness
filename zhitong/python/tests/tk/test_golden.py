# 来源：engine-service/tests/test_golden.py（zhitong-cost-ai@991ff5cd）的 tk_detect_v1 / tk_detect_v2_with_baseline 用例
"""投控金标：``tests/costsheet/fixtures/送审-异常样例.xlsx`` → 冻结输出（比对口径见 :mod:`tests.costsheet.fixtures.golden`）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.costsheet.fixtures import golden
from tests.costsheet.fixtures.endpoint import client

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"
SUBMISSION = [{"file_id": "s1", "path": str(golden.FIXTURES / "送审-异常样例.xlsx"), "file_name": "送审-异常样例.xlsx"}]
CASES = {
    "tk_detect_v1": {"project_id": "P001", "submission_files": SUBMISSION},
    "tk_detect_v2_with_baseline": {
        "project_id": "P001",
        "baseline": [
            {"project_id": "P001", "item_code": "010501001001", "item_name": "现浇混凝土基础",
             "item_feature": "C30", "unit": "m3", "base_qty": 300, "base_price": 400.0,
             "base_amount": 120000.0, "source": "合同清单"},
        ],
        "submission_files": SUBMISSION,
    },
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden_tk_detect(name):
    r = client.post("/engine/tk/detect", json=CASES[name])
    assert r.status_code == 200, r.text[:300]
    golden.check(GOLDEN_DIR / f"{name}.json", r.json())


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden_file_is_not_empty(name):
    golden.assert_not_empty(GOLDEN_DIR / f"{name}.json")
