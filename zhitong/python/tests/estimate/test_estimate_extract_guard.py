# 来源：engine-service/tests/test_estimate_extract_guard.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""WS10-P05 / P08 / P09（issue #722）：概算规模指标抽取的口径护栏。

P05：候选池就是 11 个样本输入位，prompt 原样下发样本标签（1#楼 / 2#楼 / 3#楼），
     多栋项目静默截成 3 栋，不与原文总建筑面积对账（E3_B：原文 256944.18，槽位合计 128617.91）。
P08：prompt 每行只有「格｜叶子标签｜单位」—— D15 的标签是「A区地块」，模型看不出它是
     「占地面积」下的一格，原文写明的建筑占地面积报成 not_found，detail 恒为 None。
P09：每格只要一个值；同一文件里的 154871.74 与 232497.24 由 LLM 自行选边，confidence 1.0；
     ambiguous 明细用 `:g` 显示成「232497 / 95667」。

LLM 一律打桩（本文件不耗 token）：用例钉的是**引擎自己的确定性逻辑**（prompt 内容、
归位、合并、明细格式），不是模型答得对不对。
"""
from __future__ import annotations

import json
import sys
import re

import pytest

from zt.estimate import extract as ex
from zt.estimate import policy as estimate_policy


class _U:
    prompt_tokens = 1
    completion_tokens = 1
    latency_ms = 1
    model = "stub"
    finish_reason = ""
    cache_hits = 0


# zt 改动：旧用例打桩 estimate_extract.chat；zt 里回答由 agent 给出。_extract_from_text 按旧签名把
# 「说明 + 窗口正文」交给桩（_AGENT），把它的回答交给 ex.extract_from_text 做确定性后处理。
_AGENT = None


def _extract_from_text(file_id, text, specs=None, text_source="text_layer", template_code="gsyz_v1", *,
                       file_name=None):
    pol = estimate_policy.load_policy(template_code)
    window, _st = ex.select_window(text or "", ex.extract_anchors(template_code, pol))
    answer = None
    if text and text.strip():
        prompt = ex._prompt(window, ex.cell_hint_specs(template_code, pol), estimate_policy.extract_checks(pol),
                            bool(estimate_policy.slot_cells(pol)))
        got = _AGENT([{"role": "user", "content": prompt}], max_tokens=ex.extract_max_tokens(template_code, pol))
        raw = got[0] if isinstance(got, tuple) else got
        answer = json.loads(raw) if isinstance(raw, str) else raw
    return ex.extract_from_text(file_id, text, answer, specs, text_source, template_code, file_name=file_name), None


def _set_agent(monkeypatch, fn):
    monkeypatch.setattr(sys.modules[__name__], "_AGENT", fn)


def _stub(monkeypatch, answer: dict, seen: list | None = None):
    def fake_chat(messages, **kw):
        if seen is not None:
            seen.append(messages[0]["content"])
        return json.dumps(answer, ensure_ascii=False), _U()
    _set_agent(monkeypatch, fake_chat)


def _run(monkeypatch, texts_answers: list[tuple[str, dict]]):
    per_file = []
    for i, (text, ans) in enumerate(texts_answers):
        _stub(monkeypatch, ans)
        out, _ = _extract_from_text(f"f{i}", text, None, "text_layer")
        per_file.append(out)
    return ex.merge_extractions(per_file)


def _un(merged, reason=None):
    return [u for u in merged["unresolved"] if reason is None or u["reason"] == reason]


# =================================================================== P08 prompt

def test_prompt_carries_parent_path_definition_and_synonyms(monkeypatch):
    """prompt 里 D15 不再只是「A区地块」：要有父级路径、口径定义、同义词。

    变异：恢复叶子 label（prompt 只放 s['label']）→ 本条转红。
    """
    seen: list[str] = []
    _stub(monkeypatch, {"buildings": [], "checks": {}, "cells": {}}, seen)
    _extract_from_text("f0", "建筑占地面积 5000 ㎡", None)
    p = seen[0]
    assert "经济技术指标!D15｜占地面积 > A区地块" in p
    assert "建筑物底层外墙围合的基底面积" in p           # 口径定义
    assert "建筑基底面积" in p                           # 同义词
    assert "用地面积" in p and "不是建筑占地面积" in p     # D4 的口径把两个面积分开
    # 单体槽位不再逐格下发样本标签 —— 改由单体清单确定性归位（P05）
    assert "经济技术指标!D10｜" not in p
    assert "不要合并、不要只挑前几个" in p
    # P09：一格多值全部列出
    assert "全部列出" in p and "不要自行选择" in p


def test_path_falls_back_to_the_template_row_tree_without_policy():
    """策略没写 extract_hints 的格，路径也不退回叶子名：从模板行树推父级。"""
    assert ex._row_tree_path("gsyz_v1", "经济技术指标!D16") == "占地面积 > B区地块"
    assert ex._row_tree_path("gsyz_v1", "经济技术指标!D4") == "用地面积"
    specs = {s["cell"]: s for s in ex.cell_hint_specs("gsyz_v1", policy={})}
    assert specs["经济技术指标!D15"]["path"] == "占地面积 > A区地块"


def test_llm_json_without_expected_keys_is_502_semantics(monkeypatch):
    """形状不对不是「这份文件没有指标」：抛 AnswerUnparseable（CLI 映射退出码 2；zt 改动：旧版 LLMOutputUnparseable）。"""
    _stub(monkeypatch, {"经济技术指标!D4": {"value": "1", "quote": "x"}})
    with pytest.raises(ex.AnswerUnparseable):
        _extract_from_text("f0", "用地面积 1", None)


# =================================================================== P08 分组与总量

def test_footprint_total_only_goes_to_group_head_and_rest_total_only(monkeypatch):
    """原文只写「建筑占地面积」不分地块：放 D15 并带说明，D16 落 total_only_no_partition。"""
    text = "本项目用地面积 12000 ㎡，建筑占地面积 5000 ㎡。"
    m = _run(monkeypatch, [(text, {
        "buildings": [], "cells": {},
        "checks": {"footprint_area": [{"value": "5000", "quote": "建筑占地面积 5000 ㎡"}]}})])
    d15 = next(c for c in m["candidates"] if c["cell"] == "经济技术指标!D15")
    assert d15["value"] == 5000.0 and d15["note"] and "首位" in d15["note"]
    assert d15["needs_manual"] is True and d15["confidence"] == 1.0
    d16 = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D16")
    assert d16["reason"] == "total_only_no_partition"


def test_scope_total_hit_is_treated_like_a_group_total(monkeypatch):
    m = _run(monkeypatch, [("占地 5000", {"buildings": [], "checks": {}, "cells": {
        "经济技术指标!D16": [{"value": "5000", "quote": "占地 5000", "scope": "total"}]}})])
    assert [c["cell"] for c in m["candidates"]] == ["经济技术指标!D15"]


def test_partition_values_win_over_the_group_total(monkeypatch):
    m = _run(monkeypatch, [("A区占地3000 B区占地2000 建筑占地5000", {
        "buildings": [], "checks": {"footprint_area": [{"value": "5000", "quote": "建筑占地5000"}]},
        "cells": {"经济技术指标!D15": [{"value": "3000", "quote": "A区占地3000"}],
                  "经济技术指标!D16": [{"value": "2000", "quote": "B区占地2000"}]}})])
    got = {c["cell"]: c["value"] for c in m["candidates"]}
    assert got["经济技术指标!D15"] == 3000.0 and got["经济技术指标!D16"] == 2000.0


def test_parking_total_only_is_not_found_with_a_specific_reason(monkeypatch):
    """停车位分组不允许只有总量（地面 / 地下口径不同）：两格都 not_found，detail 写明原因。"""
    m = _run(monkeypatch, [("机动车停车位 400 辆", {"buildings": [], "checks": {}, "cells": {
        "经济技术指标!D19": [{"value": "400", "quote": "机动车停车位 400 辆", "scope": "total"}]}})])
    for cell in ("经济技术指标!D19", "经济技术指标!D20"):
        u = next(u for u in m["unresolved"] if u["cell"] == cell)
        assert u["reason"] == "not_found" and "只有总量无法分区" in u["detail"]


def test_not_found_detail_distinguishes_unmentioned_and_out_of_window(monkeypatch):
    m = _run(monkeypatch, [("短文本", {"buildings": [], "checks": {}, "cells": {}})])
    d4 = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D4")
    assert d4["detail"] == "原文未提及"
    long_text = "x" * (ex.MAX_TEXT_CHARS + 10)
    m2 = _run(monkeypatch, [(long_text, {"buildings": [], "checks": {}, "cells": {}})])
    d4b = next(u for u in m2["unresolved"] if u["cell"] == "经济技术指标!D4")
    assert "窗口外未检索" in d4b["detail"]


# =================================================================== P05 单体归位

def _building(name, level, area):
    # WS29-d：面积核验不过的单体不再自动归位，所以引文要像真的一样带上面积（改前引文只有单体名）
    return {"name": name, "level": level, "area": str(area), "quote": f"{name} {area}㎡"}


def _src(bs) -> str:
    """把单体的引文拼成原文，让引文核验真的能过。"""
    return "；".join(b["quote"] for b in bs)


def test_buildings_beyond_slots_become_unmapped(monkeypatch):
    """5 栋地上楼 → 前 3 栋按出现顺序归 D10/D11/D12，第 4、5 栋落 unmapped_building，不猜、不合并。

    变异：把超出槽位的单体静默丢掉（不进 unresolved）→ 本条转红。
    """
    bs = [_building(f"{i}#楼", "above_ground", 10000 + i) for i in range(1, 6)]
    bs.insert(0, _building("地下室", "underground", 30000))
    bs.append(_building("构筑物", "structure", 500))
    text = _src(bs)
    m = _run(monkeypatch, [(text, {"buildings": bs, "checks": {}, "cells": {}})])
    cand = {c["cell"]: c for c in m["candidates"]}
    assert cand["经济技术指标!D7"]["value"] == 30000.0
    assert [cand[f"经济技术指标!D{r}"]["building_names"] for r in (10, 11, 12)] == [
        ["1#楼"], ["2#楼"], ["3#楼"]]
    assert cand["经济技术指标!D13"]["value"] == 500.0
    unmapped = _un(m, "unmapped_building")
    assert [u["label"] for u in unmapped] == ["4#楼", "5#楼"]
    assert all(u["cell"] is None and "超出模板槽位" in u["detail"] for u in unmapped)
    slots = {b["name"]: b["slot"] for b in m["buildings"]}
    assert slots["4#楼"] is None and slots["1#楼"] == "经济技术指标!D10"
    # 第二个地下室槽位没有单体 —— 落 not_found，而不是把别的单体塞进去
    assert next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D8")["reason"] == "not_found"


def test_extract_flags_area_total_mismatch(monkeypatch):
    """槽位合计与原文总建筑面积差 >1% → area_total_mismatch（E3_B：256944.18 vs 128617.91）。"""
    bs = [_building(f"{i}#楼", "above_ground", 40000) for i in range(1, 6)]
    m = _run(monkeypatch, [("总建筑面积 256944.18 ㎡；" + _src(bs), {
        "buildings": bs, "cells": {},
        "checks": {"gross_building_area": [{"value": "256944.18", "quote": "总建筑面积 256944.18 ㎡"}]}})])
    w = next(w for w in m["warnings"] if w["code"] == "area_total_mismatch")
    assert w["slot_sum"] == 120000.0 and w["source_area"] == 256944.18
    assert "2 个单体未归位" in w["message"]
    cv = next(c for c in m["check_values"] if c["key"] == "gross_building_area")
    assert cv["value"] == 256944.18 and cv["confidence"] == 1.0


def test_no_mismatch_warning_when_slots_add_up(monkeypatch):
    bs = [_building("1#楼", "above_ground", 60000), _building("地下室", "underground", 40000)]
    m = _run(monkeypatch, [("总建筑面积 100000；" + _src(bs), {
        "buildings": bs, "cells": {},
        "checks": {"gross_building_area": [{"value": "100500", "quote": "总建筑面积 100000"}]}})])
    assert "area_total_mismatch" not in {w["code"] for w in m["warnings"]}


def test_underground_total_without_building_list_goes_to_first_basement_slot(monkeypatch):
    m = _run(monkeypatch, [("地下建筑面积 30000", {
        "buildings": [], "cells": {},
        "checks": {"underground_area": [{"value": "30000", "quote": "地下建筑面积 30000"}]}})])
    d7 = next(c for c in m["candidates"] if c["cell"] == "经济技术指标!D7")
    assert d7["value"] == 30000.0 and "首个槽位" in d7["note"]
    assert next(u for u in m["unresolved"]
                if u["cell"] == "经济技术指标!D8")["reason"] == "total_only_no_partition"


def test_same_building_twice_across_files_is_deduped_but_conflicts_are_not(monkeypatch):
    a = {"buildings": [_building("1#楼", "above_ground", 5000)], "checks": {}, "cells": {}}
    b = {"buildings": [_building("1#楼", "above_ground", 5000), _building("2#楼", "above_ground", 6000)],
         "checks": {}, "cells": {}}
    m = _run(monkeypatch, [(_src(a["buildings"]), a), (_src(b["buildings"]), b)])
    assert [b["name"] for b in m["buildings"]] == ["1#楼", "2#楼"]
    c = {"buildings": [_building("1#楼", "above_ground", 5200)], "checks": {}, "cells": {}}
    m2 = _run(monkeypatch, [(_src(a["buildings"]), a), (_src(c["buildings"]), c)])
    amb = _un(m2, "ambiguous")
    assert len(amb) == 1 and amb[0]["label"] == "1#楼" and len(amb[0]["candidates"]) == 2


# =================================================================== P09 一格多值

def test_single_file_two_values_is_ambiguous_with_both_quotes(monkeypatch):
    """同一份文件里两个用地面积 → ambiguous，带两条引文；不再由 LLM 选边后 confidence 1.0 交出。

    变异：每格只取第一个值 → 出候选 154871.74，本条转红。
    """
    text = "规划用地面积 154871.74 ㎡；净用地面积 232497.24 ㎡"
    m = _run(monkeypatch, [(text, {"buildings": [], "checks": {}, "cells": {"经济技术指标!D4": [
        {"value": "154871.74", "quote": "规划用地面积 154871.74 ㎡"},
        {"value": "232497.24", "quote": "净用地面积 232497.24 ㎡"}]}})])
    assert "经济技术指标!D4" not in {c["cell"] for c in m["candidates"]}
    amb = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D4")
    assert amb["reason"] == "ambiguous"
    assert {c["value"] for c in amb["candidates"]} == {154871.74, 232497.24}
    assert {c["quote"] for c in amb["candidates"]} == {"规划用地面积 154871.74 ㎡",
                                                       "净用地面积 232497.24 ㎡"}


def test_ambiguous_detail_keeps_the_decimals(monkeypatch):
    """明细保留完整小数（E5_BC_multi：232497.24 / 95666.98）。变异：恢复 `:g` → 本条转红。"""
    # 引文里刻意不含数字：明细里的 232497.24 只能来自数值格式化本身。第一版引文里带着
    # 数字，恢复 `:g` 的变异照样全绿（数字从引文里被读到）—— 夹具够不到失败分支。
    m = _run(monkeypatch, [
        ("用地面积见附表一", {"buildings": [], "checks": {}, "cells": {
            "经济技术指标!D4": [{"value": "232497.24", "quote": "用地面积见附表一"}]}}),
        ("用地面积见附表二", {"buildings": [], "checks": {}, "cells": {
            "经济技术指标!D4": [{"value": "95666.98", "quote": "用地面积见附表二"}]}}),
    ])
    amb = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D4")
    assert "232497.24（" in amb["detail"] and "95666.98（" in amb["detail"]
    assert "用地面积见附表一" in amb["detail"]           # 附引文


def test_same_value_twice_is_not_ambiguous(monkeypatch):
    text = "用地面积 12000 ㎡ …… 总用地 12000 ㎡"
    m = _run(monkeypatch, [(text, {"buildings": [], "checks": {}, "cells": {"经济技术指标!D4": [
        {"value": "12000", "quote": "总用地 1万2"},            # 引文改写，未命中原文
        {"value": "12000", "quote": "用地面积 12000 ㎡"}]}})])
    d4 = next(c for c in m["candidates"] if c["cell"] == "经济技术指标!D4")
    assert d4["value"] == 12000.0 and d4["confidence"] == 1.0   # 取原文命中的那条
    assert not _un(m, "ambiguous")


def test_merge_candidates_keeps_its_two_tuple_contract(monkeypatch):
    _stub(monkeypatch, {"buildings": [], "checks": {}, "cells": {
        "经济技术指标!D4": [{"value": "12000", "quote": "用地面积 12000"}]}})
    out, _ = _extract_from_text("f0", "用地面积 12000", None)
    cands, unresolved = ex.merge_candidates(ex.root_input_specs(), [out])
    assert [c["cell"] for c in cands] == ["经济技术指标!D4"]
    assert len(unresolved) == 10


def test_every_candidate_needs_manual(monkeypatch):
    """铁律 2：包括单体归位出来的槽位候选、总量兜底放首位的候选，needs_manual 恒 True。"""
    bs = [_building("1#楼", "above_ground", 5000)]
    m = _run(monkeypatch, [(_src(bs) + " 占地 900", {
        "buildings": bs, "cells": {},
        "checks": {"footprint_area": [{"value": "900", "quote": "占地 900"}]}})])
    assert len(m["candidates"]) == 2
    assert all(c["needs_manual"] is True for c in m["candidates"])


def test_slots_come_from_the_policy():
    assert estimate_policy.slot_cells(estimate_policy.load_policy("gsyz_v1")) == [
        "经济技术指标!D7", "经济技术指标!D8", "经济技术指标!D10",
        "经济技术指标!D11", "经济技术指标!D12", "经济技术指标!D13"]


# =================================================================== WS10-P10 引文核数值（issue #761）
#
# 改前：`_PUNCT` 把 `. , -` 一起删，原文「95666.98」与引文「9566.698」归一化后都是「9566698」，
# 差 10 倍照样 confidence 1.0；value 从不和引文比；区间「1~2万」解析成 1。

from zt.estimate import evidence as evidence_check  # noqa: E402


@pytest.mark.parametrize("source,quote,expect", [
    ("总建筑面积 95666.98 ㎡", "总建筑面积 9566.698 ㎡", False),     # 小数点挪位
    ("总建筑面积 95666.98 ㎡", "总建筑面积 95666.98 ㎡", True),
    ("用地面积 12,000 ㎡", "用地面积 1,2000 ㎡", False),              # 逗号挪位（不是千分位）
    ("用地面积 12,000 ㎡", "用地面积 12000 ㎡", True),                # 千分位与无千分位等价
    ("地块 2020-2021 号", "地块 20202021 号", False),                 # 连字符不能被吞
])
def test_quote_in_source_keeps_decimal_point_comma_and_hyphen(monkeypatch, source, quote, expect):
    """小数点 / 逗号 / 连字符护栏（端到端走 extract_from_text，原文归一化也在被测范围内）。

    value 取引文里的数，所以只有「引文是否在原文」这一项决定 confidence。
    变异：原文与引文都退回旧 `_norm`（去掉 `.,-`）→ 第一 / 三 / 五条转红。
    """
    value = re.findall(r"[\d.,-]+\d", quote)[0].replace(",", "")
    m = _run(monkeypatch, [(source, {"buildings": [], "cells": {}, "checks": {
        "gross_building_area": [{"value": value, "quote": quote}]}})])
    cv = next(c for c in m["check_values"] if c["key"] == "gross_building_area")
    assert cv["verification"]["quote_in_source"] is expect


def test_value_must_appear_in_quote(monkeypatch):
    """引文命中原文、但 value 与引文里的数不符（差 10 倍）→ value_in_quote=False、confidence 0.0。

    夹具要求引文**命中**原文（否则 confidence 0 是 quote_in_source 给的，这条就考不到 value 核验）。
    变异：去掉 value_in_quote 判据（只看引文命中）→ 本条转红。
    """
    text = "本项目总建筑面积 95666.98 ㎡，其中地上 60000 ㎡。"
    m = _run(monkeypatch, [(text, {"buildings": [], "cells": {}, "checks": {
        "gross_building_area": [{"value": "9566.698", "quote": "总建筑面积 95666.98 ㎡"}]}})])
    cv = next(c for c in m["check_values"] if c["key"] == "gross_building_area")
    assert cv["verification"] == {"quote_in_source": True, "value_in_quote": False, "mapping": "label"}
    assert cv["confidence"] == 0.0
    # 对照：value 与引文一致才 1.0（正文换一个字：同文件同正文会命中共用助手的缓存，C18）
    m2 = _run(monkeypatch, [(text + "\n", {"buildings": [], "cells": {}, "checks": {
        "gross_building_area": [{"value": "95666.98", "quote": "总建筑面积 95666.98 ㎡"}]}})])
    cv2 = next(c for c in m2["check_values"] if c["key"] == "gross_building_area")
    assert cv2["confidence"] == 1.0 and cv2["verification"]["value_in_quote"] is True


def test_verify_candidate_rejects_9566_698_against_95666_98():
    """spec 生产取证点名的那一条：容器内直接调 verify_candidate，9566.698 必须判不通过。"""
    src = evidence_check.norm_text("总建筑面积 95666.98 ㎡")
    v = ex.verify_candidate(9566.698, "总建筑面积 95666.98 ㎡", src, ["总建筑面积"])
    assert v["value_in_quote"] is False and ex._confidence(v) == 0.0


@pytest.mark.parametrize("value,quote,expect", [
    (95700.0, "总建筑面积约 9.57万㎡", True),        # 带「万」：按引文里那个数自己的倍率
    (9.57, "总建筑面积约 9.57万㎡", False),          # 没乘倍率的 9.57 不是引文的值
    (10000.0, "机动车位 1~2万 个", True),            # 区间写法：1 继承末尾倍率
    (1.0, "机动车位 1~2万 个", False),
])
def test_value_in_quote_uses_each_numbers_own_scale(value, quote, expect):
    v = ex.verify_candidate(value, quote, evidence_check.norm_text(quote), ["机动车位", "总建筑面积"])
    assert v["value_in_quote"] is expect


@pytest.mark.parametrize("raw,expect", [
    ("1~2万", 10000.0),
    ("1-2万", 10000.0),
    ("1至2万", 10000.0),
    ("1.5万", 15000.0),
    ("12000", 12000.0),
])
def test_parse_quantity_range_inherits_the_trailing_scale(raw, expect):
    """变异：删掉区间继承（_RANGE_TAIL）→ 前三条转红（改前 `1~2万` 得 1.0）。"""
    assert ex.parse_quantity(raw) == expect


def test_quote_without_the_cells_label_is_semantic_mapping(monkeypatch):
    """引文里没有本位标签 / 同义词 → mapping=semantic（前端「全选」不勾它）。"""
    m = _run(monkeypatch, [("规划净用地 12000 ㎡", {"buildings": [], "checks": {}, "cells": {
        "经济技术指标!D4": [{"value": "12000", "quote": "规划净用地 12000 ㎡"}]}})])
    d4 = next(c for c in m["candidates"] if c["cell"] == "经济技术指标!D4")
    assert d4["verification"]["mapping"] == "semantic"
    assert d4["confidence"] == 1.0          # 核验两项都过；mapping 不压 confidence，只影响「全选」
    m2 = _run(monkeypatch, [("总用地面积 12000 ㎡", {"buildings": [], "checks": {}, "cells": {
        "经济技术指标!D4": [{"value": "12000", "quote": "总用地面积 12000 ㎡"}]}})])
    assert next(c for c in m2["candidates"] if c["cell"] == "经济技术指标!D4")["verification"]["mapping"] == "label"


@pytest.mark.skip(reason="zt 不调用模型：旧用例验 LLM 调用的 max_tokens 与截断（LLMTruncated），没有对应物")
def test_llm_call_sets_max_tokens_and_truncation_is_raised():
    pass


def test_extract_max_tokens_still_read_from_the_policy():
    # 策略字段保留（D-R119）：zt 里不再是调用预算，只随抽取说明作为输出规模的参考
    assert ex.extract_max_tokens() == 6000
    assert estimate_policy.load_policy("gsyz_v1")["extract_max_tokens"] == 6000


def test_ambiguous_candidates_carry_verification(monkeypatch):
    m = _run(monkeypatch, [("用地面积 154871.74 ㎡；另见 232497.24 ㎡", {"buildings": [], "checks": {}, "cells": {
        "经济技术指标!D4": [{"value": "154871.74", "quote": "用地面积 154871.74 ㎡"},
                          {"value": "232497.24", "quote": "另见 232497.24 ㎡"}]}})])
    amb = _un(m, "ambiguous")[0]
    assert all("verification" in c for c in amb["candidates"])


# =================================================================== WS10-P12 关键词窗口（issue #761）

def _long_text(pos: int, total: int, needle: str) -> str:
    filler = "本章为施工组织与安全文明施工说明。"
    body = (filler * (total // len(filler) + 2))
    return body[:pos] + needle + body[pos:total - len(needle)]


def test_keyword_at_50000_of_115000_chars_reaches_the_prompt(monkeypatch):
    """115000 字正文、关键指标在第 50000 字 → 进入 prompt。

    变异：select_window 退回截文首（text[:MAX_TEXT_CHARS]）→ 本条转红（改前只送前 12000 字）。
    """
    needle = "总建筑面积 256944.18 ㎡"
    text = _long_text(50000, 115000, needle)
    assert len(text) == 115000 and text.index(needle) == 50000
    seen: list[str] = []
    _stub(monkeypatch, {"buildings": [], "checks": {}, "cells": {}}, seen)
    out, _ = _extract_from_text("fB", text, None)
    assert needle in seen[0]
    st = out["text_stats"]
    assert st["text_chars"] == 115000 and st["truncated"] is True
    assert st["strategy"] == "keyword_windows" and "总建筑面积" in st["anchors_hit"]
    assert st["window_chars"] <= ex.MAX_TEXT_CHARS


def test_short_text_is_sent_whole_with_strategy_full(monkeypatch):
    _stub(monkeypatch, {"buildings": [], "checks": {}, "cells": {}})
    out, _ = _extract_from_text("f0", "用地面积 12000", None)
    assert out["text_stats"] == {"file_id": "f0", "file_name": None, "text_chars": 10, "window_chars": 10,
                                 "truncated": False, "strategy": "full", "anchors_hit": [],
                                 # WS29-d：可观测的单体计数（zt 改动：去掉 completion_tokens / llm_calls）
                                 "building_count_raw": 0,
                                 "building_count": 0, "buildings_dropped": []}


def test_no_anchor_hit_falls_back_to_head_and_detail_says_so(monkeypatch):
    text = "x" * (ex.MAX_TEXT_CHARS + 500)
    body, st = ex.select_window(text, ["总建筑面积"])
    assert st["strategy"] == "head" and body == text[:ex.MAX_TEXT_CHARS]
    m = _run(monkeypatch, [(text, {"buildings": [], "checks": {}, "cells": {}})])
    d4 = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D4")
    assert "窗口外未检索" in d4["detail"] and "只检索了前 12000 字" in d4["detail"]
    assert m["text_stats"][0]["truncated"] is True


def test_windows_are_merged_in_source_order_and_padded_with_the_head():
    text = "项目概况。" + "填充" * 20000 + "用地面积 12000 ㎡" + "填充" * 20000 + "总建筑面积 30000 ㎡" + "尾" * 5000
    body, st = ex.select_window(text, ["总建筑面积", "用地面积"], budget=6000, radius=1000)
    assert st["window_chars"] <= 6000
    assert body.index("用地面积 12000") < body.index("总建筑面积 30000")   # 按原文顺序
    assert body.startswith("项目概况")                                    # 余量补文首
    assert st["anchors_hit"] == ["用地面积", "总建筑面积"]


def test_anchors_come_from_the_policy_and_synonyms():
    anchors = ex.extract_anchors()
    for a in ("经济技术指标", "建筑面积", "总建筑面积", "建筑占地面积", "地下停车位"):
        assert a in anchors


# =================================================================== WS29-d（issue #1010）：单体不丢、楼号表锚点、占地提示
#
# 实测 08-013 第 1 项：建施说明的楼号表 25 行（24 个单体 + 地下室），只有地下室有面积，抽取结果
# `buildings` 只剩地下室 1 个。单体循环里面积解析不出就 `continue`，不进 buildings、不进 unresolved、
# 没有告警 —— 模型列了也白列。本节夹具都照那份楼号表的形状写（表格行用制表符分隔，面积列为空）。

_TABLE_ROWS = [f"{n}#楼\t住宅\t高层二类\t二级\t51.55\t52.15\t16\t/\t0.1\t" for n in
               (1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21)]
_TABLE_ROWS += [f"S-{n}#楼\t配套\t低层\t二级\t5.05\t5.6\t1\t\t0.3\t" for n in (1, 2, 3, 4)]
_BASEMENT_ROW = "地下室\t地库\t地下室\t一级\t埋深：9.4\t/\t2\t/\t59300.00"
_BUILDING_TABLE = ("2.17 各单体建筑性质及特征明细表：\n楼号\t建筑 功能\t分类\t建筑层数(层)\t建筑面积\n"
                   + "\n".join(_TABLE_ROWS) + "\n" + _BASEMENT_ROW + "\n")


def _no_area(name: str, level: str = "above_ground") -> dict:
    # 模型照新提示词把面积为空的行也列出来：area 给 null，quote 摘含单体名的那一小段
    return {"name": name, "level": level, "function": "住宅", "area": None, "quote": name + "\t"}


def _table_answer(with_no_area: bool = True) -> dict:
    bs = [_no_area(r.split("\t")[0]) for r in _TABLE_ROWS] if with_no_area else []
    bs.append({"name": "地下室", "level": "underground", "function": "地库", "area": "59300.00",
               "quote": _BASEMENT_ROW})
    return {"buildings": bs, "checks": {}, "cells": {}}


def test_24_buildings_with_23_missing_area_are_all_kept(monkeypatch):
    """模型列了 24 个单体、其中 23 个面积为空 → buildings 24 个，23 个标 area_missing，一个都不自动归位。

    变异：恢复「面积解析不出就 continue」→ buildings 只剩 1 个 → 本条转红。
    """
    assert len(_TABLE_ROWS) == 23
    m = _run(monkeypatch, [(_BUILDING_TABLE, _table_answer())])
    assert len(m["buildings"]) == 24, [b["name"] for b in m["buildings"]]
    missing = [b for b in m["buildings"] if b.get("area_missing")]
    assert len(missing) == 23
    assert all(b["area"] is None and b["slot"] is None for b in missing), "无面积单体不许自动归位"
    base = next(b for b in m["buildings"] if b["name"] == "地下室")
    assert base["area"] == 59300.0 and base["slot"] == "经济技术指标!D7" and not base.get("area_missing")
    w = next(w for w in m["warnings"] if w["code"] == "building_area_missing")
    assert "原文列了 24 个单体，其中 23 个没有面积" in w["message"]
    assert w["count"] == 24 and w["missing"] == 23
    # 无面积单体不进槽位候选、不进合计；也不当成「超出槽位」刷 23 行未归位
    assert [c["cell"] for c in m["candidates"] if c.get("building_names")] == ["经济技术指标!D7"]
    assert not [u for u in m["unresolved"] if u["reason"] == "unmapped_building"]
    st = m["text_stats"][0]
    assert st["building_count_raw"] == 24 and st["building_count"] == 24


def test_model_that_lists_only_the_basement_is_not_reported_as_missing_area(monkeypatch):
    """模型没列无面积单体（只给地下室）→ building_count_raw=1、buildings 1 个、没有 building_area_missing。

    与上一条成对：两种夹具分清「模型没列」和「列了被丢」—— 以后看 text_stats 就知道是哪一种。
    """
    m = _run(monkeypatch, [(_BUILDING_TABLE, _table_answer(with_no_area=False))])
    assert len(m["buildings"]) == 1
    assert "building_area_missing" not in {w["code"] for w in m["warnings"]}
    st = m["text_stats"][0]
    assert st["building_count_raw"] == 1 and st["building_count"] == 1


def test_no_area_building_whose_name_is_not_in_the_source_is_dropped_with_a_reason(monkeypatch):
    """无面积单体只核单体名的引文在不在原文里：不在就丢弃并记原因（防编造）。"""
    ans = _table_answer()
    ans["buildings"].append(_no_area("99#楼"))
    m = _run(monkeypatch, [(_BUILDING_TABLE, ans)])
    assert "99#楼" not in [b["name"] for b in m["buildings"]]
    st = m["text_stats"][0]
    assert st["building_count_raw"] == 25 and st["building_count"] == 24
    assert st["buildings_dropped"] == [{"name": "99#楼", "reason": "单体名的引文在原文里找不到"}]


def test_floor_count_given_as_area_is_unverified_and_not_auto_assigned(monkeypatch):
    """模型把层数当面积（area 16，引文「16层」）→ 未核验，不自动归位，进「未归位」并写明原因。

    改前：16 确实在「16层」里，核验两项都过、confidence 1.0，按出现顺序归进 1#楼 槽位。
    变异：去掉「引文里这个数后面跟的是层 / 栋 / 户…就不是面积」→ 本条转红。
    """
    text = "1#楼 住宅 16层；地下室 地库 59300.00"
    m = _run(monkeypatch, [(text, {"buildings": [
        {"name": "1#楼", "level": "above_ground", "area": "16", "quote": "16层"},
        {"name": "地下室", "level": "underground", "area": "59300.00", "quote": "地下室 地库 59300.00"},
    ], "checks": {}, "cells": {}})])
    b1 = next(b for b in m["buildings"] if b["name"] == "1#楼")
    assert b1["area"] == 16.0 and b1["confidence"] == 0.0
    assert b1["verification"]["value_is_area"] is False
    assert b1["slot"] is None, "未核验的面积不许自动归位"
    assert "经济技术指标!D10" not in {c["cell"] for c in m["candidates"] if c.get("building_names")}
    u = next(u for u in m["unresolved"] if u["reason"] == "unmapped_building" and u["label"] == "1#楼")
    assert "核验未通过" in u["detail"] and "超出模板槽位" not in u["detail"]


def test_same_name_without_and_with_area_across_files_keeps_the_area(monkeypatch):
    """归一化后同名：一份没面积、一份有面积 → 合成一个、面积取有值的那份，不判多值。"""
    a = {"buildings": [_no_area("6#楼")], "checks": {}, "cells": {}}
    b = {"buildings": [{"name": "6#楼", "level": "above_ground", "area": "5321.05",
                        "quote": "6#楼\t5321.05"}], "checks": {}, "cells": {}}
    m = _run(monkeypatch, [("6#楼\t住宅", a), ("6#楼\t5321.05", b)])
    assert [(x["name"], x["area"]) for x in m["buildings"]] == [("6#楼", 5321.05)]
    assert not _un(m, "ambiguous")


def test_different_spellings_are_not_merged_automatically(monkeypatch):
    """「6#楼」（无面积）与「6#」（有面积）归一化后不同名 → 各占一行，系统不按相似度合并（铁律 3）。"""
    a = {"buildings": [_no_area("6#楼")], "checks": {}, "cells": {}}
    b = {"buildings": [{"name": "6#", "level": "above_ground", "area": "5321.05",
                        "quote": "6#\t5321.05"}], "checks": {}, "cells": {}}
    m = _run(monkeypatch, [("6#楼\t住宅", a), ("6#\t5321.05", b)])
    assert sorted(x["name"] for x in m["buildings"]) == ["6#", "6#楼"]


