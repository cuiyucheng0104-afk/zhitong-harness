# 来源：engine-service/app/engine/estimate_policy.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""概算模板级策略（WS10 共同底座，issue #722）。

策略数据在 `data/estimate_templates/<template_code>.policy.json`，随引擎镜像发布：
不进库、不需要迁移（#696「存量库拿不到迁移」与它无关）。代码里不再硬编码格号 ——
改口径改 JSON，并由 tests/test_estimate_policy.py 钉住。

这里放的是「模板的样本私有结构」带来的口径，逐项对应 WS10 的问题编号：

  block_kinds    P01 语义键：把「1#楼 / 2#楼 / 3#楼」这类样本私有的块归并成
                 basement / above_ground / structure，同语义键下的基准行才视为同一指标的样本成员
  scaling        P02 样本包干额（土地费、配套费、其他费）不按面积放大
  building_functions  P01 业态：仓储 / 工业不出幕墙、精装修参考值（D48）
  slots / area_* P04 / P05 面积闸、单体槽位与总面积对账（D46）
  extract_*      P05 / P08 抽取口径（父级路径、定义、同义词、分组）；WS29-d 加输出预算与建筑密度提示项

策略是**只读**的：`load_policy` 有缓存，调用方不许原地改；测试要改就 deepcopy。
"""
from __future__ import annotations

import copy
import json
import re
from functools import lru_cache

from zt.estimate.engine import (
    _TEMPLATE_CODE_RE,
    _TPL_DIR,
    EstimateTemplateError,
    load_template,
)

POLICY_SUFFIX = ".policy.json"

SCALING_AREA = "area"
SCALING_LUMP_SUM = "lump_sum"


@lru_cache(maxsize=4)
def _load_policy_cached(template_code: str) -> dict:
    # 与 load_template 同一套两道闸（issue #128）：白名单正则 + 解析后仍须落在模板目录内。
    # 这里复用它的常量而不是另写一份，两处判法漂移就是一个越界读。
    if not _TEMPLATE_CODE_RE.match(template_code or ""):
        raise EstimateTemplateError(
            f"模板编码不合规（只接受 [A-Za-z0-9_-]{{1,64}}）：{template_code!r}")
    path = _TPL_DIR / f"{template_code}{POLICY_SUFFIX}"
    try:
        path.resolve().relative_to(_TPL_DIR.resolve())
    except ValueError:
        raise EstimateTemplateError(f"模板编码越界（超出模板目录）：{template_code!r}")
    if not path.is_file():
        # 没有策略文件的模板照样能算，只是没有这些口径；调用方各自按「缺席」出 info
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_policy(template_code: str = "gsyz_v1") -> dict:
    """模板策略（只读）。模板没有策略文件时回 `{}`，调用方按缺席处理、不报错。"""
    return _load_policy_cached(template_code)


def policy_version(policy: dict) -> str | None:
    return (policy or {}).get("policy_version")


# ------------------------------------------------------------------ P01 语义键

def _block_rules(policy: dict) -> list[tuple[str, re.Pattern]]:
    rules = ((policy or {}).get("block_kinds") or {}).get("rules") or []
    return [(r["kind"], re.compile(r["pattern"])) for r in rules]


def block_kind_of(policy: dict, label: str | None) -> str | None:
    """单项工程行名 → block_kind。只匹配模板自己的行名（全等正则），不是模糊匹配。"""
    if not label:
        return None
    for kind, rx in _block_rules(policy):
        if rx.search(label):
            return kind
    return None


def semantic_keys(template_code: str, policy: dict | None = None) -> dict[tuple[str, int], str]:
    """模板每个带行名的 row → 语义键。

    块表（1.建筑工程费 / 2.安装工程费）里位于单项工程块下的叶子行：
        {表名}/{block_kind}/{叶子行名}
    其余行：{表名}/{行名}

    键里带表名：spec 写的是 `{block_kind}/{叶子行名}`，今天两张块表的叶子名互不相交，
    两种写法结果一样；但哪天建筑表也出一个「电梯工程」，不带表名就会把安装的单方
    套到建筑上。块行名不命中任何规则时退成 {表名}/{块行名}/{叶子行名} —— 宁可一块一个键
    不合并，也不把不认识的块并进某个 kind（铁律 3）。
    """
    pol = load_policy(template_code) if policy is None else policy
    tpl = load_template(template_code)
    block_sheets = set(((pol or {}).get("block_kinds") or {}).get("sheets") or [])
    out: dict[tuple[str, int], str] = {}
    for s in tpl["sheets"]:
        name = s["name"]
        block_label: str | None = None
        block_level: int | None = None
        for r in s["rows"]:
            label = r.get("label")
            level = r.get("level")
            if r.get("role") != "row" or not label:
                continue
            if name in block_sheets and isinstance(level, int):
                if level <= 2:
                    # level 1 是表合计行，level 2 是单项工程行；进入新块或离开块
                    block_label = label if level == 2 else None
                    block_level = level if level == 2 else None
                elif block_label is not None and block_level is not None and level > block_level:
                    kind = block_kind_of(pol, block_label)
                    mid = kind if kind else block_label
                    out[(name, r["row"])] = f"{name}/{mid}/{label}"
                    continue
            out[(name, r["row"])] = f"{name}/{label}"
    return out


def block_rows(template_code: str, policy: dict | None = None) -> list[tuple[str, int, str]]:
    """块表里的单项工程行（level 2）→ [(表名, 行号, 行名)]，给「规则恰好覆盖」那条测试用。"""
    pol = load_policy(template_code) if policy is None else policy
    tpl = load_template(template_code)
    block_sheets = set(((pol or {}).get("block_kinds") or {}).get("sheets") or [])
    return [(s["name"], r["row"], r.get("label") or "")
            for s in tpl["sheets"] if s["name"] in block_sheets
            for r in s["rows"] if r.get("role") == "row" and r.get("level") == 2]


def min_sources_for_prefill(policy: dict) -> int:
    v = (policy or {}).get("min_sources_for_prefill")
    return int(v) if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 1


# ------------------------------------------------------------------ P02 缩放方式

def lump_sum_cells(policy: dict) -> dict[str, str | None]:
    """lump_sum 格 → manual_hint。"""
    items = ((policy or {}).get("scaling") or {}).get("lump_sum") or []
    return {i["cell"]: i.get("manual_hint") for i in items}


def scaling_of(policy: dict, cell: str) -> str:
    if cell in lump_sum_cells(policy):
        return SCALING_LUMP_SUM
    return ((policy or {}).get("scaling") or {}).get("default") or SCALING_AREA


def with_scaling(policy: dict, cells, scaling: str) -> dict:
    """返回一份把 `cells` 改成指定缩放方式的策略副本（原策略不动）。

    用途：双源仲裁代码保留给「将来可缩放的多样本」，今天的 gsyz_v1 下 5 表全是
    lump_sum、走不到那条分支；测试靠它把分支重新造出来，否则 13 条双源用例会静默
    变成空断言（spec WS10-P02 验收）。
    """
    out = copy.deepcopy(policy or {})
    sc = out.setdefault("scaling", {})
    cells = set(cells)
    kept = [i for i in sc.get("lump_sum") or [] if i["cell"] not in cells]
    if scaling == SCALING_LUMP_SUM:
        kept.extend({"cell": c, "manual_hint": None} for c in sorted(cells))
    sc["lump_sum"] = kept
    return out


# ------------------------------------------------------------------ P01 业态

def building_function_options(policy: dict) -> list[dict]:
    return [{"value": b["value"], "label": b.get("label") or b["value"]}
            for b in (policy or {}).get("building_functions") or []]


def not_typical_for(policy: dict, building_function: str | None,
                    sheet: str, label: str | None) -> bool:
    """该业态下这一行是否「通常不含」（D48）。严格全等，不做近似。"""
    if not building_function or not label:
        return False
    for b in (policy or {}).get("building_functions") or []:
        if b.get("value") != building_function:
            continue
        return any(t.get("sheet") == sheet and t.get("leaf") == label
                   for t in b.get("not_typical") or [])
    return False


def building_function_label(policy: dict, value: str | None) -> str | None:
    for b in (policy or {}).get("building_functions") or []:
        if b.get("value") == value:
            return b.get("label") or value
    return None


# ------------------------------------------------------------------ P04 / P05 面积与槽位

def area_gate(policy: dict) -> dict | None:
    g = (policy or {}).get("area_gate")
    return g if isinstance(g, dict) and g.get("cell") else None


def slots(policy: dict) -> list[dict]:
    return list((policy or {}).get("slots") or [])


def slot_cells(policy: dict) -> list[str]:
    return [s["cell"] for s in slots(policy)]


_ROOT_REF = re.compile(r"^=\s*经济技术指标!\$?D\$?(\d+)$")


@lru_cache(maxsize=4)
def _slot_label_cells_cached(template_code: str) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    tpl = load_template(template_code)
    pol = load_policy(template_code)
    rows = {(s["name"], r["row"]): r for s in tpl["sheets"] for r in s["rows"]}
    # 各表里「数量列 = 经济技术指标!$D$n」的行，按 (表, n) 归组
    refs: dict[tuple[str, int], list[int]] = {}
    for f in tpl["formulas"]:
        m = _ROOT_REF.match(f["formula"] or "")
        if not m:
            continue
        sheet, coord = f["cell"].split("!", 1)
        row_no = int("".join(ch for ch in coord if ch.isdigit()))
        refs.setdefault((sheet, int(m.group(1))), []).append(row_no)
    out = []
    for cell in slot_cells(pol):
        sheet, coord = cell.split("!", 1)
        n = int("".join(ch for ch in coord if ch.isdigit()))
        names: list[tuple[str, str]] = [(f"{sheet}!B{n}", "")]
        for (ref_sheet, ref_n), row_nos in sorted(refs.items()):
            if ref_n != n or ref_sheet == sheet:
                continue
            # 同一槽位在一张表里引用它的是「单项工程行 + 其下叶子行」，名称格取层级最高
            # （level 最小）的那一行 —— 叶子行名是「建筑工程」之类，不是单体名。
            cands = [rows[(ref_sheet, r)] for r in row_nos if (ref_sheet, r) in rows]
            cands = [r for r in cands if isinstance(r.get("level"), int)]
            if not cands:
                continue
            top = min(cands, key=lambda r: (r["level"], r["row"]))
            names.append((f"{ref_sheet}!B{top['row']}", "工程"))
        out.append((cell, tuple(names)))
    return tuple(out)


def slot_label_cells(template_code: str = "gsyz_v1") -> dict[str, list[tuple[str, str]]]:
    """槽位 → [(名称格, 后缀)]，从模板公式推导，不硬编码格号。

    以 D10 为例：经济技术指标!B10（后缀空）、估概算总表!B12、1.建筑工程费!B24、
    2.安装工程费!B22（单项工程行，后缀「工程」）。渲染时用 slot_labels 覆盖这些格，
    交付表上就不再是样本楼名（WS10-P05）。
    """
    return {cell: list(names) for cell, names in _slot_label_cells_cached(template_code)}


def area_reconcile(policy: dict) -> dict | None:
    r = (policy or {}).get("area_reconcile")
    return r if isinstance(r, dict) and r.get("check_key") else None


def footprint_check(policy: dict) -> dict | None:
    r = (policy or {}).get("footprint_check")
    return r if isinstance(r, dict) and r.get("site_cell") and r.get("footprint_cell") else None


def land_cost_cell(policy: dict) -> str | None:
    return (policy or {}).get("land_cost_cell")


# ------------------------------------------------------------------ P05 / P08 抽取口径

def extract_hints(policy: dict) -> list[dict]:
    return list((policy or {}).get("extract_hints") or [])


def extract_checks(policy: dict) -> list[dict]:
    return list((policy or {}).get("extract_checks") or [])


# 总量核对值之外，extract_checks 里还有只作提示用的百分数（WS29-d：建筑密度）
CHECK_KIND_PERCENT = "percent"


def quantity_checks(policy: dict) -> list[dict]:
    """原文总量（面积）核对项：进 check_values、给槽位对账与分组兜底用。百分数提示项不在内。"""
    return [c for c in extract_checks(policy) if c.get("kind") != CHECK_KIND_PERCENT]


def density_check(policy: dict) -> dict | None:
    """占地缺失时拿来推算提示的建筑密度项（WS29-d，D-R118）；策略没写就是 None，不出提示。"""
    return next((c for c in extract_checks(policy)
                 if c.get("kind") == CHECK_KIND_PERCENT and c.get("hint_for") == "footprint"), None)


# 抽取单次调用的输出预算（D-R119）。策略文件没写时的退路，与 gsyz_v1 的值一致
DEFAULT_EXTRACT_MAX_TOKENS = 6000


def extract_max_tokens(policy: dict) -> int:
    v = (policy or {}).get("extract_max_tokens")
    if isinstance(v, int) and not isinstance(v, bool) and v > 0:
        return v
    return DEFAULT_EXTRACT_MAX_TOKENS


def extract_groups(policy: dict) -> dict[str, dict]:
    return dict((policy or {}).get("extract_groups") or {})


def extract_anchors(policy: dict) -> list[str]:
    """P12：正文超预算时取窗口的关键词锚点（显式列表；同义词由 estimate_extract 另行并入）。"""
    return [a for a in (policy or {}).get("extract_anchors") or [] if isinstance(a, str) and a.strip()]


def slot_level_map(policy: dict) -> dict[str, str]:
    """抽取给的 level（underground / above_ground / structure）→ 槽位 kind。"""
    return dict((policy or {}).get("slot_levels") or {})


# ------------------------------------------------------------------ 对外下发

def public_payload(template_code: str = "gsyz_v1") -> dict:
    """随 GET /engine/estimate/template 下发的策略子集 —— 前端下拉的选项只来自这里。"""
    pol = load_policy(template_code)
    return {
        "policy_version": policy_version(pol),
        "building_functions": building_function_options(pol),
        "not_typical_note": pol.get("not_typical_note"),
        "min_sources_for_prefill": min_sources_for_prefill(pol) if pol else None,
        "slots": [dict(s, label_cells=[c for c, _ in slot_label_cells(template_code).get(s["cell"], [])])
                  for s in slots(pol)],
        "area_reconcile": area_reconcile(pol),
        "lump_sum_cells": sorted(lump_sum_cells(pol)),
        # 前端第 3 步高亮土地费行、第 2 步提示「占地缺失」都按这两个键取格号，不硬编码
        "land_cost_cell": land_cost_cell(pol),
        "footprint": ({"site_cell": footprint_check(pol)["site_cell"],
                       "input_cells": [h["cell"] for h in extract_hints(pol)
                                       if h.get("group") == "footprint"]}
                      if footprint_check(pol) else None),
    }
