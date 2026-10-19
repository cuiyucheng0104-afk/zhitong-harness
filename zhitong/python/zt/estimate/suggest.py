# 来源：engine-service/app/engine/estimate_suggest.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""概算正向推算通道（spec I-2.3）。

    正向：baseline_unit_cost × quantity / 10000  →  suggested_cost   ← 本模块，AI 价值所在
    反向：cost ÷ quantity × 10000               →  unit_cost        ← 原表已有（224 条公式）

没有正向通道，「概算生成」就只是个手填表单：用户得逐格拍 150 个成本数。
本模块把 `concept_indicator_baseline` 的单方指标乘回规模，出**建议值**，
用户逐条接受/覆盖；覆盖后的偏离校核在**前端本地**做（O-22 删掉了服务端那份死代码），
阈值由本模块的 `DEFAULT_TOLERANCE` 单点下发，见每条建议的 `range`。

红线（与 estimate_engine 同源，违者作废）：
- 纯确定性 Python：不调用任何 LLM，金额一分钱都不经过模型（铁律 2）；
- 引擎无状态：不连 MySQL。基准数据由 Java 查库后随请求体下发（阶段 I 接口契约裁决 A），
  本模块只吃入参 `baselines`；
- 严格查表：三条匹配规则全不中就是 `unresolved`，不做模糊匹配、不猜编码（铁律 3）；
- 建议值恒可覆盖（`editable: True`），偏离校核只出 warning。

数量从哪来（确定性反解，不猜）：
模板 224 条 `class=="unit_cost"` 公式形如 `=C7/E7*10000`，分子是成本格、分母是数量格。
解析这 224 条即得 `(成本格 → 数量格)` 映射，实测覆盖全部 150 个 `kind=="cost"` 输入位。
数量值由 `estimate_engine.run()` 求值给出——其中 105 个数量格是跨表引用
（`=经济技术指标!$D$7` 之类），只要填了 11 个根指标就自动有值；另 45 个
（3.专项工程费 42 + 4.室外及配套工程费 3）本身就是数量输入位，无根输入可推导
（`concept_base_metric` 里 127 条 quantity 基数 `root_input_ref` 全 NULL 已实证），
必须用户填，未填则落 `unresolved(reason="no_quantity")`。

WS10-A（issue #722）之后的口径：
- **语义键取代位置键**（P01）：基准行按 `estimate_policy.semantic_keys` 归到语义键，
  同键下的行是同一指标的样本成员，建议单方 = 成员中位数；区间 = 成员 [min, max]，
  单成员时不给区间（不再恒 ±20%）。
- **样本来源 < 3 个 → `reference_only`**（D47）：前端不自动预填，只作逐条采纳的参考。
- **业态不适用的分项不出参考值**（D48）、**包干额不按面积放大**（P02）、
  **费率规则不适用 / 未确认适用性的格两侧都不出值**（P03）。
