# 来源：engine-service/app/engine/amounts.py（zhitong-cost-ai@991ff5cd，W2 搬入 zt；改动见本文件内「zt 改动」注释）
"""金额 / 费率 / 工期的保数值解析与同值判定（整改 spec WS07 K3）。

总纲冲突裁决 K26：金额归一化与数字回链**全仓只此一份**（本模块 + evidence_check），
WS05 / WS10 / WS12 只写各自的领域策略，不再各写一份解析器。

为什么另起一个模块、不复用 field_extract._norm：`_norm` 为了文本分组把 `. - ( )` 一并删掉，
'3.3' 与 '330'、'10613893.46' 与 '1061389.346' 归一化后相等 —— 对金额是灾难。
这里的一切判定都在 Decimal 上做，不碰浮点。
"""
from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable, Optional, Union

# 数字内部的千分位：只删「逗号后恰好 3 位数字」的那种，'1,2,3' 这类列举不动
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")

_UNIT_SCALE = {
    "": Decimal(1), "元": Decimal(1), "圆": Decimal(1),
    "万": Decimal(10_000), "万元": Decimal(10_000),
    "亿": Decimal(100_000_000), "亿元": Decimal(100_000_000),
}

# 阿拉伯数字金额：可选负号 / 币种前缀 / 单位 / 「整」。刻意整串全匹配 ——
# value 里夹着别的字（「约」「含税」「送审金额」、两个数）一律不认，交给核验剔除，
# 而不是猜一个数出来（铁律 3）。
_AMOUNT_RE = re.compile(
    r"(?P<neg>[-−])?(?:¥|RMB|人民币)?(?P<neg2>[-−])?"
    r"(?P<num>\d+(?:\.\d+)?)"
    r"(?P<unit>亿元|万元|元|圆|亿|万)?(?:整|正)?"
)

_CN_DIGIT = {
    "零": 0, "〇": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9,
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_SMALL = {"拾": 10, "十": 10, "佰": 100, "百": 100, "仟": 1000, "千": 1000}
_CN_NUM_CHARS = "".join(_CN_DIGIT) + "".join(_CN_SMALL) + "万亿"
_CN_AMOUNT_RE = re.compile(
    rf"(?P<neg>负)?(?P<int>[{_CN_NUM_CHARS}]+)(?:元|圆)?"
    rf"(?:(?P<jiao>[{''.join(_CN_DIGIT)}])角)?(?:(?P<fen>[{''.join(_CN_DIGIT)}])分)?(?:整|正)?"
)

_RATE_RE = re.compile(r"(?P<neg>[-−])?(?P<num>\d+(?:\.\d+)?)%")
_DAYS_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)(?P<unit>日历天|天|日|个月|月)")


@dataclass(frozen=True)
class Amount:
    value: Decimal            # 单位：元（万元 / 亿元已换算）
    raw: str
    unit: str                 # 原文单位：元 / 万元 / 亿元 / 万 / 亿；没写单位为 ""
    precision_yuan: Decimal   # 原文最末一位有效数字代表多少元：'1189.43万元' → 100
    negative: bool


@dataclass(frozen=True)
class Rate:
    value: Decimal            # 百分点：'10.77%' → 10.77
    raw: str
    precision: Decimal


@dataclass(frozen=True)
class Days:
    value: Decimal
    raw: str
    unit: str                 # 天（日历天/天/日） / 月（个月/月）；月不折算成天，口径不同


def _prep(raw: object) -> str:
    s = unicodedata.normalize("NFKC", str(raw))
    s = _THOUSANDS.sub("", s)
    return re.sub(r"\s+", "", s)


def _decimals_precision(num: str) -> Decimal:
    frac = num.split(".", 1)[1] if "." in num else ""
    return Decimal(1).scaleb(-len(frac))


def _cn_int(s: str) -> Optional[int]:
    total = section = number = 0
    for ch in s:
        if ch in _CN_DIGIT:
            number = _CN_DIGIT[ch]
        elif ch in _CN_SMALL:
            section += (number or 1) * _CN_SMALL[ch]
            number = 0
        elif ch == "万":
            total += (section + number) * 10_000
            section = number = 0
        elif ch == "亿":
            total = (total + section + number) * 100_000_000
            section = number = 0
        else:  # pragma: no cover —— 正则已限定字符集
            return None
    return total + section + number


