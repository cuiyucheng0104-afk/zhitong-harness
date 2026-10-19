# 来源：engine-service/app/engine/estimate_quality.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""概算产出的完成度判定、逐格来源与计费依据（WS10-P06，issue #761）。

改前覆盖率 10.67%、总建筑面积为 0 的表与完整概算外观相同：交付 xlsx 不带来源、完成度、告警、
计费依据，结果页也不展示 input_coverage。本模块只放**纯函数**（不读库、不调 LLM，铁律 4），
由 compute 端点组装、由渲染器写进「生成说明」页与 5 表 I 列：

  · judge_quality        → {review_level: ok | needs_review | draft, reasons: [{code, message}]}
                           字段名按统一约定 C1：非任务状态不占用 status / outcome，叫 review_level；
                           **不新增任务状态**（铁律 5）—— 草稿照样 done，由文件名前缀与生成说明说出来。
  · clean_input_sources  → 校验前端申报的逐格来源（类型 / 取值 / 长度），非法抛 ValueError（端点转 422）
  · fee_basis_texts      → 5 表 I 列「费用计算标准」：文号、算式、签署类型
  · stale_fee_warnings   → 采纳的费率值与本次重算相差 > 0.5% → fee_value_stale

阈值（D50）在模板策略 `review_thresholds` 里，代码不写死数字。
"""
from __future__ import annotations

from typing import Any

# WS29-n：与 Java EstimateComputeContextValidator.SOURCE_KINDS、前端 estimateModel.INPUT_SOURCE_CN
# 三份必须一致（前端闸里有三方核对）。baseline_prefill / slot_empty 不参与需复核计数：
# 前者是 ≥3 个样本来源的基准值（D47 允许预填），后者是「本项目没有这个单体」的显式 0。
SOURCE_KINDS = ("user", "extract", "excel", "baseline_reference", "fee_rules",
                "baseline_prefill", "slot_empty", "derived")
SOURCE_KIND_CN = {
    "user": "用户手填",
    "extract": "AI 抽取（用户确认）",
    "excel": "Excel 导入",
    "baseline_reference": "单样本参考值（用户采纳）",
    "fee_rules": "费率规则建议（用户采纳）",
    "baseline_prefill": "多样本基准值（系统预填）",
    "slot_empty": "单体归位：该槽位无单体",
    # WS29-d（D-R118）：占地按 用地面积 × 建筑密度 推算，用户点「填入推算值」写入；记需复核（footprint_derived）
    "derived": "按建筑密度推算（用户点选）",
}

REVIEW_OK = "ok"
REVIEW_NEEDS = "needs_review"
REVIEW_DRAFT = "draft"
# WS25-b：报表管理的空白模板（没有输入位、不判质量、不给合计）。judge_quality 不会给出它
REVIEW_BLANK = "blank"
REVIEW_LEVEL_CN = {REVIEW_OK: "完整", REVIEW_NEEDS: "需复核", REVIEW_DRAFT: "草稿", REVIEW_BLANK: "空白模板"}

_MAX_SOURCES = 400
_MAX_TEXT = 200
_MAX_REFS = 10

# 这些告警一出现，本表就要人再看一眼（D50「需复核」口径）；值是理由的中文说明
_NEEDS_REVIEW_WARNINGS = {
    "area_mismatch_acknowledged": "单体槽位合计与原文总建筑面积的差额已由用户确认",
    "footprint_missing": "建筑占地面积缺失，室外面积按整块用地计",
    "land_cost_unfilled": "建设用地费未填，按 0 计入合计",
    "fee_value_stale": "采纳的费率建议值与本次按同一基数重算的结果不一致",
}


def _thresholds(policy: dict) -> dict:
    t = (policy or {}).get("review_thresholds") or {}
    band = t.get("reference_ratio_band") or (0.7, 1.3)
    return {
        "draft_coverage_below": float(t.get("draft_coverage_below", 0.30)),
        "draft_if_sheet_unfilled": list(t.get("draft_if_sheet_unfilled") or []),
        "fee_stale_tolerance": float(t.get("fee_stale_tolerance", 0.005)),
        # WS29-q / D-R179（U19）：概算 ÷ 参照造价落在这个区间外记需复核，不拦
        "reference_ratio_band": (float(band[0]), float(band[1])),
    }


def fee_stale_tolerance(policy: dict) -> float:
    return _thresholds(policy)["fee_stale_tolerance"]


# ------------------------------------------------------------------ 逐格来源

def clean_input_sources(raw: Any) -> dict[str, dict] | None:
    """前端申报的 {格: {source, refs?, file_id?, quote?, semantic_key?}} → 规整后的副本。

    None = 调用方没申报（老调用方 / 直接打 API）—— 不是错误，但判定时记「未申报来源」。
    非法（类型不对、source 不认识、超长）→ ValueError，端点转 422：来源是写进交付表的审计信息，
    不能静默吞掉一个写错的来源。
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("input_sources 必须是对象 {格: {source, ...}}")
    if len(raw) > _MAX_SOURCES:
        raise ValueError(f"input_sources 最多 {_MAX_SOURCES} 项")
    out: dict[str, dict] = {}
    for k, v in raw.items():
        cell = str(k).replace("$", "")
        if "!" not in cell or len(cell) > 64:
            raise ValueError(f"input_sources 的键须是「表名!格号」，实为 {k!r}")
        if not isinstance(v, dict):
            raise ValueError(f"input_sources.{cell} 必须是对象 {{source, ...}}")
        src = v.get("source")
        if src not in SOURCE_KINDS:
            raise ValueError(f"input_sources.{cell}.source 只接受 {list(SOURCE_KINDS)}，实为 {src!r}")
        item: dict[str, Any] = {"source": src}
        for key in ("file_id", "quote", "semantic_key", "file_name"):
            val = v.get(key)
            if val is None:
                continue
            if not isinstance(val, str):
                raise ValueError(f"input_sources.{cell}.{key} 必须是字符串")
            item[key] = val.strip()[:_MAX_TEXT]
        refs = v.get("refs")
        if refs is not None:
            if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
                raise ValueError(f"input_sources.{cell}.refs 必须是字符串数组")
            item["refs"] = [r[:_MAX_TEXT] for r in refs[:_MAX_REFS]]
        out[cell] = item
    return out