def test_building_with_two_areas_stays_in_the_list_without_an_area(monkeypatch):
    """同名单体面积两个取值：照旧出多值行，同时单体留在清单里（面积空、带两个取值）给面板手填。

    改前多值单体整个从 buildings 里拿掉，面板里没有这一行，多值行又没有格号、不能就地选值
    （WS29-r 评审留给本片的非阻断项）。
    """
    a = {"buildings": [{"name": "1#楼", "level": "above_ground", "area": "5000", "quote": "1#楼 5000"}],
         "checks": {}, "cells": {}}
    b = {"buildings": [{"name": "1#楼", "level": "above_ground", "area": "5200", "quote": "1#楼 5200"}],
         "checks": {}, "cells": {}}
    m = _run(monkeypatch, [("1#楼 5000", a), ("1#楼 5200", b)])
    assert len(_un(m, "ambiguous")) == 1
    b1 = next(x for x in m["buildings"] if x["name"] == "1#楼")
    assert b1["area"] is None and b1["area_options"] == [5000.0, 5200.0] and b1["slot"] is None
    assert not b1.get("area_missing"), "多值不是「原文无面积」"


def test_building_table_beyond_20000_chars_reaches_the_window(monkeypatch):
    """楼号表在正文 20000 字之后、附近没有别的锚点 → 窗口里有楼号表。

    变异：策略 extract_anchors 去掉「楼号」「栋号」「单体」「子项」→ 窗口里没有楼号表 → 本条转红。
    """
    filler = "本章为施工组织与安全文明施工说明。"
    head = (filler * 2000)[:20000]
    table = "楼号\t功能\t层数\n" + "\n".join(f"{n}#楼\t住宅\t16" for n in range(1, 25))
    text = head + table + (filler * 2000)[:20000]
    assert len(text) > ex.MAX_TEXT_CHARS
    seen: list[str] = []
    _stub(monkeypatch, {"buildings": [], "checks": {}, "cells": {}}, seen)
    out, _ = _extract_from_text("fT", text, None)
    assert "24#楼\t住宅\t16" in seen[0] and "楼号\t功能" in seen[0]
    assert "楼号" in out["text_stats"]["anchors_hit"]