def parse_amount(raw: object) -> Optional[Amount]:
    """金额串 → Amount（单位元）。支持千分位（, 与 ，）、前导负号、会计括号、万元/亿元、
    中文大写（壹…玖、拾佰仟万亿、元角分整）。不含数字、或整串不是一个金额 → None。"""
    if raw is None or isinstance(raw, bool):
        return None
    s = _prep(raw)
    if not s:
        return None
    neg = False
    m = re.fullmatch(r"\((.+)\)", s)  # 会计式负数：(1,234.00) / （1,234.00）（NFKC 后同形）
    if m:
        neg, s = True, m.group(1)
    m = _AMOUNT_RE.fullmatch(s)
    if m:
        neg = neg or bool(m.group("neg") or m.group("neg2"))
        unit = m.group("unit") or ""
        try:
            base = Decimal(m.group("num"))
        except InvalidOperation:  # pragma: no cover —— 正则保证是合法十进制
            return None
        scale = _UNIT_SCALE[unit]
        value = base * scale
        return Amount(-value if neg else value, str(raw), unit,
                      _decimals_precision(m.group("num")) * scale, neg)
    m = _CN_AMOUNT_RE.fullmatch(s)
    if m and any(ch in _CN_DIGIT or ch in _CN_SMALL for ch in m.group("int")):
        whole = _cn_int(m.group("int"))
        if whole is None:  # pragma: no cover
            return None
        value = Decimal(whole)
        precision = Decimal(1)
        if m.group("jiao"):
            value += Decimal(_CN_DIGIT[m.group("jiao")]) / 10
            precision = Decimal("0.1")
        if m.group("fen"):
            value += Decimal(_CN_DIGIT[m.group("fen")]) / 100
            precision = Decimal("0.01")
        neg = neg or bool(m.group("neg"))
        return Amount(-value if neg else value, str(raw), "元", precision, neg)
    return None


def _as_amount(x: Union[Amount, str, None]) -> Optional[Amount]:
    return x if isinstance(x, Amount) else parse_amount(x)


def same_amount(a: Union[Amount, str, None], b: Union[Amount, str, None]) -> bool:
    """同一笔钱：|a−b| ≤ max(1 元, 0.5 × 两者中较粗的精度)。

    1418635 ≍ 1418635.49813269；1189.43万元 ≍ 11894328；109405 ≍ 109405.32592；
    1418635 ≠ 1280435。解析不了的一方 → False（不是「相等」，铁律 8）。"""
    x, y = _as_amount(a), _as_amount(b)
    if x is None or y is None:
        return False
    tol = max(Decimal(1), Decimal("0.5") * max(x.precision_yuan, y.precision_yuan))
    return abs(x.value - y.value) <= tol


def parse_rate(raw: object) -> Optional[Rate]:
    """百分数 → Rate（百分点）。'10.77%' / '10.77％' → 10.77；没有 % 的裸数不认。"""
    if raw is None or isinstance(raw, bool):
        return None
    s = _prep(raw)
    m = _RATE_RE.fullmatch(s)
    if not m:
        return None
    v = Decimal(m.group("num"))
    return Rate(-v if m.group("neg") else v, str(raw), _decimals_precision(m.group("num")))


def parse_days(raw: object) -> Optional[Days]:
    """工期 → Days。'180日历天' / '180天' / '180日' → 180 天；'6个月' → 6 月。"""
    if raw is None or isinstance(raw, bool):
        return None
    m = _DAYS_RE.fullmatch(_prep(raw))
    if not m:
        return None
    unit = "月" if m.group("unit") in ("个月", "月") else "天"
    return Days(Decimal(m.group("num")), str(raw), unit)


def format_yuan(value: Decimal) -> str:
    """Decimal（元）→ 保留到分的字符串：Decimal('1418635.498') → '1418635.50'。"""
    return str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# 决策 D36：核减率按**净口径**，WS07 字段抽取 / WS12 报告 / WS08 对账三方共用这一个函数。
NET_REDUCTION_RATE_FORMULA = "(送审金额−审定金额)÷送审金额"


def net_reduction_rate(submitted: Decimal, approved: Decimal) -> Optional[Decimal]:
    """(送审 − 审定) ÷ 送审 × 100，单位百分点，不取整（展示时再按需量化）。送审为 0 → None。

    城中河项目：(11894328 − 10613893) ÷ 11894328 = 10.77%；毛口径「核减 ÷ 送审」是 11.93%，
    不是这里的口径。"""
    s, a = Decimal(submitted), Decimal(approved)
    if s == 0:
        return None
    return (s - a) / s * Decimal(100)


# ---------------------------------------------------------------- 文中数字（数字回链用）

