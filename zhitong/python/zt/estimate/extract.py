# 来源：engine-service/app/engine/estimate_extract.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""概算规模指标抽取 —— /engine/estimate/extract 的引擎层（spec I-3.1 前半段）。

zt 改动（两半式，spec §4.1）：中间那步模型调用由 agent 完成。:func:`prepare_text` 给出关键词窗口，
agent 按 :func:`instructions` 逐格给 ``{value, quote, scope}``；:func:`extract_from_text` 只做确定性后处理
（数值解析、引文回原文、单体归位、密度提示），:func:`merge_extractions` 合并多文件。下文的「LLM」即 agent。

红线（违反即作废）：
- **只抽规模量，绝不碰金额**。候选池硬编码为模板 `经济技术指标` 表的 11 个根输入位，
  它们 `kind` 全是 `quantity`、单位只有 ㎡/辆（实测 gsyz_v1.json）。响应体不得出现
  任何金额/费用字段 —— 这是 spec I-3.1 的验收判据，`tests/test_estimate_api.py`
  用全响应体键名扫描断言。
  ⚠ 与《阶段I 接口契约》§3.1「候选覆盖 11 个根输入位 + 4 个可选位」的偏离：
  4 个 optional_inputs 是 `估概算总表!C48/C49`（建设期融资费用、铺底流动资金）
  与其单方指标格 D48/D49 —— 实测模板行 48/49 的 label 就是费用名，**它们是金额**。
  抽了就必然违反"extract 响应无任何金额字段"。故本实现只抽 11 个规模位，
  两条铁律取严者。融资费用/铺底流动资金改由向导第 4 步手填（compute 的 optional 输入）。
- **LLM 不做算术**。LLM 只负责"把原文里的那句话摘出来"，数值由本模块的
  `parse_quantity()` 确定性解析（含 `万`/`亿` 倍率），倍率换算是 Python 乘法不是模型心算。
- **抽取结果必须经用户确认**（铁律 2）：所有候选恒 `needs_manual=True`，
  端点不出任何金额，compute 只吃前端回传的、用户勾过的 inputs。

WS10-A（issue #722）之后的形态：
- **单体清单 + 确定性归位**（P05）：LLM 列出原文所有单体，引擎按出现顺序归到模板的
  固定槽位（D46 延续裁决 5），超出槽位的落 `unmapped_building`，不再静默截成 3 栋；
  槽位合计与原文总建筑面积差 >1% 出 `area_total_mismatch`。
- **父级语义进 prompt**（P08）：每格带路径、口径定义、同义词、分组；原文只有总量时
  放分组首位并带说明，其余位落 `total_only_no_partition`。
- **一格多值即 ambiguous**（P09）：同一格出现不同数值（单文件也算）一律不自行选择，
  明细保留完整小数并附引文。

WS10-B（issue #761）之后：
- **引文核数值**（P10）：引文回原文比对改用 `evidence_check.norm_text`（保数值归一化，总纲 K26：
  全仓只此一份），不再把小数点、逗号、连字符一起删掉；另核 value 是否等于引文里某个数（按该数
  自己的万/亿倍率），两项都过才给 confidence 1.0；引文不含本位标签 / 同义词记 mapping=semantic。
  （旧仓此处的模型调用经 `chat_json`；zt 没有模型调用，回答由 agent 给出，见模块头的「zt 改动」。）
- **关键词窗口**（P12）：正文超预算时按策略锚点取窗口，不再静默截前 12000 字；响应带 text_stats。

WS29-d（issue #1010）之后：
- **单体不丢**：面积为空的单体也保留（`area: null, area_missing: true`），不自动归位、不计入合计，
  出 `building_area_missing`；单体名的引文在原文里找不到的才丢弃，原因记进 text_stats。
  面积核验不过（含「16层」这种层数当面积）的单体不自动归位。text_stats 记 building_count_raw
  （过滤前模型列了几个），分得清「模型没列」和「列了被丢」。
- **建筑密度只作占地提示**：只认百分数写法；推算值 = 用地面积 × 密度由代码算，挂在占地那一行
  「未取到」的 `derived` 上，**不进候选**（铁律 2）。
- 输出预算读策略 `extract_max_tokens`（6000，D-R119）；「未取到」详情写文件名，不写内部编号。
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from zt.amounts import amounts
from zt.estimate import evidence as evidence_check
from zt.estimate import policy as estimate_policy
from zt.estimate.engine import load_template

log = logging.getLogger("zt.estimate.extract")

ROOT_SHEET = "经济技术指标"

# 单次 LLM 调用的正文预算（字符）。超过预算时不再截文首，改按关键词取窗口（P12）。
MAX_TEXT_CHARS = 12000
# 每个关键词命中点前后各取多少字（P12）
WINDOW_RADIUS = 1200

# WS10-P10：输出预算。不给 max_tokens 时触顶只会把 JSON 截半截回来，被当成「解析不出」
# 甚至「这份文件没有指标」。真触顶抛 LLMTruncated → 502。WS29-d：保留无面积单体后 24 个单体加引文
# 约 2300~2700 token，3000 贴线；预算改读策略 extract_max_tokens（D-R119：6000），这里只是策略缺席时的退路。
EXTRACT_MAX_TOKENS = estimate_policy.DEFAULT_EXTRACT_MAX_TOKENS
# 改提示词必须升这个号（tests/estimate/test_estimate_extract_prompt.py 按指纹钉住）。
# v3 = WS29-d（无面积单体也列、密度、引文长度）。zt 改动：改为 agent 作答——正文另存文件、
# 回答写进 answers 文件按 file_id 分份，措辞随之改动，升为 v3-zt1。
ESTIMATE_PROMPT_VERSION = "estimate-extract/v3-zt1"

# 仍保留给「单体名去重」这类**文本**键用；数值比对一律走 evidence_check.norm_text（P10）
_PUNCT = re.compile(r"[\s　，。、；：“”‘’（）()《》〈〉【】\[\]{}—\-·…~,.;:!?'\"]+")

# 数值 + 可选中文倍率。只认这三种倍率，别的（"平米"之类的单位词）不参与换算。
_NUM = re.compile(r"(-?\d[\d,，]*(?:\.\d+)?)\s*(万亿|亿|万)?")
_SCALE = {None: 1.0, "": 1.0, "万": 1e4, "亿": 1e8, "万亿": 1e12}
# 区间连接符：`1~2万` / `1-2万` / `1至2万` —— 前一个数继承末尾倍率（P10）
_RANGE_TAIL = re.compile(r"\s*(?:~|～|〜|-|—|–|至|到)\s*(-?\d[\d,，]*(?:\.\d+)?)\s*(万亿|亿|万)")
_QUOTE_RANGE_SEP = re.compile(r"^\s*(?:~|～|〜|-|—|–|至|到)\s*$")
_UNIT_SCALE = {"万": Decimal(10_000), "万元": Decimal(10_000),
               "亿": Decimal(100_000_000), "亿元": Decimal(100_000_000)}
_LEADING_NUM = re.compile(r"^[-−]?\d+(?:\.\d+)?")


