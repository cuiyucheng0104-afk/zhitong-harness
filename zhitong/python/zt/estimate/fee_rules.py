# 来源：engine-service/app/engine/fee_rules.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""工程建设其他费用 · 费率建议求值器（阶段 I 条目 I-2.5，契约 §1.4）。

产物是**建议值**不是硬公式：原概算表「5.工程建设其他费用」的 C 列全部是造价员看图
凭经验拍的定值，图中的费率表从不进公式。本模块把 16 张扫描图转录出来的规则做成可复算、
可审计的建议，供造价员覆盖，因此每条结果 `editable` 恒为 True。

四条硬约束（与项目铁律一致）：
  1. **纯确定性 Python，零 LLM** —— LLM 不碰金额。
  2. **无状态** —— 不连 MySQL；规则读入仓 JSON（`data/fee_rules_zj2018.json`）。
  3. **签字位不许藏** —— 签署状态同时出现在每条 FeeSuggestion 的顶层
     `signoff_status`/`signoff_kind`、`basis` 的同名两键，以及 `suggest_all` 的
     规则集级 warning 里。多处都写是故意的：`suggest_one` 只回一条结果、拿不到
     warnings 列表，靠 basis 也必须能看见签的是谁。
     当前值：`signoff_status="signed"` + `signoff_kind="owner_release"` ——
     **仓主 2026-09-10 默认放行，不是造价员签署**（issue #159）。建议值因此会出，
     但每次求值都带一条 `fee_rules_owner_released` 告警说明代价。详见下方「签署闸」段。
  4. **不擅自平分** —— 落在公式格上的两项只出小计参考值 + 子项清单，由人拆。

落点冲突（契约实测）：`C6`/`C9` 是公式格不是输入位（`C6=SUM(C7:C8)`、`C9=SUM(C10:C13)`），
故 `project_management_fee` / `management_other_fee` 的 `write_target="aggregate"`、
`target_cell=None`、附 `aggregate_children`。`engineering_insurance_fee` 原表无任何数值费率
→ `write_target="manual"`、`suggested=None`。其余 13 项 `write_target="input"`。

契约 §1.4 之外**额外添加**的 FeeSuggestion 键（均为附加，不改动已锁定的键）：
`aggregate_children`（契约正文点名要求）、`signoff_status`、`ruleset`、`unavailable_reason`、
`warnings`（该条自身的告警，让 `suggest_one` 不丢信息）。

能力边界（如实标注，不粉饰）：
  · `勘察设计费` 未声明 `band_closure`（已登记在 tests/test_fee_rules_data.py 的
    CLOSURE_KNOWN_GAPS）。本模块**不静默选一边**：按默认闭开性算一遍、按另一侧再算一遍，
    把两者是否给出不同金额如实写进 `fee_band_closure_unconfirmed` 告警。
    2026-09-10 起更进一步：**公开入口对这一条单独扣留金额**
    （`unavailable_reason="band_closure_unconfirmed"`），即使规则集已放行 ——
    档界归属未知就是规则未知，放行等于在档界上编一个金额（铁律 3）。
  · `勘察设计费` 的规则只覆盖「工程设计费」；「工程勘察费」原表写的是「详见文件」，
    无数值规则 → 出 `fee_partial_coverage` 告警，建议值不含勘察费。
  · `节能评估费` 的范式归类（累进 vs 分档单价×规模）数据里就标了争议 → `fee_paradigm_disputed`。
  · 任何影响金额的属性回落到默认值都会出 `fee_attr_defaulted` 告警，不静默默认。
  · 调整系数（复杂系数、全过程造价咨询系数等）**一律不自动应用**，只在
    `basis.available_adjustments` 里列出——是否适用取决于项目属性，须造价员判断。
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data"
_SUFFIX = ".json"

DEFAULT_RULESET = "fee_rules_zj2018"
SHEET = "5.工程建设其他费用"

# 闭开性
CLOSURE_LOWER_EXCLUSIVE = "lower_exclusive_upper_inclusive"
CLOSURE_LOWER_INCLUSIVE = "lower_inclusive_upper_exclusive"
# 未声明闭开性时的默认假设：与同类已声明条目（可行性研究费/环境影响评价费）一致。
# 这是**假设不是结论**，落到该条目上一定伴随 fee_band_closure_unconfirmed 告警。
DEFAULT_CLOSURE = CLOSURE_LOWER_EXCLUSIVE

# 落在公式格上的两项 → 小计参考值 + 子项清单（契约 §1.4 点名）。
# C6=SUM(C7:C8)、C9=SUM(C10:C13)，引擎不得擅自把小计平分到子项。
AGGREGATE_CHILD_ROWS: dict[str, tuple[int, ...]] = {
    "project_management_fee": (7, 8),
    "management_other_fee": (10, 11, 12, 13),
}

# item_id → 该项在 `bases` 里可接受的基数键（按优先级）。
# `bases[item_id]` 永远是第一优先（最精确、无歧义）；数据里的 `base.name` 全名永远兜底。
# 不做任何模糊匹配，也不拿「工程费用」冒充「中标金额」「建安工程造价」这类不同口径的基数。
BASE_KEYS: dict[str, tuple[str, ...]] = {
    "project_management_fee": ("工程费用",),
    "management_other_fee": ("工程费用",),
    "bidding_agency_fee": ("中标金额",),
    "cost_consulting_fee": ("建安工程造价", "收费基数"),
    "supervision_fee": ("工程费用",),
    "feasibility_study_fee": ("工程费用",),
    "survey_design_fee": ("工程费用", "概算投资额"),
    "eia_fee": ("工程费用",),
    "energy_assessment_fee": ("总建筑面积",),
    "site_preparation_fee": ("工程费用",),
    "engineering_insurance_fee": (),
    "municipal_infrastructure_fee": ("建筑面积",),
    "high_reliability_power_fee": ("受电容量",),
    "joint_commissioning_fee": ("工程费用",),
    "patent_technology_fee": ("专利计费基数",),
    "production_preparation_fee": ("工程费用",),
}

# 多列费率表：item_id → 选列用的 attr 名（未给则用数据里的 default_column，并出告警）
COLUMN_ATTR: dict[str, str] = {
    "bidding_agency_fee": "bidding_type",
    "cost_consulting_fee": "consulting_service",
    "feasibility_study_fee": "study_stage",
    "eia_fee": "eia_doc_type",
    "energy_assessment_fee": "building_category",
}

# 市政基础设施配套费的建筑用途（住宅 150 / 非住宅 220，差 47%，绝不静默默认）
_MUNICIPAL_USE_ATTR = "building_use"
_MUNICIPAL_USE_DEFAULT = "residential"
# 该 attr 的中文名只在代码里（数据的 prices 字典没有 label 层）。抽成常量是为了
# `_select_key` 的提示文案与 `required_attrs` 下发的 label 是同一个字面量 ——
# 两处各写一份「建筑用途」，改一处漏一处就会让界面下拉与告警文案对不上。
_MUNICIPAL_USE_LABEL = "建筑用途"

_RATE_DIVISOR = {"percent": 100.0, "permille": 1000.0}
_RATE_SYMBOL = {"percent": "%", "permille": "‰"}


class FeeRuleError(ValueError):
    """规则集不存在 / 规则结构不可求值。调用方必须处理，不许静默吞掉。"""


# ------------------------------------------------------------------ 装载
@functools.lru_cache(maxsize=4)
def _load(ruleset: str = DEFAULT_RULESET) -> dict:
    path = _DATA_DIR / f"{ruleset}{_SUFFIX}"
    if not path.is_file():
        raise FeeRuleError(f"未知费率规则集 {ruleset!r}；可用：{available_rulesets()}")
    return json.loads(path.read_text(encoding="utf-8"))


def available_rulesets() -> list[str]:
    return sorted(p.stem for p in _DATA_DIR.glob(f"fee_rules_*{_SUFFIX}"))


@functools.lru_cache(maxsize=4)
def _index(ruleset: str = DEFAULT_RULESET) -> dict:
    return {i["item_id"]: i for i in _load(ruleset)["items"]}


def list_items(ruleset: str = DEFAULT_RULESET) -> list[dict]:
    """规则集里的 16 条条目（原样，只读，勿改）。"""
    return list(_load(ruleset)["items"])


def covered_cells(ruleset: str = DEFAULT_RULESET) -> set[str]:
    """本规则集能出输入位建议的单元格集合。

    调用方（`estimate_suggest`）拿「其他费」全部输入位减去本集合，得到「费率规则
    管不到的格」。⚠ 那**还不是** `no_rule`：`no_rule` 要求**两个来源都落空** ——
    指标基准库三级严格查表未命中（`base is None`）**且**本格不在本集合里。

    所以「契约点名的 C15/C24-C27 落 no_rule」这个说法是有前提的：只在基准库对这几格
    也没有行时才成立。**现行种子下不成立** —— 实测 224 行真种子跑 suggest()，
    `coverage.by_sheet["5.工程建设其他费用"] = {cost_inputs:23, suggested:23,
    unresolved:0}`，整张表零 no_rule（全部 unresolved 的 reason 只有 no_quantity）。
    该分流由**空 baselines** 场景覆盖，见
    tests/test_estimate_suggest.py::test_empty_baselines_yields_zero_suggestions_not_guesses
    （断言 no_rule 恰 10 格，含 C15/C24/C25/C26/C27）。

    aggregate / manual 两类不写输入位，故不在集合内。
    """
    out = set()
    for item in _load(ruleset)["items"]:
        if _write_target(item) == "input":
            out.add(f"{SHEET}!C{item['fee_row']}")
    return out


# ------------------------------------------------------------------ 小工具
def _num(x) -> str:
    if x is None:
        return "—"
    v = round(float(x), 6)
    if v == int(v):
        return str(int(v))
    return f"{v:.6f}".rstrip("0").rstrip(".")


def _rate_txt(rate, unit: str) -> str:
    return f"{_num(rate)}{_RATE_SYMBOL.get(unit, '')}"


def _round(x):
    return None if x is None else round(float(x), 4)


def _warn(code: str, message: str, cell=None, item_id=None) -> dict:
    return {"code": code, "cell": cell, "message": message, "item_id": item_id}


def _divisor(item: dict) -> float:
    unit = item.get("rate_unit")
    d = _RATE_DIVISOR.get(unit)
    if d is None:
        raise FeeRuleError(f"{item['fee_name']}：未知费率单位 {unit!r}")
    return d


def _write_target(item: dict) -> str:
    if item["item_id"] in AGGREGATE_CHILD_ROWS:
        return "aggregate"
    if item.get("paradigm") == "manual":
        return "manual"
    return "input"


def _interp(x, x0, y0, x1, y1) -> float:
    if float(x1) == float(x0):
        return float(y0)
    return float(y0) + (float(y1) - float(y0)) * (float(x) - float(x0)) / (float(x1) - float(x0))


def _close(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)), abs(float(b)))


