# 来源：engine-service/app/engine/estimate_engine.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""概算确定性求值器（spec I-2.2）。

对 gsyz_v1.json 固化模板做拓扑排序求值：
    run(inputs, template_code="gsyz_v1", rates=None) -> {sheets, totals, indicators, warnings}

红线（产品裁决，违者作废）：
- 纯确定性 Python：不调用任何 LLM，金额一分钱都不经过模型；
- 引擎无状态：不连 MySQL、不写库、不读环境，只吃入参和入仓模板；
- 预备费率不设硬闸：rates 可调（默认 5%），软区间 3%~8% 之外只出 warning，
  1% 必须能算出结果（用户裁决「可调，不得写死」）。

公式语言边界（515 条实测归纳，见模板 README「8 类归纳」）：
- 函数只有 SUM（单列区间），无 IF/VLOOKUP/ROUND；
- 四则 + 括号 + 单元格/跨表引用；DAG 已证无环（仍带成环防御）；
- 16 条 `_xlfn.DISPIMG`（WPS 私有图片函数）不参与求值，图片实体见
  estimate_templates/fee_images/。

求值语义（对齐 Excel 在本工作簿内的实际行为）：
- 空单元格参与四则运算按 0 计（原表 211 输入位留空即 0 的语义）；
- 单引用公式（cross_ref）原样透传目标值——总表 B25~B35 引用的是文本工程名；
- 除数为 0 → 该格结果为 None 并记 warning（对应 Excel #DIV/0!），错误向下游传播；
- 文本参与四则 → None + warning（本模板正常数据流不会出现）。
"""
from __future__ import annotations

import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

_TPL_DIR = Path(__file__).resolve().parent / "data" / "estimate_templates"


def decimal_literal(x: float) -> str:
    """把费率写成公式里安全的十进制字面量，**绝不产生指数形式**（O-15）。

    原写法 `f"{rate:.10g}"` 在 rate < 1e-4 时吐 `1e-05`，拼进 `=(C5+C45)*1e-05`
    后本模块的分词器不认 `e`，整个 compute 被打成 422
    「无法解析公式 '=(C5+C45)*1e-05'」。造价员把预备费率填 0.001%（阶段性小额预备费，
    合法输入）就崩——而铁律 7 明说预备费率不设硬闸，崩溃是最硬的闸。

    口径不变：仍取 10 位有效数字（沿用原 `.10g`），只是换成 Decimal 的定点输出。
    分词器那侧另加了 `[eE][+-]?\\d+` 兜底，两头都堵上：万一别处再拼出指数形式，
    也不会再炸成 422。
    """
    return f"{Decimal(f'{float(x):.10g}'):f}"

Cell = tuple[str, str]  # (sheet, coord) 例 ("估概算总表", "C5")


class EstimateTemplateError(ValueError):
    """模板不存在/公式超出语言边界/依赖成环。"""


# ---------------------------------------------------------------- 公式解析
_TOKEN = re.compile(
    r"""
    (?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
  | (?P<sum>SUM\()
  | (?P<ref>(?:'[^']+'!|[^\s'!+\-*/():,]+!)?\$?[A-Z]{1,3}\$?\d+)
  | (?P<op>[+\-*/():])
    """,
    re.VERBOSE,
)


def _norm_ref(raw: str, cur_sheet: str) -> Cell:
    if "!" in raw:
        sheet, coord = raw.split("!", 1)
        sheet = sheet.strip("'")
    else:
        sheet, coord = cur_sheet, raw
    return sheet, coord.replace("$", "")


def _split_coord(coord: str) -> tuple[str, int]:
    m = re.match(r"([A-Z]{1,3})(\d+)$", coord)
    if not m:
        raise EstimateTemplateError(f"非法坐标：{coord}")
    return m.group(1), int(m.group(2))


class _Parser:
    """递归下降：expr := term (± term)* ; term := factor (*/ factor)* ;
    factor := num | ref | SUM(range) | (expr) | -factor"""

    def __init__(self, formula: str, cur_sheet: str):
        self.sheet = cur_sheet
        self.toks: list[tuple[str, str]] = []
        body = formula[1:] if formula.startswith("=") else formula
        pos = 0
        while pos < len(body):
            if body[pos].isspace():
                pos += 1
                continue
            m = _TOKEN.match(body, pos)
            if not m:
                raise EstimateTemplateError(f"无法解析公式 {formula!r}（offset {pos}）")
            self.toks.append((m.lastgroup, m.group(0)))
            pos = m.end()
        self.i = 0

    def peek(self) -> tuple[str, str] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> tuple[str, str]:
        t = self.toks[self.i]
        self.i += 1
        return t

    def parse(self):
        node = self.expr()
        if self.peek() is not None:
            raise EstimateTemplateError(f"公式残留 token：{self.toks[self.i:]}")
        return node

    def expr(self):
        node = self.term()
        while (t := self.peek()) and t[1] in "+-":
            op = self.take()[1]
            node = ("add" if op == "+" else "sub", node, self.term())
        return node

    def term(self):
        node = self.factor()
        while (t := self.peek()) and t[1] in "*/":
            op = self.take()[1]
            node = ("mul" if op == "*" else "div", node, self.factor())
        return node

    def factor(self):
        kind, text = self.take()
        if kind == "num":
            return ("num", float(text))
        if kind == "ref":
            return ("ref", *_norm_ref(text, self.sheet))
        if kind == "sum":
            a = self.take()
            if a[0] != "ref":
                raise EstimateTemplateError("SUM 区间起点缺失")
            colon = self.take()
            if colon[1] != ":":
                raise EstimateTemplateError("只支持 SUM(A1:B2) 区间形态")
            b = self.take()
            close = self.take()
            if close[1] != ")":
                raise EstimateTemplateError("SUM 未闭合")
            s1, c1 = _norm_ref(a[1], self.sheet)
            s2, c2 = _norm_ref(b[1], self.sheet)
            if s1 != s2:
                raise EstimateTemplateError("SUM 不支持跨表区间")
            col1, r1 = _split_coord(c1)
            col2, r2 = _split_coord(c2)
            if col1 != col2:
                raise EstimateTemplateError("SUM 只支持单列区间（模板实证形态）")
            return ("sumrange", s1, col1, min(r1, r2), max(r1, r2))
        if text == "(":
            node = self.expr()
            if self.take()[1] != ")":
                raise EstimateTemplateError("括号未闭合")
            return node
        if text == "-":
            return ("neg", self.factor())
        raise EstimateTemplateError(f"意外 token {text!r}")


def _refs_of(node) -> list[Cell]:
    kind = node[0]
    if kind == "ref":
        return [(node[1], node[2])]
    if kind == "sumrange":
        _, sheet, col, r1, r2 = node
        return [(sheet, f"{col}{r}") for r in range(r1, r2 + 1)]
    if kind in ("add", "sub", "mul", "div"):
        return _refs_of(node[1]) + _refs_of(node[2])
    if kind == "neg":
        return _refs_of(node[1])
    return []


# ---------------------------------------------------------------- 模板装载

#: 模板编码白名单。**与 Java 侧 EngineClient.TEMPLATE_CODE 逐字一致**
#: （`^[A-Za-z0-9_-]{1,64}$`）——两边漂移的话，会出现「Java 放行、引擎拒绝」
#: 或反之的怪现象，而两处代码单看都没错。
_TEMPLATE_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@lru_cache(maxsize=4)
def load_template(template_code: str = "gsyz_v1") -> dict:
    """按编码装载概算模板。

    <h3>为什么这里要判两次（issue #128）</h3>

    这个参数从三条 POST 通道进来，此前**一路零校验**直接参与路径拼接
    （``_TPL_DIR / f"{template_code}.json"``）。实测可越界读到模板目录之外的文件::

        load_template('../../../NOT_A_TEMPLATE_secret')
        →  engine-service/app/NOT_A_TEMPLATE_secret.json 的内容被返回

    本函数是全仓装载模板的**唯一收口点**（app/ 下 8 处调用全走它），
    所以闸放在这里能覆盖所有入口 —— 但外层的 schema 与 Java 侧也各加了一道，
    理由是纵深：任何一层被后来人放宽，另外两层还在。

    两道闸都不能省：

    * **白名单正则** —— 结构上排除 ``/`` ``\\`` ``..`` 与绝对路径，
      是能读懂的那一层，也让错误信息可以明确说"编码不合规"。
    * **解析后仍须落在 _TPL_DIR 内** —— 防正则日后被放宽、或符号链接绕过。
      单靠正则是"我相信我列全了坏字符"，加上这条才是"我验证了结果没跑出去"。

    ⚠ 没有直接复用 ``app/files.py`` 的 ``resolve_safe_path()``：那个函数锚的是
    ``settings.file_root``（用户文件根，不是模板目录）且抛 ``HTTPException(400)``，
    而本模块是纯计算层、不该依赖 FastAPI。这里是同一套判法的另一处实现，
    不是"忘了复用"。

    :raises EstimateTemplateError: 编码不合规 / 越界 / 模板不存在
    """
    if not _TEMPLATE_CODE_RE.match(template_code or ""):
        raise EstimateTemplateError(f"模板编码不合规（只接受 [A-Za-z0-9_-]{{1,64}}）：{template_code!r}")
    path = _TPL_DIR / f"{template_code}.json"
    try:
        path.resolve().relative_to(_TPL_DIR.resolve())
    except ValueError:
        # 正则理应已经挡住，能走到这里说明正则被放宽了 —— 按越界拒掉，别放行
        raise EstimateTemplateError(f"模板编码越界（超出模板目录）：{template_code!r}")
    if not path.is_file():
        raise EstimateTemplateError(f"模板不存在：{template_code}")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def _compiled(template_code: str) -> dict:
    """预编译：AST、依赖边、拓扑序（费率格除外——其公式随 rates 变化，运行期编译）。"""
    tpl = load_template(template_code)
    rate_cells = {p["cell"] for p in tpl.get("rate_params", {}).values()}
    ast: dict[Cell, Any] = {}
    for f in tpl["formulas"]:
        if f["class"] == "dispimg" or f["cell"] in rate_cells:
            continue
        sheet, coord = f["cell"].split("!", 1)
        ast[(sheet, coord)] = _Parser(f["formula"], sheet).parse()
    return {"tpl": tpl, "ast": ast, "rate_cells": rate_cells, "static_text": _static_text_pass(tpl)}


@lru_cache(maxsize=4)
def error_prone_cells(template_code: str = "gsyz_v1") -> frozenset[str]:
    """会在 Excel 里冒 `#DIV/0!` 的公式格集合（含沿引用传播的下游）—— O-09。

    为什么需要这个出口：渲染器要给这些格套 `IFERROR(...,"")`，否则只填 11 个根输入
    生成的表打开就是一屏错误码。而"哪些格会出错"不能在渲染器里靠正则猜 ——
    猜出来的集合会与求值器实际的引用语义漂移（`$` 绝对引用、跨表 `'3.专项工程费'!C5`、
    SUM 区间展开三种形态）。这里直接用求值器**自己的** AST 与引用出口算，
    是与 `api/estimate.py` 复用 `_refs_of` 同一条纪律，只是做成了公开出口。

    种子 = 公式里含 `/` 的格（实测 gsyz_v1 有 236 条：unit_cost 224 + ratio 12）。
    闭包 = 再加上任何引用了种子/闭包成员的公式格 —— 因为 `IFERROR(...,"")` 落的是
    **文本空串**，`=D47+D48+D49` 拿到文本会变成 `#VALUE!`，不跟着包就是把
    `#DIV/0!` 换成了 `#VALUE!`。实测闭包只多 1 格（估概算总表!D50）。

    返回 "sheet!coord" 字符串集合（渲染器按这个形态查表）。
    """
    comp = _compiled(template_code)
    ast = comp["ast"]
    closure: set[Cell] = set()
    for f in comp["tpl"]["formulas"]:
        if f["class"] == "dispimg" or "/" not in f["formula"]:
            continue
        sheet, coord = f["cell"].split("!", 1)
        closure.add((sheet, coord))
    changed = True
    while changed:
        changed = False
        for cell, node in ast.items():
            if cell in closure:
                continue
            if any(ref in closure for ref in _refs_of(node)):
                closure.add(cell)
                changed = True
    return frozenset(f"{s}!{c}" for s, c in closure)


def _topo_order(ast: dict[Cell, Any]) -> list[Cell]:
    """Kahn 拓扑排序。DAG 已证无环，但保留防御：残环即模板缺陷，必须炸出来。"""
    dependents: dict[Cell, list[Cell]] = {}
    indeg: dict[Cell, int] = {c: 0 for c in ast}
    for cell, node in ast.items():
        for ref in _refs_of(node):
            if ref in ast:
                dependents.setdefault(ref, []).append(cell)
                indeg[cell] += 1
    queue = sorted(c for c, d in indeg.items() if d == 0)
    order: list[Cell] = []
    while queue:
        cell = queue.pop()
        order.append(cell)
        for dep in dependents.get(cell, ()):
            indeg[dep] -= 1
            if indeg[dep] == 0:
                queue.append(dep)
    if len(order) != len(ast):
        cyclic = sorted(f"{s}!{c}" for (s, c), d in indeg.items() if d > 0)
        raise EstimateTemplateError(f"公式依赖成环：{cyclic[:10]}")
    return order


# ---------------------------------------------------------------- 求值
def _eval(node, values: dict[Cell, Any], warnings: list[dict], at: Cell):
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "ref":
        v = values.get((node[1], node[2]))
        if isinstance(v, str):
            warnings.append(
                {
                    "code": "text_in_arithmetic",
                    "cell": f"{at[0]}!{at[1]}",
                    "message": f"文本值参与四则运算：{node[1]}!{node[2]}",
                }
            )
            return None
        return 0.0 if v is None else v
    if kind == "sumrange":
        _, sheet, col, r1, r2 = node
        total = 0.0
        for r in range(r1, r2 + 1):
            v = values.get((sheet, f"{col}{r}"))
            if isinstance(v, (int, float)):
                total += v
        return total
    if kind == "neg":
        v = _eval(node[1], values, warnings, at)
        return None if v is None else -v
    a = _eval(node[1], values, warnings, at)
    b = _eval(node[2], values, warnings, at)
    if a is None or b is None:
        return None
    if kind == "add":
        return a + b
    if kind == "sub":
        return a - b
    if kind == "mul":
        return a * b
    if b == 0:
        warnings.append(
            {"code": "div_by_zero", "cell": f"{at[0]}!{at[1]}", "message": "除数为 0（对应 Excel #DIV/0!）"}
        )
        return None
    return a / b


def _eval_cell(cell: Cell, node, values: dict[Cell, Any], warnings: list[dict]):
    """单引用公式透传原值（文本工程名照抄；空格按 Excel 语义显示 0），其余走算术求值。"""
    if node[0] == "ref":
        v = values.get((node[1], node[2]))
        return 0.0 if v is None else v
    return _eval(node, values, warnings, cell)


def run(
    inputs: dict[str, float],
    template_code: str = "gsyz_v1",
    rates: dict[str, float] | None = None,
) -> dict:
    """求值入口。

    inputs: {"sheet!coord": 数值}，键须命中模板声明的 211 个输入位
            （或 optional_inputs，如 估概算总表!C48 建设期融资费用）；
            未声明的键忽略并 warning；缺省的输入位按 0 计（Excel 空格语义）。
    rates:  {"reserve_rate": 0.05}；软区间外只 warning，不拒算；
            未声明的键忽略并 warning（unknown_rate），对应费率按模板默认值计。
    返回:   {sheets, totals, indicators, warnings, rates_used}
    """
    comp = _compiled(template_code)
    tpl = comp["tpl"]
    warnings: list[dict] = []

    declared = {i["cell"] for i in tpl["inputs"]} | set(tpl.get("optional_inputs", []))
    # 静态文本源先入求值环境：515 条公式里 10 条是文本透传（总表 B25~B33、B35
    # 引用分析表的工程名称），目标格是模板静态文本。这些源格不属于计算结果，
    # 输出时按 static_keys 剔除，不混进 sheets。
    values: dict[Cell, Any] = dict(comp["static_text"])
    static_keys = set(values)
    for key, val in (inputs or {}).items():
        norm = key.replace("$", "")
        if norm not in declared:
            warnings.append(
                {"code": "unknown_input", "cell": norm, "message": "未声明的输入位，已忽略（引擎只写声明位）"}
            )
            continue
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            raise EstimateTemplateError(f"输入位 {norm} 的值必须是数值，实为 {type(val).__name__}")
        sheet, coord = norm.split("!", 1)
        values[(sheet, coord)] = float(val)

    # 费率格：运行期按 rates 实例化公式（模板不写死——用户裁决）
    ast = dict(comp["ast"])
    rates = rates or {}
    rate_params = tpl.get("rate_params", {})
    # rates 未知键与 inputs 的 unknown_input 对称披露（#130）：键名拼错（如驼峰
    # reserveRate）时对应费率会静默回落模板默认值——金额随之变动却零提示。
    for rname in rates:
        if rname not in rate_params:
            warnings.append(
                {"code": "unknown_rate", "cell": rname,
                 "message": "未声明的费率参数，已忽略——对应费率按模板默认值计，本次生效值见 rates_used"}
            )
    # 本次实际生效的费率（含未传参数回落的默认值）。调用方审计记录必须落这个，
    # 不能回显入参（#130：入参写 1%、实际按默认 5% 算，审计失真 1.5 亿量级）。
    rates_used: dict[str, float] = {}
    for pname, p in rate_params.items():
        rate = rates.get(pname, p["default"])
        if not isinstance(rate, (int, float)) or isinstance(rate, bool):
            raise EstimateTemplateError(f"费率 {pname} 必须是数值，实为 {type(rate).__name__}")
        rates_used[pname] = float(rate)
        lo, hi = p.get("soft_range", (None, None))
        if lo is not None and not (lo <= rate <= hi):
            warnings.append(
                {
                    "code": "rate_out_of_range",
                    "cell": p["cell"],
                    "message": f"{pname}={rate:g} 超出常规区间 {lo:g}~{hi:g}，按输入照算（费率可调、不设硬闸）",
                }
            )
        sheet, coord = p["cell"].split("!", 1)
        formula = p["formula_template"].replace("{rate}", decimal_literal(rate))
        ast[(sheet, coord)] = _Parser(formula, sheet).parse()

    # 模板修正披露（只披露标记 runtime_warning 的修正，如 F30 错引）
    for fix in tpl.get("fixes", []):
        if fix.get("runtime_warning"):
            for ch in fix["changes"]:
                warnings.append(
                    {
                        "code": "template_fix",
                        "cell": ch["cell"],
                        "message": f"原表缺陷已修正：{ch['before']} → {ch['after']}（{fix['id']}）",
                    }
                )

    for cell in _topo_order(ast):
        values[cell] = _eval_cell(cell, ast[cell], values, warnings)

    sheets_out: dict[str, dict[str, Any]] = {}
    for (sheet, coord), v in values.items():
        if (sheet, coord) in static_keys:
            continue  # 模板静态文本不是计算结果
        sheets_out.setdefault(sheet, {})[coord] = v

    totals = {
        code: {
            "label": label,
            "cell": f"估概算总表!{coord}",
            "value": values.get(("估概算总表", coord)),
        }
        for code, (label, coord) in {
            "project_cost": ("工程费用（一）", "C5"),
            "other_cost": ("工程建设其他费用（二）", "C45"),
            "reserve_fee": ("工程预备费（三）", "C46"),
            "static_total": ("建设静态总投资（四）", "C47"),
            "financing_fee": ("建设期融资费用（五）", "C48"),
            "initial_working_capital": ("铺底流动资金（六）", "C49"),
            "dynamic_total": ("建设动态总投资（七）", "C50"),
        }.items()
    }

    indicators = []
    tech = next(s for s in tpl["sheets"] if s["name"] == "经济技术指标")
    for row in tech["rows"]:
        if row["role"] != "row":
            continue
        coord = f"D{row['row']}"
        indicators.append(
            {
                "seq": row["seq"],
                "label": row["label"],
                "unit": row["static"].get("C"),
                "value": values.get(("经济技术指标", coord)),
            }
        )

    return {"sheets": sheets_out, "totals": totals, "indicators": indicators,
            "warnings": warnings, "rates_used": rates_used}


def _static_text_pass(tpl: dict) -> dict[Cell, str]:
    """模板静态文本源（供文本透传公式取值）。

    设计取舍：515 条公式里有 10 条文本透传（估概算总表 B25~B33、B35 引用分析表的
    工程名称），目标格是模板静态文本。求值前把这些静态文本注入 values，
    透传公式即可原样取到。
    """
    out: dict[Cell, str] = {}
    for s in tpl["sheets"]:
        for row in s["rows"]:
            for col, v in row.get("static", {}).items():
                if isinstance(v, str):
                    out[(s["name"], f"{col}{row['row']}")] = v
    return out


# ------------------------------------------------------------------ 列头量纲（渲染与接口共用）

# 列头量纲：「费用\n（万元）」→ 万元；「占总投资比例\n（%）」→ %；「单方指标\n（元/x）」→ 元/x
_UNIT_IN_HEADER = re.compile(r"[（(]([^）)]{1,12})[）)]")
RATIO_UNITS = ("%", "％", "‰")


def column_units(sheet: dict) -> dict[str, str | None]:
    """从 role=="header" 行的静态文本反解每列量纲（先出现的表头不被后来的覆盖）。

    WS10-P14：渲染器的数字格式与接口的 value_scale / unit 用**同一个**判据 —— 此前渲染器
    按公式类别给格式，`估概算总表!D50`（=D47+D48+D49，占比）落进 add_chain 拿了金额格式。
    """
    out: dict[str, str | None] = {}
    for r in sheet.get("rows", []):
        if r.get("role") != "header":
            continue
        for col, text in (r.get("static") or {}).items():
            if col in out or not isinstance(text, str):
                continue
            m = _UNIT_IN_HEADER.search(text)
            out[col] = m.group(1).strip() if m else None
    return out