class AnswerUnparseable(ValueError):
    """agent 的回答形状不对（不是对象、缺 buildings / checks / cells）。

    zt 改动：旧 ``LLMOutputUnparseable`` 走 502；现在 CLI 映射成退出码 2（invalid_answers），
    绝不当成「这份文件没有指标」交出空候选（空候选对造价员是误导性成功）。"""


def _norm(s: str) -> str:
    return _PUNCT.sub("", s or "")


def root_input_specs(template_code: str = "gsyz_v1") -> list[dict]:
    """模板里 `经济技术指标` 表的输入位声明（实测 11 条，即 compute 的必填位）。

    直接读模板，不硬编码坐标 —— 模板改了这里跟着改，不会出现"端点抽 11 个、
    compute 要 12 个"的漂移。
    """
    tpl = load_template(template_code)
    return [
        {
            "cell": i["cell"],
            "label": i.get("label") or "",
            "unit": i.get("unit"),
            "seq": i.get("seq"),
        }
        for i in tpl["inputs"]
        if i["cell"].startswith(ROOT_SHEET + "!")
    ]


def parse_quantity(raw) -> float | None:
    """把 LLM 摘回来的字符串确定性地解析成数值；解析不出返回 None。

    认：`12000` / `12,000` / `1.2万` / `1.2 万` / `12000.5`（含全角逗号）。
    区间写法取第一个数，并**继承末尾倍率**（P10）：`1~2万` → 10000，不是 1。
    不认：纯文字、带运算符的表达式。
    ⚠ 取第一个数值 token：`约 12000㎡（含地下 3000㎡）` → 12000。这是刻意的
    "取主值"策略，配合 needs_manual=True 由用户复核，不做二义性猜测。
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if not isinstance(raw, str):
        return None
    m = _NUM.search(raw)
    if not m:
        return None
    digits = m.group(1).replace(",", "").replace("，", "")
    try:
        val = float(digits)
    except ValueError:
        return None
    scale = m.group(2)
    if not scale:
        tail = _RANGE_TAIL.match(raw, m.end())
        if tail:
            scale = tail.group(2)
    return val * _SCALE[scale]


# ------------------------------------------------------------------ 引文核验（WS10-P10）
#
# 此前 confidence 只看「引文去标点后是否在原文里」，而去标点把 `.` `,` `-` 一起删了：
# 原文「95666.98」与引文「9566.698」归一化后都是「9566698」，差 10 倍照样 1.0；
# value 本身从不和引文比。现在两项都核，数值比对全仓只用 evidence_check / amounts 那一份（K26），
# 这里只写本领域的策略（倍率按引文里那个数自己的单位、区间继承末尾倍率、本位标签）。


def _quote_numbers(quote: str) -> list[tuple[Decimal, Decimal]]:
    """引文里每个数按**它自己的**倍率解析后的值 → [(值, 精度)]。

    `9.57万㎡` → 95700（不是 9.57）；`1~2万` 的 1 继承末尾倍率 → 10000。
    """
    text, mentions = amounts.find_numbers(quote or "")
    out: list[tuple[Decimal, Decimal]] = []
    for i, m in enumerate(mentions):
        base, prec, _money = m.forms[0]
        scale = _mention_scale(m.raw)
        if scale == 1 and i + 1 < len(mentions):
            nxt = mentions[i + 1]
            if _QUOTE_RANGE_SEP.match(text[m.end:nxt.start]):
                scale = _mention_scale(nxt.raw)
        out.append((base * scale, prec * scale))
    return out


def _mention_scale(raw: str) -> Decimal:
    return _UNIT_SCALE.get(_LEADING_NUM.sub("", raw or "", count=1), Decimal(1))


def _value_in_quote(value: float, quote: str | None) -> bool:
    try:
        v = Decimal(repr(float(value)))
    except (InvalidOperation, ValueError, TypeError):
        return False
    for q, prec in _quote_numbers(quote or ""):
        # 严格相等（只容浮点毛刺）：引文写 95666.98、value 给 9566.698 就是不等，不按精度放宽
        tol = max(Decimal("1e-6"), abs(q) * Decimal("1e-9"))
        if abs(v - q) <= tol:
            return True
    return False


def _plain(s: str | None) -> str:
    # 只给「引文里有没有本位标签」这种**文本**判断用；数值不走这里
    return _PUNCT.sub("", unicodedata.normalize("NFKC", s or ""))


def verify_candidate(value: float | None, quote: str | None, source_norm: str,
                     labels: list[str] | tuple[str, ...]) -> dict:
    """一条候选 → verification{quote_in_source, value_in_quote, mapping}。

    - quote_in_source：引文经保数值归一化后是原文的连续片段（evidence_check.quote_in_source）；
    - value_in_quote：value 等于引文里某个数按其自身倍率解析的值；
    - mapping：引文里出现本位标签 / 路径 / 同义词之一 → label，否则 semantic（模型凭语义映射，
      前端「全选」不勾它）。
    `source_norm` = `evidence_check.norm_text(整份原文)`。
    """
    q = quote if isinstance(quote, str) else ""
    in_source = bool(q.strip()) and evidence_check.quote_in_source(q, source_norm)
    in_quote = value is not None and bool(q.strip()) and _value_in_quote(value, q)
    pq = _plain(q)
    has_label = any(_plain(lb) and _plain(lb) in pq for lb in labels if lb)
    return {"quote_in_source": bool(in_source), "value_in_quote": bool(in_quote),
            "mapping": "label" if has_label else "semantic"}


def _confidence(verification: dict) -> float:
    # 二值核验标记，不是概率：两项都过才 1.0（P10）；单体另核「引文里这个数是不是面积」（WS29-d）
    return 1.0 if (verification["quote_in_source"] and verification["value_in_quote"]
                   and verification.get("value_is_area", True)) else 0.0


# WS29-d：引文里这个数后面紧跟这些字，说明它是层数 / 栋数 / 户数 / 高度 / 比例，不是面积。
# 只看紧跟的那个字：「1000平方米」后面是「平」，照样是面积；「m2」「m²」是面积，单个「m」是高度。
_NOT_AREA_AFTER = re.compile(r"^\s*(?:层|[Ff](?![A-Za-z])|栋|幢|户|套|辆|个|部|米|[mM](?![2²])|%|％)")


def _value_is_area(value: float, quote: str | None) -> bool:
    """引文里与 value 相等的数，只要有一处后面跟的不是层 / 栋 / 户 / 米…，就认它是面积。

    实测形态（08-013 / E05 的另一种）：楼号表面积列为空，模型把「16层」的 16 填进 area，
    原核验（引文在原文、数在引文里）两项都过，按出现顺序归进了 1#楼 槽位。
    引文里根本没有这个数时回 True —— 那种由 value_in_quote 判不过，不在这里重复。
    """
    try:
        v = Decimal(repr(float(value)))
    except (InvalidOperation, ValueError, TypeError):
        return True
    text, mentions = amounts.find_numbers(quote or "")
    matched = False
    for m in mentions:
        base = m.forms[0][0] * _mention_scale(m.raw)
        if abs(v - base) > max(Decimal("1e-6"), abs(base) * Decimal("1e-9")):
            continue
        matched = True
        if not _NOT_AREA_AFTER.match(text[m.end:]):
            return True
    return not matched


# WS29-d：建筑密度只认百分数。「建筑密度」后面隔着不超过 12 个非数字字符（制表符、冒号、≤、不大于…），
# 紧跟一个数和 % / ％。不带百分号的小数（0.3）不认：猜它是 0.3% 还是 30% 都是替人编数（铁律 3）。
_DENSITY = re.compile(r"建筑密度[^\d\n]{0,12}?(\d+(?:\.\d+)?)\s*[%％]")
_DENSITY_LABEL_NUM = re.compile(r"建筑密度[^\d\n]{0,12}?\d")


def parse_density(text: str | None) -> float | None:
    """「建筑密度 30%」「建筑密度≤30％」「建筑密度\\t\\t30%」→ 30.0；其余（含 0.3、130%）→ None。

    不能用 parse_quantity：它会把「建筑密度 0.3」解析成 0.3，推算出的占地差 100 倍。
    """
    m = _DENSITY.search(unicodedata.normalize("NFKC", text or ""))
    if not m:
        return None
    v = float(m.group(1))
    return v if 0 < v <= 100 else None


def _file_label(file_id: str | None, file_name: str | None) -> str:
    """给人看的文件名。拿不到时写「文件（编号后 6 位）」—— 19 位雪花编号对造价员没有意义（08-012 第 9 项）。"""
    if isinstance(file_name, str) and file_name.strip():
        return file_name.strip()
    fid = str(file_id or "")
    return f"文件（{fid[-6:]}）" if fid else "文件"


def _cell_labels(spec: dict) -> list[str]:
    parts = [p.strip() for p in (spec.get("path") or "").split(">")]
    return [spec.get("label") or "", *parts, *(spec.get("synonyms") or [])]


def _check_labels(check: dict) -> list[str]:
    return [check.get("label") or "", *(check.get("synonyms") or [])]


# ------------------------------------------------------------------ 关键词窗口（WS10-P12）
#
# 此前正文一律截前 12000 字：B 文件 115123 字，LLM 只看到 10.4%，响应里没有任何截断标记。
# 现在超预算时按策略锚点取前后各 WINDOW_RADIUS 字的窗口，合并后按原文顺序拼接，余量补文首；
# 一个锚点都没命中才退回截文首。strategy 与命中的锚点随 text_stats 回给调用方。

_GAP = "\n……\n"


def select_window(text: str, anchors: list[str] | tuple[str, ...],
                  budget: int = MAX_TEXT_CHARS, radius: int = WINDOW_RADIUS) -> tuple[str, dict]:
    """→ (送给 LLM 的正文, stats{text_chars, window_chars, truncated, strategy, anchors_hit})。"""
    text = text or ""
    n = len(text)
    if n <= budget:
        return text, {"text_chars": n, "window_chars": n, "truncated": False,
                      "strategy": "full", "anchors_hit": []}
    hits: dict[str, list[int]] = {}
    for a in dict.fromkeys(a for a in anchors if a):
        pos = [m.start() for m in re.finditer(re.escape(a), text)]
        if pos:
            hits[a] = pos
    if not hits:
        body = text[:budget]
        return body, {"text_chars": n, "window_chars": len(body), "truncated": True,
                      "strategy": "head", "anchors_hit": []}
    # 先每个锚点的首次出现（按位置），再其余出现 —— 不让某一个高频词吃光预算
    firsts = sorted(p[0] for p in hits.values())
    rest = sorted(x for p in hits.values() for x in p[1:])
    spans: list[tuple[int, int]] = []
    for p in firsts + rest:
        trial = _merge_spans(spans + [(max(0, p - radius), min(n, p + radius))])
        if _span_len(trial) <= budget:
            spans = trial
            continue
        room = budget - _span_len(spans)
        if room > 0:
            # 放不下整窗：以命中点为中心截一段（仍盖住关键词本身），然后预算用尽
            s = max(0, min(p - room // 2, n - room))
            spans = _merge_spans(spans + [(s, s + room)])
        break
    room = budget - _span_len(spans)
    if room > 0:
        # 余量补文首（项目概况、经济技术指标表常在文首）；与已有窗口重叠只会更短，不会超预算
        spans = _merge_spans(spans + [(0, room)])
    merged = spans
    body = _GAP.join(text[s:e] for s, e in merged)
    return body, {"text_chars": n, "window_chars": sum(e - s for s, e in merged),
                  "truncated": True, "strategy": "keyword_windows",
                  "anchors_hit": sorted(hits, key=lambda a: hits[a][0])}


def _span_len(spans: list[tuple[int, int]]) -> int:
    return sum(e - s for s, e in spans)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


# ------------------------------------------------------------------ 抽取口径（WS10-P08）
#
# 此前 prompt 每行只有「格｜叶子标签｜单位」：D15 的标签是「A区地块」，模型看不出它是
# 「占地面积」下面的一格，于是原文写明的建筑占地面积、地下面积报成 not_found，
# 室外面积（D17 = D4 − D14）按整块用地计，多算约 86%。
# 现在每格带父级路径、口径定义、同义词与分组（策略 extract_hints），策略没写的格
# 退回模板行树推出的路径 —— 至少不再只有叶子名。


def _row_tree_path(template_code: str, cell: str) -> str:
    """模板行树里 cell 所在行的「父 > 子」路径（level 链），给没写 extract_hints 的格兜底。"""
    tpl = load_template(template_code)
    sheet, coord = cell.split("!", 1)
    row_no = int("".join(ch for ch in coord if ch.isdigit()))
    rows = next((s["rows"] for s in tpl["sheets"] if s["name"] == sheet), [])
    chain: list[str] = []
    want_level = None
    for r in reversed([r for r in rows if r["row"] <= row_no]):
        lvl = r.get("level")
        if not isinstance(lvl, int) or not r.get("label"):
            continue
        if want_level is None:
            chain.append(r["label"])
            want_level = lvl
        elif lvl < want_level:
            chain.append(r["label"])
            want_level = lvl
        if want_level == 1:
            break
    return " > ".join(reversed(chain))


def cell_hint_specs(template_code: str = "gsyz_v1", policy: dict | None = None) -> list[dict]:
    """逐格抽取的格（根输入位去掉单体槽位）+ 口径说明。单体槽位走「单体清单 + 归位」。"""
    pol = estimate_policy.load_policy(template_code) if policy is None else policy
    hints = {h["cell"]: h for h in estimate_policy.extract_hints(pol)}
    slots = set(estimate_policy.slot_cells(pol))
    out = []
    for s in root_input_specs(template_code):
        if s["cell"] in slots:
            continue
        h = hints.get(s["cell"]) or {}
        out.append({
            **s,
            "path": h.get("path") or _row_tree_path(template_code, s["cell"]) or s["label"],
            "definition": h.get("definition"),
            "synonyms": list(h.get("synonyms") or []),
            "group": h.get("group"),
        })
    return out


def instructions(cell_specs: list[dict], checks: list[dict], with_buildings: bool) -> str:
    """抽取说明（不含正文）：规则、单体清单、总量、逐格指标与回答格式。

    zt 改动：旧 ``_prompt`` 把说明与正文拼成一条 LLM 消息；现在正文另存为 ``概算抽取正文-NN.txt``，
    agent 读完把每份文件的回答写进 answers 文件（见 :data:`ANSWER_FORMAT`）。

    :param cell_specs: :func:`cell_hint_specs`。
    :param checks: 策略里的总量与指标。
    :param with_buildings: 模板有单体槽位时为 True。
    :returns: 文本。
    """
    cell_lines = []
    for s in cell_specs:
        unit = f"（单位 {s['unit']}）" if s.get("unit") else ""
        parts = [f"- {s['cell']}｜{s['path']}{unit}"]
        if s.get("definition"):
            parts.append(f"口径：{s['definition']}")
        if s.get("synonyms"):
            parts.append("同义词：" + "、".join(s["synonyms"]))
        if s.get("group"):
            parts.append(f"分组：{s['group']}")
        cell_lines.append("｜".join(parts))
    check_lines = [f"- {c['key']}：{c['label']}"
                   + (f"（同义词：{'、'.join(c['synonyms'])}）" if c.get("synonyms") else "")
                   + (f"｜{c['prompt_note']}" if c.get("prompt_note") else "")
                   for c in checks]
    sections = []
    if with_buildings:
        # WS29-d（08-013 第 1 项）：楼号表 25 行只有地下室有面积，旧提示词下 buildings 只出了地下室。
        # 面积为空的单体也要列（area 给 null），由引擎保留并标「原文无面积」；不许拿层数等别的列顶替
        sections.append(
            "一、buildings —— 逐个列出原文里的每一个单体（地下室、各栋楼、构筑物；常见于「楼号」「栋号」"
            "「单体」「子项」开头的明细表）。原文有多少个就列多少个，**不要合并、不要只挑前几个**。"
            "**面积为空的单体也要列出，area 给 null**（例如明细表的建筑面积列空着）；"
            "不要拿层数、高度、高差、户数等其它列的数顶替面积。每项：\n"
            '  {"name": 原文单体名, "level": "underground"（地下）| "above_ground"（地上楼栋）'
            '| "structure"（构筑物）, "function": 原文用途或 null, "area": 该单体建筑面积或 null, '
            '"quote": 原文片段（有面积时摘含面积的那一小段，没有面积时摘含单体名的那一小段）}')
    if check_lines:
        sections.append(
            "二、checks —— 原文写明的总量与指标（原文没写的键不要给）；每个键的值是数组 "
            '[{"value": ..., "quote": ...}]：\n' + "\n".join(check_lines))
    sections.append(
        "三、cells —— 逐格指标（路径｜口径｜同义词｜分组）：\n" + "\n".join(cell_lines) + "\n"
        '  每格的值是数组 [{"value": ..., "quote": ..., "scope": "partition" | "total"}]，原文没有就给 []。'
        "scope：该数值就是这一格本身时填 partition；原文只给了整组总量、不分区（例如只写"
        "「建筑占地面积」不分 A/B 地块）时填 total，放在该组任意一格即可。")
    return (
        "你是工程造价资料抽取助手。下面是一份建设项目设计说明/可研的正文。"
        "本次只抽**规模量**（面积、车位数一类的数量），不是金额。\n\n"
        "规则：\n"
        "1) 只抄原文，不概括、不换算、不推算、不编造。原文没有的就不写。\n"
        "2) quote 必须是能在正文里逐字找到的原文片段（机器要拿它回原文校验），只摘含该数值的那一小段，"
        "不超过 40 字。\n"
        "3) value / area 只填数字本身（可带 万/亿 后缀，如 `1.2万`；百分数照原文带 %），不带单位、不带文字说明。\n"
        "4) 同一项在原文里出现多个不同数值时，**全部列出**（各带自己的 quote），不要自行选择。\n"
        "5) 严禁输出任何金额、造价、费用数字 —— 本次只要规模量。\n\n"
        + "\n\n".join(sections)
        + "\n\n" + ANSWER_FORMAT
    )


# zt 改动：旧版要求「只输出一个 JSON 对象」；现在每份正文一个对象，按 file_id 写进同一个 answers 文件
ANSWER_FORMAT = ("回答写进一个 answers JSON 文件，每份正文一个对象，file_id 照抄正文文件头里的 file_id："
                 "{\"files\": [{\"file_id\": ..., \"buildings\": [...], \"checks\": {...}, \"cells\": {...}}]}，"
                 "不要解释、不要代码块。")


def _prompt(text: str, cell_specs: list[dict], checks: list[dict], with_buildings: bool) -> str:
    """说明 + 正文（调用方已按预算取好窗口，P12，这里不再二次截断）。

    :param text: 窗口正文。
    :param cell_specs: :func:`cell_hint_specs`。
    :param checks: 总量与指标。
    :param with_buildings: 是否列单体。
    :returns: 完整提示文本（指纹测试用）。
    """
    return instructions(cell_specs, checks, with_buildings) + f"\n\n正文：\n{text}"


def validate_answer(d) -> dict:
    """一份文件的回答必须是带 buildings / checks / cells 之一的对象。

    zt 改动：旧 ``_parse_llm_json`` 从模型文本里找 JSON；现在收 JSON 值，只校验形状。

    :param d: 回答。
    :returns: 原对象。
    :raises AnswerUnparseable: 不是对象，或三个键一个都没有（形状不对不是「这份文件没有指标」）。
    """
    if not isinstance(d, dict):
        raise AnswerUnparseable("回答不是 JSON 对象")
    if not any(k in d for k in ("buildings", "checks", "cells")):
        raise AnswerUnparseable("回答缺 buildings / checks / cells 键")
    return d


def _as_list(v) -> list:
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return [v]
    return []


def _hit(file_id: str, text_source: str, norm_src: str, raw: dict, labels: list[str],
         value_key: str = "value", file_name: str | None = None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    value = parse_quantity(raw.get(value_key))
    if value is None:
        # LLM 说有、但摘回来的不是可解析数值 —— 不猜，交给 merge 归 not_found
        return None
    quote = raw.get("quote") if isinstance(raw.get("quote"), str) else None
    verification = verify_candidate(value, quote, norm_src, labels)
    return {
        "value": value,
        "quote": quote,
        "source_file_id": file_id,
        # WS29-d：多值行、「未取到」详情给人看的是文件名（08-012 第 9 项）；不进候选与 check_values
        "source_file_name": file_name,
        "text_source": text_source,
        "verification": verification,
        # 二值核验标记，不是概率：引文在原文 且 value 在引文里（P10）
        "confidence": _confidence(verification),
    }


def extract_anchors(template_code: str = "gsyz_v1", policy: dict | None = None) -> list[str]:
    """关键词窗口的锚点（P12）：策略显式列的 + 各抽取位 / 总量的同义词。"""
    pol = estimate_policy.load_policy(template_code) if policy is None else policy
    words = list(estimate_policy.extract_anchors(pol))
    for h in estimate_policy.extract_hints(pol):
        words.extend(h.get("synonyms") or [])
    for c in estimate_policy.extract_checks(pol):
        words.extend([c.get("label") or "", *(c.get("synonyms") or [])])
    return [w for w in dict.fromkeys(w.strip() for w in words) if len(w) >= 2]


def extract_max_tokens(template_code: str = "gsyz_v1", policy: dict | None = None) -> int:
    """单次抽取调用的输出预算：读策略 extract_max_tokens（D-R119：6000）。端点 502 文案也用它。"""
    pol = estimate_policy.load_policy(template_code) if policy is None else policy
    return estimate_policy.extract_max_tokens(pol)


def prepare_text(file_id: str, text: str, text_source: str = "text_layer", template_code: str = "gsyz_v1",
                 *, file_name: str | None = None) -> dict:
    """单份正文 → 交给 agent 的窗口与统计（P12 关键词窗口）。

    zt 改动：旧 ``extract_from_text`` 前半段（取窗口）拆出来给 extract_prepare 用。

    :param file_id: 文件标识（zt 用项目内相对路径）。
    :param text: 整份正文。
    :param text_source: 正文来源。
    :param template_code: 模板编码。
    :param file_name: 给人看的文件名。
    :returns: ``{file_id, file_name, text_source, window, window_sha256, text_stats}``。
    """
    pol = estimate_policy.load_policy(template_code)
    window, stats = select_window(text or "", extract_anchors(template_code, pol))
    return {"file_id": file_id, "file_name": file_name, "text_source": text_source, "window": window,
            "window_sha256": hashlib.sha256(window.encode("utf-8")).hexdigest(),
            "text_stats": {"file_id": file_id, "file_name": file_name, **stats}}


def extract_from_text(
    file_id: str, text: str, answer: dict | None, specs: list[dict] | None = None,
    text_source: str = "text_layer", template_code: str = "gsyz_v1", *, file_name: str | None = None,
) -> dict:
    """单份文档正文 + agent 对这份正文的回答 → 本文件的抽取结果（未合并）。

    extraction = {file_id, file_name, text_source, text_chars, truncated, text_stats,
                  cells: {cell: [hit]}, buildings: [..], checks: {key: [hit]}, density: [..]}
    hit = {value, quote, source_file_id, source_file_name, text_source, verification, confidence[, scope]}
    `specs` 参数保留给老调用方，内容以模板 + 策略为准（抽 11 个 → 算 11 个不会漂移）。

    zt 改动：旧版在这里调模型（chat_json）；现在回答由 agent 给出（``answer``），本函数只做确定性后处理：
    数值由 :func:`parse_quantity` 解析、引文回**整份原文**核、单体名引文核、建筑密度从引文解析。

    :param file_id: 文件标识。
    :param text: 整份正文。
    :param answer: agent 的回答（{buildings, checks, cells}）；None 视为空回答。
    :param specs: 兼容旧签名，不使用。
    :param text_source: 正文来源。
    :param template_code: 模板编码。
    :param file_name: 给人看的文件名。
    :returns: 抽取结果。
    :raises AnswerUnparseable: 回答形状不对。
    """
    pol = estimate_policy.load_policy(template_code)
    cell_specs = cell_hint_specs(template_code, pol)
    checks = estimate_policy.extract_checks(pol)
    density_cfg = estimate_policy.density_check(pol)
    window, stats = select_window(text or "", extract_anchors(template_code, pol))
    # WS29-d：可观测 —— 模型列了几个单体（过滤前 / 后）、丢掉的原因
    stats = {**stats, "building_count_raw": 0, "building_count": 0, "buildings_dropped": []}
    out = {"file_id": file_id, "file_name": file_name, "text_source": text_source,
           "text_chars": stats["text_chars"], "truncated": stats["truncated"],
           "text_stats": {"file_id": file_id, "file_name": file_name, **stats},
           "cells": {}, "buildings": [], "checks": {}, "density": []}
    if not text or not text.strip():
        return out
    parsed = validate_answer(answer if answer is not None else {"cells": {}})
    st = out["text_stats"]
    # 引文回**整份原文**核（不只是窗口）：窗口是给模型看的，核验的是「原文里有没有这句话」
    norm_src = evidence_check.norm_text(text)

    cells_raw = parsed.get("cells") if isinstance(parsed.get("cells"), dict) else {}
    for s in cell_specs:
        hits = []
        for raw in _as_list(cells_raw.get(s["cell"])):
            h = _hit(file_id, text_source, norm_src, raw, _cell_labels(s), file_name=file_name)
            if h is None:
                continue
            h["scope"] = "total" if raw.get("scope") == "total" else "partition"
            hits.append(h)
        if hits:
            out["cells"][s["cell"]] = hits

    checks_raw = parsed.get("checks") if isinstance(parsed.get("checks"), dict) else {}
    for c in checks:
        if density_cfg is not None and c["key"] == density_cfg["key"]:
            continue
        hits = [h for h in (_hit(file_id, text_source, norm_src, raw, _check_labels(c), file_name=file_name)
                            for raw in _as_list(checks_raw.get(c["key"]))) if h is not None]
        if hits:
            out["checks"][c["key"]] = hits
    if density_cfg is not None:
        out["density"] = _density_hits(checks_raw.get(density_cfg["key"]), norm_src, file_id, file_name)

    raw_buildings = _as_list(parsed.get("buildings"))
    st["building_count_raw"] = len(raw_buildings)
    for raw in raw_buildings:
        if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or not raw["name"].strip():
            st["buildings_dropped"].append({"name": None, "reason": "没有单体名"})
            continue
        name = raw["name"].strip()[:60]
        level = raw.get("level") if raw.get("level") in ("underground", "above_ground", "structure") else None
        base = {"name": name, "level": level,
                "function": raw.get("function") if isinstance(raw.get("function"), str) else None,
                "source_file_id": file_id, "source_file_name": file_name, "text_source": text_source}
        h = _hit(file_id, text_source, norm_src, raw, [name], value_key="area", file_name=file_name)
        if h is not None and h["value"] > 0:
            h["verification"]["value_is_area"] = _value_is_area(h["value"], h["quote"])
            h["confidence"] = _confidence(h["verification"])
            out["buildings"].append({**base, "area": h["value"], "quote": h["quote"],
                                     "verification": h["verification"], "confidence": h["confidence"]})
            continue
        # WS29-d（E05）：面积为空的单体保留 —— 改前这里 continue，楼号表 24 个单体只剩地下室。
        # 只核单体名的引文在不在原文里（防编造）；不在就丢弃并记原因。不归位、不计入合计
        quote = raw.get("quote") if isinstance(raw.get("quote"), str) and raw["quote"].strip() else name
        if not evidence_check.quote_in_source(quote, norm_src):
            st["buildings_dropped"].append({"name": name, "reason": "单体名的引文在原文里找不到"})
            continue
        out["buildings"].append({**base, "area": None, "area_missing": True, "quote": quote,
                                 "verification": {"quote_in_source": True, "value_in_quote": False,
                                                  "mapping": "label" if _plain(name) in _plain(quote)
                                                  else "semantic"},
                                 "confidence": 0.0})
    st["building_count"] = len(out["buildings"])
    return out


def _density_hits(raws, norm_src: str, file_id: str, file_name: str | None) -> list[dict]:
    """建筑密度（WS29-d，D-R118）：数从**引文**里按百分数解析，不信模型给的 value，也不走 parse_quantity。

    → [{value | None, quote, quote_in_source, source_file_id, source_file_name}]；value 为 None =
    引文里有「建筑密度」和数，但不是百分数写法（记 density_format_unrecognized，不猜）。
    引文里连「建筑密度」加数都没有的，当模型没给，丢掉。
    """
    out: list[dict] = []
    for raw in _as_list(raws):
        if not isinstance(raw, dict):
            continue
        quote = raw.get("quote") if isinstance(raw.get("quote"), str) else ""
        if not _DENSITY_LABEL_NUM.search(unicodedata.normalize("NFKC", quote)):
            continue
        out.append({"value": parse_density(quote), "quote": quote,
                    "quote_in_source": bool(evidence_check.quote_in_source(quote, norm_src)),
                    "source_file_id": file_id, "source_file_name": file_name})
    return out


# ------------------------------------------------------------------ 合并（多文件）


def _fmt(v: float) -> str:
    # WS10-P09：`:g` 只留 6 位有效数字，232497.24 显示成 232497 —— 明细里两个候选看着
    # 像是四舍五入的同一个数。'.12g' 足够表达任何面积 / 车位数而不带浮点毛刺。
    return format(float(v), ".12g")


def _ambiguous(cell: str | None, label: str, hits: list[dict], what: str) -> dict:
    distinct = sorted({h["value"] for h in hits})
    # WS29-d（08-012 第 9 项）：写文件名，不写 19 位内部编号
    detail = "；".join(
        f"{_fmt(h['value'])}（{_file_label(h.get('source_file_id'), h.get('source_file_name'))}："
        f"{h.get('quote') or '无引文'}）"
        for h in sorted(hits, key=lambda x: (x["value"], str(x.get("source_file_id")))))
    return {
        "cell": cell, "label": label, "reason": "ambiguous",
        "detail": f"{what}出现 {len(distinct)} 个不同数值，不自行选择：{detail}",
        "source_file_id": None,
        "candidates": [{"value": h["value"], "quote": h.get("quote"),
                        "source_file_id": h.get("source_file_id"),
                        "verification": h.get("verification"),
                        "confidence": h.get("confidence")} for h in hits],
    }


def _best(hits: list[dict]) -> dict:
    # 同值多处：优先核验通过的那条（confidence=1.0），其次先到者
    return max(hits, key=lambda h: h.get("confidence") or 0.0)


def _not_found_detail(truncated_files: list[dict]) -> str:
    if truncated_files:
        parts = []
        for f in truncated_files:
            st = f.get("text_stats") or {}
            how = ("按关键词取了约 {w} 字的窗口".format(w=st.get("window_chars"))
                   if st.get("strategy") == "keyword_windows"
                   else f"只检索了前 {st.get('window_chars') or MAX_TEXT_CHARS} 字")
            # WS29-d（08-012 第 9 项）：改前写的是 file_id（「2104518694846009344（正文 33980 字…）」）
            parts.append(f"{_file_label(f.get('file_id'), f.get('file_name'))}（正文 {f['text_chars']} 字，{how}）")
        return f"原文未提及（注意：{'、'.join(parts)}，窗口外未检索）"
    return "原文未提及"


def merge_candidates(
    specs: list[dict], per_file: list, *, template_code: str = "gsyz_v1",
    policy: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """多文件合并 → (candidates, unresolved)。完整结果（含单体 / 总量 / 告警）见 merge_extractions。"""
    merged = merge_extractions(per_file, template_code=template_code, policy=policy)
    return merged["candidates"], merged["unresolved"]


def merge_extractions(per_file: list, *, template_code: str = "gsyz_v1",
                      policy: dict | None = None) -> dict:
    """多文件抽取结果合并（WS10-P05 / P08 / P09）。

    逐格：同格出现**不同数值**即 ambiguous —— 不再区分单文件与多文件（此前只比较跨文件，
    同一份文件里 154871.74 与 232497.24 两个用地面积由 LLM 自行选边、confidence 1.0 交出）。
    分组：原文只有整组总量时，放进分组首位并带 note，同组其余位落 total_only_no_partition；
          分组不允许只有总量（如停车位）时，整组 not_found 并写明「只有总量无法分区」。
    单体：按出现顺序确定性归位（地下 → D7/D8，地上 → D10-D12，构筑物 → D13），超出槽位的
          逐个落 unmapped_building，不猜、不合并；槽位合计与原文总建筑面积差 >1% 出
          area_total_mismatch。
    """
    pol = estimate_policy.load_policy(template_code) if policy is None else policy
    specs = root_input_specs(template_code)
    by_cell_spec = {s["cell"]: s for s in specs}
    cell_specs = cell_hint_specs(template_code, pol)
    groups_cfg = estimate_policy.extract_groups(pol)
    files = [f for f in per_file if isinstance(f, dict)]
    truncated = [f for f in files if f.get("truncated")]
    nf_detail = _not_found_detail(truncated)

    candidates: dict[str, dict] = {}
    unresolved: list[dict] = []
    warnings: list[dict] = []

    def _cand(cell: str, hit: dict, **extra) -> dict:
        s = by_cell_spec[cell]
        return {"cell": cell, "label": s["label"], "unit": s.get("unit"), "seq": s.get("seq"),
                "value": hit["value"], "source_file_id": hit.get("source_file_id"),
                "quote": hit.get("quote"), "text_source": hit.get("text_source") or "text_layer",
                "confidence": hit.get("confidence") or 0.0,
                "verification": hit.get("verification"),
                # 铁律 2：抽取结果须经用户确认才进计算，恒 True，没有例外分支
                "needs_manual": True, **extra}

    def _nf(cell: str, detail: str, reason: str = "not_found") -> None:
        unresolved.append({"cell": cell, "label": by_cell_spec[cell]["label"], "reason": reason,
                           "detail": detail, "source_file_id": None})

    # ---- 总量核对值（checks）----
    check_hits: dict[str, list[dict]] = {}
    for f in files:
        for key, hits in (f.get("checks") or {}).items():
            check_hits.setdefault(key, []).extend(hits)
    # 建筑密度是百分数提示项，不是总量：不进 check_values（Java 摘要「原文总量 N 项」、槽位对账都读它）
    check_labels = {c["key"]: c["label"] for c in estimate_policy.quantity_checks(pol)}
    check_values = []
    single_check: dict[str, dict] = {}
    for key in check_labels:
        hits = check_hits.get(key) or []
        for h in hits:
            check_values.append({"key": key, "label": check_labels[key], **{
                k: h.get(k) for k in ("value", "quote", "source_file_id", "confidence",
                                      "verification")}})
        if len({h["value"] for h in hits}) == 1:
            single_check[key] = _best(hits)
        elif hits:
            warnings.append({"code": "check_value_ambiguous", "cell": None,
                             "message": f"原文「{check_labels[key]}」出现多个不同数值："
                                        + "、".join(_fmt(v) for v in sorted({h['value'] for h in hits}))
                                        + "，未用它做槽位对账，请在单体归位面板核对"})

    # ---- 逐格（非槽位）----
    cell_hits: dict[str, list[dict]] = {}
    for f in files:
        for cell, hits in (f.get("cells") or {}).items():
            cell_hits.setdefault(cell, []).extend(hits)
    by_group: dict[str, list[dict]] = {}
    for s in cell_specs:
        by_group.setdefault(s.get("group") or f"_single:{s['cell']}", []).append(s)
    for gname, members in by_group.items():
        cfg = groups_cfg.get(gname) or {}
        part = {s["cell"]: [h for h in cell_hits.get(s["cell"], []) if h.get("scope") != "total"]
                for s in members}
        totals = [h for s in members for h in cell_hits.get(s["cell"], []) if h.get("scope") == "total"]
        if cfg.get("check_key") and cfg["check_key"] in single_check:
            totals = totals + [single_check[cfg["check_key"]]]
        if any(part.values()) or gname.startswith("_single:") or not totals:
            for s in members:
                hits = part[s["cell"]] or (cell_hits.get(s["cell"], []) if gname.startswith("_single:") else [])
                if not hits:
                    _nf(s["cell"], nf_detail)
                elif len({h["value"] for h in hits}) > 1:
                    unresolved.append(_ambiguous(s["cell"], s["label"], hits, "同一格"))
                else:
                    candidates[s["cell"]] = _cand(s["cell"], _best(hits))
            continue
        # 整组只有总量
        if len({h["value"] for h in totals}) > 1:
            unresolved.append(_ambiguous(members[0]["cell"], members[0]["label"], totals,
                                         f"「{members[0]['path'].split(' > ')[0]}」总量"))
            for s in members[1:]:
                _nf(s["cell"], "原文只有总量且总量本身有多个数值，无法分区", "total_only_no_partition")
            continue
        if cfg.get("allow_total_only"):
            first, rest = members[0], members[1:]
            candidates[first["cell"]] = _cand(
                first["cell"], _best(totals),
                note=f"原文只有「{first['path'].split(' > ')[0]}」总量、未分区，已放在首位；"
                     "请确认是否需要拆分到其余分区")
            for s in rest:
                _nf(s["cell"], f"原文只有总量，已放在 {first['cell']}，无法分区",
                    "total_only_no_partition")
        else:
            for s in members:
                _nf(s["cell"], "只有总量无法分区：原文只给了整组总量，本格口径要求分项数值")

    # ---- 单体清单 → 槽位（D46：固定槽位 + 确定性归位）----
    buildings_out, slot_warn = _map_buildings(files, pol, by_cell_spec, single_check, unresolved,
                                              candidates, _cand, _nf, nf_detail, groups_cfg)
    warnings.extend(slot_warn)

    # ---- 占地缺失时的建筑密度提示（WS29-d，D-R118）----
    warnings.extend(_footprint_density_hint(files, pol, candidates, unresolved, cell_specs))

    ordered = [candidates[s["cell"]] for s in specs if s["cell"] in candidates]
    order_idx = {s["cell"]: i for i, s in enumerate(specs)}
    unresolved.sort(key=lambda u: (order_idx.get(u.get("cell"), len(specs)), str(u.get("label"))))
    return {"candidates": ordered, "unresolved": unresolved, "buildings": buildings_out,
            "check_values": check_values, "warnings": warnings,
            # P12：每份文件的原文长度 / 窗口长度 / 是否截断 / 取窗策略 / 命中锚点
            "text_stats": [f["text_stats"] for f in files if isinstance(f.get("text_stats"), dict)]}


def _map_buildings(files, pol, by_cell_spec, single_check, unresolved, candidates, _cand, _nf,
                   nf_detail, groups_cfg) -> tuple[list[dict], list[dict]]:
    slots = estimate_policy.slots(pol)
    if not slots:
        return [], []
    level_map = estimate_policy.slot_level_map(pol)
    raw = [b for f in files for b in (f.get("buildings") or [])]

    # 归一化后同名才去重（多份文件重复描述同一栋）；写法不同的（「6#楼」「6#」）各占一行，
    # 由用户在面板里手动合并 —— 不按相似度自动合并（铁律 3）。
    # 同名的面积：无面积的那份让位给有面积的（建施说明的楼号表空着、分标段表有数）；
    # 有面积的取值不止一个 → ambiguous，单体照样留在清单里（面积空、带全部取值），给面板手填。
    by_name: dict[str, list[dict]] = {}
    order: list[str] = []
    for b in raw:
        key = _norm(b["name"])
        if key not in by_name:
            by_name[key] = []
            order.append(key)
        by_name[key].append(b)
    buildings: list[dict] = []
    for key in order:
        group = by_name[key]
        with_area = [b for b in group if b.get("area") is not None]
        areas = sorted({b["area"] for b in with_area})
        if len(areas) > 1:
            unresolved.append(_ambiguous(None, group[0]["name"],
                                         [dict(b, value=b["area"]) for b in with_area],
                                         f"单体「{group[0]['name']}」面积"))
            keep = dict(with_area[0], area=None, area_options=areas, confidence=0.0)
            keep.pop("area_missing", None)
            buildings.append(keep)
            continue
        buildings.append(dict(max(with_area or group, key=lambda b: b.get("confidence") or 0.0)))

    free: dict[str, list[str]] = {}
    for s in slots:
        free.setdefault(s["kind"], []).append(s["cell"])
    assigned: dict[str, list[dict]] = {}
    for b in buildings:
        b["slot"] = None
        if b.get("area") is None:
            # 无面积 / 面积多值：不归位、不计入合计，面板里手填后由用户归位（WS29-d）
            continue
        kind = level_map.get(b.get("level") or "")
        cells = free.get(kind or "", [])
        verified = (b.get("confidence") or 0.0) >= 1.0
        if kind and cells and verified:
            cell = cells.pop(0)
            b["slot"] = cell
            assigned.setdefault(cell, []).append(b)
            continue
        if not verified:
            # WS29-d：面积没核验通过（引文不在原文 / 数不在引文里 / 引文里的数是层数之类）不自动归位。
            # 改前照样按出现顺序归位，「16层」的 16 进了 1#楼 槽位
            why = "面积核验未通过（" + _unverified_why(b.get("verification") or {}) + "），未自动归位"
        else:
            why = ("超出模板槽位" if kind else "层级不明") + "，未归位"
        unresolved.append({
            "cell": None, "label": b["name"], "reason": "unmapped_building",
            "detail": (f"{b['name']}（{_level_cn(b.get('level'))}，{_fmt(b['area'])} ㎡）{why}："
                       "不猜、不合并。请在「单体归位」里核对后并入某个槽位"),
            "source_file_id": b.get("source_file_id"),
        })

    for cell, bs in assigned.items():
        b = bs[0]
        candidates[cell] = _cand(cell, {"value": b["area"], "quote": b.get("quote"),
                                        "source_file_id": b.get("source_file_id"),
                                        "text_source": b.get("text_source"),
                                        "confidence": b.get("confidence"),
                                        "verification": b.get("verification")},
                                 building_names=[b["name"]])

    # 某类单体一个都没抽到时，用该类总量兜底放首位（与逐格分组同一口径）
    for kind, cfg in groups_cfg.items():
        kind_slots = [s["cell"] for s in slots if s["kind"] == kind]
        if not kind_slots or any(c in assigned for c in kind_slots):
            continue
        total = single_check.get(cfg.get("check_key") or "")
        if total is not None and cfg.get("allow_total_only"):
            candidates[kind_slots[0]] = _cand(
                kind_slots[0], total,
                note="原文没有逐栋面积，只有该类总量，已放在首个槽位；请在「单体归位」确认")
            for c in kind_slots[1:]:
                _nf(c, f"原文只有总量，已放在 {kind_slots[0]}，无法分区", "total_only_no_partition")
    for s in slots:
        c = s["cell"]
        if c not in candidates and not any(u.get("cell") == c for u in unresolved):
            _nf(c, nf_detail)

    warnings: list[dict] = []
    missing = [b for b in buildings if b.get("area_missing")]
    if missing:
        names = "、".join(b["name"] for b in missing[:8]) + ("等" if len(missing) > 8 else "")
        warnings.append({
            "code": "building_area_missing", "cell": None,
            "message": (f"原文列了 {len(buildings)} 个单体，其中 {len(missing)} 个没有面积（{names}）。"
                        "没有面积的单体不自动归位、不计入槽位合计；请在「单体归位」里按分标段面积表等资料"
                        "手填面积后并入槽位，或确认它们已含在某个总量里。"),
            "count": len(buildings), "missing": len(missing),
        })
    gross = single_check.get("gross_building_area")
    mapped_sum = sum(c["value"] for cell, c in candidates.items()
                     if cell in {s["cell"] for s in slots})
    if gross is not None and gross["value"] > 0:
        diff = abs(mapped_sum - gross["value"]) / gross["value"]
        rec = estimate_policy.area_reconcile(pol) or {}
        tol = float(rec.get("tolerance") or 0.01)
        if diff > tol:
            # 无面积的单体另有 building_area_missing 点名，这里只数有面积而没归位的
            n_unmapped = sum(1 for b in buildings if b.get("slot") is None and b.get("area") is not None)
            warnings.append({
                "code": "area_total_mismatch", "cell": rec.get("slot_sum_cell"),
                "message": (f"单体槽位合计 {_fmt(mapped_sum)} ㎡ 与原文总建筑面积 {_fmt(gross['value'])} ㎡"
                            f" 相差 {diff:.2%}（阈值 {tol:.0%}）"
                            + (f"；另有 {n_unmapped} 个单体未归位" if n_unmapped else "")
                            + "。请在「单体归位」里把未归位单体并入槽位后再写入；"
                            "不对账直接生成会被 compute 以 422 拒绝（除非确认并写明理由）。"),
                "slot_sum": round(mapped_sum, 4), "source_area": gross["value"],
                "diff_ratio": round(diff, 6),
            })
    return buildings, warnings


def _footprint_density_hint(files, pol, candidates, unresolved, cell_specs) -> list[dict]:
    """占地没取到、原文有建筑密度时，在占地那一行「未取到」上写推算提示（WS29-d，E09，D-R118）。

    - 推算值 = 用地面积 × 密度，由**代码**算（Decimal，两位小数），挂在该行的 `derived` 上；
      **不进候选**：只有用户点「填入推算值」才写，来源记 derived、结果需复核（铁律 2）。
    - 密度只认百分数（parse_density）、引文必须在原文里；写法认不出出 density_format_unrecognized，不猜。
    → 要追加的告警。
    """
    cfg = estimate_policy.density_check(pol)
    if cfg is None:
        return []
    hits = [h for f in files for h in (f.get("density") or [])]
    warnings: list[dict] = []
    seen: set[str] = set()
    for h in hits:
        if h["value"] is None and h["quote_in_source"] and h["quote"] not in seen:
            seen.add(h["quote"])
            warnings.append({
                "code": "density_format_unrecognized", "cell": None,
                "message": (f"原文的建筑密度写法认不出：「{h['quote'].strip()}」（"
                            f"{_file_label(h.get('source_file_id'), h.get('source_file_name'))}）。"
                            "只认「建筑密度 30%」这种百分数写法；不带 % 的小数分不清是 0.3% 还是 30%，"
                            "不拿它推算占地。"),
            })
    good = [h for h in hits if h["value"] is not None and h["quote_in_source"]]
    members = [s["cell"] for s in cell_specs if s.get("group") == cfg.get("hint_for")]
    if not good or not members or any(c in candidates for c in members):
        return warnings
    row = next((u for u in unresolved if u.get("cell") == members[0] and u.get("reason") == "not_found"), None)
    if row is None:
        return warnings
    before = row.get("detail") or ""
    tail = "" if before in ("", "原文未提及") else f"；另：{before}"
    values = sorted({h["value"] for h in good})
    if len(values) > 1:
        row["detail"] = ("原文没有建筑占地面积；建筑密度出现多个不同数值（"
                         + "、".join(f"{_fmt(v)}%" for v in values) + "），不推算占地" + tail)
        return warnings
    h, density = good[0], values[0]
    quote = h["quote"].strip()
    head = (f"原文没有建筑占地面积，只有建筑密度 {_fmt(density)}%（引文：「{quote}」，"
            f"{_file_label(h.get('source_file_id'), h.get('source_file_name'))}）。")
    fp = estimate_policy.footprint_check(pol) or {}
    site = candidates.get(fp.get("site_cell") or "")
    if site is None:
        row["detail"] = head + "用地面积没有取到唯一值，无法推算占地；请按总平面图或规划条件填写" + tail
        return warnings
    derived = (Decimal(repr(float(site["value"]))) * Decimal(repr(density)) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    value = float(derived)
    row["detail"] = (head + f"按 用地面积 × 密度 推算，全地块占地约 {_fmt(value)} ㎡"
                     f"（{_fmt(site['value'])} × {_fmt(density)}%）。推算值不是原文数值，"
                     "填入后结果记「需复核」" + tail)
    row["derived"] = {
        "value": value, "basis": "site_area_x_density",
        "site_cell": fp.get("site_cell"), "site_area": site["value"],
        "density": density, "density_quote": quote,
        "source_file_id": h.get("source_file_id"), "source_file_name": h.get("source_file_name"),
        # 用地面积是全地块的数，推算出来的也是全地块占地；本标段口径时前端只给文字、不给按钮
        "scope_basis": "whole_site",
    }
    return warnings


def _unverified_why(v: dict) -> str:
    if not v.get("quote_in_source"):
        return "引文在原文里找不到"
    if not v.get("value_in_quote"):
        return "面积不在引文里"
    if v.get("value_is_area") is False:
        return "引文里的这个数是层数 / 栋数 / 高度之类，不是面积"
    return "核验不完整"


def _level_cn(level: str | None) -> str:
    return {"underground": "地下", "above_ground": "地上", "structure": "构筑物"}.get(level or "", "层级未知")