# ------------------------------------------------------------------ 差额分档累进
def tiered_amount(x: float, uppers: list, rates: list) -> float:
    """逐档累加法：每档只对落在本档区间内的部分计费（费率须已归一，如 1.0% → 0.01）。"""
    total, lower = 0.0, 0.0
    for up, r in zip(uppers, rates):
        if up is None or x <= up:
            return total + (x - lower) * r
        total += (up - lower) * r
        lower = up
    return total


def quick_deductions(uppers: list, rates: list) -> list:
    """速算扣除数 QD_k = b_{k-1}·r_k − Σ_{i<k}(b_i − b_{i-1})·r_i。"""
    qds, acc, lower = [], 0.0, 0.0
    for up, r in zip(uppers, rates):
        qds.append(lower * r - acc)
        if up is not None:
            acc += (up - lower) * r
            lower = up
    return qds


def _locate_band(uppers: list, x: float) -> int:
    for i, up in enumerate(uppers):
        if up is None or x <= up:
            return i
    return len(uppers) - 1


def bands_of(item: dict, col: dict | None):
    """取 (uppers, rates)。三种档位写法都要认——漏认一种就会整条静默失效。

    ① 条目级 `bands`（项目建设管理费 / 建设管理其他费）
    ② 列级 `bands`（工程招标代理费；此时条目级 `band_uppers` 为 None）
    ③ 条目级 `band_uppers` + 列级 `rates_permille|rates_percent|rates`（工程造价咨询费）
    """
    for node in (col, item):
        if node and node.get("bands"):
            return ([b.get("upper") for b in node["bands"]],
                    [float(b["rate"]["value"]) for b in node["bands"]])
    ups = item.get("band_uppers")
    if ups and col:
        rates = col.get("rates_permille") or col.get("rates_percent") or col.get("rates")
        if rates:
            return (list(ups), [float(r) for r in rates])
    raise FeeRuleError(f"{item['fee_name']}：取不到档位（三种档位写法都不匹配）")


# ------------------------------------------------------------------ 选列 / 选情形
def _select_key(item, attrs, ctx, options: dict, attr_name: str, default_key: str, what: str):
    """按 attr 选 options 里的一个键；未给用默认并告警；给错值告警后回落默认。"""
    item_id = item["item_id"]
    raw = attrs.get(attr_name)
    if raw is None:
        raw = attrs.get(f"{item_id}__{attr_name}")
    if raw is not None:
        key = str(raw)
        if key in options:
            ctx["attrs_used"][attr_name] = key
            return key
        ctx["warnings"].append(_warn(
            "fee_attr_unknown_value",
            f"{item['fee_name']}：{what} {attr_name}={key!r} 不在可选值 "
            f"{sorted(options)} 内，已回落默认 {default_key!r}；金额可能不适用本项目",
            ctx["cell"], item_id))
    else:
        ctx["warnings"].append(_warn(
            "fee_attr_defaulted",
            f"{item['fee_name']}：未提供 {what} {attr_name}，按默认 {default_key!r} 计算；"
            f"该选择直接影响金额，请造价员确认（可选值 {sorted(options)}）",
            ctx["cell"], item_id))
    ctx["attrs_used"][attr_name] = default_key
    return default_key


def _select_column(item, attrs, ctx):
    cols = item.get("columns")
    if not isinstance(cols, dict):
        return None, None
    attr_name = COLUMN_ATTR.get(item["item_id"], "column")
    default_key = item.get("default_column") or sorted(cols)[0]
    key = _select_key(item, attrs, ctx, cols, attr_name, default_key, "取费列")
    col = cols[key]
    ctx["basis"]["column"] = {"key": key, "label": col.get("label")}
    if item.get("column_choice_note"):
        ctx["basis"]["column_choice_note"] = item["column_choice_note"]
    return key, col


# ------------------------------------------------------------------ 闭开性
def _pick_band(bands: list, x: float, closure: str):
    """按闭开性选档。返回 (index, band)；落不进任何档返回 (None, None)。

    第一档的下限一律取闭（`x >= lower`）：否则在 lower_exclusive 下 x 恰等于首档下限
    （数据里首档下限多为 0）会落空。这是确定性的边界约定，不改变档与档之间的归属。
    """
    for i, b in enumerate(bands):
        lo = b.get("lower")
        up = b.get("upper")
        lo = float("-inf") if lo is None else float(lo)
        if closure == CLOSURE_LOWER_INCLUSIVE:
            lo_ok = x >= lo
            up_ok = up is None or x < float(up)
        else:
            lo_ok = x >= lo if i == 0 else x > lo
            up_ok = up is None or x <= float(up)
        if lo_ok and up_ok:
            return i, b
    return None, None


def _closure_of(item, ctx, override=None):
    """取闭开性。未声明 → 用默认假设（调用方负责出告警，绝不静默选一边）。"""
    if override:
        return override, True
    declared = item.get("band_closure")
    if declared:
        ctx["basis"]["band_closure"] = declared
        ctx["basis"]["band_closure_source"] = "declared"
        if item.get("band_closure_note"):
            ctx["basis"]["band_closure_note"] = item["band_closure_note"]
        return declared, False
    ctx["basis"]["band_closure"] = DEFAULT_CLOSURE
    ctx["basis"]["band_closure_source"] = "assumed"
    return DEFAULT_CLOSURE, True


# ------------------------------------------------------------------ 各范式求值
def _eval_progressive(item, base, attrs, ctx):
    """差额分档累进：速算扣除数法（spec 指定写法），并给出逐档分解供人核。"""
    _key, col = _select_column(item, attrs, ctx)
    uppers, raw_rates = bands_of(item, col)
    unit = item["rate_unit"]
    div = _divisor(item)
    rates = [r / div for r in raw_rates]
    qds = quick_deductions(uppers, rates)
    i = _locate_band(uppers, base)

    amount = base * rates[i] - qds[i]

    ctx["steps"].append(
        f"差额分档累进：基数 {_num(base)} 万元落入第 {i + 1} 档（上界 {_num(uppers[i])}），"
        f"本档费率 {_rate_txt(raw_rates[i], unit)}")
    lower = 0.0
    for k in range(i):
        seg_lo, seg_hi = lower, float(uppers[k])
        ctx["steps"].append(
            f"（{_num(seg_hi)} − {_num(seg_lo)}）× {_rate_txt(raw_rates[k], unit)} "
            f"= {_num((seg_hi - seg_lo) * rates[k])}")
        lower = seg_hi
    ctx["steps"].append(
        f"（{_num(base)} − {_num(lower)}）× {_rate_txt(raw_rates[i], unit)} "
        f"= {_num((base - lower) * rates[i])}")
    ctx["steps"].append(f"逐档累加合计 = {_num(tiered_amount(base, uppers, rates))} 万元")
    ctx["steps"].append(
        f"速算扣除数法（等价校验）：{_num(base)} × {_rate_txt(raw_rates[i], unit)} "
        f"− ({_num(qds[i])}) = {_num(amount)} 万元")
    ctx["basis"]["band"] = {"index": i, "upper": uppers[i], "rate": raw_rates[i],
                            "rate_unit": unit, "quick_deduction": _round(qds[i])}

    min_fee = item.get("min_fee_wanyuan")
    if min_fee is not None and amount < float(min_fee):
        ctx["warnings"].append(_warn(
            "fee_min_fee_applied",
            f"{item['fee_name']}：按档位算得 {_num(amount)} 万元，低于最低收费 "
            f"{_num(min_fee)} 万元，已按最低收费计（{item.get('min_fee_note', '')}）",
            ctx["cell"], item["item_id"]))
        ctx["steps"].append(f"最低收费下限：{_num(min_fee)} 万元（{item.get('min_fee_note', '')}）")
        amount = float(min_fee)

    return amount, [amount, amount]


def _eval_base_rate_range(item, base, attrs, ctx):
    """基数 × 费率区间：建议值取区间中值，range 为区间两端。"""
    variants = item["variants"]
    attr_req = item.get("attr_required")
    if attr_req:
        key = _select_key(item, attrs, ctx, variants, attr_req["name"],
                          attr_req.get("default") or sorted(variants)[0],
                          attr_req.get("label") or attr_req["name"])
    else:
        key = "default" if "default" in variants else sorted(variants)[0]
    v = variants[key]
    unit = item["rate_unit"]
    div = _divisor(item)
    lo = base * float(v["rate_min"]) / div
    hi = base * float(v["rate_max"]) / div
    mid = (lo + hi) / 2.0
    ctx["basis"]["variant"] = {"key": key, "label": v.get("label"),
                               "rate_min": v["rate_min"], "rate_max": v["rate_max"],
                               "rate_unit": unit}
    ctx["steps"].append(
        f"情形「{v.get('label', key)}」费率区间 "
        f"{_rate_txt(v['rate_min'], unit)}~{_rate_txt(v['rate_max'], unit)}"
        f"（原文：{v.get('raw_text', '')}）")
    ctx["steps"].append(f"下限 = {_num(base)} × {_rate_txt(v['rate_min'], unit)} = {_num(lo)} 万元")
    ctx["steps"].append(f"上限 = {_num(base)} × {_rate_txt(v['rate_max'], unit)} = {_num(hi)} 万元")
    ctx["steps"].append(f"建议值取区间中值 = {_num(mid)} 万元")
    return mid, [lo, hi]


def _eval_base_price_interpolation(item, base, attrs, ctx):
    """收费基价表插值（工程监理费）。表外按比例外推并打 flag（数据 notes 明写）。"""
    anchors = [(float(a["x"]), float(a["y"]["value"])) for a in item["anchors"]]
    x0, y0 = anchors[0]
    xn, yn = anchors[-1]
    if base < x0:
        amount = y0 * base / x0 if x0 else 0.0
        ctx["warnings"].append(_warn(
            "fee_base_out_of_table",
            f"{item['fee_name']}：基数 {_num(base)} 万元低于表内最小档 {_num(x0)} 万元，"
            f"已按首锚点比例外推（{_num(y0)}×{_num(base)}/{_num(x0)}），表外值仅供参考",
            ctx["cell"], item["item_id"]))
        ctx["steps"].append(f"表外（< {_num(x0)}），按首锚点比例外推 = {_num(amount)} 万元")
        ctx["basis"]["extrapolated"] = "below_table"
    elif base > xn:
        amount = yn * base / xn if xn else 0.0
        ctx["warnings"].append(_warn(
            "fee_base_out_of_table",
            f"{item['fee_name']}：基数 {_num(base)} 万元高于表内最大档 {_num(xn)} 万元，"
            f"已按末锚点比例外推（{_num(yn)}×{_num(base)}/{_num(xn)}），表外值仅供参考",
            ctx["cell"], item["item_id"]))
        ctx["steps"].append(f"表外（> {_num(xn)}），按末锚点比例外推 = {_num(amount)} 万元")
        ctx["basis"]["extrapolated"] = "above_table"
    else:
        amount = y0
        for k in range(1, len(anchors)):
            xa, ya = anchors[k - 1]
            xb, yb = anchors[k]
            if xa <= base <= xb:
                amount = _interp(base, xa, ya, xb, yb)
                ctx["steps"].append(
                    f"收费基价插值：基数 {_num(base)} 落在锚点 [{_num(xa)}, {_num(xb)}] 之间，"
                    f"对应基价 [{_num(ya)}, {_num(yb)}] 万元")
                ctx["steps"].append(
                    f"{_num(ya)} + ({_num(yb)} − {_num(ya)}) × ({_num(base)} − {_num(xa)}) / "
                    f"({_num(xb)} − {_num(xa)}) = {_num(amount)} 万元")
                ctx["basis"]["anchor_span"] = [xa, xb]
                break
    return amount, [amount, amount]


