# 来源：engine-service/app/engine/estimate_render.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""概算 xlsx 渲染器（spec I-2.6）。

    render(inputs, rates, template_code, project_name) -> bytes

**不复用** `quantity_list.render_xlsx`：对抗审查实证那是单 sheet 平表、0 公式、
只有 6 个固定表头；概算是 9 sheet / 515 公式 / 合并 / 冻结 / 分级大纲，形态完全不同。
可复用的只有 openpyxl 样式片段与 `_safe_cell` 公式注入防护——后者在本模块**重写**
而不是 import：`quantity_list` 在模块级 import `app.llm_client`，渲染器不该为了
7 行防注入代码把 LLM 客户端拖进纯离线的出表链路。

硬约束（阶段 I 接口契约 §1.3，逐条对应实现）：
1. **写真 Excel 公式，不写静态值**——499 条（515 − 16 条 DISPIMG）按模板 `formulas`
   原样写入。这样 OnlyOffice 打开就能改 D7 全表联动重算（I-0.3 验证钉已实证：
   真公式模板改参数能联动，保存后公式逐字符保真）。
2. **模板 3 处 fix 已在 gsyz_v1.json 的 formulas 里落为修正后形态**（实测 13 条
   formula 类修正的 `formula` 字段全等于 `fixes[].changes[].after`，且带 `fixed: true`
   标记），本模块原样写入即满足；渲染后由测试逐条断言。
3. **费率写独立单元格**：`估概算总表!J46` 存费率数值、`J45` 写标签，`C46` 改写为
   `=(C5+C45)*J46`（原表是公式内字面量 0.05）。落点依据：该表 I/J 列零公式、零输入位、
   `I46` 只有静态文本 `3%~8%`，J 列空闲无冲突。
4. **16 条 `class=="dispimg"` 一律跳过**：openpyxl 写图必须 Pillow，venv 未装
   （实测 `import PIL` → ModuleNotFoundError），加依赖需过决策。定额图走知识库 + 结果页侧栏。
5. 输入位有值写数值、无值**留空**（不写 0）——与求值器「空格按 0」的 Excel 语义一致。
6. `project_name` 写进各表第 2 行（role=="project"）的 A2。
   ⚠ 契约原文说「替换 `{{PROJECT_NAME}}` 占位」，但实测模板里根本没有这个占位——
   9 张表的 title/project 行 static 全空（脱敏时清掉了工程名）。所以本实现是**写入**
   而非替换；project_name 为 None 时 A2 留空。
7. 结构元数据（merges / freeze / col_widths / outline）按模板还原；
   `force_expand_outline` 为真的表**强制展开大纲**（原表大量行存成折叠隐藏态，
   直接还原会让造价员打开就看不见明细）。

引擎无状态：本模块不连库、不读环境、不调 LLM，只吃入参与入仓模板。

WS10-B（issue #761）：
8. **P06 生成说明 + 缓存值**：compute 带 notes 时末页追加「生成说明」（生成时间、模板与策略版本、
   项目画像、质量结论、覆盖率分表、告警全表、逐格来源表、已确认的对账差异、汇总费率对账），
   非 ok 时各表标题加「【草稿】/【需复核】」前缀并把生成说明设为活动表；5 表 I 列写计费依据；
   存盘后由 estimate_xlsx_values 给公式格补 `<v>` 缓存值（平台 data_only 读取不再得 None）。
9. **P14 交付表清理**：数字格式按列头量纲（% 列一律百分比，与接口 value_scale 同一判据）；
   两张清单表标「附表」并在第 2 行引用本概算总建筑面积；渲染后自检残留占位符。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side

from zt.estimate import policy as estimate_policy
from zt.estimate import quality as estimate_quality
from zt.estimate import warning_codes
from zt.estimate import xlsx_values as estimate_xlsx_values
from zt.estimate.engine import (
    RATIO_UNITS,
    EstimateTemplateError,
    column_units,
    error_prone_cells,
    load_template,
    run as estimate_run,
)
from zt.estimate.policy import slot_label_cells
# zt 改动：印记来自 zt.quantity.stamp（同一份旧 provenance_sheet.stamp_ai_draft_xlsx）
from zt.quantity.stamp import AI_DRAFT_STAMP, stamp_ai_draft_xlsx