"""
from __future__ import annotations

import re
import statistics
from typing import Any

from zt.estimate import policy as estimate_policy
from zt.estimate.engine import EstimateTemplateError, load_template, run

# 偏离阈值默认 ±20%。
# ⚠ 这是阶段 I 接口契约设的**占位默认值，未经造价员确认**（契约 §6 遗留项 3）。
# WS10-P01 起**只留给费率侧**：基准侧的 range 改由样本成员的 [min, max] 给出
# （单样本时为 [null, null]），不再按这个常量对称放缩 —— 单样本的 ±20% 是
# 伪造出来的区间，看着像统计结论，其实没有任何样本支撑。
DEFAULT_TOLERANCE = 0.20

# 费率规则侧「适用性」扣留的两种原因（P03）。命中的格**两侧都不预填**：
# 基准侧那个值同样没有回答「这条费用在本项目该不该计」。
APPLICABILITY_REASONS = ("applicability_unconfirmed", "rule_not_applicable")

# 单方指标公式的唯一实证形态（224/224 全命中，两种变体只差数量列 E/F）：
#   =C7/E7*10000   /   =C5/F5*10000
_UNIT_COST_RE = re.compile(r"^=([A-Z]{1,3})(\d+)/([A-Z]{1,3})(\d+)\*10000$")
_COORD_RE = re.compile(r"^([A-Z]{1,3})(\d+)$")

# baselines 行里参与维度过滤的四列（DDL 真实列名）
_DIM_KEYS = ("region", "price_period", "project_type", "structure_type")


def _split(cell: str) -> tuple[str, str, str, int]:
    """"1.建筑工程费!C7" -> (sheet, "C7", "C", 7)"""
    if "!" not in cell:
        raise EstimateTemplateError(f"非法单元格引用（缺 sheet）：{cell}")
    sheet, coord = cell.split("!", 1)
    coord = coord.replace("$", "")
    m = _COORD_RE.match(coord)
    if not m:
        raise EstimateTemplateError(f"非法坐标：{cell}")
    return sheet, coord, m.group(1), int(m.group(2))


def _prev_col(col: str) -> str:
    """数量列左邻即单位列（实测：5 张费用表 D=单位/E=数量，估概算总表 E=单位/F=数量）。"""
    if len(col) == 1 and col > "A":
        return chr(ord(col) - 1)
    return col


def cost_quantity_map(template_code: str = "gsyz_v1") -> dict[str, str]:
    """反解 (成本格 → 数量格)。异常形态直接跳过，由调用方记 warning。"""
    tpl = load_template(template_code)
    out: dict[str, str] = {}
    for f in tpl["formulas"]:
        if f["class"] != "unit_cost":
            continue
        sheet = f["cell"].split("!", 1)[0]
        m = _UNIT_COST_RE.match(f["formula"])
        if not m:
            continue
        out[f"{sheet}!{m.group(1)}{m.group(2)}"] = f"{sheet}!{m.group(3)}{m.group(4)}"
    return out


def _unparsed_unit_cost(template_code: str) -> list[str]:
    tpl = load_template(template_code)
    return [
        f["cell"]
        for f in tpl["formulas"]
        if f["class"] == "unit_cost" and not _UNIT_COST_RE.match(f["formula"])
    ]


def _row_index(tpl: dict) -> dict[tuple[str, int], dict]:
    return {(s["name"], r["row"]): r for s in tpl["sheets"] for r in s["rows"]}


def _sheet_order(tpl: dict) -> dict[str, int]:
    return {s["name"]: i for i, s in enumerate(tpl["sheets"])}


def _dims_ok(row: dict, dims: dict[str, Any] | None) -> bool:
    """维度过滤，NULL 通配。

    首批 224 条种子除 project_type='房屋建筑' 外四维全 NULL——若按等值过滤会全军覆没，
    所以基准行该维为 NULL 一律视为「通用，适用于任何取值」。
    """
    if not dims:
        return True
    for k in _DIM_KEYS:
        want = dims.get(k)
        if want in (None, ""):
            continue
        got = row.get(k)
        if got in (None, ""):
            continue  # 基准未断言该维 → 通配
        if got != want:
            return False
    return True


def _as_float(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _identity(b: dict) -> tuple:
    """样本成员身份 = (来源, 源表, 源行)。同一身份只能有一个单方指标。"""
    return (b.get("source"), b.get("source_sheet"), b.get("source_row"))


def _dims_tuple(b: dict) -> tuple:
    return tuple(b.get(k) for k in _DIM_KEYS)


class _Pool:
    """一个语义键（或 item_code / item_name 回退键）下已去重的样本成员。"""

    def __init__(self, members: list[dict]):
        self.members = members
        costs = [_as_float(m["unit_cost"]) for m in members]
        self.median = float(statistics.median(costs))
        self.lo = min(costs)
        self.hi = max(costs)
        # 审计指针取最接近中位数的一条；并列时按 indicator_code 定序，与行序无关
        self.ref = min(members, key=lambda m: (abs(_as_float(m["unit_cost"]) - self.median),
                                               str(m.get("indicator_code") or "")))
        # 来源未标注（source 为 NULL）的行算作同一个「未标注来源」，不当成多个独立样本
        self.sources = sorted({str(m.get("source")) if m.get("source") else "(未标注来源)"
                               for m in members})

    def evidence(self) -> dict:
        return {
            "n_values": len(self.members),
            "n_sources": len(self.sources),
            "sources": list(self.sources),
            "baseline_refs": sorted(str(m.get("indicator_code") or "") for m in self.members),
        }


def _resolve_pool(rows: list[dict]) -> tuple[_Pool | None, str | None]:
    """同键的基准行 → (样本池, 多义说明)。两条多义判据（spec WS10-P01 修法 2）：

    ① 同一身份（来源+源表+源行）出现不同单方指标 → 多义。这就是此前 cell 级
       撞键的判据：灌了第二个价期 / 地区而 dims 未收窄，DB 又不保证行序，不猜。
    ② 同一语义键下单方指标不同、**且维度元组也不同** → 多义。维度相同的不同单方
       是同一口径下的多个样本（取中位数）；维度不同则说明是不同价期 / 地区混在一起。
    单方相同的重复行按 indicator_code 取小去重，使输出对行序完全不变。
    """
    by_id: dict[tuple, dict] = {}
    for b in rows:
        key = _identity(b)
        prev = by_id.get(key)
        if prev is None:
            by_id[key] = b
            continue
        if _as_float(prev["unit_cost"]) != _as_float(b["unit_cost"]):
            return None, "同一来源同一源格有多条基准且单方指标不一致（通常是灌了第二个价期/地区而 dims 未收窄）"
        if str(b.get("indicator_code") or "") < str(prev.get("indicator_code") or ""):
            by_id[key] = b
    members = sorted(by_id.values(), key=lambda m: str(m.get("indicator_code") or ""))
    if (len({_as_float(m["unit_cost"]) for m in members}) > 1
            and len({_dims_tuple(m) for m in members}) > 1):
        return None, "同一指标下单方指标不一致且维度（地区/价期/类型/结构）不同，不猜"
    return _Pool(members), None


class _SemanticIndex:
    """语义键 → 样本池（WS10-P01）。取代原先按 (source_sheet, source_row) 位置对号的索引。

    查表顺序仍是三级严格全等：语义键（由基准行的源格推出）→ item_code → item_name。
    没有源格的行不进语义键，只走后两级（与原先一致）。
    """

    def __init__(self, baselines: list[dict], dims: dict[str, Any] | None,
                 keys: dict[tuple[str, int], str]):
        self._keys = keys
        self.by_key: dict[str, list[dict]] = {}
        self.by_item_code: dict[str, list[dict]] = {}
        self.by_item_name: dict[str, list[dict]] = {}
        self.dropped_dims = 0
        self.dropped_bad = 0
        for b in baselines or []:
            if not isinstance(b, dict):
                self.dropped_bad += 1
                continue
            if _as_float(b.get("unit_cost")) is None:
                self.dropped_bad += 1
                continue
            if not _dims_ok(b, dims):
                self.dropped_dims += 1
                continue
            sheet, row = b.get("source_sheet"), b.get("source_row")
            if sheet and isinstance(row, int) and not isinstance(row, bool):
                key = keys.get((sheet, row))
                if key is not None:
                    self.by_key.setdefault(key, []).append(b)
            if b.get("item_code"):
                self.by_item_code.setdefault(b["item_code"], []).append(b)
            if b.get("item_name"):
                self.by_item_name.setdefault(b["item_name"], []).append(b)

    def lookup(self, sheet: str, row_no: int, label: str | None, item_code: str | None,
               label_before: str | None = None
               ) -> tuple[_Pool | None, str | None, str | None, str | None]:
        """→ (样本池, match 方式, 落空原因说明, 语义键)。严格查表，无模糊、无编辑距离。

        `label_before`：模板 static 修正（WS10-P14）之前的行名，取自模板自己的 fixes 留痕 ——
        基准库 / 条目库里存的是修正前的原表名（如「海棉城市工程」），按留痕的精确别名再查一次，
        不是模糊匹配。
        """
        skey = self._keys.get((sheet, row_no))
        rows = self.by_key.get(skey) if skey else None
        if rows:
            pool, amb = _resolve_pool(rows)
            if pool is None:
                # 不退到 item_code / item_name：那两级用的是同一批行，换个维度再任选一条仍是猜
                return None, None, f"语义键 {skey} 在基准库内多义（{amb}），不猜", skey
            own = all((m.get("source_sheet"), m.get("source_row")) == (sheet, row_no)
                      for m in pool.members)
            return pool, ("cell" if own else "semantic"), None, skey
        if item_code:
            rows = self.by_item_code.get(item_code)
            if rows:
                pool, amb = _resolve_pool(rows)
                if pool is None:
                    return None, None, f"item_code={item_code} 在基准库内多义（{amb}），不猜", skey
                return pool, "item_code", None, skey
        if label:
            rows = self.by_item_name.get(label) or (
                self.by_item_name.get(label_before) if label_before else None)
            if rows:
                pool, amb = _resolve_pool(rows)
                if pool is None:
                    return None, None, f"item_name={label!r} 在基准库内多义（{amb}），不猜", skey
                return pool, "item_name", None, skey
        return None, None, None, skey


def _static_label_renames(tpl: dict) -> dict[str, str]:
    """模板 static 修正留痕里「行名列」的改动 → {修正后: 修正前}（WS10-P14 的精确别名表）。"""
    out: dict[str, str] = {}
    for fix in tpl.get("fixes") or []:
        if fix.get("kind") != "static":
            continue
        for ch in fix.get("changes") or []:
            coord = str(ch.get("cell", "")).split("!", 1)[-1]
            if coord.startswith("B") and isinstance(ch.get("after"), str) and isinstance(ch.get("before"), str):
                out[ch["after"]] = ch["before"]
    return out


def _name_to_item_code(items: list[dict] | None) -> dict[str, str]:
    """concept_indicator_item 的 item_name → item_code 回链表；重名一律丢弃（严格查表）。"""
    if not items:
        return {}
    seen: dict[str, str | None] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        name, code = it.get("item_name"), it.get("item_code")
        if not name or not code:
            continue
        if name in seen and seen[name] != code:
            seen[name] = None  # 重名指向不同编码 → 作废，绝不二选一
        else:
            seen.setdefault(name, code)
    return {k: v for k, v in seen.items() if v}


def _fee_rules_mod():
    """按需软装载 fee_rules。**引擎不硬依赖它**（它是另一条泳道的产物）。

    走 importlib 而不是 `from app.engine import fee_rules`：后者一旦模块存在就
    绑到包属性上，测试对 sys.modules 的打桩会被整条绕过（O-02 修过同一个坑）。
    """
    import importlib  # noqa: PLC0415

    try:
        return importlib.import_module("zt.estimate.fee_rules")
    except ImportError:
        return None


OTHER_FEE_SHEET = "5.工程建设其他费用"


def _fee_coverage(fee_items: list[dict] | None) -> tuple[set[str], dict[str, dict]]:
    """→ (fee_rules 能覆盖的输入位集合, target_cell → 本次费率建议)。

    fee_rules 缺席时回 (空集, 空表) —— 引擎**不硬依赖**费率泳道，退化成"只有基准
    一个来源"，与它没合入时的行为一致。
    """
    mod = _fee_rules_mod()
    covered: set[str] = set()
    if mod is not None:
        try:
            covered = set(mod.covered_cells())
        except Exception:  # noqa: BLE001 —— 规则集损坏不该把正推算打死
            covered = set()
    by_cell = {}
    for f in fee_items or []:
        cell = f.get("target_cell")
        if cell:
            by_cell[cell] = f
    return covered, by_cell


def _fee_signoff_pending() -> bool | None:
    """费率规则集**当前是否处于未签署态**。→ True/False；问不出来时 None。

    为什么 suggest 要问这个（#132）：签署闸未解时费率侧 16 条恒无金额，13 个双源格
    于是全部回落到基准侧。但 `unavailable_reason` 会被更具体的诊断盖住 ——
    `_withhold()` 明写「已有的不可用原因（no_base / manual_paradigm / …）不覆盖」。
    实测（工程费用=12000，前端真实调法）13 格里 **6 格报的是 `no_base`**：
    C11/C12/C19/C22/C23/C29。造价员照着这条去补「中标金额/建筑面积/受电容量」，
    补齐之后这 6 格的原因才变成 `ruleset_unsigned`，金额**照样是 null**
    —— 一个可执行但无效的指示，比不给指示更糟。

    所以要单独问一次闸的状态，作为 `resolution.signoff_blocking` 交给调用方：
    「补基数没用，先去签规则集」这件事必须在**同一条记录上**说清楚，而不是让人
    自己把顶层那条 `fee_rules_unsigned` 告警和这一格的 `no_base` 对起来。

    问不出来（fee_rules 未接入 / 老版本没有 `is_signed`）回 None，不臆造 False ——
    False 的语义是「已签署」，那是在替一条查不到的事实下结论。
    """
    mod = _fee_rules_mod()
    getter = getattr(mod, "is_signed", None) if mod is not None else None
    if getter is None:
        return None
    try:
        return not bool(getter())
    except Exception:  # noqa: BLE001 —— 规则集损坏不该把正推算打死
        return None


def required_fee_bases(fee_bases: dict | None = None, *,
                       derived_keys=(), derivable_keys=()) -> tuple[list[dict], list[dict]]:
    """→ (required_fee_bases, warnings)。fee_rules 缺席时回 ([], [软降级 warning])。

    为什么这个出口必须存在（O-06）：`bases` 的键名与单位此前只活在
    `fee_rules.BASE_KEYS` 这个 Python 常量里，前端/Java 无从知道该传什么。
    实测后果就是前端 `runSuggest` 从不传 `feeBases`，877 行求值器一次也不会
    被真实用户触发 —— I-2.5「16 项各出建议值」实际 0/16。

    `satisfied` 按本次实际参与求值的基数（用户值与兜底值合并后）逐项判定：前端据此知道
    「还差哪几个基数」，而不是拿到一个空的 fee[] 却不知道为什么空。

    WS10-P07：`derivable` = 这一项的基数能由本表兜底（工程费用 ← 估概算总表!C5），
    留空不算缺口；`derived` = 这一项本次**确实**用的是兜底值（用户没给任何可接受的键）。
    """
    mod = _fee_rules_mod()
    if mod is None:
        return [], [{
            "code": "fee_rules_unavailable",
            "cell": None,
            "message": "费率规则引擎尚未接入（zt.estimate.fee_rules 缺失），"
                       "本次不下发 required_fee_bases；这不代表该项目没有工程建设其他费用",
        }]
    getter = getattr(mod, "required_bases", None)
    if getter is None:
        # 与端点侧 items_unsupported 同一条纪律：并行泳道给的模块版本较老时如实说，
        # 不许 AttributeError 把整个 suggest 打成 500。
        return [], [{
            "code": "fee_bases_spec_unsupported",
            "cell": None,
            "message": "本版 fee_rules 没有 required_bases 出口，"
                       "required_fee_bases 本次不下发（调用方需自行确定基数键与单位）",
        }]
    supplied = fee_bases if isinstance(fee_bases, dict) else {}
    derived = set(derived_keys or ())
    derivable = set(derivable_keys or ())
    specs = []
    for spec in getter():
        s = dict(spec)
        keys = s.get("accepted_keys") or []
        hits = [k for k in keys
                if isinstance(supplied.get(k), (int, float)) and not isinstance(supplied.get(k), bool)]
        s["satisfied"] = bool(hits)
        s["derivable"] = any(k in derivable for k in keys)
        s["derived"] = bool(hits) and all(k in derived for k in hits)
        specs.append(s)
    return specs, []


def required_fee_attrs(fee_attrs: dict | None = None) -> tuple[list[dict], list[dict]]:
    """→ (required_fee_attrs, warnings)。fee_rules 缺席时回 ([], [软降级 warning])。

    为什么这个出口必须存在（O-08）：取费列 / 情形 / 用途这三类选择直接换一个金额
    （住宅 150 vs 非住宅 220 元/m²，差 47%），可选值却只活在规则 JSON 里。
    调用方拿不到清单就渲染不出受控下拉 —— 实测后果是引擎每次按默认列算并发
    `fee_attr_defaulted`，而造价员**根本没有机会纠正**。

    `satisfied` 按本次实际传入的 `fee_attrs` 逐项判定（认 `name` 与
    `{item_id}__{name}` 两种键，与 `fee_rules._select_key()` 同口径）：
    前端据此知道「还差哪几个属性没确认」，而不是看着一堆 defaulted 告警猜。
    """
    mod = _fee_rules_mod()
    if mod is None:
        return [], [{
            "code": "fee_rules_unavailable",
            "cell": None,
            "message": "费率规则引擎尚未接入（zt.estimate.fee_rules 缺失），"
                       "本次不下发 required_fee_attrs；受控下拉将无从渲染",
        }]
    getter = getattr(mod, "required_attrs", None)
    if getter is None:
        # 与 required_fee_bases 同一条纪律：并行泳道给的模块版本较老时如实说，
        # 不许 AttributeError 把整个 suggest 打成 500。
        return [], [{
            "code": "fee_attrs_spec_unsupported",
            "cell": None,
            "message": "本版 fee_rules 没有 required_attrs 出口，"
                       "required_fee_attrs 本次不下发（受控下拉无从渲染，"
                       "引擎将按默认值计算并逐条发 fee_attr_defaulted）",
        }]
    supplied = fee_attrs if isinstance(fee_attrs, dict) else {}
    specs = []
    for spec in getter():
        s = dict(spec)
        name = s.get("base_attr") or s.get("name")
        s["satisfied"] = any(
            supplied.get(k) is not None
            for k in ({name} | {f"{i}__{name}" for i in (s.get("item_ids") or [])} | {s.get("name")})
        )
        specs.append(s)
    return specs, []


def suggest(
    inputs: dict[str, float],
    baselines: list[dict],
    fee_items: list[dict] | None = None,
    template_code: str = "gsyz_v1",
    dims: dict[str, str | None] | None = None,
    *,
    items: list[dict] | None = None,
    fee_bases: dict | None = None,
    fee_attrs: dict | None = None,
    fee_bases_derived: list[str] | None = None,
    fee_bases_derivable: list[str] | None = None,
    policy: dict | None = None,
) -> dict:
    """正向推算：规模 × 基准 → 各成本输入位的建议金额。

    inputs      向导第 2 步已确认的规模输入（至少 11 个根输入位）；键形如 "经济技术指标!D4"。
    baselines   Java 从 concept_indicator_baseline 查出并下发的行（裁决 A，引擎不连库）。
    fee_items   可选，fee_rules 引擎产出的 FeeSuggestion 列表，原样并进结果 `fee` 段。
    dims        {region, price_period, project_type, structure_type, building_function}。
                前四维参与基准行过滤（基准行该维为 NULL 时通配）；building_function（业态）
                只供策略使用（WS10-P01 / D48），不参与过滤。
    items       可选，concept_indicator_item 行；仅用于 item_code 回链。
    fee_bases   可选，本次实际传给费率引擎的计费基数（用户值与兜底值合并后，P07）；
                **只用于给 `required_fee_bases` 标 `satisfied`**，本函数不拿它算任何金额。
    fee_bases_derived / fee_bases_derivable
                可选，哪些基数键本次取自兜底 / 能由本表兜底（给 required_fee_bases 标
                derived / derivable）。
    fee_attrs   可选，调用方本次传给费率引擎的计费属性；同上，**只用于给
                `required_fee_attrs` 标 `satisfied`**，本函数不拿它选任何取费列。
    policy      可选，替换模板策略（只给测试用：把 lump_sum 格临时改成可缩放，
                让双源仲裁这条保留分支仍然可达）。端点不暴露这个参数。

    返回 {suggestions, unresolved, fee, coverage, totals, required_fee_bases,
          required_fee_attrs, warnings}，详见阶段 I 接口契约 §1.2。
    """
    tpl = load_template(template_code)
    pol = estimate_policy.load_policy(template_code) if policy is None else policy
    warnings: list[dict] = []

    # 数量列的派生值：105 个数量格是跨表引用，必须先跑一遍求值器才拿得到。
    computed = run(inputs or {}, template_code)
    # 只透传 unknown_input——本函数是纯查询，div_by_zero/template_fix 属 compute 端的
    # 披露职责，且未填数量时会刷出上百条 div_by_zero 噪声，淹没真正有用的信息。
    warnings.extend(w for w in computed["warnings"] if w["code"] == "unknown_input")

    for bad in _unparsed_unit_cost(template_code):
        warnings.append({
            "code": "unit_cost_unparsed",
            "cell": bad,
            "message": "单方指标公式不是 =Cn/En*10000 形态，无法反解数量格，该行不出建议",
        })

    c2q = cost_quantity_map(template_code)
    rows = _row_index(tpl)
    order = _sheet_order(tpl)
    keys = estimate_policy.semantic_keys(template_code, pol)
    idx = _SemanticIndex(baselines, dims, keys)
    name2code = _name_to_item_code(items)
    renamed = _static_label_renames(tpl)
    fee_covered, fee_by_cell = _fee_coverage(fee_items)
    # 整次请求问一次就够（#132）：闸的状态是规则集属性，不随格子变
    fee_signoff_pending = _fee_signoff_pending()
    min_sources = estimate_policy.min_sources_for_prefill(pol)
    lump_sum = estimate_policy.lump_sum_cells(pol)
    building_function = (dims or {}).get("building_function") or None
    bf_label = estimate_policy.building_function_label(pol, building_function)

    declared = {i["cell"] for i in tpl["inputs"]}
    cost_cells = [i["cell"] for i in tpl["inputs"] if i["kind"] == "cost"]
    cost_cells.sort(key=lambda c: (order.get(_split(c)[0], 99), _split(c)[3]))

    suggestions: list[dict] = []
    unresolved: list[dict] = []
    by_sheet: dict[str, dict[str, int]] = {}

    for cell in cost_cells:
        sheet, _coord, _col, row_no = _split(cell)
        stat = by_sheet.setdefault(sheet, {"cost_inputs": 0, "suggested": 0, "unresolved": 0})
        stat["cost_inputs"] += 1

        trow = rows.get((sheet, row_no)) or {}
        label = trow.get("label")
        qcell = c2q.get(cell)
        qty: float | None = None
        qty_is_input = False
        unit = None
        if qcell:
            qsheet, qcoord, qcol, _qrow = _split(qcell)
            qty = _as_float(computed["sheets"].get(qsheet, {}).get(qcoord))
            qty_is_input = qcell in declared
            unit = (trow.get("static") or {}).get(_prev_col(qcol))

        def _drop(reason: str, detail: str, **extra) -> None:
            stat["unresolved"] += 1
            unresolved.append({
                "cell": cell,
                "label": label,
                "reason": reason,
                "detail": detail,
                "quantity_cell": qcell,
                "quantity_is_input": qty_is_input,
                "semantic_key": keys.get((sheet, row_no)),
                **extra,
            })

        # ---- P03：费率规则判了「不适用 / 适用性未确认」的格，两侧都不出值 ----
        # 放在最前：基准侧那个值同样没回答「这条费用本项目该不该计」，
        # 用它顶上就是把「杭州标准套义乌」换成「样本包干额套义乌」。
        fee_here = fee_by_cell.get(cell) or {}
        fee_block = fee_here.get("unavailable_reason")
        if cell in fee_covered and fee_block in APPLICABILITY_REASONS:
            _drop(fee_block,
                  _applicability_detail(fee_here),
                  covered_by_fee_rule=True)
            continue

        # ---- P01 / D48：业态上通常不含的分项不出参考值 ----
        if estimate_policy.not_typical_for(pol, building_function, sheet, label):
            _drop("not_applicable_for_use",
                  f"业态「{bf_label or building_function}」通常不含「{label}」，本格不出参考值"
                  "（初始口径，待造价员确认）；本项目确有这一项时直接填实际值")
            continue

        # ---- P02：样本包干额不按面积放大 ----
        # 这些格在种子里的「单方指标」是样本包干额 ÷ 样本总建筑面积（17 万㎡），
        # 乘本项目面积得到的是一个与本项目无关的数（建设用地费实测虚高 70%）。
        if cell in lump_sum:
            hint = lump_sum[cell]
            if cell in fee_covered:
                _drop("baseline_not_scalable",
                      "本格在样本里是包干额，不按面积推算；建议值见费率规则（响应体 fee[]）"
                      + (f"。无费率建议时：{hint}" if hint else ""),
                      covered_by_fee_rule=True)
            else:
                _drop("manual_required",
                      hint or "本格在样本里是包干额，不按面积推算，须人工填报",
                      covered_by_fee_rule=False)
            continue

        before = renamed.get(label or "")
        pool, match, amb, skey = idx.lookup(
            sheet, row_no, label, name2code.get(label or "") or name2code.get(before or ""), before)
        if pool is None:
            # 其他费表专属分流（O-07，契约点名的 no_rule）：这张表的输入位有**两个**
            # 可能的来源，基准库与费率规则。两个都没有才是"这一格谁也管不了"，
            # 才配叫 no_rule；只是基准库没有、费率规则覆盖着，那是"来源不同"不是"没来源"。
            # ⚠ WS10-P02 之后 gsyz_v1 的 5 表 23 格全是 lump_sum，**真策略下走不到这里**；
            # 保留给「将来可缩放的多样本」，由 with_scaling() 覆盖策略的测试钉住。
            if sheet == OTHER_FEE_SHEET and cell not in fee_covered:
                _drop("no_rule",
                      (amb or "指标基准库无对应行（三级严格查表均未命中）")
                      + "；费率规则集也未覆盖本格 —— 两个来源都没有，须人工填报",
                      covered_by_fee_rule=False)
            elif sheet == OTHER_FEE_SHEET:
                _drop("no_baseline",
                      (amb or "指标基准库无对应行（三级严格查表均未命中）")
                      + "；但本格由费率规则覆盖，建议值见响应体 fee[]（前端第 6 组）",
                      covered_by_fee_rule=True)
            else:
                _drop("no_baseline", amb or "指标基准库无对应行（按 语义键→item_code→item_name 三级严格查表，均未命中）")
            continue
        if qcell is None:
            _drop("no_quantity", "模板无该成本格的单方指标公式，数量格无法反解")
            continue
        if qty is None:
            _drop("no_quantity",
                  f"数量格 {qcell} 无值" + ("（该格本身是数量输入位，需用户填报）" if qty_is_input
                                            else "（数量由上游公式推导，检查根输入是否齐全）"))
            continue
        if qty == 0:
            _drop("quantity_zero", f"数量格 {qcell} 为 0，单方指标乘不出金额")
            continue

        unit_cost = round(pool.median, 4)
        suggested = round(unit_cost * qty / 10000.0, 4)
        evidence = pool.evidence()
        single = evidence["n_values"] < 2
        stat["suggested"] += 1
        base = pool.ref
        item = {
            "cell": cell,
            "label": label,
            "unit": unit or base.get("unit"),
            "quantity_cell": qcell,
            "quantity": qty,
            "unit_cost": unit_cost,
            "suggested_cost": suggested,
            "match": match,
            "semantic_key": skey,
            "baseline_ref": base.get("indicator_code"),
            # 单成员没有区间：±20% 是凭空造的区间，看着像统计结论（WS10-P01）
            "range": ([None, None] if single else
                      [round(pool.lo * qty / 10000.0, 2), round(pool.hi * qty / 10000.0, 2)]),
            "range_basis": "single_value" if single else "sample_min_max",
            "evidence": evidence,
            # D47：来源不足 3 个时只作参考，前端不自动预填
            "reference_only": evidence["n_sources"] < min_sources,
            "editable": True,
            "source": "baseline",
            "conflict": False,
        }

        # #129：命中基准行的未断言维度（NULL 当通配）。首批 224 条种子
        # region/price_period/structure_type 三维全 NULL——匹配是「通配」不是「适配」，
        # 建议值没有区分地区/价期/结构。不披露，造价员拿到的可能是不知哪个价期
        # 反推的单价且零提示；披露了才知道该核对适用性。
        unasserted = [k for k in _DIM_KEYS if base.get(k) in (None, "")]
        if unasserted:
            item["dims_unasserted"] = unasserted

        # ---- 双源冲突并列披露（O-07 / 裁决 3）----
        # 其他费表的 13 个格**两个来源各出一套值**：基准库（本次这条，从原表 F 列
        # 单方指标反推）与费率规则（浙价服〔2009〕84号 等有文号可追溯的费率）。
        # 实测两者可差 4.8 倍。此前谁生效取决于前端 forEach 的先后顺序 —— 那是
        # 让渲染顺序仲裁金额，最不该由代码默默决定的一类事。
        #
        # 落地形态：不删任何一侧，引擎把两个值**并列**交出来，由造价员二选一。
        # preferred_source 按裁决 3 取 fee_rules（有文号可追溯；baseline 那 23 行
        # 是从同一张原表反推的单方指标，溯源较弱），但 preferred_available 如实
        # 反映费率侧这次到底有没有数（签署闸未解时它恒为 None）。
        # ⚠ WS10-P02 之后真策略下 5 表全是 lump_sum，本段只在策略把它们改成可缩放时可达。
        if cell in fee_covered:
            fee = fee_by_cell.get(cell) or {}
            alt_amount = fee.get("suggested")
            unavailable = (fee.get("unavailable_reason")
                           or (None if fee else "fee_not_evaluated"))
            item["conflict"] = True
            item["alternative"] = {
                "source": "fee_rules",
                "item_id": fee.get("item_id"),
                "fee_name": fee.get("fee_name"),
                "suggested_cost": alt_amount,
                "range": fee.get("range") or [None, None],
                "basis": fee.get("basis"),
                "signoff_status": fee.get("signoff_status"),
                "unavailable_reason": unavailable,
            }
            item["preferred_source"] = "fee_rules"
            item["preferred_available"] = alt_amount is not None

            # ---- 「这一格本次到底用了哪一侧」是**字段**，不是让调用方自己推（#132）----
            #
            # 修之前调用方要把四个键 join 起来才知道结论：`source`（顶层金额的出处，
            # 恒 "baseline"）+ `preferred_source` + `preferred_available` +
            # `alternative.suggested_cost`。少读一个就会把「已回落到基准侧」读成
            # 「按裁决 3 取了费率侧」—— 这正是 #132 说的「归属裁决被静默翻转到基准侧」。
            # 前端只消费不再复刻。**不删任何一侧**，两侧的值仍原样并列。
            fee_ok = alt_amount is not None
            item["resolution"] = {
                "used_source": "fee_rules" if fee_ok else "baseline",
                "used_cost": alt_amount if fee_ok else suggested,
                # 首选侧（裁决 3 = 费率侧）没出数，只能拿另一侧顶上 —— 界面必须标
                "is_fallback": not fee_ok,
                "preferred_source": "fee_rules",
                "unavailable_reason": None if fee_ok else unavailable,
                # 🔴 补基数有没有用。见 `_fee_signoff_pending()` 的注释：13 格里 6 格
                # 报的是 no_base，把「规则集没签」整个盖住了。None = 问不出来，不猜。
                "signoff_blocking": None if fee_ok else fee_signoff_pending,
            }

            if alt_amount is None:
                why = ("本次请求没带 fee_bases、费率引擎未运行"
                       if not fee else
                       f"费率侧本次未出数（{unavailable}）")
                # 未签署时把「补基数也没用」写进正文：no_base 这类更具体的诊断会把
                # 签署闸盖住，只看这一格的人会以为补个基数就能出费率侧的值。
                gate = ("；且费率规则集尚未经造价员签署，**补齐计费基数本次也不会出值**，"
                        "解闸方式见顶层 fee_rules_unsigned 告警" if fee_signoff_pending else "")
                detail = (f"费率侧暂无可用数值（{why}{gate}），"
                          f"本次**展示与预填的是基准侧值 {suggested} 万元**，非费率侧。")
            else:
                ratio = (f"，相差 {abs(alt_amount - suggested) / suggested:.1%}"
                         if suggested else "")
                detail = (f"费率侧 {alt_amount} 万元 / 基准侧 {suggested} 万元{ratio}。"
                          f"默认取费率侧（有文号可追溯），请造价员确认。")
            warnings.append({
                "code": "fee_cell_dual_source",
                "cell": cell,
                "message": (f"{label or cell}：基准库与费率规则**各出一套建议值**，"
                            f"两者口径不同，不可相加。{detail}"),
            })

        suggestions.append(item)

    # #129：维度未断言的聚合披露（逐格明细在 suggestions[].dims_unasserted）。
    # 出一条聚合而不是每格一条：首批种子三维全 NULL 会让每条建议都带一遍，
    # 上百条同文告警只会把真正要读的 warning 淹掉。
    dims_unasserted_cells = [s["cell"] for s in suggestions if s.get("dims_unasserted")]
    if dims_unasserted_cells:
        warnings.append({
            "code": "baseline_dims_unasserted",
            "cell": None,
            "message": (
                f"{len(dims_unasserted_cells)}/{len(suggestions)} 条建议命中的基准行存在"
                "未断言维度（region/price_period/structure_type 为 NULL，按通配匹配）——"
                "建议值未区分地区/价期/结构类型，请核对对本项目的适用性；"
                "根治需给基准库补维度数据（首批 224 条种子三维全 NULL）。"
            ),
        })

    # D47：样本来源不足时整次推算只作参考（逐格明细在 suggestions[].reference_only）
    reference_cells = [s["cell"] for s in suggestions if s.get("reference_only")]
    if reference_cells:
        warnings.append({
            "code": "baseline_single_sample",
            "cell": None,
            "message": (
                f"{len(reference_cells)}/{len(suggestions)} 条建议的基准样本来源少于 "
                f"{min_sources} 个（本租户基准库目前只来自单一样本工作簿），这些值只作"
                "「单样本参考」：不会自动预填，请逐条或按组确认后采纳。"
            ),
        })

    # P01：没给业态时不能判断「仓储项目套幕墙 / 精装修」这类不适用分项，必须说出来
    if pol.get("building_functions") and not building_function:
        warnings.append({
            "code": "building_use_unconfirmed",
            "cell": None,
            "message": ("未确认项目业态（住宅 / 办公 / 仓储物流 / 工业厂房 …），"
                        "本次按「全部分项都可能有」出参考值；仓储、工业项目通常不含幕墙与精装修，"
                        "请在第 3 步「项目画像」里选择业态后重新推算。"),
        })

    if idx.dropped_bad:
        warnings.append({
            "code": "baseline_row_invalid",
            "cell": None,
            "message": f"{idx.dropped_bad} 条基准行缺少可用的 unit_cost（或不是对象），已忽略",
        })

    # 二段式时序的出口（O-06 / 裁决 3）。16 条费率规则里 7 条以「工程费用」=
    # 估概算总表!C5 为基数，而 C5 正是本步在填的合计 —— 契约从没定义这个顺序，
    # 是契约的缺陷。这里把本次 run 的合计原样带出（run 上面已经跑过一遍，零额外成本），
    # 调用方第 3 步成本位收敛后就能拿它当 fee_bases 再调一次，不必自己重算。
    req_bases, req_warnings = required_fee_bases(
        fee_bases, derived_keys=fee_bases_derived or (),
        derivable_keys=fee_bases_derivable or ())
    warnings.extend(req_warnings)
    # 受控下拉的清单（O-08）。没有它前端连「该问用户什么」都不知道，
    # 只能让引擎按默认取费列算钱 —— 那些默认值直接换一个金额。
    req_attrs, attr_warnings = required_fee_attrs(fee_attrs)
    warnings.extend(attr_warnings)

    total = len(cost_cells)
    return {
        "suggestions": suggestions,
        "unresolved": unresolved,
        "fee": list(fee_items or []),
        "totals": computed["totals"],
        "required_fee_bases": req_bases,
        "required_fee_attrs": req_attrs,
        "coverage": {
            "cost_inputs": total,
            "suggested": len(suggestions),
            "unresolved": len(unresolved),
            "rate": round(len(suggestions) / total, 4) if total else 0.0,
            # D47：出了建议但只作参考（不自动预填）的条数
            "reference_only": len(reference_cells),
            "by_sheet": by_sheet,  # 契约 §1.2 之外的增量键：前端按费用表分组时直接可用
        },
        "warnings": warnings,
    }


def _applicability_detail(fee: dict) -> str:
    """费率规则适用性扣留的一句话说明（P03）。正文取自该条自己的告警，不另编。"""
    name = fee.get("fee_name") or fee.get("item_id") or "该费用"
    for w in fee.get("warnings") or []:
        if w.get("code") in ("fee_applicability_unconfirmed", "fee_rule_not_applicable"):
            return w.get("message") or name
    if fee.get("unavailable_reason") == "rule_not_applicable":
        return f"{name}：费率规则不适用于本项目，按当地文件人工填报"
    return f"{name}：费率规则的适用条件未确认，本项暂不出建议值"


# ⚠ `check_deviation()` 已删除（O-22）。
#
# 它算的是「用户覆盖建议值后偏离基准多少」。删的理由不是它写错了，而是这份实现
# **从 Java 到前端全程无调用方**（实测 grep 零命中），而前端 `estimateModel.ts`
# 里另有一份本地实现在真的跑。两份会漂移的实现 + 其中一份没人调，是最差的形态。
#
# 前端本地算的理由成立：偏离率随用户改一个数就变，走后端等于改一格回一次网络，
# 150 个成本位填下来会等到用户放弃。
#
# 阈值不跟着删：`DEFAULT_TOLERANCE` 仍是**单一真源**，经 suggest 的每条
# `range`（[suggested×(1−t), suggested×(1+t)]）与 EstimateSuggestOut.tolerance
# 下发给前端，前端不重复硬编码 0.20。