def _eval_banded_value_range_interpolation(item, base, attrs, ctx, closure_override=None):
    """分档收费额区间 + 档内插值（可行性研究费 / 环境影响评价费）。"""
    _key, col = _select_column(item, attrs, ctx)
    bands = col["bands"]
    closure, _assumed = _closure_of(item, ctx, closure_override)
    i, b = _pick_band(bands, base, closure)
    if b is None:
        ctx["warnings"].append(_warn(
            "fee_base_out_of_table",
            f"{item['fee_name']}：基数 {_num(base)} 落不进任何档位，本项不出建议值",
            ctx["cell"], item["item_id"]))
        return None, [None, None]
    ctx["basis"]["band"] = {"index": i, "lower": b.get("lower"), "upper": b.get("upper"),
                            "fee_min": b.get("fee_min"), "fee_max": b.get("fee_max"),
                            "raw_text": b.get("raw_text")}
    fee_min = b.get("fee_min")
    fee_max = b.get("fee_max")
    if b.get("upper") is None:
        # 开口档走的是哪一条支路 —— 这是**规则表的结构**（该档原表只给下限 / 给了区间），
        # 不是本次算出的金额，量纲上不属于金额面，扣留时保留。签署闸的告警改写靠它把
        # 「只给下限」与「取区间中值」区分开，不必从正文里回读被扣留的数。
        ctx["basis"]["open_band_rule"] = (
            "lower_bound_only" if fee_max is None else "range_midpoint")
        if fee_max is None:
            ctx["warnings"].append(_warn(
                "fee_band_open_ended",
                f"{item['fee_name']}：基数落入开口档（原文 {b.get('raw_text')}），"
                f"原表只给下限，建议值取下限 {_num(fee_min)} 万元，实际可高于此值",
                ctx["cell"], item["item_id"]))
            ctx["steps"].append(f"开口档（{b.get('raw_text')}），仅取下限 {_num(fee_min)} 万元")
            return float(fee_min), [float(fee_min), None]
        mid = (float(fee_min) + float(fee_max)) / 2.0
        ctx["warnings"].append(_warn(
            "fee_band_open_ended",
            f"{item['fee_name']}：基数落入开口档（原文 {b.get('raw_text')}），"
            f"无上界无法插值，建议值取区间中值 {_num(mid)} 万元",
            ctx["cell"], item["item_id"]))
        ctx["steps"].append(
            f"开口档（{b.get('raw_text')}）无上界，取区间 "
            f"[{_num(fee_min)}, {_num(fee_max)}] 中值 = {_num(mid)} 万元")
        return mid, [float(fee_min), float(fee_max)]
    amount = _interp(base, b["lower"], fee_min, b["upper"], fee_max)
    ctx["steps"].append(
        f"落入第 {i + 1} 档（{_num(b['lower'])}, {_num(b['upper'])}]，"
        f"收费 {_num(fee_min)}~{_num(fee_max)} 万元（原文 {b.get('raw_text')}）")
    ctx["steps"].append(
        f"插入法：{_num(fee_min)} + ({_num(fee_max)} − {_num(fee_min)}) × "
        f"({_num(base)} − {_num(b['lower'])}) / ({_num(b['upper'])} − {_num(b['lower'])}) "
        f"= {_num(amount)} 万元")
    return amount, [amount, amount]


def _eval_banded_rate_range_interpolation(item, base, attrs, ctx, closure_override=None):
    """分档费率区间 + 档内插值（勘察设计费）。

    插值方向按数据 `interpolation_anchors_note` 声明的「规模越大费率越低」：
    档下限取 rate_max、档上限取 rate_min。该方向原文未显式说明，已在 basis 中原样带出。
    """
    bands = item["rate_bands"]
    closure, _assumed = _closure_of(item, ctx, closure_override)
    i, b = _pick_band(bands, base, closure)
    unit = item["rate_unit"]
    div = _divisor(item)
    if b is None:
        ctx["warnings"].append(_warn(
            "fee_base_out_of_table",
            f"{item['fee_name']}：基数 {_num(base)} 万元不在费率表覆盖区间 "
            f"[{_num(bands[0].get('lower'))}, {_num(bands[-1].get('upper'))}] 内，"
            f"原文无表外规则，**不外推**，本项不出建议值",
            ctx["cell"], item["item_id"]))
        return None, [None, None]
    rate = _interp(base, b["lower"], b["rate_max"], b["upper"], b["rate_min"])
    amount = base * rate / div
    ctx["basis"]["band"] = {"index": i, "lower": b.get("lower"), "upper": b.get("upper"),
                            "rate_min": b.get("rate_min"), "rate_max": b.get("rate_max"),
                            "rate_unit": unit, "raw_text": b.get("raw_text")}
    ctx["basis"]["interpolated_rate"] = round(rate, 6)
    ctx["basis"]["interpolation_anchors_note"] = item.get("interpolation_anchors_note")
    ctx["steps"].append(
        f"落入档 {_num(b['lower'])}~{_num(b['upper'])} 万元，费率 "
        f"{_rate_txt(b['rate_min'], unit)}~{_rate_txt(b['rate_max'], unit)}"
        f"（原文 {b.get('raw_text')}）")
    ctx["steps"].append(
        f"档内插值（规模越大费率越低）：{_rate_txt(b['rate_max'], unit)} + "
        f"({_rate_txt(b['rate_min'], unit)} − {_rate_txt(b['rate_max'], unit)}) × "
        f"({_num(base)} − {_num(b['lower'])}) / ({_num(b['upper'])} − {_num(b['lower'])}) "
        f"= {_rate_txt(round(rate, 6), unit)}")
    ctx["steps"].append(f"{_num(base)} × {_rate_txt(round(rate, 6), unit)} = {_num(amount)} 万元")
    return amount, [amount, amount]


def _eval_banded_unit_price_progressive(item, base, attrs, ctx):
    """分档单价累进（节能评估费）。

    单位代数：基数 万m2 × 10⁴ = m2；m2 × 元/m2 = 元；元 ÷ 10⁴ = 万元。
    两个 10⁴ 相消 → 万元 = Σ（各档 万m2 增量 × 该档 元/m2 单价）。
    """
    _key, col = _select_column(item, attrs, ctx)
    bands = col["bands"]
    closure, _assumed = _closure_of(item, ctx)
    i, b = _pick_band(bands, base, closure)
    ctx["steps"].append(
        f"分档累进：总建筑面积 {_num(base)} 万m2"
        f"（单位代数：万m2 × 10⁴ × 元/m2 ÷ 10⁴ = 万元）")
    total, lower = 0.0, 0.0
    for k, bd in enumerate(bands):
        up = bd.get("upper")
        price = float(bd["price"]["value"])
        last = up is None or base <= float(up)
        hi = base if last else float(up)
        if hi > lower:
            seg = hi - lower
            total += seg * price
            ctx["steps"].append(
                f"第 {k + 1} 档 {bd.get('band_label')}：（{_num(hi)} − {_num(lower)}）万m2 × "
                f"{_num(price)} 元/m2 = {_num(seg * price)} 万元")
            lower = hi
        if last:
            break
    ctx["steps"].append(f"累计 = {_num(total)} 万元")
    ctx["basis"]["band"] = ({"index": i, "lower": b.get("lower"), "upper": b.get("upper"),
                             "band_label": b.get("band_label")} if b else None)
    fr = item.get("float_range") or {}
    lo_f = float(fr.get("factor_min", 1.0))
    hi_f = float(fr.get("factor_max", 1.0))
    if fr:
        ctx["steps"].append(
            f"{fr.get('desc', '浮动幅度')}：区间 = [{_num(total * lo_f)}, {_num(total * hi_f)}] 万元")
    if item.get("paradigm_note"):
        ctx["warnings"].append(_warn(
            "fee_paradigm_disputed",
            f"{item['fee_name']}：{item['paradigm_note']}",
            ctx["cell"], item["item_id"]))
    return total, [total * lo_f, total * hi_f]


def _eval_unit_price_matrix(item, base, attrs, ctx, base_parts=None):
    """单价矩阵。单位代数：基数（m2 或 kVA）× 单价（元/单位）÷ 10⁴ = 万元。"""
    item_id = item["item_id"]
    matrix = item["matrix"]
    attr_req = item["attr_required"]
    row_key = _select_key(item, attrs, ctx, matrix, attr_req["name"],
                          attr_req.get("default") or sorted(matrix)[0],
                          attr_req.get("label") or attr_req["name"])
    row = matrix[row_key]

    if item_id == "municipal_infrastructure_fee":
        prices = row["prices"]
        ctx["basis"]["matrix_row"] = {"key": row_key, "label": row.get("label")}
        if base_parts:
            total = 0.0
            for use in sorted(base_parts):
                area = base_parts[use]
                p = prices.get(use)
                if p is None:
                    ctx["warnings"].append(_warn(
                        "fee_attr_unknown_value",
                        f"{item['fee_name']}：基数拆分键 {use!r} 不在 {sorted(prices)} 内，已忽略",
                        ctx["cell"], item_id))
                    continue
                amt = float(area) * float(p["value"]) / 10000.0
                total += amt
                ctx["steps"].append(
                    f"{use}：{_num(area)} m2 × {_num(p['value'])} 元/m2 ÷ 10000 = {_num(amt)} 万元")
            ctx["steps"].append(f"合计 = {_num(total)} 万元")
            ctx["basis"]["base_parts"] = dict(base_parts)
            return total, [total, total]
        use = _select_key(item, attrs, ctx, prices, _MUNICIPAL_USE_ATTR,
                          _MUNICIPAL_USE_DEFAULT, _MUNICIPAL_USE_LABEL)
        p = prices[use]
        amount = base * float(p["value"]) / 10000.0
        ctx["steps"].append(
            f"情形「{row.get('label')}」/ 用途 {use}：单价 {_num(p['value'])} 元/m2"
            f"（原文 {p.get('raw_text')}）")
        ctx["steps"].append(
            f"{_num(base)} m2 × {_num(p['value'])} 元/m2 ÷ 10000 = {_num(amount)} 万元")
        return amount, [amount, amount]

    # high_reliability_power_fee：行 = 电压等级，列 = 计费情形
    sc = item["scenario_attr"]
    scenario = _select_key(item, attrs, ctx, row, sc["name"],
                           sc.get("default") or sorted(row)[0],
                           sc.get("label") or sc["name"])
    cell_val = row[scenario].get("value")
    ctx["basis"]["matrix_row"] = {"key": row_key, "scenario": scenario, "price": cell_val,
                                  "raw_text": row[scenario].get("raw_text")}
    if cell_val is None:
        ctx["warnings"].append(_warn(
            "fee_matrix_not_applicable",
            f"{item['fee_name']}：电压等级 {row_key}kV × 情形 {scenario} 在原表中为「—」"
            f"（该情形不适用），本项转人工填报",
            ctx["cell"], item_id))
        ctx["steps"].append(f"矩阵格 {row_key}kV × {scenario} = 「—」，不适用")
        return None, [None, None]
    amount = base * float(cell_val) / 10000.0
    ctx["steps"].append(f"电压等级 {row_key}kV × 情形 {scenario}：单价 {_num(cell_val)} 元/(kV·A)")
    ctx["steps"].append(
        f"{_num(base)} kVA × {_num(cell_val)} 元/(kV·A) ÷ 10000 = {_num(amount)} 万元")
    return amount, [amount, amount]


