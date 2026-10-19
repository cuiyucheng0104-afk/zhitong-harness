"""zt.tk.review：只追加的复核日志与进度。"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from zt.common import ZtError
from zt.tk import review

NOW = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)


def test_append_and_states(tmp_path):
    log = tmp_path / "工作 目录" / "复核.jsonl"
    rec = review.append_decision(log, "A1", "confirmed", " 确认重复 ", anomaly={"type": "duplicate", "x": 1},
                                 reviewer="李工", now=NOW)
    assert rec == {"ts": "2026-10-19T08:00:00+00:00", "anomaly_id": "A1", "from_state": "pending",
                   "hitl_state": "confirmed", "reason": "确认重复", "reviewer": "李工",
                   "anomaly": {"type": "duplicate", "anomaly_type": None, "item_code": None, "item_name": None,
                               "source_file": None, "sheet": None, "row": None, "line_amount": None,
                               "excess_amount": None}}
    review.append_decision(log, "A1", "pending", "撤回", now=NOW)
    entries = review.read_log(log)
    assert [e["hitl_state"] for e in entries] == ["confirmed", "pending"]
    assert review.progress(["A1", "A2"], entries)["pending_ids"] == ["A1", "A2"]


@pytest.mark.parametrize("state,reason,code", [("ok", "x", "invalid_state"), ("dismissed", "  ", "reason_required")])
def test_rejects_bad_decisions(tmp_path, state, reason, code):
    with pytest.raises(ZtError) as exc:
        review.append_decision(tmp_path / "复核.jsonl", "A1", state, reason)
    assert exc.value.code == code
    assert not (tmp_path / "复核.jsonl").exists()


def test_corrupt_log_line_is_reported(tmp_path):
    log = tmp_path / "复核.jsonl"
    log.write_text('{"anomaly_id": "A1", "hitl_state": "confirmed"}\n{bad\n', encoding="utf-8")
    with pytest.raises(ZtError) as exc:
        review.read_log(log)
    assert exc.value.code == "invalid_review_log" and "第 2 行" in exc.value.message
