"""投控异常的人工复核记录：只追加的 ``复核.jsonl``（zt 新写；旧仓在 Java 侧 ``audit_tk_decision_log``）。

一行一条决定：``{ts, anomaly_id, from_state, hitl_state, reason, reviewer, anomaly}``。
``hitl_state`` ∈ ``confirmed``（确认异常）/ ``dismissed``（判为误报）/ ``pending``（撤回为待复核），
与旧系统 ``audit_tk_anomaly.hitl_state`` 同一词表。某条异常的当前状态 = 日志里它的最后一条决定；
没有决定的是 ``pending``。日志只追加、不改写，改判就再追加一条。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from zt.common.errors import ZtError

STATES = ("confirmed", "dismissed", "pending")
_SNAPSHOT_KEYS = ("type", "anomaly_type", "item_code", "item_name", "source_file", "sheet", "row",
                  "line_amount", "excess_amount")


def read_log(path: Path) -> list[dict[str, Any]]:
    """读复核日志；文件不存在时为空。

    :param path: ``复核.jsonl``。
    :returns: 决定列表（按写入顺序）。
    :raises ZtError: 某行不是合法 JSON（code ``invalid_review_log``）。
    """
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ZtError("invalid_review_log", f"{path.name} 第 {n} 行不是合法 JSON：{exc.msg}",
                          hint="复核日志只追加；请恢复被手改的那一行") from None
    return out


def current_states(log: list[dict[str, Any]]) -> dict[str, str]:
    """每条异常的当前状态（最后一条决定）。

    :param log: :func:`read_log` 的结果。
    :returns: ``anomaly_id → hitl_state``。
    """
    states: dict[str, str] = {}
    for rec in log:
        states[rec["anomaly_id"]] = rec["hitl_state"]
    return states


def append_decision(path: Path, anomaly_id: str, state: str, reason: str, *,
                    anomaly: Optional[dict[str, Any]] = None, reviewer: Optional[str] = None,
                    now: Optional[datetime] = None) -> dict[str, Any]:
    """追加一条复核决定。

    :param path: ``复核.jsonl``；父目录不存在时创建。
    :param anomaly_id: 异常 ID（检测结果里的 ``anomaly_id``）。
    :param state: ``confirmed`` / ``dismissed`` / ``pending``。
    :param reason: 复核理由（判为误报与确认都要写）。
    :param anomaly: 检测结果里的这条异常，用来留一份定位快照。
    :param reviewer: 复核人。
    :param now: 时间（测试注入）；默认当前 UTC 时间。
    :returns: 写入的记录。
    :raises ZtError: 状态不在词表里或理由为空。
    """
    if state not in STATES:
        raise ZtError("invalid_state", f"复核状态只能是 {' / '.join(STATES)}：{state!r}")
    if not reason.strip():
        raise ZtError("reason_required", "复核决定必须写理由", hint="写明依据，例如对照了哪份合同清单的哪一行")
    prev = current_states(read_log(path)).get(anomaly_id, "pending")
    rec = {
        "ts": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "anomaly_id": anomaly_id,
        "from_state": prev,
        "hitl_state": state,
        "reason": reason.strip(),
        "reviewer": reviewer,
        "anomaly": {k: anomaly.get(k) for k in _SNAPSHOT_KEYS} if anomaly else None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def progress(anomaly_ids: list[str], log: list[dict[str, Any]]) -> dict[str, Any]:
    """复核进度：本轮异常里各状态的条数与仍待复核的 ID。

    :param anomaly_ids: 本轮检测结果里的异常 ID。
    :param log: 复核日志。
    :returns: ``{total, confirmed, dismissed, pending, pending_ids}``。
    """
    states = current_states(log)
    counts = {s: 0 for s in STATES}
    pending_ids = []
    for aid in anomaly_ids:
        s = states.get(aid, "pending")
        counts[s] += 1
        if s == "pending":
            pending_ids.append(aid)
    return {"total": len(anomaly_ids), **counts, "pending_ids": pending_ids}
