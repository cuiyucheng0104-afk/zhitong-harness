# 来源：engine-service/app/api/stubs.py indicator_calc（zhitong-cost-ai@991ff5cd）
"""单方造价与章节占比的接线层：请求校验 → 读文件 → :func:`zt.indicator.engine.run` → 结果信封。

``data`` 字段（金额与比率所在对象带 ``needs_manual: true``）：

- ``indicators``：指标行（``indicator_code``、``value``、``label``、``baseline_value``、``deviation``）。
  回落到清单明细合计时 ``total_amount`` / ``unit_cost`` 两行的 ``label`` 写明「不是总造价 / 不是单方造价指标」。
- ``summary``：总造价口径 ``cost_basis`` ∈ user_input / fee_table / itemized 及其标签、面积、单方造价。
- ``chapters``、``top_items``、``fee_breakdown``：按章占比、造价驱动项 Top-N、费用构成。
- ``files_used`` / ``files_failed`` / ``file_coverage``：哪些文件计入、哪些没有及原因。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from zt.common.envelope import Envelope
from zt.costsheet import service as svc
from zt.costsheet.xlsx_out import KV_COLUMNS, MONEY_FORMAT, RATIO_FORMAT, Column, Sheet, kv_rows, write_workbook
from zt.indicator import engine

XLSX_NAME = "指标结果.xlsx"


class IndicatorRequest(BaseModel):
    """指标请求（字段名沿用旧 ``IndicatorIn``；``wbs_units`` 已不参与计算，不再接收）。

    ``baseline`` 可含 ``gross_area``、``total_amount``、``indicator_baselines``（``{指标编码: 对标值}``）、
    ``peer_library``（同类项目列表，字段见 :func:`zt.indicator.engine.match_similar`）与自身画像
    ``building_type`` / ``structure`` / ``project_id``。
    """

    model_config = ConfigDict(extra="forbid")

    price_files: list[Union[str, svc.FileRef]] = Field(min_length=1)
    baseline: Optional[dict[str, Any]] = None
    gross_area: Optional[float] = None
    area_source: Optional[str] = None
    total_amount: Optional[float] = None


def run(request: IndicatorRequest, *, max_files: int = svc.MAX_FILES,
        max_total_mb: float = svc.MAX_TOTAL_MB) -> Envelope:
    """计算指标。

    :param request: 已校验的请求。
    :param max_files: 送检份数上限。
    :param max_total_mb: 送检合计大小上限（MB）。
    :returns: ok / partial；全部文件不可计入、可计入不到一半或有 ``.xls`` 时为 insufficient。
    :raises ZtError: 文件不存在或超过送检上限。
    """
    rejected = svc.xls_rejection(request.price_files)
    if rejected is not None:
        return rejected
    files = svc.load_files(list(request.price_files), max_files=max_files, max_total_mb=max_total_mb)
    try:
        result = engine.run([f.as_tuple() for f in files], request.baseline or {}, None,
                            gross_area=request.gross_area, total_amount=request.total_amount,
                            area_source=request.area_source)
    except engine.ParseFailed as exc:
        return svc.parse_failed(exc.detail())
    data = {k: result[k] for k in ("indicators", "summary", "chapters", "top_items", "fee_breakdown",
                                   "files_used", "files_failed", "file_coverage")}
    return svc.build_envelope(data, result["warning_items"], result["file_coverage"], result["rows_parsed"])


_INDICATOR_COLUMNS = [
    Column("指标", lambda r: r.get("label") or r.get("indicator_code")),
    Column("编码", "indicator_code"),
    Column("值", "value", MONEY_FORMAT),
    Column("对标值", "baseline_value", MONEY_FORMAT),
    Column("偏差", "deviation", RATIO_FORMAT),
    Column("说明", "reason"),
]
_CHAPTER_COLUMNS = [
    Column("章码", "chapter"),
    Column("章名", lambda r: r.get("label") or r.get("chapter_name")),
    Column("合价", "amount", MONEY_FORMAT),
    Column("占比", "pct", RATIO_FORMAT),
    Column("单方(元/㎡)", "unit_cost", MONEY_FORMAT),
    Column("行数", "count"),
]
_TOP_COLUMNS = [
    Column("项目编码", "code"),
    Column("项目名称", "name"),
    Column("单位", "unit"),
    Column("合价", "amount", MONEY_FORMAT),
    Column("占比", "pct", RATIO_FORMAT),
]


def export_xlsx(data: dict, path: Path) -> Path:
    """把指标结果写成工作底稿：汇总、指标、按章、造价驱动项、未计入文件。

    :param data: :func:`run` 信封里的 ``data``。
    :param path: 目标 xlsx。
    :returns: 写入的路径。
    """
    s = data["summary"]
    summary = kv_rows([
        ("总造价口径", s.get("cost_basis_label")), ("总造价/明细合计(元)", s.get("total_amount")),
        ("清单明细合计(元)", s.get("parsed_total")), ("总建筑面积(㎡)", s.get("gross_area")),
        ("单方(元/㎡)", s.get("unit_cost")), ("单方说明", s.get("unit_cost_reason")),
        ("口径说明", s.get("cost_basis_notes")), ("未算进的部分", s.get("cost_basis_missing")),
        ("计入文件", data.get("files_used")),
        ("说明", "金额由脚本按表格取数计算，需人工复核"),
    ])
    failed = [{"k": f.get("file"), "v": f.get("reason")} for f in data.get("files_failed") or []]
    return write_workbook(path, [
        Sheet("汇总", KV_COLUMNS, summary),
        Sheet("指标", _INDICATOR_COLUMNS, data["indicators"]),
        Sheet("按章", _CHAPTER_COLUMNS, data["chapters"]),
        Sheet("造价驱动项", _TOP_COLUMNS, data["top_items"]),
        Sheet("未计入文件", [Column("文件", "k"), Column("原因", "v")], failed),
    ])