_EVALUATORS = {
    "progressive_difference": _eval_progressive,
    "base_rate_range": _eval_base_rate_range,
    "base_price_interpolation": _eval_base_price_interpolation,
    "banded_value_range_interpolation": _eval_banded_value_range_interpolation,
    "banded_rate_range_interpolation": _eval_banded_rate_range_interpolation,
    "banded_unit_price_progressive": _eval_banded_unit_price_progressive,
    "unit_price_matrix": _eval_unit_price_matrix,
}

# 闭开性未声明时需要做「两侧都算一遍」降级的范式
_CLOSURE_SENSITIVE = ("banded_value_range_interpolation", "banded_rate_range_interpolation")


# ------------------------------------------------------------------ 基数解析
def _base_candidates(item: dict, column_fee_base=None) -> list:
    keys = [item["item_id"]]
    if column_fee_base:
        keys.append(column_fee_base)
    keys.extend(BASE_KEYS.get(item["item_id"], ()))
    name = (item.get("base") or {}).get("name")
    if name:
        keys.append(name)
    seen, out = set(), []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _resolve_base(item, bases: dict, column_fee_base=None):
    """从 `bases` 里取本项基数。严格查表，不拿别的口径的基数顶替。

    额外支持「按用途拆分」的键：`建筑面积.residential` / `建筑面积.non_residential`
    （市政基础设施配套费的基数在原表就是按用途分单价的）。
    """
    if not isinstance(bases, dict):
        return None, None, None
    cands = _base_candidates(item, column_fee_base)
    if item["item_id"] == "municipal_infrastructure_fee":
        parts, used = {}, []
        for k in cands:
            for use in ("residential", "non_residential"):
                key = f"{k}.{use}"
                v = bases.get(key)
                if use not in parts and isinstance(v, (int, float)) and not isinstance(v, bool):
                    parts[use] = float(v)
                    used.append(key)
        if parts:
            return sum(parts.values()), parts, "+".join(used)
    for k in cands:
        v = bases.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v), None, k
    return None, None, None


# ------------------------------------------------------------------ 适用性（WS10-P03）
#
# 有的规则只对某类项目成立：市政配套费的单价是杭州市区口径，联合试运转费 / 生产准备
# 及开办费只对有工艺设备的生产性项目计列。此前 16 条一律求值 —— 杭州标准套到义乌
# （3298.89 vs 真实 1199.60 万元），仓储项目计入联合试运转费并作为首选侧预填。
#
# 数据里的 `applicability` 只**扣留**金额，不产生新金额：
#   属性没给           → applicability_unconfirmed（不回落默认值 —— 默认杭州就是原缺陷本身）
#   给了但不在 allowed  → rule_not_applicable，按当地文件 / 实际人工填报
APPLICABILITY_UNCONFIRMED = "applicability_unconfirmed"
RULE_NOT_APPLICABLE = "rule_not_applicable"


def _option_label(rule: dict, value) -> str:
    for o in rule.get("options") or []:
        if o.get("value") == value:
            return o.get("label") or str(value)
    return str(value)


def _applicability(item: dict, attrs: dict, ctx: dict) -> str | None:
    """→ None（适用）/ APPLICABILITY_UNCONFIRMED / RULE_NOT_APPLICABLE，并写告警与依据。"""
    item_id = item["item_id"]
    for rule in item.get("applicability") or []:
        name = rule["attr"]
        label = rule.get("label") or name
        raw = attrs.get(name)
        if raw is None:
            raw = attrs.get(f"{item_id}__{name}")
        value = None if raw is None else str(raw).strip()
        choices = "、".join(o.get("label") or o["value"] for o in rule.get("options") or [])
        valid = {o["value"] for o in rule.get("options") or []}
        ctx["basis"].setdefault("applicability", []).append(
            {"attr": name, "label": label, "value": value, "allowed": list(rule.get("allowed") or [])})
        if not value or value not in valid:
            got = f"（收到不认识的取值 {value!r}）" if value else ""
            ctx["warnings"].append(_warn(
                "fee_applicability_unconfirmed",
                f"{item['fee_name']}：未确认{label}{got}，本项暂不出建议值 —— 该费率只对特定项目"
                f"成立，适用条件未确认时不回落默认值（可选：{choices}）",
                ctx["cell"], item_id))
            ctx["steps"].append(f"{label}未确认，本项不求值")
            return APPLICABILITY_UNCONFIRMED
        ctx["attrs_used"][name] = value
        if value not in (rule.get("allowed") or []):
            ctx["warnings"].append(_warn(
                "fee_rule_not_applicable",
                f"{item['fee_name']}：{rule.get('not_applicable_message') or '本规则不适用于本项目，按实际人工填报'}"
                f"（{label}：{_option_label(rule, value)}）",
                ctx["cell"], item_id))
            ctx["steps"].append(f"{label}={_option_label(rule, value)}，本规则不适用")
            return RULE_NOT_APPLICABLE
    return None


# ------------------------------------------------------------------ 求值主体
def _blank_ctx(item):
    cell = f"{SHEET}!C{item['fee_row']}" if _write_target(item) == "input" else None
    return {"cell": cell, "steps": [], "warnings": [], "attrs_used": {}, "basis": {}}


def _evaluate(item: dict, base, base_parts, base_key, attrs: dict, ruleset: str) -> dict:
    doc = _load(ruleset)
    item_id = item["item_id"]
    wt = _write_target(item)
    ctx = _blank_ctx(item)
    ctx["basis"] = {
        "paradigm": item["paradigm"],
        "source_ref": item.get("source_ref"),
        "source_image": item.get("source_image"),
        "source_table": item.get("source_table"),
        "base_name": (item.get("base") or {}).get("name"),
        "base_unit": (item.get("base") or {}).get("unit"),
        "base_value": base,
        "base_key": base_key,
        "ruleset": ruleset,
        "signoff_status": doc.get("signoff_status"),
        # 签的是谁：cost_engineer / owner_release / None。`suggest_one` 拿不到顶层
        # warnings，只有把它落进 basis，UI 才可能分清「造价员核过」与「仓主放行」。
        "signoff_kind": doc.get("signoff_kind"),
        "signoff_by": doc.get("signoff_by"),
        "requires_human_signoff": bool(doc.get("requires_human_signoff")),
        "amount_unit": doc.get("amount_unit"),
        "steps": [],
    }
    suggested = None
    rng = [None, None]
    unavailable = None
    # WS10-P03：适用性先于一切求值；不适用 / 未确认时连基数都不看（缺基数的诊断会把
    # 「这条本项目不该计」盖掉，与 #132 里 no_base 盖住签署闸是同一种形态）
    not_applicable = _applicability(item, attrs, ctx) if wt != "manual" else None

    if not_applicable is not None:
        unavailable = not_applicable
    elif wt == "manual":
        unavailable = "manual_paradigm"
        ctx["basis"]["manual_reason"] = item.get("manual_reason")
        ctx["steps"].append(f"原表无可规则化的数值费率：{item.get('manual_reason', '')}")
        ctx["warnings"].append(_warn(
            "fee_manual_only",
            f"{item['fee_name']}：{item.get('manual_reason', '原表无数值费率')}"
            f" —— 本项不出建议值，须人工填报",
            ctx["cell"], item_id))
    elif base is None:
        unavailable = "no_base"
        hint = item.get("base_note") or ""
        ctx["warnings"].append(_warn(
            "fee_base_missing",
            f"{item['fee_name']}：未提供计费基数（可接受的键 {_base_candidates(item)}），"
            f"本项不出建议值。{hint}",
            ctx["cell"], item_id))
    elif base <= 0:
        unavailable = "non_positive_base"
        ctx["warnings"].append(_warn(
            "fee_base_non_positive",
            f"{item['fee_name']}：计费基数为 {_num(base)}（非正数），本项不出建议值",
            ctx["cell"], item_id))
    else:
        fn = _EVALUATORS.get(item["paradigm"])
        if fn is None:
            raise FeeRuleError(f"{item['fee_name']}：未实现的范式 {item['paradigm']!r}")
        if item["paradigm"] == "unit_price_matrix":
            suggested, rng = fn(item, base, attrs, ctx, base_parts=base_parts)
        else:
            suggested, rng = fn(item, base, attrs, ctx)
        if suggested is None and unavailable is None:
            unavailable = "rule_not_applicable"

        # 闭开性未确认的降级：默认侧算一遍、另一侧再算一遍，如实报告差异，不静默选边
        if item.get("band_closure") is None and item["paradigm"] in _CLOSURE_SENSITIVE:
            alt = (CLOSURE_LOWER_INCLUSIVE if DEFAULT_CLOSURE == CLOSURE_LOWER_EXCLUSIVE
                   else CLOSURE_LOWER_EXCLUSIVE)
            probe = _blank_ctx(item)
            alt_amount, _alt_rng = _EVALUATORS[item["paradigm"]](
                item, base, attrs, probe, closure_override=alt)
            differs = not _close(suggested, alt_amount)
            ctx["basis"]["closure_alternative"] = {
                "closure": alt, "suggested": _round(alt_amount), "affects_amount": differs}

            def _side(v):
                return f"{_num(v)} 万元" if v is not None else "落不进任何档、不出建议值"

            ctx["warnings"].append(_warn(
                "fee_band_closure_unconfirmed",
                f"{item['fee_name']}：原表未声明档位闭开性（已登记为已知缺口，须造价员对原图确认）。"
                f"本次按 {DEFAULT_CLOSURE} 算得 {_side(suggested)}；"
                f"按 {alt} 算得 {_side(alt_amount)}；"
                + ("**两者不同，本项金额依赖该未确认假设**，请优先确认。"
                   if differs else "两者一致，该假设在本基数下不影响金额。"),
                ctx["cell"], item_id))

    if item.get("sub_item_manual"):
        sm = item["sub_item_manual"]
        ctx["warnings"].append(_warn(
            "fee_partial_coverage",
            f"{item['fee_name']}：规则只覆盖部分子项，「{sm.get('name')}」{sm.get('reason')}，"
            f"建议值**不含**该子项，须人工补",
            ctx["cell"], item_id))
        ctx["basis"]["sub_item_manual"] = sm

    if item.get("adjustments"):
        ctx["basis"]["available_adjustments"] = item["adjustments"]
        ctx["steps"].append(
            "以下调整系数**未自动应用**（是否适用取决于项目属性，须造价员判断）："
            + "；".join(a.get("desc", a.get("id", "")) for a in item["adjustments"]))
    if item.get("extra_rules"):
        ctx["basis"]["extra_rules"] = item["extra_rules"]
    if item.get("notes"):
        ctx["basis"]["notes"] = item["notes"]

    children = None
    if wt == "aggregate":
        children = [f"{SHEET}!C{r}" for r in AGGREGATE_CHILD_ROWS[item_id]]
        ctx["warnings"].append(_warn(
            "fee_write_target_aggregate",
            f"{item['fee_name']}：C{item['fee_row']} 是公式格（小计）不是输入位，"
            f"本值仅为**小计参考值**，须由用户自行拆到子项 {children}；引擎不做平分",
            None, item_id))

    ctx["basis"]["steps"] = ctx["steps"]
    return {
        "item_id": item_id,
        "fee_name": item["fee_name"],
        "target_cell": ctx["cell"],
        "write_target": wt,
        "aggregate_children": children,
        "suggested": _round(suggested),
        "range": [_round(rng[0]), _round(rng[1])],
        "basis": ctx["basis"],
        "editable": True,
        "attrs_used": ctx["attrs_used"],
        "signoff_status": doc.get("signoff_status"),
        "signoff_kind": doc.get("signoff_kind"),
        "ruleset": ruleset,
        "unavailable_reason": unavailable,
        "warnings": ctx["warnings"],
    }


