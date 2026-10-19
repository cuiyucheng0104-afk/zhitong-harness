# 来源：engine-service/app/engine/report_guard.py（zhitong-cost-ai@991ff5c，W3 搬入 zt；改动见本文件内「zt 改动」注释）
"""AI 报告初稿的确定性护栏（整改 spec WS12-B：P01 / P02 / P05 / P06 / P07 / P09 / P10）。

LLM 写完一章之后，这里只做**确定性**的检查与标注，不再调模型：

- `backlink`（P01，铁律 2/3）：正文里每个数都要能在送进模型的资料原文里逐字找到，找不到就在原位插
  「【待核：资料中未找到此数】」。
- `check_unreadable_claims`（P02，铁律 8）：有资料读不出正文时，「未列示 / 未载明」这类断言可能只是
  没读到，加【待核】。
- `rewrite_meta_talk`（P06）：「本节信息不足」这类 AI 元话语不许进正文，改写成【待补】并记 missing_items。
- `check_claims`（P07）：全过程审核、现场踏勘这类程序性陈述，用户没确认、资料里也没有 → 【待核】。
- `check_negations`（P10）：「未涉及…」「均无…」这类全称否定，资料里没有同样的说法 → 【待核】。
- `check_transcription`（P05）：与用户勾回的成稿报告有 30 字以上逐字重合 → 记 transcribed。
- `strip_title` / `normalize_blank_lines`（P09）：首行复述章标题就删掉，连续空行合并。

WS24-o（issue #884，缺陷 02-008、02-012，总纲 D-R153）再加四条，都是确定性的逐字查找（铁律 3：不做相似度）：

- `rewrite_placeholders`（raw_placeholder）：资料里没替换的「###名称###」换成「【待补：名称】」，这一句的 [资料n] 去掉。
- `check_template_echo`（template_echo）：句子与本章写作要求有 6 个汉字以上的连续片段相同、而这段话在送入的资料里
  一次都没出现 → 句末标「【待核：出自模板写作要求，资料中未见】」，这一句的 [资料n] 去掉。句子留着（D-R153）。
  R3F-e（issue #988）：带圈序号是硬断点、片段末尾的数字回退；只是要素名引子（「…方面，」）的只标引子。
- `backlink` 的引用内数字（cited_number）：句子带 [资料n] 时，句内的数只在**所引的那几份**里查。
- `check_blank_quantity`（blank_quantity）：「约万平米」「由幢」「为项目；」这种量词前缺了数字或名称。

WS24-g（issue #947，缺陷 02-007、02-008 第 8、9 项、02-010）止住误报与裸露：

- `backlink` 的文件名豁免：资料（送入的、未送入的、读不出的）的全名或合格主名整段不参与回链。判断调 WS21-e 的
  共用函数 `guard_filename.exempt_spans`，不另写（总纲 K-R19）。实测「《…一标段1022【待核…】.GBQ7》」把文件名切断。
- `backlink` 的清单编码（unbacked_code）：0 开头的 9 / 12 位数字串按清单编码比主码，调 WS21-e 的 `verify_codes`；
  找得到不标，找不到标「【待核：资料中未找到此编码】」。实测运行 B 第三章 51 个 9 位编码被当普通数标红。
- `strip_todo_citations`：「【待补：…】[资料n]」后面的引用删掉 —— 没写出内容，就没有出处。
- `stop_fact_placeholders`（bad_placeholder）：正文里不在本次已知事实编号集合里的〔Fn〕换成「【待补：金额】」。
  程序取数（WS24-j）上线前集合恒为空。
- `strip_title` 比较时两边开头的序号都去掉（「三、编制依据」下的首行「一、编制依据」也删）。
- `is_mostly_todo`：正文大半是【待补】的章判资料不足（运行 E 535 字 23 处【待补】曾拿到最好的一档）。

## 数字回链为什么比 WS07 的 `unbacked_numbers` 更严（冲突裁决 K26 的领域策略）

数字**识别**复用 WS07 的共用解析器 `amounts.find_numbers` / `amounts.parse_amount`（K26：全仓一份）；
这里只写 WS12 的**判据**。WS07 的判据给容差、做单位换算（原文 9602 与输出「0.96万元」差 2 元在 50 元
容差内算有出处；567855.64 与 567856.44 差 0.8 元在 1 元容差内算有出处）—— 这两例恰好是 P01 生产取证
里的真缺陷（v03 换算、w01 转写差 0.8 元）。决策 D56 定的是「宽松模式：允许与资料原文**逐字一致**的数字」，
所以这里只认「输出里的数（不换算单位）与资料里某个数的十进制值完全相等」，不给容差。

## 位置对齐

共用解析器在 NFKC + 去千分位之后的文本上给位置；标注要插回 LLM 的原文（不能替用户把「329,388元」
改成「329388元」），所以 `_normalize_with_map` 逐字记下「规整后第 i 个字符来自原文第几个字符」。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from zt.amounts.amounts import find_numbers, parse_amount
from zt.report.filename_exempt import exempt_spans as filename_spans
# 清单编码的识别与回链用 WS21-e 的同一份（问答护栏），不另写：同一个 9 位主码，问答里不标、报告里标，就是两套口径。
# zt 改动：问答护栏没有搬进 zt，编码回链那一段搬到 zt.report.codes（逐字照搬）
from zt.report.codes import CODE_RE as _BILL_CODE, verify_codes

# ---------------------------------------------------------------- 标注文案（前端 sectionView.ts 按前缀着色）

MARK_UNBACKED = "【待核：资料中未找到此数】"
MARK_UNBACKED_CODE = "【待核：资料中未找到此编码】"
# 〔Fn〕没有程序取数时换成它（WS24-g 止血）。以「【待补」开头：前端按待补着色，meaningful_chars 不算它
MARK_FACT_TODO = "【待补：金额】"
# WS24-n：写到篇幅上限的章末尾挂这句（api/report.py 挂上；导出附录据此标「未写完」）
MARK_TRUNCATED = "【待补：本章内容超出篇幅上限，后面没有写完】"
MARK_UNREADABLE = "【待核：有资料无法读取，此结论可能不成立】"
MARK_NEGATION = "【待核：资料中未找到此否定结论的依据】"
MARK_META = "【待补：资料未载明本段所需信息，请补充】"
MARK_NO_SOURCE = "【待补：本章缺少相关资料】"
MARK_TEMPLATE_ECHO = "【待核：出自模板写作要求，资料中未见】"
MARK_CITED_NUMBER = "【待核：所引资料中未找到此数】"
MARK_BLANK = "【待核：原文此处缺内容】"
# WS24-j（issue #1002）：〔Fn〕替换（report_facts.substitute_facts）与转写金额另标（D-R65）
MARK_OUT_OF_SCOPE = "【待核：本章不应出现此金额】"
MARK_TRANSCRIBED_AMOUNT = "【待核：AI 转写，非程序取数】"

# 标记本身不参与任何检查（数字护栏不能把自己插进去的【待核…】当成正文再标一遍）
_MARKER_RE = re.compile(r"【[^】\n]*】|\[资料\s*\d+\]|〔F\d+〕")

# ---------------------------------------------------------------- 结果

@dataclass
class GuardFlag:
    # 机器码：unbacked_number / unbacked_code / cited_number / template_echo / raw_placeholder / bad_placeholder /
    # blank_quantity / unreadable_claim / unconfirmed_claim / unsupported_negation / transcribed /
    # transcribed_amount、out_of_scope_amount、fact_conflict（WS24-j）
    kind: str
    text: str           # 命中的原文片段
    message: str
    file_id: Optional[str] = None

    def as_dict(self) -> dict:
        d = {"kind": self.kind, "text": self.text, "message": self.message}
        if self.file_id:
            d["file_id"] = self.file_id
        return d


@dataclass
class EvidenceFile:
    """一份送进模型的资料（截断后的那份：模型没看到的部分不能算出处）。"""
    file_id: str
    file_name: str
    text: str
    kind: str = "source"   # source / finished_report
    # 提示词里的 [资料n] 的 n。没有编号（旧调用方、评测脚本）时引用内的数字退回按全部资料查
    index: Optional[int] = None


@dataclass
class GuardResult:
    content: str
    flags: list[GuardFlag] = field(default_factory=list)
    missing_items: list[str] = field(default_factory=list)
    amount_refs: list[dict] = field(default_factory=list)


# ================================================================ P09：标题与空行

_TITLE_NOISE = re.compile(r"[\s#*_`>|：:、，,.．。（）()\[\]【】\-—]+")
_TITLE_LEAD = re.compile(r"^[\s#*_`>]+")
# 开头的序号（R24-38）：「一、」「三 」「（三）」「(3)」「3.」「3.2 」「第三章」。阿拉伯数字必须带分隔，
# 免得「1#楼概况」被当成序号剥掉
_TITLE_ORDINAL = re.compile(
    r"^(?:[（(][ \t]*[一二三四五六七八九十百\d]{1,4}[ \t]*[）)]"
    r"|第[一二三四五六七八九十百\d]{1,4}[章节部分篇]"
    r"|[一二三四五六七八九十百]{1,4}(?:[ \t]*[、.．]|[ \t]+)"
    r"|\d{1,3}(?:[.．]\d{1,3})*(?:[ \t]*[、.．)）]|[ \t]+))"
)


def title_key(s: str) -> str:
    """章标题的比较键：去掉 markdown 记号、开头的序号、空白与标点。「三、编制依据」与「一、编制依据」得同一个键 ——
    模型把章标题换个序号再写一遍（运行 B 第三章首行），照样是复述标题（R24-38）。导出（report_export）也用它。"""
    s = _TITLE_LEAD.sub("", unicodedata.normalize("NFKC", s or ""))
    return _TITLE_NOISE.sub("", _TITLE_ORDINAL.sub("", s, count=1))


def strip_title(text: str, title: str) -> str:
    """首个非空行在去掉序号、空白、markdown 记号与标点后等于章标题 → 删掉这一行（LLM 爱把标题再写一遍）。
    「一、编制依据如下：…」后面还有字，键不相等，不删。"""
    if not text or not title:
        return text or ""
    key = title_key(title)
    if not key:
        return text
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if title_key(line) == key:
            del lines[i]
        break
    return "\n".join(lines)


def normalize_blank_lines(text: str) -> str:
    """行尾空白去掉、连续空行合并成一个、首尾空行去掉。"""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out: list[str] = []
    for ln in lines:
        if not ln and (not out or not out[-1]):
            continue
        out.append(ln)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


# ================================================================ 句子切分（标注插在句末）

_SENT_END = re.compile(r"[。！？!?；;\n]")


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """[(start, end)]，end 指向句末标点之前（标注插在句末标点之前）。"""
    spans, start = [], 0
    for m in _SENT_END.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans


def _insert_all(text: str, inserts: list[tuple[int, str]]) -> str:
    """按位置插入标注（同一位置的多条保持给定顺序）。"""
    if not inserts:
        return text
    ordered = sorted(enumerate(inserts), key=lambda x: (x[1][0], x[0]))
    out, last = [], 0
    for _, (pos, mark) in ordered:
        out.append(text[last:pos])
        out.append(mark)
        last = pos
    out.append(text[last:])
    return "".join(out)


def _masked(text: str) -> str:
    """标记换成等长的空白：检查时看不见标记，位置又不变。"""
    return _MARKER_RE.sub(lambda m: " " * len(m.group(0)), text)


def _compact(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or ""))


# WS24-o：一句话的引用常写在句末标点之后（「…约定执行。[资料23]」），这一句的引用要连它一起算
_CITE_TAIL_RE = re.compile(r"(?:[ \t]*\[资料\s*\d+\])+")
_CITE_IN_RE = re.compile(r"[ \t]*\[资料\s*\d+\]")


def _cited_sentences(text: str) -> list[tuple[int, int, int]]:
    """[(start, body_end, end)]：句子按屏蔽了标记的文本切（【…】里的「；」不切句）。

    body_end 是句末标点（或换行）的位置，标注插在这里；end 把句末标点后面紧跟的 [资料n] 也算进这一句。
    换行不算进句子：下一句从换行之后开始。空句（两个标点挨着）不返回。
    """
    masked = _masked(text)
    out: list[tuple[int, int, int]] = []
    start = 0
    for m in _SENT_END.finditer(masked):
        if m.start() < start:
            continue  # 落在上一句吃进来的引用里（引用已被屏蔽成空白，正常不会发生）
        body_end = m.start()
        if m.group() == "\n":
            end, nxt = body_end, m.end()
        else:
            tail = _CITE_TAIL_RE.match(text, m.end())
            end = tail.end() if tail else m.end()
            nxt = end
        if text[start:end].strip():
            out.append((start, body_end, end))
        start = nxt
    if start < len(text) and text[start:].strip():
        out.append((start, len(text), len(text)))
    return out


def _strip_cites(seg: str) -> str:
    return _CITE_IN_RE.sub("", seg)


def _cites_in(seg: str) -> set[int]:
    return {int(m.group(1)) for m in _CITE_RE.finditer(seg)}


# ================================================================ P06：AI 元话语

# 只抓「模型在说自己写不了」的句子；「资料未列示分项」这类对资料内容的断言归 P02 管，不在这里改写。
_META_RE = re.compile(
    r"(信息|资料|材料|内容)(明显)?(不足|不全|缺失|有限|欠缺|匮乏)"
    r"|无法(撰写|生成|完成|给出|提供|确定|判断|编写|展开)"
    r"|(未|没有|并未)(能)?(提供|给出)(相关|足够|具体)?(的)?(资料|材料|信息|数据)"
    r"|如实说明"
    r"|(建议|请)(补充|提供|完善)(相关|更多)?(的)?(资料|材料|信息)"
    r"|暂无(相关|可用)?(的)?(资料|信息|数据)"
)


# WS24-f（R24-32）：模型说「资料 n（至资料 m）没提供」。生产实测「【待补：资料1至资料24未提供正文，编制说明原文
# 无法读取】」（运行 B 第十章 7 处）、「【待补：资料1《X_面积统计表.xlsx》未提供】」（运行 D 第四章 10 处），而这些
# 资料在面板上都是「已读取」。诱因（提示词里的未送入名单）已在 report_compose 去掉，这里防模型自己再编。
# 它多半写在【待补：…】里面，所以在**不屏蔽标记**的原文上查；「建设单位未提供签证」这类对资料内容的陈述不命中
# （要求「资料+编号」紧挨着「未提供」）。
_MISSING_SOURCE_RE = re.compile(
    r"\[?资料\s*\d+\]?"
    r"(?:\s*(?:至|到|~|～|—|-|、|和|及|与)\s*\[?(?:资料)?\s*\d+\]?)*"
    r"\s*(?:《[^》\n]*》)?"
    r"\s*(?:均|都|皆)?\s*(?:未|没有|并未|未能)(?:被)?(?:提供|送入|给出)"
)


def _rewrite_missing_source(text: str) -> tuple[str, list[str]]:
    """「资料 n 未提供」所在的句子整句换成「【待补：本章缺少相关资料】」。

    句子按屏蔽了标记的文本切（【…】里的「；」「。」不切句），命中按原文判。
    """
    missing: list[str] = []
    pieces, last = [], 0
    for s, e in _sentence_spans(_masked(text)):
        seg = text[s:e]
        if seg.strip() and _MISSING_SOURCE_RE.search(seg):
            missing.append(seg.strip()[:80])
            pieces.append(text[last:s])
            lead = len(seg) - len(seg.lstrip())
            pieces.append(seg[:lead] + MARK_NO_SOURCE)
            last = e
    pieces.append(text[last:])
    return "".join(pieces), missing


def rewrite_meta_talk(text: str) -> tuple[str, list[str]]:
    """元话语句子整句换成【待补】；返回 (新正文, missing_items)。

    先改写「资料 n 未提供」（换成的标记随后被屏蔽，不会再被下面的规则看见），再改写「本节信息不足」一类。
    """
    text, missing = _rewrite_missing_source(text)
    masked = _masked(text)
    pieces, last = [], 0
    for s, e in _sentence_spans(text):
        seg = masked[s:e]
        if seg.strip() and _META_RE.search(seg):
            missing.append(text[s:e].strip()[:80])
            pieces.append(text[last:s])
            # 行首缩进保留，句子本身换掉
            lead = len(text[s:e]) - len(text[s:e].lstrip())
            pieces.append(text[s:s + lead] + MARK_META)
            last = e
    pieces.append(text[last:])
    return "".join(pieces), missing


# ================================================================ P02：读不出的资料 + 否定性断言

_ABSENCE_CLAIM_RE = re.compile(
    r"未(单独)?(列示|载明|列明|提及|明确|注明|体现|反映|见|说明)|无相关(记载|资料|内容)|(信息|资料)不足"
)


def check_unreadable_claims(text: str, unreadable: Sequence[object]) -> tuple[str, list[GuardFlag]]:
    """有读不出的资料时，「资料未列示…」可能只是没读到：句末加【待核】。unreadable 为空时一律不标。"""
    if not unreadable:
        return text, []
    masked = _masked(text)
    inserts, flags = [], []
    for s, e in _sentence_spans(text):
        m = _ABSENCE_CLAIM_RE.search(masked[s:e])
        if not m:
            continue
        inserts.append((e, MARK_UNREADABLE))
        flags.append(GuardFlag("unreadable_claim", text[s:e].strip()[:80],
                               f"有 {len(unreadable)} 份资料无法读取，「{m.group(0)}」可能只是没读到"))
    return _insert_all(text, inserts), flags


# ================================================================ P07：程序性陈述

DEFAULT_CLAIMS: tuple[dict, ...] = (
    {"key": "full_process_audit", "text": "全过程审核"},
    {"key": "full_process_audit", "text": "全过程跟踪审核"},
    {"key": "site_survey", "text": "现场踏勘"},
    # 「现场查勘」与 yaml 里 guzhi_chengguo 等的 claims 用同一个 key（site_check）：用户在「确认事项」
    # 勾了它，这两条兜底也一并放行。「现场查勘核实」包含「现场查勘」，重叠命中只标最长的那条（见下）。
    {"key": "site_check", "text": "现场查勘"},
    {"key": "site_check", "text": "现场查勘核实"},
    {"key": "field_measure", "text": "实地丈量"},
    {"key": "field_measure", "text": "现场丈量"},
    {"key": "not_counted", "text": "不予计取"},
    {"key": "three_level_review", "text": "三级复核"},
)


def check_claims(text: str, claims: Iterable[dict], confirmed: Iterable[str],
                 evidence_compact: str) -> tuple[str, list[GuardFlag]]:
    """未确认、资料里也没有的程序性陈述 → 紧跟其后加【待核】（spec P07 修法 4）。

    陈述按长度从长到短检查；一处命中如果落在已经标过的更长陈述里（「现场查勘核实」里的「现场查勘」），
    不再重复标 —— 否则标注会插进长陈述中间，变成「现场查勘【待核…】核实【待核…】」。

    长陈述没找到、但它包含的某条短陈述资料里有（资料写「现场查勘记录」，正文写「现场查勘核实」）：
    照标（多出来的「核实」没有依据），但提示写「资料中只见「现场查勘」」，不说「资料中也未见」——
    后者会让人以为资料里一个字都没有。
    """
    confirmed_keys = {c for c in confirmed or () if c}
    seen_text: set[str] = set()
    all_claims = [c for c in (*(claims or ()), *DEFAULT_CLAIMS) if c.get("text")]
    masked = _masked(text)
    inserts, flags = [], []
    marked: list[tuple[int, int]] = []   # 已标注的陈述在原文里的区间
    for c in sorted(all_claims, key=lambda c: -len(c["text"])):
        phrase = c["text"]
        if phrase in seen_text:
            continue
        seen_text.add(phrase)
        if c.get("key") in confirmed_keys or _compact(phrase) in evidence_compact:
            continue
        partial = _longest_contained_in_evidence(phrase, all_claims, evidence_compact)
        why = f"资料中只见「{partial}」" if partial else "资料中也未见"
        for m in re.finditer(re.escape(phrase), masked):
            if _overlaps(m.start(), m.end(), marked):
                continue
            marked.append((m.start(), m.end()))
            inserts.append((m.end(), f"【待核：「{phrase}」未经确认、{why}】"))
            flags.append(GuardFlag("unconfirmed_claim", phrase,
                                   f"「{phrase}」是程序性陈述，用户未确认、{why}"))
    return _insert_all(text, inserts), flags


def _longest_contained_in_evidence(phrase: str, all_claims: Iterable[dict], evidence_compact: str) -> str:
    """phrase 所含的更短陈述里，资料中出现过的最长那条；没有返回空串。"""
    hits = [c["text"] for c in all_claims
            if c["text"] != phrase and c["text"] in phrase and _compact(c["text"]) in evidence_compact]
    return max(hits, key=len, default="")


# ================================================================ P10：全称否定

_NEGATION_RE = re.compile(
    r"(未涉及|不涉及|均无|均未|未发生|不存在|无任何|没有任何|未出现|均不存在)"
    r"(?P<phrase>[^，。；;,.!?！？\n【]{2,16})"
)


def check_negations(text: str, evidence_compact: str) -> tuple[str, list[GuardFlag]]:
    """「未涉及工程量核减」这类结论资料里没有同样的说法 → 加【待核】。

    判据：否定词 + 其后短语的前 4 个字（不足 4 个字取全部）在资料里逐字出现才算有依据。
    """
    masked = _masked(text)
    inserts, flags = [], []
    for m in _NEGATION_RE.finditer(masked):
        phrase = m.group("phrase").strip()
        if len(phrase) < 2:
            continue
        key = _compact(m.group(1) + phrase[:4])
        if key in evidence_compact:
            continue
        inserts.append((m.end(), MARK_NEGATION))
        flags.append(GuardFlag("unsupported_negation", _compact(m.group(0)),
                               "全称否定的结论在资料中没有依据"))
    return _insert_all(text, inserts), flags


# ================================================================ P05：转写成稿报告

TRANSCRIPTION_MIN_CHARS = 30


def check_transcription(text: str, finished: Sequence[EvidenceFile]) -> list[GuardFlag]:
    """与成稿报告有 ≥30 字逐字重合（去空白后）→ transcribed。每份成稿报告只记一条。"""
    if not finished:
        return []
    out_c = _compact(_MARKER_RE.sub("", text))
    n = TRANSCRIPTION_MIN_CHARS
    if len(out_c) < n:
        return []
    windows = {out_c[i:i + n] for i in range(len(out_c) - n + 1)}
    flags = []
    for f in finished:
        src = _compact(f.text)
        for i in range(len(src) - n + 1):
            w = src[i:i + n]
            if w in windows:
                flags.append(GuardFlag("transcribed", w,
                                       f"与成稿报告《{f.file_name}》有 {n} 字以上逐字重合，疑似转写",
                                       file_id=f.file_id))
                break
    return flags


# ================================================================ WS24-o：没有依据的内容（issue #884）

# R24-42：已确认事项没有资料可标，模型把提示词里的块标题当成了编号写进正文（「…现场踏勘[已确认事项]。」）
_CONFIRMED_LABEL_RE = re.compile(r"[ \t]*[\[［【]\s*已确认事项\s*[\]］】]")


def strip_confirmed_label(text: str) -> str:
    """正文里字面的「[已确认事项]」删掉（不是标注，是模型照抄的块标题）。"""
    return _CONFIRMED_LABEL_RE.sub("", text or "")


# 资料里没替换的模板占位符（运行 A 第三章：「…依据的相关资料包括：###相关资料依据###[资料6][资料7]。」）
_PLACEHOLDER_RE = re.compile(r"#{3}[ \t]*([^#\n]{1,40}?)[ \t]*#{3}")


def rewrite_placeholders(text: str) -> tuple[str, list[GuardFlag]]:
    """「###名称###」换成「【待补：名称】」，同一句里的 [资料n] 去掉：占位符不是资料里的事实，引用是假的。"""
    if "###" not in (text or ""):
        return text or "", []
    flags: list[GuardFlag] = []
    pieces, last = [], 0
    for s, _b, e in _cited_sentences(text):
        seg = text[s:e]
        if not _PLACEHOLDER_RE.search(seg):
            continue
        for m in _PLACEHOLDER_RE.finditer(seg):
            flags.append(GuardFlag("raw_placeholder", m.group(0),
                                   f"模板占位符「{m.group(0)}」没有替换成本项目的内容，已换成【待补】"))
        pieces.append(text[last:s])
        pieces.append(_strip_cites(_PLACEHOLDER_RE.sub(lambda m: f"【待补：{m.group(1).strip()}】", seg)))
        last = e
    pieces.append(text[last:])
    return "".join(pieces), flags