# 文中的一个数：负号只认「前面不是字母数字」的那种（'2020-2021' 不是负数）
_MENTION = re.compile(
    r"(?:(?<![0-9A-Za-z.])(?P<neg>[-−]))?(?<![\d.])(?P<num>\d+(?:\.\d+)?)"
    r"(?:[ \t]*(?P<unit>%|亿元|万元|元|亿|万))?"
)
# 日期、序号、条款引用不是数值：'2024年' '第3章' '12月'
_NON_QUANTITY_AFTER = tuple("年月日号章节条款页")


@dataclass(frozen=True)
class NumberMention:
    raw: str
    start: int                 # 在 NFKC + 去千分位之后的文本里的位置
    end: int
    forms: tuple[tuple[Decimal, Decimal, bool], ...]  # (值, 精度, 是否带元单位)
    kind: str                  # amount（元/万元/亿元） | rate（%） | plain


def find_numbers(text: str, *, include_ordinals: bool = False) -> tuple[str, list[NumberMention]]:
    """抽出文中所有数。返回 (规整后的文本, 数列表)；位置指向规整后的文本。

    每个数给出若干「形」：原样的数（'1189.43'），带万/亿单位时再加换算后的值（11894300）。
    回链时任意一形对上即算有出处 —— 原文写「1189.43万元」、输出写「1189.43」也算逐字出现。
    include_ordinals：紧跟「第」的数也收（默认照旧跳过）。只给来源索引用（NumberIndex），见那里。"""
    t = _THOUSANDS.sub("", unicodedata.normalize("NFKC", text or ""))
    out: list[NumberMention] = []
    for m in _MENTION.finditer(t):
        before = t[:m.start()].rstrip()[-1:]
        after = t[m.end():].lstrip()[:1]
        unit = m.group("unit") or ""
        if (before == "第" and not include_ordinals) or (not unit and after and after in _NON_QUANTITY_AFTER):
            continue
        neg = bool(m.group("neg"))
        base = Decimal(m.group("num"))
        prec = _decimals_precision(m.group("num"))
        raw_form = (-base if neg else base, prec, unit in ("元",))
        forms = [raw_form]
        if unit in _UNIT_SCALE and _UNIT_SCALE[unit] != 1:
            scale = _UNIT_SCALE[unit]
            forms.append(((-base if neg else base) * scale, prec * scale, unit.endswith("元")))
        kind = "rate" if unit == "%" else ("amount" if unit.endswith("元") else "plain")
        out.append(NumberMention(re.sub(r"\s+", "", m.group(0)), m.start(), m.end(),
                                 tuple(forms), kind))
    return t, out


def _forms_match(a: tuple[Decimal, Decimal, bool], b: tuple[Decimal, Decimal, bool]) -> bool:
    va, pa, money_a = a
    vb, pb, money_b = b
    half = Decimal("0.5") * max(pa, pb)
    tol = max(Decimal(1), half) if (money_a or money_b) else half
    return abs(va - vb) <= tol


class NumberIndex:
    """证据里所有数的有序索引：按值二分取候选窗口，再逐个按同值规则判定。

    include_ordinals（R3F-f，R3-008）：来源里「源文件第 1716 行」的 1716 也进索引。答案写「第 1715、1716 行」时
    只有 1715 紧跟「第」被跳过，1716 照常取数，来源这边却因为同一条跳过规则没收它——逐字存在的行号被列成未核实。
    默认 False：report_guard、evidence_check、问答选出处的用法一字不变；只有问答数字回链（answer_guard.
    verify_numbers）打开，而且那边只拿它给不是金额的数作保（铁律 2）。"""

    def __init__(self, texts: Iterable[str], *, include_ordinals: bool = False) -> None:
        forms: list[tuple[Decimal, Decimal, bool]] = []
        for t in texts:
            for mention in find_numbers(t, include_ordinals=include_ordinals)[1]:
                forms.extend(mention.forms)
        forms.sort(key=lambda f: f[0])
        self._forms = forms
        self._values = [f[0] for f in forms]
        self._max_prec = max((f[1] for f in forms), default=Decimal(0))

    def contains(self, form: tuple[Decimal, Decimal, bool]) -> bool:
        v, p, _money = form
        window = max(Decimal(1), Decimal("0.5") * max(p, self._max_prec))
        lo = bisect.bisect_left(self._values, v - window)
        hi = bisect.bisect_right(self._values, v + window)
        return any(_forms_match(form, self._forms[i]) for i in range(lo, hi))