# ------------------------------------------------------------------ 签署闸（O-05）
#
# 铁律 2：LLM 不碰金额。本规则集的 591 行费率数据是 **LLM 视觉转录**产物
# （`transcribed_by="llm"`），未经造价员对图签字。转录值一旦通过 suggest 出到
# 前端就会被预填进 5.工程建设其他费用 的 C 列，逐级汇总进 C5→C47→C50 总投资 ——
# 那就是「LLM 转录值直接驱动金额」，只出一条 warning 拦不住。
#
# 所以：`signoff_status != "signed"` 时，**公开入口一律不产出非 None 的 suggested**。
# 结构信息（16 条齐全、落点、依据、来源文号、属性回落）照出，唯独金额面扣留。
# 解闸方式只有一种：造价员对着 estimate_templates/fee_images/ 原扫描图逐值核完，
# 把 `fee_rules_zj2018.json` 的 signoff_status 改成 "signed" 并写上 signoff_by。
# 代码里**没有**绕过参数 —— 加一个就等于没有闸。
#
# 算术仍然可测：`_suggest_one_ungated` / `_suggest_all_ungated` 是内部入口，
# 转录正确性的证据（含原表自带算例的复算）全部走它们，闸只管公开出口。
#
# ── 2026-09-10 增补：签署有两种，闸也变成两级（issue #159 仓主裁定）─────────
#
# 仓主裁定「默认放行、先部署、按真实使用反馈纠偏」。落地方式**不是**在代码里开一个
# 绕过参数（那等于拆闸），而是把数据的 `signoff_status` 翻成 `signed` —— 同时新增
# `signoff_kind` 如实记录**这是谁签的**：
#
#   signoff_kind = "cost_engineer"  造价员对图逐值核毕（本规则集尚未到达此状态）
#   signoff_kind = "owner_release"  仓主默认放行，**393 个转录值未经逐值核对**
#
# `owner_release` 解闸的效果与造价员签署完全一样（13 个输入位出建议值），但：
#   · `signoff_by` 如实写「仓主默认放行（非造价员签署）」，**不伪造造价员姓名** ——
#     审计链条不许撒谎，将来出问题时那个人从没看过这些数字；
#   · 每次求值另出一条 `fee_rules_owner_released` 规则集级告警，明码写清代价。
#
# 这是对铁律 2 后半句「未经造价员签署的转录费率不许出建议值」的**有意覆盖**，
# 由仓主 2026-09-10 在 issue #159 决定。前半句（LLM 不碰金额、需用户确认）不变：
# `editable` 恒 True，建议值仍需用户逐条确认才进计算。
#
# ── 条目级闸：即使规则集已签署，档界不可推测的条目仍逐条扣留 ────────────────
#
# 铁律 3「查不到就是查不到，绝不编一个金额出来」。`勘察设计费` 有 `rate_bands`
# 却没声明 `band_closure` —— 原表没写档界归属（下限含不含、上限含不含），引擎只能
# 假设一侧。这个假设**不在仓主裁定的覆盖范围内**：裁定放行的是「未经逐值核对的转录
# 数值」，而档界闭开性是一处**转录也解不出来的原文缺失**，两码事。所以它继续扣留，
# `unavailable_reason=band_closure_unconfirmed`，并在告警里点名。
# 解法只有造价员对着原图确认后给该条目补上 `band_closure`。
WITHHELD_REASON = "ruleset_unsigned"
WITHHELD_REASON_CLOSURE = "band_closure_unconfirmed"

SIGNOFF_KIND_COST_ENGINEER = "cost_engineer"
SIGNOFF_KIND_OWNER_RELEASE = "owner_release"


def is_signed(ruleset: str = DEFAULT_RULESET) -> bool:
    """该规则集是否已签署（放行金额面）。未签 → 公开入口不出金额。

    ⚠ 「已签署」不等于「造价员签署」—— 见 `signoff_kind`。
    """
    return _load(ruleset).get("signoff_status") == "signed"


def signoff_kind(ruleset: str = DEFAULT_RULESET) -> str | None:
    """谁签的：`cost_engineer` / `owner_release` / None（未签或数据没写）。"""
    return _load(ruleset).get("signoff_kind")


def is_cost_engineer_signed(ruleset: str = DEFAULT_RULESET) -> bool:
    """是否**造价员**逐值核毕签署。铁律 2 原本要求的就是这一种。"""
    return is_signed(ruleset) and signoff_kind(ruleset) == SIGNOFF_KIND_COST_ENGINEER


def _unsigned_warning(doc: dict, ruleset: str) -> dict:
    return _warn(
        "fee_rules_unsigned",
        f"费率规则集 {ruleset} 的 signoff_status={doc.get('signoff_status')!r}"
        f"（转录方 {doc.get('transcribed_by')}），未经造价员签署，"
        f"**本次不产出任何建议金额**（16 条的 suggested 全部为 null）。"
        f"{doc.get('signoff_note', '')}")


def _owner_released_warning(doc: dict, ruleset: str) -> dict:
    """已签署、但签的人不是造价员 —— 建议值照出，代价必须明码写出来。

    铁律 2 的后半句被有意覆盖了，那就不许**同时**把这件事藏起来
    （铁律 2 原话：「也不许因为难看就藏起来」）。
    """
    unresolved = [c["id"] for c in (doc.get("signoff_checklist") or [])
                  if not c.get("resolution")]
    return _warn(
        "fee_rules_owner_released",
        f"费率规则集 {ruleset} 已放行出建议值，但 signoff_kind="
        f"{doc.get('signoff_kind')!r}、signoff_by={doc.get('signoff_by')!r} —— "
        f"**不是造价员签署**：{len(doc.get('items') or [])} 条规则的转录数值"
        f"（转录方 {doc.get('transcribed_by')}）未经造价员逐值核对，"
        f"{'语义歧义 ' + '/'.join(unresolved) + ' 也仍未对图解决' if unresolved else ''}。"
        f"建议值请当作**待核实的参考**，逐条确认后再采纳。{doc.get('signoff_note', '')}")


def _scrub_closure(w: dict, s: dict, why: str) -> dict:
    differs = ((s.get("basis") or {}).get("closure_alternative") or {}).get("affects_amount")
    tail = ("**两种闭开性算得的金额不同，本项金额依赖该未确认假设**，请优先确认。"
            if differs else "两种闭开性算得的金额一致，该假设在本基数下不影响金额。")
    # 条目级扣留时，「本基数下一致」这句话很容易被读成「那就给个值呗」。把话说完：
    # 一致的是**这一次**的算术结果，不是档界归属本身 —— 换一个正好落在档界上的
    # 基数，结论就不同了。所以扣留是无条件的（见 `_gate` 的注释）。
    if not differs and s.get("unavailable_reason") == WITHHELD_REASON_CLOSURE:
        tail += ("⚠ 但「本基数下一致」只是这一次的算术巧合，**不等于档界归属已经确定**："
                 "换一个正好落在档界上的基数，两侧就会给出不同的档。规则未知即不出金额，"
                 "本项一律扣留。")
    return dict(w, message=(
        f"{s['fee_name']}：原表未声明档位闭开性（已登记为已知缺口，须造价员对原图确认）。"
        f"{tail}（{why}，两侧试算金额不予披露）"))


def _scrub_min_fee(w: dict, s: dict, why: str) -> dict:
    """原文：「按档位算得 0.004428 万元，低于最低收费 0.2 万元，已按最低收费计（…不足2000元
    的，按2000元收费）」—— 两个金额加一条把金额写进正文的表注，全在告警里。

    ⚠ 如实说明：最低收费触发时，本项金额**就等于**表里那个常数，所以「为什么按最低
    收费计」与「金额是多少」在这条规则上是同一件事，无法只披露前者。信号（本项走了
    最低收费下限）保留，两个数与那条表注一并扣留；出处见 basis。
    """
    return dict(w, message=(
        f"{s['fee_name']}：按档位算得的金额低于原表规定的最低收费，**已按最低收费计**。"
        f"（{why}，档位算得的金额与最低收费额均不予披露；出处见 basis）"))


def _scrub_out_of_table(w: dict, s: dict, why: str) -> dict:
    """外推那两个分支把算式 `y0×base/x0` 逐字写进正文 —— 那是推导过程，不是规则参数，
    与 `basis.steps` 同一性质。落不进档位 / 不外推的分支本就不含金额面，原样保留。
    """
    where = (s.get("basis") or {}).get("extrapolated")
    if where not in ("below_table", "above_table"):
        return w
    side = "低于表内最小档" if where == "below_table" else "高于表内最大档"
    anchor = "首锚点" if where == "below_table" else "末锚点"
    return dict(w, message=(
        f"{s['fee_name']}：基数{side}，已按{anchor}比例外推，**表外值仅供参考**。"
        f"（{why}，外推算式与金额不予披露）"))


