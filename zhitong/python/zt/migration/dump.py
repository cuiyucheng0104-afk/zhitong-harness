"""从 mysqldump（或 Navicat 导出的 .sql）里读指定表的行，不需要连库。

支持的写法：

- ``CREATE TABLE `t` (`` 之后逐行 ``  `col` ...`` 的列定义：给不带列名的 ``INSERT`` 定列序；
- ``INSERT INTO `t` VALUES (...),(...);``（mysqldump 默认的 extended insert，一条语句多行）；
- ``INSERT INTO `t` (`a`,`b`) VALUES (...);``（``--complete-insert``）；
- 一行一条语句（Navicat），或一条语句跨多行；
- ``USE `db`;``：记下每行属于哪个库（``--databases`` 导出多个库时用来区分）。

值：``NULL`` → None；带引号的字符串按 MySQL 转义规则还原（``\\0 \\' \\" \\b \\n \\r \\t \\Z \\\\``，
``''`` → ``'``；``\\%`` 与 ``\\_`` 保留反斜杠）；``_binary '...'``、``_utf8mb4'...'`` 去掉字符集前缀；
数字、``0x..``、``b'..'`` 原样保留为字符串，由调用方按列转换。

纯函数加一个流式读文件的入口，不缓存整份 dump：只有目标表的语句会被拼接与解析。
"""
from __future__ import annotations

import gzip
import io
import re
from pathlib import Path
from typing import Iterable, Iterator, Optional

from zt.common import ZtError

_CREATE_RE = re.compile(r"^CREATE TABLE (?:IF NOT EXISTS )?`(?P<name>[^`]+)`\s*\(")
_COLUMN_RE = re.compile(r"^\s*`(?P<col>[^`]+)`\s")
_INSERT_RE = re.compile(r"^(?:INSERT|REPLACE)(?:\s+IGNORE)?\s+INTO\s+`(?P<name>[^`]+)`\s*")
_USE_RE = re.compile(r"^USE `(?P<db>[^`]+)`;")
_ESCAPES = {"0": "\x00", "'": "'", '"': '"', "b": "\b", "n": "\n", "r": "\r", "t": "\t", "Z": "\x1a",
            "\\": "\\", "%": "\\%", "_": "\\_"}


def open_dump(path: Path) -> Iterator[str]:
    """按行读 dump；``.gz`` 结尾的按 gzip 解压。

    :param path: dump 文件。
    :returns: 逐行文本（UTF-8，保留行尾）。
    :raises ZtError: 文件不存在（``dump_not_found``）。
    """
    if not path.is_file():
        raise ZtError("dump_not_found", f"找不到 dump 文件：{path}")
    raw = gzip.open(path, "rb") if path.name.endswith(".gz") else path.open("rb")
    with raw, io.TextIOWrapper(raw, encoding="utf-8", newline="") as fh:
        yield from fh


class _QuoteState:
    """跨行跟踪是否在字符串字面量里，判断一条语句是否以 ``;`` 结束。"""

    def __init__(self) -> None:
        self.quote: Optional[str] = None
        self.escape = False

    def feed(self, text: str) -> bool:
        """喂一段文本；返回这段文本结束时语句是否已经结束（在引号外遇到 ``;`` 且其后只剩空白）。"""
        ended = False
        for ch in text:
            if self.quote is not None:
                if self.escape:
                    self.escape = False
                elif ch == "\\":
                    self.escape = True
                elif ch == self.quote:
                    self.quote = None
                continue
            if ch in ("'", '"', "`"):
                self.quote = ch
                ended = False
            elif ch == ";":
                ended = True
            elif not ch.isspace():
                ended = False
        return ended and self.quote is None


def parse_values(text: str, pos: int) -> list[list[Optional[str]]]:
    """解析 ``VALUES`` 之后的元组序列，直到语句结束的 ``;``。

    :param text: 整条语句。
    :param pos: ``VALUES`` 关键字之后的下标。
    :returns: 每个元组一个值列表。
    :raises ZtError: 语法不认识（``dump_parse_error``），带出错位置附近的原文。
    """
    rows: list[list[Optional[str]]] = []
    n = len(text)

    def fail(at: int, why: str) -> ZtError:
        return ZtError("dump_parse_error", f"dump 语句解析失败（{why}）：…{text[max(0, at - 40):at + 40]!r}…")

    def skip_ws(i: int) -> int:
        while i < n and text[i].isspace():
            i += 1
        return i

    i = skip_ws(pos)
    while True:
        if i >= n or text[i] != "(":
            raise fail(i, "缺少 (")
        i += 1
        row: list[Optional[str]] = []
        while True:
            i = skip_ws(i)
            value, i = _parse_value(text, i, fail)
            row.append(value)
            i = skip_ws(i)
            if i < n and text[i] == ",":
                i += 1
                continue
            if i < n and text[i] == ")":
                i += 1
                break
            raise fail(i, "元组里缺少 , 或 )")
        rows.append(row)
        i = skip_ws(i)
        if i < n and text[i] == ",":
            i = skip_ws(i + 1)
            continue
        if i < n and text[i] == ";":
            return rows
        if i >= n:
            return rows
        raise fail(i, "元组之后缺少 , 或 ;")


