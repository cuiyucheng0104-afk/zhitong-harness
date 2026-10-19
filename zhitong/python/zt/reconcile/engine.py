# 来源：engine-service/app/engine/reconcile_engine.py（zhitong-cost-ai@991ff5cd，W2 搬入 zt；改动见本文件内「zt 改动」注释）
"""双方对账引擎 —— reconcile/run 端点的引擎层。

核心比差算法 `reconcile()` 移植自素材仓 `app/engine/reconcile.py`（本身无 DB 耦合,
纯函数,原样搬运,未改动一行算法逻辑)。`run()` 是本服务新写的接线层:调用
`zt.costsheet.parser.parse_costsheet`（旧仓 `app.engine.costsheet`）把送审/审定两份广联达导出 Excel 解析成结构化
清单行,再喂给 `reconcile()`,最后整理成契约要求的
`{rows, total_diff, usage}` 形状(usage 由 API 层按真实耗时填,这里只管算)。

口径(结算审核规范惯例):
- 核减额(审减) = 送审合价 − 审定合价;正=审减,负=审增。
- 核减率 = 核减额 / 送审总价。
- 匹配主键:项目编码;缺编码用 名称|特征|单位 兜底。允许一码多行(队列消费)。
纯 Python,确定可复算;不调用 LLM。
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal

from openpyxl.utils import get_column_letter

from zt.costsheet.parser import basis_rejection, parse_costsheet, scope_label, to_cents
from zt.costsheet.warning_codes import warn

# WS08-19：金额按「分」比较（ROUND_HALF_UP 取整后的整数分），相差不超过 1 分判一致并注明舍入差。
# 旧版 abs(a-b) <= 0.01 在二进制浮点上比：4316.76 对 4316.77 的差是 0.010000000000218，判成「调整」。
_ROUND_CENTS = 1
# 行内算术校验容差：|量×价 − 合价| ≤ max(1 元, 0.5%)
_CALC_ABS_TOL = 1.0
_CALC_REL_TOL = 0.005


def _nkey(s) -> str:
    return re.sub(r"\s+", "", str(s or "")).lower()


def _item_keys(it: dict) -> tuple[str, str]:
    """返回 (强键=编码, 弱键=名称|特征|单位)。编码太短视为无。"""
    code = _nkey(it.get("code"))
    strong = code if len(code) >= 3 else ""
    weak = _nkey(it.get("name")) + "|" + _nkey(it.get("feature"))[:60] + "|" + _nkey(it.get("unit"))
    return strong, weak


def _f(x) -> float:
    return float(x) if isinstance(x, (int, float)) else 0.0


def reconcile(items_a: list[dict], items_b: list[dict],
              label_a: str = "送审", label_b: str = "审定") -> dict:
    """对账。items_a=送审方明细,items_b=审定/报审方明细(costsheet.parse 的 items)。"""
    # B 侧索引:强键、弱键各建队列(list 保序,匹配后置空表示已消费)
    b_strong: dict[str, list[int]] = {}
    b_weak: dict[str, list[int]] = {}
    for j, it in enumerate(items_b):
        s, w = _item_keys(it)
        if s:
            b_strong.setdefault(s, []).append(j)
        b_weak.setdefault(w, []).append(j)
    b_used = [False] * len(items_b)

    def take_best(idxs: list[int], a_item: dict):
        """同键多候选时按内容择优（WS08-09）：弱键一致 > 同单位工程 > 同 section > 金额最接近 > 行序。

        「5 行铝合金门窗」只靠名称特征单位分不清是哪栋楼，旧版在弱键相同时退到行序配对 ——
        审定侧 sheet 顺序一换，6# 楼的送审就对上了 7# 楼的审定。单位工程与 section 在这里做
        优先级而不是硬键：两侧 sheet 名写法稍有不同（「6#楼」/「6#」）时仍能配上，只是排在后面。"""
        cands = [j for j in idxs if not b_used[j]]
        if not cands:
            return None
        if len(cands) > 1:
            aw = _item_keys(a_item)[1]
            a_amt = _f(a_item.get("amount"))
            a_up = _nkey(a_item.get("unit_project"))
            a_sec = _nkey(a_item.get("section"))
            cands = [min(cands, key=lambda k: (
                _item_keys(items_b[k])[1] != aw,
                not a_up or _nkey(items_b[k].get("unit_project")) != a_up,
                not a_sec or _nkey(items_b[k].get("section")) != a_sec,
                abs(_f(items_b[k].get("amount")) - a_amt),
                k))]
        b_used[cands[0]] = True
        return cands[0]

    def _status(a_none, b_none, a_amt, b_amt, only=None):
        if a_none or b_none:
            return "待核实"               # 任一侧合价缺失/未取到,不臆测为 0
        if only:
            return only
        return "一致" if abs(to_cents(a_amt) - to_cents(b_amt)) <= _ROUND_CENTS else "调整"

    rows: list[dict] = []
    for it in items_a:
        s, w = _item_keys(it)
        j = take_best(b_strong.get(s, []), it) if s else None
        matched_by = "编码" if j is not None else ""
        if j is None:
            j = take_best(b_weak.get(w, []), it)
            matched_by = "名称特征" if j is not None else ""
        a_none = it.get("amount") is None
        a_amt = _f(it.get("amount"))
        if j is None:
            st = _status(a_none, False, a_amt, 0.0, only="仅送审")
            rows.append(_row(it, None, a_amt, 0.0, st, "", label_a, label_b))
        else:
            bt = items_b[j]
            b_none = bt.get("amount") is None
            b_amt = _f(bt.get("amount"))
            rows.append(_row(it, bt, a_amt, b_amt, _status(a_none, b_none, a_amt, b_amt), matched_by, label_a, label_b))
    # B 侧未匹配 → 仅审定(审增/新增)
    for j, it in enumerate(items_b):
        if not b_used[j]:
            b_none = it.get("amount") is None
            b_amt = _f(it.get("amount"))
            st = _status(False, b_none, 0.0, b_amt, only="仅审定")
            rows.append(_row(None, it, 0.0, b_amt, st, "", label_a, label_b))

    # 总额按整数分逐行求和,保证 Σ分部 == 总额,不与摘要错位,也不累积浮点尾差
    a_total = sum(to_cents(r["a_amount"]) for r in rows) / 100
    b_total = sum(to_cents(r["b_amount"]) for r in rows) / 100
    adjust = (sum(to_cents(r["a_amount"]) for r in rows) - sum(to_cents(r["b_amount"]) for r in rows)) / 100
    n_same = sum(1 for r in rows if r["status"] == "一致")
    n_chg = sum(1 for r in rows if r["status"] == "调整")
    n_only_a = sum(1 for r in rows if r["status"] == "仅送审")
    n_only_b = sum(1 for r in rows if r["status"] == "仅审定")
    n_uncertain = sum(1 for r in rows if r["status"] == "待核实")

    # 章节维度差异汇总
    ch: dict[str, dict] = {}
    for r in rows:
        c = r["chapter"] or "00"
        d = ch.setdefault(c, {"chapter": c, "chapter_name": r["chapter_name"],
                              "a_amount": 0.0, "b_amount": 0.0, "adjust": 0.0, "count": 0})
        d["a_amount"] += r["a_amount"]; d["b_amount"] += r["b_amount"]
        d["adjust"] += r["adjust"]; d["count"] += 1
    for d in ch.values():
        for k in ("a_amount", "b_amount", "adjust"):
            d[k] = round(d[k], 2)
    chapters = sorted(ch.values(), key=lambda x: -abs(x["adjust"]))

    attributed = [r for r in rows if r["diff_by_qty"] is not None]
    return {
        "rows": rows,
        "chapters": chapters,
        "summary": {
            "label_a": label_a, "label_b": label_b,
            "a_total": a_total, "b_total": b_total,
            "adjust_amount": adjust,
            "adjust_rate": round(adjust / a_total, 4) if a_total else 0.0,
            "count_total": len(rows),
            "count_same": n_same, "count_changed": n_chg,
            "count_only_a": n_only_a, "count_only_b": n_only_b,
            "count_uncertain": n_uncertain,
            "count_a_items": len(items_a), "count_b_items": len(items_b),
            # WS08-19：量差/价差归因（只统计两侧量价额都齐全的匹配行）
            "diff_by_qty": round(sum(r["diff_by_qty"] for r in attributed), 2),
            "diff_by_price": round(sum(r["diff_by_price"] for r in attributed), 2),
            "count_attributed": len(attributed),
            "count_rounding": sum(1 for r in rows if r["rounding_note"]),
            "count_calc_error_a": sum(1 for r in rows if f"{label_a}计算错误" in r["calc_flags"]),
            "count_calc_error_b": sum(1 for r in rows if f"{label_b}计算错误" in r["calc_flags"]),
        },
    }