def test_prompt_asks_for_buildings_without_area_and_the_version_is_v3(monkeypatch):
    """提示词写明面积为空的单体也要列出（area 给 null）；改了提示词就升版本号（C-R10）。"""
    # zt 改动：改为 agent 作答，措辞改动后升为 v3-zt1
    assert ex.ESTIMATE_PROMPT_VERSION == "estimate-extract/v3-zt1"
    seen: list[str] = []
    _stub(monkeypatch, {"buildings": [], "checks": {}, "cells": {}}, seen)
    _extract_from_text("f0", "用地面积 12000", None)
    assert "面积为空的单体也要列出" in seen[0] and "area 给 null" in seen[0]
    assert "建筑密度" in seen[0]


def test_text_stats_carry_building_counts(monkeypatch):
    # zt 改动：不再记 completion_tokens / llm_calls
    def fake_chat(messages, **kw):
        return json.dumps(_table_answer(), ensure_ascii=False), _U()

    _set_agent(monkeypatch, fake_chat)
    out, _ = _extract_from_text("f0", _BUILDING_TABLE, None, file_name="建施说明251016.docx")
    st = out["text_stats"]
    assert "completion_tokens" not in st and "llm_calls" not in st
    assert st["building_count_raw"] == 24 and st["building_count"] == 24
    assert st["file_name"] == "建施说明251016.docx"