def _parse_value(text: str, i: int, fail) -> tuple[Optional[str], int]:
    n = len(text)
    m = re.match(r"_[A-Za-z0-9]+\s*(?=')", text[i:i + 24])
    if m:
        i += m.end()
    if i < n and text[i] == "'":
        out: list[str] = []
        i += 1
        while i < n:
            ch = text[i]
            if ch == "\\" and i + 1 < n:
                nxt = text[i + 1]
                out.append(_ESCAPES.get(nxt, nxt))
                i += 2
                continue
            if ch == "'":
                if i + 1 < n and text[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                return "".join(out), i + 1
            out.append(ch)
            i += 1
        raise fail(i, "字符串没有结束引号")
    m = re.match(r"NULL\b|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?|0x[0-9A-Fa-f]*|b'[01]*'", text[i:i + 4096])
    if not m:
        raise fail(i, "不认识的值")
    token = m.group(0)
    return (None if token == "NULL" else token), i + m.end()


def iter_dump_rows(lines: Iterable[str], tables: set[str]) -> Iterator[tuple[Optional[str], str, dict[str, Optional[str]]]]:
    """从 dump 行流里取指定表的行。

    :param lines: dump 的逐行文本。
    :param tables: 要读的表名。
    :returns: ``(库名或 None, 表名, {列名: 值})`` 迭代器。
    :raises ZtError: 不带列名的 INSERT 之前没见过该表的 CREATE TABLE（``dump_columns_unknown``）、列数对不上
        （``dump_column_mismatch``）或语法错误（``dump_parse_error``）。
    """
    columns: dict[str, list[str]] = {}
    db: Optional[str] = None
    collecting: Optional[str] = None
    stmt: list[str] = []
    state: Optional[_QuoteState] = None
    stmt_table = ""
    for line in lines:
        if state is not None:
            stmt.append(line)
            if state.feed(line):
                yield from _emit(db, stmt_table, "".join(stmt), columns)
                state, stmt = None, []
            continue
        if collecting is not None:
            if line.lstrip().startswith(")"):
                collecting = None
                continue
            m = _COLUMN_RE.match(line)
            if m:
                columns[collecting].append(m.group("col"))
            continue
        m = _USE_RE.match(line)
        if m:
            db = m.group("db")
            continue
        m = _CREATE_RE.match(line)
        if m:
            if m.group("name") in tables:
                collecting = m.group("name")
                columns[collecting] = []
            continue
        m = _INSERT_RE.match(line)
        if m and m.group("name") in tables:
            stmt_table = m.group("name")
            state = _QuoteState()
            stmt = [line]
            if state.feed(line[m.end():]):
                yield from _emit(db, stmt_table, line, columns)
                state, stmt = None, []
    if state is not None:
        raise ZtError("dump_parse_error", f"dump 在表 {stmt_table} 的 INSERT 语句中途结束（文件被截断？）")


def _emit(db: Optional[str], table: str, stmt: str, columns: dict[str, list[str]]
          ) -> Iterator[tuple[Optional[str], str, dict[str, Optional[str]]]]:
    m = _INSERT_RE.match(stmt)
    assert m is not None
    i = m.end()
    cols: Optional[list[str]] = None
    if stmt[i:i + 1] == "(":
        end = stmt.index(")", i)
        cols = [c.strip().strip("`") for c in stmt[i + 1:end].split(",")]
        i = end + 1
    vm = re.compile(r"\s*VALUES\s*", re.I).match(stmt, i)
    if vm is None:
        raise ZtError("dump_parse_error", f"表 {table} 的 INSERT 语句缺少 VALUES")
    if cols is None:
        cols = columns.get(table)
        if not cols:
            raise ZtError("dump_columns_unknown", f"表 {table} 的 INSERT 之前没有 CREATE TABLE，无法确定列序",
                          hint="用带表结构的完整 dump，或用 mysqldump --complete-insert")
    for values in parse_values(stmt, vm.end()):
        if len(values) != len(cols):
            raise ZtError("dump_column_mismatch",
                          f"表 {table} 的一行有 {len(values)} 个值，表结构有 {len(cols)} 列")
        yield db, table, dict(zip(cols, values))
