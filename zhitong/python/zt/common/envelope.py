"""结果信封：所有 skill 脚本 stdout 的唯一形态（spec §4.2）。

来源：/home/user/zhitong-cost-ai/engine-service/app/result_contract.py（整改 spec 统一约定 C1/C2/C3）。
改动：去掉 HTTP 状态码映射与 ``error`` 状态（失败改为退出码 2 + 错误 JSON，见 :mod:`zt.common.errors`）；
``coverage`` 改为自由字典（文件类能力可用 :class:`FileCoverage` 生成）；信封顶层带 ``data`` 与
``needs_manual: true``；``status=ok`` 禁止空 ``data``。

组合约束（违约即 ValidationError，宁可在测试里炸，也不输出「看着成功」）：

- ``partial``：必须带非空 ``coverage``，且至少一条 level≥warn 的告警说明缺在哪。
- ``empty`` / ``insufficient``：必须带 ``status_reason``（机器码）。
- ``ok``：``data`` 不得为空。
- ``needs_manual`` 恒为 True（铁律 2）；金额、数量、费率所在对象用 :func:`manual` 标注。
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Annotated, Any, Iterable, Literal, Optional

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SerializeAsAny,
    ValidationInfo,
    model_validator,
)

from zt.common.errors import MACHINE_CODE
from zt.common.evidence import EvidenceRef

log = logging.getLogger("zt.common.envelope")


class ResultStatus(str, Enum):
    """结果状态（C1）。失败不是状态：失败走退出码 2。"""

    OK = "ok"
    PARTIAL = "partial"
    EMPTY = "empty"
    INSUFFICIENT = "insufficient"


class WarningLevel(str, Enum):
    """告警级别（C2）。告警不拦截；要拦截就抛 :class:`zt.common.errors.ZtError`。"""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"


_LEVEL_RANK = {WarningLevel.INFO: 0, WarningLevel.WARN: 1, WarningLevel.ERROR: 2}


class WarningItem(BaseModel):
    """一条结构化告警。领域需要多带键时写子类显式声明，不放开 extra。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=MACHINE_CODE)
    level: WarningLevel
    message: str = Field(min_length=1)
    hint: Optional[str] = None
    evidence: Optional[list[EvidenceRef]] = None


def has_warning_at_least(items: Iterable[WarningItem], level: WarningLevel | str) -> bool:
    """判断告警列表里是否有不低于 ``level`` 的条目。

    :param items: 告警列表。
    :param level: 下限级别。
    :returns: 存在时为 True。
    """
    floor = _LEVEL_RANK[WarningLevel(level)]
    return any(_LEVEL_RANK[w.level] >= floor for w in items)


def _force_needs_manual(value: Any, info: ValidationInfo) -> Literal[True]:
    # 铁律 2：needs_manual 恒 True，无例外分支。强制而不是校验失败；写错的上游靠日志抓。
    if value is True or value is None:
        return True
    log.error("铁律 2：needs_manual=%r 被强制为 True（%s）", value, info.field_name)
    return True


NeedsManual = Annotated[Literal[True], BeforeValidator(_force_needs_manual)]


def manual(obj: dict[str, Any]) -> dict[str, Any]:
    """给带金额、数量或费率的对象打上 ``needs_manual: true``（原地修改并返回）。

    :param obj: 结果中的一个对象。
    :returns: 同一个对象。
    """
    obj["needs_manual"] = True
    return obj


class SkippedFile(BaseModel):
    """未纳入计算的文件及原因。"""

    model_config = ConfigDict(extra="forbid")

    rel_path: Optional[str] = None
    file_name: Optional[str] = None
    sheet: Optional[str] = None
    stage: Optional[str] = None
    reason: str = Field(min_length=1)


class FileCoverage(BaseModel):
    """文件类能力的覆盖度；``model_dump()`` 后放进信封 ``coverage``。"""

    model_config = ConfigDict(extra="forbid")

    files_total: int = Field(ge=0)
    files_used: int = Field(ge=0)
    rows_parsed: Optional[int] = Field(default=None, ge=0)
    unmatched: Optional[int] = Field(default=None, ge=0)
    skipped: list[SkippedFile] = Field(default_factory=list)

    @model_validator(mode="after")
    def _used_within_total(self) -> "FileCoverage":
        if self.files_used > self.files_total:
            raise ValueError(f"files_used={self.files_used} 大于 files_total={self.files_total}")
        return self


