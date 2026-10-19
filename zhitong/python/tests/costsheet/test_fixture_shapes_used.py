# 来源：engine-service/tests/test_fixture_shapes_used.py（zhitong-cost-ai@991ff5cd）
"""防孤儿：tests/costsheet/fixtures/costsheet_shapes.py 里 @shape 登记的每个真实版式夹具，
至少被一个测试文件引用（WS08-20，issue #724）。造了形状却没人测，等于没造。"""
from __future__ import annotations

import re
from pathlib import Path

from tests.costsheet.fixtures import costsheet_shapes

TESTS = Path(__file__).resolve().parents[1]


def test_every_shape_is_used_by_some_test():
    corpus = ""
    for p in TESTS.glob("*/test_*.py"):
        if p.name == Path(__file__).name:
            continue
        corpus += p.read_text(encoding="utf-8")
    assert len(costsheet_shapes.SHAPES) >= 14, "WS08-20 要求 14 种真实版式"
    orphans = [n for n in costsheet_shapes.SHAPES if not re.search(rf"\bshapes\.{n}\(", corpus)]
    assert not orphans, f"这些夹具没有任何用例引用：{orphans}"
