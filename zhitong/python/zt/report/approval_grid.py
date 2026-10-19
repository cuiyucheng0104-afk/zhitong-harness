# 来源：engine-service/app/engine/approval_grid.py（zhitong-cost-ai@991ff5c，W3 搬入 zt；改动见本文件内「zt 改动」注释）
"""审定单 / 汇总表的确定性网格读取（整改 spec WS07 K2 第 1 条）。

QA:extract-01：只送明细表时，核减金额被 LLM 取成「净核金额」列的 1280435.50，正确值是
「其中 | 核减金额」列的 1418635.50，差 138200 元，结果 verified=true、界面零告警。
金额不该让模型去「读表」：表头定位 → 列语义（严格词表，`consulting_fields.AMOUNT_COLUMN_RULES`）
→ 合计行 → 单元格取值，每个值带 `sheet!cell` 坐标回链，所以 verify_level 直接为 strong。
表头键值行（工程名称 / 建设单位 / 施工单位）也带坐标，但只作候选：一律不高于 weak（`_cap_grid_text`，
用户 2026-09-30 裁定 ②），这份文件的 LLM 照样问，最终值由合并决定。

只读**表头 + 合计行**这一种形状（表单式读法），不解析明细行。总纲冲突裁决 K27 说「多行多列的
汇总表只在 WS08 costsheet 里解析」；这里没有调 `costsheet.parse_audit_summary`，原因写进 PR：
它把核增 / 核减 / 净核减都归成同一个 `delta` 当事方，不认没有「金额」二字的「核增」「核减」列头，
不展开合并单元格，也不读 number_format —— 恰好是本条缺陷要分清的那几件事。

xlsx 用 openpyxl 非只读模式打开（只读模式拿不到 merged_cells 与 number_format），经 WS08-A 的
容错模块 `xlsx_tolerant`（样式表损坏兜底，C6；zt 里是 `zt.costsheet.xlsx_tolerant`）。zt 改动：.xls 不转换，记 note 跳过。
"""
from __future__ import annotations

import datetime
import io
import re
import zipfile
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Optional

from zt.amounts.amounts import format_yuan, parse_amount
from zt.costsheet.xlsx_tolerant import XlsxUnreadable, load_workbook_tolerant
from zt.report.fields import (
    AUDIT_TOTAL_SUBTITLE,
    NET_REDUCTION,
    amount_column_semantic,
    field_def,
    norm_text,
    verify_candidate,
)

MAX_BYTES = 20 * 1024 * 1024
MAX_CELLS = 200_000
HEADER_SCAN_ROWS = 30
MAX_HEADER_ROWS = 4
# 表头行的判据：至少 2 个（按合并区去重）格命中这些词
_HEADER_WORDS = ("送审", "报审", "审定", "核减", "核增", "合同价", "合同金额", "净核", "审核定案")
# 表头续行里常见、数据行里不会单独出现的词
_HEADER_VOCAB = _HEADER_WORDS + ("金额", "（元）", "(元)", "万元", "其中", "合同内", "合同外",
                                 "合计", "小计", "序号", "名称", "备注", "核增减")
_TOTAL_LABELS = ("合计", "总计", "合计金额")
# 表头键值行：标签 → 字段
_KV_LABELS = {"工程名称": "工程名称", "项目名称": "工程名称", "建设单位": "建设单位", "施工单位": "施工单位"}
_KV_SCAN_ROWS = 60
# 清单 / 费用 / 材料表的列头词。这些表里「项目名称」是列头，它右邻也是列头，
# 不是「标签｜值」（PR #768 评审：GB50500 清单表把「项目特征描述」读成了工程名称、strong）。
# ⚠ 这是闭集，只是第一道闸：没登记的列头词（「内容」「费用」「审核意见」…）不靠它拦 ——
# 不带冒号的「标签｜值」只有 `_form_row_evidence` 的正面证据成立才出值（第四轮白名单），
# 同一本工作簿读出两个不同值时 `_demote_conflicting_kv` 再兜一层。
# 别再往这里加词来修漏网的列头 —— 判不了就不出值。
_COLUMN_HEADS = frozenset((
    "序号", "项目编码", "项目特征", "项目特征描述", "计量单位", "单位", "工程量", "数量", "综合单价", "单价",
    "合价", "金额", "计算基础", "费率", "规格型号", "型号规格", "工程内容", "暂估价", "备注", "调整费率",
    "调整后金额", "定额编号", "定额名称",
))
# 表单（「标签｜值」）里常见的标签。一行排两对以上时，每个「值」前面都得是这样的标签，
# 否则这一行不是表单行（多半是列头行），不出值 —— 宁可退回 LLM，也不拿列头当值
_FORM_LABELS = frozenset(_KV_LABELS) | frozenset((
    "标段", "编制单位", "审核单位", "咨询单位", "委托单位", "监理单位", "设计单位", "工程地点", "建设地点",
    "结构类型", "建筑面积", "合同价", "合同金额", "合同工期", "工期", "开工日期", "竣工日期", "编制日期",
    "审核日期", "日期", "项目编号", "工程编号", "备注",
))
_PAGE_MARK = re.compile(r"^(?:第\d*页)?(?:共\d*页)?$")        # 归一（去空白）后比
# 审定单表头行尾的计量说明「单位：元」「金额单位：万元」：不是标签也不是值，不参与配对
_UNIT_MARK = re.compile(r"^(?:金额|计量)?单位[:：](?:人民币)?(?:元|万元)$")
_SEQ_MARK = re.compile(r"^(?:\d+|[一二三四五六七八九十]+)[、.．]?$")
_UNIT_SUFFIX = re.compile(r"[（(][^（()）]*[）)]$")             # 「费率(%)」「金额(元)」
_UNIT_CELL = re.compile(r"^[（(][^（()）]{0,6}[）)]$")           # 列头下面的单位行「（元）」「(万元)」
_INLINE_LABEL = re.compile(r"^(.{1,10}?)[:：]")                  # 一格写完的「建设单位：某某公司」
# 一格写完的表头行「工程名称：X    标段：Y    第 1 页 共 3 页」：值只取到下一个标签 / 页码之前
_NEXT_LABEL = re.compile(r"\s+(?:\S{1,10}[:：]|第\s*\d*\s*页|共\s*\d*\s*页)")
# 整格都是括号的占位（签章栏「（盖章）」「〔盖章〕」、空白模板「（详见封面）」「【详见封面】」「（签字）（盖章）」）：
# 归一（去空白）后比。认（）()【】〔〕［］[] 六种（PR #768 第七轮：第六轮评审非阻断，改前只认前两种）。
# 只认整格 —— 「城中河综合整治工程（二期）」「【二期】城中河…」这种带括号前后缀的真名称照样读
_BRACKETS_OPEN, _BRACKETS_CLOSE = "（(【〔［[", "）)】〕］]"
_BRACKET_PLACEHOLDER = re.compile(
    rf"^(?:[{re.escape(_BRACKETS_OPEN)}][^{re.escape(_BRACKETS_OPEN + _BRACKETS_CLOSE)}]*"
    rf"[{re.escape(_BRACKETS_CLOSE)}])+$")