# ---- 「未取到」详情写文件名（08-012 第 9 项）

def test_not_found_detail_names_the_file_not_its_internal_id(monkeypatch):
    """改前：「原文未提及（注意：2104518694846009344（正文 33980 字…）…）」—— 造价员看不懂这串数字。"""
    long_text = "用地面积 12000 ㎡ " + "x" * (ex.MAX_TEXT_CHARS + 10)
    _stub(monkeypatch, {"buildings": [], "checks": {}, "cells": {}})
    out, _ = _extract_from_text("2104518694846009344", long_text, None, file_name="建施说明251016.docx")
    m = ex.merge_extractions([out])
    d15 = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D15")
    assert "建施说明251016.docx" in d15["detail"] and "2104518694846009344" not in d15["detail"]
    # 拿不到文件名：写「文件（编号后 6 位）」，仍不写整串编号
    out2, _ = _extract_from_text("2104518694846009344", long_text, None)
    d15b = next(u for u in ex.merge_extractions([out2])["unresolved"] if u["cell"] == "经济技术指标!D15")
    assert "文件（009344）" in d15b["detail"] and "2104518694846009344" not in d15b["detail"]


def test_ambiguous_detail_names_the_file_not_its_internal_id(monkeypatch):
    _stub(monkeypatch, {"buildings": [], "checks": {}, "cells": {"经济技术指标!D4": [
        {"value": "154871.74", "quote": "用地面积 154871.74 ㎡"},
        {"value": "232497.24", "quote": "另见 232497.24 ㎡"}]}})
    out, _ = _extract_from_text("2104518694846009344", "用地面积 154871.74 ㎡；另见 232497.24 ㎡", None,
                                  file_name="可研报告.pdf")
    amb = _un(ex.merge_extractions([out]), "ambiguous")[0]
    assert "可研报告.pdf" in amb["detail"] and "2104518694846009344" not in amb["detail"]