# `#DIV/0!` 空态消除（O-09）。
#
# 只填 11 个根输入生成的表，LibreOffice 重算实测 **71 个错误格**
# （3.专项 47 + 估概算总表 21 + 4.室外 3；按公式类 unit_cost 58 + ratio 12 +
# 沿引用传播的 add_chain 1）。造价员打开第一屏就是一片 #DIV/0!——分母是还没填的
# 数量格，这是**正常的空态**，不是错误，但它长得像错误。
#
# 处理：给会出错的公式套 `IFERROR(<原公式体>,"")`，落点由求值器自己的 AST 算出
# （见 estimate_engine.error_prone_cells），不靠正则猜。
#
# 两条刻意的选择，改之前请先读：
# 1. **无条件包，不按当次输入条件包**。设计稿写的是「分母格缺失/为 0 时才包」，
#    这里改成恒包。理由：条件包让产物随输入变形（同一模板两次渲染公式不同），
#    且用户在 Excel 里把数量清空后 #DIV/0! 会回来 —— 那正是本条在修的东西。
#    恒包不影响"公式是活的"：补填 E7 立刻出值（IFERROR 只在出错时才走兜底支）。
# 2. **只包会除零的那 237 格，不包全部 499 条**。IFERROR 会把 #REF!/#NAME? 一起
#    吞掉变成空白 —— 那是另一种「误导性成功」。限定在除法闭包内，代价可控：
#    这批公式形态固定（=Cn/En*10000 与 =Cn/C50），现实里唯一会犯的错就是除零。
_IFERROR_FALLBACK = '""'


def _wrap_iferror(formula: str) -> str:
    body = formula[1:] if formula.startswith("=") else formula
    return f"=IFERROR({body},{_IFERROR_FALLBACK})"

# 与 quantity_list.render_xlsx 同一套排版规格（宋体 10 / 细边框 / 居中换行）
_FONT_TITLE = Font(name="宋体", size=14, bold=True)
_FONT_HEAD = Font(name="宋体", size=10, bold=True)
_FONT_BODY = Font(name="宋体", size=10)
_ALIGN_C = Alignment(horizontal="center", vertical="center", wrap_text=True)
_ALIGN_L = Alignment(horizontal="left", vertical="center", wrap_text=True)
_BORDER = Border(left=Side("thin"), right=Side("thin"), top=Side("thin"), bottom=Side("thin"))

_FMT_MONEY = "#,##0.00"
_FMT_PCT = "0.00%"

# 费率独立单元格落点（契约 §1.3 硬约束 3）。
# ⚠ O-14 起这是**回落值**，不是唯一真源：落点已提到模板 `rate_params` 的
# render_value_cell / render_label_cell / render_label / render_formula 里，
# 好让 GET /estimate/template 把它带给前端（结果页要告诉造价员"改哪一格"）。
# 落点只活在本常量里的时候，前端只能硬编码 J46 或者干脆不写 —— 实测是后者，
# 于是面向用户的文案里出现的是 rate_params.cell（C46），而改 C46 等于删公式。
# 模板没写 render_* 时（老模板）仍用这里的值，行为与 O-14 之前一致。
RATE_CELLS = {
    "reserve_rate": {"value_cell": "估概算总表!J46", "label_cell": "估概算总表!J45",
                     "label": "预备费率", "formula": "=(C5+C45)*J46"},
}


def rate_render_spec(param: dict, pname: str) -> dict | None:
    """模板优先、常量回落，取一个费率参数的渲染落点。两处都没有 → None（保持原公式）。"""
    if param.get("render_value_cell"):
        return {
            "value_cell": param["render_value_cell"],
            "label_cell": param.get("render_label_cell"),
            "label": param.get("render_label") or pname,
            "formula": param.get("render_formula"),
        }
    return RATE_CELLS.get(pname)


def _safe_text(v: Any) -> Any:
    """防 xlsx 公式注入（照搬 quantity_list._safe_cell 的判据）。

    project_name 来自用户输入、静态文本来自脱敏原表，= + - @ 制表符/回车 开头的文本
    会被 Excel/WPS 当公式执行（如 `=cmd|'...'!A1`）。加单引号前缀让其显示为文本。
    """
    if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + v
    return v


