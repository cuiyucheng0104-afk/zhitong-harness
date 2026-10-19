"""证据定位 EvidenceRef：一条结果出自哪份文件的哪一格、哪一页、哪一段。

来源：/home/user/zhitong-cost-ai/engine-service/app/evidence.py（整改 spec 统一约定 C4）。
改动：``rel_path`` 改为相对项目目录（``项目/<编号>-<工程名>/``），并拒收 Windows 盘符与 UNC 绝对路径；
去掉 ``file_id`` 以外的数据库语义说明。

约束（违约即 ValidationError，不静默修正；唯一例外是 quote 超长）：

- 键集合固定；多一个键就拒收（extra="forbid"）。定位只能由代码回填，模型输出里夹带的
  confidence、自编行号之类不许混进证据。
- ``rel_path`` 必填，相对项目目录，分隔符用 ``/``。
- row / page / paragraph / chunk 从 1 开始；page 与旁车 ``## pN`` 一致。
- quote 不超过 200 字：超长时只截前缀、不加省略号，截后仍是原文片段。
- 只拷贝调用方给的值，不从 quote 推断页码与行号；缺就是 null。
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from zt.common.paths import is_absolute_any

QUOTE_MAX_CHARS = 200


class EvidenceRef(BaseModel):
    """一条证据定位。"""

    model_config = ConfigDict(extra="forbid")

    file_id: Optional[str] = None
    rel_path: str = Field(min_length=1)
    file_name: Optional[str] = None
    sheet: Optional[str] = None
    cell: Optional[str] = None
    row: Optional[int] = Field(default=None, ge=1)
    row_label: Optional[str] = None
    col_label: Optional[str] = None
    page: Optional[int] = Field(default=None, ge=1)
    paragraph: Optional[int] = Field(default=None, ge=1)
    heading: Optional[str] = None
    chunk: Optional[int] = Field(default=None, ge=1)
    quote: Optional[str] = None

    @field_validator("rel_path")
    @classmethod
    def _relative_only(cls, v: str) -> str:
        if is_absolute_any(v):
            raise ValueError("rel_path 必须相对项目目录，不许是绝对路径")
        return v

    @field_validator("quote")
    @classmethod
    def _cap_quote(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > QUOTE_MAX_CHARS:
            return v[:QUOTE_MAX_CHARS]
        return v
