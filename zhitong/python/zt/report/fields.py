# 来源：engine-service/app/engine/consulting_fields.py（FieldDef、FIELD_DEFS、field_def、AMOUNT_COLUMN_RULES、
# NET_REDUCTION、AUDIT_TOTAL_SUBTITLE、amount_column_semantic）与 engine-service/app/engine/evidence_check.py
# （norm_text、quote_in_source、verify_candidate 及其辅助函数）（zhitong-cost-ai@991ff5c，W3 搬入 zt）。
# zt 改动：
# - 只搬审定单网格读取（zt.report.approval_grid）与审核报告章节读取（zt.report.sections）用到的部分；
#   文档角色、来源优先级、字段抽取提示词版本属于已废弃的字段抽取能力（spec §2 决策 8），不搬。
# - field_def 不再回落到概要字段目录（summary_fields.yaml 没有迁入）：不在 14 个老字段里的名字按纯文本核验。
# - verify_candidate 去掉 date / measure 两类（只有概要字段目录用到，这里走不到）。
"""审定单与审核报告读数用到的字段口径与摘录核验。

两件事：

1. 字段口径 :data:`FIELD_DEFS`（14 个咨询字段）与审定单金额列语义 :func:`amount_column_semantic`；
2. 保数值的归一化 :func:`norm_text` 与按字段类型核验一条候选 :func:`verify_candidate`。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from zt.amounts.amounts import parse_amount, parse_days, parse_rate

# ================================================================ 字段口径（consulting_fields）


@dataclass(frozen=True)
class FieldDef:
    """一个字段的口径。

    :ivar kind: amount | rate | duration | org | text | narrative。
    :ivar labels: 字段名 + 同义词 / 列名。数值类 quote 里不含任何一个 → 弱核验。
    :ivar definition: 口径说明。
    :ivar excludes: 容易混淆、必须排除的东西。
    :ivar value_rule: value 的书写规则。
    :ivar deny_labels: 引文里出现其一、又没有任何 labels → 剔除（excluded_label）。
    :ivar needs_number: 取值必须含阿拉伯数字（value_without_number）。
    :ivar undecided_suffixes: 取值以其一结尾 → 只作候选（合并用，这里只保存）。
    """

    kind: str
    labels: tuple[str, ...]
    definition: str = ""
    excludes: tuple[str, ...] = ()
    value_rule: str = ""
    deny_labels: tuple[str, ...] = ()
    needs_number: bool = False
    undecided_suffixes: tuple[str, ...] = ()


FIELD_DEFS: dict[str, FieldDef] = {
    "工程名称": FieldDef(
        "text", ("工程名称", "项目名称"),
        "本项目的工程名称全称（审定单 / 审核报告封面上写的那一个）",
        ("单位工程或分部分项的名称（如「土建工程」「安装工程」）", "文件标题、合同名称"),
        "照抄原文全称，不缩写",
        undecided_suffixes=("勘察服务", "设计服务", "监理服务", "咨询服务"),
    ),
    "建设单位": FieldDef(
        "org", ("建设单位", "发包人", "发包单位", "业主单位", "业主"),
        "发包人或业主单位的机构全称",
        ("代建单位、监理单位、跟审单位", "「建设单位代表 / 经办人：某某」里的人名"),
        "机构全称，以公司 / 局 / 中心 / 委员会等机构后缀结尾",
    ),
    "施工单位": FieldDef(
        "org", ("施工单位", "承包人", "承包单位", "施工总承包单位"),
        "承包人或施工总承包单位",
        ("勘察、设计、监理、招标代理、造价咨询单位", "人名（项目经理、负责人、联系人）", "分包单位"),
        "机构全称，以公司 / 局 / 中心等机构后缀结尾",
    ),
    "建筑规模": FieldDef(
        "text", ("建筑规模", "建筑面积", "规模"),
        "工程的建筑面积或建设规模（数值带单位）",
        ("用地面积、占地面积",),
        "照抄原文，数值与单位一起写",
        deny_labels=("用地面积", "占地面积"),
        needs_number=True,
    ),
    "送审金额": FieldDef(
        "amount", ("送审金额", "送审造价", "送审价", "送审总价", "报审金额"),
        "施工单位报送审核的工程造价合计（送审价）",
        ("合同价、审定金额", "单个单位工程的送审金额（不是合计）"),
        "只写数字和单位，不换算",
    ),
    "审定金额": FieldDef(
        "amount", ("审定金额", "审定造价", "审定价", "审定总价", "审核定案金额", "审核定案造价"),
        "审核后审定的工程造价合计（审定价 / 审核定案金额）",
        ("送审金额", "「合同内」「合同外」等分项审定金额（不是合计）"),
        "只写数字和单位，不换算",
    ),
    "核减金额": FieldDef(
        "amount", ("核减金额", "核减造价", "核减额", "审减金额"),
        "审核中核减的金额，毛额，不扣除核增",
        ("净核减、净核金额、核增减合计", "分项里的「约 X 万元」"),
        "只写数字和单位，不换算",
    ),
    "核增额": FieldDef(
        "amount", ("核增额", "核增金额", "核增造价"),
        "审核中核增的金额，毛额",
        ("净核增减、核增减合计",),
        "只写数字和单位，不换算",
    ),
    "核减率": FieldDef(
        "rate", ("核减率",),
        "原文明示的核减率百分数（系统另会按口径自行计算，这里只抄原文）",
        ("核增率", "自己计算出来的比例"),
        "写成百分数，如 10.77%",
    ),
    "审核依据": FieldDef(
        "narrative", ("审核依据", "编制依据", "审计依据"),
        "审核报告「审核依据」章节的原文",
        ("国家或地方标准的条文正文", "技术规范里的要求性条款"),
        "只抄原文连续段落，不概括、不改写",
    ),
    "相关事项审核说明": FieldDef(
        "narrative", ("相关事项", "有关事项", "其他说明", "需说明的事项"),
        "审核报告「相关事项说明」章节的原文",
        ("规范条文、设计说明里的技术要求（如外窗通风、节能要求）",),
        "只抄原文连续段落，不概括、不改写",
    ),
    "合同价": FieldDef(
        "amount", ("合同价", "合同金额", "合同总价", "签约合同价"),
        "签约合同价（合同总价）",
        ("合同内 / 合同外分项金额", "暂列金额、暂估价"),
        "只写数字和单位，不换算",
    ),
    "招标控制价": FieldDef(
        "amount", ("招标控制价", "最高投标限价"),
        "招标控制价或最高投标限价，value 必须是数",
        ("投标报价、中标价",),
        "只写数字和单位；原文只有「招标控制价」字样而没有数时填 null",
    ),
    "工期": FieldDef(
        "duration", ("工期", "合同工期"),
        "合同工期（日历天）",
        ("实际工期", "延期天数"),
        "只写「N日历天」或「N天」，不写整句",
    ),
}


def field_def(name: str) -> FieldDef:
    """字段口径：14 个咨询字段之一返回登记的定义，其余按纯文本（标签就是字段名本身）。

    :param name: 字段名。
    :returns: 字段定义。
    """
    hit = FIELD_DEFS.get(name)
    return hit if hit is not None else FieldDef("text", (name,))


# 审定单 / 汇总表的金额列语义。判定前先去空白、全角括号归一。顺序即优先级：「净核减金额」先判净核减，
# 才轮不到核减。「净核减」识别出来是为了不把它当成核减金额（QA:extract-01 的错列）。
NET_REDUCTION = "净核减"
AMOUNT_COLUMN_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    # (语义, 必须含其一, 不许含任何一个)
    (NET_REDUCTION, ("净核", "审减净额"), ()),
    ("核减金额", ("核减",), ("净", "核增减")),
    ("核增额", ("核增",), ("核增减",)),
    ("送审金额", ("送审", "报审"), ()),
    ("审定金额", ("审定", "审核定案"), ()),
    ("合同价", ("合同价", "合同金额"), ("合同内", "合同外")),
)
# 审定金额列属于多列合并组（「审定金额」下面分「合同内 / 合同外 / 合计」）时，只认子标题带这些词的一列
AUDIT_TOTAL_SUBTITLE = ("合计", "小计", "总")


def amount_column_semantic(title: str) -> str | None:
    """列标题（多级表头自上而下用「|」拼接）→ 语义。

    :param title: 列标题。
    :returns: 语义；都不命中为 None。
    """
    t = "".join((title or "").split()).replace("（", "(").replace("）", ")")
    for sem, need, deny in AMOUNT_COLUMN_RULES:
        if any(k in t for k in need) and not any(k in t for k in deny):
            return sem
    return None


# ================================================================ 摘录核验（evidence_check）

_PUNCT = re.compile(r"[\s　，。、；：“”‘’（）()《》〈〉【】\[\]{}—\-·…~,.;:!?'\"]+")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
# 数字 token：负号只认「前面不是字母数字」的那种（'2020-2021' 是两个正数）
_TOKEN = re.compile(r"(?:(?<![0-9A-Za-z.])-)?(?<![\d.])\d+(?:\.\d+)?")
_SEP = "\x1f"

LEVELS = ("none", "weak", "strong")
_RANK = {lv: i for i, lv in enumerate(LEVELS)}

NUMERIC_KINDS = frozenset({"amount", "rate", "duration"})

_ORG_SUFFIXES = (
    "公司", "集团", "局", "院", "所", "中心", "委员会", "政府", "管委会", "指挥部", "办事处",
    "学校", "大学", "医院", "银行", "事务所", "站", "厂", "社", "处", "街道", "镇", "乡", "村",
)
_PERSON_ROLE = r"(?:代表人?|经办人|负责人|联系人|项目经理)"
_HAN_NAME = re.compile(r"[一-鿿]{2,4}")


def norm_text(s: object) -> str:
    """NFKC → 去数字内部千分位 → 数字 token 两侧包 ``\\x1f`` → 其余片段去空白与标点。

    先切 token 再去空白：xlsx 抽出的正文是 ``\\t`` 分隔的单元格，'1418635\\t330' 若先去空白就粘成一个数。

    :param s: 任意值。
    :returns: 归一化文本；None 为空串。
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
    """引文归一后是不是原文（已归一）的子串。

    :param quote: 引文。
    :param source_norm: ``norm_text(原文)``。
    :returns: 是子串且引文非空时为 True。
    """
    q = norm_text(quote)
    return bool(q) and q in source_norm


