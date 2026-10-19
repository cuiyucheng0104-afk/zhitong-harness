# 来源：engine-service/app/engine/estimate_checks.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""概算计算段的非阻断检查与入参校验（WS25-b，issue #945）。

从 `app/api/estimate.py` **原样挪出**（函数体、告警文案一字未改），供两处共用：
  · `POST /engine/estimate/compute`（概算向导第 5 步出表）；
  · `POST /engine/reportform/render`（报表管理按渲染上下文出表，WS25-b）。
同一份判断只活在一处 —— 另写一套就会成为概算向导之外的第二个出表入口，口径迟早漂移
（spec WS25 §3.4「不采用」表）。四道**拦截**闸在 `estimate_gates`，这里只放：

  · 告警：成本位覆盖率（O-11）、可选位未填（optional_input_missing）、比值标度（O-10）、
          土地费 / 占地（P02 / P08）
  · 费率：计费基数兜底与合并（P07，suggest 也用）、compute 的费率重跑（P06）、汇总费率对账
  · 入参校验：面积对账三件套（P05）与交付表上下文五件套（P06）—— 非法抛 ValueError，
          由端点转成 422（文案原样作 detail，与挪动前逐字相同，见 tests/test_estimate_gates_refactor.py）

纯函数、零 LLM、不连库（铁律 2、铁律 4）。fee_rules 一律经 importlib 装载（O-02 纪律，见各函数注释）。
"""
from __future__ import annotations

import importlib
import re
from functools import lru_cache

from zt.estimate import policy as estimate_policy
from zt.estimate import quality as estimate_quality
from zt.estimate.engine import RATIO_UNITS, EstimateTemplateError, column_units, load_template
from zt.estimate.engine import _compiled as _compiled_template, _refs_of
from zt.estimate.engine import run as estimate_run

# ------------------------------------------------------------------ 成本位覆盖率（O-11）

@lru_cache(maxsize=4)
def cost_input_cells(template_code: str) -> tuple[tuple[str, str], ...]:
    """(sheet, cell) 形态的成本输入位清单（实测 gsyz_v1 有 150 个）。"""
    tpl = load_template(template_code)
    return tuple((i["cell"].split("!", 1)[0], i["cell"])
                 for i in tpl["inputs"] if i["kind"] == "cost")


def input_coverage(template_code: str, supplied: set[str]) -> tuple[dict, list[dict]]:
    """成本位覆盖率披露（O-11）→ (input_coverage, warnings)。

    为什么必须有：全零闸只挡「一个成本位都没填」。填 1/150 照样过闸，端点 200，
    Java 落一条 state=done 的任务，造价员拿到一份七项合计**齐全**、看着像算完了的
    概算表——那是「误导性成功」的另一种形态，只是发生在 compute 而不是 extract。
    闸解决"全没算却报成功"，本函数解决"只算了一点点却看不出来"。

    只出数据与 warning，**不新增任何拦截**：概算本来就允许分批填、允许某些表为空
    （不是所有项目都有专项工程）。判断「够不够」是造价员的事，引擎的责任是把
    完成度如实说出来。
    """
    cells = cost_input_cells(template_code)
    by_sheet: dict[str, dict[str, int]] = {}
    filled = 0
    for sheet, cell in cells:
        stat = by_sheet.setdefault(sheet, {"cost_inputs": 0, "filled": 0, "missing": 0})
        stat["cost_inputs"] += 1
        if cell in supplied:
            stat["filled"] += 1
            filled += 1
        else:
            stat["missing"] += 1
    total = len(cells)
    rate = round(filled / total, 4) if total else 0.0
    coverage = {"cost_inputs": total, "filled": filled, "missing": total - filled,
                "rate": rate, "by_sheet": by_sheet}
    if rate >= 1.0:
        return coverage, []
    worst = sorted(by_sheet.items(), key=lambda kv: (-kv[1]["missing"], kv[0]))
    gaps = "；".join(f"{name} 缺 {s['missing']}/{s['cost_inputs']}"
                     for name, s in worst if s["missing"])
    return coverage, [{
        "code": "cost_input_incomplete",
        "cell": None,
        "message": (f"150 个成本输入位只填了 {filled} 个（{rate:.1%}）；未填的按 Excel"
                    f"「空格 = 0」参与求值，合计因此偏低。缺口分布：{gaps}。"
                    f"可调 POST /engine/estimate/suggest 用指标基准推算建议值，"
                    f"逐条确认后再生成。"),
    }]


# --------------------------------------------------------- 可选输入位的元数据与影响面
#
# 背景（对抗复核确认的缺陷）：模板 4 个 optional_inputs（估概算总表 C48/C49/D48/D49）
# 不填时按 Excel 空格语义 = 0 参与求值，C50 `=C47+C48+C49` 照样算得出数、不报错、
# 不出任何 warning —— 「建设动态总投资（七）」于是**恒等于**「建设静态总投资（四）」。
# 对造价员这不是"缺失提示"，是一个静默的错误合计，比报错危险。
#
# 这里做两件事，两件都由模板实测驱动、不硬编码格号：
#   1. `optional_input_impact` 反查「哪些公式格会被某个未填的可选位静默污染」，
#      compute 端点据此出 `optional_input_missing` warning（把静默变响亮）；
#   2. `optional_input_specs` 把 label/unit 补齐 —— 模板 `inputs`(211) 里**不含**
#      这 4 个位（实测 `cell in inputs == False` ×4），原实现 setdefault 出来的是
#      label=None/unit=None，前端拿到 4 个光秃秃的格号，渲染不出录入控件。

_COORD_RE = re.compile(r"^([A-Z]{1,3})(\d+)$")

# --------------------------------------------------------- 输入位的存储标度（O-10）
#
# 「列头写的单位」不等于「单元格里存的标度」。实测 估概算总表 D 列：列头写
# 「占总投资比例（%）」，而同列 D45/D46/D47 全是 `=Cn/C50`，算出来是 0.99494… 的
# **小数**（0.00% 是 Excel 的显示格式，不是存储标度），且 `D50=D47+D48+D49`。
# 用户照列头把 D48 填成 3（想表达 3%）→ D50 从 1.04 变成 5.99（599%），
# 端点 200、零 warning、零拦截（对抗复核第 2 轮实测，见 tests/test_estimate_api.py）。
#
# 此前这 100 倍换算全靠前端对 `unit` 做 `=== "%"` 的**推断**在守（estimateModel.ts
# 的 isPercentScaleSpec 里写着「引擎给了 value_scale 就按引擎的」，而引擎从来没给）。
# 这里把推断换成事实：判据与 `unit` 同一处推导（列头量纲），**不按格号硬编码** ——
# 硬编码换一个模板就静默失效，失效的表现是数字差 100 倍且没有任何提示。
VALUE_SCALE_FRACTION = "fraction"   # 存小数：界面按百分数录入、下发前 ÷100
VALUE_SCALE_ABSOLUTE = "absolute"   # 存原值：录入什么下发什么


def split_cell(cell: str) -> tuple[str, str, int]:
    """"估概算总表!C48" -> ("估概算总表", "C", 48)"""
    sheet, coord = cell.split("!", 1)
    m = _COORD_RE.match(coord.replace("$", ""))
    if not m:
        raise EstimateTemplateError(f"非法坐标：{cell}")
    return sheet, m.group(1), int(m.group(2))


@lru_cache(maxsize=4)
def optional_input_impact(template_code: str) -> dict[str, tuple[str, ...]]:
    """可选输入位 → 引用了它的公式格（升序去重）。

    用求值器已编译的 AST 反查，因此和真实求值行为同源。注意 `_compiled` 的 ast 里
    **不含费率格**（其公式随 rates 运行期编译）；实测费率格 C46 `=(C5+C45)*rate`
    不引用任何可选位，故此处不受影响。
    """
    comp = _compiled_template(template_code)
    optional = list(comp["tpl"].get("optional_inputs", []))
    want = {tuple(c.split("!", 1)): c for c in optional}
    impact: dict[str, set[str]] = {c: set() for c in optional}
    for cell, node in comp["ast"].items():
        for ref in _refs_of(node):
            hit = want.get(ref)
            if hit is not None:
                impact[hit].add(f"{cell[0]}!{cell[1]}")
    return {c: tuple(sorted(impact[c])) for c in optional}


def column_labels(sheet: dict) -> dict[str, str | None]:
    """列头原文（去掉换行与尾随空格），给前端做输入框的列名。"""
    out: dict[str, str | None] = {}
    for r in sheet.get("rows", []):
        if r.get("role") != "header":
            continue
        for col, text in (r.get("static") or {}).items():
            if col in out or not isinstance(text, str):
                continue
            out[col] = " ".join(text.split()) or None
    return out


@lru_cache(maxsize=4)
def input_value_scales(template_code: str) -> dict[str, str]:
    """每个**已声明输入位**（必填 211 + 可选 4）的存储标度（见上面 O-10 那段头注）。

    覆盖必填位而不只覆盖 4 个可选位：今天 gsyz_v1 的 211 个必填位里一个比值列都没有
    （实测），但判据是从列头量纲推的，换个模板就可能有 —— 那时哨兵得跟着覆盖到，
    不能靠"当初只有可选位是比值"这个偶然。
    """
    tpl = load_template(template_code)
    units = {s["name"]: column_units(s) for s in tpl["sheets"]}
    cells = [i["cell"] for i in tpl.get("inputs", [])]
    cells += list(tpl.get("optional_inputs", []))
    out: dict[str, str] = {}
    for cell in cells:
        sheet_name, col, _row = split_cell(cell)
        unit = ((units.get(sheet_name) or {}).get(col) or "").strip()
        out[cell] = VALUE_SCALE_FRACTION if unit in RATIO_UNITS else VALUE_SCALE_ABSOLUTE
    return out


@lru_cache(maxsize=4)
def optional_input_specs(template_code: str) -> tuple[dict, ...]:
    """4 个可选输入位的完整录入元数据 —— 前端向导据此渲染控件。

    label 取自行树（估概算总表 行 48 label=「建设期融资费用」、行 49=「铺底流动资金」），
    unit/column_label 取自该表的表头行，`affects` 是不填就会被静默污染的合计格。
    """
    tpl = load_template(template_code)
    sheets = {s["name"]: s for s in tpl["sheets"]}
    rows = {(s["name"], r["row"]): r for s in tpl["sheets"] for r in s["rows"]}
    impact = optional_input_impact(template_code)
    scales = input_value_scales(template_code)

    def _label_of(cell: str) -> str | None:
        sh, _col, rn = split_cell(cell)
        return (rows.get((sh, rn)) or {}).get("label") or None

    specs: list[dict] = []
    for cell in tpl.get("optional_inputs", []):
        sheet_name, col, row_no = split_cell(cell)
        sheet = sheets.get(sheet_name, {})
        r = rows.get((sheet_name, row_no), {})
        affects = impact.get(cell, ())
        specs.append({
            "cell": cell,
            "sheet": sheet_name,
            "col": col,
            "row": row_no,
            "seq": r.get("seq"),               # varchar，禁止当数字用（1.10 塌缩）
            "label": r.get("label"),
            "column_label": column_labels(sheet).get(col),
            "unit": column_units(sheet).get(col),
            # 存储标度（O-10）：unit 是**列头怎么写的**，value_scale 是**格子里存什么**。
            # D48/D49 两者不一致（列头 %、格里存小数），前端据此决定要不要 ÷100。
            "value_scale": scales.get(cell, VALUE_SCALE_ABSOLUTE),
            "kind": None,                      # 不在 inputs(211) 里，模板未声明 cost/quantity
            "optional": True,
            # 不填就会被静默按 0 计入的公式格（含其行名，前端可直接用于提示文案）
            "affects": [{"cell": c, "label": _label_of(c)} for c in affects],
        })
    return tuple(specs)


def missing_optional_warnings(template_code: str, supplied: set[str]) -> list[dict]:
    """未填的可选输入位 → `optional_input_missing` warning（不阻断，只披露）。

    只对**确有下游引用**的可选位出 warning：没有任何公式引用它，不填就没有静默后果。
    """
    out: list[dict] = []
    for spec in optional_input_specs(template_code):
        cell = spec["cell"]
        if cell in supplied or not spec["affects"]:
            continue
        affected = "、".join(
            f"{a['label']}[{a['cell']}]" if a["label"] else a["cell"]
            for a in spec["affects"]
        )
        out.append({
            "code": "optional_input_missing",
            "cell": cell,
            "message": (
                f"可选输入位「{spec['label'] or cell}」未填，按空格=0 参与求值；"
                f"受影响的合计格：{affected}。该项若非零，这些合计是少算的 —— "
                f"请补填后重算。"
            ),
        })
    return out


def ratio_scale_warnings(template_code: str, inputs: dict | None) -> list[dict]:
    """比值型输入位收到 |值| > 1 → `ratio_scale_suspect`（哨兵，**不设硬闸**）。

    为什么是哨兵不是闸（与铁律 7、与 O-06 的 fee_base_magnitude_suspect 同一条纪律）：
    「占总投资比例 > 100%」在现实里几乎一定是把百分数当小数传了，但引擎不能替造价员
    断定这不可能 —— 照算，只是把这件事说出来。

    为什么必须有它：`value_scale` 只是**下发**给前端的事实，前端可以不读、可以走
    退化路径（estimateModel.ts 的裸格号分支硬编码 percentInput:false），也可以有别的
    调用方直接打 API。实测直接传 D48=3.0：D50=5.99（599%），端点 200，
    warnings 与传 0.03 时**完全相同**（都只有一条 template_fix）。契约的另一半在这里。
    """
    scales = input_value_scales(template_code)
    specs = {s["cell"]: s for s in optional_input_specs(template_code)}
    out: list[dict] = []
    for raw_cell, raw_value in (inputs or {}).items():
        cell = raw_cell.replace("$", "")
        if scales.get(cell) != VALUE_SCALE_FRACTION:
            continue
        try:
            v = float(raw_value)
        except (TypeError, ValueError):
            continue          # 非数值由求值器自己的 text_in_arithmetic 管
        if abs(v) <= 1.0:
            continue
        label = (specs.get(cell) or {}).get("label") or cell
        out.append({
            "code": "ratio_scale_suspect",
            "cell": cell,
            "message": (
                f"「{label}」[{cell}] 是**比值列**，格子里存的是小数（列头写的 % 只是"
                f"显示格式）；本次收到 {v:g}，即 {v * 100:g}%。若你想表达的是 {v:g}%，"
                f"应传 {v / 100:g}。本次仍按 {v:g} 照算（哨兵不设硬闸），请核对标度。"
            ),
        })
    return out


# 能由本表兜底的计费基数键 → 取值格（WS10-P07）。只有「工程费用」= 估概算总表!C5。
DERIVABLE_FEE_BASES = {"工程费用": "估概算总表!C5"}


def derive_fee_bases(inputs: dict, template_code: str) -> dict:
    """用本次 run 的 `估概算总表!C5`（工程费用合计）推出可兜底的基数（O-06）。

    二段式时序是契约的缺口：16 条费率规则里 7 条以「工程费用」为基数，而工程费用
    就是本步在填的 C5 合计。兜底不是猜：C5 就是这次 inputs 按模板公式算出来的工程费用，
    与前端第 3 步收敛后自己汇总的数**必然一致**（同一套公式）。

    C5 <= 0（成本位一个没填）时不兜底：拿 0 去调费率引擎只会刷出 16 条
    `fee_base_non_positive`，把「还没到时候」伪装成「算过了但没结果」。
    """
    try:
        computed = estimate_run(inputs, template_code)
    except EstimateTemplateError:
        return {}  # 模板/输入非法，交给下游 suggest 统一报 422，这里不抢着报
    c5 = (computed["totals"].get("project_cost") or {}).get("value")
    if not isinstance(c5, (int, float)) or isinstance(c5, bool) or c5 <= 0:
        return {}
    return {"工程费用": float(c5)}


def resolve_fee_bases(inputs: dict, template_code: str, fee_bases: dict | None,
                       warnings: list[dict]) -> tuple[dict, list[str]]:
    """合并兜底基数与用户基数 → (merged, 本次取自兜底的键)。suggest 与 compute 共用。

    WS10-P07：此前是 `body.fee_bases or _derive_fee_bases(...)` —— 二选一。用户只要补了
    任一基数（比如中标金额），「工程费用」兜底就整条失效：7 条以工程费用为基数的规则
    全部 no_base，双源格静默回退到基准侧（监理费 890.87 → 1058.47）。前端注释与占位
    文字写的却是「留空由服务端兜底」—— 前后端契约相反。

    现在是合并：`{**兜底, **用户值}`，用户值优先。只有「工程费用」**确实**取自兜底时
    才出 `fee_base_derived`（把替人补值这件事说破，不静默）。
    """
    user = {k: v for k, v in (fee_bases or {}).items()}
    derived = derive_fee_bases(inputs, template_code)
    merged = {**derived, **user}
    used_derived = [k for k in derived if k not in user]
    for k in used_derived:
        warnings.append({
            "code": "fee_base_derived",
            "cell": DERIVABLE_FEE_BASES.get(k),
            "message": (
                f"未提供「{k}」基数，已用本次求值的工程费用合计（{DERIVABLE_FEE_BASES.get(k)} = "
                f"{float(derived[k]):.4f} 万元）兜底调用费率引擎；用户给出的其他基数照常参与。"
                "若第 3 步成本位尚未收敛，该基数会随后续录入变化——收敛后请重调一次 suggest "
                "以刷新其他费建议。其余基数（中标金额/建筑面积/受电容量等）无法从本表推导，"
                "清单见响应体 required_fee_bases。"),
        })
    return merged, used_derived


def aggregate_checks(fee_list: list[dict] | None, inputs: dict | None,
                      warnings: list[dict]) -> list[dict]:
    """fee_rules.aggregate_checks 的端点侧包装（suggest 与 compute 共用）。

    同 `_fee_suggestions` 的 importlib 纪律（O-02）：测试可能把 fee_rules 整个打桩成一个
    只有 suggest_all 的假模块，这里探不到 aggregate_checks 就不对账（没有可对的东西），不炸。
    """
    if not fee_list:
        return []
    try:
        fee_rules = importlib.import_module("zt.estimate.fee_rules")  # noqa: PLC0415
    except ImportError:
        return []
    fn = getattr(fee_rules, "aggregate_checks", None)
    if fn is None:
        return []
    checks, warns = fn(fee_list, inputs)
    warnings.extend(warns)
    return checks



# ------------------------------------------------------------------ 费率（P06 / P07）与入参校验（P05 / P06）

MAX_SLOT_LABEL = 40
MAX_ACK_REASON = 500
ACKABLE = ("area_total_mismatch",)
# 单体名里不许出现的字符：换行 / 制表会把 xlsx 名称格撑乱；公式注入由渲染器的 _safe_text 兜
SLOT_LABEL_BAD = re.compile(r"[\r\n\t\x00-\x1f]")


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def cell_value(result: dict, cell: str):
    sheet, coord = cell.split("!", 1)
    return (result.get("sheets") or {}).get(sheet, {}).get(coord.replace("$", ""))


def check_area_context(area_checks_in: dict | None, acknowledged_checks: list | None,
                       slot_labels: dict | None, pol: dict) -> tuple[dict, dict, dict]:
    """校验 P05 的三个新入参 → (area_checks, acks{code: reason}, slot_labels)。非法 → ValueError（端点转 422）。"""
    area_checks: dict[str, float] = {}
    for k, v in (area_checks_in or {}).items():
        if not is_num(v) or v <= 0:
            raise ValueError(f"area_checks.{k} 必须是正数（㎡），实为 {v!r}")
        area_checks[str(k)] = float(v)
    acks: dict[str, str] = {}
    for a in acknowledged_checks or []:
        code = a.get("code") if isinstance(a, dict) else None
        reason = a.get("reason") if isinstance(a, dict) else None
        if code not in ACKABLE:
            raise ValueError(f"acknowledged_checks 只接受 {list(ACKABLE)}，实为 {a!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"确认 {code} 须写明理由（reason 不能为空）")
        acks[code] = reason.strip()[:MAX_ACK_REASON]
    allowed = set(estimate_policy.slot_cells(pol))
    labels: dict[str, str] = {}
    for k, v in (slot_labels or {}).items():
        cell = str(k).replace("$", "")
        if cell not in allowed:
            raise ValueError(f"slot_labels 的键须是单体槽位 {sorted(allowed)} 之一，实为 {k!r}")
        if not isinstance(v, str) or not v.strip() or len(v.strip()) > MAX_SLOT_LABEL \
                or SLOT_LABEL_BAD.search(v):
            raise ValueError(f"slot_labels.{cell} 须是 1~{MAX_SLOT_LABEL} 字的单行文本，实为 {v!r}")
        labels[cell] = v.strip()
    return area_checks, acks, labels


MAX_PROFILE_KEYS = 16
MAX_PROFILE_TEXT = 64
# WS29-q / D-R179：第 5 步选填的参照造价 {amount: 万元, note: 参照的是什么}。画像里唯一的对象值，
# 与 Java EstimateComputeContextValidator 同口径；只拿来算一个比值，不进任何公式
REFERENCE_COST_KEY = "reference_cost"


def _check_reference_cost(v) -> dict | None:
    if v is None:
        return None
    if not isinstance(v, dict):
        raise ValueError("project_profile.reference_cost 须是对象 {amount, note}")
    amount = v.get("amount")
    if not is_num(amount) or amount <= 0:
        raise ValueError(f"project_profile.reference_cost.amount 须是正数（万元），实为 {amount!r}")
    note = v.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > MAX_PROFILE_TEXT
                             or SLOT_LABEL_BAD.search(note)):
        raise ValueError(f"project_profile.reference_cost.note 须是 {MAX_PROFILE_TEXT} 字以内的单行文本")
    out: dict = {"amount": float(amount)}
    if note and note.strip():
        out["note"] = note.strip()
    return out


def check_output_context(input_sources: dict | None, fee_bases: dict | None, fee_attrs: dict | None,
                         project_profile: dict | None, generated_at: str | None
                         ) -> tuple[dict | None, dict, dict, dict, str | None]:
    """校验 P06 的五个新入参 → (input_sources, fee_bases, fee_attrs, project_profile, generated_at)。

    非法 → ValueError（端点转 422）：这些值要写进交付表（来源 / 画像 / 生成时间）或参与费率重算，写错了不能静默吞。
    与 inputs 同一条纪律：数值必须是真数值（pydantic 会把 true 静默转成 1.0）。
    """
    sources = estimate_quality.clean_input_sources(input_sources)
    bases: dict = {}
    for k, v in (fee_bases or {}).items():
        if not is_num(v):
            raise ValueError(f"fee_bases.{k} 必须是数值（万元 / ㎡ / kVA），实为 {v!r}")
        bases[str(k)] = float(v)
    attrs: dict = {}
    for k, v in (fee_attrs or {}).items():
        if not isinstance(v, str):
            raise ValueError(f"fee_attrs.{k} 必须是字符串（受控词），实为 {v!r}")
        attrs[str(k)] = v
    profile: dict = {}
    for k, v in list((project_profile or {}).items())[:MAX_PROFILE_KEYS + 1]:
        if len(profile) >= MAX_PROFILE_KEYS:
            raise ValueError(f"project_profile 最多 {MAX_PROFILE_KEYS} 项")
        if k == REFERENCE_COST_KEY:
            ref = _check_reference_cost(v)
            if ref is not None:
                profile[k] = ref
            continue
        if v is not None and not isinstance(v, str) and not is_num(v):
            raise ValueError(f"project_profile.{k} 只接受字符串 / 数值 / null")
        if isinstance(v, str) and (len(v) > MAX_PROFILE_TEXT or SLOT_LABEL_BAD.search(v)):
            raise ValueError(f"project_profile.{k} 须是 {MAX_PROFILE_TEXT} 字以内的单行文本")
        profile[str(k)[:MAX_PROFILE_TEXT]] = v
    gen = generated_at
    if gen is not None:
        from datetime import datetime  # noqa: PLC0415

        try:
            datetime.fromisoformat(str(gen).strip().replace("Z", ""))
        except ValueError:
            raise ValueError(f"generated_at 须是 ISO 时间（如 2026-09-30 10:00:00），实为 {gen!r}")
        gen = str(gen).strip()[:40]
    return sources, bases, attrs, profile, gen


def fee_rerun(inputs: dict, template_code: str, bases_in: dict, attrs: dict
              ) -> tuple[list[dict], list[str], str | None]:
    """compute 用与 suggest **同一个**合并口径（P07 的 resolve_fee_bases）重跑一次 fee_rules。

    纯函数、零 LLM；产物只用来写 5 表 I 列的计费依据、比对采纳值是否过期（P06），
    **不改任何输入位的值**（金额只来自用户确认过的 inputs，铁律 2）。
    """
    try:
        fee_rules = importlib.import_module("zt.estimate.fee_rules")  # noqa: PLC0415 —— O-02 同款纪律
    except ImportError:
        return [], [], None
    scratch: list[dict] = []   # fee_base_derived 属 suggest 的交互提示，交付表的依据文本里另有说明
    bases, derived = resolve_fee_bases(inputs, template_code, bases_in or None, scratch)
    kind = fee_rules.signoff_kind() if hasattr(fee_rules, "signoff_kind") else None
    if not bases:
        return [], [], kind
    out = fee_rules.suggest_all(bases, attrs or None)
    return list(out.get("items") or []), derived, kind


def footprint_warnings(pol: dict, result: dict) -> list[dict]:
    """P08：用地面积 > 0 而占地面积 = 0 → 室外面积 = 整块用地（D17 = D4 − D14），多算。"""
    fc = estimate_policy.footprint_check(pol)
    if fc is None:
        return []
    site = cell_value(result, fc["site_cell"])
    foot = cell_value(result, fc["footprint_cell"])
    if is_num(site) and site > 0 and (not is_num(foot) or foot == 0):
        return [{"code": "footprint_missing", "cell": fc["footprint_cell"],
                 "message": (f"建筑占地面积（{fc['footprint_cell']}）为 0，室外面积"
                             f"（{fc.get('outdoor_cell') or '室外面积'}）按整块用地 {site:.2f} ㎡ 计，"
                             "室外及配套工程的数量会偏大。原文有建筑占地 / 基底面积时请回第 2 步补填。")}]
    return []


def land_cost_warnings(pol: dict, supplied: set[str]) -> list[dict]:
    """P02：土地费格一个键都没交 → 提示；显式填 0 视为划拨或不计列，不告警。"""
    cell = estimate_policy.land_cost_cell(pol)
    if not cell or cell in supplied:
        return []
    return [{"code": "land_cost_unfilled", "cell": cell,
             "message": ("建设用地费未填：该格不按面积推算（样本里是包干额），请填出让合同价或挂牌价"
                         "（万元）；划拨或本概算不计列时请显式填 0。未填按 0 计入合计。")}]