# 网格（键值通道）读出的文本字段只作候选（用户 2026-09-30 裁定 ②）：verify_notes 里的标记
GRID_TEXT_CANDIDATE = "grid_text_candidate"


@dataclass
class GridResult:
    candidates: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class _Col:
    idx: int            # 1 起
    title: str          # 多级表头自上而下用「|」拼接
    leaf: str           # 最末一级标题
    group_span: int     # 表头首行所在合并区覆盖了几个（折叠后）列


def _norm(v: Any) -> str:
    return "".join(str(v).split()) if v is not None else ""


def _letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _is_number(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float, Decimal)):
        return True
    return isinstance(v, str) and parse_amount(v) is not None


def _to_decimal(v: Any) -> Optional[Decimal]:
    """单元格 → Decimal（元为单位前的原值）。float 走 repr，不带二进制尾差；字符串交给 parse_amount。"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, Decimal)):
        return Decimal(v)
    if isinstance(v, float):
        try:
            return Decimal(repr(v))
        except InvalidOperation:  # pragma: no cover —— nan/inf
            return None
    if isinstance(v, str):
        a = parse_amount(v)
        return a.value if a is not None else None
    return None


def _plain(d: Decimal) -> str:
    return format(d, "f")


def display(d: Decimal, number_format: Optional[str]) -> str:
    """按单元格的 number_format 出展示串：造价员在 Excel 里看到的就是这个数。

    支持 General、0、`0_ `、0.00、#,##0、#,##0.00；其它格式直接用 Decimal 原值（不猜）。
    真实汇总表的 D12=11894327.9609491 格式是「0」，显示为 11894328 —— 正好是正式数（QA:extract-10）。"""
    f = (number_format or "General").strip().rstrip("_ ").strip()
    if f in ("", "General"):
        return _plain(d)
    if f == "0":
        return _plain(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if f == "0.00":
        return _plain(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if f == "#,##0":
        return f"{d.quantize(Decimal(1), rounding=ROUND_HALF_UP):,}"
    if f == "#,##0.00":
        return f"{d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,}"
    return _plain(d)


class _Sheet:
    """带合并区展开的只读视图：合并区里每一格都读到左上角的值。"""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.title = ws.title
        self.max_row = ws.max_row or 0
        self.max_col = ws.max_column or 0
        self.owner: dict[tuple[int, int], tuple[int, int]] = {}
        self.span: dict[tuple[int, int], tuple[int, int, int, int]] = {}
        for rng in ws.merged_cells.ranges:
            top = (rng.min_row, rng.min_col)
            box = (rng.min_row, rng.min_col, rng.max_row, rng.max_col)
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    self.owner[(r, c)] = top
                    self.span[(r, c)] = box

    def top(self, r: int, c: int) -> tuple[int, int]:
        return self.owner.get((r, c), (r, c))

    def value(self, r: int, c: int) -> Any:
        tr, tc = self.top(r, c)
        return self.ws.cell(row=tr, column=tc).value

    def text(self, r: int, c: int) -> str:
        v = self.value(r, c)
        if v is None or isinstance(v, (int, float, Decimal, bool, datetime.date, datetime.time)):
            return ""
        return _norm(v)

    def number_format(self, r: int, c: int) -> Optional[str]:
        tr, tc = self.top(r, c)
        return self.ws.cell(row=tr, column=tc).number_format


def _header_hits(sh: _Sheet, r: int) -> int:
    owners = set()
    for c in range(1, sh.max_col + 1):
        t = sh.text(r, c)
        if t and any(w in t for w in _HEADER_WORDS):
            owners.add(sh.top(r, c))
    return len(owners)


def _row_is_total(sh: _Sheet, r: int) -> bool:
    return any(sh.text(r, c) in _TOTAL_LABELS for c in range(1, min(3, sh.max_col) + 1))


def _is_header_continuation(sh: _Sheet, r: int, block: list[int]) -> bool:
    vals = [(c, sh.value(r, c)) for c in range(1, sh.max_col + 1)]
    vals = [(c, v) for c, v in vals if v is not None and _norm(v)]
    if not vals or _row_is_total(sh, r):
        return False
    if any(_is_number(v) for _c, v in vals):
        return False
    for c, v in vals:
        if sh.top(r, c)[0] in block:
            return True   # 合并区从上面的表头行延伸下来
        if any(w in _norm(v) for w in _HEADER_VOCAB):
            return True
    return False


def _header_block(sh: _Sheet) -> Optional[list[int]]:
    anchor = next((r for r in range(1, min(HEADER_SCAN_ROWS, sh.max_row) + 1)
                   if _header_hits(sh, r) >= 2), None)
    if anchor is None:
        return None
    block = [anchor]
    r = anchor + 1
    while r <= sh.max_row and len(block) < MAX_HEADER_ROWS and _is_header_continuation(sh, r, block):
        block.append(r)
        r += 1
    return block


def _columns(sh: _Sheet, block: list[int]) -> list[_Col]:
    """每列的标题路径；标题路径相同且在每一行表头里都属于同一个合并区的相邻列折叠成一列
    （取左边那列）。真实审定单「送审价」占 D6:E7，合计行的值也合并在 D10:E10。"""
    raw: list[tuple[int, str, str]] = []
    for c in range(1, sh.max_col + 1):
        segs: list[str] = []
        for r in block:
            t = sh.text(r, c)
            if t and (not segs or segs[-1] != t):
                segs.append(t)
        if segs:
            raw.append((c, "|".join(segs), segs[-1]))
    folded: list[tuple[int, str, str]] = []
    last_phys: Optional[int] = None
    for c, title, leaf in raw:
        if folded and last_phys == c - 1:
            kc, ktitle, _kl = folded[-1]
            same_region = all(sh.span.get((r, c)) is not None
                              and sh.span.get((r, c)) == sh.span.get((r, kc)) for r in block)
            if ktitle == title and same_region:
                last_phys = c
                continue
        folded.append((c, title, leaf))
        last_phys = c
    # 表头首行的合并区覆盖了几个折叠后的列：「审定金额」横跨 合同内 / 合同外 / 合计 三列 → 3
    kept = {c for c, _t, _l in folded}
    out: list[_Col] = []
    for c, title, leaf in folded:
        box = sh.span.get((block[0], c))
        span = 1
        if box is not None:
            span = sum(1 for k in kept if box[1] <= k <= box[3])
        out.append(_Col(c, title, leaf, span))
    return out


def _data_rows(sh: _Sheet, start: int, amount_cols: list[_Col]) -> list[int]:
    rows = []
    for r in range(start, sh.max_row + 1):
        if any(_to_decimal(sh.value(r, col.idx)) is not None for col in amount_cols):
            rows.append(r)
    return rows


def _amount_candidates(sh: _Sheet, block: list[int], notes: list[str],
                       include_net_reduction: bool = False) -> list[dict]:
    cols = _columns(sh, block)
    by_sem: dict[str, list[_Col]] = {}
    for col in cols:
        sem = amount_column_semantic(col.title)
        if sem is None or (sem == NET_REDUCTION and not include_net_reduction):
            continue
        if sem == "审定金额" and col.group_span > 1:
            # 「审定金额」下面分「合同内 / 合同外 / 合计」：只认子标题带合计 / 小计 / 总的那一列
            if not any(w in col.leaf for w in AUDIT_TOTAL_SUBTITLE):
                continue
        by_sem.setdefault(sem, []).append(col)
    groups_without_total = [col for col in cols
                            if amount_column_semantic(col.title) == "审定金额" and col.group_span > 1]
    if groups_without_total and "审定金额" not in by_sem:
        notes.append(f"「{sh.title}」审定金额是多列合并组，但没有子标题含合计/小计/总的列，列歧义，不出值")
    usable: dict[str, _Col] = {}
    for sem, cs in by_sem.items():
        if len(cs) > 1:
            notes.append(f"「{sh.title}」列歧义：{sem} 同时命中 "
                         + "、".join(f"{_letter(c.idx)}列〔{c.title}〕" for c in cs) + "，不出值")
            continue
        usable[sem] = cs[0]
    if not usable:
        return []

    first_data = block[-1] + 1
    totals = [r for r in range(first_data, sh.max_row + 1) if _row_is_total(sh, r)]
    if totals:
        row = totals[-1]
        row_label = next(sh.text(row, c) for c in range(1, min(3, sh.max_col) + 1)
                         if sh.text(row, c) in _TOTAL_LABELS)
    else:
        data = _data_rows(sh, first_data, list(usable.values()))
        if len(data) != 1:
            notes.append(f"「{sh.title}」没有合计行，数据行 {len(data)} 行，不出值（不猜哪一行是合计）")
            return []
        row = data[0]
        row_label = next((sh.text(row, c) for c in range(1, min(3, sh.max_col) + 1) if sh.text(row, c)),
                         f"第{row}行")
        notes.append(f"「{sh.title}」没有合计行，只有 1 行数据（第 {row} 行），按该行取值")

    out: list[dict] = []
    for sem, col in usable.items():
        tr, tc = sh.top(row, col.idx)
        d = _to_decimal(sh.value(row, col.idx))
        cell = f"{_letter(tc)}{tr}"
        if d is None:
            notes.append(f"「{sh.title}」{sem} 在 {cell} 不是数值，不出值")
            continue
        scale = Decimal(10000) if "万元" in col.title else Decimal(1)
        shown = display(d, sh.number_format(row, col.idx))
        out.append({
            "field": sem, "value": shown, "unit": "万元" if scale != 1 else "元",
            "amount_yuan": format_yuan(d * scale), "kind": "amount", "channel": "grid",
            "quote": f"{sh.title}!{cell}〔{col.leaf} × {row_label}〕= {shown}",
            "evidence": {"sheet": sh.title, "cell": cell, "row": tr, "row_label": row_label,
                         "col_label": col.title},
            # 坐标回链本身就是核验：值就是这一格
            "verify_level": "strong", "verified": True, "verify_notes": [],
        })
    return out


def _is_form_label(t: str) -> bool:
    return t.rstrip("：:") in _FORM_LABELS


def _is_column_head(t: str) -> bool:
    return _UNIT_SUFFIX.sub("", t) in _COLUMN_HEADS


def _row_cells(sh: _Sheet, r: int) -> list[tuple[tuple[int, int], str, Any]]:
    """一行里非空的格（合并区只算一次），按列序：(合并区左上角, 归一文本, 原值)。"""
    out: list[tuple[tuple[int, int], str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for c in range(1, sh.max_col + 1):
        top = sh.top(r, c)
        if top in seen:
            continue
        seen.add(top)
        v = sh.value(r, c)
        t = _norm(v)
        if t:
            out.append((top, t, v))
    return out


def _bottom(sh: _Sheet, top: tuple[int, int]) -> int:
    """合并区 `top` 的底边行号（没合并就是它自己那一行）。"""
    box = sh.span.get(top)
    return box[2] if box else top[0]


def _below(sh: _Sheet, top: tuple[int, int]) -> tuple[int, str]:
    """合并区 `top` 正下方那一格：(行号, 归一文本；数值也算内容)。从合并区的**底边**往下算 ——
    标签格跨两行合并时，下一行还是它自己（PR #768 第三轮非阻断 M6）。"""
    r = _bottom(sh, top) + 1
    return r, (_norm(sh.value(r, top[1])) if r <= sh.max_row else "")