def _plain(s: object) -> str:
    return _PUNCT.sub("", unicodedata.normalize("NFKC", str(s or "")))


def _tokens(s: str) -> list[str]:
    return _TOKEN.findall(_THOUSANDS.sub("", unicodedata.normalize("NFKC", s)))


def _contained(value: str, quote: str) -> bool:
    nv = norm_text(value)
    return bool(nv) and nv in norm_text(quote)


def _value_numbers_in_quote(value: str, quote: str) -> bool:
    vt = _tokens(value)
    if not vt:  # 中文大写金额没有阿拉伯数字：退回整段包含
        return _contained(value, quote)
    return set(vt) <= set(_tokens(quote))


def number_tokens(s: object) -> list[str]:
    """取值 / 引文里的阿拉伯数字 token（与 :func:`norm_text` 同一个切法）。

    :param s: 任意值。
    :returns: 数字 token 列表。
    """
    return _tokens(str(s or ""))


def _mentions(words: Iterable[str], quote: str) -> bool:
    q = _plain(quote)
    return any(_plain(w) in q for w in words if w)


def _has_label(fd: FieldDef, quote: str) -> bool:
    return _mentions(fd.labels, quote)


def _has_label_beyond_denied(fd: FieldDef, quote: str) -> bool:
    """引文里有字段标签，而且不只是排除词里的那几个字：先把排除词整个抹掉再找标签。"""
    q = _plain(quote)
    for w in sorted(fd.deny_labels, key=len, reverse=True):
        if w:
            q = q.replace(_plain(w), "\x00")
    return any(_plain(w) in q for w in fd.labels if w)


