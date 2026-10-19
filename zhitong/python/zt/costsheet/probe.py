# 来源：engine-service/app/engine/costsheet_probe.py（zhitong-cost-ai@991ff5cd，W2 搬入 zt；改动见本文件内「zt 改动」注释）
"""计价表预检（WS26-i，spec WS26 §3.9，决策 D-R82）—— 只回答「这份 Excel 是不是计价表」。

选文件对话框把 22 份 Excel 混在一组，唯一的计价表排在最后（缺陷 03-003，RF-26 / TK-B01）。预检给每份文件
打一个标签，让人一眼认出哪份是计价表；它**不解析清单行、不读金额、不调模型**：

  - 只读 xlsx / xlsm。先按正式解析的同一份表名词表（costsheet._SHEET_SKIP）跳过非清单表，其余每张表只读前
    PROBE_ROWS 行，用正式解析的同一套表头识别（_detect_header_block、_looks_listy）判是不是清单表；
  - kind：costsheet（至少 1 张表认出了清单表头）/ other（读完了，一张都没认出）/ unknown（没读，或没读完）；
  - .xls 不转换（转换要起 soffice，几秒一份），直接回 unknown「旧格式，未预检」；
  - 读不开、读不到、预算用完的文件一律 unknown 并写原因。**没读的文件不许说成 other**（铁律 8）：other 的意思是
    「读过了，没有清单表头」，用户会据此不选它；
  - 返回里没有任何金额字段：标签只说「是不是、有几张清单表、表头有哪几种期次」。金额只由正式解析读表得出（铁律 2）。

调用方是 :mod:`zt.costsheet.probe_files`（CLI ``python -m zt.costsheet.cli probe``）；旧仓由 Java 的 CostsheetProbeCache 调用。
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from zt.costsheet.parser import (
    _SHEET_SKIP,
    _TITLE_SKIP_IN_ROWS,
    BASIS_KEYS,
    _basis_available,
    _detect_header_block,
    _eff_side,
    _looks_listy,
    _measure_cols,
    _title_text,
)
from zt.costsheet.xlsx_tolerant import XlsxUnreadable, load_workbook_tolerant

PROBE_ROWS = 40               # 每张表只读前 40 行：表头锚行只在前 30 行里找（costsheet._HEADER_SCAN），再留 10 行给续行与编码
MAX_FILES = 60                # 单次最多 60 份（与 COSTSHEET_MAX_FILES 的默认值同数）
DEFAULT_DEADLINE_MS = 8000    # 一次请求的总预算；到点后剩下的全回 unknown
MAX_FILE_MB = 64              # 单份超过这个大小不读：读字节本身打断不了，一份大文件会把整次预算吃光

KIND_COSTSHEET = "costsheet"
KIND_OTHER = "other"
KIND_UNKNOWN = "unknown"

# reason_code → 给人看的原因。unknown 的原因码决定 Java 缓不缓存（timeout / missing 是一时的，不缓存）
REASON_TEXT = {
    # zt 改动：本机不转换 .xls，原因里直接给出下一步
    "xls": "旧格式 .xls，未预检；请用 Excel/WPS 另存为 .xlsx",
    "not_excel": "不是 xlsx / xlsm，未预检",
    "timeout": "预检时间用完，未预检",
    "too_large": f"文件超过 {MAX_FILE_MB} MB，未预检",
    "missing": "读不到文件，未预检",
    "unreadable": "文件读不开，未预检",
    "no_list_header": "未找到清单表头",
}


def _result(file_id: str, kind: str, *, list_sheets: Optional[int] = None, sheets_total: Optional[int] = None,
            basis_available: Optional[list] = None, reason_code: Optional[str] = None,
            reason: Optional[str] = None) -> dict:
    return {"file_id": file_id, "kind": kind, "list_sheets": list_sheets, "sheets_total": sheets_total,
            "basis_available": basis_available, "reason_code": reason_code,
            "reason": reason if reason is not None else REASON_TEXT.get(reason_code or "")}


def unknown(file_id: str, reason_code: str, reason: Optional[str] = None) -> dict:
    return _result(file_id, KIND_UNKNOWN, reason_code=reason_code, reason=reason)


def _ext(file_name: str) -> str:
    return file_name.rsplit(".", 1)[-1].lower() if "." in (file_name or "") else ""


def precheck(file_id: str, file_name: str) -> Optional[dict]:
    """不用读字节就能下结论的：.xls、非 Excel。其余返回 None（要读）。"""
    ext = _ext(file_name)
    if ext == "xls":
        return unknown(file_id, "xls")
    if ext not in ("xlsx", "xlsm"):
        return unknown(file_id, "not_excel")
    return None


def _list_sheet(title: str, rows: list) -> Optional[list]:
    """这张表认不认得出清单表头。认得出 → 表头里出现过的期次（basis_available，可能为空）；认不出 → None。

    与正式解析（costsheet._parse_sheet）同一套判断，只是不往下读数据行：表头块、表内标题黑名单、
    有工程量/单价/金额列、像清单（表名或 ≥3 个清单编码）；审核汇总版式（≥2 组当事方金额列、没有编码/单位/量/价列，
    _parse_sheet 里的 audit_shape）也算 —— 它是对账审定侧的正当输入，标成「未找到清单表头」会把人指错。"""
    hb = _detect_header_block(rows)
    if hb is None:
        return None
    head_text = _title_text(rows, hb.rows[0])
    if any(k in head_text for k in _TITLE_SKIP_IN_ROWS):
        return None
    cols = hb.cols
    if not _measure_cols(cols):
        return None
    idents = {c.ident for c in cols if c.ident}
    money_parties = {c.party for c in cols if c.measure == "amount" and not c.component and c.party}
    audit_shape = (len(money_parties) >= 2 and "code" not in idents and "unit" not in idents
                   and not any(c.measure in ("qty", "price") for c in cols))
    if not (audit_shape or _looks_listy(title + head_text, rows)):
        return None
    return _basis_available(cols, _eff_side(cols, None))


def probe_workbook(raw: bytes, file_id: str, file_name: str, *, deadline: float,
                   clock: Optional[Callable[[], float]] = None) -> dict:
    """一份 xlsx / xlsm → 预检结果。deadline 是 clock()（默认 time.monotonic）的绝对时刻；
    读到一半到点 → unknown（没读完不下结论，哪怕前面已经认出过清单表）。"""
    clock = clock or time.monotonic
    pre = precheck(file_id, file_name)
    if pre is not None:
        return pre
    if clock() >= deadline:
        return unknown(file_id, "timeout")
    try:
        wb, _notes = load_workbook_tolerant(raw)
    except XlsxUnreadable as e:
        return unknown(file_id, "unreadable", f"文件读不开，未预检：{e.message}")
    list_sheets = 0
    basis: set = set()
    try:
        sheets = wb.worksheets
        for ws in sheets:
            if clock() >= deadline:
                return unknown(file_id, "timeout")
            title = str(ws.title)
            if any(k in title for k in _SHEET_SKIP):
                continue
            rows = [list(r) if r else [] for r in ws.iter_rows(max_row=PROBE_ROWS, values_only=True)]
            got = _list_sheet(title, rows)
            if got is not None:
                list_sheets += 1
                basis.update(got)
        total = len(sheets)
    except Exception as e:  # noqa: BLE001 — 工作表内容坏在哪一张、抛什么异常都有可能；读不完就是没读
        return unknown(file_id, "unreadable", f"文件读不开，未预检：{type(e).__name__}")
    finally:
        wb.close()
    if list_sheets:
        return _result(file_id, KIND_COSTSHEET, list_sheets=list_sheets, sheets_total=total,
                       basis_available=[k for k in BASIS_KEYS if k in basis])
    return _result(file_id, KIND_OTHER, list_sheets=0, sheets_total=total, basis_available=[],
                   reason_code="no_list_header")
