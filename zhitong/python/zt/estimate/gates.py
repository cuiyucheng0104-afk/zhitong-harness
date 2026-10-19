# 来源：engine-service/app/engine/estimate_gates.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""概算的四道拦截闸（WS25-b，issue #945）—— compute 与 reportform/render 共用的同一份判断。

    必填闸        11 个必填指标位（经济技术指标表的输入位）有缺
    P04 面积闸    总建筑面积格为空或 ≤ 0（没有确认放行口）
    P05 面积对账  槽位合计与原文总建筑面积相差 > 容差（可由用户确认放行）
    全零闸        静态投资合计（估概算总表!C47）恰好为 0

每道闸是一个**不抛异常**的纯函数：通过回 None，不通过回 GateFinding(code, cell, message)。
怎么处置由调用方定 —— 这正是抽出来的理由：
  · compute（概算向导出表）遇到 GateFinding 抛 422，detail 就是 `message`，与抽取前逐字相同；
  · reportform/render（报表管理出表）不拒绝，降为「草稿」并把同一句话写进理由（spec WS25 §3.4）。
另写一套「报表版」的闸，就会多出一个能产出「完整」却没过面积闸的出表入口（铁律 2 的延伸，C-R13）。

**顺序**由调用方照 ORDER 执行，并由测试钉死：面积闸必须在全零闸之前 —— 总建筑面积为 0 时
室外成本照样让 C47 ≠ 0，全零闸拦不住；P05 对账同理。
只读模板与策略，零 LLM、不连库（铁律 2、铁律 4）。
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from zt.estimate import policy as estimate_policy
from zt.estimate.checks import cell_value, is_num
from zt.estimate.engine import load_template

# 与 estimate_extract.ROOT_SHEET 同值。这里不 import estimate_extract：它在模块级 import
# app.llm_client，报表渲染这条零 LLM 的链路不该为一个表名把 LLM 客户端拖进来。
# 两边算出的必填位清单必须一致，由 tests/test_estimate_gates_refactor.py 钉住。
ROOT_SHEET = "经济技术指标"

REQUIRED = "required_inputs_missing"
AREA_GATE = "area_gate_failed"
AREA_MISMATCH = "area_total_mismatch"
ALL_ZERO = "all_zero_result"
# compute 抛 422 的先后、render 记理由的先后，都按这个顺序
ORDER = (REQUIRED, AREA_GATE, AREA_MISMATCH, ALL_ZERO)


@dataclass(frozen=True)
class GateFinding:
    code: str
    cell: str | None
    message: str               # 完整说明：compute 原样作 422 的 detail
    facts: str | None = None   # 只有 P05 有：差额事实句，用户确认后拼进 area_mismatch_acknowledged


@lru_cache(maxsize=4)
def required_cells(template_code: str) -> tuple[str, ...]:
    """必填输入位 = 模板「经济技术指标」表的输入位（gsyz_v1 实测 11 个），按模板声明顺序。"""
    tpl = load_template(template_code)
    return tuple(i["cell"] for i in tpl["inputs"] if i["cell"].startswith(ROOT_SHEET + "!"))


def required(cells, supplied: set[str]) -> GateFinding | None:
    """必填闸。`supplied` 是本次提交的键（已去 `$`）；显式填 0 也算已填（0 由面积闸管）。"""
    missing = [c for c in cells if c not in supplied]
    if not missing:
        return None
    return GateFinding(REQUIRED, None, "缺少必填输入位：" + ",".join(missing))


def area_gate_absent(pol: dict) -> dict | None:
    """模板没声明面积闸 → 一条 info 告警（不是闸：没有闸可跑，只能如实说出来）。"""
    if estimate_policy.area_gate(pol) is not None:
        return None
    return {"code": "area_gate_absent", "cell": None,
            "message": "本模板未声明面积闸（策略缺 area_gate），总建筑面积为 0 的概算不会被拦下，"
                       "请人工核对经济技术指标。"}


def area_gate(pol: dict, result: dict) -> GateFinding | None:
    """P04：总建筑面积格为空或 ≤0。没有确认放行口（D5=0 的房建概算没有可交付的口径）。

    必须在全零闸**之前**跑：Ae_K / Ce_K 的总建筑面积 = 0，金额全部来自「室外面积 = 用地面积」
    的室外成本，C47 ≠ 0，全零闸拦不住它。模板没声明面积闸时回 None（由 area_gate_absent 披露）。
    """
    gate = estimate_policy.area_gate(pol)
    if gate is None:
        return None
    v = cell_value(result, gate["cell"])
    if is_num(v) and v > 0:
        return None
    return GateFinding(
        AREA_GATE, gate["cell"],
        (f"{gate.get('label') or '总建筑面积'}（{gate['cell']}）为 {v if v is not None else '空'}："
         "房建概算没有建筑面积就没有可交付的口径（单方指标全部失真，金额只剩室外部分）。"
         "请回第 2 步填写单体面积（地下室 / 各栋楼 / 构筑物）后再生成。"))


def area_reconcile(pol: dict, result: dict, area_checks: dict) -> GateFinding | None:
    """P05：槽位合计与原文总建筑面积相差 > 容差。确认与否由调用方判（compute 认 acks，render 还要核有效性）。"""
    rec = estimate_policy.area_reconcile(pol)
    if rec is None:
        return None
    src = area_checks.get(rec["check_key"])
    if src is None:
        return None
    slot_sum = cell_value(result, rec["slot_sum_cell"])
    slot_sum = float(slot_sum) if is_num(slot_sum) else 0.0
    tol = float(rec.get("tolerance") or 0.01)
    diff = abs(slot_sum - src) / src
    if diff <= tol:
        return None
    what = (f"单体槽位合计 {slot_sum:.2f} ㎡ 与原文总建筑面积 {src:.2f} ㎡ 相差 {diff:.2%}"
            f"（阈值 {tol:.0%}）")
    return GateFinding(
        AREA_MISMATCH, rec["slot_sum_cell"],
        (f"{what}：多栋项目被截成模板槽位数时会少算面积。请回第 2 步「单体归位」把"
         "未归位的单体并入槽位；确属口径差异（如原文总面积含架空层）时，在第 5 步勾选"
         "确认并写明理由后再生成。"),
        facts=what)


def mismatch_acknowledged(finding: GateFinding, reason: str) -> dict:
    """P05 已由用户确认 → 放行，但出一条需复核告警（judge_quality 据此给 needs_review）。"""
    return {"code": "area_mismatch_acknowledged", "cell": finding.cell,
            "message": f"{finding.facts}，已由用户确认：{reason}。本表按需复核处理。"}


def all_zero(result: dict) -> GateFinding | None:
    """全零闸：静态投资合计恰好为 0。

    只挡精确的 0，不挡 None —— None 是 #DIV/0! 传播（另一种病，由 div_by_zero 披露），
    把它一起拦会把可诊断的异常压成一句笼统的报错。闸设在产出侧：既能挡「一个成本位都没填」，
    也能挡「填了但全是 0」，且不必枚举 150 个成本位。
    """
    st = result["totals"].get("static_total") or {}
    if st.get("value") != 0:
        return None
    return GateFinding(
        ALL_ZERO, st.get("cell") or "估概算总表!C47",
        "概算结果为全零：静态投资合计（估概算总表!C47）为 0，"
        "说明 150 个成本输入位一个都没填（或全填了 0）。"
        "请先完成费用明细——可调 POST /engine/estimate/suggest 用指标基准"
        "推算建议值，逐条确认后再回来生成。"
        "全零概算表对造价员是误导性成功，此处拒绝出表。")
