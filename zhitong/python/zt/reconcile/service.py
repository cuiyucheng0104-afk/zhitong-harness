# 来源：engine-service/app/api/stubs.py reconcile_run（zhitong-cost-ai@991ff5cd）
"""送审 vs 审定核对的接线层：请求校验 → 读文件 → :func:`zt.reconcile.engine.run` → 结果信封。

``data`` 字段（金额与数量所在对象带 ``needs_manual: true``）：

- ``rows``：逐行核对结果（编码、名称、两侧量价额、``diff`` = 送审 − 审定、``status`` ∈ 一致/调整/仅送审/仅审定/待核实、
  两侧回到原表的 file/sheet/row）。
- ``total_diff``：核减额合计（正 = 审减，负 = 审增）。
- ``chapters``：按章汇总，按核减额绝对值降序。
- ``summary``：两侧合计、核减额与核减率、各状态行数、量差/价差归因、所用口径。
- ``file_coverage``：两侧各自的解析覆盖率。
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict

from zt.common.envelope import Envelope
from zt.costsheet import service as svc
from zt.costsheet.xlsx_out import KV_COLUMNS, MONEY_FORMAT, Column, Sheet, kv_rows, write_workbook
from zt.reconcile import engine

XLSX_NAME = "核对结果.xlsx"


class ReconcileRequest(BaseModel):
    """核对请求（``--in`` 的 JSON；字段名沿用旧 ``ReconcileIn``，``rel_path`` 改为 ``path``）。"""

    model_config = ConfigDict(extra="forbid")

    submitted_file: Union[str, svc.FileRef]
    approved_file: Union[str, svc.FileRef]
    basis: Literal["auto", "current", "cumulative", "contract"] = "auto"


def run(request: ReconcileRequest, *, max_files: int = svc.MAX_FILES,
        max_total_mb: float = svc.MAX_TOTAL_MB) -> Envelope:
    """执行一次核对。

    :param request: 已校验的请求。
    :param max_files: 送检份数上限。
    :param max_total_mb: 送检合计大小上限（MB）。
    :returns: ok / partial；解析不出可比的行、口径问题、无价或 ``.xls`` 时为 insufficient。
    :raises ZtError: 文件不存在或超过送检上限。
    """
    specs = [request.submitted_file, request.approved_file]
    rejected = svc.xls_rejection(specs)
    if rejected is not None:
        return rejected
    a, b = svc.load_files(specs, max_files=max_files, max_total_mb=max_total_mb)
    try:
        result = engine.run(a.raw, a.file_name, b.raw, b.file_name, basis=request.basis,
                            submitted_file_id=a.file_id, approved_file_id=b.file_id)
    except engine.ParseFailed as exc:
        return svc.parse_failed(exc.detail())
    data = {
        "rows": result["rows"],
        "total_diff": result["total_diff"],
        "chapters": result["chapters"],
        "summary": result["summary"],
        "file_coverage": result["file_coverage"],
    }
    return svc.build_envelope(data, result["warning_items"], result["file_coverage"],
                              sum(c["checked_rows"] for c in result["file_coverage"]))


_ROW_COLUMNS = [
    Column("状态", "status"),
    Column("项目编码", "item_code"),
    Column("项目名称", "item_name"),
    Column("项目特征", "feature"),
    Column("单位", "unit"),
    Column("章", "chapter_name"),
    Column("单位工程", "unit_project"),
    Column("送审工程量", "submitted_qty"),
    Column("审定工程量", "approved_qty"),
    Column("送审单价", "submitted_price", MONEY_FORMAT),
    Column("审定单价", "approved_price", MONEY_FORMAT),
    Column("送审合价", "submitted_amount", MONEY_FORMAT),
    Column("审定合价", "approved_amount", MONEY_FORMAT),
    Column("核减额(送审−审定)", "diff", MONEY_FORMAT),
    Column("量差", "diff_by_qty", MONEY_FORMAT),
    Column("价差", "diff_by_price", MONEY_FORMAT),
    Column("匹配依据", "matched_by"),
    Column("标记", lambda r: list(r.get("calc_flags") or []) + ([r["rounding_note"]] if r.get("rounding_note") else [])),
    Column("送审位置", lambda r: _loc(r, "submitted")),
    Column("审定位置", lambda r: _loc(r, "approved")),
]

_CHAPTER_COLUMNS = [
    Column("章码", "chapter"),
    Column("章名", "chapter_name"),
    Column("送审合价", "a_amount", MONEY_FORMAT),
    Column("审定合价", "b_amount", MONEY_FORMAT),
    Column("核减额", "adjust", MONEY_FORMAT),
    Column("行数", "count"),
]


def _loc(row: dict, side: str) -> Optional[str]:
    sheet, line = row.get(f"{side}_sheet"), row.get(f"{side}_row")
    if not sheet:
        return None
    return f"{row.get(f'{side}_file') or ''}「{sheet}」第 {line} 行"


def export_xlsx(data: dict, path: Path) -> Path:
    """把核对结果写成工作底稿：汇总、逐行核对、按章汇总三张表。

    :param data: :func:`run` 信封里的 ``data``。
    :param path: 目标 xlsx。
    :returns: 写入的路径。
    """
    s = data["summary"]
    summary = kv_rows([
        ("送审合计", s.get("a_total")), ("审定合计", s.get("b_total")),
        ("核减额(正=审减)", s.get("adjust_amount")), ("核减率", s.get("adjust_rate")),
        ("行数", s.get("count_total")), ("一致", s.get("count_same")), ("调整", s.get("count_changed")),
        ("仅送审", s.get("count_only_a")), ("仅审定", s.get("count_only_b")), ("待核实", s.get("count_uncertain")),
        ("量差合计", s.get("diff_by_qty")), ("价差合计", s.get("diff_by_price")),
        ("对比口径", s.get("basis")), ("送审取数口径", (s.get("basis_label") or {}).get("submitted")),
        ("审定取数口径", (s.get("basis_label") or {}).get("approved")),
        ("说明", "金额与数量由脚本按表格取数计算，需人工复核"),
    ])
    for r in summary:
        if r["k"] == "核减率" and isinstance(r["v"], float):
            r["v"] = f"{r['v']:.2%}"
    return write_workbook(path, [
        Sheet("汇总", KV_COLUMNS, summary),
        Sheet("逐行核对", _ROW_COLUMNS, data["rows"]),
        Sheet("按章汇总", _CHAPTER_COLUMNS, data["chapters"]),
    ])
