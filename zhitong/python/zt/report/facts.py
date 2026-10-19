# 来源：engine-service/app/engine/report_facts.py（zhitong-cost-ai@991ff5c，W3 搬入 zt；改动见本文件内「zt 改动」注释）
"""AI 报告初稿的金额事实（WS24-j，issue #1002；spec WS24 §3.8；总纲 K-R18、K-R44、C-R13、D-R60、D-R65）。

为什么有它：报告里的金额改前全靠模型从资料里抄（系统提示词规则 2），护栏只核对「这个数在资料里出现过」，
不核对「它是不是这个意思的数」。运行 D 的「五、审核结果」模型自己编了〔F1〕…〔F20〕（RM-C26），WS24-g 只能
把它们全换成【待补：金额】。本模块让资料里**写着的那一格**由程序读出来、带「文件 / 工作表 / 单元格」来源，
模型只写占位符（铁律 2：LLM 不碰金额）。

两条通道，都是确定性读取，不新写读表规则：

- **通道一 · 审定单 / 汇总表**：调 WS07 的 `approval_grid.read_grid_fields`（列语义是严格词表、合计行、单元格坐标），
  只多传一个 `include_net_reduction=True`（净核减是资料里写着的一格，字段抽取不要它，报告要）。同一份文件多张表
  给出同一个金额且值不同：只认表名整名在汇总级词表里的那一张；恰好一张就取它，零张或多张记冲突、不取舍。
- **通道二 · 项目级费用表**：调 WS26-h 的 `costsheet.parse_costsheet`（与指标同一条路径，K-R44：报告、指标、字段
  提取候选拿到的是同一个格子）。只认一种结果：WS26-h 采用的是项目级合计，而且与各单位工程费用表之和勾稽过
  （差 ≤ 1 元）。采用「各单位工程之和」、勾稽不过、取不到，都不出事实（D-R60 不派生：相加出来的数不是资料里
  写着的一格）。

规则（C-R13）：金额只取资料里写着的一个格子并带来源；多于一个候选是冲突，不取舍；不派生（不相加、不相减）。
不同文件给出同一个金额且值不同：都留着，`conflict=true`。

替换（`substitute_facts`）在护栏之后做：已知、本章允许、无冲突 → 单元格原显示 + 单位；冲突 → 列出各处的值并标
【待核】；本章不允许 → 【待核：本章不应出现此金额】；不认识的编号 → 【待补：金额】。

zt 改动：不连库、不经 HTTP；facts 由 `python -m zt.report.cli facts` 写进 `工作/<日期>-报告/facts.json`，
之后每章的 section_prepare / section_finalize 读同一份文件（同一份输入编号不变）。
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Callable, Iterable, Optional, Sequence

from zt.amounts.amounts import format_yuan
from zt.common import ZtError
from zt.costsheet.parser import parse_costsheet
from zt.report.approval_grid import read_grid_fields
from zt.report.guard import MARK_FACT_TODO, MARK_OUT_OF_SCOPE, MARK_TRANSCRIBED_AMOUNT, GuardFlag

log = logging.getLogger("zt.report.facts")

# 金额事实的键 → 给人看的名字。顺序就是 F1、F2… 的编号顺序（同一份输入编号不变，context_hash 才稳）
FACT_LABELS: dict[str, str] = {
    "submitted_total": "送审金额",
    "approved_total": "审定金额",
    "reduction": "核减金额",
    "increase": "核增额",
    "net_reduction": "净核减金额",
    "contract_price": "合同价",
    "control_price_total": "招标控制价",
    "bid_price_total": "投标报价",
}

# approval_grid 的列语义（consulting_fields.AMOUNT_COLUMN_RULES）→ 事实键
_GRID_FIELD_KEY = {
    "送审金额": "submitted_total",
    "审定金额": "approved_total",
    "核减金额": "reduction",
    "核增额": "increase",
    "净核减": "net_reduction",
    "合同价": "contract_price",
}

# 汇总级的表名（整名相等才算，NFKC、去空白后比）：同一份文件多张表各有一个合计时，只认这一张
SUMMARY_SHEET_NAMES = frozenset(("汇总表", "汇总", "审定单", "工程造价审定单", "结算审核汇总表", "审核汇总表"))

SPREADSHEET_EXTS = frozenset(("xlsx", "xlsm", "xls"))
# 单份上限与取材、审定单网格通道同一个口径（D-R02 / approval_grid.MAX_BYTES）
FACTS_MAX_FILE_BYTES = 20 * 1024 * 1024
# 引擎端总时限（spec §3.8「时限与失败」）：在文件之间检查，到时后没读的文件记进 notes
FACTS_DEADLINE_MS = 60_000

# ================================================================ 读取

@dataclass
class _Cand:
    key: str
    value: str                 # 元，两位小数（format_yuan 口径）
    display: str               # 单元格原显示
    unit: str                  # 元 / 万元
    source: dict               # {file_id, file_name, sheet, cell}
    check: Optional[dict] = None


@dataclass
class FactsResult:
    facts: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    files_total: int = 0                       # 送来的表格份数（别的格式不算）
    files_read: int = 0
    timed_out: list[str] = field(default_factory=list)
    # 没读成的表格：(file_id, file_name, 原因)。结果契约的 coverage.skipped 用
    skipped: list[tuple[str, str, str]] = field(default_factory=list)


def _sheet_key(name: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name or ""))


_SUMMARY_KEYS = frozenset(_sheet_key(n) for n in SUMMARY_SHEET_NAMES)


def is_summary_sheet(name: str) -> bool:
    return _sheet_key(name) in _SUMMARY_KEYS


def _source(file_id: str, file_name: str, sheet: str, cell: Optional[str]) -> dict:
    return {"file_id": file_id, "file_name": file_name, "sheet": sheet, "cell": cell}


def grid_candidates(content: bytes, ext: str, file_id: str, file_name: str, notes: list[str]) -> list[_Cand]:
    """通道一：审定单 / 汇总表的合计行 → 每个金额键至多一个候选（同一文件里多张表的取舍见模块说明）。"""
    res = read_grid_fields(content, ext, file_name, include_net_reduction=True)
    by_key: dict[str, list[_Cand]] = {}
    for c in res.candidates:
        key = _GRID_FIELD_KEY.get(c.get("field") or "")
        # 只要合计行那一格（channel=grid）；备注里正则读出的金额（channel=regex）不是「写在格子里的那个数」
        if key is None or c.get("kind") != "amount" or c.get("channel") != "grid":
            continue
        ev = c.get("evidence") or {}
        by_key.setdefault(key, []).append(_Cand(
            key=key, value=c["amount_yuan"], display=str(c["value"]), unit=c.get("unit") or "元",
            source=_source(file_id, file_name, ev.get("sheet") or "", ev.get("cell"))))
    out: list[_Cand] = []
    for key, cands in by_key.items():
        if len({c.value for c in cands}) == 1:
            out.extend(cands)
            continue
        summary = [c for c in cands if is_summary_sheet(c.source["sheet"])]
        if len(summary) == 1:
            out.append(summary[0])
            continue
        # 零张或多张汇总级的表：几张表各写一个不同的数，程序不替用户选（C-R13）
        out.extend(cands)
        notes.append(f"《{file_name}》有 {len(cands)} 张表各写了一个{FACT_LABELS[key]}且不相同，"
                     + ("没有一张是汇总表" if not summary else f"其中 {len(summary)} 张都是汇总级的表")
                     + "，程序不取舍")
    return out


def _fee_key(hit: dict) -> Optional[str]:
    """项目级合计是招标控制价还是投标报价：看表名与合计行名。两样都写不明白就不认（不猜）。"""
    text = unicodedata.normalize("NFKC", f"{hit.get('sheet') or ''}{hit.get('label') or ''}")
    if "投标" in text:
        return "bid_price_total"
    if "招标控制价" in text or "控制价" in text:
        return "control_price_total"
    return None


def _money(v) -> Optional[str]:
    if v is None:
        return None
    try:
        return format_yuan(Decimal(repr(float(v))))
    except (InvalidOperation, ValueError, TypeError):
        return None


def fee_candidates(content: bytes, file_id: str, file_name: str, notes: list[str], *,
                   ext: str = "xlsx") -> list[_Cand]:
    """通道二：项目级费用表合计。只调 WS26-h 的读取器（K-R18 / K-R44），不改它的取数与采用规则。
    ext：content 的实际格式（zt 里 .xls 在 collect_facts 就跳过了，这里只会是 xlsx / xlsm）。"""
    parse_name = file_name if (file_name or "").lower().endswith("." + ext) else f"{file_name}.{ext}"
    meta = parse_costsheet(content, parse_name, file_id=file_id)["meta"]
    chk = meta.get("fee_total_check") or {}
    if not chk.get("has_fee_sheet"):
        return []
    source = chk.get("source")
    hit = chk.get("hit") or {}
    if source == "project" and hit.get("cell") and hit.get("amount_str"):
        key = _fee_key(hit)
        if key is None:
            notes.append(f"《{file_name}》项目级合计读到了（{hit.get('sheet')}!{hit.get('cell')}），"
                         "但表名与行名都没写明是招标控制价还是投标报价，不作为金额事实")
            return []
        layer_notes = chk.get("notes") or []
        check = {
            "p": _money(chk.get("project_total")),
            "u": _money(chk.get("unit_sum")), "n_unit": chk.get("unit_count"),
            "s": _money(chk.get("single_sum")), "n_single": chk.get("single_count"),
            "z": _money(chk.get("specialty_sum")), "n_specialty": chk.get("specialty_count"),
            "diff": _money(chk.get("diff")),
            # WS26-h 自己写的那句「项目级合计 P，n 张单位工程费用表之和 U，差 d 元」：界面「来源」照抄它
            "text": layer_notes[0] if layer_notes else None,
        }
        return [_Cand(key=key, value=hit["amount_str"], display=hit.get("display") or hit["amount_str"],
                      unit="元", source=_source(file_id, file_name, hit.get("sheet") or "", hit.get("cell")),
                      check=check)]
    if source == "unit_sum":
        notes.append(f"《{file_name}》只有各单位工程费用表，没有项目级合计，程序不相加"
                     f"（{chk.get('unit_count')} 张单位工程费用表之和只用于指标，不作为报告的金额事实）")
    elif source == "single_hit":
        notes.append(f"《{file_name}》只读到一个合计行（{hit.get('sheet')}），没有另一层费用表可以勾稽，"
                     "不作为金额事实")
    elif chk.get("reason"):
        notes.append(f"《{file_name}》费用表合计没有采用：{chk['reason']}")
    return []


def _merge(cands: Sequence[_Cand]) -> list[dict]:
    """全部候选 → 事实（每个键一条），按 FACT_LABELS 的顺序编号 F1、F2…"""
    by_key: dict[str, list[_Cand]] = {}
    for c in cands:
        by_key.setdefault(c.key, []).append(c)
    out: list[dict] = []
    for key in FACT_LABELS:
        cs = by_key.get(key)
        if not cs:
            continue
        sources: list[dict] = []
        for c in cs:
            if c.source not in sources:
                sources.append(c.source)
        values = {c.value for c in cs}
        fact = {"id": f"F{len(out) + 1}", "key": key, "label": FACT_LABELS[key], "sources": sources,
                "conflict": len(values) > 1, "candidates": [], "check": None}
        if len(values) == 1:
            first = cs[0]
            fact.update(value=first.value, display=first.display, unit=first.unit, check=first.check)
        else:
            fact.update(value=None, display=None, unit=None)
            fact["candidates"] = [{"value": c.value, "display": c.display, "unit": c.unit, "source": c.source}
                                  for c in cs]
        out.append(fact)
    return out


def collect_facts(files: Sequence[tuple[str, str, Callable[[], bytes]]], *,
                  deadline_ms: int = FACTS_DEADLINE_MS,
                  clock: Callable[[], float] = time.monotonic,
                  size: Optional[Callable[[str], int]] = None) -> FactsResult:
    """读勾选资料里表格的金额事实。

    zt 改动：读字节的函数抛 :class:`zt.common.ZtError`，``invalid_path``（越界、绝对路径）原样往外抛（安全信号，
    不许吞）；其余单份失败只记 note。``.xls`` 不转换，记一条跳过原因（请另存为 xlsx）。

    :param files: ``[(file_id, file_name, 读字节的函数)]``；表格以外的文件不读。
    :param deadline_ms: 总时限；在文件之间检查，到时后没读的文件记进 notes。
    :param clock: 计时函数（测试可注入）。
    :param size: 按 file_id 给字节数（只 stat 不读），超过 20 MB 的不读进内存。
    :returns: 事实、notes 与覆盖度。
    :raises ZtError: 路径越界或非法（``invalid_path``）。
    """
    res = FactsResult()
    start = clock()
    cands: list[_Cand] = []
    for file_id, file_name, load in files:
        ext = (file_name.rsplit(".", 1)[-1].lower() if "." in (file_name or "") else "")
        if ext not in SPREADSHEET_EXTS:
            continue
        res.files_total += 1

        def skip(reason: str, note: str) -> None:
            res.skipped.append((file_id, file_name, reason))
            res.notes.append(note)

        if (clock() - start) * 1000 >= deadline_ms:
            res.timed_out.append(file_name)
            res.skipped.append((file_id, file_name, "金额事实读取超时"))
            continue
        if ext == "xls":
            skip("旧版 .xls 不能直接读取", f"《{file_name}》是旧版 .xls，请用 Excel/WPS 另存为 .xlsx 后再读金额")
            continue
        try:
            if size is not None and size(file_id) > FACTS_MAX_FILE_BYTES:
                skip("超过 20 MB", f"《{file_name}》超过 20 MB，没有读金额")
                continue
            content = load()
        except ZtError as e:
            if e.code == "invalid_path":
                raise
            skip("读不到", f"《{file_name}》读不到（{e.message}），没有读金额")
            continue
        if len(content) > FACTS_MAX_FILE_BYTES:
            skip("超过 20 MB", f"《{file_name}》超过 20 MB，没有读金额")
            continue
        res.files_read += 1
        try:
            cands.extend(grid_candidates(content, ext, file_id, file_name, res.notes))
        except Exception as e:  # noqa: BLE001 —— 一份读坏了不连累别的文件
            log.warning("报告金额事实：审定单通道读取出错 %s：%s", file_name, e)
            res.notes.append(f"《{file_name}》按审定单读金额时出错（{type(e).__name__}），跳过")
        try:
            cands.extend(fee_candidates(content, file_id, file_name, res.notes, ext=ext))
        except Exception as e:  # noqa: BLE001
            log.warning("报告金额事实：费用表通道读取出错 %s：%s", file_name, e)
            res.notes.append(f"《{file_name}》按费用表读金额时出错（{type(e).__name__}），跳过")
    for name in res.timed_out:
        res.notes.append(f"金额事实读取超时：{name}")
    res.facts = _merge(cands)
    return res


def needed_notice(facts: Sequence[dict], needed_keys: Iterable[str]) -> Optional[str]:
    """模板有章节声明了金额事实、而本次一个都没读到 → 第四步顶部那句提示（R24-46）；不需要提示 → None。"""
    needed = [k for k in FACT_LABELS if k in set(needed_keys or ())]
    if not needed or any(f.get("key") in needed for f in facts):
        return None
    labels = "、".join(FACT_LABELS[k] for k in needed[:4])
    return (f"这套模板需要{labels}等金额，所选资料里没有读到金额：本稿金额没有程序取数，"
            "金额位全部是【待补】或 AI 转写，请核对原件")


# ================================================================ 提示词

def _where(src: dict) -> str:
    cell = f"!{src['cell']}" if src.get("cell") else ""
    return f"《{src.get('file_name') or ''}》{src.get('sheet') or ''}{cell}"


def prompt_block(facts: Sequence[dict]) -> Optional[str]:
    """本章允许的事实 → 提示词里单独一块。**不给数值**（铁律 2：模型拿不到数，就写不出别的数）；没有事实回 None。"""
    if not facts:
        return None
    lines = []
    for f in facts:
        if f.get("conflict"):
            where = "、".join(_where(s) for s in f.get("sources") or [])
            lines.append(f"〔{f['id']}〕{f['label']}（几处资料写的不一致：{where}；程序会把各处的值都列出来）")
        else:
            src = (f.get("sources") or [{}])[0]
            lines.append(f"〔{f['id']}〕{f['label']}（来源{_where(src)}）")
    return ("【金额事实（程序已从资料的单元格读出，数值不在这里）】\n"
            "正文写到下列金额时，只写它的占位符，例如「送审金额为〔F1〕」：不写数字、不写单位、不做任何换算，"
            "程序会把占位符换成单元格里的原值并注明来源。这些金额只能写占位符，写作结构要求里「金额逐字照抄」"
            "的说法对它们不适用；不在下列编号里的金额不得自编占位符。\n"
            + "\n".join(lines))


# ================================================================ 替换

# 占位符连同模型在它后面写的单位：单位以程序取到的为准（「〔F1〕万元」而事实是元时不能拼成「321721万元」）
_PLACEHOLDER_RE = re.compile(r"〔[FＦ](\d+)〕(?:[ \t]*(?:万元|亿元|元))?")


def _safe(s: str) -> str:
    """名字进【…】标记之前去掉会提前闭合标记的字符（表名「…费用表【地下室】」里就有）。"""
    return (s or "").replace("【", "（").replace("】", "）").replace("\n", " ")


def _conflict_mark(f: dict) -> str:
    parts = [f"{_safe(_where(c['source']))} 为 {c['display']}{c['unit']}" for c in f.get("candidates") or []]
    return "【待核：金额冲突，" + "，".join(parts) + "】"


def substitute_facts(text: str, facts: Sequence[dict],
                     allowed_keys: Iterable[str]) -> tuple[str, list[GuardFlag], list[dict]]:
    """护栏之后把正文里的〔Fn〕换掉。返回 (新正文, flags, amount_refs)。

    - 已知、本章允许、无冲突 → 单元格原显示 + 单位；amount_refs 记一条 origin=fact（带 sheet、cell、check）。
    - 冲突 → 「【待核：金额冲突，《A》表!格 为 x，《B》表!格 为 y】」+ fact_conflict。
    - 本章不允许的事实 → 「【待核：本章不应出现此金额】」+ out_of_scope_amount。
    - 不认识的编号（模型自造的）→ 「【待补：金额】」+ bad_placeholder（与 WS24-g 的止血同一个标记）。
    """
    by_id = {f["id"]: f for f in facts}
    allowed = set(allowed_keys or ())
    flags: list[GuardFlag] = []
    refs: list[dict] = []

    def _sub(m: re.Match) -> str:
        fid = f"F{int(m.group(1))}"
        f = by_id.get(fid)
        if f is None:
            flags.append(GuardFlag("bad_placeholder", m.group(0),
                                   f"金额占位符「{m.group(0)}」没有程序取数，已换成{MARK_FACT_TODO}"))
            return MARK_FACT_TODO
        if f["key"] not in allowed:
            flags.append(GuardFlag("out_of_scope_amount", m.group(0),
                                   f"「{f['label']}」不是本章该写的金额，没有替换，已标【待核】"))
            return MARK_OUT_OF_SCOPE
        if f.get("conflict"):
            flags.append(GuardFlag("fact_conflict", m.group(0),
                                   f"「{f['label']}」在几处资料里写的不一致，程序不取舍，已列出各处的值并标【待核】"))
            return _conflict_mark(f)
        shown = f"{f['display']}{f['unit']}"
        src = (f.get("sources") or [{}])[0]
        ref = {"raw": shown, "value": f["value"], "file_ids": [s["file_id"] for s in f.get("sources") or []][:3],
               "origin": "fact", "fact_id": fid, "key": f["key"], "label": f["label"],
               "file_name": src.get("file_name"), "sheet": src.get("sheet"), "cell": src.get("cell")}
        if f.get("check"):
            ref["check"] = f["check"]
        refs.append(ref)
        return shown

    return _PLACEHOLDER_RE.sub(_sub, text or ""), flags, refs


__all__ = [
    "FACTS_DEADLINE_MS",
    "FACTS_MAX_FILE_BYTES",
    "FACT_LABELS",
    "MARK_OUT_OF_SCOPE",
    "MARK_TRANSCRIBED_AMOUNT",
    "SPREADSHEET_EXTS",
    "SUMMARY_SHEET_NAMES",
    "FactsResult",
    "collect_facts",
    "fee_candidates",
    "grid_candidates",
    "is_summary_sheet",
    "needed_notice",
    "prompt_block",
    "substitute_facts",
]
