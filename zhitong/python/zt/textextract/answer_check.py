"""问答回答的出处核对：数字回链与引用核对。

来源：旧仓 engine-service/app/filetree/answer_guard.py 的数字回链（``verify_numbers``：答案里的数字必须能在
读过的资料里逐值找到）与「引用只指向读过的位置」纪律；数值解析与同值判定用 :mod:`zt.amounts.amounts`
（全仓只此一份）。

不改写回答，只标出：

- **无出处的数字**：答案里的金额 / 费率 / 其它数，在传入的资料文本里找不到同值（含 ``万元`` ↔ ``元`` 换算）。
  不检查的数：引用括号内、反引号内、15 位以上的 ID、``1.2.3`` 这类三级以上条文号、0 打头的编码段、
  规范编号（``GB 50854-2013``）、文件名；日期与「第 N」序号由 ``find_numbers`` 自己跳过；
- **引用问题**：``〔路径 位置〕`` 形式的引用，路径不在读过的资料里（``citation_not_read``）；位置写成 ``pN`` 或
  ``RN`` 而资料文本里没有对应的 ``[pN]`` / ``[RN]`` 锚点（``citation_locator_missing``）。

资料文本通常是 ``textextract extract --text-out`` 写出的文件。传入的文本里没有的内容，一律视为「没读过」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from zt.amounts.amounts import NumberIndex, find_numbers

CITATION = re.compile(r"〔([^〕\n]{1,200})〕")
_BACKTICK = re.compile(r"`[^`\n]*`")
_EXCLUDE = (
    CITATION,
    _BACKTICK,
    re.compile(r"[^\s，。；、,;：:（）()「」“”《》【】]+\.(?:pdf|docx?|xlsx?|xlsm|txt|md|pptx)\b", re.IGNORECASE),
    re.compile(r"\d+(?:\.\d+){2,}"),
    re.compile(r"\d{15,}"),
    re.compile(r"(?<![\dA-Za-z])[Zz]?\d{9}(?:\d{3})?(?!\d)"),
    re.compile(r"(?<![\d.,])0\d{2,}(?![\d.])"),
    re.compile(r"(?:GB|JGJ|CJJ|JTG|DBJ?\d*|T/[A-Z]{2,})(?:/T)?[ \t]*\d+(?:[-—]\d{4})?", re.IGNORECASE),
)
_CONTEXT_CHARS = 14
_PAGE_LOC = re.compile(r"(?:^|\s)p(\d+)(?:\b|$)")
_ROW_LOC = re.compile(r"(?:^|!|\s)R(\d+)(?:\b|$)")


@dataclass
class Source:
    """一份读过的资料：项目内相对路径 + 文本。"""

    rel_path: str
    text: str


@dataclass
class Unattributed:
    """答案里一个找不到出处的数。"""

    raw: str
    kind: str
    context: str


@dataclass
class CitationIssue:
    """一条有问题的引用。"""

    cite: str
    problem: str  # citation_not_read / citation_locator_missing
    detail: str


@dataclass
class AnswerCheck:
    """核对结果。"""

    numbers_checked: int = 0
    unattributed: list[Unattributed] = field(default_factory=list)
    citations_total: int = 0
    citation_issues: list[CitationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """没有无出处的数、也没有引用问题。"""
        return not self.unattributed and not self.citation_issues


def _masked(answer: str) -> str:
    """把不检查的片段换成等长空格，保持其余数字的位置。"""
    out = answer
    for pat in _EXCLUDE:
        out = pat.sub(lambda m: " " * len(m.group(0)), out)
    return out


def _match_source(path: str, sources: list[Source]) -> Optional[Source]:
    norm = path.strip().replace("\\", "/")
    for s in sources:
        if s.rel_path == norm:
            return s
    by_name = [s for s in sources if s.rel_path.rsplit("/", 1)[-1] == norm.rsplit("/", 1)[-1]]
    return by_name[0] if len(by_name) == 1 else None


def check_answer(answer: str, sources: list[Source]) -> AnswerCheck:
    """核对答案的数字与引用。

    :param answer: 答案全文。
    :param sources: 读过的资料（路径 + 文本）。
    :returns: 核对结果。
    """
    res = AnswerCheck()
    index = NumberIndex([s.text for s in sources], include_ordinals=True)
    norm, mentions = find_numbers(_masked(answer))
    res.numbers_checked = len(mentions)
    for m in mentions:
        if not any(index.contains(form) for form in m.forms):
            lo, hi = max(0, m.start - _CONTEXT_CHARS), min(len(norm), m.end + _CONTEXT_CHARS)
            res.unattributed.append(Unattributed(m.raw, m.kind, " ".join(norm[lo:hi].split())))
    for cm in CITATION.finditer(answer):
        res.citations_total += 1
        body = cm.group(1).strip()
        path, _, loc = body.partition(" ")
        src = _match_source(path, sources)
        if src is None:
            res.citation_issues.append(CitationIssue(cm.group(0), "citation_not_read",
                                                     f"引用的 {path} 不在读过的资料里"))
            continue
        page = _PAGE_LOC.search(loc)
        if page and f"[p{page.group(1)}]" not in src.text and f"## p{page.group(1)}" not in src.text:
            res.citation_issues.append(CitationIssue(cm.group(0), "citation_locator_missing",
                                                     f"{src.rel_path} 的文本里没有第 {page.group(1)} 页"))
            continue
        row = _ROW_LOC.search(loc)
        if row and f"[R{row.group(1)}]" not in src.text:
            res.citation_issues.append(CitationIssue(cm.group(0), "citation_locator_missing",
                                                     f"{src.rel_path} 的文本里没有第 {row.group(1)} 行"))
    return res


def read_source(spec: str) -> Source:
    """解析命令行的 ``--source``：``<项目内相对路径>=<文本文件>``，或只给文本文件（路径取文件名）。

    :param spec: 参数值。
    :returns: 资料。
    :raises FileNotFoundError: 文本文件不存在。
    """
    rel, sep, file = spec.partition("=")
    path = Path(file if sep else rel)
    text = path.read_text(encoding="utf-8")
    return Source(rel.strip().replace("\\", "/") if sep else path.name, text)
