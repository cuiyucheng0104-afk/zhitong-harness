# 来源：engine-service/app/engine/evidence_check.py 的 norm_text / quote_in_source（zhitong-cost-ai@991ff5cd，W4 搬入 zt）
"""引文回原文的保数值归一化（总纲 K26）。

概算抽取只用这两件：:func:`norm_text` 把原文与引文规整成可比较的形式，:func:`quote_in_source` 判引文是否是
原文的连续片段。旧模块里字段抽取的证据定级（依赖 consulting_fields / value_kinds）不搬。
"""
from __future__ import annotations

import re
import unicodedata

_PUNCT = re.compile(r"[\s　，。、；：“”‘’（）()《》〈〉【】\[\]{}—\-·…~,.;:!?'\"]+")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
# 数字 token：负号只认「前面不是字母数字」的那种（'2020-2021' 是两个正数）
_TOKEN = re.compile(r"(?:(?<![0-9A-Za-z.])-)?(?<![\d.])\d+(?:\.\d+)?")
_SEP = "\x1f"


def norm_text(s: object) -> str:
    """NFKC → 去数字内部千分位 → 数字 token 两侧包 ``\\x1f`` → 其余片段去空白与标点。

    先切 token 再去空白：xlsx 抽出的正文是 ``\\t`` 分隔的单元格，'1418635\\t330' 若先去空白
    就粘成一个数 '1418635330'，单元格 '330' 再也命中不了。

    :param s: 任意文本。
    :returns: 规整后的文本。
    """
    if s is None:
        return ""
    t = _THOUSANDS.sub("", unicodedata.normalize("NFKC", str(s)))
    out: list[str] = []
    pos = 0
    for m in _TOKEN.finditer(t):
        out.append(_PUNCT.sub("", t[pos:m.start()]))
        out.append(f"{_SEP}{m.group(0)}{_SEP}")
        pos = m.end()
    out.append(_PUNCT.sub("", t[pos:]))
    return "".join(out)


def quote_in_source(quote: object, source_norm: str) -> bool:
    """引文规整后是否是规整后原文的连续片段。

    :param quote: 引文。
    :param source_norm: :func:`norm_text` 处理过的原文。
    :returns: 是连续片段时为 True；空引文为 False。
    """
    q = norm_text(quote)
    return bool(q) and q in source_norm