# ------------------------------------------------------------------ 计费依据（5 表 I 列）

_SIGNOFF_CN = {"cost_engineer": "造价员已签署", "owner_release": "仓主默认放行（非造价员签署）"}
# fee_rules 的 unavailable_reason → 交付表上给人看的话（码仍附在括号里，便于回查）
_UNAVAILABLE_CN = {
    "no_base": "未提供计费基数",
    "non_positive_base": "计费基数非正数",
    "rule_not_applicable": "规则不适用（如基数超出原表范围、属性组合原表无对应值）",
    "applicability_unconfirmed": "适用条件（项目所在地 / 项目性质）未确认",
    "manual_paradigm": "原表无数值费率，须人工填报",
    "band_closure_unconfirmed": "档界闭开性未经造价员对图确认",
    "ruleset_unsigned": "费率规则集未签署",
}


def fee_basis_texts(fee_items: list[dict] | None, derived_keys: list[str] | None = None,
                    max_chars: int = 300) -> dict[int, str]:
    """→ {5 表行号: 依据文本}。只写依据，不写金额以外的推断；没出建议值的也写清为什么。"""
    from zt.estimate import fee_rules  # noqa: PLC0415 —— 与端点同源，避免模块级循环依赖

    derived = set(derived_keys or [])
    out: dict[int, str] = {}
    for it in fee_items or []:
        row = (fee_rules._index(it.get("ruleset") or fee_rules.DEFAULT_RULESET).get(it.get("item_id"))
               or {}).get("fee_row")
        if not row:
            continue
        basis = it.get("basis") or {}
        parts: list[str] = []
        ref = basis.get("source_ref") or basis.get("source_table")
        if ref:
            parts.append(f"依据：{ref}")
        key = basis.get("base_key")
        if key and basis.get("base_value") is not None:
            # '.12g' 不用 ':g'：后者只留 6 位有效数字，310071.49 会写成 310071（P09 修过同一个坑）
            parts.append(f"基数「{key}」{format(float(basis['base_value']), '.12g')} "
                         f"{basis.get('base_unit') or ''}".rstrip()
                         + ("（取自本表工程费用合计）" if key in derived else ""))
        steps = [s for s in (basis.get("steps") or []) if "未自动应用" not in s]
        if it.get("suggested") is not None and steps:
            parts.append("算式：" + "；".join(steps))
        elif it.get("unavailable_reason"):
            why = it["unavailable_reason"]
            parts.append(f"本次未出建议值：{_UNAVAILABLE_CN.get(why, why)}（{why}）")
        kind = it.get("signoff_kind") or basis.get("signoff_kind")
        parts.append("签署：" + _SIGNOFF_CN.get(kind, "未签署"))
        text = "；".join(parts)
        out[int(row)] = text if len(text) <= max_chars else text[: max_chars - 1] + "…"
    return out


