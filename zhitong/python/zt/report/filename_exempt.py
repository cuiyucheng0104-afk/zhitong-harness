# 来源：engine-service/app/engine/guard_filename.py（zhitong-cost-ai@991ff5c，W3 搬入 zt；逐字照搬）
"""数字护栏共用的「文件名里的数字不算数」豁免（实跑整改 WS21-e，总纲 K-R19）。

两份数字护栏各有一条文件名豁免：问答的 `filetree/answer_guard`、报告的 `engine/report_guard`
（WS24-g 接入）。口径不一样时，同一句「合同价 1200 元」在一边回链、在另一边被放过。统一成这一个
纯函数，规则取严的一边（铁律 3：逐字相等，不做模糊匹配）：

① 片段与某个文件的**全名**（含扩展名）逐字相等 → 豁免；
② 与去扩展名的**主名**逐字相等，且主名含至少一个汉字或字母、不少于 4 个字符 → 豁免；
③ 其余不豁免。《…》本身不是豁免理由：「《合同价1022万元的说明》」不是任何一份资料的名字。

为什么 ② 要「含汉字或字母」：清单里有 `1200.xlsx` 时，主名 `1200` 会让「合同价 1200 元」整个逃过
回链。纯数字主名只在带着扩展名（①）时才算文件名。
"""
from __future__ import annotations

from typing import Iterable

STEM_MIN_CHARS = 4


def has_word_char(s: str) -> bool:
    """含至少一个汉字或字母（数字、标点、空白都不算）。"""
    return any(ch.isalpha() for ch in s)


def stem_of(name: str) -> str:
    """去掉最后一段扩展名的主名；没有扩展名（或以点开头的隐藏名）时返回空串——那种名字只走 ①。"""
    head, dot, _ext = name.rpartition(".")
    return head if dot and head else ""


def _glued(text: str, i: int, j: int, form: str) -> bool:
    """写法以数字开头 / 结尾、而正文里紧挨着的还是数字或小数点 → 那是一个更长的数，不是这个名字
    （文件 `12.xlsx` 的全名不该吃掉「3412.xlsx」里的后半截；PR #787 第三轮评审的同一条边界）。"""
    def edge(ch: str) -> bool:
        return ch.isdigit() or ch == "."
    return ((form[0].isdigit() and i > 0 and edge(text[i - 1]))
            or (form[-1].isdigit() and j < len(text) and edge(text[j])))


def exempt_forms(file_names: Iterable[str]) -> set[str]:
    """文件名清单 → 可豁免的写法集合（全名 + 合格的主名）。传进来的应是文件名，不是路径。"""
    forms: set[str] = set()
    for raw in file_names:
        name = (raw or "").strip()
        if not name:
            continue
        forms.add(name)
        stem = stem_of(name)
        if len(stem) >= STEM_MIN_CHARS and has_word_char(stem):
            forms.add(stem)
    return forms


def exempt_spans(text: str, file_names: Iterable[str]) -> list[tuple[int, int]]:
    """正文里「属于某个资料文件名」的字符区间 [(start, end)]，按位置排序、不合并。

    位置以传入的 text 为准：调用方在哪一份文本上找数字，就把哪一份传进来（本函数不做规整）。
    file_names 传文件名（basename）；要同时认「去掉存储编号的显示名」时由调用方把两种名字都放进来。
    """
    if not text:
        return []
    out: list[tuple[int, int]] = []
    for form in exempt_forms(file_names):
        i = text.find(form)
        while i != -1:
            j = i + len(form)
            if not _glued(text, i, j, form):
                out.append((i, j))
            i = text.find(form, i + 1)
    return sorted(out)