def _above(sh: _Sheet, top: tuple[int, int]) -> str:
    r = top[0] - 1
    return _norm(sh.value(r, top[1])) if r >= 1 else ""


def _label_field(t: str) -> Optional[str]:
    return _KV_LABELS.get(t.rstrip("：:"))


def _form_cell(t: str) -> Optional[str]:
    """一格是不是表单标签格 → 标签（去冒号）；不是 → None。

    认两种：光标签「建设单位」「工程名称：」，和一格写完的「建设单位：某某公司」。「备注」这种同时是
    列头词的不算 —— 数据表的最后一列常叫备注，拿它当「表单还在继续」的证据会放过列头行。"""
    if not t:
        return None
    base = t.rstrip("：:")
    if base in _FORM_LABELS and base not in _COLUMN_HEADS:
        return base
    m = _INLINE_LABEL.match(t)
    if m and m.group(1) in _FORM_LABELS and m.group(1) not in _COLUMN_HEADS:
        return m.group(1)
    return None


def _pair_value(sh: _Sheet, top: tuple[int, int]) -> str:
    """表单标签格 `top` 的值（归一）：一格写完的取冒号后面；光标签取同一行右边第一个非空格
    （跳过「单位：元」与页码）。"""
    t = _norm(sh.value(*top))
    if t.rstrip("：:") not in _FORM_LABELS:
        m = _INLINE_LABEL.match(t)
        return t[m.end():] if m else ""
    box = sh.span.get(top)
    for c in range((box[3] if box else top[1]) + 1, sh.max_col + 1):
        v = _norm(sh.value(top[0], c))
        if v and not _UNIT_MARK.match(v) and not _PAGE_MARK.match(v):
            return v
    return ""


