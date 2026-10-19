# 来源：engine-service/tests/test_golden.py 的负控用例（zhitong-cost-ai@991ff5cd）
"""金标比对器自己的负控：归一化不能把业务结果抹掉，投影不能把漂移藏起来。"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from tests.costsheet.fixtures import golden

RECONCILE = Path(__file__).resolve().parents[1] / "reconcile" / "fixtures" / "golden" / "reconcile_run.json"


def test_normalize_only_strips_time_fields_and_manual_marks():
    sample = {"total_diff": 18500.0, "usage": {"latency_ms": 42, "prompt_tokens": 0},
              "rows": [{"diff": 1.005, "status": "调整", "needs_manual": True}]}
    out = golden.normalize(sample)
    assert "latency_ms" not in out["usage"], "latency_ms 应被剥离"
    assert out["usage"]["prompt_tokens"] == 0, "prompt_tokens 是业务字段，不许剥"
    assert out["total_diff"] == 18500.0, "金额不许被抹"
    assert out["rows"][0] == {"diff": 1.005, "status": "调整"}
    a = golden.normalize({"rate": 0.142307})["rate"]
    b = golden.normalize({"rate": 0.144900})["rate"]
    assert a != b, "归一化把不同的比率抹成了同一个值 —— 闸被削弱了"


def test_projection_still_sees_changed_and_missing_values():
    expected = {k: v for k, v in golden.normalize(json.loads(RECONCILE.read_text(encoding="utf-8"))).items()
                if k not in golden.HTTP_ONLY_KEYS}
    assert golden.project(expected, copy.deepcopy(expected)) == expected
    changed = copy.deepcopy(expected)
    changed["rows"][0]["diff"] = 1.0
    assert golden.project(expected, changed) != expected, "改了一行的核减额，投影后必须看得出来"
    missing = copy.deepcopy(expected)
    del missing["summary"]["adjust_rate"]
    assert golden.project(expected, missing) != expected, "金标里的键在新输出里消失，必须看得出来"
    extra = copy.deepcopy(expected)
    extra["rows"][0]["新字段"] = 1
    assert golden.project(expected, extra) == expected, "新输出多出的键不比"