# 模板话术回流（spec WS24 §3.15 二-1）。阈值 6 取自实测样本：「赶工保质费用」6 字、「不低于标准费率」7 字、
# 「取费基数为人工费」8 字，整句照抄的 30 字以上
TEMPLATE_ECHO_MIN_HAN = 6
TEMPLATE_ECHO_MIN_SENTENCE = 12
_HAN = re.compile(r"[一-鿿]")
# 行首小标题：以序号开头（（一）、一、、1.、1、、(1)、①），不超过 20 个字、没有句末标点 —— 本来就照模板写
_HEADING_RE = re.compile(
    r"[ \t]*(?:[（(][ \t]*[一二三四五六七八九十百\d]{1,4}[ \t]*[）)]"
    r"|[一二三四五六七八九十百]{1,4}[、.．]"
    r"|\d{1,3}(?:[.．]\d{1,3})*[、.．)）]"
    r"|[①-⑳])"
)
HEADING_MAX_CHARS = 20
# 写在行首、冒号收尾的小标题（「二、土石方渣土外运包干：余方弃置…[资料23]」）：冒号前照模板写，冒号后才是正文
_HEADING_PREFIX_RE = re.compile(_HEADING_RE.pattern + r"[^。！？!?；;：:\n]{0,%d}[：:]" % HEADING_MAX_CHARS)


