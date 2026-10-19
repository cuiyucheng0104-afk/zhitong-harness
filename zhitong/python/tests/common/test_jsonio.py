"""JSON 读写：UTF-8、中文不转义、Decimal 精确、原子写入。"""
from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from enum import Enum
from pathlib import Path, PureWindowsPath

import pytest

from zt.common import ZtError, dumps, read_json, to_jsonable, write_json


class Color(Enum):
    RED = "red"


@dataclasses.dataclass
class Row:
    code: str
    amount: Decimal


def test_to_jsonable_covers_common_types() -> None:
    value = {
        "row": Row("010101001", Decimal("1234.50")),
        "path": PureWindowsPath("资料\\合同.pdf"),
        "color": Color.RED,
        "tags": {"b", "a"},
        "tuple": (1, 2),
    }
    assert to_jsonable(value) == {
        "row": {"code": "010101001", "amount": "1234.50"},
        "path": "资料/合同.pdf",
        "color": "red",
        "tags": ["a", "b"],
        "tuple": [1, 2],
    }
    with pytest.raises(TypeError):
        to_jsonable(object())


def test_dumps_keeps_chinese() -> None:
    assert dumps({"名称": "土建"}, indent=None) == '{"名称": "土建"}'


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "子目录" / "结果.json"
    write_json(target, {"金额": Decimal("0.10")})
    raw = target.read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert "金额".encode("utf-8") in raw
    assert read_json(target) == {"金额": "0.10"}
    assert [p.name for p in target.parent.iterdir()] == ["结果.json"]


def test_read_json_accepts_bom(tmp_path: Path) -> None:
    target = tmp_path / "bom.json"
    target.write_bytes(b"\xef\xbb\xbf" + json.dumps({"a": 1}).encode())
    assert read_json(target) == {"a": 1}


def test_read_json_errors(tmp_path: Path) -> None:
    with pytest.raises(ZtError) as info:
        read_json(tmp_path / "missing.json")
    assert info.value.code == "input_not_found"
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    with pytest.raises(ZtError) as info:
        read_json(bad)
    assert info.value.code == "invalid_json"
