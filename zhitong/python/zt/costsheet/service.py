# 来源：engine-service/app/api/stubs.py 的 _limits/_check_limits/_status/_coverage（zhitong-cost-ai@991ff5cd）
"""计价表三件套（核对 / 指标 / 投控）共用的接线层：读文件、送检上限、结果信封。

旧仓这一层是 FastAPI 端点（``app/api/stubs.py``）。搬进 zt 后改为：

- 输入文件是本机路径（相对当前目录或绝对路径）。``file_id`` 缺省取调用方写的路径原文，
  ``file_name`` 缺省取文件名；结果里的定位字段（``file`` / ``file_id`` / ``sheet`` / ``row``）沿用旧口径。
- 旧端点的 422（解析不出清单行、口径不存在或有歧义、全部无价）改为 ``status=insufficient``：
  ``status_reason`` 是旧的 ``reason_code``（没有时为 ``parse_failed``），``data.detail`` 是旧的 422 detail 对象，
  并附一条 error 级告警说明原因与下一步。
- 送审文件里有 ``.xls``：本机不做 xls→xlsx 转换，整次 ``status=insufficient``（``xls_unsupported``），
  提示用 Excel/WPS 另存为 xlsx。
- 送检上限（旧 413）与文件不存在改为 :class:`ZtError`（退出码 2）。
- 金额与数量所在对象都带 ``needs_manual: true``（:func:`mark_manual`）。
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zt.common.envelope import Envelope, FileCoverage, ResultStatus, SkippedFile, WarningLevel, insufficient
from zt.common.errors import ZtError
from zt.costsheet.warning_codes import CostsheetWarningItem, warn

# 送检上限（旧 COSTSHEET_MAX_FILES / COSTSHEET_MAX_TOTAL_MB 的默认值）；CLI 可用 --max-files / --max-total-mb 改。
MAX_FILES = 60
MAX_TOTAL_MB = 300.0

BASIS_CHOICES = ("auto", "current", "cumulative", "contract")

_SKIP_REASON = {"unpriced": "清单无单价/金额（疑似招标工程量清单）",
                "non_list": "不是清单表（非国标清单/费用表等）"}


class FileRef(BaseModel):
    """请求里的一份文件：``path`` 必填；``file_id``、``file_name`` 只影响结果里的定位字段。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    file_id: Optional[str] = None
    file_name: Optional[str] = None


FileSpec = Union[str, FileRef]


@dataclass(frozen=True)
class SourceFile:
    """已读入内存的一份计价表。

    :ivar path: 本机路径。
    :ivar file_name: 结果里显示的文件名。
    :ivar file_id: 结果里的文件标识（缺省为调用方写的路径原文）。
    :ivar raw: 文件字节。
    """

    path: Path
    file_name: str
    file_id: str
    raw: bytes

    def as_tuple(self) -> tuple[bytes, str, str]:
        """旧引擎 ``run()`` 的文件三元组 ``(bytes, filename, file_id)``。

        :returns: 三元组。
        """
        return self.raw, self.file_name, self.file_id


def parse_request(model: type[BaseModel], request: Any) -> Any:
    """按请求模型校验 ``--in`` 的 JSON。

    :param model: pydantic 请求模型。
    :param request: 已解析的 JSON。
    :returns: 模型实例。
    :raises ZtError: 字段缺失、多余或类型不对（code ``invalid_request``）。
    """
    try:
        return model.model_validate(request)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(x) for x in first["loc"]) or "<root>"
        raise ZtError("invalid_request", f"请求字段 {loc}：{first['msg']}") from None


def _ref(spec: FileSpec) -> FileRef:
    return FileRef(path=spec) if isinstance(spec, str) else spec


def is_xls(spec: FileSpec) -> bool:
    """文件扩展名是否为旧版 ``.xls``（按显示名与路径判断）。

    :param spec: 文件引用。
    :returns: 是 ``.xls`` 时为 True。
    """
    ref = _ref(spec)
    names = [ref.path] + ([ref.file_name] if ref.file_name else [])
    return any(n.lower().endswith(".xls") for n in names)