def _scrub_open_ended(w: dict, s: dict, why: str) -> dict:
    """开口档那两条支路各把一个被扣留的金额逐字印在正文里（对抗复核第 2 轮实证）：

      · 只给下限支路：「原表只给下限，建议值取下限 184 万元」 —— 184 就是 suggested；
      · 取中值支路：  「无上界无法插值，建议值取区间中值 207 万元」 —— 207 就是 suggested，
        而同句的「原文 184.0~230.0」把 range 两端一并带出（basis.band.raw_text
        在扣留时已经因为这个理由被 pop 掉了，正文这一份是漏网的第二份）。

    改写口径与 `_scrub_min_fee` 同款：**信号留、数扣**。留下的信号是「本项落在原表
    最后一个开口档上」和「该档原表是只给下限还是给了区间」—— 两者都是规则表的结构，
    出处见 basis.band（档界 lower / upper=None 与 open_band_rule 都还在）。
    """
    rule = (s.get("basis") or {}).get("open_band_rule")
    how = {
        "lower_bound_only": "原表在该档只给下限、不给上限，建议值即取该下限，**实际可高于此值**",
        "range_midpoint": "原表在该档只给一个收费区间、没有上界基数可插值，建议值取该区间中值",
    }.get(rule, "原表在该档没有上界基数可插值")
    return dict(w, message=(
        f"{s['fee_name']}：基数落入原表最后一个**开口档**（无上界）。{how}。"
        f"（{why}，该档原文与由它算得的金额均不予披露；档界出处见 basis.band）"))


def _scrub_aggregate(w: dict, s: dict, why: str) -> dict:
    """WS10-P11 的两条对账告警（fee_aggregate_mismatch / fee_possible_double_count）把小计参考值
    写进正文。它们只在小计参考值**已出**时才会产生（aggregate_checks 对 suggested=None 的条目直接跳过），
    今天走不到扣留分支；登记在这里是守纪律：哪天改成对扣留条目也做对账，金额不许漏出去。"""
    return dict(w, message=(
        f"{s.get('fee_name')}：子项与规则小计对账有差异或可能重复计列。（{why}，小计参考值与子项金额不予披露）"))


# code → 改写函数。**新增任何会把金额写进正文的 code，都必须在这里登记**，
# 否则 tests/test_fee_rules_data.py 的金额面扫描会当场转红。
# 「登记了才不红」不再只是自觉纪律：
# `tests/test_fee_rules_data.py::test_every_warn_site_that_prints_an_amount_is_registered`
# 会静态扫本模块的每一处 `_warn(...)`，凡正文里同时出现 `_num(` 与「万元」而 code
# 没登记的，当场点名。
_WARNING_SCRUBBERS = {
    "fee_band_closure_unconfirmed": _scrub_closure,
    "fee_min_fee_applied": _scrub_min_fee,
    "fee_base_out_of_table": _scrub_out_of_table,
    "fee_band_open_ended": _scrub_open_ended,
    "fee_aggregate_mismatch": _scrub_aggregate,
    "fee_possible_double_count": _scrub_aggregate,
}


# 扣留理由 → 告警正文里那句括号的措辞。**新增扣留理由必须在这里登记**，
# 否则改写出来的告警会说错话（说"规则集未签署"而实际上规则集已经签了）。
_WITHHOLD_WHY = {
    WITHHELD_REASON: "规则集未签署",
    WITHHELD_REASON_CLOSURE: "本条目档界闭开性未经造价员对图确认",
}


def _scrub_warning(w: dict, s: dict, why: str) -> dict:
    """扣留金额时，把正文里带金额（或带金额推导算式）的告警改写成不含数字的等价表述。

    留着它们，造价员照样能从告警里抄出一个未签署的 LLM 转录值填进表 —— 闸就白设了。
    但「这条金额依赖一个未确认的假设 / 走了最低收费 / 是表外外推」这些信号必须保留，
    所以一律是**改写不是删除**。
    """
    fn = _WARNING_SCRUBBERS.get(w.get("code"))
    return fn(w, s, why) if fn else w


STEPS_WITHHELD = (
    "本项金额被扣留，金额推导明细不予披露（范式、档位、费率、基数、出处见 basis 其余各键）。"
    "扣留原因见本条的 unavailable_reason 与告警；解除后本项即出完整推导。"
)

# basis 里以**金额单位**（amount_unit，万元）计价的键 —— 扣留时一律清掉。
# 判据是「量纲」不是「重要性」：
#   · `quick_deduction` 是万元常数，base × rate − QD 一步就是本次金额；
#   · `fee_min` / `fee_max` / `min_fee` 是原表直接标价的费用区间与下限，本身就是金额；
#   · `band.lower` / `band.upper` / `anchor_span` 同样是万元，但它们是**基数**的档界
#     （base_unit），不是金额面，且用户自己填的 base_value 本来就在手上 → 保留。
_AMOUNT_FACE_BAND_KEYS = ("quick_deduction", "fee_min", "fee_max")


def _withhold_basis(basis: dict) -> dict:
    """把 basis 的**金额面**一并扣留，只留结构与出处。

    为什么只清 `suggested` 不够（对抗复核第 1 轮实证）：`basis["steps"]` 就是金额推导
    的逐行过程，末行形如「逐档累加合计 = 185 万元」。实测 16 条里有 9 条 suggested
    已扣留、steps 里照样带着「= X 万元」的结论行；而界面把 steps 逐条渲染在
    **同一行的手填输入框旁边**（Wizard.vue:724 的 v-for 紧挨着 700-707 的
    a-input-number）—— 展开读到 185，抬手填进去，随后进 compute → C5 → C47 → C50
    总投资。闸对 UI 而言形同虚设。

    扣什么、留什么：
      扣  steps（整段换成一句不含数字的说明）
      扣  band.quick_deduction / band.fee_min / band.fee_max（万元计价）
      扣  band.raw_text —— 仅当该档是「直接标价」档（带 fee_min/fee_max）时，
          它的原文就是 "25.8~69.0" 这样的金额区间
      扣  min_fee（万元）
      扣  interpolated_rate —— 它不是表里的费率，是**按本次 base_value 插出来的**
          等效费率，base_value × 它 = 本次金额，属于「本次结果」而非「规则参数」
      扣  closure_alternative.suggested（原有行为，保留）
      留  paradigm / source_* / notes / base_* / band 的档界与表内费率 /
          variant / matrix_row / column / 闭开性 / available_adjustments / extra_rules

    ⚠ 如实说明这条闸**没有**覆盖什么：对 `base_rate_range`（如场地准备费 0.7%~0.8%）
    这类单步范式，表内费率 × 用户自己填的基数仍然是一次乘法就到金额。那不是疏漏
    而是刻意的边界 —— 闸拦的是「引擎把算好的金额递到手上」，不是「让造价员看不见
    这张待签署的费率表」。看得见费率正是签署评审要做的事（铁律 2 的「须用户确认」）；
    看不见费率，basis 就退化成一句"有规则但不告诉你"，评审无从下手。
    """
    out = dict(basis)
    if "steps" in out:
        out["steps"] = [STEPS_WITHHELD]

    band = out.get("band")
    if isinstance(band, dict):
        b = dict(band)
        tabulated_fee = any(k in b for k in ("fee_min", "fee_max"))
        for k in _AMOUNT_FACE_BAND_KEYS:
            b.pop(k, None)
        if tabulated_fee:
            # "25.8~69.0" —— 直接标价档的原文就是金额区间本身
            b.pop("raw_text", None)
        out["band"] = b

    if out.get("min_fee") is not None:
        out["min_fee"] = None
    if out.get("interpolated_rate") is not None:
        out["interpolated_rate"] = None

    alt = out.get("closure_alternative")
    if isinstance(alt, dict):
        out["closure_alternative"] = dict(alt, suggested=None)
    return out


_WITHHELD_EXPLAIN = {
    WITHHELD_REASON: (
        "费率规则集未经造价员签署（铁律 2：未签署的 LLM 转录值不得驱动金额）。"
        "签署后本项即出建议值。"),
    WITHHELD_REASON_CLOSURE: (
        "原表未声明本条目的档位闭开性（`band_closure` 缺失），档界处该用哪一档费率"
        "**不可推测**。规则集虽已放行，这一条仍单独扣留 —— 放行它等于在档界上编一个"
        "金额出来（铁律 3：查不到就是查不到）。解法：造价员对着原扫描图确认档界归属后，"
        "给该条目补上 band_closure。"),
}


def _withhold(s: dict, reason: str = WITHHELD_REASON) -> dict:
    """清空一条 FeeSuggestion 的金额面（顶层 + basis，见 `_withhold_basis`）。

    `reason` 决定 `unavailable_reason` 与告警措辞：规则集级扣留（未签署）与
    条目级扣留（档界闭开性未确认）说的不是同一件事，不许共用一句话 ——
    规则集已签署时还说「未经造价员签署」就是在骗读者。
    """
    out = dict(
        s,
        basis=_withhold_basis(s["basis"]),
        suggested=None,
        range=[None, None],
        # 已有的不可用原因（no_base / manual_paradigm / …）是更具体的诊断，不覆盖
        unavailable_reason=s.get("unavailable_reason") or reason,
    )
    why = _WITHHOLD_WHY.get(reason, "本项金额被扣留")
    out["warnings"] = [_scrub_warning(w, out, why) for w in s["warnings"]]
    if s["suggested"] is not None or s["range"] != [None, None]:
        out["warnings"] = [*out["warnings"], _warn(
            "fee_suggestion_withheld",
            f"{s['fee_name']}：规则依据齐全但**建议金额被扣留** —— "
            f"{_WITHHELD_EXPLAIN.get(reason, '')}",
            s["target_cell"], s["item_id"])]
    return out


def _closure_unconfirmed(s: dict) -> bool:
    """本条的档界归属仍是**引擎自己假设的**，不是原表写的。

    判据取 `basis.closure_alternative` 的存在性 —— 它由 `_evaluate` 里
    「`band_closure` 未声明且范式属 `_CLOSURE_SENSITIVE`」那一支写入，
    与告警 `fee_band_closure_unconfirmed` 同一个分支，不会漂移。
    """
    return isinstance((s.get("basis") or {}).get("closure_alternative"), dict)


def _gate(result: dict, ruleset: str) -> dict:
    """公开入口的统一出口：两级扣留 + 重建顶层 warnings。

    ① 规则集未签署 → 16 条全部扣留（`ruleset_unsigned`）。
    ② 规则集已签署但某条的档界闭开性未确认 → **该条**扣留
       （`band_closure_unconfirmed`），其余照出。

    ⚠ ② 是无条件的，不看 `closure_alternative.affects_amount`：那个字段说的是
    「在**本次这个基数**上两侧算得的金额是否相同」，不是「档界归属已经确定」。
    按它放行等于「大多数基数下给值、恰好落在档界上时不给值」——同一条费用时有时无，
    而真正危险的那次（正好卡在档界）恰恰是它不给值的那次，用户只会以为引擎坏了。
    档界归属未知就是规则未知，铁律 3。
    """
    signed = is_signed(ruleset)
    items, changed = [], False
    for s in result["items"]:
        if not signed:
            items.append(_withhold(s, WITHHELD_REASON))
            changed = True
        elif _closure_unconfirmed(s):
            items.append(_withhold(s, WITHHELD_REASON_CLOSURE))
            changed = True
        else:
            items.append(s)
    if not changed:
        return result
    # 规则集级告警（量级哨兵、owner_released 之类，item_id 为 None）不属于任何一条，
    # 重建时必须留住 —— 否则「传错了单位」这条诊断会被签署闸顺手吃掉。
    # fee_rules_unsigned 例外：未签署时换成扣留版措辞，已签署时它本就不该出现。
    warnings = [] if signed else [_unsigned_warning(_load(ruleset), ruleset)]
    warnings.extend(w for w in result["warnings"]
                    if w.get("item_id") is None
                    and (signed or w.get("code") != "fee_rules_unsigned"))
    for s in items:
        warnings.extend(s["warnings"])
    return {"items": items, "warnings": warnings}


