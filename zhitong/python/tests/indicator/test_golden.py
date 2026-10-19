# 来源：engine-service/tests/test_golden.py（zhitong-cost-ai@991ff5cd）的 indicator_calc 用例
"""指标金标：``tests/costsheet/fixtures/指标-计价表.xlsx`` → 冻结输出（比对口径见 :mod:`tests.costsheet.fixtures.golden`）。"""
from __future__ import annotations

from pathlib import Path

from tests.costsheet.fixtures import golden
from tests.costsheet.fixtures.endpoint import client

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "indicator_calc.json"


def test_golden_indicator_calc():
    r = client.post("/engine/indicator/calc", json={
        "baseline": {"gross_area": 5000, "indicator_baselines": {"unit_cost": 25.0}},
        "price_files": [{"file_id": "p1", "path": str(golden.FIXTURES / "指标-计价表.xlsx"),
                         "file_name": "指标-计价表.xlsx"}],
    })
    assert r.status_code == 200, r.text[:300]
    golden.check(GOLDEN, r.json())


def test_golden_file_is_not_empty():
    golden.assert_not_empty(GOLDEN)
