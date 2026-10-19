# 来源：engine-service/app/engine/report_sections.py（zhitong-cost-ai@991ff5c，W3 搬入 zt；只改了 import）
"""审核报告正文的确定性读取（整改 spec WS07 K2 第 2 条）。

docx、文字层 PDF、旁车文本通用：输入是 `zt.textextract.extract.load_document` 给出的正文（C6），
不在这里解析任何文件格式。

两件事：
- `cut_sections`：按「一、二、三、……」切章，章名归一（审核依据 / 相关事项 / 审核结果 / 项目概况）。
  「审核依据」「相关事项审核说明」两个叙述字段直接取章节原文（channel=section）——
  改前由 LLM 摘录，498 份那次审核依据取成了节能设计标准条文、相关事项取成了外窗通风条文。
- `regex_fields`：金额 / 核减率 / 工期用锚定正则取（channel=regex；找不到章节时对全文跑，
  channel=regex_fulltext，排序低于 regex）。连接词只允许「为 / 是 / 冒号」，**带「约」的
  近似数不取**；核减金额的锚点带 `(?<!净)`，「净核减造价为 1280435 元」不会被当成核减金额
  （QA:extract-01：LLM 正是把净核减当成了核减，差 138200 元）。

这里产出的候选都经 `evidence_check.verify_candidate` 核验（数字回链全仓只此一份，K26），
定位（章名、页）由代码回填，不让模型写（C4）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from zt.amounts.amounts import format_yuan, parse_amount, parse_days, parse_rate
from zt.report.fields import field_def, norm_text, verify_candidate

# 章标题：行首「一、」「二．」…，标题本身不超过 21 个字（再长就是正文里以序号开头的句子）
_HEAD = re.compile(r"^\s*([一二三四五六七八九十]+)[、.．]\s*(\S.{0,20})$")
# text_chain 给多页正文插的页锚行：`[p3]`、`[p3–p5] ｜未取得正文（…）`、`[p4] ｜OCR`
_PAGE_ANCHOR = re.compile(r"^\[p(\d+)(?:–p\d+)?\]")

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "审核依据": ("审核依据", "编制依据", "审计依据"),
    "相关事项": ("相关事项说明", "相关事项审核说明", "有关事项说明", "其他说明", "需说明的事项"),
    "审核结果": ("审核结果", "审计结果", "审定结果"),
    "项目概况": ("项目概况", "工程概况"),
}
# 叙述字段 ← 章节
NARRATIVE_SECTIONS: dict[str, str] = {"审核依据": "审核依据", "相关事项审核说明": "相关事项"}
# 锚定正则只在这两章里跑（审核依据 / 相关事项里的数是引用的规范条文、分项说明，不是结论）
REGEX_SCOPE = ("审核结果", "项目概况")

_CONNECT = r"\s*[为是:：]?\s*(?:人民币|RMB|¥|￥)?\s*"
_NUM = r"(-?[\d,，]+(?:\.\d+)?)\s*(万元|元)"
# 字段 → (锚点, 取值部分, 取值类型)
FIELD_PATTERNS: dict[str, tuple[str, str, str]] = {
    "送审金额": (r"送审(?:总)?(?:造价|金额|价)", _NUM, "amount"),
    "审定金额": (r"(?:审核定案|审定)(?:总)?(?:造价|金额|价)", _NUM, "amount"),
    "核减金额": (r"(?<!净)核减(?:造价|金额|额)", _NUM, "amount"),
    "核增额": (r"核增(?:造价|金额|额)", _NUM, "amount"),
    "核减率": (r"核减率", r"(-?\d+(?:\.\d+)?)\s*([%％])", "rate"),
    "合同价": (r"(?:签约)?合同(?:价|金额|总价)", _NUM, "amount"),
    # 决策 D37：只取合同工期
    "工期": (r"合同工期", r"(\d+)\s*(日历天|天)", "duration"),
}
_COMPILED = {f: re.compile(a + _CONNECT + v) for f, (a, v, _k) in FIELD_PATTERNS.items()}
# 引文取到句读为止
_CLAUSE_END = "。；;\n"
_QUOTE_MAX = 200


@dataclass
class Section:
    no: str                 # 「四」
    title: str              # 标题原文（去掉序号）
    canon: Optional[str]    # 归一章名；认不出 → None
    heading: str            # 整行标题，如「四、审核结果」
    start: int              # 正文（标题行之后）在全文里的起点
    end: int                # 正文终点（下一章标题行的起点，或全文末尾）
    page: Optional[int]     # 标题所在页（按页锚回填；单页 / 无锚点为 None）


def _canon(title: str) -> Optional[str]:
    t = re.sub(r"[\s:：。.]+", "", title)
    for canon, aliases in SECTION_ALIASES.items():
        if any(a in t for a in aliases):
            return canon
    return None


def page_at(text: str, pos: int) -> Optional[int]:
    """pos 之前最近的一条页锚 → 页号（C4：页号与旁车 `## pN`、text_chain 的 `[pN]` 同口径）。"""
    head = text[:pos]
    for line in reversed(head.split("\n")):
        m = _PAGE_ANCHOR.match(line.strip())
        if m:
            return int(m.group(1))
    return None


def cut_sections(text: str) -> list[Section]:
    """按行切章。没有任何章标题 → []。"""
    if not text:
        return []
    heads: list[tuple[int, int, re.Match]] = []
    pos = 0
    for line in text.split("\n"):
        m = _HEAD.match(line)
        if m:
            heads.append((pos, pos + len(line), m))
        pos += len(line) + 1
    out: list[Section] = []
    for i, (lstart, lend, m) in enumerate(heads):
        body_start = min(len(text), lend + 1)
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        title = m.group(2).strip()
        out.append(Section(m.group(1), title, _canon(title), text[lstart:lend].strip(),
                           body_start, max(body_start, end), page_at(text, lstart)))
    return out


def section_body(text: str, sec: Section) -> str:
    """章节正文：去掉页锚行（那是我们自己插的，不是原文），首尾空白去掉。"""
    lines = [ln for ln in text[sec.start:sec.end].split("\n")
             if not _PAGE_ANCHOR.match(ln.strip())]
    return "\n".join(lines).strip()


def _clause(text: str, start: int, end: int) -> tuple[str, int]:
    """匹配所在的分句（前后到句读为止），过长时以匹配为中心截到 200 字。返回 (引文, 引文起点)。"""
    lo = start
    while lo > 0 and text[lo - 1] not in _CLAUSE_END:
        lo -= 1
    hi = end
    while hi < len(text) and text[hi] not in _CLAUSE_END:
        hi += 1
    if hi - lo > _QUOTE_MAX:
        lo = max(lo, end - _QUOTE_MAX)
        hi = min(hi, lo + _QUOTE_MAX)
    return text[lo:hi].strip(), lo


def _value_of(kind: str, num: str, unit: str) -> Optional[dict]:
    """正则取到的数 → 候选的取值键。解析不了（理论上不会）→ None，不编一个数出来（铁律 3）。"""
    raw = f"{num}{unit}"
    if kind == "amount":
        a = parse_amount(raw)
        if a is None:
            return None
        return {"value": raw, "unit": unit, "amount_yuan": format_yuan(a.value)}
    if kind == "rate":
        r = parse_rate(num + "%")
        if r is None:
            return None
        return {"value": f"{num}%", "unit": "%"}
    d = parse_days(raw)
    if d is None:
        return None
    return {"value": raw, "unit": unit}


def _scan(text: str, lo: int, hi: int, fields: Iterable[str], channel: str,
          heading: Optional[str], source_norm: str, *, first_only: bool) -> list[dict]:
    """在 text[lo:hi] 里跑锚定正则。

    - 章节内（`first_only`）：**每个字段只取第一处**。审核结果里常见「审定金额为 X 元，其中土建
      工程审定金额为 Y 元」，第一处才是合计。
    - 全文（找不到章节）：每个**不同的值**都出一条候选。全文里谁是合计说不清，只取第一处会把另一个
      数静默丢掉；都交给合并 —— 同层级的数值冲突留空待选（D35），由人来挑。"""
    out: list[dict] = []
    for f in fields:
        pat = _COMPILED.get(f)
        if pat is None:
            continue
        seen: set[str] = set()
        for m in pat.finditer(text, lo, hi):
            kind = FIELD_PATTERNS[f][2]
            val = _value_of(kind, m.group(1), m.group(2))
            if val is None:
                continue
            key = val.get("amount_yuan") or val["value"]
            if key in seen:
                continue
            quote, _qpos = _clause(text, m.start(), m.end())
            vr = verify_candidate(field_def(f), val["value"], quote, source_norm)
            if vr.reject:
                continue
            seen.add(key)
            out.append({
                "field": f, **val, "kind": field_def(f).kind, "quote": quote, "channel": channel,
                "verify_level": vr.level, "verified": vr.verified, "verify_notes": list(vr.notes),
                "evidence": {"heading": heading, "page": page_at(text, m.start()), "quote": quote},
            })
            if first_only:
                break
    return out


def regex_fields(text: str, fields: Optional[Iterable[str]] = None, *,
                 sections: Optional[list[Section]] = None) -> list[dict]:
    """锚定正则取数。只在「审核结果」「项目概况」两章里跑（channel=regex）；
    这两章都找不到时对全文跑（channel=regex_fulltext，合并时排在 regex 之后）。"""
    if not text:
        return []
    want = list(fields) if fields is not None else list(FIELD_PATTERNS)
    secs = sections if sections is not None else cut_sections(text)
    scoped = [s for s in secs if s.canon in REGEX_SCOPE]
    src_norm = norm_text(text)
    if not scoped:
        return _scan(text, 0, len(text), want, "regex_fulltext", None, src_norm, first_only=False)
    # 审核结果优先：同一字段两章都有时两处都出候选（同值归一组，不同值由合并按冲突处理）
    scoped.sort(key=lambda s: REGEX_SCOPE.index(s.canon))
    out: list[dict] = []
    for s in scoped:
        out.extend(_scan(text, s.start, s.end, want, "regex", s.heading, src_norm, first_only=True))
    return out


def section_fields(text: str, fields: Optional[Iterable[str]] = None, *,
                   sections: Optional[list[Section]] = None) -> list[dict]:
    """叙述字段直接取章节原文：value 与 quote 相同，channel=section，verify_level=strong
    （原文就是这一段，不存在「模型改写过」的问题）。同名章节有多个时取第一个。"""
    want = list(fields) if fields is not None else list(NARRATIVE_SECTIONS)
    secs = sections if sections is not None else cut_sections(text)
    out: list[dict] = []
    for f in want:
        canon = NARRATIVE_SECTIONS.get(f)
        if canon is None:
            continue
        sec = next((s for s in secs if s.canon == canon), None)
        if sec is None:
            continue
        body = section_body(text, sec)
        if not body:
            continue
        out.append({
            "field": f, "value": body, "quote": body, "kind": field_def(f).kind,
            "channel": "section", "verify_level": "strong", "verified": True, "verify_notes": [],
            "evidence": {"heading": sec.heading, "page": sec.page, "quote": body},
        })
    return out