def _n(v) -> str:
    return format(float(v), ".12g")


def stale_fee_warnings(fee_items: list[dict] | None, inputs: dict | None,
                       input_sources: dict | None, tolerance: float) -> list[dict]:
    """采纳自费率规则的格：采纳值与本次重算相差 > tolerance → fee_value_stale（只提示，不改值）。"""
    if not input_sources:
        return []
    by_cell = {it["target_cell"]: it for it in fee_items or [] if it.get("target_cell")}
    vals = {str(k).replace("$", ""): v for k, v in (inputs or {}).items()}
    out: list[dict] = []
    for cell, src in input_sources.items():
        if src.get("source") != "fee_rules" or cell not in by_cell:
            continue
        adopted = vals.get(cell)
        if isinstance(adopted, bool) or not isinstance(adopted, (int, float)):
            continue
        it = by_cell[cell]
        now = it.get("suggested")
        if now is None:
            out.append({"code": "fee_value_stale", "cell": cell,
                        "message": (f"{it.get('fee_name')}：采纳值 {_n(adopted)} 万元来自费率建议，但按本次基数"
                                    f"重算已不出建议值（{it.get('unavailable_reason') or '条件不满足'}），"
                                    "请核对该值是否仍然成立。")})
            continue
        if now == 0:
            continue
        dev = (float(adopted) - float(now)) / float(now)
        if abs(dev) > tolerance:
            out.append({"code": "fee_value_stale", "cell": cell,
                        "message": (f"{it.get('fee_name')}：采纳值 {_n(adopted)} 万元与按本次基数重算的 {_n(now)} 万元"
                                    f"相差 {dev:+.2%}（阈值 ±{tolerance:.1%}）—— 采纳后基数变了（如成本位又改过），"
                                    "请回第 3 步重新推算或确认。")})
    return out


# ------------------------------------------------------------------ 参照造价（WS29-q / D-R179）

def _wan(v: float) -> str:
    return f"{float(v):,.2f}"


def reference_comparison(reference: dict | None, static_total: Any, policy: dict) -> dict | None:
    """用户在第 5 步填的参照造价（如招标控制价，万元）→ 与「建设静态总投资」的比值。

    只算一个比值，**不进任何公式**：参照造价填与不填，totals 逐项相同（铁律 2 的同一条纪律——
    金额只来自用户确认过的 inputs）。比值落在 reference_ratio_band 外 → deviates=True，
    judge_quality 据此记需复核（U19：不拦）。没填参照 → None（不出这一项，也不报错）。
    """
    if not isinstance(reference, dict):
        return None
    amount = reference.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        return None
    note = (reference.get("note") or "").strip() if isinstance(reference.get("note"), str) else ""
    ref_text = f"参照造价 {_wan(amount)} 万元" + (f"（{note}）" if note else "")
    out: dict[str, Any] = {"amount": float(amount), "note": note or None,
                           "static_total": None, "ratio": None, "deviates": False}
    if isinstance(static_total, bool) or not isinstance(static_total, (int, float)):
        out["message"] = f"{ref_text}；本次没有算出建设静态总投资，无法对比"
        return out
    ratio = float(static_total) / float(amount)
    lo, hi = _thresholds(policy)["reference_ratio_band"]
    out.update(static_total=float(static_total), ratio=round(ratio, 4), deviates=ratio > hi or ratio < lo)
    out["message"] = f"建设静态总投资 {_wan(static_total)} 万元，是{ref_text}的 {ratio:.2f} 倍"
    return out


# ------------------------------------------------------------------ 完成度判定

