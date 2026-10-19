"""``案例索引.md``：每个项目一行的表格，桶内唯一的跨项目汇总。

格式：任意前言 + 一张 Markdown 表（表头含「编号」「工程名」），表后可有备注。单元格里的竖线写成反斜杠加竖线。
列固定为 :data:`COLUMNS`；解析时多出的列保留，缺的列按空串。

模板在 ``zhitong/skills/zt-project/templates/案例索引.md``。项目编号的分配在 zt-project 的
``scripts/new_project.py`` 里，本模块只负责读写表格与取当年最大序号。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from zt.common import ZtError
from zt.common.paths import PROJECT_CODE

COLUMNS = ("编号", "工程名", "业态", "规模", "咨询类型", "关键指标", "成果链接", "状态")
_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def split_table_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells = re.split(r"(?<!\\)\|", body)
    return [c.strip().replace("\\|", "|") for c in cells]


def _fmt_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


@dataclass
class Casebook:
    """解析后的案例索引。

    :ivar before: 表前的文字行。
    :ivar header: 表头列名。
    :ivar rows: 数据行，每行 ``{列名: 值}``。
    :ivar after: 表后的文字行。
    """

    before: list[str] = field(default_factory=list)
    header: list[str] = field(default_factory=lambda: list(COLUMNS))
    rows: list[dict[str, str]] = field(default_factory=list)
    after: list[str] = field(default_factory=list)

    def render(self) -> str:
        """渲染回 Markdown。

        :returns: 全文，以单个换行结尾。
        """
        head = "| " + " | ".join(self.header) + " |"
        sep = "|" + "|".join("---" for _ in self.header) + "|"
        body = ["| " + " | ".join(_fmt_cell(r.get(c, "")) for c in self.header) + " |" for r in self.rows]
        parts = [*self.before, head, sep, *body, *self.after]
        return "\n".join(parts).rstrip("\n") + "\n"

    def find(self, code: str) -> Optional[dict[str, str]]:
        """按编号找行。

        :param code: 项目编号。
        :returns: 行；没有则 None。
        """
        return next((r for r in self.rows if r.get("编号", "").strip() == code), None)

    def upsert(self, row: dict[str, str]) -> bool:
        """按编号更新一行，没有则追加；只覆盖 ``row`` 里给出的列。

        :param row: 至少含 ``编号``。
        :returns: True 表示更新了已有行，False 表示追加。
        :raises ZtError: 缺编号或编号格式不对（``invalid_project_code``）。
        """
        code = row.get("编号", "").strip()
        if not PROJECT_CODE.match(code):
            raise ZtError("invalid_project_code", f"项目编号应为 YYYY-NNN：{code!r}")
        for col in row:
            if col not in self.header:
                self.header.append(col)
        existing = self.find(code)
        if existing is not None:
            existing.update(row)
            return True
        self.rows.append({c: "" for c in self.header} | row)
        return False

    def max_seq(self, year: int) -> int:
        """表里某一年的最大流水号；没有该年的行为 0。编号格式不对的行忽略。

        :param year: 年份。
        :returns: 最大 NNN。
        """
        return max_seq_in_codes((r.get("编号", "") for r in self.rows), year)


def max_seq_in_codes(codes, year: int) -> int:
    """从一批编号（或以编号开头的目录名）里取某一年的最大流水号。

    :param codes: 字符串迭代；每项以 ``YYYY-NNN`` 开头才计入（目录名 ``2026-007-某工程`` 也行）。
    :param year: 年份。
    :returns: 最大 NNN；没有为 0。
    """
    best = 0
    for raw in codes:
        m = re.match(r"\s*(\d{4})-(\d{3})(?!\d)", raw or "")
        if m and int(m.group(1)) == year:
            best = max(best, int(m.group(2)))
    return best


def parse_casebook(text: str) -> Casebook:
    """解析案例索引。

    空文本得到空表（列为 :data:`COLUMNS`）。

    :param text: 全文。
    :returns: :class:`Casebook`。
    :raises ZtError: 有内容但找不到表头含「编号」「工程名」的表（``casebook_invalid``）。
    """
    if not text.strip():
        return Casebook()
    lines = text.lstrip("\ufeff").splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.lstrip().startswith("|") and "编号" in ln and "工程名" in ln), None)
    if start is None or start + 1 >= len(lines) or not _SEP_RE.match(lines[start + 1]):
        raise ZtError("casebook_invalid", "案例索引里找不到表头含「编号」「工程名」的表格",
                      hint="按 zt-project/templates/案例索引.md 的格式修复，不要整表重写")
    header = split_table_row(lines[start])
    rows: list[dict[str, str]] = []
    i = start + 2
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        cells = split_table_row(lines[i])
        cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells[: len(header)])))
        i += 1
    return Casebook(before=lines[:start], header=header, rows=rows, after=lines[i:])