def _num_format(col: str, cls: str | None, kind: str | None, unit: str | None = None) -> str | None:
    # WS10-P14：% 列一律百分比格式，按列头量纲判（与接口 _input_value_scales 同一判据）——
    # 此前 估概算总表!D50（=D47+D48+D49，占比）属 add_chain，拿了金额格式，显示成 1.00 而不是 100.00%。
    if cls == "ratio" or (unit or "").strip() in RATIO_UNITS:
        return _FMT_PCT
    if cls == "cross_ref" and col == "B":
        return None  # 工程名称文本透传，不套数字格式
    if cls is not None or kind is not None:
        return _FMT_MONEY
    return None


# 渲染后自检的样本占位符（WS10-P14）：（***）/ *x% / （x）。「元/x」「x/㎡」是合法的量纲写法，不算。
_PLACEHOLDER = re.compile(r"\*{3}|\*\s*x\s*%|[（(]\s*x\s*[)）]")
NOTES_SHEET = "生成说明"
TITLE_PREFIX = {estimate_quality.REVIEW_DRAFT: "【草稿】", estimate_quality.REVIEW_NEEDS: "【需复核】"}


@dataclass
class RenderResult:
    xlsx: bytes
    warnings: list[dict] = field(default_factory=list)
    cached_cells: int = 0


def render(
    inputs: dict[str, float],
    rates: dict[str, float] | None = None,
    template_code: str = "gsyz_v1",
    project_name: str | None = None,
    slot_labels: dict[str, str] | None = None,
) -> bytes:
    """按固化模板渲染带真公式的概算 xlsx，返回字节流（不带生成说明，见 render_estimate）。

    inputs   {"sheet!coord": 数值}，只写命中模板声明位的键（未声明键静默忽略——
             由 `estimate_engine.run()` 负责出 unknown_input warning，渲染器不重复报）。
    rates    {"reserve_rate": 0.05}；写进独立费率格，公式引用之。软区间不设硬闸（铁律 7）。
    slot_labels {槽位格: 单体名}（WS10-P05）：覆盖样本楼名。名称格由模板公式推导
             （estimate_policy.slot_label_cells），单项工程行补「工程」后缀；文本走
             _safe_text 防公式注入。调用方（端点）已校验键与长度。
    """
    return render_estimate(inputs, rates, template_code, project_name, slot_labels).xlsx