def _num(x) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _calc_error(it: dict | None) -> bool:
    """行内 |量×价 − 合价| 超过 max(1 元, 0.5%) → 算术错误（WS08-19）。

    只在量、价、额都取到且量与额同一期次组时判：进度款表「合同量 × 单价 ≠ 本期产值」是常态，
    不是算错（与投控 self_check 同一口径）。"""
    if not it:
        return False
    q, p, amt = _num(it.get("qty")), _num(it.get("price")), _num(it.get("amount"))
    if q is None or p is None or amt is None:
        return False
    periods = it.get("periods") or {}
    if periods.get("qty") and periods.get("amount") and periods["qty"] != periods["amount"]:
        return False
    return abs(q * p - amt) > max(_CALC_ABS_TOL, _CALC_REL_TOL * abs(amt))


def _loc(it: dict | None) -> dict:
    if not it:
        return {"file": None, "file_id": None, "sheet": None, "row": None}
    return {"file": it.get("file"), "file_id": it.get("file_id"), "sheet": it.get("sheet"), "row": it.get("row")}


def _row(a, b, a_amt, b_amt, status, matched_by, label_a, label_b) -> dict:
    src = a or b or {}
    # 缺失的量/价保持 None（WS08-01）：旧版 _f() 把「没取到」写成 0.0，界面上看着像「审定量为 0」
    a_qty = _num(a.get("qty")) if a else None
    b_qty = _num(b.get("qty")) if b else None
    a_price = _num(a.get("price")) if a else None
    b_price = _num(b.get("price")) if b else None
    a_c, b_c = to_cents(a_amt), to_cents(b_amt)
    flags = [f for f, it in ((f"{label_a}计算错误", a), (f"{label_b}计算错误", b)) if _calc_error(it)]
    diff_by_qty = diff_by_price = None
    if a and b and None not in (a_qty, b_qty, a_price, b_price):
        # 量差 =（送审量 − 审定量）× 审定价；价差 =（送审价 − 审定价）× 送审量。
        # 两侧都自洽时 量差 + 价差 == 送审额 − 审定额（恒等式，测试钉住）
        diff_by_qty = float((Decimal(repr(a_qty)) - Decimal(repr(b_qty))) * Decimal(repr(b_price)))
        diff_by_price = float((Decimal(repr(a_price)) - Decimal(repr(b_price))) * Decimal(repr(a_qty)))
        diff_by_qty, diff_by_price = round(diff_by_qty, 2), round(diff_by_price, 2)
    return {
        "code": src.get("code", ""), "name": src.get("name", ""),
        "feature": src.get("feature", ""), "unit": src.get("unit", ""),
        "chapter": src.get("chapter", "00"), "chapter_name": src.get("chapter_name", "无编码项"),
        "unit_project": src.get("unit_project"), "section": src.get("section") or "",
        "a_loc": _loc(a), "b_loc": _loc(b),
        "a_qty": a_qty, "b_qty": b_qty, "a_price": a_price, "b_price": b_price,
        "a_amount": a_c / 100, "b_amount": b_c / 100,
        "adjust": (a_c - b_c) / 100,   # 审减(正=核减)
        "status": status, "matched_by": matched_by,
        # WS26-a：这一侧有行、但合价没取到（与 reconcile() 判「待核实」用的 a_none / b_none 同一判据）。
        # a_amount / b_amount 仍按 0 写（只增字段，不改既有口径）；没有这一侧的行（仅送审 / 仅审定）不算缺失
        "a_amount_missing": a is not None and a.get("amount") is None,
        "b_amount_missing": b is not None and b.get("amount") is None,
        "rounding_note": "舍入差 ±0.01" if status == "一致" and abs(a_c - b_c) == 1 else None,
        "calc_flags": flags,
        "diff_by_qty": diff_by_qty, "diff_by_price": diff_by_price,
    }