# ---- 建筑密度与占地推算提示（E09，D-R118）

@pytest.mark.parametrize("quote, expect", [
    ("建筑密度 30%", 30.0),
    ("建筑密度≤30％", 30.0),
    ("建筑密度\t\t30%\t≤30%", 30.0),          # 生产原文的表格行
    ("建筑密度不大于 28.5%", 28.5),
    ("建筑密度 0.3", None),                    # 不带 % 的小数不认（不猜是 0.3% 还是 30%）
    ("建筑密度 30", None),
    ("容积率 2.58，绿地率 30%", None),         # 没有「建筑密度」字样
    ("建筑密度 130%", None),                   # 超出 (0, 100]
])
def test_parse_density_only_accepts_percent_written_after_the_label(quote, expect):
    """变异：改用 parse_quantity → 「建筑密度 0.3」得 0.3 → 本条转红。"""
    assert ex.parse_density(quote) == expect


_SITE = {"value": "43783.70", "quote": "总用地面积\tm2\t43783.70"}
_SITE_TEXT = "总用地面积\tm2\t43783.70\n容积率\t\t2.58\t\n建筑密度\t\t30%\t≤30%\n"


def _density_run(monkeypatch, text, density_quote, value="30%"):
    return _run(monkeypatch, [(text, {"buildings": [], "cells": {"经济技术指标!D4": [_SITE]},
                                      "checks": {"building_density": [{"value": value, "quote": density_quote}]}})])