# ------------------------------------------------------------------ 量级哨兵（O-06）
#
# 16 条规则的基数混着 万元 / 万m2 / m2 / kVA 四种单位。最危险的一对是
# 「总建筑面积」(万m2, 节能评估费) 与「建筑面积」(m2, 市政配套费)：名字只差一个字，
# 量纲差 10^4。把 60000 m² 当成 60000 万m² 传进去，节能评估费放大约 4300 倍，
# 而求值器一声不吭 —— 它拿到的是个合法正数。
#
# 这是**哨兵不是闸**（与铁律 7 同一条纪律）：只出 warning，照常出建议值。
# 区间取得很宽，只挡"差几个数量级"这种量纲错，不挡"这个项目特别大/特别小"。
_BASE_MAGNITUDE_SANE: dict[str, tuple[float, float]] = {
    # 0.001 万m² = 10 m²；500 万m² = 500 万平米（超大城市综合体量级已远在其下）
    "万m2": (0.001, 500.0),
    # 10 m²；5,000,000 m²（= 500 万m²，与上一行同一个上界，换算过来）
    "m2": (10.0, 5_000_000.0),
    # 0.1 万元 = 1000 元；5,000,000 万元 = 500 亿元
    "万元": (0.1, 5_000_000.0),
    # 1 kVA；1,000,000 kVA = 100 万 kVA
    "kVA": (1.0, 1_000_000.0),
}

# 同量纲、名字相近、单位差 10^4 的一对。factor = 把「按兄弟单位读出来的数」换算成本键单位。
# 万m2 键收到 60000：按 m2 读是 60000 m²（合理）→ 本键应传 60000×1e-4 = 6。
_UNIT_SIBLING = {"万m2": ("m2", 1e-4), "m2": ("万m2", 1e4)}


def base_key_units(ruleset: str = DEFAULT_RULESET) -> dict[str, str]:
    """所有可接受的基数键 → 单位。含市政配套费的 `建筑面积.residential` 拆分键。"""
    out: dict[str, str] = {}
    for spec in required_bases(ruleset):
        unit = spec["unit"]
        if not unit:
            continue
        for k in spec["accepted_keys"]:
            out.setdefault(k, unit)
            if spec["item_id"] == "municipal_infrastructure_fee":
                for use in ("residential", "non_residential"):
                    out.setdefault(f"{k}.{use}", unit)
    return out


def check_base_magnitudes(bases: dict | None,
                          ruleset: str = DEFAULT_RULESET) -> list[dict]:
    """量级哨兵：基数值与其声明单位差几个数量级时出 `fee_base_magnitude_suspect`。

    只出告警，不改值、不拦截。单位未知的键（调用方自造的 item_id 覆盖键之外的键）
    直接跳过 —— 无判据就不报，不猜。
    """
    if not isinstance(bases, dict) or not bases:
        return []
    units = base_key_units(ruleset)
    out: list[dict] = []
    for key, raw in bases.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        unit = units.get(key)
        sane = _BASE_MAGNITUDE_SANE.get(unit or "")
        if sane is None:
            continue
        lo, hi = sane
        v = float(raw)
        if lo <= v <= hi:
            continue
        hint = ""
        sib = _UNIT_SIBLING.get(unit or "")
        if sib is not None:
            other_unit, factor = sib
            olo, ohi = _BASE_MAGNITUDE_SANE[other_unit]
            if olo <= v <= ohi:
                hint = (f"；这个数按 {other_unit} 读倒是合理的 —— 很可能把 {other_unit} 的数"
                        f"直接当 {unit} 传了（两者差 10^4）。若确是 {other_unit}，"
                        f"本键应传 {_num(v * factor)}")
        out.append(_warn(
            "fee_base_magnitude_suspect",
            f"计费基数 {key}={_num(v)} 的量级可疑：该键单位为 {unit}，"
            f"常规区间约 {_num(lo)}~{_num(hi)}{hint}。"
            f"本次仍按传入值照算（哨兵不设硬闸），请核对单位。"))
    return out


# ------------------------------------------------------------------ 对外入口
def _suggest_one_ungated(item_id: str, base=None,
                         attrs: dict | None = None,
                         ruleset: str = DEFAULT_RULESET) -> dict:
    """内部：不过签署闸的单条求值。**只供转录正确性测试与签署复核使用。**

    产品路径一律走 `suggest_one` / `suggest_all`。
    """
    item = _index(ruleset).get(item_id)
    if item is None:
        raise FeeRuleError(f"未知费用条目 {item_id!r}；可用：{sorted(_index(ruleset))}")
    b = None if base is None else float(base)
    return _evaluate(item, b, None, item_id if b is not None else None,
                     dict(attrs or {}), ruleset)


def _suggest_all_ungated(bases: dict | None = None,
                         attrs: dict | None = None,
                         ruleset: str = DEFAULT_RULESET) -> dict:
    """内部：不过签署闸的全量求值。**只供转录正确性测试与签署复核使用。**"""
    doc = _load(ruleset)
    bases = bases or {}
    attrs = dict(attrs or {})
    items, warnings = [], []

    if doc.get("signoff_status") != "signed":
        warnings.append(_unsigned_warning(doc, ruleset))
    elif doc.get("signoff_kind") != SIGNOFF_KIND_COST_ENGINEER:
        # 已签署但不是造价员签的（当前是仓主默认放行）。金额照出 —— 但"照出"和
        # "不声明"是两件事，铁律 2 的最后一句：也不许因为难看就藏起来。
        warnings.append(_owner_released_warning(doc, ruleset))

    # 量级哨兵（O-06）：先于求值，让「单位传错」这条诊断排在一堆费用告警之前
    warnings.extend(check_base_magnitudes(bases, ruleset))

    for item in doc["items"]:
        column_fee_base = None
        cols = item.get("columns")
        if isinstance(cols, dict):
            attr_name = COLUMN_ATTR.get(item["item_id"], "column")
            key = str(attrs.get(attr_name) or attrs.get(f"{item['item_id']}__{attr_name}")
                      or item.get("default_column") or "")
            column_fee_base = (cols.get(key) or {}).get("fee_base")
        base, parts, key_used = _resolve_base(item, bases, column_fee_base)
        s = _evaluate(item, base, parts, key_used, attrs, ruleset)
        items.append(s)
        warnings.extend(s["warnings"])

    return {"items": items, "warnings": warnings}


def suggest_one(item_id: str, base=None,
                attrs: dict | None = None,
                ruleset: str = DEFAULT_RULESET) -> dict:
    """单条求值（契约 §1.4）。返回一个 FeeSuggestion。

    该条自身的告警在返回值的 `warnings` 里 —— 本函数不回顶层 warnings 列表，
    只看 `suggested` 会丢掉「未签署 / 闭开性未确认 / 属性回落默认」这些信息。
    `signoff_status` 同时落在顶层与 `basis` 里，UI 读哪一层都看得见「待复核」。

    ⚠ 过签署闸（O-05）：规则集未签署时 `suggested`/`range` 恒为 None。
    """
    one = _suggest_one_ungated(item_id, base, attrs, ruleset)
    return _gate({"items": [one], "warnings": []}, ruleset)["items"][0]


def suggest_all(bases: dict | None = None,
                attrs: dict | None = None,
                ruleset: str = DEFAULT_RULESET) -> dict:
    """全量求值（契约 §1.4）。返回 `{"items": [FeeSuggestion], "warnings": [...]}`。

    `bases` 按**基数名**索引，例如 `{"工程费用": 12000.0, "中标金额": 6000.0}`；
    也接受以 `item_id` 为键做精确覆盖。查不到基数的条目照样出现在 `items` 里
    （`suggested=None` + `fee_base_missing` 告警）—— 少一条比给错一条更危险：
    16 条永远齐全，缺什么一目了然。

    ⚠ 过签署闸（O-05）：规则集未签署时 16 条的 `suggested` 全部为 None，
    结构与依据照出。见本文件「签署闸」段。
    """
    return _gate(_suggest_all_ungated(bases, attrs, ruleset), ruleset)


def required_bases(ruleset: str = DEFAULT_RULESET,
                   attrs: dict | None = None) -> list[dict]:
    """本规则集需要调用方提供哪些计费基数（O-06，契约 §1.4 补齐）。

    为什么必须有这个出口：`bases` 的键此前只活在本模块的 `BASE_KEYS` 常量里，
    调用方（前端/Java）无从知道该传什么、单位是什么。实测后果是前端从不传
    `feeBases`，877 行求值器一次也不会被真实用户触发。

    单位必须一起下发（裁决 3「单位进契约」）：16 条规则的基数混着
    万元 / 万m² / m² / kVA。「总建筑面积(万m²)」与「建筑面积(m²)」名字只差一个字、
    量纲差 10⁴ —— 误传把节能评估费放大 4300 倍且零告警。

    返回每项：{item_id, fee_name, base_key, accepted_keys, unit, base_name,
               target_cell, write_target, optional, satisfied(恒 None，由调用方填)}。
    """
    doc = _load(ruleset)
    attrs = dict(attrs or {})
    out: list[dict] = []
    for item in doc["items"]:
        column_fee_base = None
        cols = item.get("columns")
        if isinstance(cols, dict):
            attr_name = COLUMN_ATTR.get(item["item_id"], "column")
            key = str(attrs.get(attr_name) or attrs.get(f"{item['item_id']}__{attr_name}")
                      or item.get("default_column") or "")
            column_fee_base = (cols.get(key) or {}).get("fee_base")
        cands = _base_candidates(item, column_fee_base)
        # 首选键 = item_id 之后的第一个「基数名」候选（item_id 是精确覆盖键，不是基数名）
        named = [k for k in cands if k != item["item_id"]]
        wt = _write_target(item)
        out.append({
            "item_id": item["item_id"],
            "fee_name": item["fee_name"],
            "base_key": named[0] if named else None,
            "accepted_keys": cands,
            "unit": (item.get("base") or {}).get("unit"),
            "base_name": (item.get("base") or {}).get("name"),
            "target_cell": f"{SHEET}!C{item['fee_row']}" if wt == "input" else None,
            "write_target": wt,
            # manual 项（工程保险费）原表无数值费率，给了基数也不出建议 → 不必强求
            "optional": wt == "manual",
            "satisfied": None,
        })
    return out