class ParseFailed(RuntimeError):
    """zt：接线层（zt.costsheet.service.parse_failed）把它转成 status=insufficient，detail() 原样放进 data.detail。

    计价表解析不出任何清单行(格式不支持/损坏/非广联达清单表/口径不存在或有歧义/无价)—— API 层转 422。

    reason_code 是机器码（same_file_same_columns / basis_not_found / column_ambiguous）。WS26-e 起 422 的 detail
    是对象（detail()）：Java TaskOutcomeJudge 取 message 作 summary、reason_code 作 outcome_reason、hint 进告警。"""

    def __init__(self, message: str, *, reason_code: str | None = None, hint: str | None = None,
                 basis_requested: str | None = None, basis_available: list | None = None,
                 files: list | None = None):
        super().__init__(message)
        self.message = message
        self.reason_code = reason_code
        self.hint = hint
        self.basis_requested = basis_requested
        self.basis_available = basis_available
        self.files = files

    def detail(self) -> dict:
        return {"message": self.message, "reason_code": self.reason_code, "hint": self.hint,
                "basis_requested": self.basis_requested, "basis_available": self.basis_available or [],
                "files": self.files or []}


_SIDE_LABEL = {"submitted": "送审", "approved": "审定"}


def _require_items(parsed: dict, role: str, name: str, basis: str = "auto", file_id: str | None = None) -> None:
    """一侧解析不出可比的行 → ParseFailed（铁律 8：不静默返回空 rows / 全 0）。

    WS26-e（07-009）：口径不存在（basis_missing）与多组列分不清（ambiguous）分开说。改前两者都是同一句
    「表头存在多组金额列…请选择对比口径」，括号里又写「表头没有『本期』口径的金额列」—— 一句让人去选口径，
    一句说选的口径不存在。"""
    meta = parsed["meta"]
    label = _SIDE_LABEL[role]
    if not parsed["items"]:
        details = meta.get("sheets_detail", [])
        statuses = {d["status"] for d in details}
        if statuses & {"basis_missing", "ambiguous"} and not statuses & {"used", "unpriced"}:
            info = {"file": f"{label}文件「{name}」", "file_id": file_id,
                    "basis_available": meta.get("basis_available") or []}
            reasons = "；".join(sorted({f"{d['sheet']}：{d['reason']}" for d in details
                                       if d["status"] == "ambiguous"}))[:300]
            rej = basis_rejection(basis, [info] if "basis_missing" in statuses else [],
                                  [info] if "ambiguous" in statuses else [],
                                  lead=f"{label}文件「{name}」解析失败", ambiguous_tail=f"（{reasons}）")
            raise ParseFailed(rej.pop("message"), **rej)
        raise ParseFailed(f"{label}文件「{name}」解析失败：{'; '.join(parsed['warnings']) or '未知原因'}")
    if meta.get("unpriced"):
        # WS08-04：任一侧无价就没法对账 —— 两侧金额都会是空，结果「全部待核实」毫无意义
        raise ParseFailed(f"{label}文件「{name}」解析失败：清单无单价/金额（疑似招标工程量清单），无法对账")