def _run_members(sh: _Sheet, ltop: tuple[int, int]) -> list[tuple[int, int]]:
    """标签格所在的那一列里，上下紧挨着、连成一串的表单标签格（不含它自己；合并区只算一次）。
    沿整列走到断开为止，不只看紧挨着的一行（PR #768 第三轮非阻断 M7）。"""
    col = ltop[1]
    out: list[tuple[int, int]] = []
    r = ltop[0] - 1
    while r >= 1:
        top = sh.top(r, col)
        if not _form_cell(_norm(sh.value(*top))):
            break
        out.append(top)
        r = top[0] - 1
    r = _below(sh, ltop)[0]
    while r <= sh.max_row:
        top = sh.top(r, col)
        if top == ltop:        # 标签格自己的合并区
            r += 1
            continue
        if not _form_cell(_norm(sh.value(*top))):
            break
        out.append(top)
        r = max(r, _bottom(sh, top)) + 1
    return out


def _right_above_header(sh: _Sheet, ltop: tuple[int, int], vtop: tuple[int, int],
                        header_rows: frozenset[int]) -> bool:
    """这一行紧挨在已认出的金额表头（`_header_block`）上面，中间只隔空行或「单位：元」这类说明行 ——
    表头上面那一行是这张表的抬头（工程名称 / 建设单位），不是它的列头（审定单常见排法，第三轮召回项）。
    标签或值的合并区伸进了表头 → 它是多级表头的一部分，不算。

    `_header_block` 本身很粗（一行里两格含「送审 / 审定 / 核减 / 核增 / 合同价」就算表头），所以
    PR #768 第五轮起这条证据还要：
    - `header_rows` 只在这张表真从合计行读出了金额时才传进来（`read_grid_fields`）—— 审核意见表的数据行
      「合同价|按签约合同价…计」读不出合计行金额；
    - 表头首行在标签那一列有自己的标题：没有 → 标签列的标题在上一级，上面这一行是两级表头的上一级
      （「项目名称|费用（B:D 合并）」横在「（空）|送审金额|审定金额|核减金额」上面），不是抬头；
    - 那个标题不像金额列（不含 `_HEADER_WORDS`）：真表头的这一列是序号 / 单位工程名称，
      「核减金额|系送审重复计取」这种被误认的数据行，标签列本身就是金额词。"""
    if not header_rows:
        return False
    anchor = min(header_rows)
    title = _norm(sh.value(anchor, ltop[1]))
    if not title or any(w in title for w in _HEADER_WORDS):
        return False
    last = max(_bottom(sh, ltop), _bottom(sh, vtop))
    if last >= anchor:
        return False
    for r in range(last + 1, anchor):
        for _top, t, _v in _row_cells(sh, r):
            if not (_UNIT_MARK.match(t) or _PAGE_MARK.match(t) or _UNIT_CELL.match(t)):
                return False
    return True


def _blank_mark(t: str) -> str:
    """「单位：元」与页码这类说明不算内容（`_PAGE_MARK` 对空串也匹配，空串照旧是空串）。"""
    return "" if _UNIT_MARK.match(t) or _PAGE_MARK.match(t) else t


def _data_rows_below(sh: _Sheet, filled: list[tuple[tuple[int, int], tuple[int, int]]],
                     header_rows: frozenset[int]) -> bool:
    """一行排了几对「标签|值」时，它是不是其实是数据表的列头行（审核记录表「工程名称|审核意见|审核日期|审核人」）。

    往下找第一行实打实的内容，一直找到表尾：空行、分类行「一、土建工程」（值列空）、单位行「（元）」、
    一格横跨几列而这一行别的列都空的标题 / 说明行都跳过（第三轮评审：只看紧下一行，多一行分类行就漏过去；
    第四轮评审探针：分类行多过 8 行、或数据行把「条目 + 意见」合并成一格而日期 / 审核人照填，都漏过去）。
    找到的那一行：
    - 是已认出的金额表头（`header_rows`，只在这张表真从合计行读出金额时才有）→ 每个标签列在表头行里都有
      自己的标题才算抬头；有标签列没有标题 → 这一行是两级表头的上一级（「项目名称|费用|工期|说明」横在
      「（空）|送审金额|审定金额|核减金额」上面）→ 列头行；
    - **每个**标签列都是表单标签（或连同值一起空着）→ 下一行还是表单行 → 不是列头。只要有一个标签列是
      别的内容（「工期|按合同工期计|2024-05-01|张三」的第三列是日期）就不算表单行（第四轮评审探针 N5）；
    - **至少两格**是列头词（「序号|单位工程名称|金额」「序号|项目编码|项目名称|项目特征描述」）→ 另一张表的列头，
      不是数据行。只有一格的不算：数据行里偶尔有一格恰好写「单价」「工程量」「数量」（「外架拆除|单价|2024-05-01|张三」），
      改前一格就算，判据①照样成立、列头词以 strong 读出（PR #768 第五轮评审阻断 1）；
    - 否则**任何一对**的值列下面有内容 → 数据行 → 这一行是列头（只填了一部分的数据行，和「两对表单 +
      下一行没登记的标签」分不清，拿不准就算数据行）。"""
    start = max(max(_bottom(sh, lt), _bottom(sh, vt)) for lt, vt in filled) + 1
    for r in range(start, sh.max_row + 1):
        if r in header_rows:
            return not all(_norm(sh.value(r, lt[1])) for lt, _vt in filled)
        # 按「标签1, 值1, 标签2, 值2…」的顺序读；被左边同一行的合并区盖住的列当空（「施工单位|某某（B:D 合并）」
        # 的第二对是空的，不是又一个「某某」）
        seen: set[tuple[int, int]] = set()
        lab_t: list[str] = []
        val_t: list[str] = []
        for lt, vt in filled:
            for c, out in ((lt[1], lab_t), (vt[1], val_t)):
                top = sh.top(r, c)
                out.append("" if top in seen else _blank_mark(_norm(sh.value(*top))))
                seen.add(top)
        if len(seen) < 2 * len(filled) and sum(1 for t in lab_t + val_t if t) <= 1:
            continue            # 一格横跨几列、这一行别的列都空：标题 / 说明行
        if any(_form_cell(t) for t in lab_t) and \
                all(_form_cell(t) or not (t or v) for t, v in zip(lab_t, val_t)):
            return False        # 下一行还是表单行
        if sum(1 for t in lab_t + val_t if t and _is_column_head(t)) >= 2:
            return False        # 另一张表的列头（一格列头词的是数据行，见上）
        if any(v and not _UNIT_CELL.match(v) for v in val_t):
            return True
    return False


