# 来源：engine-service/app/engine/tk_align.py（zhitong-cost-ai@991ff5cd，W2 搬入 zt；改动见本文件内「zt 改动」注释）
"""送审行 ↔ 合同/中标清单基准行 严格对齐 —— tk/detect 端点 v2 基准规则族的依赖。

WS08-07（issue #760，铁律 3「严格查表，不做模糊匹配，查不到就是查不到」）重写。
移植自素材仓 scripts/detect/align.py 的旧版有两条会编金额的路：
  · 精确分支只比编码，不看名称与单位 —— 04B003「接驳费用」对上基准里同码的「检查井高度调整」，
    照样出价差；
  · 编码没对上就用 difflib 比「名称+单位+特征」相似度 ≥0.3 认模糊对齐，并据此产出价差/量差
    金额 —— De315 PE 管对上 De500 PE 管。
现在四种结果：
  EXACT     国标编码规范化后相等 **且** 名称归一后相等 **且** 单位同义后相等；
            补充码 / 无编码 / 非国标编号不按编码跨文件对齐，要求 名称+特征+单位 三项归一后完全相等。
            只有 EXACT 能出金额（超合同 / 漏报）。
  CONFLICT  编码相同但对不上：国标码名称或单位不同；补充码/字母编号的名称、特征、单位任一不同。
            不出金额，进 alignment_issues，待人工指定（04B003「接驳费用」对「检查井高度调整」）。
  SUGGEST   原来的模糊候选（名称+单位相同、特征不同，或编码没对上但名称+单位相同）：
            只进 align_suggestions 给人看，不带金额，也不判「合同外新增」。
  NEW_ITEM  什么都对不上：合同外新增候选（是否出条目另由基准覆盖率护栏决定，见 tk_engine）。

WS26-m（issue #828，铁律 3）加第五种结果，并改掉「同一个键在合同清单里有多行时取第一行」：
  AMBIGUOUS 严格键命中了多行，收窄后仍不唯一：不出金额，进 alignment_issues 待人工指定，
            候选全部列出；不算合同外新增，也不算严格对齐。
  严格键本身不变。命中多行时依次收窄，哪一步剩下恰好一行就对到那一行：
    ① 同单位工程（归一后相等）；② 补充码 / 无编码行再看编码原文（在同单位工程的候选里，
    没有同单位工程的候选时在全部候选里）。
  多栋楼的项目里，补充清单项每栋楼各列一次（名称、特征、单位相同，编码各编各的）是常态。旧版一律
  对到最先出现的那栋楼：一份清单自己比自己报出 13 条置信「高」的工程量疑似超合同，8855 行里
  205 行比的是别的楼。
  单位工程不进对齐键：送审与合同的表名、单位工程写法不一致时（进度款报审表常见），放进键里会
  整份对不上。合同里那个键只有一行时不看单位工程。也不按金额、工程量挑最接近的 —— 那是猜。
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from zt.code_registry.registry import GB, normalize_code

EXACT = "exact"
CONFLICT = "conflict"
SUGGEST = "suggest"
NEW_ITEM = "new_item"
AMBIGUOUS = "ambiguous"

_WS = re.compile(r"\s+")
_BRACKETS = str.maketrans({"（": "(", "）": ")", "【": "[", "】": "]", "，": ",", "；": ";", "：": ":"})

# 单位同义：只收**口径完全相同**的写法。「个」与「只」、「项」与「宗」不算同义 ——
# 对不上就是对不上（铁律 3），宁可进 CONFLICT 让人看。
_UNIT_SYNONYMS = {
    "m3": ("m3", "m³", "立方米", "立方", "方"),
    "m2": ("m2", "m²", "平方米", "平米", "平方"),
    "m": ("m", "米", "延长米"),
    "t": ("t", "吨"),
    "kg": ("kg", "千克", "公斤"),
    "km": ("km", "千米", "公里"),
}
_UNIT_CANON = {alias: canon for canon, aliases in _UNIT_SYNONYMS.items() for alias in aliases}


def norm_text(s) -> str:
    """名称/特征归一：NFKC（全角转半角）、去空白、括号标点统一、小写。不做同义替换。"""
    t = unicodedata.normalize("NFKC", str(s or "")).translate(_BRACKETS)
    return _WS.sub("", t).lower()


def norm_unit(s) -> str:
    u = norm_text(s)
    return _UNIT_CANON.get(u, u)


def _pno(r: dict) -> str:
    return str(r.get("project_id", "")).split(".")[0].strip()


def _unit_project_raw(r: dict) -> str:
    """单位工程：costsheet 取表头上方的「单位工程名称」，没有时是表名。与 rule_duplicate 的分组同一口径。"""
    return str(r.get("unit_project") or r.get("sheet") or "").strip()


def _code_key(v) -> tuple[Optional[str], bool]:
    """(规范编码, 是否国标)。只有国标编码（9–12 位，规范化补前导 0）凭编码+名称+单位认同一条；
    补充码 01B047、字母编号 LC2020 在两份文件里可能指两样东西（各家自编流水号），
    编码相同只用来发现冲突，认同一条要 名称+特征+单位 三项全等。"""
    nc = normalize_code(v)
    if not nc.is_item_code:
        return None, False
    return nc.display.lower(), nc.kind == GB


@dataclass
class Alignment:
    base: Optional[dict]
    method: str
    reason: str = ""
    candidates: tuple = ()


def build_index(baselines: list[dict]) -> dict:
    by_code: dict[tuple, list[dict]] = defaultdict(list)
    by_ident: dict[tuple, list[dict]] = defaultdict(list)
    by_name_unit: dict[tuple, list[dict]] = defaultdict(list)
    for b in baselines:
        pno = _pno(b)
        code, _gb = _code_key(b.get("item_code"))
        if code:
            by_code[(pno, code)].append(b)
        name, unit = norm_text(b.get("item_name")), norm_unit(b.get("unit"))
        if name:
            by_ident[(pno, name, norm_text(b.get("item_feature")), unit)].append(b)
            by_name_unit[(pno, name, unit)].append(b)
    return {"by_code": dict(by_code), "by_ident": dict(by_ident), "by_name_unit": dict(by_name_unit)}


def _diffs(row: dict, c: dict, *, with_feature: bool) -> str:
    out = []
    if norm_text(c.get("item_name")) != norm_text(row.get("item_name")):
        out.append("名称不同")
    if with_feature and norm_text(c.get("item_feature")) != norm_text(row.get("item_feature")):
        out.append("项目特征不同")
    if norm_unit(c.get("unit")) != norm_unit(row.get("unit")):
        out.append("单位不同")
    return "编码相同但" + ("、".join(out) or "对不上")


def _resolve(row: dict, hits: list[dict], *, is_gb: bool) -> Alignment:
    """严格键命中的候选 → 唯一的那一行，或 AMBIGUOUS（铁律 3：分不清对哪一行就不出数，不取第一条）。"""
    if len(hits) == 1:
        return Alignment(hits[0], EXACT)
    up_raw = _unit_project_raw(row)
    up = norm_text(up_raw)
    # 送审行自己没有单位工程信息时不收窄：空对空不算「同单位工程」
    same_up = [c for c in hits if up and norm_text(_unit_project_raw(c)) == up]
    if len(same_up) == 1:
        return Alignment(same_up[0], EXACT)
    if not is_gb:
        # 国标码的编码已经在键里，再比一次分不开；补充码各编各的流水号，同名同特征同单位时靠它分
        raw = norm_text(row.get("item_code"))
        same_text = [c for c in (same_up or hits) if norm_text(c.get("item_code")) == raw]
        if len(same_text) == 1:
            return Alignment(same_text[0], EXACT)
    key = "同编码同名称同单位" if is_gb else "同名称同特征同单位"
    if same_up:
        why = f"其中 {len(same_up)} 行与送审行同在单位工程「{up_raw}」"
    elif up_raw:
        why = f"没有一行的单位工程与送审行的「{up_raw}」写法相同"
    else:
        why = "送审行没有单位工程信息"
    return Alignment(None, AMBIGUOUS, f"合同清单里有 {len(hits)} 行{key}，{why}，无法确定对哪一行", tuple(hits))


def align_row(row: dict, index: dict) -> Alignment:
    pno = _pno(row)
    name, unit = norm_text(row.get("item_name")), norm_unit(row.get("unit"))
    code, is_gb = _code_key(row.get("item_code"))
    same_code = index["by_code"].get((pno, code), []) if code else []
    if is_gb:
        hits = [c for c in same_code if norm_text(c.get("item_name")) == name and norm_unit(c.get("unit")) == unit]
        if hits:
            return _resolve(row, hits, is_gb=True)
        if same_code:
            return Alignment(same_code[0], CONFLICT, _diffs(row, same_code[0], with_feature=False), tuple(same_code))
    elif name:
        hits = index["by_ident"].get((pno, name, norm_text(row.get("item_feature")), unit), [])
        if hits:
            return _resolve(row, hits, is_gb=False)
        if same_code:
            return Alignment(same_code[0], CONFLICT, _diffs(row, same_code[0], with_feature=True), tuple(same_code))
    if name:
        sug = index["by_name_unit"].get((pno, name, unit), [])
        if sug:
            return Alignment(None, SUGGEST, "名称与单位相同但编码或项目特征不同", tuple(sug))
    return Alignment(None, NEW_ITEM)


def align_stats(rows: list[dict], index: dict) -> dict:
    """每项目 精确/冲突/建议/新增/多行可对 五档计数。"""
    per: dict[str, dict] = {}
    for r in rows:
        a = align_row(r, index)
        d = per.setdefault(_pno(r), {EXACT: 0, CONFLICT: 0, SUGGEST: 0, NEW_ITEM: 0, AMBIGUOUS: 0, "total": 0})
        d[a.method] += 1
        d["total"] += 1
    return per
