# 来源：engine-service/app/api/costsheet_probe.py（zhitong-cost-ai@991ff5cd）
"""计价表预检的接线层：逐份文件给标签，一份出问题不让整次失败。

无状态、零模型、不返回任何金额（:mod:`zt.costsheet.probe` 的模块注释写了为什么）。
读不到（路径不存在）、读不开、超大、预算用完，都落成这一份的 unknown 并写原因；其余文件照常预检。
超过 60 份整次失败（:class:`ZtError` ``too_many_files``，调用方分批）。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from zt.common.envelope import Envelope, SkippedFile, WarningItem, WarningLevel, empty, ok, partial
from zt.common.errors import ZtError
from zt.costsheet import probe as cp
from zt.costsheet.service import FileRef


class ProbeRequest(BaseModel):
    """预检请求：``files`` 是路径或 ``{path, file_id?, file_name?}``；``deadline_ms`` 超过 8000 按 8000。"""

    model_config = ConfigDict(extra="forbid")

    files: list[Union[str, FileRef]] = Field(default_factory=list)
    deadline_ms: Optional[int] = None


class ProbeFile(BaseModel):
    """一份文件的预检结果。extra=forbid：返回里只许有这几个键 —— 没有任何金额字段（铁律 2；
    tests/costsheet/test_costsheet_probe.py 钉着这张白名单）。"""

    model_config = ConfigDict(extra="forbid")

    file_id: str
    kind: Literal["costsheet", "other", "unknown"]
    # 认出清单表头的表数 / 工作表总数；unknown（没读或没读完）时为 None —— 不拿「不知道」冒充 0
    list_sheets: Optional[int] = None
    sheets_total: Optional[int] = None
    # 清单表头里出现过的期次（plain / contract / current / cumulative …）；unknown 为 None
    basis_available: Optional[list[str]] = None
    reason_code: Optional[str] = None
    reason: Optional[str] = None


def deadline_ms(v: Optional[int]) -> int:
    """本次总预算（毫秒）：缺省或非正数取 8000，超过 8000 按 8000。

    :param v: 请求里的 ``deadline_ms``。
    :returns: 生效的预算。
    """
    if not v or v <= 0:
        return cp.DEFAULT_DEADLINE_MS
    return min(int(v), cp.DEFAULT_DEADLINE_MS)


def run(request: ProbeRequest) -> Envelope:
    """逐份预检。

    :param request: 已校验的请求。
    :returns: 都预检到了 → ok；预算用完、有文件没轮到 → partial（coverage.skipped 列出是哪几份）；没有文件 → empty。
    :raises ZtError: 超过 60 份（``too_many_files``）。
    """
    if len(request.files) > cp.MAX_FILES:
        raise ZtError("too_many_files", f"本次预检 {len(request.files)} 份文件，超过上限 {cp.MAX_FILES} 份",
                      hint="分批预检")
    t0 = time.monotonic()
    deadline = t0 + deadline_ms(request.deadline_ms) / 1000.0
    out: list[dict] = []
    for spec in request.files:
        ref = FileRef(path=spec) if isinstance(spec, str) else spec
        fid = ref.file_id or ref.path
        name = ref.file_name or Path(ref.path).name
        pre = cp.precheck(fid, name)
        if pre is not None:
            out.append(pre)
            continue
        if time.monotonic() >= deadline:
            out.append(cp.unknown(fid, "timeout"))
            continue
        path = Path(ref.path)
        # 读不到的文件只说「读不到」，不往外给路径
        try:
            if not path.is_file():
                out.append(cp.unknown(fid, "missing"))
                continue
            if path.stat().st_size > cp.MAX_FILE_MB * 1024 * 1024:
                out.append(cp.unknown(fid, "too_large"))
                continue
            raw = path.read_bytes()
        except OSError as exc:  # 权限、被占用：这一份读不了，其余照常
            out.append(cp.unknown(fid, "unreadable", f"文件读不开，未预检：{type(exc).__name__}"))
            continue
        out.append(cp.probe_workbook(raw, fid, name, deadline=deadline))
    files = [ProbeFile(**r).model_dump() for r in out]
    # complete = 每份都试过了：读不到 / 读不开是这份文件的事实，照实标在它身上；只有预算用完才算「没做完」
    late = [r for r in files if r["reason_code"] == "timeout"]
    data = {"files": files, "complete": not late}
    coverage = {"files_total": len(files), "files_used": len(files) - len(late), "rows_parsed": None,
                "unmatched": None,
                "skipped": [SkippedFile(rel_path=r["file_id"], stage="probe", reason=r["reason"] or "").model_dump()
                            for r in late]}
    if not files:
        return empty("no_source_files", data=data)
    if not late:
        return ok(data, coverage=coverage)
    return partial(data, coverage=coverage, reason="probe_budget_exhausted",
                   warnings=[WarningItem(code="probe_budget_exhausted", level=WarningLevel.WARN,
                                         message=f"预检时间用完，{len(late)} 份文件没有预检",
                                         hint="减少文件数后重试")])