def _keep_plain(c: str) -> bool:
    return not c.isspace() and not unicodedata.category(c).startswith("P")


# 正文里的标记（[资料n]、〔Fn〕、【…】）换成它：比对时它是硬断点，不会像标点那样被去掉。否则「送审造价〔F6〕[资料5]，
# 审核定案造价〔F7〕[资料5]，核减造价…」去掉标记和标点后连成「…造价核减造价核增造价…」，凭空拼出写作要求里那一串
_SEP = "\x00"

# 带圈、带括号、带点的序号（①–⑳、⑴–⒇、⒈–⒛、❶–❿、㉑–㊿、㈠–㈩、㊀–㊉ 及同一区段的字母）也换成 _SEP，不做 NFKC。
# R3-002：NFKC 把写作要求「…取费基数为人工费＋机械费）；①安全文明…」里的「①」变成「1」，与正文「…机械费137382.74元」
# 的首位「1」连成写作要求里有、资料里没有的「人工费+机械费1」，有出处的金额句被判成模板话术、引用被去掉。
# 也不能整个删掉：它隔开写作要求里的相邻要素，删了「安全文明施工基本费②企业管理费」会连成一个资料里没有的长片段
_ENCLOSED_ORDINAL = re.compile(r"[①-⓿❶-➓㈠-㉟㊀-㊿]")


