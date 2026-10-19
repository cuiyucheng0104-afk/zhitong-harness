"""所有分区共享的基础件：结果信封、证据定位、错误、JSON 读写、CLI 基类、路径工具。"""
from zt.common.cli import Call, Cli
from zt.common.envelope import (
    Envelope,
    FileCoverage,
    ResultStatus,
    SkippedFile,
    WarningItem,
    WarningLevel,
    empty,
    insufficient,
    manual,
    ok,
    partial,
)
from zt.common.errors import EXIT_ERROR, ZtError
from zt.common.evidence import EvidenceRef
from zt.common.jsonio import dumps, read_json, to_jsonable, write_json

__all__ = [
    "Call",
    "Cli",
    "EXIT_ERROR",
    "Envelope",
    "EvidenceRef",
    "FileCoverage",
    "ResultStatus",
    "SkippedFile",
    "WarningItem",
    "WarningLevel",
    "ZtError",
    "dumps",
    "empty",
    "insufficient",
    "manual",
    "ok",
    "partial",
    "read_json",
    "to_jsonable",
    "write_json",
]