def xls_rejection(specs: Iterable[FileSpec]) -> Optional[Envelope]:
    """送检文件里有 ``.xls`` 时返回 ``insufficient`` 信封，否则 None。

    :param specs: 本次送检的全部文件。
    :returns: 信封或 None。
    """
    xls = [_ref(s) for s in specs if is_xls(s)]
    if not xls:
        return None
    names = [r.file_name or Path(r.path).name for r in xls]
    item = CostsheetWarningItem(**warn(
        "xls_unsupported", f"{len(names)} 份旧版 .xls 不能直接解析：" + "、".join(names),
        hint="请用 Excel 或 WPS 打开后「另存为」.xlsx，再用新文件重试"))
    return insufficient("xls_unsupported", warnings=[item], data={"xls_files": [r.path for r in xls]})


def load_files(specs: list[FileSpec], *, max_files: int = MAX_FILES,
               max_total_mb: float = MAX_TOTAL_MB) -> list[SourceFile]:
    """检查送检上限并读入文件（旧 ``_check_limits`` + ``read_file_bytes``）。

    :param specs: 文件引用。
    :param max_files: 份数上限。
    :param max_total_mb: 合计大小上限（MB）。
    :returns: 读入的文件，顺序与 ``specs`` 相同。
    :raises ZtError: 超过上限（``too_many_files`` / ``input_too_large``）或文件不存在（``input_not_found``）。
    """
    refs = [_ref(s) for s in specs]
    if len(refs) > max_files:
        raise ZtError("too_many_files", f"本次送检 {len(refs)} 份文件，超过上限 {max_files} 份",
                      hint="减少所选文件后分批运行")
    paths = [Path(r.path) for r in refs]
    missing = [r.path for r, p in zip(refs, paths) if not p.is_file()]
    if missing:
        raise ZtError("input_not_found", "找不到文件：" + "、".join(missing),
                      hint="确认路径相对于当前目录，或改用绝对路径")
    total = sum(p.stat().st_size for p in paths)
    if total > max_total_mb * 1024 * 1024:
        raise ZtError("input_too_large",
                      f"本次送检文件合计 {total / 1024 / 1024:.1f} MB，超过上限 {max_total_mb:g} MB",
                      hint="分批运行")
    return [SourceFile(path=p, file_name=r.file_name or p.name, file_id=r.file_id or default_file_id(r.path),
                       raw=p.read_bytes())
            for r, p in zip(refs, paths)]


def default_file_id(path: str) -> str:
    """调用方没给 ``file_id`` 时的缺省标识：路径原文，反斜杠统一成 ``/``，相对路径去掉 ``./`` 与 ``..`` 冗余。

    投控的 ``anomaly_id`` 含 ``file_id``；同一份文件在 Windows 与 Linux、``./资料/a.xlsx`` 与 ``资料/a.xlsx``
    之间写法不同不应改变身份。绝对路径与相对路径仍然不等价，调用方要跨轮次稳定就始终用同一种写法（或显式给 ``file_id``）。

    :param path: 调用方写的路径。
    :returns: 规范化后的字符串。
    """
    posix = path.replace("\\", "/")
    if posix.startswith("/") or re.match(r"^[A-Za-z]:/", posix):
        return posix
    return posixpath.normpath(posix)


def status_of(warning_items: list[dict], file_coverage: list[dict]) -> tuple[ResultStatus, Optional[str]]:
    """顶层 status（旧 ``stubs._status``）。

    有计入了的文件覆盖率不足或 error 级告警（有东西没算进去）→ partial，否则 ok。覆盖率只看计入了的文件：
    没计入的文件（读不出 / 非清单 / 无价）由 files_failed / file_unpriced / no_items 这些 error 级告警说明。

    :param warning_items: 引擎告警。
    :param file_coverage: 引擎逐文件覆盖率。
    :returns: ``(status, status_reason)``。
    """
    levels = {c.get("level") for c in file_coverage if c.get("status") == "parsed"}
    if "poor" in levels:
        return ResultStatus.PARTIAL, "coverage_poor"
    if any(w.get("level") == "error" for w in warning_items):
        return ResultStatus.PARTIAL, "items_not_counted"
    if "partial" in levels:
        return ResultStatus.PARTIAL, "coverage_partial"
    return ResultStatus.OK, None