def _plain_char(ch: str) -> str:
    if _ENCLOSED_ORDINAL.match(ch):
        return _SEP
    return "".join(c for c in unicodedata.normalize("NFKC", ch) if _keep_plain(c))


def _plain(s: str) -> str:
    """去掉空白和标点后的文本（spec：两边都先去掉空白和标点）；带圈序号是硬断点（见 `_ENCLOSED_ORDINAL`）。"""
    return "".join(c for c in unicodedata.normalize("NFKC", _ENCLOSED_ORDINAL.sub(_SEP, s or ""))
                   if c == _SEP or _keep_plain(c))


def _plain_with_map(text: str, start: int, end: int) -> tuple[str, list[int]]:
    """text[start:end] 的 _plain，外加每个字来自 text 的哪个位置（标记已换成 _SEP）。"""
    chars: list[str] = []
    where: list[int] = []
    for p in range(start, end):
        for c in _plain_char(text[p]):
            chars.append(c)
            where.append(p)
    return "".join(chars), where


def _echo_spans(sent: str, prompt: str) -> list[tuple[int, int]]:
    """句子里所有「从某个位置起、尽量长地出现在写作要求里」的片段 [i, j) 中，汉字不少于阈值的那些。

    只比最长的一段不够：「安全文明施工基本费按建筑装饰工程分档累进费率…」里最长的「安全文明施工基本费」资料里有，
    另一段「分档累进费率」却只在写作要求里有。被更早一段完整包住的片段跳过（它是那一段的子串，结论相同）。
    片段不跨 _SEP：写作要求里的带圈序号也是 _SEP，不许拿正文标记处的 _SEP 去对它。
    """
    out: list[tuple[int, int]] = []
    covered = 0
    n = len(sent)
    for i in range(n):
        j = i
        while j < n and sent[j] != _SEP and sent[i:j + 1] in prompt:
            j += 1
        if j > covered and len(_HAN.findall(sent[i:j])) >= TEMPLATE_ECHO_MIN_HAN:
            out.append((i, j))
        covered = max(covered, j)
    return out


