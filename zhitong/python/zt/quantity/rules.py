# 来源：engine-service/app/engine/quantity_rules.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""工程量清单生成的确定性规则（WS11，issue #763）。纯函数、零 LLM。

规则数据在 `data/quantity_rules.yaml`，本模块只负责读它并给出判定：

- 专业范围（QTY-07）：`file_scope` 按领域词计数判文件是否越出房建范围；`heading_scope` 判章节。
- 做法片段词表（QTY-03）：`practice_signal` / `looks_like_practice`。
- 层的角色（QTY-09）：`layer_words` 给出 standalone / aux / base 命中，角色闸在 quantity_list。
- 语义一致性闸（QTY-02，铁律 3，决策 D52）：`check_consistency` 只判「这个码和这段原文说的是不是
  一回事」，**从不改码** —— 违反规则的条目由调用方降为待核，建议栏写规则期望的码表名称。
- 标段 / 范围排除（QTY-11，决策 D54）：`parse_project_lot`、`find_exclusions`、`match_exclusion`。
- 层内标记（WS29-f，D-R110 / D-R111）：`find_inline_marker` —— 做法层正文里的自理、二次装修、
  精装修引用只管这一层；`scan_exclusions` 另外交代「句式命中但对象词不成立」的句子（铁律 8）。