def _amounts_identical_suspect(result: dict, a_meta: dict, b_meta: dict) -> dict | None:
    """护栏（WS08-01）：匹配行 ≥95% 两侧金额逐分相同，且任一侧表头有 ≥2 组金额列 →
    多半是两侧取成了同一口径（例如进度款两份都取了合同合价 → 假「全部一致」）。"""
    matched = [r for r in result["rows"] if r["status"] in ("一致", "调整")]
    if not matched:
        return None
    same = sum(1 for r in matched if round(r["a_amount"] * 100) == round(r["b_amount"] * 100))
    multi = any(d.get("amount_columns", 0) >= 2
                for m in (a_meta, b_meta) for d in m.get("sheets_detail", []) if d.get("status") == "used")
    if multi and same / len(matched) >= 0.95:
        return warn("amounts_identical_suspect",
                    f"匹配上的 {len(matched)} 行里有 {same} 行两侧金额逐分相同，而表头有多组金额列："
                    f"两侧可能取成了同一口径（送审 {a_meta.get('basis_used')} / 审定 {b_meta.get('basis_used')}），"
                    "请确认对比口径")
    return None


_SHOW_SHEETS = 10      # 告警里最多写出几个表名，其余写「等 N 张」


def _cols(idx: list) -> str:
    """列下标 → 用户在 Excel 里看到的列号：[7] →「H 列」，[4, 6] →「E、G 列」。"""
    return "、".join(get_column_letter(i + 1) for i in idx) + " 列"