# 名目后面紧跟着的值：「审核定案总造价为319786元[资料5]」「审核定案总造价为〔F2〕」。写作要求规定了名目的说法
# （结算审核报告「按模板措辞写审核结果：送审总造价、审核定案总造价…」），资料写的是「审定金额」—— 这句话断言的
# 事实是那个数，数由数字回链和引用内的数字去查，名目本身不算没有依据的话
_LABEL_VALUE_RE = re.compile(
    r"[ \t]*(?:为|是|：|:|合计|共计|计|约)?[ \t]*(?:(?P<num>[0-9０-９][0-9０-９,，.．]*)|〔F\d+〕)")


def _is_label_of_backed_value(text: str, pos: int, ev_numbers: "_EvidenceNumbers") -> bool:
    m = _LABEL_VALUE_RE.match(text, pos)
    if not m:
        return False
    if m.group("num") is None:
        return True  # 〔Fn〕金额占位符（WS24-j 由程序填数）
    raw = unicodedata.normalize("NFKC", m.group("num")).replace(",", "").rstrip(".")
    try:
        return ev_numbers.files_of(Decimal(raw)) is not None
    except ArithmeticError:
        return False


def _is_heading(text: str, s: int, body_end: int, end: int) -> bool:
    line = text[s:body_end]
    at_line_start = s == 0 or text[s - 1] == "\n"
    ends_line = body_end == end and (end == len(text) or text[end] == "\n")
    return (at_line_start and ends_line and len(line.strip()) <= HEADING_MAX_CHARS
            and _HEADING_RE.match(line) is not None)


def _cut_trailing_number(sent: str, i: int, j: int) -> int:
    """片段以数字结尾时回退到片段里最后一个汉字之后（R3-002）。

    那几位数是正文里紧跟着的数的开头，恰好和写作要求里的数字或序号对上了（「…机械费1」+「37382.74」），不是写作要求
    的话；名目豁免也要从回退点取数，否则取到的是被劈掉首位的「37382.74」，查不到。"""
    if j <= i or not sent[j - 1].isdigit():
        return j
    k = j
    while k > i and not _HAN.match(sent[k - 1]):
        k -= 1
    return k


# 要素名引子（R3-002）：「结构形式与耐火、抗震、防水等级口径方面，建筑结构安全等级为二级[资料1]」「安装工程专项方面，
# 地下室给排水工程分部分项工程费为3698058.49元…[资料5]」。引子照写作要求写，后面是有出处的事实
_LEAD_FANGMIAN_RE = re.compile(r"[ \t]*方面(?=[ \t]*[，,：:])")
_LEAD_PUNCT_RE = re.compile(r"[ \t]*[，,：:]")
_LEAD_COLON_RE = re.compile(r"[ \t]*[：:]")


def _lead_mark_at(masked: str, frag: str, pos: int) -> Optional[int]:
    """片段（在正文里结束于 pos）是要素名引子时，返回引子的标注位置（「方面」之后、「，」「：」之前）；不是返回 None。

    只认「方面，」「方面：」和紧跟的「：」。片段后面只跟一个「，」不算：「规费按招标文件载明的费率下限，…」是一句话。"""
    m = _LEAD_FANGMIAN_RE.match(masked, pos)
    if m:
        return m.end()
    if _LEAD_COLON_RE.match(masked, pos) or (frag.endswith("方面") and _LEAD_PUNCT_RE.match(masked, pos)):
        return pos
    return None


def check_template_echo(text: str, gen_prompt: str,
                        evidence: Sequence[EvidenceFile]) -> tuple[str, list[GuardFlag]]:
    """句子里有一段（不少于 6 个汉字）与本章写作要求逐字相同、且这段话在送入的资料里一次都没出现 →
    句末标「【待核：出自模板写作要求，资料中未见】」，去掉这一句的 [资料n]（D-R153：留句子、去引用）。

    不标的三种：片段在资料里出现过（「安全文明施工基本费」写作要求里有，清单里也有）；行首小标题（含冒号前的
    小标题）；片段是一个有出处的数的名目（见 `_LABEL_VALUE_RE`）。片段以数字结尾的先回退到最后一个汉字
    （`_cut_trailing_number`）。

    R3-002：一句里没有出处的片段都是要素名引子（片段后面紧跟「方面，」「：」）时，只在引子后面标，同一分句里
    后面的事实与 [资料n] 不动 —— 引子是照写作要求写的，后面的事实有自己的出处。
    """
    prompt = _plain(gen_prompt)
    if len(prompt) < TEMPLATE_ECHO_MIN_HAN:
        return text, []
    ev = _plain("\n".join(f.text or "" for f in evidence))
    ev_numbers = _EvidenceNumbers(evidence)
    masked = _masked(text)
    sep = _MARKER_RE.sub(lambda m: _SEP * len(m.group(0)), text)
    flags: list[GuardFlag] = []
    pieces, last = [], 0
    for s, b, e in _cited_sentences(text):
        if _is_heading(text, s, b, e):
            continue
        body_start = s
        if s == 0 or text[s - 1] == "\n":
            hp = _HEADING_PREFIX_RE.match(masked, s, b)
            body_start = hp.end() if hp else s
        sent, where = _plain_with_map(sep, body_start, b)
        if len(_MEANINGFUL.findall(sent)) < TEMPLATE_ECHO_MIN_SENTENCE:
            continue
        missing: list[tuple[str, int]] = []   # (片段, 片段在正文里结束的位置)
        for i, j in _echo_spans(sent, prompt):
            k = _cut_trailing_number(sent, i, j)
            frag, after = sent[i:k], where[k - 1] + 1 if k > i else 0
            if len(_HAN.findall(frag)) < TEMPLATE_ECHO_MIN_HAN or frag in ev \
                    or _is_label_of_backed_value(text, after, ev_numbers):
                continue
            missing.append((frag, after))
        if not missing:
            continue
        leads = [_lead_mark_at(masked, frag, after) for frag, after in missing]
        pieces.append(text[last:s])
        if all(p is not None for p in leads):
            at: dict[int, str] = {}
            for (frag, _a), p in zip(missing, leads):
                at.setdefault(p, frag)
            for p, frag in sorted(at.items()):
                flags.append(GuardFlag("template_echo", frag,
                                       f"「{frag}」与本章写作要求逐字相同，送入的资料里没有这段话；只标这段引子，"
                                       "后面的内容与引用不动"))
            pieces.append(_insert_all(text[s:e], [(p - s, MARK_TEMPLATE_ECHO) for p in sorted(at)]))
            last = e
            continue
        frag = max((f for f, _a in missing), key=len)
        flags.append(GuardFlag("template_echo", frag,
                               f"「{frag}」与本章写作要求逐字相同，送入的资料里没有这段话，引用已去掉"))
        body = _strip_cites(text[s:b]).rstrip(" \t")
        pieces.append(body + MARK_TEMPLATE_ECHO + _strip_cites(text[b:e]))
        last = e
    pieces.append(text[last:])
    return "".join(pieces), flags


# 量词前缺内容（运行 A 第一章照抄了带空的模板成稿：「为项目；总建筑面积约万平米…由幢二类高层住宅」）。
# 只认这张小词表；「单位为平方米」「作为项目负责人」「由项目部组织」「设计层高」这类正常说法排除在外
_BLANK_QTY_RE = re.compile(
    r"(?<!单位)(?<!作)(?:约|共|计|为|由)"
    r"(?:万平方米|万平米|平方米|万元|亿元|幢|栋|层(?![高数面])|项目(?=[ \t]*(?:[，。；、,.;：:\n]|$)))"
)