def test_footprint_hint_is_computed_by_code_and_never_becomes_a_candidate(monkeypatch):
    """用地 43783.70、密度 30% → 占地那一行「未取到」写推算提示，推算值 13135.11 由代码算出。

    推算值不进候选（铁律 2：只有用户点「填入推算值」才写，且来源记 derived、结果需复核）。
    变异：把推算值写进 candidates → 「不进候选」断言转红。
    """
    m = _density_run(monkeypatch, _SITE_TEXT, "建筑密度\t\t30%")
    d15 = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D15")
    assert d15["reason"] == "not_found"
    assert "原文没有建筑占地面积，只有建筑密度 30%" in d15["detail"] and "13135.11" in d15["detail"]
    assert "建筑密度\t\t30%" in d15["detail"], "要附密度的原文引文"
    der = d15["derived"]
    assert der["value"] == 13135.11 and der["density"] == 30.0 and der["site_area"] == 43783.7
    assert der["site_cell"] == "经济技术指标!D4" and der["density_quote"] == "建筑密度\t\t30%"
    cells = {c["cell"] for c in m["candidates"]}
    assert "经济技术指标!D15" not in cells and "经济技术指标!D16" not in cells
    assert all(c["value"] != 13135.11 for c in m["candidates"])
    # 密度只作提示：不进原文总量（check_values），也不进候选
    assert all(c["key"] != "building_density" for c in m["check_values"])
    d16 = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D16")
    assert "derived" not in d16 or d16["derived"] is None