class Envelope(BaseModel):
    """脚本成功输出的信封。"""

    model_config = ConfigDict(extra="forbid")

    status: ResultStatus
    status_reason: Optional[str] = Field(default=None, pattern=MACHINE_CODE)
    coverage: dict[str, Any] = Field(default_factory=dict)
    # SerializeAsAny：领域子类多带的键序列化时不被裁回基类。
    warning_items: list[SerializeAsAny[WarningItem]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    needs_manual: NeedsManual = True

    @model_validator(mode="after")
    def _c1_combinations(self) -> "Envelope":
        s = self.status
        if s is ResultStatus.OK and not self.data:
            raise ValueError("status=ok 不允许空 data：没有结果请用 empty 并给 status_reason")
        if s is ResultStatus.PARTIAL:
            if not self.coverage:
                raise ValueError("status=partial 必须带 coverage（缺了哪些、用了多少）")
            if not has_warning_at_least(self.warning_items, WarningLevel.WARN):
                raise ValueError("status=partial 必须至少有一条 level≥warn 的 warning_items，说明缺在哪")
        if s in (ResultStatus.EMPTY, ResultStatus.INSUFFICIENT) and not self.status_reason:
            raise ValueError(f"status={s.value} 必须带 status_reason（机器码，如 no_source_files）")
        return self

    def to_json(self) -> dict[str, Any]:
        """序列化为 JSON 兼容字典（枚举取字符串值）。

        :returns: 可直接 ``json.dumps`` 的字典。
        """
        return self.model_dump(mode="json")


def ok(data: dict[str, Any], *, coverage: Optional[dict[str, Any]] = None,
       warnings: Optional[list[WarningItem]] = None) -> Envelope:
    """构造 ``ok`` 信封。

    :param data: 非空结果数据。
    :param coverage: 覆盖度。
    :param warnings: 告警。
    :returns: 信封。
    """
    return Envelope(status=ResultStatus.OK, data=data, coverage=coverage or {}, warning_items=warnings or [])


def partial(data: dict[str, Any], *, coverage: dict[str, Any], warnings: list[WarningItem],
            reason: Optional[str] = None) -> Envelope:
    """构造 ``partial`` 信封。

    :param data: 已得到的部分结果。
    :param coverage: 非空覆盖度。
    :param warnings: 至少一条 level≥warn 的告警。
    :param reason: 可选机器码。
    :returns: 信封。
    """
    return Envelope(status=ResultStatus.PARTIAL, status_reason=reason, data=data,
                    coverage=coverage, warning_items=warnings)


def empty(reason: str, *, coverage: Optional[dict[str, Any]] = None,
          warnings: Optional[list[WarningItem]] = None, data: Optional[dict[str, Any]] = None) -> Envelope:
    """构造 ``empty`` 信封：输入齐全但没有结果。

    :param reason: 机器码。
    :param coverage: 覆盖度。
    :param warnings: 告警。
    :param data: 可选的辅助数据（例如扫描过的文件列表）。
    :returns: 信封。
    """
    return Envelope(status=ResultStatus.EMPTY, status_reason=reason, coverage=coverage or {},
                    warning_items=warnings or [], data=data or {})


def insufficient(reason: str, *, coverage: Optional[dict[str, Any]] = None,
                 warnings: Optional[list[WarningItem]] = None, data: Optional[dict[str, Any]] = None) -> Envelope:
    """构造 ``insufficient`` 信封：输入不足以给出结果（缺件、缺字段）。

    :param reason: 机器码。
    :param coverage: 覆盖度。
    :param warnings: 告警，建议说明缺什么。
    :param data: 可选的辅助数据。
    :returns: 信封。
    """
    return Envelope(status=ResultStatus.INSUFFICIENT, status_reason=reason, coverage=coverage or {},
                    warning_items=warnings or [], data=data or {})
