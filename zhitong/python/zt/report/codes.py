# 来源：engine-service/app/filetree/answer_guard.py 的 ``_CODE``、``CodeCheck``、``_code_sets``、``_PHONE_LABEL``、
# ``verify_codes``、``MAX_LISTED``（zhitong-cost-ai@991ff5c，W3 搬入 zt）。zt 改动：只搬报告护栏用到的清单编码回链，
# 问答专用的其余部分（数字回链、码表核对、公式）不搬；函数体逐字照搬。
"""清单编码回链：正文里的 9 / 12 位清单编码必须能在送入的资料里逐字找到（报告护栏 ``unbacked_code`` 用）。

判据（铁律 3，不做相似度）：

- 按 9 位主码**整码相等**比（含有没有 Z）：Z010901008 与 010901008 是两个编码；
  资料里是 12 位 010502001001、正文写 9 位 010502001 → 主码相等，不标。
- 12 位另比全码：主码在、这 12 位不在 → 顺序码未找到。
- 不以 0 开头的 9 位数（上亿的金额、单号）不是编码，不归这里管。
- 前面紧挨「电话 / 手机 / 传真」等标签的 0 开头长串是电话号码，跳过。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

# 旧仓 answer_guard 的同名常量：回链不上的编码最多列这么多条说明
MAX_LISTED = 10

CODE_RE = re.compile(r"(?<![\dA-Za-z])(?P<code>[Zz]?\d{9})(?P<item>\d{3})?(?!\d)")

# 前面紧挨着这些标签的 0 开头数字串是电话号码，不是清单编码
_PHONE_LABEL = re.compile(r"(?:电话|手机|座机|传真|联系方式|Tel|TEL|tel|Fax|FAX)[ \t]*[:：]?[ \t]*$")


@dataclass
class CodeCheck:
    """编码回链结果。

    :ivar notes: 给人看的说明（最多 :data:`MAX_LISTED` 条）。
    :ivar segments: 回链不上的编码在正文里的位置 ``{"start", "end", "hasBasis", "sourceIndexes"}``。
    :ivar unverified: 回链不上的编码（正文写法，去重）。
    """

    notes: list[str] = field(default_factory=list)
    segments: list[dict] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)


def _code_sets(texts: Iterable[str]) -> tuple[set[str], set[str]]:
    """文本里的清单编码 → (9 位主码集合, 12 位全码集合)。主码带不带 Z 是两个编码，原样记。"""
    mains: set[str] = set()
    fulls: set[str] = set()
    for t in texts:
        for m in CODE_RE.finditer(unicodedata.normalize("NFKC", t or "")):
            main = m.group("code").upper()
            mains.add(main)
            if m.group("item"):
                fulls.add(main + m.group("item"))
    return mains, fulls


def verify_codes(answer: str, evidence_texts: Iterable[str], user_inputs: Iterable[str] = (),
                 prior_texts: Iterable[str] = ()) -> CodeCheck:
    """正文里的清单编码逐个到资料里找。

    :param answer: 正文（调用方已做 NFKC 与去千分位时，位置以它为准）。
    :param evidence_texts: 送入的资料正文。
    :param user_inputs: 用户原句、附件正文（同样算出处）。
    :param prior_texts: 上文对话；只换说明措辞，不算出处。
    :returns: 回链结果。
    """
    mains, fulls = _code_sets([*evidence_texts, *user_inputs])
    prior_mains, _prior_fulls = _code_sets(prior_texts)
    out = CodeCheck()
    noted: set[str] = set()
    for m in CODE_RE.finditer(answer or ""):
        main = unicodedata.normalize("NFKC", m.group("code")).upper()
        if main.lstrip("Z")[:1] != "0":
            continue
        if _PHONE_LABEL.search(unicodedata.normalize("NFKC", (answer or "")[max(0, m.start() - 8):m.start()])):
            continue
        item = m.group("item") or ""
        written = main + item
        if main in mains:
            if not item or written in fulls:
                continue
            note = f"12 位编码 {written} 的顺序码未在检索到的原文中找到（主码 {main} 在原文中），请核对"
        elif main in prior_mains:
            note = f"编码 {written} 来自上文对话，本轮检索到的原文里没有逐字出现，请核对"
        else:
            alt = main[1:] if main.startswith("Z") else "Z" + main
            note = (f"编码 {written} 未能在检索到的原文中逐字找到；原文写法为 {alt}" if alt in mains
                    else f"编码 {written} 未能在检索到的原文中逐字找到，请核对")
        out.segments.append({"start": m.start(), "end": m.end(), "hasBasis": False, "sourceIndexes": []})
        if written not in noted:
            noted.add(written)
            out.unverified.append(written)
            if len(out.notes) < MAX_LISTED:
                out.notes.append(note)
    return out
