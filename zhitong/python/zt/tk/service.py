# 来源：engine-service/app/api/stubs.py tk_detect（zhitong-cost-ai@991ff5cd）
"""投控异常检测的接线层：请求校验 → 读文件 → :func:`zt.tk.engine.run` → 结果信封。

引擎只产「疑似」：每条异常 ``review_status`` 恒为 ``pending``，终判归造价师（:mod:`zt.tk.review` 记录复核决定）。

``data`` 字段（金额所在对象带 ``needs_manual: true``）：

- ``anomalies``：异常清单。``type`` 是规则（duplicate / code_repeat / zangu / self_check / big_amount /
  price_over_baseline / qty_over_baseline / missing_submit / new_item），``anomaly_type`` 是中文类别，
  ``detail`` 是证据文案，``anomaly_id`` 是跨轮次稳定的身份（项目、文件、表、行）。
- ``alignment_issues`` / ``align_suggestions``：与合同清单对不准、需要人工指定的行（不带金额）。
- ``rules_version``、``rules_run``、``rules_skipped``：阈值版本与本轮跑了哪些规则、为什么跳过。
- ``baseline``：合同基准的状态（not_provided / provided / invalid）与对齐统计。
- ``scope_label``、``file_coverage``：送检范围与逐文件覆盖率。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from zt.common.envelope import Envelope
from zt.costsheet import service as svc
from zt.costsheet.xlsx_out import KV_COLUMNS, MONEY_FORMAT, Column, Sheet, kv_rows, write_workbook
from zt.tk import engine

XLSX_NAME = "投控异常.xlsx"


class TkRequest(BaseModel):
    """投控请求（字段名沿用旧 ``TkDetectIn``）。

    ``baseline_files`` 是合同/中标清单文件（按合同价口径解析成基准行）；``baseline`` 是旧的清单级基准行
    ``[{item_code, item_name, item_feature, unit, base_qty, base_price, base_amount, source}]``，兼容但校验。
    """

    model_config = ConfigDict(extra="forbid")

    submission_files: list[Union[str, svc.FileRef]] = Field(min_length=1)
    baseline_files: list[Union[str, svc.FileRef]] = Field(default_factory=list)
    baseline: Optional[Any] = None
    project_id: str = ""
    basis: Literal["auto", "current", "cumulative", "contract"] = "auto"


def run(request: TkRequest, *, rules_path: Optional[Path] = None, max_files: int = svc.MAX_FILES,
        max_total_mb: float = svc.MAX_TOTAL_MB) -> Envelope:
    """执行一次投控异常检测。

    :param request: 已校验的请求。
    :param rules_path: 阈值配置；None 用随包的 ``zt/tk/data/tk_detect.yaml``。
    :param max_files: 送检份数上限（送审与合同清单合计）。
    :param max_total_mb: 送检合计大小上限（MB）。
    :returns: ok / partial（0 条异常且 ``coverage.rows_parsed`` > 0 是合法的「检出 0 条」）；
        送审文件全部读不出、全部无价、口径问题或有 ``.xls`` 时为 insufficient。
    :raises ZtError: 文件不存在或超过送检上限。
    """
    specs = list(request.submission_files) + list(request.baseline_files)
    rejected = svc.xls_rejection(specs)
    if rejected is not None:
        return rejected
    files = svc.load_files(specs, max_files=max_files, max_total_mb=max_total_mb)
    sub, base = files[:len(request.submission_files)], files[len(request.submission_files):]
    try:
        result = engine.run([f.as_tuple() for f in sub], request.baseline, project_id=request.project_id,
                            basis=request.basis, baseline_files=[f.as_tuple() for f in base],
                            rules_path=rules_path or engine.RULES_PATH)
    except engine.ParseFailed as exc:
        return svc.parse_failed(exc.detail())
    # 规则名在旧响应里叫 type（AnomalyRow），引擎内部叫 subtype
    anomalies = [{"type": a["subtype"], **{k: v for k, v in a.items() if k != "subtype"}}
                 for a in result["anomalies"]]
    data = {
        "anomalies": anomalies,
        "alignment_issues": result["alignment_issues"],
        "align_suggestions": result["align_suggestions"],
        "rules_version": result["rules_version"],
        "rules_run": result["rules_run"],
        "rules_skipped": result["rules_skipped"],
        "baseline": result["baseline"],
        "scope_label": result.get("scope_label"),
        "project_id": request.project_id,
        "file_coverage": result["file_coverage"],
    }
    return svc.build_envelope(data, result["warning_items"], result["file_coverage"], result["checked_rows"])


_ANOMALY_COLUMNS = [
    Column("序号", "seq"),
    Column("规则", "type"),
    Column("类别", "anomaly_type"),
    Column("置信档", "confidence_tier"),
    Column("项目编码", "item_code"),
    Column("项目名称", "item_name"),
    Column("单位", "unit"),
    Column("单位工程", "unit_project"),
    Column("送审金额", "line_amount", MONEY_FORMAT),
    Column("疑似超出", "excess_amount", MONEY_FORMAT),
    Column("基准值", "baseline_value"),
    Column("偏差%", "deviation_pct"),
    Column("证据", "detail"),
    Column("文件", "source_file"),
    Column("表", "sheet"),
    Column("行", "row"),
    Column("复核状态", "review_status"),
    Column("异常ID", "anomaly_id"),
]
_ISSUE_COLUMNS = [
    Column("类型", lambda r: {"conflict": "同码不同名或单位", "ambiguous": "合同清单多行可对"}.get(
        r.get("method") or "", "候选（名称单位相同）")),
    Column("项目编码", "item_code"),
    Column("项目名称", "item_name"),
    Column("单位", "unit"),
    Column("文件", "file"),
    Column("表", "sheet"),
    Column("行", "row"),
    Column("原因", "reason"),
    Column("合同清单候选", lambda r: [f"{c.get('item_code') or ''} {c.get('item_name') or ''}"
                                  f"（{c.get('sheet') or ''} 第 {c.get('row')} 行）"
                                  for c in (r.get("baseline") or r.get("candidates") or [])]),
]


def export_xlsx(data: dict, path: Path) -> Path:
    """把检测结果写成工作底稿：汇总、异常清单、对不准的行。

    :param data: :func:`run` 信封里的 ``data``。
    :param path: 目标 xlsx。
    :returns: 写入的路径。
    """
    rows = [dict(a, seq=i) for i, a in enumerate(data["anomalies"], start=1)]
    by_type: dict[str, int] = {}
    for a in data["anomalies"]:
        by_type[a["type"]] = by_type.get(a["type"], 0) + 1
    b = data.get("baseline") or {}
    summary = kv_rows([
        ("阈值版本", data.get("rules_version")), ("异常条数", len(rows)),
        ("按规则", by_type), ("合同基准", b.get("status")), ("基准行数", b.get("rows")),
        ("送检范围", data.get("scope_label")),
        ("说明", "引擎只给疑似，终判由造价师逐条复核；金额需人工复核"),
    ])
    issues = list(data.get("alignment_issues") or []) + list(data.get("align_suggestions") or [])
    return write_workbook(path, [
        Sheet("汇总", KV_COLUMNS, summary),
        Sheet("异常清单", _ANOMALY_COLUMNS, rows),
        Sheet("对不准的行", _ISSUE_COLUMNS, issues),
    ])


def anomaly_index(result: dict[str, Any]) -> dict[str, dict]:
    """从 ``result.json``（完整信封）建 ``anomaly_id → 异常`` 索引。

    :param result: 检测结果信封。
    :returns: 索引。
    """
    return {a["anomaly_id"]: a for a in (result.get("data") or {}).get("anomalies") or []}