def _column_header_above(sh: _Sheet, row: int, cols: list[tuple[int, int]]) -> bool:
    """`row` 上方是不是一张表的列头（「序号|检查项|结果」「项目|内容」）：每一对（标签列, 值列）上方，
    标签列那一格有内容、且不是表单标签，值列那一格是另一格、也有内容。

    是 → 下面这一列 / 这一行标签的「值」是这张表那一列的数据，列头说它是什么就是什么 —— 核对表的
    「结果」列是核对结论（「相符 / 基本相符 / 不符」），和概况表的「内容」列结构上一模一样，拿不准
    （PR #768 第四轮评审阻断 2：判据②「行首有序号」分不出这两种表，删掉之后判据④照样读出排在中间的
    「工程名称|相符」）。
    往上跳过夹在列头和表体之间的行 —— 没有表单标签、又不是每一对标签和值都有字的行都算：
    - 空行；
    - 分节行：一格横跨标签列和值列的标题 / 分类行（「一、基本信息」合并成一格），或值列空着的分类行；
    - 注释行：标签列空着、值列有字（「（空）|（是/否）」「（空）|详见附表」「（空）|（√/×）」「（空）|（元）」）——
      PR #768 第五轮评审阻断 2：改前碰到这种行就停下判「不是列头」，否决失效，核对表读出 strong「相符」。
    - 只填了一部分的行（一行两对时）：没有表单标签、有的对填满有的对空着（「资料完整性|完整|（空）|（空）」）——
      一行两对的核对表，列头和表体之间可能夹着这种半行数据；改前碰到它就停下判「不是列头」，否决失效
      （PR #768 第六轮自查）。它本身不当列头：上面没有列头（「工程概况|编号：…|（空）|（空）」这种标题行）照样不否决。
    「单位：元」与页码不算字（`_blank_mark`），所以「标题 | 第 1 页 共 1 页」也按分节行跳过，不被当成列头。
    找得越远只会多否决、不会多出值。停下的条件：有一对的标签是表单标签 → 表单行 → 不是列头；每一对标签、值都有字 →
    列头（或那张表的一整行）；到顶 → 不是列头。单列（只有一对）时，只填了一部分就是注释行 / 分类行，和上面一致。"""
    r = row - 1
    while r >= 1:
        texts = []
        for lc, vc in cols:
            lt, vt = sh.top(r, lc), sh.top(r, vc)
            texts.append((_blank_mark(_norm(sh.value(*lt))),
                          "" if lt == vt else _blank_mark(_norm(sh.value(*vt)))))
        if any(_form_cell(lab) for lab, _v in texts):
            return False        # 表单行：这一列 / 这一行标签上面接着的是表单，不是列头
        if all(lab and v for lab, v in texts):
            return True         # 每一对标签、值都有字：列头（或那张表的一整行数据）
        r -= 1                  # 空行 / 分节行 / 注释行 / 半行：列头还可能在它上面
    return False


def _is_form_row(sh: _Sheet, r: int, cols: list[tuple[int, int]]) -> bool:
    """第 `r` 行在这几对（标签列, 值列）上是不是表单行：至少一对的标签是表单标签，其余每一对要么也是表单标签、
    要么标签和值都空着（「编制单位|齐全|（空）|（空）」算）。和 `_column_header_above` 停下判「表单行」的条件同源，
    读法也一样（「单位：元」与页码不算字，标签和值同在一个合并区时值当空）。"""
    texts = []
    for lc, vc in cols:
        lt, vt = sh.top(r, lc), sh.top(r, vc)
        texts.append((_blank_mark(_norm(sh.value(*lt))), "" if lt == vt else _blank_mark(_norm(sh.value(*vt)))))
    return any(_form_cell(lab) for lab, _v in texts) and \
        all(_form_cell(lab) or not (lab or v) for lab, v in texts)


def _form_block_top(sh: _Sheet, row: int, cols: list[tuple[int, int]]) -> int:
    """从 `row` 往上走过紧挨着的表单行（`_is_form_row`），返回这块表单行的最上面一行。

    PR #768 第六轮评审阻断：一行两对的核对表「检查项|结果|检查项|结果 / 建设单位|基本相符|施工单位|不符 /
    工程名称|相符|监理单位|基本相符」—— 表体行本身就是表单标签行。判据①改前从目标行本身往上找列头，碰到上面那条
    表体行（有表单标签）就停下判「不是列头」，否决失效，读出 strong「相符」。先走到块顶再找列头，和判据④从
    `_run_members` 那一串表单标签的最上面一行往上找是同一条判据。
    评审试改版另有一条特判「块顶正上方是整行空行就不再往上找」（保住召回夹具「两对_上面半行表单_再上核对表」），
    第七轮不采用：列头和表体之间空一行的两对核对表（夹具 W7）会因它读出「相符」，而判据④对单列的同一形状
    （CHECKLISTS「空行_工程名称在中间」）本来就跳过空行往上找、照样否决。代价是那张召回表改由 LLM 读。"""
    top = row
    while top > 1 and _is_form_row(sh, top - 1, cols):
        top -= 1
    return top