def render_estimate(
    inputs: dict[str, float],
    rates: dict[str, float] | None = None,
    template_code: str = "gsyz_v1",
    project_name: str | None = None,
    slot_labels: dict[str, str] | None = None,
    *,
    notes: dict | None = None,
    values: dict[str, dict[str, Any]] | None = None,
    stamp_text: str | None = None,
) -> RenderResult:
    """render() 的完整出口（WS10-P06 / P14）→ RenderResult(xlsx, warnings, cached_cells)。

    notes（compute 端点组装，None = 不附生成说明）：
      {generated_at, quality{review_level, reasons}, input_coverage, warnings, input_sources,
       acks{code: reason}, fee_basis{5 表行号: 依据文本}, aggregate_checks, project_profile}
    values：求值器 run() 的 sheets（给公式格补缓存值）；None 时本函数自己跑一次 run()。
    stamp_text（WS25-b）：打印页眉与生成说明末行的标记。None = 「AI 初稿·须人工复核」（默认不变）；
      报表管理按数据血缘传：纯人工填报与空白模板写「须人工复核」（spec WS25 U12）。
    """
    stamp = stamp_text or AI_DRAFT_STAMP
    tpl = load_template(template_code)
    pol = estimate_policy.load_policy(template_code)
    wb = Workbook()
    wb.remove(wb.active)

    values_in = {str(k).replace("$", ""): v for k, v in (inputs or {}).items()}
    declared = {i["cell"] for i in tpl["inputs"]} | set(tpl.get("optional_inputs", []))
    input_kind = {i["cell"]: i["kind"] for i in tpl["inputs"]}
    formulas = {f["cell"]: f for f in tpl["formulas"] if f["class"] != "dispimg"}

    # 空态 #DIV/0! 消除（O-09）：会除零的公式格恒套 IFERROR，见本文件顶部注释
    for cell in error_prone_cells(template_code):
        f = formulas.get(cell)
        if f is not None:
            formulas[cell] = dict(f, formula=_wrap_iferror(f["formula"]))

    # 费率格：把公式里的字面量费率提成独立单元格（契约 §1.3-3）
    rates = rates or {}
    # {sheet: {row: [(col, value, number_format)]}}
    rate_extra: dict[str, dict[int, list[tuple[str, Any, str | None]]]] = {}
    for pname, p in tpl.get("rate_params", {}).items():
        spec = rate_render_spec(p, pname)
        if spec is None:
            continue  # 模板新增了费率参数但两处都没给落点 —— 保持原公式，不擅自安置
        rate = rates.get(pname, p["default"])
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise EstimateTemplateError(f"费率 {pname} 必须是数值，实为 {type(rate).__name__}")
        _stash(rate_extra, spec["value_cell"], float(rate), _FMT_PCT)
        if spec.get("label_cell"):
            _stash(rate_extra, spec["label_cell"], spec["label"], None)
        if spec.get("formula") and p["cell"] in formulas:
            formulas[p["cell"]] = dict(formulas[p["cell"]], formula=spec["formula"])

    # {sheet: {(col, row): 名称}} —— 覆盖样本私有的楼名（1#楼 / 2#楼 / 3#楼）
    name_overrides: dict[str, dict[tuple[str, int], str]] = {}
    if slot_labels:
        name_cells = slot_label_cells(template_code)
        for slot, label in slot_labels.items():
            for cell, suffix in name_cells.get(slot, []):
                text = label if not suffix or label.endswith(suffix) else label + suffix
                sh, coord = cell.split("!", 1)
                col = coord.rstrip("0123456789")
                name_overrides.setdefault(sh, {})[(col, int(coord[len(col):]))] = text

    quality = (notes or {}).get("quality") or {}
    title_prefix = TITLE_PREFIX.get(quality.get("review_level"), "")
    # 5 表 I 列「费用计算标准」：计费依据（WS10-P06）
    fee_basis = {int(k): v for k, v in ((notes or {}).get("fee_basis") or {}).items()}
    refs = {r["sheet"]: r for r in (pol.get("reference_sheets") or []) if r.get("sheet")}

    for sheet in tpl["sheets"]:
        extra = dict(rate_extra.get(sheet["name"], {}))
        if sheet["name"] == "5.工程建设其他费用":
            for row_no, text in fee_basis.items():
                extra.setdefault(row_no, []).append(("I", text, None))
        _render_sheet(wb, sheet, declared, input_kind, formulas, values_in,
                      extra, project_name,
                      name_overrides.get(sheet["name"], {}),
                      title_prefix=title_prefix, reference=refs.get(sheet["name"]))

    warnings = _placeholder_warnings(wb)
    if notes is not None:
        ws = _append_notes_sheet(wb, tpl, pol, notes, project_name, warnings, stamp)
        if title_prefix:
            # 非 ok：打开就先看到「为什么是草稿 / 需复核」
            wb.active = wb.sheetnames.index(ws.title)
    stamp_ai_draft_xlsx(wb, stamp)

    buf = BytesIO()
    wb.save(buf)
    if values is None:
        values = estimate_run(inputs or {}, template_code, rates)["sheets"]
    fixed = _parse_time((notes or {}).get("generated_at"))
    xlsx, n = estimate_xlsx_values.inject_cached_values(buf.getvalue(), values, fixed_time=fixed)
    return RenderResult(xlsx=xlsx, warnings=warnings, cached_cells=n)


def _parse_time(s: Any) -> datetime | None:
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", ""))
    except ValueError:
        return None
    return dt if dt.year >= 1980 else None


def _placeholder_warnings(wb: Workbook) -> list[dict]:
    """渲染后自检：交付表里还残留样本占位符 → template_placeholder_left（WS10-P14）。"""
    hits: list[str] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and not c.value.startswith("=") and _PLACEHOLDER.search(c.value):
                    hits.append(f"{ws.title}!{c.coordinate}「{c.value.strip()[:20]}」")
    if not hits:
        return []
    return [{"code": "template_placeholder_left", "cell": None,
             "message": (f"交付表里还有 {len(hits)} 处样本占位符未替换：{'、'.join(hits[:10])}"
                         + ("…" if len(hits) > 10 else "") + "。请人工改成本项目的实际名称。")}]