def check_blank_quantity(text: str) -> tuple[str, list[GuardFlag]]:
    """量词或「项目」前面本该有数字或名称却是空的 → 命中处之后标「【待核：原文此处缺内容】」。"""
    masked = _masked(text)
    inserts, flags = [], []
    for m in _BLANK_QTY_RE.finditer(masked):
        inserts.append((m.end(), MARK_BLANK))
        flags.append(GuardFlag("blank_quantity", m.group(0), f"「{m.group(0)}」前面缺了数字或名称"))
    return _insert_all(text, inserts), flags


# ================================================================ WS24-g：【待补】后的引用、〔Fn〕止血（issue #947）

_TODO_THEN_CITE_RE = re.compile(r"(【待补[^】\n]*】)(?:[ \t]*\[资料\s*\d+\])+")


def strip_todo_citations(text: str) -> str:
    """「委托单位：【待补：委托单位】[资料12]」→ 去掉 [资料12]（R24-18：运行 B 第七章 5 处、运行 E 前 6 行）。
    缺的内容没有写出来，挂着的编号不是任何一句话的出处。只删紧跟在【待补】后面的引用，同一句别处的引用不动。"""
    return _TODO_THEN_CITE_RE.sub(r"\1", text or "")


_FACT_PLACEHOLDER_RE = re.compile(r"〔[FＦ](\d+)〕")


def stop_fact_placeholders(text: str, known_facts: Iterable[str] = ()) -> tuple[str, list[GuardFlag]]:
    """正文里的〔Fn〕不在本次已知的事实编号集合里 → 换成「【待补：金额】」，每处记一条 bad_placeholder。

    R24-05（运行 D「五、审核结果」20 个〔F1〕…〔F20〕原样留在正文、不高亮、不计数）。程序取数（WS24-j）上线前
    集合恒为空，全部换掉；j 上线后集合由 facts 给出，在集合里的留给替换 —— 这段代码不用改回。
    known_facts 写「F1」这种编号（大小写、全角都按同一个编号认）。
    """
    known = {f"F{int(m.group(1))}" for k in known_facts or ()
             for m in [re.fullmatch(r"\s*[FfＦｆ]?(\d+)\s*", unicodedata.normalize("NFKC", str(k)))] if m}
    flags: list[GuardFlag] = []

    def _sub(m: re.Match) -> str:
        if f"F{int(m.group(1))}" in known:
            return m.group(0)
        flags.append(GuardFlag("bad_placeholder", m.group(0),
                               f"金额占位符「{m.group(0)}」没有程序取数，已换成{MARK_FACT_TODO}"))
        return MARK_FACT_TODO

    return _FACT_PLACEHOLDER_RE.sub(_sub, text or ""), flags


# ================================================================ P01：数字回链

_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")

# 不参与回链的数（spec P01：日期、行首序号、规范号和文号、〔Fn〕占位符）
_EXEMPT_PATTERNS = (
    # 日期：2024-03-15 / 2024/3/15 / 2024.3.15（年月日写法由共用解析器按「年月日」后缀跳过）
    re.compile(r"(?<![\d.])\d{4}\s*[-/.]\s*\d{1,2}\s*[-/.]\s*\d{1,2}(?![\d.])"),
    re.compile(r"(?<![\d.])\d{4}\s*[-/]\s*\d{1,2}(?![\d./-])"),
    re.compile(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)"),
    # 行首序号：1. / 1、 / (1) / （1） / 1）
    re.compile(r"(?m)^[ \t]*(?:[(（][ \t]*\d{1,3}[ \t]*[)）]|\d{1,3}[ \t]*[.、)）](?!\d))"),
    # 规范号、牌号：GB 50500-2013、GB/T50353-2013、JGJ130、C30、HRB400、m2（RMB/CNY 是币种，不算）
    re.compile(r"(?<![A-Za-z])(?!RMB|CNY|rmb|cny)[A-Za-z]{1,6}(?:/[A-Za-z]{1,3})?[ \t]*\d+(?:[.\-－—]\d+)*"),
    # 文号：〔2018〕61号 / [2018]61 号
    re.compile(r"[〔\[［(（][ \t]*\d{4}[ \t]*[〕\]］)）][ \t]*\d+[ \t]*号?"),
    # 条款号：3.2.1、5.1.2.3
    re.compile(r"(?<![\d.])\d+(?:\.\d+){2,}(?![\d.])"),
)

# 数字后面紧跟的单位：标注插在单位之后，「329元【待核…】」而不是「329【待核…】元」
_UNIT_AFTER = re.compile(r"[ \t]*(?:平方米|立方米|日历天|个月|万元|亿元|㎡|m²|m³|元|天|%|％)")

_CN_AMOUNT_IN_TEXT = re.compile(
    r"[零〇壹贰叁肆伍陆柒捌玖拾佰仟万亿]{2,}[元圆](?:[零壹贰叁肆伍陆柒捌玖]角)?(?:[零壹贰叁肆伍陆柒捌玖]分)?[整正]?"
)


def _normalize_with_map(text: str) -> tuple[str, Optional[list[int]]]:
    """与共用解析器同一种规整（NFKC → 去千分位），并记下规整后每个字符来自原文的哪个位置。

    返回 (规整后的文本, pos)：pos[i] = 规整后第 i 个字符在原文里的下标；pos[len] = len(text)。
    个别字符 NFKC 之后与整串 NFKC 不同（组合字符序列）时对不上，pos 返回 None：调用方改在规整后的
    文本上插标注（正文里的千分位等被规整掉），不会漏标。
    """
    chars: list[str] = []
    pos: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch):
            chars.append(c)
            pos.append(i)
    nfkc = "".join(chars)
    drop = {m.start() for m in _THOUSANDS.finditer(nfkc)}
    norm = "".join(c for j, c in enumerate(nfkc) if j not in drop)
    npos = [p for j, p in enumerate(pos) if j not in drop]
    expected = _THOUSANDS.sub("", unicodedata.normalize("NFKC", text))
    if norm != expected:
        return expected, None
    return norm, npos + [len(text)]


def _exempt_spans(norm: str) -> list[tuple[int, int]]:
    spans = [(m.start(), m.end()) for m in _MARKER_RE.finditer(norm)]
    for pat in _EXEMPT_PATTERNS:
        spans.extend((m.start(), m.end()) for m in pat.finditer(norm))
    return spans


def _overlaps(s: int, e: int, spans: list[tuple[int, int]]) -> bool:
    return any(s < b and a < e for a, b in spans)


def _filename_exempt(norm: str, file_names: Iterable[str]) -> list[tuple[int, int]]:
    """正文里属于某份资料文件名的区间（K-R19 共用函数）。名字按正文同一种规整（NFKC、去千分位）再找一遍：
    正文是规整过的，名字里有全角字符时原样找不到。"""
    names: list[str] = []
    for n in file_names or ():
        n = (n or "").strip()
        if n:
            names.append(n)
            names.append(_THOUSANDS.sub("", unicodedata.normalize("NFKC", n)))
    return filename_spans(norm, names) if names else []