def test_density_without_a_percent_sign_is_not_used_and_says_so(monkeypatch):
    m = _density_run(monkeypatch, "总用地面积\tm2\t43783.70\n建筑密度 0.3\n", "建筑密度 0.3", value="0.3")
    d15 = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D15")
    assert not d15.get("derived") and "13135" not in d15["detail"]
    w = next(w for w in m["warnings"] if w["code"] == "density_format_unrecognized")
    assert "建筑密度 0.3" in w["message"]


def test_density_quote_not_in_the_source_is_not_used(monkeypatch):
    m = _density_run(monkeypatch, "总用地面积\tm2\t43783.70\n绿地率 30%\n", "建筑密度 30%")
    d15 = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D15")
    assert not d15.get("derived") and "建筑密度" not in d15["detail"]


def test_density_hint_without_a_site_area_says_it_cannot_derive(monkeypatch):
    m = _run(monkeypatch, [("建筑密度 30%", {"buildings": [], "cells": {},
                                           "checks": {"building_density": [{"value": "30%",
                                                                             "quote": "建筑密度 30%"}]}})])
    d15 = next(u for u in m["unresolved"] if u["cell"] == "经济技术指标!D15")
    assert "只有建筑密度 30%" in d15["detail"] and "用地面积没有取到" in d15["detail"]
    assert not d15.get("derived")


def test_no_density_hint_when_the_footprint_is_in_the_source(monkeypatch):
    text = _SITE_TEXT + "建筑占地面积 13000 ㎡\n"
    m = _run(monkeypatch, [(text, {"buildings": [], "cells": {"经济技术指标!D4": [_SITE], "经济技术指标!D15": [
        {"value": "13000", "quote": "建筑占地面积 13000 ㎡"}]},
        "checks": {"building_density": [{"value": "30%", "quote": "建筑密度\t\t30%"}]}})])
    assert next(c for c in m["candidates"] if c["cell"] == "经济技术指标!D15")["value"] == 13000.0
    assert not [u for u in m["unresolved"] if u.get("derived")]


@pytest.mark.skip(reason="zt 不调用模型：旧用例验解析失败重调计入 llm_calls，没有对应物")
def test_llm_calls_counts_a_parse_retry():
    pass