def _stash(store: dict[str, dict[int, list[tuple[str, Any, str | None]]]],
           cell: str, value: Any, fmt: str | None) -> None:
    sheet, coord = cell.split("!", 1)
    col = coord.rstrip("0123456789")
    row = int(coord[len(col):])
    store.setdefault(sheet, {}).setdefault(row, []).append((col, value, fmt))


def _render_sheet(wb: Workbook, sheet: dict, declared: set[str], input_kind: dict[str, str],
                  formulas: dict[str, dict], inputs: dict[str, Any],
                  rate_extra: dict[int, list[tuple[str, Any, str | None]]],
                  project_name: str | None,
                  name_overrides: dict[tuple[str, int], str] | None = None,
                  *, title_prefix: str = "", reference: dict | None = None) -> None:
    name = sheet["name"]
    ws = wb.create_sheet(title=name)
    units = column_units(sheet)
    # 原表小计行在明细行之上（实测 31 条 SUM/composite 公式的父行行号全部 < 区间起点），
    # summaryBelow 必须为 False，否则大纲折叠按钮画在错误的一侧。
    ws.sheet_properties.outlinePr.summaryBelow = False

    for col, width in (sheet.get("col_widths") or {}).items():
        ws.column_dimensions[col].width = width

    expand = bool(sheet.get("force_expand_outline"))
    body_cols = _body_columns(sheet)

    for row in sheet["rows"]:
        r = row["row"]
        role = row["role"]

        outline = row.get("outline")
        if outline:
            dim = ws.row_dimensions[r]
            dim.outlineLevel = outline.get("level") or 0
            # 强制展开：原表把大量明细行存成 hidden=true，还原后造价员打开是一张空壳表
            dim.hidden = False if expand else bool(outline.get("hidden"))

        if role == "title" and not (row.get("static") or {}):
            # 9 张表里 8 张的标题行是空的——脱敏时连表名一起清了。空着交付是一张
            # 无名表，所以回填 sheet 名（sheet 自己的身份，不是编造内容）。
            # 5.工程建设其他费用 的标题在 B1 静态文本里，交给下面的 statics 循环写，A1 不重复。
            # WS10-P14：清单表是样本表的空壳，标明「附表（口径参考…）」；WS10-P06：非 ok 加前缀
            title = row.get("label") or name
            if reference and reference.get("title"):
                title = f"{reference['title']}：{title}"
            _put(ws, "A", r, _safe_text(title_prefix + title), _FONT_TITLE, _ALIGN_C, None)
        elif role == "project":
            _put(ws, "A", r, _safe_text(project_name), _FONT_BODY, _ALIGN_C, None)

        for col, text in (row.get("static") or {}).items():
            text = (name_overrides or {}).get((col, r), text)
            if role == "title" and title_prefix and isinstance(text, str):
                text = title_prefix + text
            font = _FONT_TITLE if role == "title" else (
                _FONT_HEAD if role == "header" else _FONT_BODY)
            align = _ALIGN_L if col == "B" and role not in ("header", "title") else _ALIGN_C
            _put(ws, col, r, _safe_text(text), font, align, None)

        if role in ("row", "sentinel") and row.get("seq") is not None:
            # seq 存 varchar：「1.10」当数字会塌缩成 1.1 与真 1.1 重号（种子 DDL 已记在案）
            _put(ws, "A", r, str(row["seq"]), _FONT_BODY, _ALIGN_C, "@")

        for col in body_cols:
            cell = f"{name}!{col}{r}"
            f = formulas.get(cell)
            if f is not None:
                _put(ws, col, r, f["formula"], _FONT_BODY, _ALIGN_C,
                     _num_format(col, f["class"], None, units.get(col)))
                continue
            if cell in declared:
                v = inputs.get(cell)
                fmt = _num_format(col, None, input_kind.get(cell, "cost"), units.get(col))
                # 无值留空：不写 0，与求值器「空格按 0」语义一致，也让造价员一眼看见哪些没填
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    _put(ws, col, r, float(v), _FONT_BODY, _ALIGN_C, fmt)
                else:
                    _put(ws, col, r, None, _FONT_BODY, _ALIGN_C, fmt)

        for col, val, fmt in rate_extra.get(r, ()):
            align = _ALIGN_L if isinstance(val, str) and len(val) > 12 else _ALIGN_C
            _put(ws, col, r, _safe_text(val), _FONT_BODY, align, fmt)

        if role == "project" and reference and reference.get("area_cell") and reference.get("area_ref"):
            # WS10-P14：清单表第 2 行「建筑面积：」后引用本概算的总建筑面积（不是样本的空白）
            sh, coord = reference["area_ref"].split("!", 1)
            col_letters = coord.rstrip("0123456789")
            ref = f"'{sh}'!${col_letters}${coord[len(col_letters):]}"
            acol = reference["area_cell"].rstrip("0123456789")
            _put(ws, acol, r, f"={ref}", _FONT_BODY, _ALIGN_C, _FMT_MONEY)

        if role in ("row", "sentinel", "header"):
            for col in ["A", *body_cols]:
                ws[f"{col}{r}"].border = _BORDER

    if sheet.get("freeze"):
        ws.freeze_panes = sheet["freeze"]
    # 合并放最后：openpyxl 的 merge_cells 会把非锚点格换成只读 MergedCell，
    # 先写值后合并才不会踩「写不进去」。实测模板无任何内容落在非锚点格上。
    for rng in sheet.get("merges") or []:
        ws.merge_cells(rng)