def _looks_like_person(value: str, quote: str) -> bool:
    if not _HAN_NAME.fullmatch(value):
        return False
    pat = _PERSON_ROLE + r"[\s:：、，,（(]*" + re.escape(value)
    return re.search(pat, unicodedata.normalize("NFKC", quote)) is not None


def _is_org_name(value: str) -> bool:
    v = re.sub(r"[\s。.，,；;：:]+$", "", unicodedata.normalize("NFKC", value))
    v = re.sub(r"\([^()]*\)$", "", v)  # 「……有限公司（盖章）」
    return v.endswith(_ORG_SUFFIXES)


def _numeric_ok(kind: str, value: str) -> bool:
    if kind == "amount":
        return parse_amount(value) is not None
    if kind == "rate":
        return parse_rate(value) is not None
    return parse_days(value) is not None


@dataclass
class VerifyResult:
    """一条候选的核验结论。

    :ivar level: strong | weak | none。
    :ivar notes: 降级原因码。
    :ivar reject: 非空 = 这条候选不进结果（原因码）。
    :ivar value_override: 非空 = 结果的 value 改用它（叙述字段只认原文）。
    """

    level: str
    notes: list[str] = field(default_factory=list)
    reject: str | None = None
    value_override: str | None = None

    @property
    def verified(self) -> bool:
        """没有剔除且核验等级为 strong。"""
        return self.reject is None and self.level == "strong"