def _code_spans(norm: str, evidence: Sequence[EvidenceFile]) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """清单编码（R24-31）→ (不参与数字回链的区间, 资料里找不到、要标的区间)。

    编码 = 0 开头的 9 位或 12 位数字串（WS21-e 的 `_CODE`，不带 Z 的那种；Z 开头的是牌号写法，早已整体豁免）。
    前后紧挨小数点或千分位的不算编码，是一个带小数的数，照常回链。找没找得到由 `verify_codes` 判：9 位主码与资料里
    12 位编码的前 9 位相等就算找到（模型常把 010101002001 写成 010101002）。不以 0 开头的 9 位数（上亿的金额）
    不是编码，照常回链。前面是「电话」「手机」的 0 开头长串 `verify_codes` 不当编码，这里也不豁免，照常回链。
    """
    cands: list[tuple[int, int]] = []
    for m in _BILL_CODE.finditer(norm):
        s, e = m.span()
        if not norm[s:e].startswith("0"):
            continue
        if (s >= 2 and norm[s - 1] in ".," and norm[s - 2].isdigit()) or \
           (e + 1 < len(norm) and norm[e] in ".," and norm[e + 1].isdigit()):
            continue
        cands.append((s, e))
    if not cands:
        return [], []
    ev_texts = [f.text or "" for f in evidence]
    unverified = {(seg["start"], seg["end"]) for seg in verify_codes(norm, ev_texts).segments}
    # verify_codes 对「电话 0571…」不出 segment：单独再问一遍每个写法，查得到的才是「编码且有出处」
    alone = set(verify_codes("\n".join(norm[s:e] for s, e in cands), ev_texts).unverified)
    exempt = [(s, e) for s, e in cands if (s, e) in unverified or norm[s:e] not in alone]
    return exempt, sorted(unverified & set(cands))


class _EvidenceNumbers:
    """资料里所有数的十进制值（不换算单位），外加每个值出现在哪几份资料。"""

    def __init__(self, files: Sequence[EvidenceFile]) -> None:
        self.raw: dict[Decimal, list[str]] = {}
        self.scaled: set[Decimal] = set()
        for f in files:
            _, mentions = find_numbers(f.text or "")
            for m in mentions:
                v = abs(m.forms[0][0])
                ids = self.raw.setdefault(v, [])
                if f.file_id not in ids:
                    ids.append(f.file_id)
                for form in m.forms:
                    self.scaled.add(abs(form[0]))
            for cm in _CN_AMOUNT_IN_TEXT.finditer(f.text or ""):
                a = parse_amount(cm.group(0))
                if a is not None:
                    self.scaled.add(abs(a.value))

    def files_of(self, value: Decimal) -> Optional[list[str]]:
        return self.raw.get(abs(value))


# 金额的写法：带「元 / 万元 / 亿元」（共用解析器 kind=amount），或前面紧挨「¥」（NFKC 后全角￥也是它）
_YUAN_SIGN_BEFORE = re.compile(r"¥[ \t]*$")


def backlink(text: str, evidence: Sequence[EvidenceFile],
             file_names: Iterable[str] = (), *,
             mark_transcribed: bool = False) -> tuple[str, list[GuardFlag], list[dict]]:
    """查不到出处的数在原位（数字与单位之后）插【待核】。返回 (新正文, flags, amount_refs)。

    - 阿拉伯数字：只认「不换算单位的十进制值」与资料里某个数完全相等（D56 逐字；千分位、全角已规整）。
      正负号不看（「核减1935元」对应资料里的 -1935 算同一个数）。
    - WS24-o（cited_number）：句子带 [资料n] 时只在**所引的那几份**里查；只在别的资料里出现的数标
      「【待核：所引资料中未找到此数】」，amount_refs 只登记所引的资料。句子不带引用的仍按全部资料查。
      资料没带编号（EvidenceFile.index 为空）时没法对上 [资料n]，退回按全部资料查。
    - 中文大写金额：整串逐字出现，或换算成元后与资料里的某个数（含资料自己写的万元换算）相等。
      大写金额不分所引资料（换算值不按资料记），仍按全部资料查。
    - WS24-g：file_names（本次请求里全部资料的文件名：送入的、未送入的、读不出的）里某个名字的全名或合格主名
      在正文里出现，那一段不参与回链（K-R19，带不带书名号都认；「《合同价1022万元的说明》」不是任何资料的名字，
      照查）。清单编码不当普通数查，见 `_code_spans`；资料里找不到的编码标「【待核：资料中未找到此编码】」。
    - WS24-j（D-R65，mark_transcribed）：本章声明了金额事实（facts_allowed 非空）时，**通过了回链**的金额
      （带元 / 万元 / 亿元，或前面是 ¥；大写金额同样）后面再挂「【待核：AI 转写，非程序取数】」，记 transcribed_amount。
      护栏只核对「这个数在资料里出现过」，不核对「它是不是这个意思的数」；程序取数的金额在护栏之后才由
      report_facts.substitute_facts 换进来，不会走到这里。没有 facts_allowed 的章节不标，照旧只做回链。
    """
    ev = _EvidenceNumbers(evidence)
    evidence_compact = _compact("\n".join(f.text or "" for f in evidence))
    id_of_index = {f.index: f.file_id for f in evidence if f.index is not None}
    norm, pos = _normalize_with_map(text)
    base = text
    if pos is None:
        base, pos = norm, list(range(len(norm) + 1))
    names = _filename_exempt(norm, file_names)
    codes, bad_codes = _code_spans(norm, evidence)
    bad_codes = [c for c in bad_codes if not _overlaps(c[0], c[1], names)]
    exempt = _exempt_spans(norm) + names + codes
    _, mentions = find_numbers(norm)
    sentences = _cited_sentences(norm) if id_of_index else []

    def cited_ids_at(p: int) -> Optional[set[str]]:
        """数字所在句子引用的资料 file_id；句子没带引用（或资料没编号）返回 None。"""
        for s, _b, e in sentences:
            if s <= p < e:
                cites = _cites_in(norm[s:e])
                return {id_of_index[n] for n in cites if n in id_of_index} if cites else None
        return None

    inserts: list[tuple[int, str]] = []
    flags: list[GuardFlag] = []
    refs: list[dict] = []
    cn_spans = [(m.start(), m.end()) for m in _CN_AMOUNT_IN_TEXT.finditer(norm)]
    for m in mentions:
        if _overlaps(m.start, m.end, exempt) or _overlaps(m.start, m.end, cn_spans):
            continue
        value = m.forms[0][0]
        files = ev.files_of(value)
        mark = MARK_UNBACKED
        if files:
            cited = cited_ids_at(m.start)
            hit = files if cited is None else [fid for fid in files if fid in cited]
            if hit:
                if len(refs) < 200:
                    refs.append({"raw": m.raw, "value": str(abs(value)), "file_ids": hit[:3]})
                if mark_transcribed and (m.kind == "amount"
                                         or _YUAN_SIGN_BEFORE.search(norm[max(0, m.start - 4):m.start])):
                    inserts.append((pos[m.end], MARK_TRANSCRIBED_AMOUNT))
                    flags.append(GuardFlag("transcribed_amount", m.raw,
                                           f"「{m.raw}」是 AI 从资料里转写的金额，不是程序从单元格取的数"))
                continue
            mark = MARK_CITED_NUMBER
            flags.append(GuardFlag("cited_number", m.raw,
                                   f"「{m.raw}」在所引的资料里找不到（只见于本章送入的其它资料）"))
        else:
            flags.append(GuardFlag("unbacked_number", m.raw, f"「{m.raw}」在资料原文中找不到（不做单位换算）"))
        end = pos[m.end]
        u = _UNIT_AFTER.match(base, end)
        if u and not re.search(r"[%％]|元|万|亿", m.raw[-2:]):
            end = u.end()
        inserts.append((end, mark))

    for a, b in cn_spans:
        if _overlaps(a, b, exempt):
            continue
        raw = norm[a:b]
        amt = parse_amount(raw)
        if _compact(raw) in evidence_compact or (amt is not None and abs(amt.value) in ev.scaled):
            if mark_transcribed:
                inserts.append((pos[b], MARK_TRANSCRIBED_AMOUNT))
                flags.append(GuardFlag("transcribed_amount", raw,
                                       f"大写金额「{raw}」是 AI 从资料里转写的，不是程序从单元格取的数"))
            continue
        inserts.append((pos[b], MARK_UNBACKED))
        flags.append(GuardFlag("unbacked_number", raw, f"大写金额「{raw}」在资料原文中找不到"))

    for a, b in bad_codes:
        code = norm[a:b]
        inserts.append((pos[b], MARK_UNBACKED_CODE))
        flags.append(GuardFlag("unbacked_code", code,
                               f"清单编码「{code}」在送入的资料里找不到（按前 9 位主码比对，资料里的 12 位编码也算）"))

    return _insert_all(base, inserts), flags, refs