def judge_quality(*, coverage: dict, warnings: list[dict], input_sources: dict | None,
                  supplied: set[str], fee_signoff_kind: str | None, policy: dict,
                  declarable_cells: set[str] | None = None, reference: dict | None = None) -> dict:
    """D50 口径 → {review_level, reasons:[{code, message}]}（填了参照造价时另带 reference_comparison）。

    草稿：成本位覆盖率 < 30%，或「1.建筑工程费」「2.安装工程费」任一表一格都没填；
    需复核：采纳过参考值 / 仓主放行的费率、面积差额已确认、占地缺失、土地费未填、未申报来源、
            费率采纳值过期、占地按建筑密度推算（WS29-d）、其余费用表整表没填（WS29-q / U18：点名，不降草稿）、
            概算偏离参照造价超过区间（WS29-q / U19）。草稿优先；理由全部列出（草稿的表往往也有需复核的理由）。
    reference：reference_comparison() 的产物；None = 没填参照造价。
    """
    th = _thresholds(policy)
    draft: list[dict] = []
    review: list[dict] = []

    rate = coverage.get("rate")
    if isinstance(rate, (int, float)) and rate < th["draft_coverage_below"]:
        draft.append({"code": "coverage_below_draft",
                      "message": (f"成本位只填了 {coverage.get('filled')}/{coverage.get('cost_inputs')}"
                                  f"（{rate:.1%}），低于 {th['draft_coverage_below']:.0%}")})
    by_sheet = coverage.get("by_sheet") or {}
    for sheet in th["draft_if_sheet_unfilled"]:
        st = by_sheet.get(sheet)
        if st is not None and not st.get("filled"):
            draft.append({"code": "sheet_unfilled",
                          "message": f"「{sheet}」一格都没填，该表合计按 0 计入"})

    # WS29-q（E39）：不在草稿判据里的费用表（专项 / 室外 / 其他费）整表没填，改前不产生任何理由，
    # 横幅于是写「出数完整」。U18：仍是需复核，点名哪张表、按 0 计入；不降成草稿
    empty = [(name, st.get("cost_inputs") or 0) for name, st in by_sheet.items()
             if name not in th["draft_if_sheet_unfilled"] and st.get("cost_inputs") and not st.get("filled")]
    if empty:
        review.append({"code": "sheet_unfilled_review",
                       "message": "、".join(f"「{name}」0/{n}" for name, n in empty)
                                  + " 一格都没填，按 0 计入合计；本项目确实没有这类费用可以不填，否则请回第 3 步补"})

    if reference is not None and reference.get("deviates"):
        review.append({"code": "reference_cost_deviation",
                       "message": (f"{reference['message']}，超出 {th['reference_ratio_band'][0]:g}～"
                                   f"{th['reference_ratio_band'][1]:g} 倍；请核对单价口径与规模（只提示，不拦）")})

    sources = input_sources or {}
    adopted_ref = sorted(c for c, s in sources.items() if s.get("source") == "baseline_reference")
    if adopted_ref:
        review.append({"code": "reference_values_adopted",
                       "message": f"采纳了 {len(adopted_ref)} 条单样本参考值（样本来源不足，D47）"})
    derived = sorted(c for c, s in sources.items() if s.get("source") == "derived")
    if derived:
        # WS29-d：推算值不是原文数值，填了就至少「需复核」（铁律 2：代码算的数也要人看过才算数）
        review.append({"code": "footprint_derived",
                       "message": (f"{'、'.join(c.split('!')[-1] for c in derived)} 的建筑占地面积按 用地面积 × 建筑密度"
                                   " 推算，不是原文数值")})
    adopted_fee = sorted(c for c, s in sources.items() if s.get("source") == "fee_rules")
    if adopted_fee and fee_signoff_kind != "cost_engineer":
        review.append({"code": "owner_released_fee_adopted",
                       "message": (f"采纳了 {len(adopted_fee)} 条费率建议值，费率规则集为仓主默认放行、"
                                   "未经造价员逐值签署")})
    seen: set[str] = set()
    for w in warnings or []:
        code = w.get("code")
        if code in _NEEDS_REVIEW_WARNINGS and code not in seen:
            seen.add(code)
            review.append({"code": code, "message": _NEEDS_REVIEW_WARNINGS[code]})

    declarable = set(declarable_cells) if declarable_cells is not None else set(supplied)
    undeclared = sorted(c for c in supplied if c in declarable and c not in sources)
    if input_sources is None:
        review.append({"code": "input_sources_undeclared",
                       "message": "调用方未申报任何输入位的来源（input_sources），交付表无法说明每个数从哪来"})
    elif undeclared:
        review.append({"code": "input_sources_undeclared",
                       "message": f"{len(undeclared)} 个已填输入位未申报来源（如 {'、'.join(undeclared[:3])}）"})

    level = REVIEW_DRAFT if draft else (REVIEW_NEEDS if review else REVIEW_OK)
    out: dict[str, Any] = {"review_level": level, "reasons": draft + review}
    if reference is not None:
        # 放进 quality：Java 把 quality 整个透传进 engine_task.result，结果页不偏离时也要写这句比值
        out["reference_comparison"] = reference
    return out