def _names(sheets: list) -> str:
    shown = "、".join(f"「{s['sheet']}」" for s in sheets[:_SHOW_SHEETS])
    return shown + (f"等 {len(sheets)} 张" if len(sheets) > _SHOW_SHEETS else "")


def _same_file_sheets(a_meta: dict, b_meta: dict) -> tuple[list[dict], list[dict]]:
    """同一份文件放两侧时，逐表看两侧各取了哪一列金额 → (同列的表, 分列的表)。

    只看两侧都计入（status=used）且都取到了金额的表：按标题跳过的费用表、歧义表、无价表都不算。
    比的是列下标 amount_col_idx，不是 columns 里的表头文本（铁律 3：不靠文本相似判断）——
    下标在一张表里唯一，表头文本不保证；金额由 量×价 补出的表两侧「金额列文本」同为空，取数列却可能不同。"""
    b_by = {d["sheet"]: d for d in b_meta.get("sheets_detail", [])}
    same: list[dict] = []
    split: list[dict] = []
    for da in a_meta.get("sheets_detail", []):
        db = b_by.get(da["sheet"])
        if db is None or da.get("status") != "used" or db.get("status") != "used":
            continue
        ia, ib = da.get("amount_col_idx") or [], db.get("amount_col_idx") or []
        if not ia or not ib:
            continue
        (same if ia == ib else split).append({
            "sheet": da["sheet"], "a_cols": ia, "b_cols": ib,
            "a_label": da.get("basis_label"), "b_label": db.get("basis_label")})
    return same, split


def _two_sides_message(split: list[dict]) -> str:
    """写明两侧各取了哪一列；几十张同版式的表合成一句（按「送审列 / 审定列」分组计数）。"""
    groups: dict[tuple, int] = {}
    for s in split:
        k = (_cols(s["a_cols"]), s["a_label"] or "", _cols(s["b_cols"]), s["b_label"] or "")
        groups[k] = groups.get(k, 0) + 1
    parts = [f"{n} 张表送审取 {ac}{f'（{al}）' if al else ''}、审定取 {bc}{f'（{bl}）' if bl else ''}"
             for (ac, al, bc, bl), n in sorted(groups.items(), key=lambda kv: -kv[1])[:3]]
    more = f"；另有 {len(groups) - 3} 种列组合" if len(groups) > 3 else ""
    return "送审与审定是同一份文件，已按表头里的两组金额列分别取数：" + "；".join(parts) + more