# ================================================================ 引用

_CITE_RE = re.compile(r"\[资料\s*(\d+)\]")


def cited_indexes(text: str) -> list[int]:
    seen: list[int] = []
    for m in _CITE_RE.finditer(text or ""):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


# ================================================================ 充分性

INSUFFICIENT_MIN_CHARS = 30
_MEANINGFUL = re.compile(r"[一-鿿A-Za-z0-9]")


def meaningful_chars(text: str) -> int:
    """去掉【待补】【待核】[资料n] 之后的实义字符数（汉字、字母、数字）。"""
    return len(_MEANINGFUL.findall(_MARKER_RE.sub("", text or "")))


# R24-34「资料不足」的第二条口径：【待补】至少 3 处，且平均每处【待补】摊到的实义字不足 40 个。两个阈值只写在这里。
# 取自实测：运行 E 审定单（23 处、实义字 156）、运行 B 第一章（10 处、223）判资料不足；运行 C 第六章（13 处、842）不判
MOSTLY_TODO_MIN_COUNT = 3
MOSTLY_TODO_CHARS_PER_TODO = 40
# 与前端 sectionView.ts 的 MARKER_RE 同一个写法：【】内不跨行
_TODO_RE = re.compile(r"【待补[^】\n]*】")


def todo_count(text: str) -> int:
    """正文里「【待补…】」的处数。"""
    return len(_TODO_RE.findall(text or ""))


def is_mostly_todo(text: str) -> bool:
    """T ≥ 3 且 M ÷ T < 40（T = 【待补】处数，M = 去掉标记后的实义字符数）。全篇【待补】的空表不再拿最好的一档。"""
    t = todo_count(text)
    return t >= MOSTLY_TODO_MIN_COUNT and meaningful_chars(text) < MOSTLY_TODO_CHARS_PER_TODO * t


# ================================================================ 流水线

def guard_section(content: str, *, title: str, evidence: Sequence[EvidenceFile],
                  unreadable: Sequence[object] = (), claims: Iterable[dict] = (),
                  confirmed: Iterable[str] = (), gen_prompt: str = "",
                  file_names: Iterable[str] = (), known_facts: Iterable[str] = (),
                  transcribed_amounts: bool = False) -> GuardResult:
    """一章的完整护栏：标题与空行 → 元话语 →「[已确认事项]」→ 占位符 → 模板话术 →〔Fn〕止血 →【待补】后的引用
    → 数字回链（含引用内的数字、文件名豁免、清单编码）→ 量词前缺内容 → 读不出的资料 → 程序性陈述 → 全称否定 → 转写。

    顺序有讲究：元话语整句换掉之后，剩下的「信息不足」才轮到 P02；之后插入的标注都被 `_MARKER_RE` 屏蔽，
    不会被当成正文再检查一遍。占位符与模板话术排在数字回链之前：它们去掉的是假引用，「引用内的数字」
    不该再拿假引用当依据（去掉引用的句子，句内的数按全部资料查）。gen_prompt 为空（旧 Java 窗口期）时
    不查模板话术。〔Fn〕在模板话术之后才换：「审核定案总造价为〔F2〕」的名目豁免是 WS24-o 定的，止血不改它；
    换成【待补：金额】之后紧跟的 [资料n] 再由 strip_todo_citations 去掉。
    file_names：本次请求全部资料的文件名（文件名豁免，K-R19）；known_facts：程序取数给出的事实编号（WS24-j）——
    在集合里的〔Fn〕留给护栏之后的 report_facts.substitute_facts 去换。transcribed_amounts：本章声明了金额事实
    （facts_allowed 非空）时为真，回链通过的金额另标「AI 转写」（D-R65，见 backlink）。
    """
    text = normalize_blank_lines(strip_title(content or "", title))
    text, missing = rewrite_meta_talk(text)
    text = strip_confirmed_label(text)
    text, ph_flags = rewrite_placeholders(text)
    text, echo_flags = check_template_echo(text, gen_prompt, evidence)
    text, fact_flags = stop_fact_placeholders(text, known_facts)
    text = strip_todo_citations(text)
    text, num_flags, refs = backlink(text, evidence, file_names, mark_transcribed=transcribed_amounts)
    text, blank_flags = check_blank_quantity(text)
    text, unread_flags = check_unreadable_claims(text, unreadable)
    evidence_compact = _compact("\n".join(f.text or "" for f in evidence))
    text, claim_flags = check_claims(text, claims, confirmed, evidence_compact)
    text, neg_flags = check_negations(text, evidence_compact)
    finished = [f for f in evidence if f.kind == "finished_report"]
    trans_flags = check_transcription(text, finished)
    flags = [*ph_flags, *echo_flags, *fact_flags, *num_flags, *blank_flags, *unread_flags, *claim_flags,
             *neg_flags, *trans_flags]
    return GuardResult(content=normalize_blank_lines(text), flags=flags, missing_items=missing,
                       amount_refs=refs)


__all__ = [
    "DEFAULT_CLAIMS",
    "EvidenceFile",
    "GuardFlag",
    "GuardResult",
    "INSUFFICIENT_MIN_CHARS",
    "MARK_BLANK",
    "MARK_CITED_NUMBER",
    "MARK_FACT_TODO",
    "MARK_META",
    "MARK_NEGATION",
    "MARK_NO_SOURCE",
    "MARK_OUT_OF_SCOPE",
    "MARK_TEMPLATE_ECHO",
    "MARK_TRANSCRIBED_AMOUNT",
    "MARK_TRUNCATED",
    "MARK_UNBACKED",
    "MARK_UNBACKED_CODE",
    "MARK_UNREADABLE",
    "MOSTLY_TODO_CHARS_PER_TODO",
    "MOSTLY_TODO_MIN_COUNT",
    "TEMPLATE_ECHO_MIN_HAN",
    "TRANSCRIPTION_MIN_CHARS",
    "backlink",
    "check_blank_quantity",
    "check_claims",
    "check_negations",
    "check_template_echo",
    "check_transcription",
    "check_unreadable_claims",
    "cited_indexes",
    "guard_section",
    "is_mostly_todo",
    "meaningful_chars",
    "normalize_blank_lines",
    "rewrite_meta_talk",
    "rewrite_placeholders",
    "stop_fact_placeholders",
    "strip_confirmed_label",
    "strip_title",
    "strip_todo_citations",
    "title_key",
    "todo_count",
]