def _form_row_evidence(sh: _Sheet, ltop: tuple[int, int], vtop: tuple[int, int],
                       pairs: dict, header_rows: frozenset[int]) -> Optional[str]:
    """不带冒号的「标签｜值」凭什么算表单行 → 证据名；没有正面证据 → None（不出值，交给 LLM）。

    PR #768 第四轮（用户 2026-09-30 裁定：改白名单）。前两轮是「默认出 strong，结构上能证明是列头才拦」，
    判据只看紧下一行，列头下面多一行分类行 / 空行 / 单位行、或下面接的正是表单标签就漏过去，照样出
    strong 列头词。结构上「工程名称|内容 / 建设单位|…」和「工程名称|城中河… / 建设单位|…」一模一样，
    只能靠词表区分 —— 所以一列标签的**第一行**、一行孤零零的「标签|值」一律拿不准，不出值。正面证据：
    ① 同一行排了两对以上（不算「备注」这种兼作列头词的标签），各对的值互不相同（「工程名称|相符|建设单位|相符」
       是核对表），且往下找不到数据行（`_data_rows_below`）；
    ③ 紧挨在已认出、且真从合计行读出了金额的金额表头上面（`_right_above_header`）；
    ④ 在一列连续表单标签的**中间**：正上方、正下方都是表单标签格（光标签、带冒号、一格写完都算）。
    （第四轮的判据②「行首有序号」PR #768 第五轮删掉：它分不出概况表「1|工程名称|城中河…」和核对表
    「1|工程名称|相符」，不在用户裁定列举的正面证据里。带序号的一列表单，第一行交 LLM，中间的行照样按④读。）
    ①③④ 都再过一道否决：这一行（①是紧挨着的这块表单行的最上面一行 `_form_block_top`，PR #768 第七轮；
    ③④是这一列连续表单标签的最上面一行）上方（中间只隔空行 / 分节行 / 标签列空着的注释行 / 只填了一部分的行）
    是一张表的列头（`_column_header_above`）。
    ③④再过两道否决：同一列连续的标签里还有一个映射到同一字段的（「项目名称|甲 /
    工程名称|乙」拿不准哪个是本项目的）；或另一个标签的值和它一样（核对表的「相符 / 相符」，值列不是表单值）。
    带冒号的「工程名称：」本身就是正面证据，不走这里。"""
    own = _norm(sh.value(*vtop))
    filled = [(lt, val[0]) for lt, val in pairs.items()
              if val is not None and not _is_column_head(sh.text(*lt)) and not _is_column_head(val[1])]
    if len(filled) >= 2:
        if sum(1 for _lt, vt in filled if _norm(sh.value(*vt)) == own) > 1:
            return None         # 同一行两对的值一样：核对表的结论列，不是表单值
        cols = [(lt[1], vt[1]) for lt, vt in filled]
        top = _form_block_top(sh, min(t[0] for lt, vt in filled for t in (lt, vt)), cols)
        if _column_header_above(sh, top, cols):
            return None         # 这块表单行上面是列头行：这一行是那张表的数据（PR #768 第七轮：从块顶往上找）
        return None if _data_rows_below(sh, filled, header_rows) else "two_pairs"
    if _right_above_header(sh, ltop, vtop, header_rows):
        why = "above_amount_header"
    elif _form_cell(_above(sh, ltop)) and _form_cell(_below(sh, ltop)[1]):
        why = "inside_form_block"
    else:
        return None
    field_name = _label_field(sh.text(*ltop))
    run = _run_members(sh, ltop)
    for top in run:
        lab = _form_cell(_norm(sh.value(*top)))
        if lab and _KV_LABELS.get(lab) == field_name:
            return None         # 同一列里另有一个同字段标签：拿不准哪个是本项目的
        if own and _pair_value(sh, top) == own:
            return None         # 两个不同标签的值一样：值列是核对结论 / 勾选列，不是表单值
    if _column_header_above(sh, min([ltop[0], *(t[0] for t in run)]), [(ltop[1], vtop[1])]):
        return None             # 这一列表单标签上面是列头行（「序号|检查项|结果」）：值是那一列的数据
    return why


def _kv_value(sh: _Sheet, r: int, c: int,
              header_rows: frozenset[int] = frozenset()) -> tuple[Optional[str], Optional[int]]:
    """「标签｜值」两格结构里标签格右邻的值。拿不准就不出值（退回 LLM），不拿列头当 strong 值。

    整行按「标签 [值]」依次配对：碰到一格既不是表单标签、又不是紧跟在标签后面的值 → 这一行
    不是表单行，不出值。标签的右邻是列头词 → 列头行，不出值。行首的序号格（工程概况表
    「1 | 工程名称 | 某某工程」）、页码格（「第 1 页 共 3 页」）与计量说明（「单位：元」）不参与配对 ——
    序号只是被跳过，本身不再算正面证据（PR #768 第五轮）。
    不带冒号的标签还要有正面证据（`_form_row_evidence`，第四轮白名单）才出值。`header_rows` 是真从合计行
    读出了金额的那张表的表头行（`read_grid_fields`），没读出就是空集。"""
    cells = [x for x in _row_cells(sh, r) if not _PAGE_MARK.match(x[1]) and not _UNIT_MARK.match(x[1])]
    if cells and _SEQ_MARK.match(cells[0][1]) and not _is_form_label(cells[0][1]):
        cells = cells[1:]
    pairs: dict[tuple[int, int], Optional[tuple[tuple[int, int], str, Any]]] = {}
    i = 0
    while i < len(cells):
        top, t, _raw = cells[i]
        if not _is_form_label(t):
            return None, None
        if i + 1 < len(cells) and not _is_form_label(cells[i + 1][1]):
            pairs[top] = cells[i + 1]
            i += 2
        else:
            pairs[top] = None   # 这个标签没有填值（右邻是下一个标签或行尾）
            i += 1
    ltop = sh.top(r, c)
    val = pairs.get(ltop)
    if val is None:
        return None, None
    vtop, vt, vraw = val
    if _is_column_head(vt):
        return None, None
    label_text = sh.text(*ltop)
    if not label_text.endswith(("：", ":")) and \
            _form_row_evidence(sh, ltop, vtop, pairs, header_rows) is None:
        return None, None
    return str(vraw).strip(), vtop[1]


def _inline_value(raw: str) -> Optional[str]:
    """一格写完的「工程名称：X」。后面还跟着别的标签 / 页码（GB50500 表头行）时只取到它之前；
    截完还带冒号、或截完是空（空白模板「工程名称：   标段：   第 页 共 页」）→ 不出值。"""
    value = raw.strip()
    cut = _NEXT_LABEL.search(value)
    if cut:
        value = value[:cut.start()].strip()
    if not value or re.search(r"[:：]", value):
        return None
    return value


def _looks_like_header(value: str) -> bool:
    t = _norm(value)
    return amount_column_semantic(t) is not None or "金额" in t or "(元)" in t or "（元）" in t


