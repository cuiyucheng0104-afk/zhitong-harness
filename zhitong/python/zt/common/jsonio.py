"""JSON 读写：显式 UTF-8、保留中文、原子替换写入。

序列化口径（:func:`to_jsonable`）：

- ``Decimal`` 写成字符串，保留精确值；读取方按字段约定转回 ``Decimal``。金额不得经过 float。
- ``Path`` 写成 ``/`` 分隔字符串。
- pydantic 模型按 ``model_dump(mode="json")``；dataclass 按字段展开；枚举取值。
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path, PurePath
from typing import IO, Any

from pydantic import BaseModel

from zt.common.errors import ZtError


def to_jsonable(value: Any) -> Any:
    """把常见 Python 值转换为 JSON 兼容结构。

    :param value: 任意值。
    :returns: 只含 dict/list/str/int/float/bool/None 的结构。
    :raises TypeError: 遇到无法表示的类型。
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if isinstance(value, PurePath):
        return value.as_posix()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value
        return [to_jsonable(v) for v in items]
    raise TypeError(f"无法序列化为 JSON：{type(value).__name__}")


def dumps(value: Any, *, indent: int | None = 2) -> str:
    """序列化为 JSON 文本（不转义中文）。

    :param value: 任意可经 :func:`to_jsonable` 转换的值。
    :param indent: 缩进；None 为紧凑输出。
    :returns: JSON 文本。
    """
    return json.dumps(to_jsonable(value), ensure_ascii=False, indent=indent)


def read_json(path: Path | str) -> Any:
    """读取 UTF-8 JSON 文件；``-`` 表示 stdin。

    :param path: 文件路径或 ``-``。
    :returns: 解析结果。
    :raises ZtError: 文件不存在（``input_not_found``）或不是合法 JSON（``invalid_json``）。
    """
    if str(path) == "-":
        return _parse(sys.stdin.read(), "<stdin>")
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ZtError("input_not_found", f"找不到输入文件：{p}") from None
    return _parse(text, str(p))


def _parse(text: str, origin: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ZtError("invalid_json", f"{origin} 不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列 {exc.msg}") from None


def write_json(path: Path | str, value: Any) -> Path:
    """原子写入 UTF-8 JSON：先写同目录临时文件，再替换目标。

    :param path: 目标路径；父目录不存在时创建。
    :param value: 任意可经 :func:`to_jsonable` 转换的值。
    :returns: 写入的路径。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    text = dumps(value) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p


def emit(value: Any, stream: IO[str] | None = None) -> None:
    """向 stdout（或给定流）输出一行紧凑 JSON。

    :param value: 任意可经 :func:`to_jsonable` 转换的值。
    :param stream: 输出流；默认 ``sys.stdout``。
    """
    out = stream if stream is not None else sys.stdout
    out.write(dumps(value, indent=None) + "\n")
    out.flush()