- 规格签名（QTY-09 跨来源去重）：`spec_signature`。
- 告警 code 表（C2）：`WARNING_CODES`，tests/quantity/test_quantity_rules.py 扫源码核对登记。
"""
from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import yaml

RULES_PATH = Path(__file__).resolve().parent / "data" / "quantity_rules.yaml"

BUILDING, MUNICIPAL, INSTALLATION = "building", "municipal", "installation"

# C2：本领域发出的告警 code（code → 中文名）。新增 code 必须先登记，源码扫描测试把关。
WARNING_CODES: dict[str, str] = {
    "quantity_file_skipped_no_text": "文件抽不出正文，已跳过",
    "quantity_duplicate_file": "内容相同的文件只按其中一份生成",
    "quantity_file_out_of_scope": "文件不属于房建专业，已跳过",
    "quantity_section_out_of_scope": "章节不属于房建专业，其下做法未列项",
    "quantity_ocr_source": "正文来自 OCR 识别，请核对原件",
    "quantity_ocr_truncated": "OCR 只识别了部分页",
    "quantity_pages_missing": "部分页未取得正文",
    "quantity_hidden_sheets": "隐藏工作表已跳过",
    "quantity_docx_line_mode": "文档表格结构读取失败，已逐行处理",
    "quantity_xlsx_repaired": "xlsx 样式表损坏，已按容错方式读取",
    # zt 改动：分类由 agent 作答，「模型未完成」即 answers 里缺这个片段
    "quantity_llm_failed": "部分片段没有回答（answers 里缺这些 id）",
    "quantity_llm_unknown_ids": "回答了不存在的片段编号，已丢弃",
    "quantity_answer_duplicate": "同一片段重复作答，只取第一条",
    "quantity_features_unknown_items": "特征摘录里的清单项编码不在本次清单里，已忽略",
    "quantity_llm_unknown_exclusion": "模型引用了不存在的排除句编号，已忽略",
    "quantity_pending_review": "部分条目降为待核（语义不一致 / 角色冲突 / 排除未确认）",
    "quantity_unmatched": "部分片段没有得到码表里的编码",
    "quantity_excluded_scope": "部分做法按原文排除句划出本标段范围",
    "quantity_fitout_provisional": "部分做法层原文注明详精装修设计，已按暂定做法列项",
    "quantity_exclusion_object_too_generic": "有句子读着像范围排除句，但对象只有泛指词，没有据此排除",
    "quantity_block_lines_unrecognized": "做法块里有行没有认成构造层，已列在「说明」页",
    "quantity_lot_unknown": "项目名称里解析不到标段，命中排除句的做法降为待核",
    "quantity_features_skipped": "项目特征还没有摘录，相关槽位写「待补」",
    "quantity_cross_version": "编码与其他版本码表同号异名",
    "quantity_partial": "部分片段未完成分类，结果为部分完成",
    # R4F-d fix15（用户 2026-10-12 决定 4）：没有任何正式项也照常出表，用这一条告警说明清单页为什么是空的
    "quantity_no_formal_items": "没有形成任何正式清单项，清单页为空，明细见「待核与未匹配」页",
}


def warning_label(code: str) -> str:
    return WARNING_CODES[code]


@functools.lru_cache(maxsize=1)
def load_rules() -> dict:
    with RULES_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _norm(text: Optional[str]) -> str:
    return unicodedata.normalize("NFKC", text or "")


# ============================================================ 专业范围（QTY-07）

@dataclass(frozen=True)
class ScopeVerdict:
    counts: dict[str, int]
    building_share: float
    out_of_scope: bool
    domain: Optional[str]          # 越界时占优的非房建领域

    @property
    def foreign_hits(self) -> int:
        return self.counts.get(MUNICIPAL, 0) + self.counts.get(INSTALLATION, 0)


def domain_counts(text: str) -> dict[str, int]:
    t = _norm(text)
    doms = load_rules()["scope_domains"]
    return {d: sum(t.count(_norm(w)) for w in words) for d, words in doms.items()}


def file_scope(text: str) -> ScopeVerdict:
    """building_share < min_building_share 且非房建词命中 ≥ min_foreign_hits → 越界。"""
    cfg = load_rules()["scope"]
    counts = domain_counts(text)
    b = counts.get(BUILDING, 0)
    foreign = counts.get(MUNICIPAL, 0) + counts.get(INSTALLATION, 0)
    total = b + foreign
    share = (b / total) if total else 1.0
    out = share < float(cfg["min_building_share"]) and foreign >= int(cfg["min_foreign_hits"])
    dom = None
    if out:
        dom = MUNICIPAL if counts.get(MUNICIPAL, 0) >= counts.get(INSTALLATION, 0) else INSTALLATION
    return ScopeVerdict(counts, round(share, 4), out, dom)


def heading_scope(heading: str) -> Optional[str]:
    """标题只含非房建词（房建词 0 次）→ 返回该领域；否则 None。"""
    c = domain_counts(heading)
    if c.get(BUILDING, 0) > 0:
        return None
    m, i = c.get(MUNICIPAL, 0), c.get(INSTALLATION, 0)
    if m == 0 and i == 0:
        return None
    return MUNICIPAL if m >= i else INSTALLATION


def domain_name(domain: Optional[str]) -> str:
    return (load_rules().get("domain_names") or {}).get(domain or "", domain or "")


# ============================================================ 做法词表（QTY-03）

@functools.lru_cache(maxsize=1)
def _lexicon() -> tuple[list[re.Pattern], list[re.Pattern], list[str]]:
    lex = load_rules()["practice_lexicon"]
    return ([re.compile(p) for p in lex["thickness"]],
            [re.compile(p) for p in lex["strength"]],
            [_norm(w) for w in lex["materials"]])


@dataclass(frozen=True)
class PracticeSignal:
    thickness: bool
    strength: bool
    materials: tuple[str, ...]


def practice_signal(text: str) -> PracticeSignal:
    t = _norm(text)
    thick, strength, materials = _lexicon()
    return PracticeSignal(
        thickness=any(p.search(t) for p in thick),
        strength=any(p.search(t) for p in strength),
        materials=tuple(w for w in materials if w in t),
    )


def looks_like_practice(text: str, *, in_block: bool) -> bool:
    """做法块内 / 做法列里：命中材料词或厚度即算；块外散行：须（厚度或强度）且材料词。"""
    s = practice_signal(text)
    if in_block:
        return bool(s.materials) or s.thickness
    return bool(s.materials) and (s.thickness or s.strength)


def thickness_starts(text: str) -> bool:
    return bool(re.match(r"\s*\d+(?:\.\d+)?\s*(?:mm|MM|毫米)?\s*厚", _norm(text)))


# ============================================================ 层的角色（QTY-09）

@dataclass(frozen=True)
class LayerWords:
    standalone: tuple[str, ...]
    aux: tuple[str, ...]
    base: tuple[str, ...]


def layer_words(text: str) -> LayerWords:
    t = _norm(text)
    g = load_rules()["granularity"]
    hit = lambda ws: tuple(w for w in ws if _norm(w) in t)  # noqa: E731
    return LayerWords(hit(g["standalone"]), hit(g["aux"]), hit(g["base"]))


# ============================================================ 语义一致性闸（QTY-02，铁律 3）

@dataclass(frozen=True)
class Violation:
    rule_id: str
    message: str
    expect: tuple[str, ...]
    forbid: tuple[str, ...]
    # 建议栏写哪几个码（yaml 的 suggest）。forbid 型规则没有 expect，建议栏只能靠它写出码表名称（WS29-k2）
    suggest: tuple[str, ...] = ()


def _strip_z(code: str) -> str:
    c = (code or "").strip()
    return c[1:] if c[:1] in ("Z", "z") else c


def _any(words: Iterable[str], hay: str) -> bool:
    return any(_norm(w) in hay for w in words)


# R4F-d fix3，铁律 3：这是当前层证据闸的有限语法，不是中文 NLP 或专业选码器。
# 主语归属和名词组否定分别解析：标点不能丢主语，新谓词不能延长材料否定。
_SUBJECT = r"本层|该层|相邻层|其他层|其它层|另层|上层|下层"
_SCOPE_TOKEN = re.compile(rf"{_SUBJECT}|[()\[\]【】]|[，,。.;；!?！？\n]")
_NEW_LAYER = re.compile(r"\s*\d+(?:\.\d+)?\s*(?:mm|MM|毫米)?\s*厚")
# 逗号只有紧接显式连词时才连接同一宾语组；新谓语/分号仍结束组。
_COORDINATION = r"\s*(?:(?:[，,]\s*)?(?:以及|或者|或|和|及|与|、)\s*)?"
_NEGATION = (
    r"(?:非|不|无|未|没有)\s*(?:(?:属于|具备|具有|承担|要求|存在|采用|使用|设置|含有|含|需要|作为|用作|用于|是|需|须|设|用|做)\s*)?")
_POST_DENIAL = (
    r"\s*(?:均|都|完全)?\s*(?:(?:不|未|没有)\s*(?:属于|具备|具有|承担|要求|存在|采用|使用|设置|含有|含|作为|用作|用于|是|设|用|做)"
    r"|不存在|没有|为零|为非保温)")
_FUNCTION_GROUP = rf"(?:保温|隔热)(?:{_COORDINATION}(?:保温|隔热))*\s*(?:功能|性能)"
_FUNCTION_DENIAL = re.compile(
    rf"(?:{_NEGATION}){_FUNCTION_GROUP}"
    rf"|{_FUNCTION_GROUP}[\s，,:：]*(?:均|都|完全|明确)?\s*(?:不具备|不具有|不承担|不存在|为零|没有|无)"
    rf"(?=$|[\s，,。.;；!?！？\n]|但|且|并|的)")
_AMBIGUOUS_NEGATION = re.compile(r"(?:并非|不是|不能|未必|不)(?:\s*)(?:不|未|无|没有)")


@dataclass(frozen=True)
class _ScopedClause:
    subject: str               # current / foreign / unknown
    text: str                  # 主语限定的谓语/名词投影；不含他层内容
    spans: tuple[tuple[int, int], ...] = ()  # 后置主语规范化文本中的原跨度
    predicates: tuple[str, ...] = ()  # 完整独立插语的有界谓语；消费端分别判定


@functools.lru_cache(maxsize=1)
def _insertion_signal() -> re.Pattern:
    # 铁律 3：插语是否含证据仍由同一规则词表决定，不另造专业材料表。
    words = tuple(_norm(w) for rule in load_rules()["consistency_rules"]
                  for w in rule.get("text_affirmative_none", ()))
    atoms = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True))
    return re.compile(rf"(?:{atoms})|(?:具备|具有|承担|存在|采用|使用|设置|含有|作为|用作|用于|为零)|(?:明确)?(?:没有|未|不|无|非)(?=\s*$)")


_RELATION = re.compile(
    r"(?:属于|具备|具有|承担|要求|存在|采用|使用|设置|含有|作为|用作|用于|需要|没有)")
# 铁律 3：名词组前置限定语是可组合构件序列，不是固定线性模板：指示/数量、
# 已登记形容词（可带「的」、可并列）、「用途的」，顺序自由、可重复。节点、
# 标签、尾部描述共用这些构件；构件不含采用关系，真正的关系词仍结束名词组。
_ADJECTIVE = r"(?:不燃|非承重|憎水|阻燃|防火|耐火|复合)"
_NOUN_MODIFIER = rf"(?:{_ADJECTIVE}\s*)*"
_ADJECTIVE_PHRASE = rf"{_ADJECTIVE}(?:\s*的)?(?:\s*(?:、|以及|和|及|与|或)\s*{_ADJECTIVE}(?:\s*的)?)*"
_ENUM_NUMBER = r"(?:\d+|[一二三四五六七八九十百两]+|多|若干|几)"
_CLASSIFIER = r"(?:种|类|项)"
# 对比限定（另一种/其他）指称别的成员，不与前一名词同指，不能作同位续接。
_CONTRASTIVE = rf"(?:另外?(?:一|{_ENUM_NUMBER})?{_CLASSIFIER}|其[他它余])"
_QUANTIFIER = rf"(?:{_CONTRASTIVE}|(?:(?:某|第|[这那该同各每]){_ENUM_NUMBER}?|{_ENUM_NUMBER}){_CLASSIFIER})"
_ENUM_REFERENCE = r"(?:这些|那些|上述|下列|以下|以上|前述|所列)"
# 不带量词的数量限定同属封闭类（一些/部分/所有），与带量词的数量构件同位。
_BARE_QUANTIFIER = r"(?:一些|某些|部分|若干|所有|全部)"
_DETERMINER = rf"(?:{_ENUM_REFERENCE}|{_QUANTIFIER}|{_BARE_QUANTIFIER})"
_OBJECT_LABEL = r"(?:材料(?:说明)?\s*[:：，,]?\s*)?"
# 铁律 3：前置「用途的」及后置用途注释都属于材料名词组，不另起谓语。
_PURPOSE_DESCRIPTION = rf"(?:用于|用作|作为)\s*(?:保温|隔热)(?:{_COORDINATION}(?:保温|隔热))*\s*(?:功能|性能|材料)?"
_PURPOSE_ATTRIBUTE = rf"{_PURPOSE_DESCRIPTION}\s*的"
_PRE_MODIFIER = rf"(?:(?:{_DETERMINER}|{_ADJECTIVE_PHRASE}|{_PURPOSE_ATTRIBUTE})\s*)*"
_PURPOSE_POSTFIX = rf"(?:\s*{_PURPOSE_DESCRIPTION})*"
_PURPOSE_PREFIX = re.compile(rf"^{_COORDINATION}(?:(?:{_DETERMINER}|{_ADJECTIVE_PHRASE})\s*)*{_PURPOSE_ATTRIBUTE}")
_PARENT_RELATIONS = ("属于", "具备", "具有", "承担", "要求", "存在", "采用", "使用", "设置", "含有", "作为", "用作", "用于", "需要")


def _purpose_modifier(text: str) -> bool:
    return bool(_PURPOSE_PREFIX.match(text.lstrip()))


@functools.lru_cache(maxsize=1)
def _material_object_tail() -> re.Pattern:
    words = {_norm(w) for rule in load_rules()["consistency_rules"]
             for w in rule.get("text_affirmative_none", ())}
    atoms = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?:{atoms})\s*(?:板材|板层|材料|砌块|功能|性能|板|层|砖)?{_PURPOSE_POSTFIX}\s*$")


def _material_term(words: tuple[str, ...]) -> str:
    # 铁律 3：用途归属和否定消费共用同一个名词节点；不能只标记首个注释。
    atom = "(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + ")"
    return (_PRE_MODIFIER + atom
            + r"\s*(?:板材|板层|材料|砌块|功能|性能|板|层|砖)?" + _PURPOSE_POSTFIX)


# 铁律 3：无材料词的描述语（标签/尾部）用同一组前置构件，至少含一个指示/数量。
# 限定语没有采用关系；真正的关系词不能作为未知名词后缀吞掉。
_MATERIAL_CLASS = r"(?:材料|板材|板层)"
_NOMINAL_DESCRIPTOR = (rf"(?:(?:{_ADJECTIVE_PHRASE}|{_PURPOSE_ATTRIBUTE})\s*)*{_DETERMINER}\s*"
                       rf"{_PRE_MODIFIER}{_MATERIAL_CLASS}")
# 标签：逗号引出成员只限列举型（材料说明/指称或数量+类别），其他描述语须用冒号。
_ENUM_COUNT = rf"(?:[这那]?{_ENUM_NUMBER}{_CLASSIFIER})"
_ENUMERATING_LABEL = re.compile(
    rf"\s*(?:材料(?:说明)?|(?:{_ENUM_REFERENCE}(?:{_ENUM_COUNT})?|{_ENUM_COUNT}){_MATERIAL_CLASS})"
    rf"(?P<separator>\s*[:：，,]?\s*)")
_DESCRIPTOR_LABEL = re.compile(rf"\s*{_NOMINAL_DESCRIPTOR}(?P<separator>\s*[:：]?\s*)")
_NOMINAL_TAIL = re.compile(rf"\s*(?:等(?:{_MATERIAL_CLASS})?|{_NOMINAL_DESCRIPTOR})\s*")
# 成员可以是带材料词的节点，也可以是连词后的无材料词描述语（其他用于隔热的材料）。
_MEMBER_DESCRIPTOR = re.compile(rf"\s*{_NOMINAL_DESCRIPTOR}")
# 带材料词的名词也可作标签，用冒号引出同位成员；逗号仍只随显式连词续接。
_APPOSITION = re.compile(r"\s*[:：]\s*")
# 话题：冒号后的评述是否定（无/未采用/均不使用）时，话题名词组在否定范围内。
_COMMENT_DENIAL = re.compile(rf"\s*[:：](?:{_POST_DENIAL}|\s*(?:均|都)?\s*无(?=$|[，,。.;；!?！？\n]))")
_CONTRASTIVE_START = re.compile(rf"\s*{_CONTRASTIVE}")
_CONJUNCTION = re.compile(r"以及|或者|或|和|及|与|、")
_GROUP_CONNECTOR = re.compile(_COORDINATION)


@dataclass(frozen=True)
class _MaterialGroup:
    start: int
    end: int
    purposes: tuple[tuple[int, int], ...]


@functools.lru_cache(maxsize=16)
def _material_node(words: tuple[str, ...]) -> re.Pattern:
    return re.compile(_material_term(words))


@functools.lru_cache(maxsize=1)
def _object_material_words() -> tuple[str, ...]:
    return tuple(sorted({_norm(w) for rule in load_rules()["consistency_rules"]
                         for w in rule.get("text_affirmative_none", ())}))


def _material_group(text: str, start: int, words: tuple[str, ...]) -> Optional[_MaterialGroup]:
    """从实际起点组合材料节点、用途与枚举限定语，返回名词组原跨度。

    同一解析供用途归属及前后置否定消费使用。只消耗已识别的名词构件，
    遇真实谓词/未知文本停止；后面的谓词不使前面已解析用途失去归属。
    标点和主语仍由外层隔离，括号透明投影保留原偏移。
    标签（描述语或带材料词的名词加冒号）与无连词并置都是同位续接；
    对比限定开头的名词不与前项同指，不在同位处续接。
    """
    purposes: list[tuple[int, int]] = []

    def own(part: re.Match) -> None:
        # 用途归属覆盖组内全部构件（标签、节点、尾部描述），不只首个节点。
        purposes.extend((m.start() + part.start(), m.end() + part.start())
                        for m in re.finditer(_PURPOSE_DESCRIPTION, part.group()))

    pos = _GROUP_CONNECTOR.match(text, start).end()
    label = _ENUMERATING_LABEL.match(text, pos) or _DESCRIPTOR_LABEL.match(text, pos)
    apposed = colon = conjoined = False
    if label:
        own(label)
        pos, apposed, colon = label.end(), True, bool(re.search(r"[:：]", label.group("separator")))
        # 没有冒号时描述语本身就是成员，可由连词续接（其他用于隔热的材料及岩棉板材）。
        connector = _GROUP_CONNECTOR.match(text, label.start("separator"))
        if not colon and _CONJUNCTION.search(connector.group()):
            pos, apposed, conjoined = connector.end(), False, True
    end = pos
    found = False
    node_pattern = _material_node(words)
    while True:
        node = node_pattern.match(text, pos) or (_MEMBER_DESCRIPTOR.match(text, pos) if conjoined else None)
        if not node or (apposed and _CONTRASTIVE_START.match(text, node.start())):
            break
        found = True
        own(node)
        end = node.end()
        while tail := _NOMINAL_TAIL.match(text, end):
            own(tail)
            end = tail.end()
        apposition = None if colon else _APPOSITION.match(text, end)
        if apposition and node_pattern.match(text, apposition.end()):
            pos, apposed, colon = apposition.end(), True, True
            continue
        connector = _GROUP_CONNECTOR.match(text, end)
        conjoined = bool(_CONJUNCTION.search(connector.group()))
        pos, apposed = connector.end(), not conjoined
        if pos == node.start():
            break
    if label and not found:
        # 只有描述语也是名词组（未采用用于保温的两种材料）；分隔符不属于组。
        return _MaterialGroup(start, label.start("separator"), tuple(purposes))
    return _MaterialGroup(start, end, tuple(purposes)) if found else None


def _material_object_purposes(fragment: str) -> tuple[tuple[int, int], ...]:
    # 铁律 3：用途的归属不再依赖包含后续独立谓词的整段 fullmatch。
    group = _material_group(fragment, 0, _object_material_words())
    return group.purposes if group else ()


def _insertion_nominal_parts(fragment: str) -> tuple[tuple[int, int], ...]:
    """材料组后紧接真实关系时分别消费，父否定只支配前面的宾语。"""
    group = _material_group(fragment, 0, _object_material_words())
    if group and group.end < len(fragment) and not _FUNCTION_DENIAL.search(fragment):
        tail = fragment[group.end:]
        # 没有新宾语的后置否定属于该组；完整功能否定必须保持一个谓词。
        if (not re.fullmatch(_POST_DENIAL + r"\s*", tail)
                and re.match(rf"\s*(?:{_NEGATION})?{_RELATION.pattern}", tail)):
            return ((0, group.end), (group.end, len(fragment)))
    return ((0, len(fragment)),)


def _purpose_annotation(parent: str, fragment: str, following: str) -> bool:
    """用途插语依附前面的材料宾语，或由括号外「的」完成前置修饰。

    只接纯用途描述；「采用岩棉用于保温」等有自己宾语的完整谓语
    不在此分支。父流已经按主语隔离，不能跨他层材料借用宾语。
    """
    if not re.fullmatch(rf"\s*{_NOUN_MODIFIER}{_PURPOSE_DESCRIPTION}\s*", fragment):
        return False
    return bool(re.match(r"[\s)\]】]*的\s*", following)
                or _material_object_tail().search(parent))


def _unfinished_parent_relation(parent: str, child: str) -> bool:
    """同主语父算子接子谓语；父关系接宾语，独立关系不接另一关系。

    只看最后一个标点/转折后的未完成尾部；已含宾语的关系不支配新谓语。
    谓词可在括号处拆开，但连接后必须是同一个已登记关系词。
    """
    tail = re.split(r"[，,。.;；!?！？\n]|但|并且|而且", parent)[-1].rstrip()
    if re.search(r"(?:未|不|没有|无|非)\s*$", tail):
        return True
    for relation in _PARENT_RELATIONS:
        for split in range(1, len(relation)):
            if tail.endswith(relation[:split]) and child.lstrip().startswith(relation[split:]):
                return True
    return False


def _continued_insertion_object(fragment: str, following: str) -> bool:
    """括号内材料/功能宾语可由括号外连词续接；无关宾语不据此拼平。"""
    if not re.match(r"[\s)\]】]*(?:[，,]\s*)?(?:以及|或者|或|和|及|与|、)", following):
        return False
    return bool(_material_object_tail().search(fragment))


def _clause_parts(clause: _ScopedClause) -> tuple[str, ...]:
    # 连接谓语只存在父 text 中；独立插语有自己的宾语，两类消费者共用边界。
    return (clause.text, *clause.predicates)


def _complete_insertion_predicate(text: str, *, attached_purpose: tuple[bool, ...] = ()) -> bool:
    """铁律 3：有宾语的独立关系不能与父句拼出原文不存在的功能否定。

    「不/未/不具备」是未完算子，仍可接父句宾语；「不具有防水性能」
    已经有自己的宾语。内层已绑定材料的用途关系保留其来源归属，外层
    不能把用途词再解释成独立采用；同片段中的真实新关系仍分别识别。
    """
    if _FUNCTION_DENIAL.search(text):
        return True
    return any(not (attached_purpose and all(attached_purpose[m.start():m.end()]))
               and re.match(r"\s*[^\s，,。.;；!?！？:：\n]+", text[m.end():])
               for m in _RELATION.finditer(text))


def _scoped_clauses(text: str) -> tuple[_ScopedClause, ...]:
    """同主语未完算子/谓词/宾语延续父句，完整独立插语另起谓语。

    父流保留投影字符原跨度与未完关系：父未/不/没有绑定补全谓语，
    用途「的」修饰仍属于材料宾语；已完成父宾语不支配新谓语。独立
    插语另存完整谓语/宾语，两类消费者共用该边界。按片段处理混合
    插语，省略纯确认/无证据修饰；显式本层回切不继承他层否定。
    标点与新谓词界定材料组；未知指代、复杂引语、双重否定不推理；
    不配对括号仍不提供豁免证据。不是任意中文句法或专业选码器。
    """
    pairs = {"(": ")", "[": "]", "【": "】"}
    # 后置主语仍只回指紧邻谓语，不跨标点/括号；跨度基于这个规范化文本。
    postfix_subject = re.compile(
        rf"(?P<predicate>[^，,。.;；!?！？\n()\[\]【】]*?)(?:的\s*)?是\s*(?P<subject>{_SUBJECT})")
    text = postfix_subject.sub(lambda m: m.group("subject") + "：" + m.group("predicate"), text)
    owners = ["current"]
    streams: list[list[tuple[str, int]]] = [[]]
    predicates: list[list[str]] = [[]]
    active, start = 0, 0
    stack: list[tuple[str, int, int]] = []
    # 铁律 3：用途节点透明投影后仍保留原字符归属；嵌套外层不能重判
    # 这个关系为独立谓词。用原跨度标记，主语切换后不向别的流传播。
    purpose_offsets: set[int] = set()
    malformed = False

    def append(begin: int, end: int) -> None:
        streams[active].extend((text[i], i) for i in range(begin, end))

    def switch(owner: str) -> None:
        nonlocal active
        if owners[active] != owner:
            owners.append(owner)
            streams.append([])
            predicates.append([])
            active = len(streams) - 1

    for token in _SCOPE_TOKEN.finditer(text):
        append(start, token.start())
        value = token.group()
        if value in ("本层", "该层"):
            switch("current")
        elif value.endswith("层"):
            switch("foreign")
        elif value in pairs:
            stack.append((pairs[value], active, len(streams[active])))
        elif value in pairs.values():
            if stack and stack[-1][0] == value:
                _, parent, begin = stack.pop()
                # 只投影该父主语实际拥有的字符；foreign/recapture流不会混入。
                insertion = streams[parent][begin:]
                projected = "".join(c for c, _ in insertion)
                relevant = [m for m in re.finditer(r"[^，,。.;；!?！？\n]+", projected)
                            if _insertion_signal().search(m.group())]
                if relevant:
                    # 同一括号可先补父句名词组、再出现独立谓语；按实际
                    # 标点/转折边界逐段处理，不能把整个括号一次移走。
                    transparent: list[tuple[str, int]] = []
                    for part in re.finditer(r"[^，,。.;；!?！？\n]+", projected):
                        for bounded in re.finditer(r"(?:^|但|并且|而且)(.*?)(?=但|并且|而且|$)", part.group()):
                            bounded_start = part.start() + bounded.start(1)
                            bounded_end = part.start() + bounded.end(1)
                            for noun_start, noun_end in _insertion_nominal_parts(projected[bounded_start:bounded_end]):
                                begin_part = bounded_start + noun_start
                                end_part = bounded_start + noun_end
                                fragment = projected[begin_part:end_part]
                                if not _insertion_signal().search(fragment):
                                    continue
                                parent_text = "".join(c for c, _ in streams[parent][:begin] + transparent)
                                attached = _purpose_annotation(parent_text, fragment, text[token.end():])
                                object_purposes = _material_object_purposes(fragment)
                                for purpose_begin, purpose_end in object_purposes:
                                    purpose_offsets.update(offset for _, offset in insertion[
                                        begin_part + purpose_begin:begin_part + purpose_end])
                                if attached:
                                    purpose_offsets.update(offset for _, offset in insertion[begin_part:end_part])
                                if (_unfinished_parent_relation(parent_text, fragment)
                                        or _purpose_modifier(fragment)
                                        or attached):
                                    transparent.extend(insertion[begin_part:end_part])
                                elif (_complete_insertion_predicate(
                                        fragment,
                                        attached_purpose=tuple(offset in purpose_offsets for _, offset in insertion[begin_part:end_part]))
                                      and not _continued_insertion_object(fragment, text[token.end():])):
                                    predicates[parent].append(fragment)
                                else:
                                    if transparent and begin_part > 0 and projected[begin_part - 1] in "，,":
                                        transparent.append(insertion[begin_part - 1])
                                    transparent.extend(insertion[begin_part:end_part])
                    streams[parent][begin:] = transparent
                else:
                    del streams[parent][begin:]
                active = parent
            else:
                malformed = True
                switch("unknown")
        else:
            append(token.start(), token.end())
            if not stack and _NEW_LAYER.match(text[token.end():]):
                switch("current")
        start = token.end()
        if value.endswith("层"):
            # 显式主语标签的「的」属于标签；同主语插标签不能隔断谓语与功能名词。
            possessive = re.match(r"\s*的\s*", text[start:])
            if possessive:
                start += possessive.end()
    append(start, len(text))
    if stack or malformed:
        return (_ScopedClause("unknown", text, ((0, len(text)),)),)
    clauses = []
    for owner, stream, bounded in zip(owners, streams, predicates):
        if not stream and not bounded:
            continue
        spans: list[tuple[int, int]] = []
        for _, offset in stream:
            if spans and spans[-1][1] == offset:
                spans[-1] = (spans[-1][0], offset + 1)
            else:
                spans.append((offset, offset + 1))
        clauses.append(_ScopedClause(owner, "".join(c for c, _ in stream), tuple(spans), tuple(bounded)))
    return tuple(clauses)


def _current_layer_function_denied(clauses: tuple[_ScopedClause, ...]) -> bool:
    """只在当前主语区域内找行内/前后置功能否定，不借他层或无关性能扩大范围。"""
    for clause in clauses:
        if clause.subject != "current":
            continue
        if any(_FUNCTION_DENIAL.search(part) for part in _clause_parts(clause)):
            return True
    return False


# R4F-d fix12，铁律 3：材料否定的辖域按「边界」计算，不再由封闭名词组语法决定。
# 否定算子在谓词位起辖域，向右延伸到第一个边界：句末标点/分号、主语切换（主语流）、
# 新层厚度描述、转折连接、逗号/括号后的独立肯定小句、短语内未被否定的采用关系。连词
# 续接、纯名词短语、无主语用途短语、回指主语、修饰语/量词/引号/破折号都不是边界，所以
# 名词组内部是开放类修饰（高密度、憎水型、A级、防潮的、两款、这批…）也一样在辖域内。
# 括号是插入语：紧接否定关系的括号是宾语；谓词位括号（前面只有副词）是谓语本身，其
# 末态流出；其余括号继承父辖域、内部截断在闭括号后恢复；只含后置否定的括号回指前面的
# 名词；只含否定算子的括号与其后的关系组成算子。后置/评述否定只有在被否定关系没有自己
# 的宾语、或宾语是用途/功能时才回指话题（「岩棉板材：不含石棉」话题仍在）；标签冒号后
# 否定掉的是同类材料成员时，标签同被否定。功能否定与双重否定仍按原样。
# 不是任意中文句法：关系词是封闭语法类，按谓词位/修饰位区分，未覆盖的仍按保守方向处理。
_PAIR = {"(": ")", "[": "]", "【": "】", "〔": "〕", "「": "」", "『": "』", "〈": "〉", "《": "》",
         "“": "”", "‘": "’", "{": "}", "〖": "〗"}
_CLOSER = {v: k for k, v in _PAIR.items()}
_ATOM = ""  # 当前层级上一个完整括号插入语的占位
_HARD_STOP = frozenset("。.;；!?！？\n")
_PHRASE_STOP = frozenset(",，:：")
_ADOPT_MULTI = ("采用|使用|选用|选择|选取|选定|采纳|应用|运用|利用|改用|换用|改为|改成|代之以|设置|增设|另设|加设|"
                "布设|铺设|敷设|铺贴|粘贴|粘结|安装|安设|配置|配备|填充|填塞|嵌填|施工|施作|采取|添加|掺加|铺装|"
                "满铺|满贴|干铺|用到")
_ADOPT_SINGLE = "用|设|做|铺|贴|装|填|加|涂|刷|砌|抹|放|选|采"
_PURPOSE_MULTI = "用于|用作|作为|用来|用以|用在|当作|充当|起到"
_PURPOSE_SINGLE = "作|起"
_POSSESS_MULTI = "含有|具有|具备|存在|包含|带有|附有|设有|配有|需要|要求|承担|发现|见到|看到|看见|检出"
_POSSESS_SINGLE = "有|含|需|须|要|具|见"
_PURPOSE_RELATIONS = frozenset((_PURPOSE_MULTI + "|" + _PURPOSE_SINGLE).split("|"))
# 否定算子：副词型（须接关系或材料/功能词）与动词型（本身即否定谓词）。
_PRE_NEGATION_ADVERB = r"(?:并|也|均|都|皆|亦|尚|仍|还|从|绝|已|又|则|完全|根本|始终|一直|暂|一律|全部|全都|一概|概|决|明确|确实|确认)"
_NEGATOR_ADVERB = r"(?:不(?![仅但论管过断只光])|未|没(?!有)|勿|莫|甭)"
_NEGATOR_VERB = (r"(?:没有|无(?![论关])|(?<![除无莫])非(?![常但])|取消|删除|删去|去掉|去除|拆除|禁止|严禁|禁用|避免|"
                 r"杜绝|放弃|摒弃|舍弃|排除|省去|省略|免设|免做|免铺)")
_NEGATION_MODAL = r"(?:再行|另行|予以|直接|一律|允许|建议|考虑|打算|准备|计划|必要|再|得|准|宜|应|该|可|能|必|曾|予|会|另|法|太|拟)"
_ANY_RELATION = "|".join(sorted(set((_ADOPT_MULTI + "|" + _ADOPT_SINGLE + "|" + _PURPOSE_MULTI + "|" + _PURPOSE_SINGLE
                                     + "|" + _POSSESS_MULTI + "|" + _POSSESS_SINGLE + "|属于|是|为").split("|")),
                                key=len, reverse=True))
_CUE = re.compile(rf"(?P<neg>{_NEGATOR_ADVERB}|{_NEGATOR_VERB})(?P<mod>{_NEGATION_MODAL}*)(?P<rel>{_ANY_RELATION})?")
# 否定关系后的动词补足语属于同一否定谓语（「无需设置」「不需要采用」「严禁在墙内使用」）。
_NEED_RELATIONS = frozenset(("需", "须", "要", "需要", "要求"))
_ADVERBIAL_GAP = r"(?:(?:在|于|从|向|往|对|给)[^,，:：;；。.!?！？\n" + "\ue000" + r"]{0,6}?)?"
_CHAIN = re.compile(rf"\s*{_ADVERBIAL_GAP}(?:{_NEGATION_MODAL})*\s*(?:{_ADOPT_MULTI}|{_PURPOSE_MULTI})")
_NEED_CHAIN = re.compile(rf"\s*{_ADVERBIAL_GAP}(?:{_NEGATION_MODAL})*\s*(?:{_ADOPT_MULTI}|{_PURPOSE_MULTI}|{_ADOPT_SINGLE})")
# 只含否定算子的插入语（「（未）」「（明确未）」「（说明【未】）」），与括号后的关系组成算子。
_BARE_NEGATOR = re.compile(rf"[^,，:：。.;；!?！？\n]{{0,6}}?(?:{_NEGATOR_ADVERB}|{_NEGATOR_VERB}){_NEGATION_MODAL}*\s*")
_ADVERB_BEFORE_SINGLE = r"(?<=[均都也还另亦已则仍再直就才并])"
# 未被否定的谓词（逗号/括号后小句是否独立）：多字关系、系词、副词后的单字关系。
_PREDICATE = re.compile(
    rf"{_ADOPT_MULTI}|{_PURPOSE_MULTI}|{_POSSESS_MULTI}|属于"
    r"|(?<![作认成称因以行较更尤极最改分视变转])为(?![零非止])|(?<![或还但凡若于只总可要倒就即])是"
    rf"|{_ADVERB_BEFORE_SINGLE}(?:{_ADOPT_SINGLE}|{_POSSESS_SINGLE}|{_PURPOSE_SINGLE})")
_ADOPTION = re.compile(rf"{_ADOPT_MULTI}|{_ADVERB_BEFORE_SINGLE}(?:{_ADOPT_SINGLE})")
_THICKNESS_HEAD = re.compile(r"\d+(?:\.\d+)?\s*(?:mm|MM|毫米)?\s*厚")
_CONTRAST = re.compile(r"取而代之|代之以|改用|改为|改成|换用|反而|然而|而是|(?<![不非])但(?:是)?|"
                       r"(?<![从因进继故反然])而(?![且言后已])|却|(?<![^,，:：])(?:不过|可是)")
_PHRASE_ADVERB = r"(?:另行|直接|全部|统一|同时|一律|另外|此外|专门|另|再|仍|均|都|亦|也|还|则|改|又|只|仅|已|须|需|应|宜|可|拟|将|就|才|便)"
_PHRASE_ADOPTION = re.compile(
    rf"\s*{_PHRASE_ADVERB}*(?:{_ADOPT_MULTI}|用(?![于作来以在料量途法户])|设(?![备计施])|做(?!法)|铺|贴(?!面)|属于|为|是)")
_PHRASE_PURPOSE = re.compile(rf"\s*{_PHRASE_ADVERB}*(?:{_PURPOSE_MULTI}|作(?![业法])|起(?!到))")
_PREDICATE_POSITION = re.compile(rf"(?:\s|{_ATOM}|{_PHRASE_ADVERB}|{_PRE_NEGATION_ADVERB})*")
_ANAPHOR = re.compile(r"\s*(?:该|其(?![他它余中])|它|此|这些|那些|上述|前述|以上|二者|两者|这两者|前者|后者|这几种|这两种|这类|此类)")
_LIST_CONJUNCTION = re.compile(r"\s*(?:以及|或者|或是|或|和|及|与|、|连同|包括)")
_CLAUSE_CONJUNCTION = re.compile(r"\s*(?:并且|而且|并|且|同时|也|亦|还|另外)")
_OR_AND_BEFORE = re.compile(r"(?:以及|或者|或是|或|和|及|与|、|连同)\s*$")
_PARTICLES = re.compile(r"[\s" + re.escape("".join(_PAIR) + "".join(_CLOSER)) + r"]|了|过|的|等|啦|呢|即可")
_POSTFIX_SUBJECT = re.compile(
    rf"(?P<predicate>[^，,。.;；!?！？\n()\[\]【】]*?)(?:的\s*)?是\s*(?P<subject>{_SUBJECT})")


def _subject_streams(text: str) -> tuple[tuple[str, str], ...]:
    """与 _scoped_clauses 相同的主语切分（后置主语、回切、新层厚度、括号父主语），
    但保留括号字符，供辖域计算识别插入语；标点后新层厚度另起一条本层流（否定不跨层
    描述）。括号不配对时整体为 unknown。"""
    pairs = {"(": ")", "[": "]", "【": "】"}
    text = _POSTFIX_SUBJECT.sub(lambda m: m.group("subject") + "：" + m.group("predicate"), text)
    owners, streams = ["current"], [[]]
    active, start, stack, malformed = 0, 0, [], False

    def switch(owner: str, fresh: bool = False) -> None:
        nonlocal active
        if owners[active] != owner or fresh:
            owners.append(owner)
            streams.append([])
            active = len(streams) - 1

    for token in _SCOPE_TOKEN.finditer(text):
        streams[active].append(text[start:token.start()])
        value = token.group()
        if value in ("本层", "该层"):
            switch("current")
        elif value.endswith("层"):
            switch("foreign")
        elif value in pairs:
            streams[active].append(value)
            stack.append((pairs[value], active))
        elif value in pairs.values():
            if stack and stack[-1][0] == value:
                _, parent = stack.pop()
                streams[parent].append(value)
                active = parent
            else:
                malformed = True
                switch("unknown")
        else:
            streams[active].append(value)
            if not stack and _NEW_LAYER.match(text[token.end():]):
                switch("current", fresh=True)
        start = token.end()
        if value.endswith("层"):
            possessive = re.match(r"\s*的\s*", text[start:])
            if possessive:
                start += possessive.end()
    streams[active].append(text[start:])
    if stack or malformed:
        return (("unknown", text),)
    return tuple((owner, "".join(parts)) for owner, parts in zip(owners, streams) if "".join(parts))


def _bracket_pairs(s: str) -> dict[int, int]:
    """括号配对（含引号/书名号/六角括号）；不配对的括号字符按普通字符处理。"""
    stack: list[tuple[int, str]] = []
    close_of: dict[int, int] = {}
    for i, ch in enumerate(s):
        if ch in _PAIR:
            stack.append((i, ch))
        elif ch in _CLOSER:
            for depth in range(len(stack) - 1, -1, -1):
                if stack[depth][1] == _CLOSER[ch]:
                    close_of[stack[depth][0]] = i
                    del stack[depth:]
                    break
    return close_of


@dataclass(frozen=True)
class _Cue:
    start: int                 # 当前层级掩码串中的否定算子位置
    end: int                   # 算子（含关系词）结束位置
    relation: str
    relation_atom: Optional[int]   # 关系词在紧随的括号内时，该括号的位置
    topic_denying: bool        # 无宾语/用途/功能宾语：回指话题
    member_denying: bool       # 宾语是材料/功能成员：冒号前的标签同被否定


class _Level:
    """一个层级（整条主语流或一个括号内部）的掩码视图：嵌套括号折叠成单个占位符。"""

    def __init__(self, s: str, lo: int, hi: int, close_of: dict[int, int]):
        chars, atoms = [], []
        i = lo
        while i < hi:
            j = close_of.get(i)
            if j is not None and j < hi:
                chars.append(_ATOM)
                atoms.append((i, j + 1))
                i = j + 1
            else:
                chars.append(s[i])
                atoms.append((i, i + 1))
                i += 1
        self.s, self.m, self.atoms = s, "".join(chars), atoms

    def raw(self, a: int, b: int) -> str:
        return self.s[self.atoms[a][0]:self.atoms[b - 1][1]] if a < b else ""

    def inner(self, i: int) -> str:
        ra, rb = self.atoms[i]
        return self.s[ra + 1:rb - 1]


def _flat(text: str) -> str:
    return "".join(ch for ch in text if ch not in _PAIR and ch not in _CLOSER)


def _in_relative(m: str, start: int, end: int, b: int) -> bool:
    # 「用于隔热的XPS板材」「所采用的」：关系在「的」字关系从句里，是修饰不是谓语。
    if start > 0 and m[start - 1] == "所":
        return True
    k = m.find("的", end, b)
    return k >= 0 and not _PREDICATE.search(m[end:k])


def _phrase_cues(level: _Level, a: int, b: int, atom_pattern: re.Pattern) -> list[_Cue]:
    m, cues = level.m, []

    def add(p: int, end: int, relation: str, relation_atom: Optional[int], rest: str) -> None:
        rest = _PARTICLES.sub("", rest)
        topic = not rest or relation in _PURPOSE_RELATIONS or "保温" in rest or "隔热" in rest
        cues.append(_Cue(p, end, relation, relation_atom, topic, topic or bool(atom_pattern.search(rest))))

    def relation_after(end: int) -> tuple[str, Optional[int], str, int]:
        # 关系词可直接跟在算子后（可隔介词状语「在墙内」），也可在紧随的括号开头（「未（采用…）」）。
        hit = re.compile(rf"\s*{_ADVERBIAL_GAP}({_ANY_RELATION})").match(m, end, b)
        if hit:
            return hit.group(1), None, "", hit.end()
        k = end
        while k < b and m[k].isspace():
            k += 1
        if k < b and m[k] == _ATOM:
            inner = re.match(rf"[\s{re.escape(''.join(_PAIR))}]*({_ANY_RELATION})", level.inner(k))
            if inner:
                return inner.group(1), k, level.inner(k)[inner.end():], k
        return "", None, "", end

    i = a
    while i < b:
        if m[i] == _ATOM and _BARE_NEGATOR.fullmatch(_flat(level.inner(i))):
            relation, relation_atom, rest_inside, end = relation_after(i + 1)
            if relation:
                tail = level.raw(relation_atom + 1, b) if relation_atom is not None else level.raw(end, b)
                add(i, relation_atom if relation_atom is not None else end, relation, relation_atom, rest_inside + tail)
            i += 1
            continue
        hit = _CUE.match(m, i, b)
        if not hit or re.match(_ADJECTIVE, m[i:b]):
            i += 1
            continue  # 已登记的否定前缀形容词（不燃/非承重）不是算子
        p = i
        relation, relation_atom, rest_inside, end = hit.group("rel") or "", None, "", hit.end()
        if not relation:
            relation, relation_atom, rest_inside, end = relation_after(hit.end())
        if relation_atom is None:
            chain = (_NEED_CHAIN if relation in _NEED_RELATIONS else _CHAIN).match(m, end, b)
            if chain and (relation or not re.fullmatch(_NEGATOR_ADVERB, hit.group("neg"))):
                end = chain.end()
        material_next = bool(re.compile(rf"\s*(?:{atom_pattern.pattern})").match(m, hit.end(), b))
        in_object = bool(_PREDICATE.search(m, a, p) or _THICKNESS_HEAD.search(m[a:p]))
        i = max(hit.end(), p + 1)
        if re.fullmatch(_NEGATOR_ADVERB, hit.group("neg")):
            if not relation and not material_next:
                continue  # 副词否定须接关系或材料/功能词（不燃、未经、不仅不是算子）
        elif in_object and not relation and not material_next:
            continue  # 宾语内的「无机/非燃烧体/无甲醛」是修饰语
        if relation_atom is not None:
            add(p, relation_atom, relation, relation_atom, rest_inside + level.raw(relation_atom + 1, b))
        else:
            add(p, end, relation, None, level.raw(end, b))
    return cues


def _unnegated(m: str, pattern: re.Pattern, a: int, b: int, cues: list[_Cue], skip_lead: bool) -> list[int]:
    out = []
    lead = len(m[a:b]) - len(m[a:b].lstrip()) + a
    for hit in pattern.finditer(m, a, b):
        if any(c.start <= hit.start() < max(c.end, c.start + 1) for c in cues):
            continue
        if skip_lead and hit.start() == lead:
            continue
        if _in_relative(m, hit.start(), hit.end(), b):
            continue
        out.append(hit.start())
    return out


def _np_only(level: _Level, a: int, b: int, atom_pattern: re.Pattern) -> bool:
    if _NEW_LAYER.match(level.m, a, b):
        return False  # 层厚度描述是本层名称，不是后置否定的话题
    return not _phrase_cues(level, a, b, atom_pattern) and not _unnegated(level.m, _PREDICATE, a, b, [], False)


def _phrase_breaks(level: _Level, a: int, b: int, sep: str, atom_pattern: re.Pattern, seg_end: int) -> bool:
    """继承的否定能否进入这个短语：独立肯定小句截断，续接成分继承。

    转折词（却/但）切开的短语，其谓语在转折词之后：谓语按到下一个标点为止的整段判断。"""
    m = level.m
    text = m[a:b]
    cues = _phrase_cues(level, a, b, atom_pattern)
    whole = _phrase_cues(level, a, seg_end, atom_pattern) if seg_end > b else cues
    lead = a + len(text) - len(text.lstrip())
    if cues and re.fullmatch(rf"{_PRE_NEGATION_ADVERB}*", m[lead:cues[0].start]):
        return False  # 短语以否定开头：仍在否定中
    conj = _LIST_CONJUNCTION.match(m, a, b) or _CLAUSE_CONJUNCTION.match(m, a, b)
    if conj:
        # 连词后「以及/并且 + 未被否定的采用」另起谓语；连词后的名词（含后置用途）/否定续接。
        return bool(_PHRASE_ADOPTION.match(m, conj.end(), b) or _unnegated(m, _ADOPTION, conj.end(), seg_end, whole, False))
    adopting = _unnegated(m, _ADOPTION, a, seg_end, whole, False)
    if _ANAPHOR.match(m, a, b) and not adopting:
        return False  # 回指主语继承极性（「其为保温材料」）
    purpose = _PHRASE_PURPOSE.match(m, a, b)
    if purpose and not adopting:
        if not _in_relative(m, purpose.end() - 1, purpose.end(), b):
            return False  # 无主语用途短语属于前面的宾语
        if sep == "(" and _PARTICLES.sub("", m[m.find("的", purpose.end(), b) + 1:b]):
            return True   # 名词后括号「用于保温的X」有自己的中心语：独立陈述，不是注释
    if _PHRASE_ADOPTION.match(m, a, b):
        return True   # 省略主语的新采用谓语
    if sep in (":", "："):
        return bool(adopting)  # 标签冒号后是成员
    if _unnegated(m, _PREDICATE, a, seg_end, whole, False):
        return True   # 名词 + 未否定谓语：独立肯定小句
    # 名词 + 带自身宾语的否定关系（「XPS板不含甲醛」）：话题仍在，也是独立小句。
    return any(not c.topic_denying for c in cues)


def _split_phrases(m: str, a: int, b: int) -> list[tuple[int, int, str]]:
    cuts: list[tuple[int, int, str]] = []
    for i in range(a, b):
        if m[i] in _PHRASE_STOP:
            cuts.append((i, i + 1, m[i]))
    for hit in _CONTRAST.finditer(m, a, b):
        if not any(s <= hit.start() < e for s, e, _ in cuts):
            cuts.append((hit.start(), hit.start(), "contrast"))
    cuts.sort()
    phrases, start, sep = [], a, ""
    for s, e, kind in cuts:
        if s < start:
            continue
        phrases.append((start, s, sep))
        start, sep = e, kind
    phrases.append((start, b, sep))
    return phrases


def _deny(denied: list[bool], start: int, end: int) -> None:
    for k in range(start, end):
        denied[k] = True


def _walk_level(s: str, lo: int, hi: int, inherit: bool, lead: str, close_of: dict[int, int],
                denied: list[bool], atom_pattern: re.Pattern) -> tuple[bool, bool]:
    """处理一个层级；返回（是否只含后置否定、层级末尾的否定状态）。

    lead：""＝普通插入语；"object"＝否定关系的宾语括号；"relation"＝否定算子后、
    以关系词开头的括号（该关系词属于算子，不是新谓语）。"""
    level = _Level(s, lo, hi, close_of)
    m = level.m
    bracket_only = False
    nested = lo > 0 or hi < len(s)
    clause_start, neg = 0, False
    for index in range(len(m) + 1):
        if index < len(m) and m[index] not in _HARD_STOP:
            continue
        first_clause = clause_start == 0
        # 顶层句末结束否定；括号内的句末只分隔插入语内部小句，父辖域仍流入。
        neg = inherit if (first_clause or nested) else False
        phrases = _split_phrases(m, clause_start, index)
        for number, (a, b, sep) in enumerate(phrases):
            leading = bool(lead) and first_clause and number == 0
            seg_end = b
            for later in phrases[number + 1:]:
                if later[2] != "contrast":
                    break
                seg_end = later[1]
            if sep == "contrast":
                neg = False
            elif neg and not leading and _phrase_breaks(level, a, b, sep or (nested and "("), atom_pattern, seg_end):
                neg = False
            cues = _phrase_cues(level, a, b, atom_pattern)
            stops = set(_unnegated(m, _ADOPTION, a, b, cues, leading and lead == "relation"))
            stops = {q for q in stops if not _OR_AND_BEFORE.search(m[a:q])}

            def anchor(cue: _Cue) -> int:
                start, k = a, number
                while k > 0 and phrases[k][2] in (",", "，", ":", "：") and \
                        (cue.topic_denying or phrases[k][2] in (":", "：")) and \
                        _np_only(level, phrases[k - 1][0], phrases[k - 1][1], atom_pattern):
                    k -= 1
                    start = phrases[k][0]
                return start

            by_start = {c.start: c for c in cues}
            object_until = a if leading else -1   # 紧接否定关系的括号（及其并置括号）是宾语
            if leading and lead == "relation":
                head = re.compile(rf"\s*(?:{_ANY_RELATION})").match(m, a, b)
                object_until = head.end() if head else a
            for i in range(a, b):
                cue = by_start.get(i)
                if cue:
                    neg = True
                    object_until = cue.end
                    if cue.topic_denying:
                        # 无宾语/用途宾语的后置否定：话题（含逗号/冒号前的纯名词短语）被否定。
                        origin = anchor(cue)
                        if origin < cue.start:
                            _deny(denied, level.atoms[origin][0], level.atoms[cue.start][0])
                    elif cue.member_denying and _PREDICATE_POSITION.fullmatch(m[a:cue.start]):
                        # 「保温材料：未采用岩棉板材」：被否定的是标签下的同类成员，标签同被否定。
                        origin = anchor(cue)
                        if origin < a:
                            _deny(denied, level.atoms[origin][0], level.atoms[a][0])
                    if cue.topic_denying and first_clause and number == 0 and re.fullmatch(
                            rf"\s*{_PRE_NEGATION_ADVERB}*\s*", m[a:cue.start]):
                        bracket_only = True
                elif i in stops and neg:
                    neg = False
                ra, rb = level.atoms[i]
                if m[i] == _ATOM:
                    if any(c.relation_atom == i for c in cues):
                        inner_lead = "relation"
                    elif (object_until >= 0 and not m[object_until:i].strip()) or (
                            neg and _OR_AND_BEFORE.search(m[a:i])):
                        inner_lead = "object"   # 宾语位或并列连词后的括号是宾语成员
                    else:
                        inner_lead = ""
                    transparent = bool(_PREDICATE_POSITION.fullmatch(m[a:i]))
                    if cue and cue.start == i:
                        # 只含算子的括号：算子本身，括号内容已由父层级解读。
                        continue
                    inner_only, inner_neg = _walk_level(s, ra + 1, rb - 1, neg, inner_lead, close_of,
                                                        denied, atom_pattern)
                    if inner_lead:
                        object_until = i + 1
                    if inner_only:
                        origin = anchor(_Cue(i, i, "", None, True, True))
                        if origin < i:
                            _deny(denied, level.atoms[origin][0], ra)
                    if transparent:
                        neg = inner_neg   # 谓词位括号即谓语，末态流出
                elif neg:
                    denied[ra] = True
        clause_start = index + 1
    return bracket_only, neg


def _negation_denied(stream: str, words: tuple[str, ...]) -> list[bool]:
    atoms = "|".join(re.escape(w) for w in sorted(set(words), key=len, reverse=True)) or r"(?!)"
    denied = [False] * len(stream)
    _walk_level(stream, 0, len(stream), False, "", _bracket_pairs(stream), denied, re.compile(atoms))
    return denied


def _affirmative_any(words: Iterable[str], text: str) -> bool:
    """当前层肯定材料不能推翻本层功能冲突；他层材料不能充当本层证据。"""
    clauses = _scoped_clauses(text)
    if _current_layer_function_denied(clauses):
        return False
    # 有限语法无法断定双重否定，不从同一区域拾取材料当肯定证据。
    if any(c.subject == "current" and any(_AMBIGUOUS_NEGATION.search(part)
           for part in _clause_parts(c)) for c in clauses):
        return False
    words = tuple(_norm(w) for w in words)
    for owner, stream in _subject_streams(text):
        if owner != "current":
            continue
        denied = _negation_denied(stream, words)
        for word in words:
            for hit in re.finditer(re.escape(word), stream):
                if not all(denied[hit.start():hit.end()]):
                    return True
    return False


def _rule_applies(rule: dict, text: str, ctx: str, category: str = "") -> bool:
    # 仅声明 category_any 的规则使用结构化类别。兼容旧纯文本调用，其余规则不变。
    # 当前片段类别来自编号/列组，房间位置与引用中的异部位词不能关闭它的语义闸。
    categories = rule.get("category_any")
    if categories is not None and category and category not in categories:
        return False
    rule_ctx = category if categories is not None and category else ctx
    both = text + "\n" + ctx
    checks = (
        ("any", both, True), ("text_any", text, True), ("ctx_any", rule_ctx, True),
        ("any_none", both, False), ("text_none", text, False), ("ctx_none", rule_ctx, False),
    )
    for key, hay, want in checks:
        words = rule.get(key)
        if words is None:
            continue
        if _any(words, hay) != want:
            return False
    words = rule.get("text_affirmative_none")
    if words is not None and _affirmative_any(words, text):
        return False
    return True


def check_consistency(code: str, text: str, context: str = "", *, category: str = "") -> list[Violation]:
    """编码与原文 / 上下文是否一致。返回违反的规则（空 = 一致）。**只判不改**（决策 D52）。"""
    t, c = _norm(text), _norm(context)
    bare = _strip_z(code)
    out: list[Violation] = []
    for rule in load_rules()["consistency_rules"]:
        if not _rule_applies(rule, t, c, _norm(category)):
            continue
        expect = tuple(rule.get("expect") or ())
        forbid = tuple(rule.get("forbid") or ())
        bad = bool(expect) and not any(bare.startswith(p) for p in expect)
        bad = bad or any(bare.startswith(p) for p in forbid)
        if bad:
            out.append(Violation(rule["id"], rule["message"], expect, forbid, tuple(rule.get("suggest") or ())))
    return out


# ============================================================ 存疑闸（R4F-d fix13 → fix15，R4-006）
# 用户决定（2026-10-11 16:19）：同一句里只要出现否定，就降为「待人工确认」，不再判正式项；宁可多让人看
# 一眼，也不能漏判。本闸**只降级、不升级**（铁律 3）：调用方只在一条正式项即将成立时问它；命中就改成
# 待核（保留建议编码、来源、位置、全文，不出工程量），从不改码、改单位，也不把待核升成正式项。
# 用户 2026-10-12 四项决定（fix15）：
#   1. 作用域按切层之前的原文判（doubt_host）：本层所在单元格 / 段落（xlsx 格内多行不切断）里与本层同一「句」的全部
#      文字——句界 。！？；; 换行（docx 段落 / 单元格内的硬换行）、段落、单元格；层号「1) 2) ①」、逗号、冒号、括号内都
#      不切句。同句里的兄弟层、做法名称 / 编号行与批注（含行首 □ ○ 空框）都在作用域内。跨句：触发句带前指（以下 /
#      下列 / 如下 / 其后 / 冒号或省略号结尾）覆盖其后，带回指（上述 / 前述 / 以上 / 该 / 此 / 其 / 这些 / 那些 / 两层 /
#      各层 / 均 / 全部 / 整个做法 …，按语素认）覆盖其前；拿不准时取宽：本层自己的原文（含同格续行）里任何一句的触发都
#      算（doubt_gate，fix14 口径），层号外的说明文字对该格各层都算。另一单元格的文字不因「续行」并进本层作用域
#      （quantity_segment 把它记在 Segment.out_ranges，调用方用 scope_text()）。
#   2. 触发：范围内触发清单由本节各表生成（_logs/R4F-d-fix15-20261012/trigger-inventory.md）：否定、取消 / 删除 /
#      作废 / 撤项 / 去除、替代（改为 / 以B代A / 由B替代 / 箭头）、无此项符号（× — / N/A 〇 无符号 0 空框）、常见英文
#      否定，以及清单里每个汉字的繁体 / 异体写法（_DOUBT_TRAD_PAIRS）。
#   3. 放行名单：quantity_rules.yaml 的 doubt_safe_terms（规范比较用语、材料属性、构造类型）只遮蔽术语本身；
#      别 缺 除 代 换 空 停 弃 废 免 零 否 略 掉 剔 欠 乏 拒 罢 汰 休 舍 这些有非否定复合词的单字按语素模式认
#      （_DOUBT_MORPH：否定义为主的只排除列明的非否定复合词，其余只认列明的否定搭配）；fix14 的「改性」「空白」
#      临时例外删除，改由放行名单里的「改性 + 材料」「中空 + 玻璃」表达。
#   · 遮蔽：yaml 词典里已匹配上的材料名 / 层名 / 编码字面与放行术语；触发的**首字**落在遮蔽区里才不算；
#   · 「拟 / 暂定 / 或 / 可选 / 待定」不在批准的范围内，不算触发。
# R4F-d fix16（review16a / 16b / 16c，四项决定不变，只修实现偏离合同处；仍只降级）：
#   · 决定 1：无表头表格一行拼成一句时以本层材料所在格为锚（quantity_segment._own_hosts）；另一句的序数指层（第1层 /
#     第一层 / 第1、2层 / 首层 …，层号对得上或认不出才算）、点名本层材料 / 层名、英文指代（both / all above）算回指 / 前指；
#     层号外说明文字指向别的层时不算本层；被否定的辅层与主层过同一道闸（quantity_list.decide）；
#   · 决定 2：代 换 掉 略 缺省算（只排除列明的非否定复合词）；「以…代」「除…外」按合同句配对；省了 / 此层空 / 转 + 材料；
#     叉号前置（×60厚、1)×60厚、x60厚）；撇号写法；「为0.」；
#   · 决定 3：放行术语不跨句、字间断开要末字后也断开、after / not_after；「免拆」只收「免拆模板」一类整词；名单补到 40 条。

DOUBT_REASON = "同句含否定/替代/取消表述，需人工确认是否采用"
DOUBT_NEGATION, DOUBT_SUBSTITUTION, DOUBT_CANCEL, DOUBT_SYMBOL = "否定", "替代", "取消", "无此项符号"
DOUBT_WIDE = "取宽（作用域不明）"

# 无条件的单字否定（繁体 / 异体先折叠再判）
_DOUBT_NEG_CHARS = frozenset("不未没无冇唔非勿莫毋甭弗匪罔靡蔑禁忌撤删拆嫑覅朆呒岂咪砍")
_DOUBT_SUB_CHARS = frozenset("替")
# 「改」是变动动词：后接动词（改挂、改喷、改刮…）或名词（改XPS板、改岩棉板、改抹灰…）都是替代；
# 「改性沥青 / 改性砂浆」这类材料名由放行名单（doubt_safe_terms 的「改性 + 材料」）遮蔽，代码里不再设例外
_DOUBT_GAI = "改"
_DOUBT_ZERO_CHARS = frozenset("〇")
# 去除 / 搬运类动词：「V去 / V走」动补、「V掉」「V除」的前字
# R4F-d fix18（协调者裁定 2，review18a R18A-08）：按语素类补齐冲刷 / 锤击 / 爆破 / 掰折 / 钻凿 / 撞踢 / 劈锉 / 掀拽 / 焚融 …
# 一类去除动作的单字（刷掉灰层、冲掉砂层、锤掉块料、炸掉块石、掰掉棱角、冲除浮浆、刷除浮灰、钻除浮浆、冲走浮砂、刷去浮灰）
_DOUBT_REMOVE_VERBS = ("铲凿揭剥撕割挖刮截扒锯卸拆删剔略省抹划勾裁砍舍拿消剪刨扣减移撤除清运搬挪拉取抽拔摘撬敲砸磨削"
                       "切剁剃剜抠擦吹吸抬拖吊收调转扛推捞铣甩丢扔抛弃掏洗褪脱滤筛退扯挑烧熔"
                       "刷冲锤炸掰钻撞踢劈锉磕掀融溶喷碾拧扭拽揪薅掐拨搓揉剐戳捅錾剖斩焚涮漂淘沥掸拂揩拭拣捡掳")
# R4F-d fix17（协调者裁定 2）：缺省算的语素字（除 掉 代 换 …）前字是去除 / 清除类动词时先判为触发，不看后字排除表
# （铲除灰层、凿除砂浆层、清除油漆面层、打掉砂浆层、敲掉块料、铲掉漆层）。按语素类认：上面的去除 / 搬运类动词，再加
# 打（打掉）、排（排除）、革 根 破 废 解 免 扫 驱 祛 摒 屏 戒 剿 涤（革除 根除 破除 废除 解除 免除 扫除 驱除 …）
_DOUBT_CLEAR_VERBS = frozenset(_DOUBT_REMOVE_VERBS + "打排革根破废解免扫驱祛摒屏戒剿涤去")


@dataclass(frozen=True)
class _Morph:
    """只在复合词里才是否定 / 替代 / 无此项的单字（决定 3）：按紧凑流里的前字 / 后字判。
    次序：前字在 prev_no（后字在 prev_no_unless 时除外）或后字在 next_no（后面紧接 next_no_unless 里的词时除外）里 →
    不算；两侧都不是汉字（单字成词：「（空）」「：废」）→ 算；前字在 end_after 且后面不是汉字（「此层空」「此层省」句末）
    → 算；前字在 prev_ok 或后字在 next_ok → 算；next_non_cjk：后面不是汉字（句末 / 标点 / 数字）→ 算；next_ascii：后接字母
    数字 → 算；next_material：后接词典材料词 → 算；prev_non_cjk：前面不是汉字（句首）→ 算；否则按 default。
    R4F-d fix16：否定 / 替代义为主的字（别 缺 除 停 弃 废 免 零 否 罢 汰，以及 代 换 掉 略）default=True，只排除列明的
    非否定复合词（代号 / 年代 / 换热 / 换气 / 掉落 / 略高 …）—— 封闭的搭配表漏掉真否定（用B代A、换别的材料、打掉、此层略），
    排除表漏掉的普通词只会多报待核；非否定义为主的字（空 省 剔 欠 乏 拒 休 舍）只认列明的否定 / 替代搭配。
    R4F-d fix17（协调者裁定 2）：缺省算的字，前字是 prev_ok 或去除 / 清除类动词（_DOUBT_CLEAR_VERBS）时先算，后字排除表
    不再压过它（铲除灰层、敲掉块料）；排除只按「整词」认（next_no_words：换 + 热器 / 热站 / 气扇 / 气次数 …），不按后字
    一刀切（换热固复合聚苯板、换气泡混凝土砌块照算）；object_first：后面紧接词典材料词或「X层」时先算（除砂浆层、
    除灰土垫层、除油漆面层 —— 去掉的是一层材料，不是「除油 / 除灰」工序）。"""
    kind: str
    default: bool = False
    prev_ok: frozenset = frozenset()
    next_ok: frozenset = frozenset()
    prev_no: frozenset = frozenset()
    next_no: frozenset = frozenset()
    prev_no_unless: frozenset = frozenset()
    next_no_unless: tuple = ()
    next_no_words: tuple = ()
    prev_no_words: tuple = ()
    end_after: frozenset = frozenset()
    next_non_cjk: bool = False
    next_ascii: bool = False
    next_material: bool = False
    prev_non_cjk: bool = False
    object_first: bool = False
    # 整词排除的「除非后面紧接」：除锈 + 蚀（「除锈蚀严重部位外」是「除…外」）
    next_no_words_unless: tuple = ()
    # 前字是去除 / 清除类动词时先算（裁定 2）。弃 / 废 不作去除动词的补语（没有「铲弃」「凿废」这类去除复合词），
    # 前字恰好在那一类里时是另一个词：废弃物（废 + 弃物）、外运弃土（运 + 弃土）、排废气（排 + 废气）—— 这两个字关掉
    clear_first: bool = True
    # R4F-d fix18（裁定 2，按语素类）：非空时 next_no 只在前字是这些字或不是汉字时生效——「掉」只在缺陷语境（不掉灰、防掉落、
    # 起砂掉灰、易掉皮、句首掉色）里排除，前面是别的汉字（多半是动作动词：清理掉、处理掉、锤掉、撬掉 …）照算
    next_no_ctx: frozenset = frozenset()


_DOUBT_VERBS = frozenset("用做铺贴装设采选刷涂抹砌施安放加填要再动上搞弄使浇灌钉挂粘喷刮批打封包敷覆盖留买进送拆改换碰让"
                         "忘管拿搬运堆压踩踏撞搭接连焊锚嵌埋衬垫找磨抛镀泡淋冲洗擦拖扫扔丢去走开漏乱想信看急")
_DOUBT_MORPH: dict[str, _Morph] = {
    # 别：「别 + 动词」是禁止（别用、千万别铺）；分别 / 识别 / 级别 / 类别 / 别墅 / 别名 / 千差万别 … 不是
    "别": _Morph(DOUBT_NEGATION, default=True,
                prev_no=frozenset("分识区类级特个差辨鉴判告离派性组型科门送惜诀永话阔道吻拜挥作甄国"),
                next_no=frozenset("墅名称处的人具致针样院克离字号册卷稿体种类国家业"), prev_no_words=("千差万",)),
    # 休：「休 + 动词」（休铺、休用）是古白话的禁止；休息 / 休闲 不是
    "休": _Morph(DOUBT_NEGATION, next_ok=_DOUBT_VERBS | frozenset("要想得")),
    # 缺：缺层 / 缺项 / 缺失 / 缺少 / 本层缺岩棉板 / 欠缺 / 空缺 … 都算；缺口 / 缺陷 / 缺角 / 缺损 / 缺棱 / 缺省 / 缺氧 / 残缺
    # 不是
    "缺": _Morph(DOUBT_NEGATION, default=True, prev_no=frozenset("残"), next_no=frozenset("口陷角损棱省氧")),
    # 除：拆除 / 去除 / 清除 / 删除 / 除去 / 除掉 / 除外 / 「除…外」… 都算；除锈 / 除尘 / 除湿 / 除油 / 除污 … 这类
    # 「除 + 污物」的表面处理工序（整词）不是。fix17（裁定 2）：前字是去除 / 清除类动词（铲除 凿除 清除 剔除 挖除 …）先算；
    # 后面紧接材料词或「X层」（除砂浆层、除灰土垫层、除油漆面层、除灰层）也先算；排除只认整词，「除甲方…外」照算
    "除": _Morph(DOUBT_NEGATION, default=True, object_first=True,
                next_no_words=("锈", "尘", "湿", "油", "污", "垢", "灰", "冰", "霜", "味", "臭", "醛", "草", "虫", "渣",
                               "砂", "泥", "菌", "霉", "甲醛", "杂质", "杂物", "杂草", "浮浆", "浮灰", "浮尘", "浮锈",
                               "以"),
                next_no_words_unless=("锈蚀",)),
    # 代（fix16：替代义为主，缺省算）：代替 / 取代 / 代以 / 代之 / 用B代A / 由B代 / （B代）/ 以B（…）代A 都算；
    # 代号 / 代表 / 代码 / 代理 / 代价 / 代建 / 代为 / 年代 / 现代 / 交代 / 第三代 … 不是
    "代": _Morph(DOUBT_SUBSTITUTION, default=True, prev_ok=frozenset("取替顶改更"), next_ok=frozenset("替以用换之"),
                prev_no=frozenset("年时世近现当古交后历朝末上下隔断绝迭一二三四五六七八九十几多"),
                next_no=frozenset("表号码理价购办收谢际言位课词数销管扣缴建为金沟")),
    # 换（fix16：替代义为主，缺省算）：更换 / 换成 / 换用 / 换 + 任何材料（换泡沫玻璃板 / 换其他材料 / 换一种做法 /
    # 换气凝胶毡）都算；换算 / 换填 / 换乘 / 换行 / 交换 / 兑换 / 换衣 … 不是。fix17（裁定 2）：换热 / 换气 只按整词排除
    #（换热器 / 换热站 / 换热机组 … / 换气扇 / 换气次数 / 换气口 …），「换热固复合聚苯板」「换热反射涂料」「换气泡混凝土
    # 砌块」是换 + 材料，照算
    "换": _Morph(DOUBT_SUBSTITUTION, default=True, prev_ok=frozenset("更替置改调互撤对掉"),
                next_ok=frozenset("用成为作掉上下了去取铺贴装做刷涂砌"), next_ascii=True, next_material=True,
                prev_no=frozenset("交兑"), next_no=frozenset("算填行季届乘页向衣鞋代班证"),
                next_no_words=("热器", "热站", "热机组", "热设备", "热管", "热量", "热面积", "热效率", "热系数", "热盘管",
                               "热首站", "热机房", "热间", "热装置", "热系统", "气扇", "气次数", "气量", "气口", "气机",
                               "气装置", "气窗", "气孔", "气设备", "气系统", "气管", "气率",
                               # fix18（review18b R18B-05 的 P2，整词）：换气功能 / 换气百叶 / 换气效果 / 换气性能 这类通风用语。
                               # fix19：换热计算是计算术语；旧夹具的待核期望不能取代用户的语素合同。
                               "气功能", "气百叶", "气效果", "气性能", "热计算")),
    # 空：单字成词（「（空）」「：空」）、「此层空 / 本项空」句末；复合词（空白 / 留空 / 为空 / 空缺 …）在 _DOUBT_COMPOUNDS
    "空": _Morph(DOUBT_SYMBOL, end_after=frozenset("层项格栏")),
    # 停：停用 / 停止 / 停做 / 停建 / 暂停 / 叫停 / 已停 … 都算；停车 / 停放 / 停靠 / 停留 / 停顿 / 停机坪 / 停电 不是
    "停": _Morph(DOUBT_NEGATION, default=True, next_no=frozenset("车放靠泊留顿歇息机电")),
    # 弃：弃用 / 放弃 / 舍弃 / 废弃 / 弃之 … 都算；弃土 / 弃渣 / 弃料 / 弃方 不是
    "弃": _Morph(DOUBT_NEGATION, default=True, next_no=frozenset("土渣料方石砟物"), clear_first=False),
    # 废：作废 / 已废 / 报废 / 废除 / 废止 / 废弃 … 都算；废料 / 废水 / 废气 / 废渣 / 废物 / 废旧 / 废弃物 不是
    "废": _Morph(DOUBT_NEGATION, default=True, next_no=frozenset("料水气渣物旧品油纸液浆热铁钢"),
                next_no_words=("弃物",), clear_first=False),
    # 免：免做 / 免铺 / 免设 / 免除 / 免于 / 免予 / 豁免 / 减免 … 都算；免钉 / 免拆 / 免漆 / 免烧 / 免蒸 / 免振捣 / 以免 / 难免
    # 不是（「免拆」本身不再放行：拆 是无条件否定字，只有「免拆模板」这类构造类型在放行名单里）
    # fix17（review17c R17C-05）：「免漆」只在免漆板 / 免漆门 这类材料名（整词）里排除，涂料层的「本层免漆」是不做这一层
    "免": _Morph(DOUBT_NEGATION, default=True, prev_no=frozenset("以难避"), next_no=frozenset("钉拆烧蒸检费疫振"),
                next_no_words=("漆板", "漆门", "漆木", "漆饰面", "漆实木", "漆生态板", "漆家具", "漆柜", "漆型")),
    # 零：工程量为零 / 零项 / （零）… 都算；零星 / 零件 / 零下 / 零售 / 零散 / 零部件 / 零线 / 零坡度 / 零甲醛 / 零VOC /
    # 零排放 / 一百零五 不是
    "零": _Morph(DOUBT_SYMBOL, default=True, prev_no=frozenset("千百万亿"),
                next_no=frozenset("星件下售散部碎头钱线度时点坡v甲排污")),
    # 否：否 / 否决 / 「是否采用：否」，以及「是否 / 能否 / 可否 + 采用 / 使用 / 设置 / 施工 / 铺设 …」（本层用不用拿不准）
    # 都算；「是否加设托架」「锚栓是否加密」这类问别的细节的、与否 / 否则 不是
    "否": _Morph(DOUBT_NEGATION, default=True, prev_no=frozenset("是能可与成然当"),
                prev_no_unless=frozenset("采使选设施实铺安保需列计做用装留"), next_no=frozenset("则")),
    # 略（fix16：省略义缺省算）：省略 / 从略 / 略去 / 此层略 / （略）都算；略高 / 略低 / 略有 / 略微 / 略作 / 策略 / 简略 /
    # 大略 / 约略 … 不是
    "略": _Morph(DOUBT_NEGATION, default=True, prev_ok=frozenset("省忽从删"), next_ok=frozenset("去过掉"),
                prev_no=frozenset("策战方谋攻粗简大概约领侵韬史要才胆智雄"),
                next_no=frozenset("高低有大小微带显超厚薄长短宽窄多少为图作加偏重轻胜逊深浅早晚快慢差好强弱向斜凸凹呈述知读倾")),
    # 省（fix16）：省了 / 省却 / 此层省（句末）算；省掉 / 省去 / 省略 / 可省 在 _DOUBT_COMPOUNDS；节省 / 省标 / 本省 不是
    "省": _Morph(DOUBT_NEGATION, next_ok=frozenset("了却除免"), end_after=frozenset("层项")),
    # 掉（fix16：去除义缺省算）：去掉 / 拆掉 / 打掉 / 清理掉 / 砸掉 / 搞掉 / 处理掉 … 都算；掉落 / 掉灰 / 掉皮 / 掉粉 / 掉色 不是
    "掉": _Morph(DOUBT_NEGATION, default=True,
                prev_ok=frozenset(_DOUBT_REMOVE_VERBS) | frozenset("去删省除砍扔拿撤换废免干甩停改弄"),
                next_no=frozenset("落灰皮粉色渣块角棱头漆砂屑线"),
                next_no_ctx=frozenset("不未无没别勿莫甭防免避易会能可致导起砂鼓裂粉皮渣止及和与或并等严禁需须应要将已再"
                                      "棱角落色块头漆屑线灰锈蚀壳缝损")),
    # 剔：剔除 / 剔去 / 剔掉 / 剔出；剔凿 不是
    "剔": _Morph(DOUBT_NEGATION, next_ok=frozenset("除去掉出")),
    # 欠：欠缺 / 欠妥；欠火砖 不是
    "欠": _Morph(DOUBT_NEGATION, next_ok=frozenset("缺妥做铺设装项")),
    # 乏：缺乏 / 匮乏
    "乏": _Morph(DOUBT_NEGATION, prev_ok=frozenset("缺匮贫")),
    # 拒：拒绝 / 拒用 / 拒收；拒水（憎水材料）不是
    "拒": _Morph(DOUBT_NEGATION, next_ok=frozenset("绝用收做铺设装签批不付")),
    # 罢：作罢 / 罢用 / 罢铺 / 罢免 —— 都算
    "罢": _Morph(DOUBT_NEGATION, default=True),
    # 汰：淘汰 —— 都算
    "汰": _Morph(DOUBT_NEGATION, default=True),
    # 舍：句首的「舍A取B」、舍弃 / 舍去 / 割舍；宿舍 不是
    "舍": _Morph(DOUBT_SUBSTITUTION, prev_ok=frozenset("割"), next_ok=frozenset("弃去掉除用"), prev_non_cjk=True),
}
# 「除…外」配对用的「除」：与语素「除」同一套排除（除湿 / 除油 / 除尘 …整词、前字去除动词先算、后接材料先算），只是不排除
#「除以」——「除以下注明部位…外」「除以上所述…外」正是「除…外」（fix17，协调者裁定 6）
_DOUBT_CHU_PAIR = _Morph(DOUBT_NEGATION, default=True, object_first=True,
                         next_no_words=tuple(w for w in _DOUBT_MORPH["除"].next_no_words if w != "以"),
                         next_no_words_unless=_DOUBT_MORPH["除"].next_no_words_unless)
# 「除…外」「以…代」两半之间最多隔多少个字（紧凑流，同一合同句里）：fix16 不设上限会把「施工前除湿，……室外」这类远处的
#「外」配上（review17b R17B-03）；30 字盖得住「除以上所述的位于建筑物北侧山墙及楼梯间顶部区域的局部部位外」这类长从句
_DOUBT_PAIR_WINDOW = 30
_DOUBT_COMPOUNDS: tuple[tuple[str, str], ...] = tuple(
    [(w, DOUBT_CANCEL) for w in (
        "取消 取缔 省去 省掉 省略 省却 省除 省免 可省 去掉 去除 抹去 划去 勾去 裁去 砍去 舍去 拿去 消去 剪去 刨去 "
        "扣去 减去 空白 空置 留空 放空 置空 空着 空项 清空 终止 中止 注销 销毁 勾销 核销 吊销 销项 失效 失去 丢失 "
        "遗失 消失 遗漏 漏项 杜绝 谢绝 避免 规避 避用 回避 避开 搁置 打叉 画叉 划叉 叉去 裁减 核减 扣减 抵消 打消 "
        "勾消 移走 移去 移出 移开 退场 退出 退回 退还 卸下 取销 清运 冲销 抵销 跳过 "
        # fix15 补：驳回 / 推翻 / 落选 / 审减 / 调减 / 冲减 / 留白 / 为空 / 剥离 / 清退 …（review15a B 族 / 决定 2）
        "驳回 否决 推翻 撤回 收回 打回 淘汰 落选 出局 审减 调减 冲减 冲抵 扣回 抵扣 削减 缩减 剥离 割舍 舍弃 摒弃 "
        "放弃 抛弃 丢弃 弃置 留白 为空 暂空 空缺 落空 带走 清退 销号 拔掉 拔除 划出 划掉 划除 勾掉 涂掉 抹掉 拿掉 "
        "叫停 暂停 停建 停工 作罢 欠缺 缺乏 匮乏 豁免 减免 撤项 删项 撇去 撇掉 剔掉 "
        # 以下各词本身含否定语素（单字也会命中），列在这里只为让原因栏按「取消」类显示整词
        "作废 删除 删去 删掉 撤销 撤除 撤去 拆除 拆去 剔除 剔去 废除 废止 废弃 弃用 停用 停止 免除 略去").split()]
    # 反问 / 古白话的否定与「阙如」：词里没有否定语素，按整词认（方言 / 文言 / 反问整体是已知局限，这里只收常见的）
    + [(w, DOUBT_NEGATION) for w in (
        "何须 何必 何需 何用 何苦 难道 哪用 哪需 哪能 休要 休想 休得 阙如 何曾 何尝 何来 哪有 怎会 怎能 焉用 焉能 "
        "谁会 作甚 有必要吗 用得着吗 哪里需要 哪儿用得上 哪里用得着").split()]
    + [(w, DOUBT_SUBSTITUTION) for w in (
        "改用 改为 改成 改作 改换 改设 改铺 改贴 改选 改采 改做 改装 改填 改砌 改涂 改刷 改抹 改以 改按 改由 改到 "
        "改至 改在 改走 更改 修改 改动 变更 变为 变成 变换 改变 变动 转为 转用 转换 转而 转成 转作 调整 调换 调为 "
        "调成 调改 取代 代替 替代 替换 替用 顶替 更换 置换 换用 换成 换为 代以 "
        "变作 变改 更正 更替 更易 更动 修正 修订 订正 纠正 "
        # fix15 补（review15a C 族）
        "补位 递补 让位 更以 易之 代之 另选 另用").split()])
# 「更新 / 校正 / 优化 / 升级 / 降级 / 易」本身不是变动（岩棉板更新、移位校正），带上「为 / 成 / 作」才是；
# fix15 补「降为 / 置为（设置为除外）/ 翻新为 / 调剂为」
_DOUBT_CHANGE_TO = re.compile(r"(?:更新|校正|优化|升级|降级|易)(?:为|成|作)")
_DOUBT_CHANGE_TO2 = re.compile(r"(?<!设)置(?:为|成)|(?:降|翻新|调剂)(?:为|成|作)")
# 去除类动补「V去 / V走」：V 是去除 / 搬运类动词（铲去、凿去、揭去、运走、拿走、清走…）
_DOUBT_REMOVE = re.compile(f"[{_DOUBT_REMOVE_VERBS}][去走]")
# 「V出 / V下 / V开」只认取出、拆出、挖出、划出…与揭下、撕下、铲下、拔下…与挪开、拿开、移开（出 / 下 / 开太常见）
_DOUBT_REMOVE_OUT = re.compile(r"[取拆挖清抽拔搬运扒掏挪划剔]出|[揭撕铲取拆剥割摘撬敲凿锯刮扒抠剜拔卸]下|[挪拿移撤搬掀]开")
# 箭头表示「改成」：A→B（另按 Unicode 名称认所有箭头字符，见 _doubt_symbol_name）
_DOUBT_ARROWS = frozenset("→⇒➔⟶⟹➜➝➞⇨⇾⇢➡⮕↦⟼➙🡒")
_DOUBT_ARROW_RX = re.compile(r"[-=]+>")
# 撤项（造价口径）：甩项、减项、退项、扣项、砍项、缺项、负项…
_DOUBT_ITEM = re.compile(r"[甩减退扣砍销漏空删撤免核少落丢缺除取负消]项")
# 「漏 + 动词」是漏做；「渗漏 / 防漏 / 堵漏 …」里的「漏」是渗漏，后面接的是下一个词（防渗漏 | 加强）
_DOUBT_LEAK = re.compile(r"(?<![渗防堵滴泄检补查止])漏[做设铺贴装填刷涂抹砌用放加]")
# 「变 / 转」只在复合词里，或「变 / 转 + 材料名 / 字母 / 数字 / 指代」（变岩棉板为…、转聚苯板）时算替代
_DOUBT_BIAN = frozenset("变转")
_DOUBT_OBJECT_REF = frozenset("此该其原这那本")
# R4F-d fix16：「转 + 词典外材料」（转泡沫玻璃板、转石墨聚苯板）也是替代：转 后面一段汉字里有材料字尾（板 砖 浆 料 …）；
# 转角 / 转接 / 转弯 / 转动 / 周转 / 旋转 / 运转 … 不是
_DOUBT_ZHUAN_PREV_NO = frozenset("周旋运流逆扭回公自好急婉翻辗中")
_DOUBT_ZHUAN_NEXT_NO = frozenset("角接动向弯运化移交轴载速台椅盘门入出让发达账告述交身眼瞬折")
_DOUBT_MATERIAL_TAIL = frozenset("板砖浆料材棉毡膜漆布网砂石胶剂管瓦钢璃块土岩苯泡")
# 复合词后面紧接这些字时不是取消义：废弃物（建筑废弃物再生骨料）
_DOUBT_COMPOUND_NOT = {"废弃": ("物",)}
# 「除…外」的「外」后面接这些字时是外墙 / 外侧 / 外保温一类的词，不是收尾的「外」
_DOUBT_CHU_WAI_NEXT_NO = frozenset("墙侧保露围部面观形表层贴挂立置加窗门檐沿口边缘框套径界线包装运")
_DOUBT_EN = re.compile(
    r"(?<![a-z])(?:(?P<sub>replac[a-z]*|instead|substitut[a-z]*|swap[a-z]*|supersed[a-z]*|switch(?:ed|ing)"
    r"|chang(?:e|ed|es|ing))"
    r"|(?P<cancel>cancel[a-z]*|delet[a-z]*|remov[a-z]*|omit[a-z]*|skip[a-z]*|drop[a-z]*|eliminat[a-z]*"
    r"|abandon[a-z]*|discard[a-z]*|waive[a-z]*|void[a-z]*|scrap[a-z]*|obsolete|deprecat[a-z]*|withdr[a-z]*"
    r"|rescind[a-z]*|revok[a-z]*|struck|strike\s+out|cross(?:ed)?\s+out|out\s+of\s+scope|by\s+others"
    r"|omission[s]?|exclusion[s]?|notused|notuse|notapplicable|del(?![a-z0-9-]))"
    r"|(?P<neg>not|no(?!\s*\.\s*\d)|non[a-z]*|none|nil|null|nothing|without|w/o|w/out|except[a-z]*|exclud[a-z]*|excl"
    r"|never|neither|nor|avoid[a-z]*|cannot|[a-z]+n['’]t"
    r"|(?:do|does|did|is|are|was|were|ca|wo|should|could|would|have|has|had|need|must|ai)nt"
    r"|un(?:used|needed|necessary|installed|applied|available|approved|required|specified|selected|adopted|wanted"
    r"|suitable|acceptable)|inapplicable|missing|zero|nic|n\.i\.c\.?"
    r"|reject[a-z]*|declin[a-z]*|prohibit[a-z]*|forbid[a-z]*|ban(?:s|ned|ning)?|disallow[a-z]*|discontinu[a-z]*"
    r"|invalid[a-z]*|obsolet[a-z]*|ceas(?:e|ed|es|ing)|disus[a-z]*|nope|nix|nah))(?![a-z])")
# 字母间空格的英文（N O T  U S E D）：至少三个单字母以单个空格隔开，拼起来认
_DOUBT_SPACED = re.compile(r"(?<![a-z])[a-z](?: [a-z]){2,}(?![a-z])")
_DOUBT_SPACED_WORD = re.compile(r"not|none|unused|cancel|delet|remov|omit|void|excl|^no$|^na$")
_DOUBT_NA = re.compile(r"(?<![a-z0-9])n\s*[/.\\∕⁄‧·•・]?\s*a\.?(?![a-z0-9])")
# 拼音否定（已知局限之外的顺手补充，不计入合同范围）
_DOUBT_PINYIN = re.compile(r"(?<![a-z])(?:b[uùú]|w[eèé]i|m[eé]i)\s*"
                           r"(?:c[aǎá]i|y[oò]ng|zu[oò]|sh[eè]|y[oǒ]u|sh[iī])(?![a-z])"
                           r"|(?<![a-z])q[uǔ]\s*xi[aā]o(?![a-z])|(?<![a-z])zu[oò]\s*f[eè]i(?![a-z])")
# 零：带正负号的（±0.000、-0.050 里的 0、偏差 ±0）是标高 / 偏差，不算；不带符号的 0 / 0.00 / 0.000 既可能是
# 「无此项」（工程量 0）也可能是标高，拿不准按触发（宁可多看一眼），不按字面另设例外
_DOUBT_ZERO = re.compile(r"(?<![\d.])0+(?:\.0+)?(?!\d)(?!\.\d)")   # fix16：「工程量为0.」句号前的 0 也算
# 无此项符号：叉、空框、空心圆（〇 的形近写法）、禁止 / 空集类符号恒为触发（∅ 后接数字时是直径，不算）；删除线组合符恒为触发
_DOUBT_SYMBOLS = frozenset("¬≠∉∄⊘≢✗✘❌❎☒╳⊠⊗□☐▢⛔🗙🗴🗵🗶🗷⮽🚫🛇◻❏○◯⭕⬜◽▫⬚❐❑❒ㄨ⤫⤬⦸🞨")
_DOUBT_EMPTYSET = frozenset("∅øØ⌀")   # 空集 / 带斜线的 O：后接数字是直径（∅6、Ø8），单独出现是「无此项」
_DOUBT_STRIKE = frozenset("\u0334\u0335\u0336\u0337\u0338\u20d2\u20d3\u20e0\u20e5")
# 按 Unicode 名称认的叉 / 禁止类符号（罕见码位）
_DOUBT_SYMBOL_NAMES = ("SALTIRE", "X MARK", "BALLOT X", "CROSS MARK", "CIRCLED REVERSE SOLIDUS",
                       "CIRCLED DIVISION SLASH", "PROHIBITED", "NO ENTRY", "MULTIPLICATION X", "CIRCLED TIMES",
                       "SQUARED TIMES")
# 按字符名认箭头时只认「向右」的（替代 = A → B）；向上 / 向下 / 向左 / 双向 / 折向的箭头（标高↑、坡度↓、↳ 子项）不是替代
_DOUBT_ARROW_NOT = frozenset({"LEFT", "LEFTWARDS", "UPWARDS", "DOWNWARDS", "NORTH", "SOUTH"})
# 乘号 / 斜杠 / 破折号：规格、区间、单位、负数里的不算（600×1200、（1.2厚）×2层、W/(m·K)、XPS板/EPS板、
# -0.050、2%-3%）；其余位置（单独一格、句尾、冒号后、括号里）读作「无此项」。判定时跳过空白，用未遮蔽的原文。
_DOUBT_TIMES = frozenset("×⨯✕✖☓⨉乂")
_DOUBT_SLASHES = frozenset("/∕⁄\\／╱＼╲⧸⧹")
_DOUBT_DASHES = frozenset("-‐‑‒–—―⸺⸻﹘﹣−－─━ー⁃➖")
_DOUBT_INFIX = _DOUBT_TIMES | _DOUBT_SLASHES | _DOUBT_DASHES
_DOUBT_SIGNS = frozenset("±∓+＋﹢") | _DOUBT_DASHES
_DOUBT_OPENERS = frozenset("（([【〔「『〈《{“‘［｛〖〘")
# 紧凑流里丢掉的字：韩文填充字 / 盲文空格（「取（U+3164）消」）与间隔号（「取·消」）——都不是触发，只会把复合词拆开
_DOUBT_FILLERS = frozenset("\u3164\u115f\u1160\uffa0\u2800")
_DOUBT_O_SHAPES = frozenset("型形字圈环")      # O型圈 / O形 / O字：字母 O 是形状，不是零
_DOUBT_INTERPUNCTS = frozenset("·・‧∙•")
_DOUBT_FORWARD = ("以下 下列 如下 下述 下文 下面 下边 下表 下方 后述 后列 后文 后面 后边 后附 附后 见下 详下 如次 "
                  "接下来 见后 详后 下款 下条 下项 如后 随后 嗣后 以后各").split()
_DOUBT_BACK = ("上述 前述 以上 如上 上列 前列 上文 前文 上面 前面 上边 前边 前者 后者 同上 同前 同样 相同 所述 所列 "
               "所提 所指 提到 二者 两者 三者 〃 一并 上款 前款 上条 前条 上项 前项 "
               "前头 上头 全部 一律 统统 一概 悉数 整层 全层 所有 全数 通通 整个 全都").split()
_DOUBT_FORWARD_RX = re.compile(r"[下后次][一二两三四五六七八九十几数]?[项条句种段款层行个类节点道]")
_DOUBT_BACK_RX = re.compile(r"[前上][一二两三四五六七八九十几数]?[项条句种段款层行个类节点道]")
# 同一单元格 / 段落里另一层的文字（fix14 口径，作为下限保留）：明示的多字指代
_DOUBT_PEER_FORWARD = ("以下 下列 如下 下述 下文 下面 后述 后列 后文 后面 见下 详下 如后 随后 以后各").split()
_DOUBT_PEER_BACK = ("上述 前述 以上 如上 上列 前列 上文 前文 上面 前面 前者 同上").split()
_DOUBT_PEER_FORWARD_RX = re.compile(r"[下后次][一二两三四五六七八九十几数]?[项条句层款行]")
_DOUBT_PEER_BACK_RX = re.compile(r"[前上][一二两三四五六七八九十几数]?[项条句层款行]")
_DOUBT_BACK_CHARS = frozenset("该此其这那本它彼之均都皆亦也俱")
# 决定 1 的跨句指代（按语素认，用于所在格里另一句的触发）：前指 = 以下 / 下列 / 如下 / 其后 / 后续 … 或冒号 / 省略号 /
# 破折号结尾；回指 = 上述 / 前述 / 以上 … 与「该 此 其 这 那 本 它 彼 均 都 皆 亦 也 俱 各 诸」与「两层 / 各层 / 二者 …」
# fix17：方位语素补「往后 / 向下 / 向后 / 其下 / 下余」（前指）与「往前 / 向上 / 此前」（回指）（review17a R17A-03）
_DOUBT_HOST_FORWARD = tuple(_DOUBT_FORWARD) + tuple("其后 此后 之后 后续 往下 后附各 往后 向下 向后 其下 下余".split())
_DOUBT_HOST_BACK = tuple(_DOUBT_BACK) + tuple("这些 那些 这两 那两 连同 一起 同时 整个做法 全部做法 本做法 本层 "
                                              "往前 向上 此前".split())
_DOUBT_HOST_BACK_CHARS = _DOUBT_BACK_CHARS | frozenset("各诸")
_DOUBT_HOST_QUANT_RX = re.compile(r"[两二三四五六七八九十几多数各全诸每][层项种道者个样处部]")
# R4F-d fix17（协调者裁定 4）：量化回指语素不分前后——触发句里带「全 / 整体 / 整套 / 双层 / 各层 / 所有 / 其余 / 尽数 / 一应 /
# 总体 / 一概 / 统统 …」，同格 / 同段里在它前面、后面的层都算（「1)A。2)B。全取消」「1)C，其余各层取消。2)A」）。按语素认：
# 全 + 部 / 都 / 数 / 体 / 套 / 层 / 项 或直接接否定 / 取消类字；整 + 体 / 套 / 个 / 层；双 + 层 / 项 / 道；数词 / 各 / 诸 / 每 /
# 余 + 层 / 项 / 种 / 道 / 者 …；概 + 否定字；以及 所有 其余 余下 剩余 尽数 一应 总体 一概 统统 通通 悉数 一律 连带 一并 …
_DOUBT_QUANT_WORDS = tuple(("所有 其余 其他各 其它各 其他层 其它层 余下 剩余 尽数 一应 总体 一概 统统 通通 悉数 一律 连带 "
                            "一并 全数 全部 全都 全体 全然 整体 整套 整个 整层 全层 二者 两者 三者 诸层").split())
_DOUBT_QUANT_RX = re.compile(
    r"全[部都数体套层项]|全(?=[不未无没非免取删撤拆改换作废停省略弃去掉除禁])|整[体套个层项段片]|双[层项道]"
    r"|[两二三四五六七八九十几多数各诸每余][层项种道者个样处部套]|概(?=[不未无没非免取删撤拆改换作废停])")
# R4F-d fix18（决定 1「按语素规则而非整词清单」、协调者裁定 4，review18a R18A-05）：量化语素再按语素类补齐——
#   全：除「全部 / 全都 …」外，「全 + 8 字以内（不跨标点）+ 否定 / 取消 / 替代类字」都是全称（全已取消、全被删除、全予以取消、
#       全应改为、全用B替代、全以B代替、全盘取消、全面作废、全须取消）；安全 / 完全 / 健全 / 齐全 …（前字）与 全玻 / 全瓷 /
#       全钢 / 全粘 / 全封闭 / 全现浇 …（后字，材料与工艺名）、后面紧接放行术语（全不锈钢）不算；
#   整 + 幢 / 栋 / 面 / 块 / 樘；每（一）+ 层 / 项；逐 + 层 / 项；层层（每遍 / 每道 / 逐个 说的是本层自己的遍数，不算）；
#   统一 + 4 字以内接否定 / 取消 / 替代类字；一切 / 剩下 / 别的 / 另外的 / 余均 / 余者 / 其他的 / 其它的 / 其余的 / 全员；
#   一同 / 一齐 / 一起 只按位置认（见下）
_DOUBT_QUANT_WORDS = _DOUBT_QUANT_WORDS + tuple(("一切 逐层 层层 每一层 每一项 剩下 别的 另外的 余均 余者 "
                                                 "其他的 其它的 其余的 全员").split())
# 位置受限的指代 / 量化语素（fix18）：方位语素（以后 / 下部 / 上方 …，_DOUBT_FWD_MORPH / _DOUBT_BACK_MORPH 新认的部分）与
# 一同 / 一齐 / 一起：只在分句开头（句首、标点后）或后面紧接 的 / 各 / 所 / 均 / 都 / 全 / 层 / 项 / 道 / 之 / 诸 / 余 时才算指代——
#「终凝以后不得踩踏」「墙体下部不得空鼓」「与找平层一同施工」里的是时间 / 部位 / 方式，不指别的层
_DOUBT_CLAUSE_START = frozenset("，,。；;：:！？!?、（(")
_DOUBT_REF_FOLLOW = frozenset("的各所均都全层项道之诸余")
_DOUBT_TOGETHER_RX = re.compile(r"一同|一齐|一起")
# fix20：限定词、数词、量词与类别修饰分别解析，最终必须指向层/项。
# 每遍/每道等工艺次数仍不能跨层；逐个构造层则明确量化构造层。
_DOUBT_LAYER_CLASSIFIER = r"(?:一?[个种类项])?"
_DOUBT_LAYER_MODIFIER = r"(?:(?:构造|做法|材料|施工)的?)*"
_DOUBT_QUANT_RX2 = re.compile(
    rf"整[幢栋面块樘]|(?:每(?:一|{_DOUBT_LAYER_CLASSIFIER})|各{_DOUBT_LAYER_CLASSIFIER}|逐{_DOUBT_LAYER_CLASSIFIER})"
    rf"{_DOUBT_LAYER_MODIFIER}[层项]|层层"
    r"|(?:统|通)(?:共|统|通)(?=[^，,。；;！？!?：:、]{0,4}[不未无没取删撤拆改换作废停])")
_DOUBT_QUANT_ALL = re.compile(r"(?<![安完健齐周保成顾])全(?![玻瓷钢铝粘贴封现长高宽厚断包装自天频季程站景息新氟塑木实满埋焊熔"
                              r"螺牙丝铜铁石部都数体套层项然])(?=[^，,。；;！？!?：:、]{0,8}?"
                              r"[不未无没非免取删撤拆改换作废停省略弃去掉除禁替代甩减])")
_DOUBT_QUANT_TRIG = frozenset("不未无没非免取删撤拆改换作废停省略弃去掉除禁替代甩减")
# 「统一」（统一取消 / 统一不做 / 统一改为）：后面 4 字以内（不跨标点）接否定 / 取消 / 替代类字才算全称（「颜色统一，不得…」不算）
_DOUBT_QUANT_TONGYI = re.compile(r"统一(?=[^，,。；;！？!?：:、]{0,4}?[不未无没非免取删撤拆改换作废停省略弃去掉除禁替代甩减])")
# 单字回指「均」的非指代用法（形容词 / 名词）：均匀 / 均质 / 均布 / 均衡 / 均值 / 均等 / 均分 / 均摊 / 均温 / 均压 / 平均
_DOUBT_NOT_REF_RX = re.compile(r"均[匀质布衡值等分摊温压]|平均")
# 方位语素（决定 1：前指覆盖其后、回指覆盖其前；review18a R18A-06）：之 / 此 / 其 / 以 / 往 / 向 / 底 + 下 / 后、下 / 后 + 部 / 头 /
# 侧 / 方 / 面 / 边 / 首 / 端 / 段 / 文 / 述 / 列（之下、此下、以后、下部、下头、后头、底下、下侧、下端 …）是前指；之 / 此 / 其 /
# 以 / 往 / 向 + 上 / 前、上 / 前 + 同一类字（上部、上方、前部、上侧、前方、上端 …）与 先前 / 如上 / 一同 / 一齐 / 一起 / 一并 /
# 连同 是回指。在去掉序数（倒数 / 自下而上 / 第N层以下 …）之后的紧凑串上认
_DOUBT_FWD_MORPH = re.compile(r"[之此其以往向底](?:下|后)|(?:下|后)[部头侧方面边首端段文述列]"
                              r"|如下|见下|详下|随后|嗣后|以降")
_DOUBT_BACK_MORPH = re.compile(r"[之此其以往向](?:上|前)|(?:上|前)[部头侧方面边首端段文述列者]"
                               r"|先前|如上|一同|一齐|一起|一并|连同|同上|同前")


def _doubt_positional(rx: re.Pattern, s: str) -> str:
    """rx 在紧凑串 s 里第一个「位置合格」的命中（分句开头，或后面紧接 _DOUBT_REF_FOLLOW）；没有返回空串（fix18）。"""
    for m in rx.finditer(s):
        a, b = m.start(), m.end()
        if a == 0 or s[a - 1] in _DOUBT_CLAUSE_START or (b < len(s) and s[b] in _DOUBT_REF_FOLLOW):
            return m.group(0)
    return ""
# 补集语素（裁定 4，review18a R18A-02）：除…外（「外」后面接 墙 / 侧 / 保 / 露 / 围 … 是 外墙 / 外侧 这类词，不算）/ 以外 /
# 之外 / 其外、另一层 / 相邻层 / 任何一层、其他 / 其它 / 其余 / 另外 + 的 / 各 / 均 / 都 / 全 / 皆 / 一 / 层 / 项 / 道 / 做 / 构
# 或直接接否定类字、剩下 / 剩余 / 余下 / 余者 / 余均 / 别的——序数指别的层也把本层包括进去，方向不限
_DOUBT_COMP_RX = re.compile(r"除[^，,。；;：:！？!?]{0,16}?外(?![墙侧保露围部面观形表层贴挂立置加窗门檐沿口边缘框套径界线包装运])"
                            r"|[以之其]外|另一[层项道个]|相邻[层项道]|邻[层项道]|任何一?[层项]"
                            r"|(?:其[他它余]|另外)(?=[的各均都全皆一层项道做构])"
                            r"|(?:其[他它余]|另外)(?=[不未无没非免取删撤拆改换作废停省略弃去掉除禁替代甩减])"
                            r"|剩下|剩余|余下|余者|余均|别的")
# 句里已经有序数点了别的层时，补集读得更宽（「第2层保留，其余部分取消」「第2层照做，任何别的都不做」）：其他 / 其余 / 另外 /
# 别处 / 任何 / 余 + 任何字都算本层在补集里（没有序数时只认上面的严格写法，「其余部位不得渗漏」「任何部位不得渗漏」不连）
_DOUBT_COMP_LOOSE_RX = re.compile(r"其[他它余]|另外|别处|任何|余[下者均都皆]|剩")
# R4F-d fix16（决定 1：回指按语素认）：序数指层「第1层 / 第一层 / 第①层 / 第1、2层 / 第1~2层」与「首层 / 底层 / 顶层 /
# 最后一层 / 最上层」。数字能对上本层层号就只算本层，对不上的不算；「首层 / 底层 …」与本层层号认不出时取宽（各层都算）
_DOUBT_ORD_NUM = r"[0-9零一二两三四五六七八九十壹贰叁肆伍陆柒捌玖拾]+"
_DOUBT_ORD_RX = re.compile(rf"第\s*({_DOUBT_ORD_NUM}(?:\s*[、,，及和与或至到~～\-—－]\s*{_DOUBT_ORD_NUM})*)\s*层")
_DOUBT_ORD_WIDE_RX = re.compile(r"首层|底层|顶层"
                                r"|(?:前|后|首|末|头|尾|最后|最前)(?:两|二|三|四|五|几|[2-9])[层道项]")
# fix18（裁定 4：按层数换算，换算不了取宽）：位置序数——最上 / 最外 / 最先 / 头 / 首道 → 第 1 层；最下 / 最底 / 最里 / 最内 /
# 最后 / 末 / 尾 → 最后一层（层数认不出时取宽）。首层 / 底层 / 顶层 在建筑说明里常指楼层，仍取宽
_DOUBT_ORD_FIRST_RX = re.compile(r"最(?:上|外|先|前)(?:面|边|的)?一?[层道项]|头一?[层道遍项]|首道|首项")
_DOUBT_ORD_LAST_RX = re.compile(r"最(?:下|底|里|内|后)(?:面|边|的)?一?[层道项]|末一?[层道项]|尾一?[层道项]")
_DOUBT_ORD_RANGE = frozenset("至到~～-—－")
# R4F-d fix17（协调者裁定 4 / 10）：序数取一句里全部的「第N层 / 项 / 条 / 道」（第1层和第2层、第一及第二层、第②项）、不带「第」
# 的「N、M层 / N~M层」（1、2层取消、1~2层取消）、罗马数字「第Ⅰ层 / 第II层」；倒数 / 自下（倒数第二层、从下往上数第2层、
# 自下而上第二层）按层数换算，换算不了取宽。单独一个不带「第」的「2层」不当序数（「卷材2层」是层数、「2层卫生间」是楼层；
# 当序数会把说明文字的取宽收窄成一层，拿不准取宽），按 fix16 口径走点名 / 取宽。在折叠后的紧凑串上认（全角 / 圈码 ② / Ⅰ
# 已 NFKC 成 2 / i）
_DOUBT_ORD_SEP = r"[、,，及和与或至到~～\-—－]"
_DOUBT_ORD_UNIT = r"[层项条道]"
_DOUBT_ROMAN = r"(?:xii|xi|ix|x|viii|vii|vi|iv|v|iii|ii|i)"
# 所在格另一段的序数往前多看几个字：切层把「，1、2层取消」的「1、」当层号切走时，序数要连着它前面的字认
_DOUBT_ORD_LOOKBACK = 6
# R4F-d fix18（裁定 4，review18a R18A-07）：反方向计数补「由内向外 / 从里往外 / 从基层往外 / 下起 / 自下起 / 从底部算起 /
# 由底至顶 …」——做法表按惯例自面层往基层列（第 1 层是外露面），从内 / 从底 / 从基层数就是倒着数，按层数换算
# fix19：先识别方向与完整区间，再转换数字。不能让正序扫描截获倒数表达里的「第Ⅱ层」。
_DOUBT_ORD_VALUE = rf"(?:{_DOUBT_ORD_NUM}|{_DOUBT_ROMAN})"
_DOUBT_ORD_REVERSE = (
    r"(?:倒数|(?:从|自|由)?(?:下|底部|底层|底|基层|墙体|结构层|内|里)"
    r"(?:往|而|向|至|到)(?:上|外|顶|面)(?:数|算)?起?"
    r"|(?:从|自|由)?(?:下|底部|底层|底|基层|内|里)(?:面|边)?(?:数|算)起?"
    r"|(?:从|自|由)?(?:下|底部|底层|底|基层)(?:算起|起算|起))的?"
)
_DOUBT_ORD_BOTTOM_RX = re.compile(rf"{_DOUBT_ORD_REVERSE}第?({_DOUBT_ORD_VALUE}){_DOUBT_ORD_UNIT}?")
_DOUBT_ORD_INTERVAL_RX = re.compile(
    rf"(?P<direction>{_DOUBT_ORD_REVERSE})?第?(?P<start>{_DOUBT_ORD_VALUE})(?P<unit>{_DOUBT_ORD_UNIT})"
    rf"[至到~～\-—－](?P<end_direction>{_DOUBT_ORD_REVERSE})?第?(?P<end>{_DOUBT_ORD_VALUE}){_DOUBT_ORD_UNIT}"
)
_DOUBT_ORD_LIST_RX = re.compile(rf"第({_DOUBT_ORD_NUM}(?:{_DOUBT_ORD_SEP}第?{_DOUBT_ORD_NUM})*){_DOUBT_ORD_UNIT}")
_DOUBT_ORD_ROMAN_RX = re.compile(rf"第({_DOUBT_ROMAN}(?:{_DOUBT_ORD_SEP}第?{_DOUBT_ROMAN})*){_DOUBT_ORD_UNIT}")
_DOUBT_ORD_BARE_RX = re.compile(rf"(?<![0-9.第a-z])([0-9]{{1,2}}(?:{_DOUBT_ORD_SEP}[0-9]{{1,2}})+)层")
# fix18：不带「第」的中文数字区间（一至二层、一、二层）与相对序数（第N层以下 / 以上 / 起 / 之后 / 上方一层 / 的下一层 /
# 往上数第M层 …：所指随方向而定，换算不了，取宽）
_DOUBT_ORD_BARE_CN_RX = re.compile(rf"(?<![第一二两三四五六七八九十])([一二两三四五六七八九十]{{1,3}}(?:{_DOUBT_ORD_SEP}"
                                   rf"[一二两三四五六七八九十]{{1,3}})+)层")
_DOUBT_ORD_REL_RX = re.compile(
    rf"(?:第?(?:{_DOUBT_ORD_NUM}|{_DOUBT_ROMAN})(?:{_DOUBT_ORD_SEP}第?(?:{_DOUBT_ORD_NUM}|{_DOUBT_ROMAN}))*{_DOUBT_ORD_UNIT}"
    rf"|首层|底层|顶层|末层)的?"
    rf"(?:以下|以上|之下|之上|下面|上面|下方|上方|前面|后面|之前|之后|以后|以前|起|开始|往上|往下|向上|向下|上一|下一"
    rf"|上部|下部|以外|之外|外|前一|后一|相邻|上下|两侧|及以下|及以上|及其)")
_ROMAN_NUM = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12}
# 英文的跨句指代（both layers omitted / All above cancelled）
_DOUBT_EN_BACK_RX = re.compile(r"(?<![a-z])(?:both|all|above|these|those|said|aforementioned|entire|whole|each|every)"
                               r"(?![a-z])")
_DOUBT_EN_FORWARD_RX = re.compile(r"(?<![a-z])(?:below|following|as follows|next)(?![a-z])")
# 撇号的各种写法（don‘t / don´t / don`t / don′t / donʼt / DON＇T）一律折叠成 '（决定 2：常见英文否定的写法变体）
_DOUBT_APOSTROPHES = frozenset("‘’´`′ʼ＇‛ʹʻʽˈꞌ")
# 叉号紧挨厚度数字的勾选式标记（×60厚岩棉板、1)×60厚…、（1）×…、①×…）：叉号在「段首」时是「无此项」，不是规格；前面有
# 材料 / 数字（600×1200、卷材3厚×2层）才按规格写法判。fix17（协调者裁定 3）：段首 = 叉号前面（同一合同句里）去掉层号、中文
# 序号、字母序号、项目符号、「标签：」之后为空；或紧挨在一个层号后面（「（1）…（2）×5厚…」「1、…，2、×5厚…」：层号本身
# 就是段首）。兄弟层片段用所在格原文判，不再用 edge_left 一刀切（review17a R17A-01 / 02）
# 不带左括号的层号（1) 2、 a. 二、）前面不能是数字 / 字母 / 运算符 / 左括号：「（3+3）×1层」的「3）」是算式的一半，不是层号
# R4F-d fix18（协调者裁定 3「去掉层号、中文序号、项目符号、标签冒号后为空」，review18a R18A-04 / review18c R18C-04）：层号按
# 语素类认，不再是三四种写法的封闭表——阿拉伯数字（含多级编号 1.1、2.1.3）、罗马数字（Ⅰ–Ⅻ 折叠后的 i v x l c 串）、
# 中文数字 / 大写数字、天干地支、单个字母，可带括号（（） () 【】 [] 〔〕 〈〉 《》 「」 等）或后接 、 . ． ) ） : ：；
# 圈码 / 带括号或圈的数字、字母、汉字（① ⑴ ⒈ ⒜ Ⓐ ⓐ ❶ ➀ ㈠ ㊀）不折叠，直接当层号；「第N层 / 项 / 条 / 道 / 步」也是层号。
# 不带左括号的层号前面不能是数字 / 字母 / 运算符 / 左括号：「（3+3）×1层」的「3）」是算式的一半，不是层号
_DOUBT_HEAD_NUM = (r"(?:\d{1,3}(?:[.．\-－]\d{1,3})*|[ivxlc]{1,6}|[一二三四五六七八九十百零〇两]{1,4}|[壹贰叁肆伍陆柒捌玖拾]{1,3}"
                   r"|[甲乙丙丁戊己庚辛壬癸]|[子丑寅卯辰巳午未申酉戌亥]|[a-z])")
_DOUBT_CIRCLED = re.compile(r"[①-⒛⒜-⓿❶-➓㈠-㈩㊀-㊉]")
_DOUBT_HEAD_MARK = (rf"[（(\[【〔〈《「『［｛〖〘<]\s*(?:{_DOUBT_HEAD_NUM}|第\s*[0-9一二三四五六七八九十ivxlc]{{1,4}}\s*"
                    rf"[层项条道步])\s*[)）\]】〕〉》」』］｝〗〙>]"
                    rf"|(?<![a-z])(?:no\.?|№|#)\s*\d{{1,3}}\s*[)）.．、:：]?"
                    rf"|(?<![0-9a-z+\-*/×.．（(])(?:{_DOUBT_HEAD_NUM})\s*[)）.．、:：]"
                    rf"|[①-⒛⒜-⓿❶-➓㈠-㈩㊀-㊉]"
                    rf"|第\s*[0-9一二三四五六七八九十ivxlc]{{1,4}}\s*[层项条道步]\s*[:：、]?")
_DOUBT_HEAD_MARK_TAIL = re.compile(rf"(?:{_DOUBT_HEAD_MARK})\s*$")
# 项目符号：常见列表符号，另按 Unicode 类别认（符号 So / Sm、连接号 Pd 与列表点 · • ‧ ∙ ・ ※ * ‣ ⁃ ⁌ ⁍）；乘号本身不算
_DOUBT_HEAD_BULLETS = frozenset("●◆▲■◇△•▪◉★☆▶►▸‣※➢➣➤◎◈▫♦❖◦·*✦⦁⁃⁌⁍∙‧・○□◇◻◼▻▹➔→-–—~")
# 标签：冒号（不在两个数字之间）前面一直到句界 / 逗号 / 顿号的一段（可带括号、空格，40 字以内）；方括号里的标签
#（【保温层】、[保温]）没有冒号也算
_DOUBT_HEAD_LABEL_STOP = frozenset("。！？；;!?，,、\n\r")
_DOUBT_HEAD_BRACKETS = {"】": "【", "]": "[", "〕": "〔", "」": "「", "』": "『", "》": "《", "〉": "〈", "〗": "〖", "〙": "〘",
                        "）": "（", ")": "("}
_DOUBT_TERMINATORS = frozenset("。！？；;\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")
_DOUBT_PAIRS = {"（": "）", "(": ")", "[": "]", "【": "】", "〔": "〕", "「": "」", "『": "』", "〈": "〉",
                "《": "》", "{": "}", "“": "”", "‘": "’", "［": "］", "｛": "｝", "〖": "〗", "〘": "〙"}
_DOUBT_CLOSERS = frozenset(_DOUBT_PAIRS.values()) | {'"'}
_DOUBT_MASK = "￼"
# 繁体 / 日文新字体 / 异体 → 简体：覆盖触发清单、指代、放行术语与材料提及里出现的每个汉字（决定 2：清单里每个汉字的
# 繁体 / 异体写法自动补上）；trigger-inventory.md 逐字列出。西里尔 / 希腊形近字母 → 拉丁字母
_DOUBT_TRAD_PAIRS = (
    "巖岩擠挤溫温熱热捲卷塗涂滲渗結结膠胶噴喷漿浆細细劑剂氈毡瀝沥綸纶爐炉膩腻磚砖崗岗環环龍龙矽硅鈣钙礦矿鋁铝網网鋼钢絲丝離离層层護护墊垫桿杆腳脚塊块滿满黴霉鏽锈銹锈無无沒没別别棄弃廢废刪删罷罢換换締缔卻却劃划捨舍"
    "減减為为設设鋪铺舖铺貼贴選选採采裝装變变轉转調调著着項项終终註注銷销毀毁燬毁丟丢遺遗絕绝絶绝謝谢規规迴回囘回廻回開开擱搁畫画畵画動动場场塲场還还該该這这後后兩两両两樣样様样併并並并竝并條条見见詳详來来邊边辺边"
    "牆墙墻墙麵面爲为廃废変变転转旡无癈废缼缺畧略闕阙運运沖冲衝冲過过鏟铲剷铲鑿凿剝剥鋸锯脫脱擡抬優优級级訂订糾纠糺纠須须鬚须難难駁驳駮驳閉闭實实実实納纳計计種种類类個个箇个節节點点處处処处頭头體体數数統统號号簽签"
    "認认證证補补讓让譲让遞递剤剂嘗尝誰谁會会嗎吗裡里裏里兒儿決决審审縮缩暫暂帶带拋抛匱匮貧贫辭辞歸归帰归續续続续單单単单舉举擧举挙举擴扩拡扩隱隐隠隐應应応应對对対对氣气気气價价価价總总総总濟济済济臟脏臓脏檢检検检"
    "驗验験验險险険险藥药薬药發发発发權权権权蔵藏戰战戦战歩步毎每圖图図图鐵铁鉄铁壓压圧压抜拔準准譯译訣诀話话闊阔揮挥國国識识區区鑒鉴鑑鉴組组門门稱称針针業业冊册於于機机紡纺縫缝屬属礙碍輛辆車车樓楼蓋盖夾夹燒烧樹树"
    "纖纤維维靑青圍围範范顏颜觀观現现態态稅税標标寬宽長长寫写錄录據据舊旧壞坏適适陰阴陽阳陸陆隊队階阶際际隨随雜杂雙双電电靈灵頂顶順顺預预領领題题顯显風风飛飞養养餘余館馆馬马驅驱髒脏鬆松魚鱼鳥鸟麥麦黃黄齊齐齒齿龜龟"
    "與与專专東东嚴严喪丧豐丰臨临麗丽麼么義义烏乌樂乐喬乔習习鄉乡書书買买亂乱爭争虧亏雲云亞亚產产親亲億亿僅仅從从侖仑倉仓儀仪們们眾众夥伙傘伞偉伟傳传傷伤倫伦偽伪傭佣俠侠侶侣側侧債债傾倾償偿儲储兌兑黨党蘭兰關关興兴"
    "獸兽內内岡冈軍军農农馮冯凍冻淨净淒凄涼凉湊凑幾几鳳凤憑凭凱凯擊击劉刘則则剛刚創创劍剑劇剧勸劝辦办務务勵励勁劲勞劳勢势勳勋醫医華华協协賣卖盧卢鹵卤衛卫廠厂廳厅曆历歷历厲厉厭厌廁厕廂厢廈厦廚厨縣县參参敘叙疊叠葉叶"
    "歎叹籲吁嚇吓呂吕啟启吳吴嘸呒嘔呕員员嗆呛嗚呜詠咏響响啞哑嘩哗喲哟喚唤團团園园圓圆聖圣堅坚壇坛壩坝塢坞墳坟墜坠壟垄壘垒墾垦塹堑墮堕壯壮聲声殼壳壺壶備备復复夠够誇夸奪夺奮奋獎奖奧奥妝妆婦妇媽妈嫗妪婁娄嬌娇娛娱嬰婴"
    "嬸婶孫孙學学寧宁寶宝寵宠憲宪宮宫賓宾寢寝尋寻導导壽寿將将爾尔塵尘堯尧尷尴屍尸盡尽屜屉屆届屢屡嶼屿歲岁豈岂嶇岖島岛嶺岭嶽岳峽峡巒峦嶄崭鞏巩幣币帥帅師师幃帏帳帐簾帘幟帜幀帧幫帮莊庄慶庆廬庐庫库廟庙龐庞異异張张彌弥"
    "彎弯彈弹強强當当彙汇彥彦徹彻徑径禦御憶忆懷怀憐怜戀恋懇恳惡恶惱恼悅悦懸悬驚惊懼惧慘惨懲惩慚惭慣惯憤愤願愿懶懒戲戏戶户紮扎撲扑執执掃扫揚扬擾扰撫抚搶抢報报擔担擬拟攏拢揀拣擁拥攔拦擰拧撥拨擇择掛挂摯挚攣挛撓挠擋挡"
    "掙挣撈捞損损撿捡搗捣擄掳擲掷撣掸摻掺攬揽攙搀摟搂攪搅攜携攝摄擺摆搖摇擯摈攤摊撐撑攆撵擻擞攢攒敵敌斂敛齋斋鬥斗斬斩斷断時时曠旷晝昼晉晋曬晒曉晓暈晕暉晖曖暧術术樸朴殺杀楊杨傑杰極极構构樞枢棗枣槍枪楓枫櫃柜檸柠柵栅"
    "棧栈棟栋欄栏棲栖欒栾橋桥樁桩夢梦欖榄櫸榉檻槛橫横櫻樱櫥橱櫓橹簷檐歡欢歐欧殲歼殘残殯殡毆殴畢毕斃毙氫氢匯汇漢汉湯汤洶汹溝沟漚沤淪沦滄沧滬沪濘泞淚泪瀉泻潑泼澤泽潔洁灑洒窪洼淺浅澆浇濁浊測测瀏浏渾浑滸浒濃浓濤涛澇涝"
    "漣涟渦涡渙涣滌涤潤润澗涧漲涨澀涩澱淀淵渊漬渍瀆渎漸渐漁渔遊游灣湾濕湿潰溃濺溅滯滞濾滤濫滥灘滩瀟潇潛潜瀾澜瀨濑瀕濒滅灭燈灯災灾燦灿燉炖煉炼熾炽爍烁爛烂燭烛煙烟煩烦燴烩燙烫燼烬煥焕愛爱爺爷牘牍牽牵犧牺狀状猶犹狽狈"
    "獨独狹狭獅狮獄狱豬猪貓猫獻献瑪玛璽玺瓏珑瑣琐瓊琼甕瓮甦苏暢畅療疗瘡疮瘋疯癢痒癱瘫癮瘾皺皱盞盏鹽盐監监盜盗盤盘矚瞩睜睁瞞瞒鑽钻矯矫礬矾碼码硯砚礪砺礫砾礎础確确禮礼禍祸祿禄稟禀禿秃稈秆積积穢秽穩稳窮穷竊窃竅窍窯窑"
    "竄窜窩窝窺窥豎竖競竞筆笔筍笋箋笺籠笼箏筝籌筹簡简籃篮籬篱粵粤糧粮繫系緊紧紀纪約约紅红紋纹純纯紗纱綱纲縱纵紛纷紙纸紐纽線线練练紳绅織织絆绊紹绍經经綁绑絨绒給给絢绚絡络絞绞絹绢繼继績绩緒绪綾绫緞缎綺绮緋绯綽绰繩绳"
    "綿绵綢绸綜综綻绽綠绿綴缀緬缅纜缆緩缓縛缚纏缠繆缪繞绕繳缴羅罗罰罚羈羁翹翘聳耸恥耻聶聂聾聋職职聯联聰聪肅肃腸肠膚肤腎肾腫肿脹胀脅胁膽胆勝胜脈脉臍脐腦脑臉脸臘腊騰腾艦舰艙舱艱艰豔艳藝艺蕪芜蘆芦葦苇蒼苍蘋苹莖茎薦荐"
    "蕎荞薈荟薺荠蕩荡榮荣葷荤熒荧蔭荫蓮莲獲获瑩莹鶯莺蘿萝螢萤營营縈萦蕭萧薩萨蔥葱蔣蒋藍蓝薔蔷蘊蕴藪薮蘚藓虜虏慮虑虛虚蟲虫雖虽蝦虾蝕蚀蟻蚁螞蚂蠶蚕蠟蜡蠅蝇蟬蝉銜衔襯衬襖袄襪袜襲袭褲裤襤褴覓觅視视覽览覺觉觸触訊讯討讨"
    "訓训記记託讬訛讹訝讶訟讼訪访許许訴诉診诊評评詞词詢询試试詩诗誠诚誕诞詭诡誘诱語语誤误請请諸诸諾诺讀读課课諒谅談谈誼谊謀谋謊谎謂谓諧谐諭谕諱讳謎谜謙谦講讲謠谣謹谨譏讥譜谱譽誉讚赞貝贝貞贞負负貢贡財财責责賢贤敗败"
    "賬账貨货質质販贩貪贪貶贬購购貯贮貫贯貳贰賤贱貸贷貿贸費费賀贺賊贼賈贾賄贿資资賠赔賞赏賦赋賭赌賜赐賴赖賺赚賽赛贈赠贏赢贓赃贖赎趕赶趙赵趨趋躍跃跡迹踐践蹤踪軀躯軌轨軒轩軟软軸轴輕轻載载較较輔辅輩辈輝辉輪轮輯辑輸输"
    "輻辐轄辖轎轿轍辙辯辩辮辫遼辽達达遷迁邁迈進进遠远違违連连遲迟遜逊邏逻遙遥鄧邓鄰邻鬱郁鄭郑醜丑醬酱釀酿釋释釐厘釘钉釣钓鈍钝鈔钞鐘钟鈉钠鑰钥鈴铃鉛铅鉤钩銅铜銀银鋒锋鋤锄鋅锌錫锡錐锥錘锤錦锦錨锚錯错鍵键鍍镀鍋锅鎖锁"
    "鎮镇鏈链鏡镜鑄铸鑼锣閃闪問问闖闯閑闲間间閘闸閣阁閥阀閨闺聞闻閱阅闌阑闡阐陣阵陳陈陝陕隸隶雛雏霧雾靄霭靜静韋韦韌韧韓韩頁页頃顷頑顽顧顾頓顿頒颁頌颂顱颅頗颇頸颈頰颊頻频顆颗額额顛颠飄飘飢饥飯饭飲饮飼饲飽饱飾饰餃饺"
    "餅饼餓饿饅馒饒饶饑饥馭驭馳驰馴驯駐驻駕驾駛驶駝驼駭骇騎骑騙骗騷骚驕骄驛驿驟骤驢驴骯肮鬍胡鬧闹鮮鲜鳴鸣鴨鸭鵝鹅鶴鹤鷹鹰鹼碱齡龄幹干乾干弔吊摳抠銑铣篩筛洩泄銲焊鎔熔踫碰掽碰昇升陞升鉋刨拏拿覈核畱留飜翻"
    # fix16 补：清单新增的字（排除语境 / 序数 / 材料字尾）用 macOS ICU Hans-Hant 逐字核出的缺口
    "萬万稜棱緣缘說说輾辗錢钱韜韬複复")
# R4F-d fix18（决定 2「清单里每个汉字的繁体 / 异体自动补上」，review18c R18C-10）：用 macOS ICU Hant-Hans 对 U+3400–4DBF、
# U+4E00–9FFF、U+F900–FAFF 逐字求简体（评审产物 tools/hant2hans.js → icu-hant2hans.json），凡简体落在触发清单（全部 _DOUBT*
# 常量与放行名单）里某个字上、折叠表还没收的繁体 / 异体，由 tools/trad_check_fix18.py --emit 生成下面这一串（不手抄）；异体本身
# 也是清单字的（俱：回指「俱」，ICU 把它映到「具」）不折叠
_DOUBT_TRAD_PAIRS2 = ("瞭了跤交剋克尅克齣出彆别颳刮鬀剃剮剐賸剩叄叁髮发檯台臺台颱台嚮向曏向週周傢家嚐尝儘尽侷局跼局佈布噹当"
                      "搧扇纔才釦扣摺折罣挂撢掸闆板搆构欵款汙污溼湿籤签麤粗係系縴纤綫线緻致衊蔑錶表証证痠酸埰采鏨錾銼锉鎚锤顔颜"
                      # 冻结前终核补的 2 对（排除语境字：「均勻」的均不是回指、「換氣效菓」是整词）
                      "勻匀菓果")
_DOUBT_TRAD = {k: v for k, v in zip((_DOUBT_TRAD_PAIRS + _DOUBT_TRAD_PAIRS2)[0::2],
                                    (_DOUBT_TRAD_PAIRS + _DOUBT_TRAD_PAIRS2)[1::2]) if k != v}
_DOUBT_LOOKALIKE_PAIRS = ("АAВBЕEКKМMНHОOРPСCТTУYХXаaеeоoрpсcуyхxіiјjѕsЅSІIЈJ"
                          "ΑAΒBΕEΖZΗHΙIΚKΜMΝNΟOΡPΤTΥYΧXοoνvκkιiχx")
_DOUBT_LOOKALIKE = dict(zip(_DOUBT_LOOKALIKE_PAIRS[0::2], _DOUBT_LOOKALIKE_PAIRS[1::2]))


@dataclass(frozen=True)
class DoubtTrigger:
    kind: str           # 否定 / 替代 / 取消 / 无此项符号
    token: str          # 原文字面（原文的切片，原样）
    pos: int            # 原文第几个字（从 1 起）
    sentence: int       # 第几句（从 1 起）
    link: str = ""      # 同句 / 前指 / 回指 / 取宽（作用域不明） / 全文（无材料提及） / 同格 …；空 = 未判作用域

    def label(self) -> str:
        if self.token and all(ch in _DOUBT_STRIKE for ch in self.token):
            return "删除线 " + " ".join(f"U+{ord(ch):04X}" for ch in self.token)
        return self.token


@dataclass(frozen=True)
class DoubtVerdict:
    sentences: tuple[str, ...]
    mentions: tuple[str, ...]            # 命中的材料提及词（折叠后）
    mention_sentences: tuple[int, ...]   # 含提及的句序号（从 1 起）
    forward: tuple[int, ...]             # 含前指 / 以冒号、省略号、破折号结尾的句序号
    back: tuple[int, ...]                # 含回指的句序号
    triggers: tuple[DoubtTrigger, ...]   # 识别到的全部触发（遮蔽区间之外）
    gating: tuple[DoubtTrigger, ...]     # 作用域内的触发；本行原文里的每个触发都在作用域内（认不出就取宽）

    def describe(self, limit: int = 5) -> str:
        shown = "、".join(f"「{t.label()}」（{t.kind}，原文第{t.pos}字，第{t.sentence}句，{t.link}）"
                         for t in self.gating[:limit])
        more = f"等共 {len(self.gating)} 处" if len(self.gating) > limit else ""
        return f"{DOUBT_REASON}：{shown}{more}"


@dataclass(frozen=True)
class DoubtHostVerdict:
    """同一单元格 / 段落里、本行原文之外的触发（同句的兄弟层、名称 / 编号行与批注、层号外的说明文字、带指代的另一句）。
    pos 按所在格 / 段原文计。"""
    host_text: str
    where: str                           # 单元格 / 段落 / 行
    gating: tuple[DoubtTrigger, ...]

    def describe(self, limit: int = 5) -> str:
        shown = "、".join(f"「{t.label()}」（{t.kind}，所在{self.where}原文第{t.pos}字，第{t.sentence}句，{t.link}）"
                         for t in self.gating[:limit])
        more = f"等共 {len(self.gating)} 处" if len(self.gating) > limit else ""
        text = self.host_text if len(self.host_text) <= 160 else self.host_text[:160] + "…"
        return f"{DOUBT_REASON}：{shown}{more}；所在{self.where}原文：{text}"


def _doubt_char(ch: str) -> str:
    """单个原文字符 → 判定用字符串：NFKC、去格式字符与非删除线组合符、韩文填充字、形近字母、大小写、繁简折叠；
    各种撇号（‘ ’ ´ ` ′ ʼ ＇ …）折叠成 '（fix16）。"""
    if ch in _DOUBT_STRIKE:
        return ch
    if ch in _DOUBT_APOSTROPHES:
        return "'"
    if ch in _DOUBT_FILLERS:
        return ""
    out: list[str] = []
    for c in unicodedata.normalize("NFKC", ch):
        if c in _DOUBT_STRIKE:
            out.append(c)
            continue
        if c in _DOUBT_FILLERS:
            continue
        cat = unicodedata.category(c)
        if cat in ("Cf", "Mn", "Me", "Cs", "Co", "Cn") or (cat == "Cc" and not c.isspace()):
            continue
        out.extend(_DOUBT_TRAD.get(d, d) for d in _DOUBT_LOOKALIKE.get(c, c).casefold())
    return "".join(out)


def _doubt_fold(text: str) -> str:
    return "".join(_doubt_char(ch) for ch in text or "")


def _doubt_compact(text: str) -> str:
    """折叠后去空白、删除线覆盖符与间隔号的紧凑串（放行术语、指代判断用）。"""
    return "".join(c for c in _doubt_fold(text) if not c.isspace() and c not in _DOUBT_STRIKE
                   and c not in _DOUBT_INTERPUNCTS)


def _doubt_sentences(text: str) -> list[tuple[int, int]]:
    """按原文字符切句，返回 [start, end)。括号 / 引号未闭合时其后不再断句（取宽）；落单的右括号忽略。"""
    spans: list[tuple[int, int]] = []
    start, stack = 0, []
    for i, ch in enumerate(text):
        if ch == '"':
            if stack and stack[-1] == '"':
                stack.pop()
            else:
                stack.append('"')
        elif ch in _DOUBT_PAIRS:
            stack.append(_DOUBT_PAIRS[ch])
        elif ch in _DOUBT_CLOSERS:
            if stack and stack[-1] == ch:
                stack.pop()
        elif ch in _DOUBT_TERMINATORS and not stack:
            spans.append((start, i + 1))
            start = i + 1
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _doubt_mask_words() -> list[str]:
    """遮蔽词：本 yaml 里已有的材料名 / 层名词表与规则编码（放行名单另见 _doubt_safe_terms）。"""
    r = load_rules()
    words: list[str] = list((r.get("practice_lexicon") or {}).get("materials") or ())
    for ws in (r.get("granularity") or {}).values():
        words.extend(ws or ())
    for rule in r.get("consistency_rules") or ():
        for key in ("any", "text_any", "ctx_any", "any_none", "text_none", "ctx_none", "text_affirmative_none",
                    "expect", "forbid", "suggest"):
            words.extend(rule.get(key) or ())
    return sorted({_norm(str(w)) for w in words if str(w).strip()}, key=len, reverse=True)


def _doubt_masked(text: str) -> set[int]:
    """词典词在原文里（按现有规则同样的 NFKC 子串匹配）命中的原文字符下标。"""
    nf: list[str] = []
    src: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch):
            nf.append(c)
            src.append(i)
    hay = "".join(nf)
    masked: set[int] = set()
    for w in _doubt_mask_words():
        at = hay.find(w)
        while at != -1:
            masked.update(src[at:at + len(w)])
            at = hay.find(w, at + 1)
    return masked


@dataclass(frozen=True)
class _SafeTerm:
    term: str                          # 折叠繁简 / 全角、去空白后的术语
    after: tuple[str, ...] = ()        # 非空：术语后面（同一句里）必须紧接其中之一
    after_end: bool = False            # after 非空时：术语后面是句末 / 非汉字（标点、字母数字）也算
    after_materials: bool = False      # after 非空时：后面紧接 yaml 词典材料词也算
    not_after: tuple[str, ...] = ()    # 术语后面紧接其中之一时不是这个术语（「不燃」+ 气 = 不 + 燃气）
    # fix17（协调者裁定 1）：「无 + 名词」类术语被否定的名词；它在同一合同句里（术语之外）也出现 = 否定的正是本层主材，不放行
    # fix18（review18b R18B-01 / 03、review18c R18C-03）：只对「标注 / 谓语」用法生效——术语靠 after_end 放行（句末、括号收尾：
    # 「（无框）」「本层无釉」），或前面紧挨着本层 / 该层 / 此层 / 局部 / 全部 / 均 / 都 / 亦 … 这类主语 / 范围词（「本层无釉面砖」）；
    # 这时在整段原文（不限同一句，「…框格栅面层。本层无框」）里、除去所有放行术语出现处之后找被否定的名词。后接 after 词的固定
    # 写法（无框玻璃、无粘结预应力、无碱玻纤、无釉面砖规格 …）照放，同句重复同一术语、名词只在别的复合词里（框架、粘结长度、
    # 耐碱）都不再挡
    objects: tuple[str, ...] = ()
    # fix18（review18b R18B-04）：after 词前面允许隔几个汉字（「无釉防滑地砖」「无框钢化玻璃门」），0 = 必须紧接
    after_gap: int = 0


def _doubt_safe_terms() -> list[_SafeTerm]:
    """放行名单（quantity_rules.yaml doubt_safe_terms，决定 3）→ 折叠后的术语与后接条件，长的在前。"""
    out: list[_SafeTerm] = []
    for e in load_rules().get("doubt_safe_terms") or ():
        after = tuple(a for a in (_doubt_compact(str(x)) for x in (e.get("after") or ())) if a)
        not_after = tuple(a for a in (_doubt_compact(str(x)) for x in (e.get("not_after") or ())) if a)
        objects = tuple(a for a in (_doubt_compact(str(x)) for x in (e.get("objects") or ())) if a)
        gap = int(e.get("after_gap") or 0)
        for t in e.get("terms") or ():
            ft = _doubt_compact(str(t))
            if ft:
                out.append(_SafeTerm(ft, after, bool(e.get("after_end")), bool(e.get("after_materials")), not_after,
                                     objects, gap))
    return sorted(set(out), key=lambda x: (-len(x.term), x.term))


def _doubt_spaced(gap: str) -> bool:
    """两个字之间的原文是不是「断开」：有空白、间隔号、删除线覆盖符或韩文填充字（零宽字符不算断开）。"""
    return any(c.isspace() or c in _DOUBT_INTERPUNCTS or c in _DOUBT_STRIKE or c in _DOUBT_FILLERS for c in gap)


# 放行术语前面紧挨着的主语 / 范围词：「本层无釉面砖」「局部无粘结」「该门无框」——这时术语是谓语，按 objects 核被否定的名词
_DOUBT_SAFE_SUBJECT = re.compile(
    r"(?:(?:本|该|此|这一?|那一?)[层项处门窗墙段部块樘道件]|局部|部分|全部|均|都|皆|亦|也)"
    r"(?:已(?:经)?|现(?:在)?|仍(?:然)?|确实|目前)*$"
)


def _doubt_safe_predicate(stream: str, at: int, term: str) -> bool:
    """术语前的谓语位置，结合原文材料复现关系；不靠枚举项目/现场主语放过真正否定。"""
    prefix = re.split(r"[，,。；;：:！？!?（(]", stream[:at])[-1]
    if _DOUBT_SAFE_SUBJECT.search(prefix):
        return True
    if not prefix or _DOUBT_THICK_RX.search(prefix) or re.search(r"(?:采用|使用|铺贴|为|选用)$", prefix):
        return False
    # 「本工程已无釉面砖」的无后完整名词在前文出现，且术语位于新分句的主语后。
    # 「8厚无釉面砖」没有这个谓语位置；「无釉面砖，釉面砖…」也不会被未来文字反向污染。
    if term.startswith("无"):
        remainder = re.match(r"[a-z㐀-鿿]{1,24}", stream[at + 1:])
        if remainder:
            noun = remainder.group(0)
            before_clause = stream[:at - len(prefix)]
            return any(noun[:n] in before_clause for n in range(2, len(noun) + 1))
    return False


def _doubt_safe(stream: str, idx: list[int], text: str = "") -> set[int]:
    """放行术语在紧凑流里（整词）命中的原文字符下标：只遮蔽术语本身（决定 3）。R4F-d fix16 收紧「整词」：
      · 不跨合同句界（。！？；; 换行 …）：「本层：无⏎缝隙…」拼不成「无缝」；
      · 术语字间隔着空白 / 间隔号时（字间空格写法「不 少 于」「不 燃 型」），术语末字后面也必须断开（空白、非汉字或句末），
        否则是两个词凑上的（「无 机械」= 无 + 机械，「非 金属漆」= 非 + 金属漆）；
      · after 非空：术语后面必须紧接其中之一（after_end：句末 / 非汉字也行；after_materials：紧接词典材料词也行）——
        「无机」+ 房 / 械 / 组 不是材料属性；
      · not_after：后面紧接其中之一就不是这个术语（「不燃」+ 气 / 油 / 料，「除锈」+ 蚀，「无收缩」+ 缝）。
    R4F-d fix17（协调者裁定 1）：objects —— 被否定的名词在同一合同句里术语之外也出现就不放行（「门框（无框）」）；after 的术语
    后面紧接另一个放行术语也算（「无机不燃」）。"""
    safe: set[int] = set()
    if not stream:
        return safe
    sid = [0] * len(stream)
    if text:
        sent_of = [0] * len(text)
        for k, (a, b) in enumerate(_doubt_sentences(text)):
            for i in range(a, min(b, len(text))):
                sent_of[i] = k
        sid = [sent_of[i] if 0 <= i < len(text) else 0 for i in idx]
    materials: list[str] = []
    terms = _doubt_safe_terms()
    all_terms = sorted({t.term for t in terms}, key=len, reverse=True)
    # 紧凑流里所有放行术语（不论这一处能不能放行）的出现位置：objects 只在这些位置之外找被否定的名词
    term_mask = [False] * len(stream)
    for t in all_terms:
        at2 = stream.find(t)
        while at2 != -1:
            for p in range(at2, at2 + len(t)):
                term_mask[p] = True
            at2 = stream.find(t, at2 + 1)
    outside_all = "".join(c if not term_mask[p] else "\x00" for p, c in enumerate(stream))
    for st in terms:
        term = st.term
        at = stream.find(term)
        while at != -1:
            end = at + len(term)
            ok = sid[at] == sid[end - 1]
            nxt_same = end < len(stream) and sid[end] == sid[at]
            rest = stream[end:] if nxt_same else ""
            if ok and nxt_same:
                k = end
                while k < len(stream) and sid[k] == sid[at]:
                    k += 1
                rest = stream[end:k]
            if ok and text and any(_doubt_spaced(text[idx[p] + 1:idx[p + 1]]) for p in range(at, end - 1)):
                # 字间断开的写法：末字后面也要断开
                ok = not (nxt_same and not _doubt_spaced(text[idx[end - 1] + 1:idx[end]]) and _doubt_cjk(stream[end]))
            if ok and st.not_after and any(rest.startswith(w) for w in st.not_after):
                ok = False
            how = "plain"
            if ok and st.after:
                # fix17：后面紧接另一个放行术语也算（「无机不燃」，review17a R17A-06）
                good = any(rest.startswith(a) for a in st.after) or any(rest.startswith(t) for t in all_terms)
                if not good and st.after_gap:
                    # fix18：after 词前面隔着几个汉字（无釉防滑地砖、无框钢化玻璃门）
                    for g in range(1, st.after_gap + 1):
                        if g >= len(rest) or not _doubt_cjk(rest[g - 1]):
                            break
                        if any(rest.startswith(a, g) for a in st.after):
                            good = True
                            break
                if good:
                    how = "after"
                if not good and st.after_end:
                    good = not rest or not _doubt_cjk(rest[0])
                    how = "end" if good else how
                if not good and st.after_materials:
                    if not materials:
                        materials = [w for w in (_doubt_compact(x) for x in
                                                 ((load_rules().get("practice_lexicon") or {}).get("materials") or ()))
                                     if w]
                    good = any(rest.startswith(w) for w in materials)
                    how = "after" if good else how
                ok = good
            if ok and st.objects and (how == "end" or _doubt_safe_predicate(stream, at, term)):
                # fix18：标注 / 谓语用法——整段原文里（放行术语出现处之外）有被否定的名词 = 否定的正是本层主材，不放行
                if any(o in outside_all for o in st.objects):
                    ok = False
            if ok:
                safe.update(idx[at:end])
            at = stream.find(term, at + 1)
    return safe


def _doubt_shares(prefix: str, family: str) -> bool:
    p = _strip_z(str(prefix))
    return bool(family) and (family.startswith(p) if len(p) < 6 else p[:6] == family)


def _doubt_vocab(code: str) -> tuple[str, ...]:
    """该编码的材料提及词（只用于原因栏标「同句」）：同 6 位分部的规则词（expect 型规则的 text_any +
    text_affirmative_none）；没有专属词表的编码用做法材料词表。"""
    family = _strip_z(code)[:6]
    words: list[str] = []
    for rule in load_rules().get("consistency_rules") or ():
        expect = list(rule.get("expect") or ())
        forbid = list(rule.get("forbid") or ())
        if any(_doubt_shares(p, family) for p in expect):
            words.extend(rule.get("text_any") or ())
        if any(_doubt_shares(p, family) for p in expect + forbid):
            words.extend(rule.get("text_affirmative_none") or ())
    if not words:
        words = list((load_rules().get("practice_lexicon") or {}).get("materials") or ())
    return tuple(dict.fromkeys(f for f in ("".join(_doubt_fold(str(w)).split()) for w in words) if f))


def _doubt_colon_end(sentence: str) -> bool:
    body = sentence[:-1] if sentence and sentence[-1] in _DOUBT_TERMINATORS else sentence
    s = _doubt_fold(body).rstrip()
    while s and (s[-1] in _DOUBT_CLOSERS or s[-1] == "'" or s[-1].isspace()):
        s = s[:-1]
    return bool(s) and (s[-1] in (":", "∶", "⋯", "︙") or s.endswith("..") or s[-1] in _DOUBT_DASHES)


def _doubt_infix_ok(run: str, before: str, after: str, after_open: str) -> bool:
    """乘号 / 斜杠 / 破折号是不是规格、单位、区间、负数里的写法（是就不算触发）。"""
    if all(ch in _DOUBT_TIMES for ch in run):          # 600×1200、（1.2厚）×2层、×2
        return (before.isalnum() and after.isalnum()) or before.isdigit() or after.isdigit()
    if all(ch in _DOUBT_SLASHES for ch in run):        # XPS板/EPS板、kg/m³、W/(m·K)
        return before.isalnum() and (after.isalnum() or after_open.isalnum())
    if all(ch in _DOUBT_DASHES for ch in run):         # 50—60、-0.050、2%-3%、-5℃
        return (before.isalnum() and after.isalnum()) or after.isdigit()
    return before.isalnum() and after.isalnum()


def _doubt_head_bullet(ch: str) -> bool:
    if ch in _DOUBT_TIMES or ch.isalnum():
        return False
    if ch in _DOUBT_HEAD_BULLETS:
        return True
    return unicodedata.category(ch) in ("So", "Sm", "Pd")


def _doubt_head(prefix: str) -> bool:
    """叉号前面的原文（同一合同句里、到叉号为止）是不是「段首」（fix17 → fix18，协调者裁定 3）：从右往左去掉空白、项目符号、
    「标签：」与方括号标签，剩下空串 / 句界 / 逗号顿号，或者紧挨着一个层号（1) 1、 1. （1） ① 一、 （一） a) Ⅱ、 甲、 【2】
    1.1、 第1层 …）就是段首。"""
    # 圈码 / 带括号或圈的数字字母汉字（① ⑴ ❶ ➀ Ⓐ ㈠ ㊀）不做 NFKC 折叠——折成「1」「(1)」「b」就认不出它是层号了
    s = "".join(ch if _DOUBT_CIRCLED.fullmatch(ch) else _doubt_char(ch) for ch in prefix or "")
    s = "".join(c for c in s if c not in _DOUBT_FILLERS and c not in _DOUBT_STRIKE)
    for _round in range(32):
        s = s.rstrip()
        if not s or s[-1] in _DOUBT_TERMINATORS or s[-1] in "，,、;；":
            return True
        if _DOUBT_HEAD_MARK_TAIL.search(s):
            return True
        if _doubt_head_bullet(s[-1]):
            s = s[:-1]
            continue
        if s[-1] in ":：":
            k = len(s) - 1
            while k > 0 and s[k - 1] not in _DOUBT_HEAD_LABEL_STOP and len(s) - k <= 41:
                k -= 1
            if len(s) - k > 41:
                return False
            s = s[:k]
            continue
        if s[-1] in _DOUBT_HEAD_BRACKETS:
            op = s.rfind(_DOUBT_HEAD_BRACKETS[s[-1]])
            inner = s[op + 1:-1] if op >= 0 else ""
            if op >= 0 and 0 < len(inner) <= 20 and not any(c.isdigit() or c in "+-*/×=" for c in inner):
                s = s[:op]
                continue
        return False
    return False


def _doubt_head_marked(prefix: str) -> bool:
    """叉号 / x 前面紧挨着（隔空白）一个层号（No.1 x60厚、1) x60厚）：x 前面是数字也仍是段首叉号（fix18）。"""
    s = "".join(ch if _DOUBT_CIRCLED.fullmatch(ch) else _doubt_char(ch) for ch in prefix or "").rstrip()
    return bool(s) and bool(_DOUBT_HEAD_MARK_TAIL.search(s))


def _doubt_cjk(ch: str) -> bool:
    return bool(ch) and ("㐀" <= ch <= "鿿" or "豈" <= ch <= "﫿")


def _doubt_symbol_name(ch: str) -> str:
    """按 Unicode 名称认的罕见符号（显式字表之外的兜底）：向右的箭头 → 替代；叉 / 禁止类 → 无此项符号；都不是返回空串。
    只看符号类字符（Unicode 类别 S*）：字母（楔形文字的 CROSSING）、组合符、空白（NARROW NO-BREAK SPACE 里的
    「ARROW」）不算；名称按整词比，不按子串。"""
    if ch.isascii() or _doubt_cjk(ch) or ch in _DOUBT_INFIX or not unicodedata.category(ch).startswith("S"):
        return ""
    name = unicodedata.name(ch, "")
    if not name:
        return ""
    words = set(re.findall(r"[A-Z0-9]+", name))
    if words & {"ARROW", "ARROWS"} and "RIGHTWARDS" in words and not words & _DOUBT_ARROW_NOT:
        return DOUBT_SUBSTITUTION
    if any(re.search(rf"\b{re.escape(k)}\b", name) for k in _DOUBT_SYMBOL_NAMES):
        return DOUBT_SYMBOL
    return ""


_DOUBT_LAYER_OBJECT = re.compile(r"[一-鿿]{1,3}层")


def _doubt_morph_hit(m: _Morph, prev: str, nxt: str, rest: str, words: list[str], before: str = "") -> bool:
    if prev in m.prev_no and nxt not in m.prev_no_unless:
        return False
    if m.prev_no_words and any(before.endswith(w) for w in m.prev_no_words):
        return False                                  # 千差万别 不是「别 + 动词」（千万别铺 照算）
    if m.default and (prev in m.prev_ok or (m.clear_first and prev in _DOUBT_CLEAR_VERBS)):
        return True                                   # fix17：前字是去除 / 清除 / 替代类动词先算（铲除灰层、敲掉块料）
    if m.object_first and (any(rest.startswith(w) for w in words) or _DOUBT_LAYER_OBJECT.match(rest)):
        return True                                   # fix17：除 + 材料 / X层（除砂浆层、除灰土垫层、除灰层）
    if nxt in m.next_no and not any(rest.startswith(w) for w in m.next_no_unless) and (
            not m.next_no_ctx or not _doubt_cjk(prev) or prev in m.next_no_ctx):
        return False                                  # 换算 / 换填 不算；「换气凝胶毡」是换 + 材料，照算
    if any(rest.startswith(w) for w in m.next_no_words) and not any(rest.startswith(w)
                                                                    for w in m.next_no_words_unless):
        return False                                  # 整词排除：废弃物、换热器、除锈（除锈蚀 照算）
    if not _doubt_cjk(prev) and not _doubt_cjk(nxt):
        return True                                   # 单字成词：「（空）」「：废」「废」
    if prev in m.end_after and not _doubt_cjk(nxt):
        return True                                   # 句末：「此层空」「此层省」
    if prev in m.prev_ok or nxt in m.next_ok:
        return True
    if m.next_non_cjk and not _doubt_cjk(nxt):
        return True
    if m.prev_non_cjk and not _doubt_cjk(prev):
        return True
    if m.next_ascii and nxt.isascii() and nxt.isalnum():
        return True
    if m.next_material and any(rest.startswith(w) for w in words):
        return True
    return m.default


_DOUBT_CHU_WAI_PREV_NO = frozenset("室户场屋门窗墙洞内中")
# 兄弟层片段右侧紧挨着这些标点时，判乘号 / 斜杠 / 破折号用真实右邻（fix18）
_DOUBT_RIGHT_PUNCT = frozenset("，,；;。、：:！？!?）)]】〕」』〉》\n\r")


def _doubt_chu_span_pair(stream: str, j: int, close: int) -> bool:
    """R4F-d fix18（裁定 6 + 裁定 2「排除只认整词」，review18c R18C-07）：「除」后面紧接的是整词排除表里的词（除湿 / 除尘 /
    除草 / 除油 / 除灰 …），但它和收尾的「外」之间还隔着 1–8 个汉字（除湿区外、除草坪外、除灰色区域外、除尘器间外）时，
    那个「整词」并不是整词——说的是「除（湿区）外」，照「除…外」算；中间有标点（施工前除湿，室外 …）或「外」是室外 / 户外
    这类词的一半时不算。"""
    rest = stream[j + 1:]
    w = max((x for x in _DOUBT_CHU_PAIR.next_no_words if rest.startswith(x)), key=len, default="")
    if not w:
        return False
    span = stream[j + 1 + len(w):close]
    return (1 <= len(span) <= 8 and all(_doubt_cjk(ch) for ch in span)
            and stream[close - 1] not in _DOUBT_CHU_WAI_PREV_NO)


def _doubt_detect(text: str, edge_left: bool = False, edge_right: bool = False,
                  head_prefix: Optional[str] = None, right_char: Optional[str] = None) -> list[tuple[str, int, int]]:
    """原文 → 触发 [(类别, 首字下标, 末字下标)]（原文字符下标，从 0 起），按位置排。

    复合词、语素规则与语素化单字在未遮蔽的紧凑流上认（去空白、删除线覆盖符、间隔号、韩文填充字，折叠繁简），跨句也认
    （换行把「取消」拆成两行照样算）；触发的首字落在词典词或放行术语里才不算。无条件单字、英文、N/A、零与符号在
    逐字流上认。edge_left / edge_right：本段是从同一格里截出来的一段（层号前的说明文字等），这一侧紧挨着构造层的
    文字 —— 判乘号 / 斜杠 / 破折号时把那一侧当作有字（「有效—— 1)…」的破折号是连接号，不是「无此项」）。
    head_prefix（fix17）：本段在所在格原文里前面那一截（同一合同句里），判叉号是否在「段首」时接在本段前面一起看
    （兄弟层片段「2、×5厚…」前面是「1、…，2、」）；None = 本段就是一层的开头（本行原文），只看本段自己。
    right_char（fix18，裁定 3 / review18a R18A-03）：本段右侧在所在格原文里紧挨着的标点（，；。、： 括号 …）；给了就用它判
    乘号 / 斜杠 / 破折号的右邻（兄弟层末尾的「×，」「／，」「——，」是无此项标记），不再一律当作有字。"""
    text = text or ""
    chars: list[str] = []
    src: list[int] = []
    for i, ch in enumerate(text):
        for c in _doubt_char(ch):
            chars.append(c)
            src.append(i)
    comp = [(c, i) for c, i in zip(chars, src) if not c.isspace() and c not in _DOUBT_STRIKE
            and c not in _DOUBT_INTERPUNCTS]
    stream = "".join(c for c, _i in comp)
    idx = [i for _c, i in comp]
    masked = _doubt_masked(text) | _doubt_safe(stream, idx, text)
    next_of: dict[int, str] = {}       # 原文下标 → 紧凑流里的下一个字 / 上一个字
    prev_of: dict[int, str] = {}
    pos_of: dict[int, int] = {}        # 原文下标 → 紧凑流位置
    for j, (_c, i) in enumerate(comp):
        if i not in pos_of:
            pos_of[i] = j
        if j + 1 < len(comp) and i not in next_of:
            next_of[i] = comp[j + 1][0]
        if j > 0 and i not in prev_of:
            prev_of[i] = comp[j - 1][0]
    found: list[tuple[str, int, int]] = []
    covered: set[int] = set()

    def add(kind: str, first: int, last: int) -> None:
        found.append((kind, first, last))

    words = [w for w in (_doubt_fold(x) for x in _doubt_mask_words()) if w]
    # 紧凑流每个字所在的合同句（「除…外」「以…代」配对不跨句；逗号、冒号、括号内不切）
    sent_of = [0] * len(text)
    for k, (a, b) in enumerate(_doubt_sentences(text)):
        for i in range(a, b):
            sent_of[i] = k
    sid = [sent_of[i] for i in idx]
    hits: list[tuple[int, int, str]] = []
    for word, kind in _DOUBT_COMPOUNDS:
        at = stream.find(word)
        while at != -1:
            if not any(stream.startswith(w, at + len(word)) for w in _DOUBT_COMPOUND_NOT.get(word, ())):
                hits.append((at, at + len(word) - 1, kind))
            at = stream.find(word, at + 1)
    for rx, kind in ((_DOUBT_LEAK, DOUBT_CANCEL), (_DOUBT_REMOVE, DOUBT_CANCEL), (_DOUBT_REMOVE_OUT, DOUBT_CANCEL),
                     (_DOUBT_ITEM, DOUBT_CANCEL), (_DOUBT_CHANGE_TO, DOUBT_SUBSTITUTION),
                     (_DOUBT_CHANGE_TO2, DOUBT_SUBSTITUTION)):
        hits += [(m.start(), m.end() - 1, kind) for m in rx.finditer(stream)]
    in_word = {k for a, b, _kind in hits for k in range(a, b + 1)}     # 已由复合词 / 构词模式认出的字（转为、转用 …）
    for j, c in enumerate(stream):
        if c not in _DOUBT_BIAN or j + 1 >= len(stream):
            continue
        nxt = stream[j + 1]
        if (nxt.isascii() and nxt.isalnum() or nxt in _DOUBT_OBJECT_REF
                or any(stream.startswith(w, j + 1) for w in words)):
            hits.append((j, j, DOUBT_SUBSTITUTION))
        elif (c == "转" and j not in in_word and nxt not in _DOUBT_ZHUAN_NEXT_NO
              and (j == 0 or stream[j - 1] not in _DOUBT_ZHUAN_PREV_NO)):
            # fix16：转 + 词典外材料（转泡沫玻璃板）：后面同一句里的一段汉字（8 字以内）带材料字尾
            k = j + 1
            while k < len(stream) and k - j <= 8 and sid[k] == sid[j] and _doubt_cjk(stream[k]):
                if k > j + 1 and stream[k] in _DOUBT_MATERIAL_TAIL:
                    hits.append((j, j, DOUBT_SUBSTITUTION))
                    break
                k += 1
    # 「除…外」（除本层外均施工）与「以B代A」：在同一合同句里找另一半（fix16：逗号、冒号、括号内不切句）。fix17（协调者
    # 裁定 6）：配对有窗口上限（两半之间不超过 _DOUBT_PAIR_WINDOW 个字），并沿用「除」的语素排除——除湿 / 除油 / 除尘
    #（整词、前面不是去除动词、后面不是材料）不是「除…外」的「除」，「施工前除湿，室外…」不配对；「除」后面的「外」得是
    # 收尾的「外」，外墙 / 外侧 / 外保温 不是
    for j, c in enumerate(stream):
        if c == "除":
            k = j + 1
            close = None
            while k < len(stream) and sid[k] == sid[j] and k - j - 1 <= _DOUBT_PAIR_WINDOW:
                if stream[k] == "外" and (k + 1 >= len(stream) or stream[k + 1] not in _DOUBT_CHU_WAI_NEXT_NO):
                    close = k
                    break
                k += 1
            if close is None:
                continue
            if (_doubt_morph_hit(_DOUBT_CHU_PAIR, stream[j - 1] if j > 0 else "",
                                 stream[j + 1] if j + 1 < len(stream) else "", stream[j + 1:], words,
                                 stream[max(0, j - 6):j])
                    or _doubt_chu_span_pair(stream, j, close)):
                hits.append((j, j, DOUBT_NEGATION))
        elif c == "代":
            k = j - 1
            while k >= 0 and sid[k] == sid[j] and j - k - 1 <= _DOUBT_PAIR_WINDOW:
                if stream[k] == "以" and (j + 1 >= len(stream) or stream[j + 1] not in "号表码理价购办收谢际言位"):
                    hits.append((j, j, DOUBT_SUBSTITUTION))
                    break
                k -= 1
    seen: set[tuple[int, int]] = set()
    for a, b, kind in hits:
        first, last = idx[a], idx[b]
        if first in masked or (first, last) in seen:
            continue
        seen.add((first, last))
        add(kind, first, last)
        covered.update(range(first, last + 1))
    for j, c in enumerate(chars):
        i = src[j]
        if c in _DOUBT_STRIKE:
            add(DOUBT_SYMBOL, i, i)
        elif i in covered or i in masked:
            continue
        elif c in _DOUBT_NEG_CHARS:
            add(DOUBT_NEGATION, i, i)
        elif c in _DOUBT_SUB_CHARS or c == _DOUBT_GAI:
            add(DOUBT_SUBSTITUTION, i, i)
        elif c in _DOUBT_MORPH:
            p = pos_of.get(i, -1)
            rest = stream[p + 1:] if p >= 0 else ""
            if _doubt_morph_hit(_DOUBT_MORPH[c], prev_of.get(i, ""), next_of.get(i, ""), rest, words,
                                stream[max(0, p - 6):p] if p >= 0 else ""):
                add(_DOUBT_MORPH[c].kind, i, i)
        elif c in _DOUBT_ZERO_CHARS or c in _DOUBT_SYMBOLS:
            add(DOUBT_SYMBOL, i, i)
        elif c in _DOUBT_EMPTYSET:
            if not (next_of.get(i) or "").isdigit():
                add(DOUBT_SYMBOL, i, i)
        elif c in _DOUBT_ARROWS:
            add(DOUBT_SUBSTITUTION, i, i)
        else:
            kind = _doubt_symbol_name(c)
            if kind:
                add(kind, i, i)
    ws = "".join(_DOUBT_MASK if i in masked else c for c, i in zip(chars, src))
    for m in _DOUBT_EN.finditer(ws):
        kind = DOUBT_SUBSTITUTION if m.group("sub") else DOUBT_CANCEL if m.group("cancel") else DOUBT_NEGATION
        add(kind, src[m.start()], src[m.end() - 1])
    # 字母之间的连字符去掉再认（un-used、can-not）
    hy = [(c, k) for k, c in enumerate(ws) if not (c in "-‐‑" and 0 < k < len(ws) - 1 and ws[k - 1].isalpha()
                                                   and ws[k + 1].isalpha())]
    if len(hy) != len(ws):
        hs = "".join(c for c, _k in hy)
        for m in _DOUBT_EN.finditer(hs):
            span = ws[hy[m.start()][1]:hy[m.end() - 1][1] + 1]
            if "-" in span or "‐" in span or "‑" in span:
                kind = DOUBT_SUBSTITUTION if m.group("sub") else DOUBT_CANCEL if m.group("cancel") else DOUBT_NEGATION
                add(kind, src[hy[m.start()][1]], src[hy[m.end() - 1][1]])
    for m in _DOUBT_SPACED.finditer(ws):
        word = m.group(0).replace(" ", "")
        if _DOUBT_SPACED_WORD.search(word):
            add(DOUBT_NEGATION, src[m.start()], src[m.end() - 1])
    for m in _DOUBT_NA.finditer(ws):
        add(DOUBT_SYMBOL, src[m.start()], src[m.end() - 1])
    for m in _DOUBT_ARROW_RX.finditer(ws):
        add(DOUBT_SUBSTITUTION, src[m.start()], src[m.end() - 1])
    for m in _DOUBT_PINYIN.finditer(ws):
        add(DOUBT_NEGATION, src[m.start()], src[m.end() - 1])
    plain = "".join(chars)

    def neighbour(j: int, step: int, skip: frozenset = frozenset()) -> str:
        while 0 <= j < len(plain) and (plain[j].isspace() or plain[j] in _DOUBT_STRIKE or plain[j] in skip):
            j += step
        if 0 <= j < len(plain):
            return plain[j]
        if step > 0 and edge_right and right_char is not None:
            return right_char
        return "层" if (step < 0 and edge_left) or (step > 0 and edge_right) else ""

    def at_head(i: int) -> bool:
        """原文第 i 字（叉号 / 单独的 x）是不是在段首：本行原文看本段自己（edge_left 的说明文字片段不算段首）；所在格里的
        片段接上它前面那一截原文一起看（fix17，协调者裁定 3）。"""
        if head_prefix is None:
            return not edge_left and _doubt_head(text[:i])
        return _doubt_head(head_prefix + text[:i])

    for m in _DOUBT_ZERO.finditer(ws):
        if neighbour(m.start() - 1, -1) in _DOUBT_SIGNS:
            continue                    # ±0.000、-0.050、偏差 ±0：带正负号的是标高 / 偏差，不是「无此项」
        add(DOUBT_SYMBOL, src[m.start()], src[m.end() - 1])
    j = 0
    while j < len(plain):
        c = plain[j]
        if c in _DOUBT_INFIX:
            e = j
            while e + 1 < len(plain) and plain[e + 1] in _DOUBT_INFIX:
                e += 1
            run = plain[j:e + 1]
            before, after = neighbour(j - 1, -1), neighbour(e + 1, 1)
            after_open = neighbour(e + 1, 1, _DOUBT_OPENERS)
            if src[j] not in masked:
                if all(ch in _DOUBT_TIMES for ch in run) and at_head(src[j]):
                    # fix16：叉号前面只有层号或什么都没有（×60厚岩棉板、1)×60厚…）：勾选式「无此项」标记，不是规格「×2」
                    add(DOUBT_SYMBOL, src[j], src[e])
                elif not _doubt_infix_ok(run, before, after, after_open):
                    add(DOUBT_SYMBOL, src[j], src[e])
            j = e + 1
            continue
        if c in "xo" and src[j] not in masked:
            before, after = neighbour(j - 1, -1), neighbour(j + 1, 1)
            r = src[j] - 1
            while r >= 0 and text[r].isspace():
                r -= 1
            if r >= 0 and _DOUBT_CIRCLED.fullmatch(text[r]):
                before = ""             # fix18：圈码层号（Ⓑ ⓑ ⑵ ㊁）NFKC 后是字母 / 数字，紧挨着的 x 仍是段首叉号
            lone = not re.fullmatch(r"[a-z0-9]", before) and not re.fullmatch(r"[a-z0-9]", after)
            # fix16：行首 / 层号后的单独 x 紧挨厚度数字（x60厚、X 60厚）同样是叉号标记
            lead_x = (c == "x" and after.isdigit() and at_head(src[j])
                      and (not re.fullmatch(r"[a-z0-9]", before) or _doubt_head_marked(text[:src[j]])))
            if lone or lead_x:
                # 单独的 x 是叉；单独的 o（含全角 Ｏ、形近字母）当零 —— 「共O项」「数量Ｏ」；「O型圈 / O形」除外
                if c == "x" or after not in _DOUBT_O_SHAPES:
                    add(DOUBT_SYMBOL, src[j], src[j])
        j += 1
    found.sort(key=lambda t: (t[1], -(t[2] - t[1])))
    out: list[tuple[str, int, int]] = []
    keyset: set[tuple[str, int, int]] = set()
    for t in found:
        if t not in keyset:
            keyset.add(t)
            out.append(t)
    return out


def _doubt_refs(sentence_compact: str, raw_sentence: str) -> tuple[bool, bool]:
    """(前指, 回指)：触发句里的指代词 / 指代模式 / 冒号结尾（本行原文里的链接标签用，fix14 口径）。"""
    fwd = (any(w in sentence_compact for w in _DOUBT_FORWARD) or bool(_DOUBT_FORWARD_RX.search(sentence_compact))
           or _doubt_colon_end(raw_sentence))
    back = (any(w in sentence_compact for w in _DOUBT_BACK) or bool(_DOUBT_BACK_RX.search(sentence_compact))
            or any(c in _DOUBT_BACK_CHARS for c in sentence_compact))
    return fwd, back


def _doubt_quant(raw_sentence: str) -> str:
    """量化回指语素（fix17 → fix18，协调者裁定 4：按语素认、不分前后）：句里的「全 / 整体 / 双层 / 各层 / 所有 / 其余 / 尽数 /
    全已 / 全被 / 整幢 / 每一层 / 逐层 / 层层 / 一切 …」；没有返回空串。序数指层（第二层 / 第1、2层 / 倒数第二层 …）先去掉，
    不当「二层」数量。"""
    s = _doubt_ordinal_strip(_doubt_compact(raw_sentence))
    return _doubt_quant_c(s)


def _doubt_quant_c(s: str) -> str:
    """_doubt_quant 的紧凑串版本（s 已去掉序数）。「全」接放行术语（全不锈钢）不算全称。"""
    hit = next((w for w in _DOUBT_QUANT_WORDS if w in s), "")
    if hit:
        return hit
    for rx in (_DOUBT_QUANT_RX, _DOUBT_QUANT_RX2):
        for m in rx.finditer(s):
            if m.group(0) == "全" and _doubt_after_safe(s, m.end()):
                continue
            return m.group(0)
    m = _DOUBT_QUANT_TONGYI.search(s)
    if m:
        return m.group(0)
    hit = _doubt_positional(_DOUBT_TOGETHER_RX, s)
    if hit:
        return hit
    for m in _DOUBT_QUANT_ALL.finditer(s):
        if _doubt_after_safe(s, m.end()):
            continue
        k = m.end()
        while k < len(s) and s[k] not in _DOUBT_QUANT_TRIG:
            k += 1
        return s[m.start():k + 1]
    return ""


def _doubt_after_safe(s: str, at: int) -> bool:
    """紧凑串 s 从 at 起是不是一个放行术语（全不锈钢、全无机 …：全 修饰的是材料名，不是全称否定）。"""
    return any(s.startswith(t.term, at) for t in _doubt_safe_terms())


def _doubt_complement(raw_sentence: str) -> str:
    """补集语素（fix18，裁定 4 / review18a R18A-02）：除…外 / 以外 / 之外 / 其余的 / 剩下的 / 别的 / 另外的 …；没有返回空串。
    在去掉序数之后的紧凑串上认（「除第1层外」→「除、外」）。"""
    m = _DOUBT_COMP_RX.search(_doubt_ordinal_strip(_doubt_compact(raw_sentence)))
    return m.group(0) if m else ""


def _doubt_host_refs(raw_sentence: str) -> tuple[str, str]:
    """决定 1 的跨句指代（所在格里另一句的触发）：(前指词, 回指词)，按语素认；没有的一项为空串。
    fix18：方位语素按语素类认（_DOUBT_FWD_MORPH / _DOUBT_BACK_MORPH：之下 / 此下 / 下部 / 下头 / 后头 / 以后 / 底下 / 下侧 …
    与 上部 / 上方 / 前部 / 上侧 / 前方 / 先前 / 一同 / 一齐 …），在去掉序数之后的紧凑串上认。"""
    s = _doubt_compact(raw_sentence)
    sq = _doubt_ordinal_strip(s)          # fix16：「第二层」是序数指层（另判），不是「两层 / 二层」这类数量指代
    fwd = next((w for w in _DOUBT_HOST_FORWARD if w in sq), "")
    if not fwd:
        m = _DOUBT_FORWARD_RX.search(sq)
        fwd = m.group(0) if m else (_doubt_positional(_DOUBT_FWD_MORPH, sq)
                                    or ("冒号结尾" if _doubt_colon_end(raw_sentence) else ""))
    if not fwd:
        m = _DOUBT_EN_FORWARD_RX.search(_doubt_fold(raw_sentence))
        fwd = m.group(0) if m else ""
    back = next((w for w in _DOUBT_HOST_BACK if w in sq), "")
    if not back:
        m = _DOUBT_BACK_RX.search(sq) or _DOUBT_HOST_QUANT_RX.search(sq)
        back = m.group(0) if m else _doubt_positional(_DOUBT_BACK_MORPH, sq)
        # fix18：单字回指里去掉「均匀 / 均质 / 平均 …」的「均」（形容词，不是「都」）
        back = back or next((c for c in _DOUBT_NOT_REF_RX.sub("", sq) if c in _DOUBT_HOST_BACK_CHARS), "")
    if not back:
        m = _DOUBT_EN_BACK_RX.search(_doubt_fold(raw_sentence))
        back = m.group(0) if m else ""
    return fwd, back


def doubt_scan(code: str, text: str) -> DoubtVerdict:
    """逐句列出触发、提及与指代（不判去向）。只看本行原文；同格 / 段的其余文字由 doubt_host 另看。"""
    text = text or ""
    spans = _doubt_sentences(text)
    sent_of = [0] * len(text)
    for k, (a, b) in enumerate(spans):
        for i in range(a, b):
            sent_of[i] = k
    n = len(spans)
    found = [DoubtTrigger(kind, text[a:b + 1], a + 1, sent_of[a] + 1) for kind, a, b in _doubt_detect(text)]
    plain_sent = ["".join(c for c in _doubt_fold(text[a:b]) if not c.isspace() and c not in _DOUBT_STRIKE)
                  for a, b in spans]
    vocab = _doubt_vocab(code)
    mention_sents = [k for k in range(n) if any(w in plain_sent[k] for w in vocab)]
    mentions = tuple(w for w in vocab if any(w in plain_sent[k] for k in mention_sents))
    refs = [_doubt_refs(plain_sent[k], text[spans[k][0]:spans[k][1]]) for k in range(n)]
    forward = [k for k in range(n) if refs[k][0]]
    back = [k for k in range(n) if refs[k][1]]
    gating: list[DoubtTrigger] = []
    for t in found:
        k = t.sentence - 1
        if not mention_sents:
            link = "全文（无材料提及）"
        elif k in mention_sents:
            link = "同句"
        elif k in forward and any(m > k for m in mention_sents):
            link = "前指"
        elif k in back and any(m < k for m in mention_sents):
            link = "回指"
        else:
            # 本层自己的原文里认不出材料、也认不出指向材料句的指代（零形回指、词表外材料名、泛指名词、未列指代）
            # → 拿不准，取宽：照样算作用域内（宁可多让人看一眼，也不能漏判）
            link = DOUBT_WIDE
        gating.append(DoubtTrigger(t.kind, t.token, t.pos, t.sentence, link))
    return DoubtVerdict(tuple(text[a:b] for a, b in spans), mentions, tuple(k + 1 for k in mention_sents),
                        tuple(k + 1 for k in forward), tuple(k + 1 for k in back), tuple(found), tuple(gating))


def doubt_gate(code: str, text: str) -> Optional[DoubtVerdict]:
    """即将成为正式项的一行：本行原文（来自另一单元格的部分已由调用方换成空白）里有触发 → 返回判定（调用方降为
    待核）；没有 → None（照旧出正式项）。"""
    v = doubt_scan(code, text)
    return v if v.gating else None


def _doubt_peer_ref(region: str, after: bool) -> str:
    """另一层的文字里指向本层的明示多字指代（fix14 口径）：在本层之后找回指、之前找前指；没有返回空串。"""
    s = "".join(c for c in _doubt_fold(region) if not c.isspace() and c not in _DOUBT_STRIKE)
    words, rx = (_DOUBT_PEER_BACK, _DOUBT_PEER_BACK_RX) if after else (_DOUBT_PEER_FORWARD, _DOUBT_PEER_FORWARD_RX)
    hit = next((w for w in words if w in s), "")
    if not hit:
        m = rx.search(s)
        hit = m.group(0) if m else ""
    return hit


_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
           "壹": 1, "贰": 2, "叁": 3, "肆": 4, "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9}


def _doubt_num(s: str) -> Optional[int]:
    """「12」「一」「十二」「二十」→ 整数；认不出 → None。"""
    if s.isdecimal():
        try:
            return int(s)
        except ValueError:
            return None
    if s in ("十", "拾"):
        return 10
    s = s.replace("拾", "十")
    if len(s) == 1:
        return _CN_NUM.get(s)
    if len(s) == 2 and s[0] == "十":
        return 10 + _CN_NUM.get(s[1], -100) if s[1] in _CN_NUM else None
    if len(s) == 2 and s[1] == "十" and s[0] in _CN_NUM:
        return _CN_NUM[s[0]] * 10
    if len(s) == 3 and s[1] == "十" and s[0] in _CN_NUM and s[2] in _CN_NUM:
        return _CN_NUM[s[0]] * 10 + _CN_NUM[s[2]]
    return None


def _doubt_ord_body(body: str, conv) -> Optional[set[int]]:
    """「1、2」「一及第二」「1~3」「ii、iii」→ 层号集合（区间展开）；有一个认不出 → None。"""
    parts = re.split(f"({_DOUBT_ORD_SEP})", body)
    nums: set[int] = set()
    prev: Optional[int] = None
    rng = False
    for tok in parts:
        if not tok:
            continue
        if re.fullmatch(_DOUBT_ORD_SEP, tok):
            rng = tok in _DOUBT_ORD_RANGE
            continue
        v = conv(tok.lstrip("第"))
        if v is None:
            return None
        if rng and prev is not None and prev <= v <= prev + 50:
            nums.update(range(prev, v + 1))
        nums.add(v)
        prev, rng = v, False
    return nums


def _doubt_ordinal_scan(s: str, total: Optional[int] = None) -> tuple[list[str], set[int], bool, str]:
    """紧凑串 s 里的全部序数指层 → (原词列表, 层号集合, 是否有认不出 / 取宽的, 去掉序数之后的串)。"""
    words: list[str] = []
    nums: set[int] = set()
    wide = False
    explicit: set[str] = set()   # FIRST/LAST 位置序数（fix18 裁定 4）匹配的词，不因「道/遍」结尾取宽

    def take(rx, handler):
        nonlocal s
        for m in list(rx.finditer(s)):
            words.append(m.group(0))
            handler(m)
        s = rx.sub("、", s)

    def bottom(m):
        nonlocal wide
        v = _doubt_no_value(m.group(1))
        if v is None or not total or not 1 <= v <= total:
            wide = True
        else:
            nums.add(total - v + 1)

    def listed(conv):
        def h(m):
            nonlocal wide
            got = _doubt_ord_body(m.group(1), conv)
            if got is None:
                wide = True
            else:
                nums.update(got)
        return h

    def widen(_m):
        nonlocal wide
        wide = True

    def interval(m):
        nonlocal wide
        a, b = _doubt_no_value(m.group("start")), _doubt_no_value(m.group("end"))
        if a is None or b is None or abs(a - b) > 50:
            wide = True
            return
        reverse_a = bool(m.group("direction"))
        reverse_b = bool(m.group("end_direction")) or reverse_a
        if reverse_a or reverse_b:
            if not total or not (1 <= a <= total and 1 <= b <= total):
                wide = True
                return
            a = total - a + 1 if reverse_a else a
            b = total - b + 1 if reverse_b else b
        nums.update(range(min(a, b), max(a, b) + 1))

    take(_DOUBT_ORD_REL_RX, widen)          # 相对序数先认，不能把「第N层以下」收窄成端点
    take(_DOUBT_ORD_INTERVAL_RX, interval)
    take(_DOUBT_ORD_BOTTOM_RX, bottom)
    take(_DOUBT_ORD_LIST_RX, listed(_doubt_num))
    take(_DOUBT_ORD_ROMAN_RX, listed(lambda t: _ROMAN_NUM.get(t)))
    take(_DOUBT_ORD_BARE_RX, listed(_doubt_num))
    take(_DOUBT_ORD_BARE_CN_RX, listed(_doubt_num))

    def first(_m):
        nums.add(1)
        explicit.add(_m.group(0))

    def last(_m):
        nonlocal wide
        explicit.add(_m.group(0))
        if total:
            nums.add(total)
        else:
            wide = True

    take(_DOUBT_ORD_FIRST_RX, first)
    take(_DOUBT_ORD_LAST_RX, last)
    take(_DOUBT_ORD_WIDE_RX, widen)
    # fix19：host 与 own_scope 共用同一取宽规则，条文号或越界序数不能作为排除本层的依据。
    # 「首道 / 头道 / 最上道 / 末道 / 尾道 / 头遍」等位置序数（fix18 裁定 4）已明确指层，不因「道 / 遍」结尾取宽；
    # 「第N条 / 第N道」这类可能是条文号 / 工序编号的仍取宽。
    if any(w not in explicit and not w.endswith(("层", "项")) for w in words):
        wide = True
    if any(n < 1 or (total is not None and n > total) for n in nums):
        wide = True
    return words, nums, wide, s


def _doubt_ordinal_strip(compact: str) -> str:
    """紧凑串去掉全部序数指层（量化 / 数量指代判断用：「第二层」不是「二层」）。"""
    return _doubt_ordinal_scan(compact)[3]


def _doubt_ordinal(raw_sentence: str, total: Optional[int] = None) -> Optional[tuple[Optional[frozenset], str]]:
    """句子里的序数指层（R4F-d fix16 → fix17，决定 1 的回指语素、协调者裁定 4）：None = 没有；(层号集合, 原词)；层号集合为
    None = 认不出指哪一层（首层 / 底层 / 最后一层 / 倒数第N层但层数不知道 …），取宽。fix17：一句里的全部序数都取（第1层和
    第2层、第一及第二层、首层及第3层），认「项 / 条 / 道」与不带「第」的「1、2层 / 1~2层」、罗马数字（第Ⅰ层），
    倒数 / 自下按所在格的层数 total 换算。"""
    words, nums, wide, _rest = _doubt_ordinal_scan(_doubt_compact(raw_sentence), total)
    if not words:
        return None
    return (None if wide or not nums else frozenset(nums)), "、".join(words)


_DOUBT_PIECE_NO = re.compile(r"(?:^|[^\d.．a-z])(\d{1,2}|[一二三四五六七八九十]{1,3}|[ivx]{1,4})\s*[)）、.．]\s*$")
_DOUBT_PIECE_NO_PAREN = re.compile(r"[（(]\s*(\d{1,2}|[一二三四五六七八九十]{1,3}|[ivx]{1,4})\s*[)）]\s*$")
_DOUBT_PIECE_NO_CIRCLE = re.compile(r"([①-⑳])\s*$")
# fix18（review18c R18C-06）：做法名称与首层同段、首层层号粘在名称冒号后面（「外墙C19：1）…」切层没切开）——层号在片内
_DOUBT_PIECE_GLUED = re.compile(r"^([^。；;！？!?\n]{1,40}?[：:])\s*(?=[（(]?\s*[1一]\s*[)）、.．])")
_DOUBT_THICK_RX = re.compile(r"\d+(?:\.\d+)?\s*(?:mm|MM|毫米)?\s*厚")
_DOUBT_PIECE_GLUED_NO = re.compile(r"^[^。；;！？!?\n]{1,40}?[：:]\s*[（(]?\s*(\d{1,2}|[一二三四五六七八九十]{1,3})\s*[)）、.．]")


def _doubt_no_value(tok: str) -> Optional[int]:
    if tok in _ROMAN_NUM:
        return _ROMAN_NUM[tok]
    return _doubt_num(tok)


def _doubt_piece_no(host_text: str, start: int, end: Optional[int] = None) -> Optional[int]:
    """本片在所在格原文里紧挨在前面的层号（1) 1、 1. （1） ① 一、 （二） Ⅱ、）；fix18：前面没有、片内开头是「名称：1）」
    （首层层号粘在做法名称后面）时取片内那个号。都没有 → None（序数指层按取宽算）。"""
    raw = host_text[max(0, start - 10):start]
    m = _DOUBT_PIECE_NO_CIRCLE.search(raw)
    if m:
        return ord(m.group(1)) - ord("①") + 1
    head = _doubt_fold(raw)
    m = _DOUBT_PIECE_NO_PAREN.search(head) or _DOUBT_PIECE_NO.search(head)
    if m:
        return _doubt_no_value(m.group(1))
    if end is not None and end > start:
        m = _DOUBT_PIECE_GLUED_NO.match(_doubt_fold(host_text[start:min(end, start + 60)]))
        if m:
            return _doubt_no_value(m.group(1))
    return None


def _doubt_name_words() -> list[str]:
    """点名用的材料 / 层名词（yaml 词典：做法材料词、单列层与辅层的层名词、一致性规则的原文词），折叠后、长的在前。"""
    r = load_rules()
    words: list[str] = list((r.get("practice_lexicon") or {}).get("materials") or ())
    g = r.get("granularity") or {}
    words += list(g.get("standalone") or ()) + list(g.get("aux") or ())
    for rule in r.get("consistency_rules") or ():
        words += list(rule.get("text_any") or ())
    return sorted({w for w in (_doubt_compact(str(x)) for x in words) if w}, key=lambda w: (-len(w), w))


def _doubt_names(text: str, vocab: list[str]) -> set[str]:
    s = _doubt_compact(text)
    return {w for w in vocab if w in s}


_DOUBT_MATERIAL_NOUN = re.compile(
    r"[a-z㐀-鿿]{1,32}(?:板|毡|棉|砖|砂浆|涂料|混凝土|卷材|膜|布|漆|玻璃|石材)")
_DOUBT_MATERIAL_BOUNDARY = re.compile(
    r"(?:饰面|保温|隔热|保护|找平|防水|面)层|作为|采用|粘贴|铺设|涂刷|喷涂|安装|铺贴")


def _doubt_layer_materials(text: str) -> set[str]:
    """从已切出的来源层首句提取材料名词，仅用作同格指称候选（铁律3：不参与编码）。

    厚度、角色、工艺及括号/逗号是描述边界，不再要求厚度→材料→层名的固定顺序。
    保留名词本身与原句的匹配；后续取消/替代句不能给本层凭空添加候选材料。
    """
    spans = _doubt_sentences(text)
    first = _doubt_compact(text[:spans[0][1]] if spans else text)
    first = _DOUBT_THICK_RX.sub(" ", first)
    first = _DOUBT_MATERIAL_BOUNDARY.sub(" ", first)
    found: set[str] = set()
    for token in re.findall(r"[a-z㐀-鿿]+", first):
        material = _DOUBT_MATERIAL_NOUN.match(token)
        if material:
            found.add(material.group(0))
    return found


def _doubt_layer_total(host_text: str, pieces: list[tuple[int, int, str]]) -> Optional[int]:
    """所在格 / 段的层数（fix17 → fix18：倒数 / 自下的序数按它换算）：各层都带层号时取最大层号；只有部分层片带号（同一层按
    厚度切出的无号片，review18a R18A-07「3、…，8厚胶粘剂粘贴」）时，带号的层号依次递增就取最大层号，否则层数不明（None，
    倒数 / 自下取宽）；都不带号时数层片；没有层片 → None。"""
    spans = [(pc[0], pc[1]) for pc in pieces if pc[2] == "layer" and pc[0] >= 0 and pc[1] > pc[0]]
    nos = [_doubt_piece_no(host_text, a, b) for a, b in spans]
    if nos and all(nos):
        return max(nos)
    known = [x for x in nos if x]
    if known:
        return max(known) if all(x < y for x, y in zip(known, known[1:])) else None
    return len(spans) or None


_DOUBT_OWN_SELF = frozenset("本此该这那其它彼之同亦也自当连余剩别凡任俱皆均都各诸每逐全整双两")


def _doubt_pure_other_ordinal(sent: str, total: int, my_no: int) -> bool:
    """本层原文第一句之后的一句是不是「纯序数、明确指向别的层」（fix18，决定 1 + 裁定 4；review18a R18A-01 / review18b
    R18B-02 / review18c R18C-01 / 05）：句里有序数，全部能换算成 1..层数 之内、单位都是「层」、不含本层层号；去掉序数之后
    没有任何回指 / 自指 / 前指 / 量化 / 补集语素（本 此 该 这 那 其 同 亦 也 自身 当前 连同 另 余 剩 别 除 均 都 各 全 整 双 两 …、
    以上 / 以下 / 上部 / 下方 …）。只有这样的句子才不算本层作用域；其余一律取宽（拿不准时取宽）。"""
    cs = _doubt_compact(sent)
    words, nums, wide, rest = _doubt_ordinal_scan(cs, total)
    if not words or wide or not nums:
        return False
    if my_no in nums or any(n < 1 or n > total for n in nums):
        return False
    if any(not w.endswith(("层", "项")) for w in words):
        return False                       # 第N条 / 第N道 / 第N步（本层「两道」里的第二道、条文号）：拿不准
    if any(c in _DOUBT_OWN_SELF for c in rest):
        return False
    fwd = next((w for w in _DOUBT_HOST_FORWARD if w in rest), "") or _DOUBT_FORWARD_RX.search(rest) \
        or _DOUBT_FWD_MORPH.search(rest)
    back = next((w for w in _DOUBT_HOST_BACK if w in rest), "") or _DOUBT_BACK_RX.search(rest) \
        or _DOUBT_BACK_MORPH.search(rest) or _DOUBT_HOST_QUANT_RX.search(rest)
    if fwd or back or _doubt_quant_c(rest) or _DOUBT_COMP_RX.search(rest):
        return False
    return True


def doubt_own_scope(text: str, host_text: str, pieces: list[tuple[int, int, str]], me: int) -> str:
    """本行原文里明确指向别的层的句子 → 换成等长空白（R4F-d fix17 → fix18，决定 1：作用域是与本层材料提及同句的文字，跨句
    要有指代）。只处理本行原文第一句之后的句子，而且只收窄「纯序数、明确指向别的（存在的）层」的句子（_doubt_pure_other_ordinal：
    「3)…罩面层。第1层取消」放在最后一层原文里）；句里带本层自指 / 回指 / 量化 / 除…外 / 其余 / 相对序数、序数越界或单位是
    项 / 条 / 道、点名了本层材料，或本层层号 / 层数认不出时，照旧取宽（本层原文里任何一句的触发都算）。位置不变，原因栏
    「原文第 N 字」仍按全文计。"""
    if not text or not host_text or not (0 <= me < len(pieces)) or pieces[me][0] < 0:
        return text
    my_no = _doubt_piece_no(host_text, pieces[me][0], pieces[me][1])
    spans = _doubt_sentences(text)
    if my_no is None or len(spans) < 2:
        return text
    total = _doubt_layer_total(host_text, pieces)
    if not total:
        return text
    vocab = _doubt_name_words() + sorted(_doubt_layer_materials(text))
    mine = _doubt_names(text[spans[0][0]:spans[0][1]], vocab)
    chars = list(text)
    for a, b in spans[1:]:
        sent = text[a:b]
        if not _doubt_pure_other_ordinal(sent, total, my_no):
            continue
        if _doubt_names(sent, vocab) & mine:
            continue
        for i in range(a, b):
            if not chars[i].isspace():
                chars[i] = " "
    return "".join(chars)


def doubt_host(code: str, host_text: str, where: str, pieces: list[tuple[int, int, str]],
               me: int) -> Optional[DoubtHostVerdict]:
    """同一单元格 / 段落里、本行原文之外的触发（本行原文由 doubt_gate 看）。决定 1：作用域按切层之前的整格 / 整段原文判。

    pieces：该格 / 段（xlsx 格内多行共用）切出的各片 [(起, 止, 角色)]，角色 layer = 构造层（自己或兄弟层），free = 不属于
    任何层的文字（做法名称 / 编号行与批注、行首空框、层号前的说明、悬空的续句）；me = 本行是第几片。落在任何片之外的
    原文（层号、分隔符、定位不到的片）按 free 算。
      · 兄弟层：触发与本层同句（合同句界：。！？；; 换行；层号、逗号、冒号、括号内不切）→ 算（同句）；触发句在本层之前且
        带前指（以下 / 下列 / 如下 / 其后 / 冒号结尾 …）、或在本层之后且带回指（上述 / 该 / 此 / 其 / 这些 / 两层 / 均 …）
        → 算；兄弟层文字带 fix14 的明示多字指代（以上 / 上一层 / 以下各层 …）→ 算（fix14 口径，作为下限保留）；
        R4F-d fix16：另一句里的序数指层（第1层 / 第一层 / 第1、2层 / 首层 / 底层 …；层号对得上本层、或认不出指哪层时算，
        指向别的层不算）、点名本层材料 / 层名（「保温层取消」「岩棉板改为XPS板」：句里的材料 / 层名词本层原文里有；触发所在
        那层自己也有同名材料时指哪层拿不准，取宽）→ 算；其余（另一句、无指代、没点名本层）不算。
      · 说明文字（free）：同句标「同句」；另一句带前指（在本层之前）/ 回指（在本层之后）的标「前指 / 回指」；其余句
        先看序数指层 / 点名：指向别的层、或只点名了别的层的材料 → 不算本层；点名本层 / 认不出 → 算；什么都没指的取宽
        （拿不准时取宽，fix14 口径）——说明文字的触发对该格各层都算，标签只说明它是怎么连到本层的。"""
    if not host_text or not (0 <= me < len(pieces)):
        return None
    s0, e0 = pieces[me][0], pieces[me][1]
    if s0 < 0 or e0 <= s0:
        return None
    n = len(host_text)
    spans = _doubt_sentences(host_text)
    sent_of = [0] * n
    for k, (a, b) in enumerate(spans):
        for i in range(a, b):
            sent_of[i] = k
    mine = sorted({sent_of[i] for i in range(s0, min(e0, n))})
    if not mine:
        return None
    lo, hi = mine[0], mine[-1]
    refs: dict[int, tuple[str, str]] = {}

    def ref_of(j: int) -> tuple[str, str]:
        if j not in refs:
            a, b = spans[j]
            refs[j] = _doubt_host_refs(host_text[a:b])
        return refs[j]

    covered = [False] * n
    regions: list[tuple[int, int, str]] = []
    first_layer = min((pc[0] for pc in pieces if pc[2] != "free" and pc[0] >= 0 and pc[1] > pc[0]), default=-1)
    for k, pc in enumerate(pieces):
        a, b, role = pc[0], pc[1], pc[2]
        if a < 0 or b <= a:
            continue
        for i in range(max(0, a), min(b, n)):
            covered[i] = True
        if k != me:
            g = (_DOUBT_PIECE_GLUED.match(host_text[a:min(b, n)])
                 if role != "free" and a == first_layer else None)
            if g and _DOUBT_THICK_RX.search(g.group(1)):
                g = None                   # 前缀是一层的描述（「5厚…面层，以下取消：3)…」），不是做法名称
            if g:
                # fix18（review18c R18C-05 SC-03 / 06）：做法名称（含批注「（取消）」）粘在首层片头上（「外墙C03（取消）：1、…」）
                # ——名称部分按不属于任何层的文字（free）看，批注管整个做法，拿不准时取宽
                regions.append((a, a + g.end(1), "free"))
                regions.append((a + g.end(1), min(b, n), role))
            else:
                regions.append((a, min(b, n), role))
    i = 0
    while i < n:
        if covered[i]:
            i += 1
            continue
        j = i
        while j < n and not covered[j]:
            j += 1
        if host_text[i:j].strip():
            regions.append((i, j, "free"))
        i = j
    my_no = _doubt_piece_no(host_text, s0, e0)
    total = _doubt_layer_total(host_text, pieces)
    quants: dict[int, str] = {}
    comps: dict[int, str] = {}

    def quant_of(j: int) -> str:
        if j not in quants:
            a, b = spans[j]
            quants[j] = _doubt_quant(host_text[a:b])
        return quants[j]

    def comp_of(j: int) -> str:
        """补集语素（fix18，裁定 4）：除…外 / 以外 / 其余的 / 剩下的 / 别的 …——序数指别的层也把本层包括进去，方向不限。"""
        if j not in comps:
            a, b = spans[j]
            comps[j] = _doubt_complement(host_text[a:b])
        return comps[j]

    vocab: list[str] = []
    mine_words: set[str] = set()
    other_words: set[str] = set()

    def names_ready() -> None:
        nonlocal vocab, mine_words, other_words
        if vocab:
            return
        actual = _doubt_layer_materials(host_text[s0:e0])
        for a2, b2, r2 in regions:
            if r2 != "free":
                actual |= _doubt_layer_materials(host_text[a2:b2])
        vocab = _doubt_name_words() + sorted(actual)
        own_first = _doubt_sentences(host_text[s0:e0])
        mine_words = _doubt_names(host_text[s0:s0 + own_first[0][1]] if own_first else host_text[s0:e0], vocab)
        for a2, b2, r2 in regions:
            if r2 != "free":
                peer_first = _doubt_sentences(host_text[a2:b2])
                other_words |= _doubt_names(host_text[a2:a2 + peer_first[0][1]] if peer_first else host_text[a2:b2], vocab)

    def via_reference(j: int, a: int, b: int, free: bool) -> Optional[str]:
        """另一句里没有方向对的代词指代时：序数指层 / 点名本层 → 标签；指向别的层 → ""（不算）；什么都没指 → None。
        fix17（协调者裁定 4）：一句里的序数全取；序数对不上本层时仍看点名（「第2层取消，保温层改为XPS板」点名本层照算）。
        序数看触发所在这一段、连同它前面紧挨的几个字（同一句里）：「，1、2层取消」的「1、」会被切层当成层号切走，只剩
        「2层取消」一段。点名只看触发所在的这一段（fix16 口径）：整句里还有别的层自己的原文，拿整句点名会把做法名称批注
        （「外墙346（停用）：1、岩棉板…；2、抗裂砂浆…」）当成只点名了第 1 层而不算第 2 层——批注管整个做法，什么都没
        点名就取宽。"""
        sa, sb = spans[j]
        part = host_text[max(a, sa):min(b, sb)]
        od = _doubt_ordinal(host_text[max(sa, a - _DOUBT_ORD_LOOKBACK):min(b, sb)], total)
        what = "层号外的说明文字" if free else "另一层"
        names_ready()
        said = _doubt_names(part, vocab)
        # 句里点名的材料 / 层名本层原文里有就算点名本层；触发所在那层自己也有同名材料（「2)岩棉板防火隔离带，宽300。
        # 岩棉板改为XPS板」）时指哪一层拿不准，取宽（决定 1），不扣掉那层自己的层头
        hit = sorted(said & mine_words, key=lambda w: (-len(w), w))
        if od is not None:
            nums, word = od
            if nums is None or my_no is None or my_no in nums:
                return f"序数指层·同{where}{what}（「{word}」）"
            if hit:
                return f"点名本层·同{where}{what}（「{hit[0]}」）"
            loose = _DOUBT_COMP_LOOSE_RX.search(_doubt_ordinal_strip(_doubt_compact(host_text[sa:sb])))
            if loose:
                # fix18（裁定 4）：序数点了别的层、句里另有补集说法——本层在补集里
                return f"补集·同{where}{what}（「{word}」+「{loose.group(0)}」）"
            return ""
        if hit:
            return f"点名本层·同{where}{what}（「{hit[0]}」）"
        if free and said and said <= (other_words - mine_words):
            return ""
        return None

    gating: list[DoubtTrigger] = []
    seen: set[tuple[int, int]] = set()
    for a, b, role in regions:
        region = host_text[a:b]
        peer = "" if role == "free" else _doubt_peer_ref(region, a >= e0)
        # fix17（协调者裁定 3）：叉号是否在段首按所在格原文看——片段前面同一合同句里的那一截（「1、…，2、」）接在前面一起判
        head = host_text[spans[sent_of[a]][0]:a] if a < n else ""
        # fix18（裁定 3 / review18a R18A-03）：片段右侧紧挨的是标点时用真实右邻判叉号 / 斜杠 / 破折号（「面层×，3、…」）；
        # 右侧是字（「有效—— 1)…」的层号）时照旧当作有字
        nxt_raw = host_text[b:].lstrip(" \t\u3000")
        rc = (_doubt_fold(nxt_raw[0])[:1] or nxt_raw[0]) if nxt_raw and nxt_raw[0] in _DOUBT_RIGHT_PUNCT else None
        for kind, x, y in _doubt_detect(region, edge_left=a > 0, edge_right=b < n, head_prefix=head, right_char=rc):
            p = a + x
            if (p, y - x) in seen:
                continue
            j = sent_of[p]
            if role == "free":
                if lo <= j <= hi:
                    link = f"同句·同{where}层号外的说明文字"
                elif j < lo and ref_of(j)[0]:
                    link = f"前指·同{where}层号外的说明文字（「{ref_of(j)[0]}」）"
                elif j > hi and ref_of(j)[1]:
                    link = f"回指·同{where}层号外的说明文字（「{ref_of(j)[1]}」）"
                elif quant_of(j):
                    link = f"全称·同{where}层号外的说明文字（「{quant_of(j)}」）"
                elif comp_of(j):
                    link = f"补集·同{where}层号外的说明文字（「{comp_of(j)}」）"
                else:
                    via = via_reference(j, a, b, True)
                    if via == "":
                        continue
                    link = via or f"取宽·同{where}层号外的说明文字"
            elif peer:
                link = f"{'回指' if a >= e0 else '前指'}·同{where}另一层（「{peer}」）"
            elif lo <= j <= hi:
                link = f"同句·同{where}另一层"
            elif j < lo and ref_of(j)[0]:
                link = f"前指·同{where}另一层（「{ref_of(j)[0]}」）"
            elif j > hi and ref_of(j)[1]:
                link = f"回指·同{where}另一层（「{ref_of(j)[1]}」）"
            elif quant_of(j):
                # fix17（协调者裁定 4）：量化回指语素不分前后（方向对的前指 / 回指先按原标签记）
                link = f"全称·同{where}另一层（「{quant_of(j)}」）"
            elif comp_of(j):
                # fix18（裁定 4，review18a R18A-02）：补集（除第1层外均取消、第1层保留，其余取消、剩下的取消）不分前后
                link = f"补集·同{where}另一层（「{comp_of(j)}」）"
            else:
                via = via_reference(j, a, b, False)
                if not via:
                    continue
                link = via
            seen.add((p, y - x))
            gating.append(DoubtTrigger(kind, host_text[p:a + y + 1], p + 1, j + 1, link))
    if not gating:
        return None
    gating.sort(key=lambda t: (t.pos, -len(t.token)))
    return DoubtHostVerdict(host_text, where, tuple(gating))


def confusables() -> list[str]:
    return list(load_rules().get("confusables") or [])


# ============================================================ 标段 / 范围排除（QTY-11，D54）

_ROMAN = {"Ⅰ": 1, "Ⅱ": 2, "Ⅲ": 3, "Ⅳ": 4, "Ⅴ": 5, "Ⅵ": 6, "Ⅶ": 7, "Ⅷ": 8, "Ⅸ": 9, "Ⅹ": 10,
          "Ⅺ": 11, "Ⅻ": 12}
_ASCII_ROMAN = {"I": 1, "V": 5, "X": 10}
_CN_DIGIT = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def normalize_lot(token: str) -> Optional[int]:
    """罗马数字（含 Unicode Ⅰ–Ⅻ）、中文数字、阿拉伯数字 → int；解析不了 None。"""
    s = (token or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if len(s) == 1 and s in _ROMAN:
        return _ROMAN[s]
    up = s.upper()
    if all(ch in _ASCII_ROMAN for ch in up):
        total, prev = 0, 0
        for ch in reversed(up):
            v = _ASCII_ROMAN[ch]
            total = total - v if v < prev else total + v
            prev = max(prev, v)
        return total or None
    if all(ch in _CN_DIGIT or ch == "十" for ch in s):
        if s == "十":
            return 10
        if "十" in s:
            head, _, tail = s.partition("十")
            return (_CN_DIGIT.get(head, 1) if head else 1) * 10 + (_CN_DIGIT.get(tail, 0) if tail else 0)
        if len(s) == 1:
            return _CN_DIGIT[s]
    return None


def parse_project_lot(project_name: Optional[str]) -> Optional[int]:
    """项目名称里的「X标 / 第X标段」→ 标段号（D54）。解析不到 None。"""
    if not project_name:
        return None
    pat = re.compile(load_rules()["lot_pattern"])
    for m in pat.finditer(_norm(project_name)):
        n = normalize_lot(m.group("lot"))
        if n is not None:
            return n
    return None


@dataclass
class Exclusion:
    id: str                    # e1, e2 …（送进 prompt 的编号）
    kind: str                  # lot / owner / secondary / not_in_scope
    sentence: str
    objects: list[str]
    target_lot: Optional[int] = None
    segment_id: Optional[str] = None
    location: str = ""
    file_name: str = ""


@functools.lru_cache(maxsize=1)
def _exclusion_patterns() -> list[tuple[str, re.Pattern]]:
    pats = load_rules()["exclusion_patterns"]
    return [(k, re.compile(v)) for k, v in pats.items()]


# 写在做法层正文里也照样管全局的两类（标段句、「不在本次范围」句）；自理与二次装修写在层里只管这一层
GLOBAL_IN_LAYER = ("lot", "not_in_scope")

_CJK = re.compile(r"[\u4e00-\u9fff]")
# 句首条文号 / 序号：「3、」「(3)」「13.13、」带分隔符；「13.13 」「3 」后面是空白；
# 「13.13楼地面」多级号直接接汉字（「1.5厚」的厚度不是条文号，不动）
_CLAUSE_NO = re.compile(
    r"^\s*(?:[（(]?\d+(?:[.．]\d+)*\s*[)）、.．](?!\d)\s*"
    r"|\d+(?:[.．]\d+)*\s+"
    r"|\d+(?:[.．]\d+)+(?=[\u4e00-\u9fff])(?!厚))")
_BALANCED = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|【[^【】]*】")


def _strip_clause_no(s: str) -> str:
    """去句首的多级条文号与单独的序号。只去一级时「13.13 二次装修…」会剩下对象词「13」，
    子串匹配排掉所有带「13」的片段（实测 14 条，含全部住宅楼的外墙保温；E29）。"""
    prev = None
    while prev != s:
        prev = s
        s = _CLAUSE_NO.sub("", s, count=1)
    return s


def _strip_brackets(s: str) -> str:
    """成对的括号连内容去掉；落单的半边括号是切分留下的残片：「(详」留左边，「内掺建筑胶) 地下室」留右边。"""
    prev = None
    while prev != s:
        prev = s
        s = _BALANCED.sub(" ", s)
    for op, cl in (("(", ")"), ("[", "]"), ("【", "】")):
        if cl in s:
            s = s.rsplit(cl, 1)[1]
        if op in s:
            s = s.split(op, 1)[0]
    return s


def _split_objects(obj: str) -> tuple[list[str], list[str]]:
    """排除句的对象串 → (对象词, 因为是泛指词而丢弃的词)。"""
    cfg = load_rules()["exclusion_object"]
    stop = {_norm(w) for w in cfg.get("stop_words") or []}
    generic = {_norm(w) for w in cfg.get("generic_words") or []}
    obj = _BALANCED.sub(" ", _strip_clause_no(obj))
    parts = re.split(cfg["split"], obj)
    for extra in cfg.get("also_split") or []:
        parts = [q for p in parts for q in p.split(extra)]
    out: list[str] = []
    dropped: list[str] = []
    for p in parts:
        s = _strip_brackets(p).strip(" ：:，,。.、（）()\"'“”")
        s = _strip_clause_no(s)
        changed = True
        while changed and s:
            changed = False
            for pre in cfg.get("strip_prefix") or []:
                if s.startswith(pre):
                    # 前缀后面还会露出序号（「注：1. 卫生间洁具」）：不再去一次，对象词就是「1. 卫生间洁具」，
                    # 哪个片段都匹配不上，这条排除句等于没写（第六条：对象词不能带编号）
                    s = _strip_clause_no(s[len(pre):].lstrip("：: "))
                    changed = True
            for suf in cfg.get("strip_suffix") or []:
                if s.endswith(suf) and len(s) > len(suf):
                    s = s[: -len(suf)]
                    changed = True
        s = s.strip()
        if len(s) < int(cfg.get("min_len", 2)) or s in stop:
            continue
        if len(_CJK.findall(s)) < int(cfg.get("min_cjk", 2)):
            continue          # 纯数字、纯标点、「13」「3#」：不能当对象词
        if s in generic:
            if s not in dropped:
                dropped.append(s)
            continue
        if s not in out:
            out.append(s)
    return out, dropped


@dataclass(frozen=True)
class ExclusionScan:
    """一句原文过排除句式的结果。found 之外的两项是「句式命中、但没有据此排除」，调用方要让人看得到。"""
    found: tuple = ()            # ((kind, [对象词], 目标标段), …)
    too_generic: tuple = ()      # ((kind, [泛指词]), …)：清洗后只剩泛指词
    no_object: tuple = ()        # (kind, …)：清洗后没有对象词

    @property
    def rejected(self) -> bool:
        return bool(self.too_generic or self.no_object)


def scan_exclusions(text: str, kinds: Optional[Iterable[str]] = None) -> ExclusionScan:
    t = _norm(text)
    want = set(kinds) if kinds is not None else None
    found: list[tuple[str, list[str], Optional[int]]] = []
    too_generic: list[tuple[str, list[str]]] = []
    no_object: list[str] = []
    for kind, pat in _exclusion_patterns():
        if want is not None and kind not in want:
            continue
        m = pat.search(t)
        if not m:
            continue
        lot = normalize_lot(m.group("lot")) if kind == "lot" else None
        if kind == "lot" and lot is None:
            continue
        objs, dropped = _split_objects(m.group("obj"))
        if objs:
            found.append((kind, objs, lot))
        elif dropped:
            too_generic.append((kind, dropped))
        else:
            no_object.append(kind)
    return ExclusionScan(tuple(found), tuple(too_generic), tuple(no_object))


def find_exclusions(text: str, kinds: Optional[Iterable[str]] = None
                    ) -> list[tuple[str, list[str], Optional[int]]]:
    """一句原文里的排除句 → [(kind, 对象词, 目标标段)]。不是排除句返回空。kinds 限定只看哪几类。"""
    return list(scan_exclusions(text, kinds).found)


def match_exclusion(exclusions: list[Exclusion], haystack: str) -> Optional[Exclusion]:
    """片段正文 + 上下文里出现了某条排除句的对象词 → 返回那条（按出现顺序取第一条）。"""
    h = _norm(haystack)
    for ex in exclusions:
        if any(o in h for o in ex.objects):
            return ex
    return None


# ============================================================ 层内标记（WS29-f，D-R110 / D-R111）

OWNER_AMBIGUOUS = "owner_inline_ambiguous"         # 「自理或（详精装修设计）」→ 待核，不替人选
OWNER_INLINE = "excluded_owner_inline"             # 本层用户自理 → 范围排除，引用原句，不送模型
SECONDARY_INLINE = "excluded_secondary_inline"     # 本层写明为二次装修 → 范围排除
FITOUT_PROVISIONAL = "fitout_provisional"          # 详精装修设计 / 详二次装修 → 照常列项，带「做法暂定」（标记，不是去向）

# 层内原因码与标记（code → 中文名）。待核 / 范围排除两页、覆盖核算页按这里的名字写
INLINE_CODES: dict[str, str] = {
    OWNER_AMBIGUOUS: "原文写「自理或…」，自理与另一种做法并列，不替人选，请人工确认",
    OWNER_INLINE: "原文注明这一层自理，不在本次范围",
    SECONDARY_INLINE: "原文写明这一层为二次装修，不在本次范围",
    FITOUT_PROVISIONAL: "原文注明详精装修设计，做法暂定",
}
PROVISIONAL_NOTE = INLINE_CODES[FITOUT_PROVISIONAL]


@dataclass(frozen=True)
class InlineMarker:
    code: str
    matched: str               # 命中的原文字样（「用户自理」「详精装修设计」）
    also: str = ""             # 同一层另外带着的精装修引用（「详二次装修」），写进原因
    where: str = "layer"       # layer / practice / part：标记写在层正文、做法名称还是适用部位上


@functools.lru_cache(maxsize=1)
def _inline_patterns() -> tuple[re.Pattern, re.Pattern, list[re.Pattern], list[re.Pattern], re.Pattern]:
    r = load_rules()
    own = r["inline_owner"]
    alt = lambda ws: "|".join(re.escape(_norm(w)) for w in ws)  # noqa: E731
    owner = re.compile(rf"(?:{alt(own['subjects'])})(?:{'|'.join(own['actions'])})")
    either = re.compile(rf"^[\s()（）]*(?:{alt(own['alternatives'])})")
    fit = r["inline_fitout_ref"]
    return (owner, re.compile(r["inline_secondary"]), [re.compile(p) for p in fit["patterns"]],
            [re.compile(p) for p in fit.get("name_patterns") or []], either)


def _fitout_ref(t: str, *, name: bool = False) -> str:
    _owner, _sec, pats, name_pats, _either = _inline_patterns()
    for p in pats + (name_pats if name else []):
        m = p.search(t)
        if m:
            return m.group(0)
    return ""


@functools.lru_cache(maxsize=4096)
def find_inline_marker(text: str, practice: str = "", part: str = "") -> Optional[InlineMarker]:
    """做法层正文（续行合并之后）里的标记，只管这一层。同一层命中多个时取优先级高的：

    1 自理 + 「或」→ 待核；2 自理 → 范围排除；3 本层写明为二次装修 → 范围排除；
    4 精装修引用（层正文、做法名称、适用部位任一处）→ 照常列项，带「做法暂定」。
    """
    t = _norm(text)
    owner, secondary, _pats, _name_pats, either = _inline_patterns()
    ref = _fitout_ref(t)
    m = owner.search(t)
    if m:
        also = ref if ref and ref not in m.group(0) else ""
        if either.search(t[m.end():]):
            return InlineMarker(OWNER_AMBIGUOUS, m.group(0), also)
        return InlineMarker(OWNER_INLINE, m.group(0), also)
    m = secondary.search(t)
    if m:
        return InlineMarker(SECONDARY_INLINE, m.group(0), ref)
    if ref:
        return InlineMarker(FITOUT_PROVISIONAL, ref)
    for where, src in (("practice", practice), ("part", part)):
        hit = _fitout_ref(_norm(src), name=True) if src else ""
        if hit:
            return InlineMarker(FITOUT_PROVISIONAL, hit, where=where)
    return None


def scope_related_words(text: str) -> list[str]:
    """原文里出现的范围相关字样（二次装修 / 精装修 / 自理）。"""
    t = _norm(text)
    return [w for w in load_rules().get("scope_related_words") or [] if _norm(w) in t]


# ============================================================ 规格签名（QTY-09）

# 「屋面防水：」这类标签；不含数字，免得把「20厚1:2」的配合比冒号当成标签切掉
_LABEL_PREFIX = re.compile(r"^[^\d：:]{1,16}[：:]")
_NUMBERING = re.compile(r"^\s*(?:[（(]?\d{1,2}[)）.、．]|[①-⑳])\s*")


def spec_signature(text: str) -> str:
    """规格签名：NFKC、去编号与「xx：」标签、去空白与分隔标点、「2.0」→「2」、「份」→「分」。"""
    s = _norm(text)
    s = _NUMBERING.sub("", s)
    s = _LABEL_PREFIX.sub("", s)
    s = re.sub(r"(\d+)\.0+(?!\d)", r"\1", s)
    s = s.replace("份", "分")
    # 小数点与配合比冒号保留：「1.5厚」≠「15厚」，「1:2」≠「12」
    s = re.sub(r"[\s，,。;；、()（）\[\]【】\"'“”]", "", s)
    return s.lower()


@dataclass
class RuleSummary:
    rules: int = 0
    ids: list[str] = field(default_factory=list)


def rule_summary() -> RuleSummary:
    rs = load_rules()["consistency_rules"]
    return RuleSummary(len(rs), [r["id"] for r in rs])