def _all_rows_identical(result: dict) -> dict | None:
    """两份不同的文件、每一行都配上且两侧金额逐分相同 → 提示（可能是合法的「审定无核减」，不拦）。

    有「仅送审 / 仅审定 / 待核实 / 调整」行就不是全部一致：那时核减额不为 0 或有行没比上，
    用户看得到差异，再提示「请确认审定文件选对了」是噪声。"""
    rows = result["rows"]
    if not rows or any(r["status"] != "一致" or round(r["a_amount"] * 100) != round(r["b_amount"] * 100)
                       for r in rows):
        return None
    return warn("all_rows_identical",
                f"{len(rows)} 行全部一致，核减额 0。如果这不是你预期的结果，请确认审定文件选对了")


def run(submitted_raw: bytes, submitted_name: str, approved_raw: bytes, approved_name: str,
        basis: str = "auto", *, submitted_file_id: str | None = None,
        approved_file_id: str | None = None) -> dict:
    """接线层:两份计价 Excel(bytes) → 契约形状的对账结果。

    调用方明确给出角色（WS08-01）：送审侧 side=submit、审定侧 side=audit —— 旧版两侧调同一个
    解析器、不带侧别，门窗三段表的审定侧取成了「原合同」块，审定单放在审定侧取到的是报审金额。
    basis 是两侧共用的期次口径（auto：有本期列比本期，否则比合价；D45）。
    解析不出清单行 / 口径歧义 / 任一侧无价时抛 ParseFailed —— API 层转 422。

    两侧是同一份文件（原始字节 sha256 相同：同一个文件选了两次，或内容相同的两份副本）时逐表看
    两侧取到的金额列（WS26-b / D-R78）：审核对比表在同一张表里有送审、审定两组列，两侧选同一份
    是正确用法；单列合价表两侧取到的是同一列，比出来必然「全部一致、核减 0」—— 铁律 8，不给这种
    200。全部同列 → ParseFailed；部分同列 → 那些表两侧都剔除并出 error 告警。
    """
    a = parse_costsheet(submitted_raw, submitted_name, side="submit", basis=basis,
                        file_id=submitted_file_id)
    b = parse_costsheet(approved_raw, approved_name, side="audit", basis=basis,
                        file_id=approved_file_id)
    warnings = list(a["warnings"]) + list(b["warnings"])
    _require_items(a, "submitted", submitted_name, basis, submitted_file_id)
    _require_items(b, "approved", approved_name, basis, approved_file_id)
    warning_items = list(a["warning_items"]) + list(b["warning_items"])

    a_items, b_items = a["items"], b["items"]
    same_file = hashlib.sha256(submitted_raw).digest() == hashlib.sha256(approved_raw).digest()
    if same_file:
        same, split = _same_file_sheets(a["meta"], b["meta"])
        if same and not split:
            # 「按当前对比口径」：表头可能有按月份分组的上报 / 审核列（30003 进度款），只是本次口径取不到
            raise ParseFailed(
                "送审与审定是同一份文件（或内容完全相同），而且按当前对比口径表头没有分送审、审定两组金额列，"
                f"两侧取到的是同一列（共 {len(same)} 张表，如「{same[0]['sheet']}」两侧都取 "
                f"{_cols(same[0]['a_cols'])}）。请分别选择送审文件和审定文件。",
                reason_code="same_file_same_columns")
        if same:
            drop = {s["sheet"] for s in same}
            a_items = [it for it in a_items if it["sheet"] not in drop]
            b_items = [it for it in b_items if it["sheet"] not in drop]
            w = warn("same_file_sheets_excluded",
                     f"送审与审定是同一份文件，其中 {len(same)} 张表没有分送审、审定两组金额列，两侧取到的是同一列，"
                     f"未参与对账：{_names(same)}")
            warning_items.append(w)
            warnings.append(w["message"])
        if split:
            # info 级只进结构化告警：旧的字符串通道只放 warn / error（同 costsheet._legacy 的口径）
            warning_items.append(warn("same_file_two_sides", _two_sides_message(split)))

    result = reconcile(a_items, b_items, label_a="送审", label_b="审定")
    guard = _amounts_identical_suspect(result, a["meta"], b["meta"])
    # 表头有多组金额列时 amounts_identical_suspect（error）已经说了同一件事，不再叠一条
    guard = guard or (None if same_file else _all_rows_identical(result))
    if guard:
        warning_items.append(guard)
        warnings.append(guard["message"])
    n_a, n_b = result["summary"]["count_calc_error_a"], result["summary"]["count_calc_error_b"]
    if n_a or n_b:
        w = warn("calc_error_rows", f"送审侧 {n_a} 行、审定侧 {n_b} 行 量×价 与合价不符（超过 max(1 元, 0.5%)），"
                                    "已在行上标记「送审计算错误 / 审定计算错误」")
        warning_items.append(w)
        warnings.append(w["message"])
    summary = dict(result["summary"])
    summary["basis"] = basis
    summary["basis_used"] = {"submitted": a["meta"].get("basis_used"), "approved": b["meta"].get("basis_used")}
    summary["basis_label"] = {"submitted": a["meta"].get("basis_label"), "approved": b["meta"].get("basis_label")}
    # WS26-e：汇总卡「范围」一行（两侧各自的技术措施表读没读进来）
    summary["scope_label"] = {"submitted": scope_label([a["meta"]["coverage"]]),
                              "approved": scope_label([b["meta"]["coverage"]])}
    levels = {"submitted": a["meta"]["coverage"]["level"], "approved": b["meta"]["coverage"]["level"]}
    summary["coverage_level"] = levels
    # D42 / WS08-02：覆盖率 poor 照常出结果，但标明不可作为结论（前端据此显示红条）
    summary["coverage_ok"] = "poor" not in levels.values()

    rows = [
        {
            "item_code": r["code"] or None,
            "item_name": r["name"],
            "feature": r["feature"] or None,
            "unit": r["unit"] or None,
            "chapter": r["chapter"],
            "chapter_name": r["chapter_name"],
            "submitted_qty": r["a_qty"],
            "approved_qty": r["b_qty"],
            "submitted_price": r["a_price"],
            "approved_price": r["b_price"],
            "submitted_amount": r["a_amount"],
            "approved_amount": r["b_amount"],
            "diff": r["adjust"],
            # WS26-a：金额 0.0 与「没取到」分得开（前端缺失的一侧显示「—」）
            "a_amount_missing": r["a_amount_missing"],
            "b_amount_missing": r["b_amount_missing"],
            "status": r["status"],
            "matched_by": r["matched_by"] or None,
            # WS08-09：两侧各自回到原表的定位，外加单位工程与 section（前端「送审位置 / 审定位置」列）
            "unit_project": r["unit_project"],
            "section": r["section"] or None,
            "submitted_file": r["a_loc"]["file"], "submitted_file_id": r["a_loc"]["file_id"],
            "submitted_sheet": r["a_loc"]["sheet"], "submitted_row": r["a_loc"]["row"],
            "approved_file": r["b_loc"]["file"], "approved_file_id": r["b_loc"]["file_id"],
            "approved_sheet": r["b_loc"]["sheet"], "approved_row": r["b_loc"]["row"],
            # WS08-19
            "rounding_note": r["rounding_note"],
            "calc_flags": r["calc_flags"],
            "diff_by_qty": r["diff_by_qty"],
            "diff_by_price": r["diff_by_price"],
        }
        for r in result["rows"]
    ]
    return {
        "rows": rows,
        "total_diff": result["summary"]["adjust_amount"],
        "chapters": result["chapters"],
        "summary": summary,
        "warnings": warnings,
        "warning_items": warning_items,
        "file_coverage": [a["meta"]["coverage"], b["meta"]["coverage"]],
        "parsed": {"submitted": a["meta"], "approved": b["meta"]},
    }