def coverage_of(file_coverage: list[dict], rows_parsed: int) -> dict[str, Any]:
    """逐文件覆盖率 → 信封 ``coverage``（旧 ``stubs._coverage``；``files_used`` = 计入了行的文件数）。

    ``rows_parsed`` 取「有金额的叶子行」数：投控 0 条异常只有在它 >0 时才算合法的「检出 0 条」。

    :param file_coverage: 引擎逐文件覆盖率。
    :param rows_parsed: 有金额的叶子行数。
    :returns: :class:`FileCoverage` 的字典形式；``skipped[].rel_path`` 是该文件的 ``file_id``。
    """
    skipped = []
    for c in file_coverage:
        if c["status"] != "parsed":
            skipped.append(SkippedFile(rel_path=c.get("file_id"), file_name=c.get("file"), stage="parse",
                                       reason=_SKIP_REASON.get(c["status"], "未识别到可计入的清单行")))
        for sh in c.get("skipped_sheets") or []:
            skipped.append(SkippedFile(rel_path=c.get("file_id"), file_name=c.get("file"), sheet=sh,
                                       stage="parse", reason="含清单的表未计入（表头认不出或口径有歧义）"))
    used = sum(1 for c in file_coverage if c["status"] == "parsed")
    return FileCoverage(files_total=len(file_coverage), files_used=used, rows_parsed=rows_parsed,
                        skipped=skipped).model_dump(mode="json")


_COVERAGE_WARN = {
    "coverage_poor": "可识别清单表的金额计入不到一半，结果不可作为结论",
    "coverage_partial": "可识别清单表的金额没有全部计入，见 file_coverage 各文件状态",
}


def build_envelope(data: dict[str, Any], warning_items: list[dict], file_coverage: list[dict],
                   rows_parsed: int) -> Envelope:
    """引擎结果 → ok / partial 信封。

    :param data: 业务数据（会被 :func:`mark_manual` 标注）。
    :param warning_items: 引擎告警（``warn()`` 产出的字典）。
    :param file_coverage: 引擎逐文件覆盖率。
    :param rows_parsed: 有金额的叶子行数。
    :returns: 信封。
    """
    status, reason = status_of(warning_items, file_coverage)
    items = [CostsheetWarningItem(**w) for w in warning_items]
    if status is ResultStatus.PARTIAL and not any(w.level in (WarningLevel.WARN, WarningLevel.ERROR) for w in items):
        # 覆盖率降级但引擎没有出对应告警：补一条，满足 partial 的组合约束，也让转述有话可说
        items.append(CostsheetWarningItem(**warn(reason, _COVERAGE_WARN[reason])))
    return Envelope(status=status, status_reason=reason, coverage=coverage_of(file_coverage, rows_parsed),
                    warning_items=items, data=mark_manual(data))


def parse_failed(detail: dict[str, Any]) -> Envelope:
    """旧端点的 422（引擎 ``ParseFailed.detail()``）→ ``insufficient`` 信封。

    :param detail: ``{message, reason_code, hint, basis_requested, basis_available, files}``。
    :returns: 信封；``data.detail`` 原样保留旧 detail。
    """
    reason = detail.get("reason_code") or "parse_failed"
    item = CostsheetWarningItem(code=reason, level=WarningLevel.ERROR, message=detail["message"],
                                hint=detail.get("hint"))
    return insufficient(reason, warnings=[item], data={"detail": detail})


# 金额、数量、单价、比率所在对象的键名特征（mark_manual 据此判断）
_MANUAL_KEY = re.compile(r"amount|qty|price|total|cost|diff|adjust|value|excess|deduct|sum|fee|pct|deviation")


def _numeric(v: Any) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)) or v is None or (
        isinstance(v, str) and re.fullmatch(r"-?[\d,]+(?:\.\d+)?", v) is not None)


def mark_manual(obj: Any) -> Any:
    """递归给含金额、数量、单价或比率字段的对象加 ``needs_manual: true``（原地修改并返回）。

    判据：对象里至少有一个键名命中金额/数量特征、且值是数字、数字串或 null。

    :param obj: 任意 JSON 兼容结构。
    :returns: 同一个对象。
    """
    if isinstance(obj, dict):
        for v in obj.values():
            mark_manual(v)
        if any(isinstance(k, str) and _MANUAL_KEY.search(k) and _numeric(v) for k, v in obj.items()):
            obj["needs_manual"] = True
    elif isinstance(obj, list):
        for v in obj:
            mark_manual(v)
    return obj