def _kv_candidates(sh: _Sheet, notes: list[str], skip_rows: frozenset[int] = frozenset(),
                   evidence_rows: frozenset[int] = frozenset()) -> list[dict]:
    """表头键值行：「工程名称 | 某某工程」或一格里写「工程名称：某某工程」。金额表的表头行跳过 ——
    汇总表的列头里也有「工程名称」，它右边是「合同价金额」列头，不是工程名称的值（`skip_rows`，`_header_block`
    认出的每一行都跳过）。`evidence_rows` 是白名单的一条正面证据：紧挨在它上面的「标签|值」是表头的抬头
    （`_right_above_header`）。它只在这张表真从合计行读出了金额时才等于表头行、否则是空集 ——
    `_header_block` 会把审核意见表里「合同价|按签约合同价…计」这种数据行也认成表头（PR #768 第五轮）。
    工程名称整格都是括号占位（「（盖章）」「（详见封面）」）不出值、写 note —— 带冒号 / 一行两对都算正面证据，
    改前读出 strong 占位串（PR #768 第五轮评审非阻断）。建设单位 / 施工单位有机构后缀核验，占位串只到 none，不在这里拦。"""
    out: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for r in range(1, min(_KV_SCAN_ROWS, sh.max_row) + 1):
        if r in skip_rows:
            continue
        for c in range(1, sh.max_col + 1):
            top = sh.top(r, c)
            if top in seen:
                continue
            seen.add(top)
            raw = sh.value(r, c)
            if not isinstance(raw, str):
                continue
            t = _norm(raw)
            label, value, vcol = None, None, None
            if t.rstrip("：:") in _KV_LABELS:
                label = t.rstrip("：:")
                value, vcol = _kv_value(sh, r, c, evidence_rows)
            else:
                m = re.match(r"^(工程名称|项目名称|建设单位|施工单位)[:：](.+)$", str(raw).strip())
                if m:
                    label, value, vcol = m.group(1), _inline_value(m.group(2)), top[1]
            if not label or not value or _looks_like_header(value):
                continue
            f = _KV_LABELS[label]
            if f == "工程名称" and _BRACKET_PLACEHOLDER.match(_norm(value)):
                notes.append(f"「{sh.title}」{f}的取值「{value}」整格是括号占位（签章栏 / 空白模板），不出值")
                continue
            quote = f"{label}：{value}"
            vr = verify_candidate(field_def(f), value, quote, norm_text(quote))
            if vr.reject:
                notes.append(f"「{sh.title}」{label} 的取值「{value}」被剔除（{vr.reject}）")
                continue
            cell = f"{_letter(vcol)}{r}"
            out.append({
                "field": f, "value": value, "kind": field_def(f).kind, "channel": "grid",
                "quote": f"{sh.title}!{cell}〔{label}〕= {value}",
                "evidence": {"sheet": sh.title, "cell": cell, "row": r, "row_label": label},
                "verify_level": vr.level, "verified": vr.verified, "verify_notes": list(vr.notes),
            })
    return out


def _demote_conflicting_kv(kv: list[dict], notes: list[str]) -> None:
    """同一本工作簿里，键值读法给同一字段读出两个以上不同的值 → 一律不给 strong（就地改成 weak），打
    `grid_readings_conflict` 标记、写 note。

    PR #768 第二轮评审起的兜底层。第四轮改白名单后，「只有一行表头的空白表」这类形状已经不出值；
    这里兜的是两处都有正面证据、写的却不是同一个名称（封面「工程名称：甲」、抬头「工程名称：乙」）。
    strong 的后果是这份文件的 LLM 不再问这个字段、阶段二也不补抽，所以拿不准哪个对时不能给 strong；
    同层级、互不包含的两个值在合并时再判 unresolved（K4 / D35）。
    PR #768 第七轮起 `_cap_grid_text` 把网格文本一律压到 weak，这里改级别的那一步已被它覆盖；保留的是冲突标记与
    note（告诉用户同一本里读出了哪几个不同的值）。
    金额不走这里：金额按合计行坐标取值，跨表的不同合计在合并时已按 D35 判 unresolved。"""
    by_field: dict[str, list[dict]] = {}
    for c in kv:
        by_field.setdefault(c["field"], []).append(c)
    for f, cs in by_field.items():
        distinct = {norm_text(c["value"]) for c in cs}
        if len(distinct) < 2:
            continue
        for c in cs:
            if c["verify_level"] == "strong":
                c["verify_level"] = "weak"
            c["verified"] = False
            c["verify_notes"] = [*c["verify_notes"], "grid_readings_conflict"]
        where = "、".join(f"{c['evidence']['sheet']}!{c['evidence']['cell']}「{c['value']}」" for c in cs)
        notes.append(f"同一本工作簿里{f}读出 {len(distinct)} 个不同的值（{where}），都不按强核验算，"
                     "交给模型补问与人工核对")


def _cap_grid_text(cands: list[dict]) -> None:
    """网格（键值通道，channel=grid）读出的**文本类字段**一律 verify_level 不高于 weak（就地改）。

    用户 2026-09-30 裁定 ②：工程名称、建设单位、施工单位等所有非金额字段，不论正面证据多充分，网格读数只作候选。
    六轮评审一直在补「结构上像表单、其实是另一张表的数据」的漏洞（列头词、核对结论、占位串），每一轮都还有下一种
    形状能拿到 strong —— strong 的后果是这份文件的 LLM 不再问、阶段二也不补抽、合并时压过审核报告。压到 weak 后
    这份文件照样发给 LLM 补问（`field_extract.extract_file` 只跳过已有 strong 的字段）、阶段二照样补抽
    （`api/extract._strong_fields`），最终值由合并决定（`field_extract.merge_candidates`：网格文本组只作候选，
    有网格以外出处的一组胜出）；前端按 weak 的既有样式标出。
    **金额类字段不受影响**：合计行读出的送审 / 审定 / 核减 / 核增 / 合同价按坐标回链取值，照旧 strong。
    本来就是 none 的（建设单位不带机构后缀等）保持 none；只有从 strong 压下来的才打 `grid_text_candidate` 标记。"""
    for c in cands:
        if c.get("channel") != "grid" or c.get("kind") == "amount":
            continue
        if c["verify_level"] == "strong":
            c["verify_level"] = "weak"
            c["verify_notes"] = [*c["verify_notes"], GRID_TEXT_CANDIDATE]
        c["verified"] = False


def _remark_candidates(sh: _Sheet) -> list[dict]:
    """「备注」格里常写「签约合同价为 N 元，合同工期 N 日历天」：用审核报告同一套锚定正则取。"""
    from zt.report.sections import regex_fields

    out: list[dict] = []
    for r in range(1, sh.max_row + 1):
        for c in range(1, min(4, sh.max_col) + 1):
            raw = sh.value(r, c)
            if not isinstance(raw, str):
                continue
            t = str(raw).strip()
            if _norm(t).rstrip("：:") == "备注":
                texts = [(str(sh.value(r, c2)).strip(), sh.top(r, c2)[1])
                         for c2 in range(c + 1, sh.max_col + 1)
                         if sh.top(r, c2) != sh.top(r, c) and _norm(sh.value(r, c2))]
                note, ncol = (texts[0] if texts else ("", c))
            elif re.match(r"^备\s*注\s*[:：]", t):
                note, ncol = re.split(r"[:：]", t, 1)[1].strip(), sh.top(r, c)[1]
            else:
                continue
            if not note:
                continue
            cell = f"{_letter(ncol)}{r}"
            for cand in regex_fields(note, ("合同价", "工期"), sections=[]):
                cand["channel"] = "regex"
                cand["evidence"] = {"sheet": sh.title, "cell": cell, "row": r, "row_label": "备注",
                                    "quote": cand["quote"]}
                cand["from_remark"] = True
                out.append(cand)
    return out