def verify_candidate(field_def: FieldDef, value: object, quote: object,
                     source_norm: str) -> VerifyResult:
    """一条候选 → 核验结论。

    | 类型 | 条件 | 结果 |
    | 所有 | quote 不在原文 | none，quote_not_in_source |
    | amount/rate/duration | value 解析不成数（含 value 就是标签） | reject value_not_numeric |
    | amount/rate/duration | value 的数字没有原样出现在 quote 里 | none，value_not_in_quote |
    | amount/rate/duration | quote 不含字段标签 | weak，quote_without_label |
    | org | 2~4 个汉字且 quote 里紧挨着前面是「代表/经办人/负责人/联系人/项目经理」 | reject person_name |
    | org | 不以机构后缀结尾 | none，not_org_name |
    | org / text | value 不是 quote 的连续片段 | none，value_not_in_quote |
    | narrative | 一律 value 取 quote 原文 | value_from_quote |
    | needs_number | value 里没有阿拉伯数字 | reject value_without_number |
    | deny_labels | quote 里有排除词、又没有任何 labels | reject excluded_label |

    :param field_def: 字段口径。
    :param value: 取值。
    :param quote: 引文。
    :param source_norm: ``norm_text(整份原文)``。
    :returns: 核验结论。
    """
    kind = field_def.kind
    v = "" if value is None else str(value).strip()
    q = "" if quote is None else str(quote)
    if kind in NUMERIC_KINDS and not _numeric_ok(kind, v):
        return VerifyResult("none", ["value_not_numeric"], reject="value_not_numeric")
    if kind == "org" and _looks_like_person(v, q):
        return VerifyResult("none", ["person_name"], reject="person_name")
    if field_def.needs_number and not number_tokens(v):
        return VerifyResult("none", ["value_without_number"], reject="value_without_number")
    if field_def.deny_labels and _mentions(field_def.deny_labels, q) \
            and not _has_label_beyond_denied(field_def, q):
        return VerifyResult("none", ["excluded_label"], reject="excluded_label")

    res = VerifyResult("strong")

    def down(to: str, note: str) -> None:
        res.notes.append(note)
        if _RANK[to] < _RANK[res.level]:
            res.level = to

    if not quote_in_source(q, source_norm):
        down("none", "quote_not_in_source")
    if kind in NUMERIC_KINDS:
        if not _value_numbers_in_quote(v, q):
            down("none", "value_not_in_quote")
        if not _has_label(field_def, q):
            down("weak", "quote_without_label")
    elif kind == "org":
        if not _is_org_name(v):
            down("none", "not_org_name")
        if not _contained(v, q):
            down("none", "value_not_in_quote")
    elif kind == "narrative":
        if q.strip():
            res.value_override = q.strip()
            if res.value_override != v:
                res.notes.append("value_from_quote")
    elif field_def.needs_number:
        if not _value_numbers_in_quote(v, q):
            down("none", "value_not_in_quote")
        if not _has_label(field_def, q):
            down("weak", "quote_without_label")
    else:
        if not _contained(v, q):
            down("none", "value_not_in_quote")
    return res