_PROFILE_CN = {"building_function": "业态", "project_city": "项目所在地", "project_nature": "项目性质",
               "project_type": "项目类型"}


def _append_notes_sheet(wb: Workbook, tpl: dict, pol: dict, notes: dict, project_name: str | None,
                        render_warnings: list[dict], stamp: str = AI_DRAFT_STAMP):
    """末页「生成说明」（WS10-P06）：这份表是怎么来的、完成到什么程度、哪些地方要人再看。

    只追加在最后、不在既有表里插行（概算模板有固定公式格，插一行就把引用全挪错了）。
    所有文本走 _safe_text（来源引文、确认理由都是用户 / 原文文本）。
    """
    ws = wb.create_sheet(title=NOTES_SHEET)
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 70
    rows: list[tuple] = []
    quality = notes.get("quality") or {}
    level = quality.get("review_level")

    def sec(title: str) -> None:
        rows.append(())
        rows.append((f"■ {title}",))

    rows.append((NOTES_SHEET,))
    rows.append(("项目名称", project_name or "（未填）"))
    rows.append(("生成时间", notes.get("generated_at") or "未提供（调用方未传 generated_at）"))
    rows.append(("模板", f"{tpl.get('template_code')} v{tpl.get('template_version')}"))
    rows.append(("口径策略版本", estimate_policy.policy_version(pol) or "（无策略文件）"))
    rows.append(("质量结论", f"{estimate_quality.REVIEW_LEVEL_CN.get(level, level or '未判定')}（{level or '—'}）"))
    for r in quality.get("reasons") or []:
        rows.append(("", r.get("code") or "", "", r.get("message") or ""))

    sec("项目画像")
    profile = dict(notes.get("project_profile") or {})
    # WS29-q：参照造价是对象，不按「键 = 值」写进画像，下面单独成节
    reference_cost = profile.pop("reference_cost", None)
    if not profile:
        rows.append(("（未提供）",))
    for k, v in profile.items():
        shown = v
        if k == "building_function":
            shown = estimate_policy.building_function_label(pol, v) or v
        rows.append((_PROFILE_CN.get(k, k), "" if shown is None else str(shown)))

    # WS29-q / D-R179：填了参照造价才有这一节；比值只是对照，表里的金额与它无关
    comparison = quality.get("reference_comparison")
    if isinstance(reference_cost, dict) or isinstance(comparison, dict):
        sec("参照造价对比")
        ref = comparison if isinstance(comparison, dict) else reference_cost
        amount = ref.get("amount")
        rows.append(("参照造价", f"{float(amount):,.2f} 万元" if isinstance(amount, (int, float)) else "",
                     "", ref.get("note") or ""))
        if isinstance(comparison, dict) and comparison.get("message"):
            rows.append(("参照对比", "需复核" if comparison.get("deviates") else "在区间内", "",
                         comparison["message"] + "（只作对照，不参与计算）"))

    sec("成本位覆盖率（按表）")
    cov = notes.get("input_coverage") or {}
    rows.append(("表", "成本位", "已填", "覆盖率"))
    for name, st in (cov.get("by_sheet") or {}).items():
        n, f = st.get("cost_inputs") or 0, st.get("filled") or 0
        rows.append((name, n, f, f"{(f / n if n else 0):.1%}"))
    if cov:
        rows.append(("合计", cov.get("cost_inputs"), cov.get("filled"), f"{(cov.get('rate') or 0):.1%}"))

    sec("告警")
    rows.append(("级别", "告警", "格", "说明"))
    all_warn = list(notes.get("warnings") or []) + list(render_warnings or [])
    for w in all_warn:
        meta = warning_codes.describe(w.get("code") or "") or {}
        rows.append(({"warn": "需关注", "info": "提示"}.get(meta.get("severity"), meta.get("severity") or ""),
                     meta.get("label") or w.get("code") or "", w.get("cell") or "", w.get("message") or ""))
    if not all_warn:
        rows.append(("（无）",))

    sec("已确认的对账差异")
    acks = notes.get("acks") or {}
    for code, reason in acks.items():
        meta = warning_codes.describe(code) or {}
        rows.append((meta.get("label") or code, "", "", f"确认理由：{reason}"))
    if not acks:
        rows.append(("（无）",))

    sec("汇总型费率与子项对账")
    checks = notes.get("aggregate_checks") or []
    for c in checks:
        dev = c.get("deviation")
        rows.append((c.get("fee_name") or c.get("item_id") or "", c.get("status") or "",
                     c.get("aggregate_cell") or c.get("cell") or "",
                     (f"子项和 {c.get('children_sum')} 万元 / 小计参考 {c.get('subtotal')} 万元"
                      + (f"，偏差 {dev:+.1%}" if isinstance(dev, (int, float)) else "")
                      + (f"；{c.get('reason')}" if c.get("reason") else ""))))
    if not checks:
        rows.append(("（无：没有已填的汇总子项，或规则未出小计参考值）",))

    sec("逐格来源")
    rows.append(("格", "行名", "来源", "出处 / 说明"))
    labels = {i["cell"]: i.get("label") for i in tpl.get("inputs", [])}
    sources = notes.get("input_sources")
    supplied = notes.get("supplied") or []
    for cell in supplied:
        src = (sources or {}).get(cell)
        if src is None:
            rows.append((cell, labels.get(cell) or "", "未申报", ""))
            continue
        where = "；".join(x for x in (
            src.get("file_name") or src.get("file_id") or "",
            f"引文：{src['quote']}" if src.get("quote") else "",
            f"基准：{'、'.join(src['refs'])}" if src.get("refs") else "",
            f"语义键：{src['semantic_key']}" if src.get("semantic_key") else "") if x)
        rows.append((cell, labels.get(cell) or "", estimate_quality.SOURCE_KIND_CN.get(src["source"], src["source"]),
                     where))

    rows.append(())
    rows.append((stamp + "：金额由确定性求值器按上表输入计算，LLM 不碰金额（铁律 2）；"
                 "打开后改输入格会联动重算。",))
    for r in rows:
        ws.append([_safe_text(v) for v in r])
    ws["A1"].font = _FONT_TITLE
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = _ALIGN_L
            if isinstance(c.value, str) and c.value.startswith("■ "):
                c.font = _FONT_HEAD
    return ws


def _body_columns(sheet: dict) -> list[str]:
    """本表实际用到的正文列（A 序号列除外），由 static/col_widths 归纳，不写死。

    B 列必须包含：估概算总表 B25~B35 的 11 条 cross_ref 公式（引分析表工程名）就在 B 列。
    col_widths 里的 IB/IF/IK 之类是原表默认列宽尾巴，len>1 已滤掉。
    """
    cols: set[str] = set()
    for row in sheet["rows"]:
        cols.update(c for c in (row.get("static") or {}) if len(c) == 1)
    cols.update(c for c in (sheet.get("col_widths") or {}) if len(c) == 1)
    cols.discard("A")
    return sorted(cols)


def _put(ws, col: str, row: int, value: Any, font: Font, align: Alignment,
         number_format: str | None) -> None:
    c = ws[f"{col}{row}"]
    if value is not None:
        c.value = value
    c.font = font
    c.alignment = align
    if number_format:
        c.number_format = number_format