_SHEET_XML_RE = re.compile(r"^xl/worksheets/[^/]+\.xml$")


def largest_sheet_xml(content: bytes) -> Optional[tuple[str, int]]:
    """zip 目录里解压后最大的那张 sheet XML：(条目名, 解压后字节数)。只读目录，不解压。
    不是 zip / 目录读不了 → None（交给后面的载入去报它自己的错）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            sheets = [(i.filename, i.file_size) for i in z.infolist() if _SHEET_XML_RE.match(i.filename)]
    except (zipfile.BadZipFile, OSError, ValueError):
        return None
    return max(sheets, key=lambda x: x[1]) if sheets else None


# zt 改动：旧仓从配置 GRID_MAX_SHEET_XML_MB 取（缺省 30）；这里是调用方参数的缺省值，CLI 用 --max-sheet-xml-mb 改
DEFAULT_MAX_SHEET_XML_MB = 30


def _sheet_xml_limit_mb(explicit: Optional[int]) -> int:
    if explicit is not None:
        return max(0, int(explicit))
    return DEFAULT_MAX_SHEET_XML_MB


def read_grid_fields(content: bytes, ext: str, file_name: str = "", *,
                     max_sheet_xml_mb: Optional[int] = None,
                     include_net_reduction: bool = False) -> GridResult:
    """审定单 / 汇总表 → 带坐标的候选。读不了 / 不是这种表 → 零候选 + notes（写明为什么）。

    `max_sheet_xml_mb`：任一张 sheet XML 解压后超过它就不做整本载入（0 = 不设）；缺省
    `DEFAULT_MAX_SHEET_XML_MB`（30）。

    `include_net_reduction`（WS24-j，issue #1002）：默认 False，「净核减」列照旧不出值 —— 字段抽取（WS07）
    没有这个字段，识别它只为不把它当成核减金额（QA:extract-01 的错列）。只有报告的金额事实（report_facts）
    传 True：净核减是资料里写着的一格，报告要用它，程序不拿「送审 − 审定」去算（D-R60 不派生）。
    字段抽取的调用点（field_extract、pricebook_fields）不传，行为不变（tests/test_report_facts.py 有源码棘轮）。"""
    res = GridResult()
    ext = (ext or "").lower().lstrip(".")
    if ext == "xls":
        # zt 改动：本机不装 LibreOffice，不转换 .xls（与 zt.costsheet 同口径）
        res.notes.append(f"{file_name}：旧版 .xls 不能直接读取，请用 Excel/WPS 另存为 .xlsx；网格通道跳过")
        return res
    if ext not in ("xlsx", "xlsm"):
        return res
    if len(content) > MAX_BYTES:
        res.notes.append(f"{file_name}：文件超过 20MB，网格通道跳过")
        return res
    # 格数闸的前半截，必须在整本载入**之前**（整改 spec WS22-h，issue #794）：下面的 MAX_CELLS 要等
    # 非只读载入完才查得到，而载入本身就是膨胀的那一步 —— 本机实测一份 3.9 MB 的 xlsx（sheet XML
    # 解压后 40.8 MB，200 万个带样式的空格）载入后常驻内存 +693 MB，然后才报「超过 200000 格，跳过」。
    # 这里只看 zip 目录里的解压后大小，不解压。跳过的只是网格通道，正文通道（只读流式）照常。
    limit_mb = _sheet_xml_limit_mb(max_sheet_xml_mb)
    biggest = largest_sheet_xml(content) if limit_mb > 0 else None
    if biggest is not None and biggest[1] > limit_mb * 1024 * 1024:
        res.notes.append(
            f"{file_name}：工作表数据（{biggest[0].rsplit('/', 1)[-1]}）解压后 {biggest[1] / 1048576:.0f} MB，"
            f"超过 {limit_mb} MB，整本载入会占用过多内存，网格通道跳过（正文照常读取）")
        return res
    try:
        wb, wnotes = load_workbook_tolerant(content, read_only=False, data_only=True)
    except XlsxUnreadable as e:
        res.notes.append(f"{file_name}：{e.message}")
        return res
    except Exception as e:  # noqa: BLE001 —— 网格通道读不了就退回 LLM，不让整份文件失败
        res.notes.append(f"{file_name}：openpyxl 读取失败（{type(e).__name__}），网格通道跳过")
        return res
    res.notes.extend(f"{file_name}：{n['message']}" for n in wnotes if n.get("level") != "info")
    kv_all: list[dict] = []
    try:
        for ws in wb.worksheets:
            state = getattr(ws, "sheet_state", "visible") or "visible"
            if state != "visible":
                # QA:report-12：空白模板里的隐藏示例表带着示例金额
                res.notes.append(f"跳过隐藏工作表「{ws.title}」（sheet_state={state}，hidden）")
                continue
            if (ws.max_row or 0) * (ws.max_column or 0) > MAX_CELLS:
                res.notes.append(f"工作表「{ws.title}」超过 {MAX_CELLS} 格，网格通道跳过")
                continue
            sh = _Sheet(ws)
            block = _header_block(sh)
            amt_notes: list[str] = []
            amounts = (_amount_candidates(sh, block, amt_notes, include_net_reduction)
                       if block is not None else [])
            # 金额表头能当「抬头」的正面证据，前提是这张表真从合计行读出了金额（PR #768 第五轮）：
            # 「只有 1 行数据」的兜底不算 —— 审核意见表里被误认成表头的一行下面，恰好有一行带数的也会走到它
            from_total = any(c["evidence"]["row_label"] in _TOTAL_LABELS for c in amounts)
            kv = _kv_candidates(sh, res.notes, frozenset(block or ()),
                                frozenset(block) if block is not None and from_total else frozenset())
            kv_all.extend(kv)
            res.candidates.extend(kv)
            res.notes.extend(amt_notes)
            res.candidates.extend(amounts)
            res.candidates.extend(_remark_candidates(sh))
        _demote_conflicting_kv(kv_all, res.notes)
        _cap_grid_text(res.candidates)      # 裁定 ②：网格文本只作候选（金额不动）
    finally:
        try:
            wb.close()
        except Exception:  # noqa: BLE001
            pass
    return res