# ------------------------------------------------------------------ 计费属性清单
def _attr_options(mapping: dict) -> list[dict]:
    """{key: {...}} → [{value, label}]，保持数据里的顺序。

    label 只从数据里取，**查不到就给 None**，绝不由代码编一个中文名：
    这些键（`01_investment_estimate`、`non_residential`、`user_total`）是费率表
    的原始口径，前端拿 None 会回落显示 value 本身 —— 显示得难看，好过显示一个
    引擎自造、与原表对不上的名字。

    ⚠ 这里**不下发** `raw_text`/`source_cell`。第一版曾把它们当 `source_hint`
    带出来，实测那是一条绕过签署闸的旁路：市政配套费的 raw_text 是
    「住宅：150元/平方米」、高可靠性供电费的是「250」—— 未签署的转录费率，
    而 `required_attrs` 是个静态出口，根本不过 `_gate`。下拉渲染也用不上它。
    """
    out: list[dict] = []
    for key, val in mapping.items():
        val = val if isinstance(val, dict) else {}
        out.append({"value": key, "label": val.get("label")})
    return out


def _attr_specs_of(item: dict) -> list[dict]:
    """一条规则里所有「选错就换一个金额」的受控属性。

    覆盖 `_select_key()` 的全部 5 个调用点（取费列 / variants / matrix 行 /
    市政建筑用途 / 供电计费情形）。只覆盖前 3 个是不够的：漏掉的那两个照样
    静默取默认值算钱，只是没人有机会纠正。
    """
    item_id = item["item_id"]
    fee_name = item.get("fee_name") or item_id
    specs: list[dict] = []

    def _spec(name, label, default, options, note=None):
        specs.append({
            "name": name,
            "label": label,
            "default": default,
            "options": options,
            "item_ids": [item_id],
            # 前端 itemsText 目前 join 的是 item_ids（英文内部码）。中文名一并下发，
            # 界面愿意换过去就是改一行，不用再回引擎要一次。
            "fee_names": [fee_name],
            "note": note,
        })

    # WS10-P03：适用性属性作为受控属性下发，前端下拉自动出现。没有默认值 ——
    # 默认就是「按杭州 / 按生产性算」，那正是要修掉的缺陷，所以 default 恒为 None。
    for rule in item.get("applicability") or []:
        _spec(rule["attr"], rule.get("label") or rule["attr"], None,
              [{"value": o["value"], "label": o.get("label")} for o in rule.get("options") or []],
              rule.get("note"))
        specs[-1]["applicability"] = True

    cols = item.get("columns")
    if isinstance(cols, dict) and cols:
        _spec(COLUMN_ATTR.get(item_id, "column"),
              f"{fee_name}·取费列",
              item.get("default_column") or sorted(cols)[0],
              _attr_options(cols),
              item.get("column_choice_note"))

    attr_req = item.get("attr_required")
    variants = item.get("variants")
    matrix = item.get("matrix")
    if isinstance(attr_req, dict):
        pool = variants if isinstance(variants, dict) and variants else matrix
        if isinstance(pool, dict) and pool:
            _spec(attr_req["name"],
                  attr_req.get("label") or attr_req["name"],
                  attr_req.get("default") or sorted(pool)[0],
                  _attr_options(pool))

    if isinstance(matrix, dict):
        # 市政基础设施配套费：矩阵行里再挂一层 prices（住宅 150 / 非住宅 220）。
        # 按结构判定而不是按 item_id 判定，免得规则集加一条同形状的规则时漏掉。
        prices: dict = {}
        for row in matrix.values():
            if isinstance(row, dict):
                for k, v in (row.get("prices") or {}).items():
                    prices.setdefault(k, v)
        if prices:
            _spec(_MUNICIPAL_USE_ATTR, _MUNICIPAL_USE_LABEL,
                  _MUNICIPAL_USE_DEFAULT, _attr_options(prices),
                  "基数按用途拆分下发时（base_parts）本项不生效，逐用途分别计价")

        sc = item.get("scenario_attr")
        if isinstance(sc, dict):
            scen: dict = {}
            for row in matrix.values():
                if isinstance(row, dict):
                    for k, v in row.items():
                        if isinstance(v, dict) and "value" in v:
                            scen.setdefault(k, v)
            if scen:
                _spec(sc["name"], sc.get("label") or sc["name"],
                      sc.get("default") or sorted(scen)[0], _attr_options(scen))

    return specs


def required_attrs(ruleset: str = DEFAULT_RULESET) -> list[dict]:
    """本规则集需要调用方确认哪些**计费属性**（O-08）。

    为什么必须有这个出口：取费列 / 情形 / 用途这些键（`01_investment_estimate`、
    `report_form`、`non_residential`…）此前只活在规则 JSON 里，调用方无从知道
    该问用户什么、可选值是什么。实测后果是前端一个受控下拉都渲染不出来，
    引擎每次按 `default_column` 算并发一条 `fee_attr_defaulted` —— 而这些选择
    直接换一个金额（住宅 150 vs 非住宅 220 元/m²，差 47%）。

    与 `required_bases()` 同一条纪律：**选项只能来自服务端**。前端抄一份内部
    编码必然与规则数据漂移，漂移的后果是引擎按 `fee_attr_unknown_value`
    回落默认列 —— 金额照出，用户不知道用错了。

    返回每项：{name, label, default, options:[{value,label,source_hint}],
               item_ids, fee_names, note}。

    重名处理：同名属性被多条规则用、而可选值集合不同时，一律降级成
    `{item_id}__{name}` 的**逐条**属性（`_select_key()` 本就接受这种精确覆盖键）；
    合并成一个下拉会让用户在 A 规则的选项里给 B 规则挑值。
    """
    doc = _load(ruleset)
    order: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for item in doc["items"]:
        for spec in _attr_specs_of(item):
            if spec["name"] not in grouped:
                grouped[spec["name"]] = []
                order.append(spec["name"])
            grouped[spec["name"]].append(spec)

    out: list[dict] = []
    for name in order:
        specs = grouped[name]
        values = {tuple(o["value"] for o in s["options"]) for s in specs}
        if len(specs) == 1:
            out.append(specs[0])
        elif len(values) == 1 and len({s["default"] for s in specs}) == 1:
            merged = dict(specs[0])
            merged["item_ids"] = [i for s in specs for i in s["item_ids"]]
            merged["fee_names"] = [n for s in specs for n in s["fee_names"]]
            merged["note"] = next((s["note"] for s in specs if s["note"]), None)
            out.append(merged)
        else:
            for s in specs:
                scoped = dict(s)
                scoped["name"] = f"{s['item_ids'][0]}__{name}"
                scoped["base_attr"] = name
                out.append(scoped)
    return out


# ------------------------------------------------------------------ 汇总项对账（WS10-P11）
#
# 落在公式格上的两项（C6 = SUM(C7:C8)、C9 = SUM(C10:C13)）只出小计参考值，子项由造价员自己拆。
# 此前拆完从不回头对：C10-C13 子项之和 1446.57 是规则小计 451.18 的 3.2 倍，只有一句「须自行拆到
# 子项」。这里只**对账**、只报数：不给剩余额度、不平分、不给子项分配任何金额（铁律 3 / 本模块硬约束 4）。

AGGREGATE_TOLERANCE = 0.20

# 小计规则已含、而子项里又单列的费用（数据注 3：建设管理其他费已含施工阶段全过程造价咨询）
DOUBLE_COUNT_CHILDREN: dict[str, tuple[tuple[int, str], ...]] = {
    "management_other_fee": ((12, "注3：建设管理其他费已含施工阶段全过程造价咨询费用"),),
}


def _num_or_none(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def aggregate_checks(fee_items: list[dict] | None, inputs: dict | None,
                     tolerance: float = AGGREGATE_TOLERANCE) -> tuple[list[dict], list[dict]]:
    """汇总型费率规则与子项对账 → (checks, warnings)。纯函数，suggest 与 compute 共用。

    每条 write_target="aggregate" 且小计参考值存在的规则：
      · 子项全部已填、子项和偏离小计 > tolerance → status=mismatch + 告警 fee_aggregate_mismatch；
      · 子项全部已填、偏离在 tolerance 内      → status=consistent（只进 checks）；
      · 部分已填                              → status=partial（info，只报已填和，不给剩余额度）；
      · 一个都没填                            → 不出（没有可对的东西）。
    另：数据注明小计已含某子项、而该子项又有值 → 告警 fee_possible_double_count。
    """
    vals = {str(k).replace("$", ""): _num_or_none(v) for k, v in (inputs or {}).items()}
    checks: list[dict] = []
    warnings: list[dict] = []
    for item in fee_items or []:
        if item.get("write_target") != "aggregate" or not item.get("aggregate_children"):
            continue
        subtotal = _num_or_none(item.get("suggested"))
        if subtotal is None or subtotal <= 0:
            continue
        item_id = item.get("item_id")
        children = list(item["aggregate_children"])
        filled = {c: vals[c] for c in children if vals.get(c) is not None}
        fee_row = (_index(item.get("ruleset") or DEFAULT_RULESET).get(item_id) or {}).get("fee_row")
        agg_cell = f"{SHEET}!C{fee_row}" if fee_row else None
        base = {"item_id": item_id, "fee_name": item.get("fee_name"), "aggregate_cell": agg_cell,
                "children": children, "subtotal": _round(subtotal),
                "filled_cells": sorted(filled, key=children.index),
                "children_sum": _round(sum(filled.values())) if filled else None}
        if filled and len(filled) == len(children):
            s = sum(filled.values())
            dev = (s - subtotal) / subtotal
            base.update(deviation=round(dev, 6))
            if abs(dev) > tolerance:
                base.update(status="mismatch", level="warn")
                warnings.append(_warn(
                    "fee_aggregate_mismatch",
                    f"{item.get('fee_name')}：子项 {'、'.join(c.split('!', 1)[1] for c in children)} 之和 "
                    f"{_num(s)} 万元，与规则小计参考值 {_num(subtotal)} 万元相差 {dev:+.1%}"
                    f"（阈值 ±{tolerance:.0%}）。请核对子项拆分是否重复计列或漏项；引擎不替你拆分。",
                    agg_cell, item_id))
            else:
                base.update(status="consistent", level="info")
        elif filled:
            base.update(status="partial", level="info",
                        missing_cells=[c for c in children if c not in filled])
        else:
            continue
        checks.append(base)

        for row, why in DOUBLE_COUNT_CHILDREN.get(item_id, ()):
            cell = f"{SHEET}!C{row}"
            v = vals.get(cell)
            if v is not None and v != 0:
                warnings.append(_warn(
                    "fee_possible_double_count",
                    f"{item.get('fee_name')}（{agg_cell}）的规则小计参考值 {_num(subtotal)} 万元，{why}；"
                    f"{cell} 又填了 {_num(v)} 万元，可能重复计列。政府投资项目请核对是否另计结算审核费用。",
                    cell, item_id))
                checks.append({"item_id": item_id, "fee_name": item.get("fee_name"),
                               "aggregate_cell": agg_cell, "status": "possible_double_count",
                               "level": "warn", "cell": cell, "value": _round(v),
                               "subtotal": _round(subtotal), "reason": why})
    return checks, warnings
