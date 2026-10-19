# 来源：engine-service/tests/test_report_templates.py（zhitong-cost-ai@991ff5c，W3 搬入；HTTP 端点用例改成读模板与
# template_summary，其余只改了 import 与数据文件路径）
"""报告模板测试。

数据源 zhitong/skills/zt-report/data/report_templates.yaml（旧仓 engine/data/report_templates.yaml 原样迁入，24 套）。
过滤 enabled=false，按 seq 排序章节。
"""
from __future__ import annotations

import pytest

from tests.report._support import DATA_DIR, resolve_section, templates
from zt.common import ZtError
from zt.report import service
from zt.report.templates import load_templates, parse_templates as _parse_templates

_DATA_FILE = DATA_DIR / "report_templates.yaml"


def _listed():
    return service.template_summary(load_templates(DATA_DIR)).data["templates"]


def test_templates_returns_24():
    ts = templates()
    # 源 yaml 24 套且全部 enabled=true；若未来源数据禁用若干套，此处数量=启用数
    assert len(ts) == 24
    codes = [t["template_code"] for t in ts]
    assert len(codes) == len(set(codes)), "template_code 不应重复"
    assert [t["template_code"] for t in _listed()] == codes


def test_template_section_quadruple_complete():
    monthly = next(t for t in templates() if t["template_code"] == "tzkz_monthly_v0")
    assert monthly["name"].startswith("投资控制月报")
    assert monthly["note"]
    sections = monthly["sections"]
    assert len(sections) == 7
    for s in sections:
        # 章节四元组 + seq 齐全且非空
        assert s["code"]
        assert s["title"]
        assert isinstance(s["seq"], int)
        assert s["rag_query"]
        assert s["gen_prompt"]
    seqs = [s["seq"] for s in sections]
    assert seqs == sorted(seqs), "章节应按 seq 升序返回"


def test_parse_filters_disabled():
    raw = {
        "templates": [
            {"template_code": "a", "name": "A", "enabled": True, "sections": []},
            {"template_code": "b", "name": "B", "enabled": False, "sections": []},
            # enabled 缺省视为启用（与源 yaml 全显式 true 兼容）
            {"template_code": "c", "name": "C", "sections": []},
        ]
    }
    parsed = _parse_templates(raw)
    assert [t["template_code"] for t in parsed] == ["a", "c"]


def test_parse_sorts_sections_and_keeps_note_optional():
    raw = {
        "templates": [
            {
                "template_code": "x",
                "name": "X",
                "enabled": True,
                "sections": [
                    {"code": "s2", "title": "二", "seq": 20, "rag_query": "q2", "gen_prompt": "p2"},
                    {"code": "s1", "title": "一", "seq": 10, "rag_query": "q1", "gen_prompt": "p1"},
                ],
            }
        ]
    }
    parsed = _parse_templates(raw)
    assert parsed[0]["note"] == ""
    assert parsed[0]["note_user"] == ""
    assert [s["code"] for s in parsed[0]["sections"]] == ["s1", "s2"]


# ---------------------------------------------------------------- WS12-B P07（issue #758）

import yaml  # noqa: E402
from pathlib import Path  # noqa: E402


# spec P07 生产取证：资料里 0 命中、却被当成项目事实写进正文的预置措辞
# 「现场查勘」「现场查勘核实」：gaisuan / yusuan / jiesuan_chengguo 三套曾在写作要求里直接要求写
# 「实施了…现场查勘核实及与建设/施工单位核对等程序」（PR-YAML Y1），与「现场踏勘」同类。
# 预置核减原因（P07 修法 2「删掉结论句和预置原因」）：#758 从三套预算审核的 duibi 写作要求里删掉的原因类别，
# 只许留在 rag_query（检索用）。写回 gen_prompt 等于引导模型给核减金额贴资料里没有的原因标签（PR #786 评审）。
PRESET_REDUCTION_REASONS = ("主材单价偏高", "工程量多算", "定额套用有误", "取费修正", "数量虚增", "规格虚高")
PRESET_BLACKLIST = ("全过程审核", "现场踏勘", "实地丈量", "不予计取", "结算审核书", "超图计量",
                    "现场查勘", "现场查勘核实", *PRESET_REDUCTION_REASONS)


def _all_templates():
    return _parse_templates(yaml.safe_load(_DATA_FILE.read_text(encoding="utf-8")))


def test_1_no_preset_phrases_in_any_gen_prompt():
    """① 程序性陈述、预置核减原因、附件名称不许写在写作要求里（改为 claims / attachment_hints）。"""
    hits = [(t["template_code"], s["code"], p) for t in _all_templates() for s in t["sections"]
            for p in PRESET_BLACKLIST if p in s["gen_prompt"]]
    assert hits == []


def test_1b_gen_prompt_does_not_say_follow_the_original_text():
    """「按原文…」里的原文指模板底稿，模型会读成「照抄资料原文」。"""
    hits = [(t["template_code"], s["code"]) for t in _all_templates() for s in t["sections"]
            if "按原文" in s["gen_prompt"] or "留占位" in s["gen_prompt"]]
    assert hits == []


def test_2_settlement_report_sections_have_boundaries():
    """② jiesuan_shenhe_bg（及市政 / 园林变体）的概况、结果、对比三章必须有 excludes 或 facts_allowed。"""
    for code in ("jiesuan_shenhe_bg", "jiesuan_shenhe_bg_shizheng", "jiesuan_shenhe_bg_yuanlin"):
        t = next(x for x in _all_templates() if x["template_code"] == code)
        by = {s["code"]: s for s in t["sections"]}
        for sec in ("gaikuang", "jieguo", "duibi"):
            assert by[sec]["excludes"] or by[sec]["facts_allowed"], (code, sec)


def test_3_all_24_templates_parse_with_new_fields():
    ts = _all_templates()
    assert len(ts) == 24
    for t in ts:
        for s in t["sections"]:
            for key in ("excludes", "facts_allowed", "attachment_hints"):
                assert isinstance(s[key], list)
            for c in s["claims"]:
                assert set(c) == {"key", "text"} and c["key"] and c["text"]


def test_claims_moved_out_of_prompt_into_claims():
    daoyu = resolve_section("jiesuan_shenhe_bg", "daoyu")
    assert {c["key"] for c in daoyu["claims"]} == {"full_process_audit", "site_survey", "field_measure"}
    assert "全过程审核" not in daoyu["gen_prompt"]
    fujian = resolve_section("jiesuan_shenhe_bg", "fujian")
    assert fujian["attachment_hints"] and "工程竣工结算造价审定单" in fujian["attachment_hints"]


def test_resolve_section_unknown_raises():
    """zt 改动：旧端点找不到章节回 None（再由调用方 422）；这里直接抛结构化错误。"""
    with pytest.raises(ZtError) as e1:
        resolve_section("jiesuan_shenhe_bg", "nope")
    assert e1.value.code == "section_not_found"
    with pytest.raises(ZtError) as e2:
        resolve_section("nope", "daoyu")
    assert e2.value.code == "template_not_found"


def test_summary_exposes_claims_for_the_confirm_step():
    data = service.template_summary(load_templates(DATA_DIR), "jiesuan_shenhe_bg").data
    daoyu = next(s for s in data["sections"] if s["code"] == "daoyu")
    assert daoyu["claims"], "「确认事项」一步从 templates 子命令取 claims"
    assert {c["key"] for c in data["claims_to_confirm"]} >= {c["key"] for c in daoyu["claims"]}


# ---------------------------------------------------------------- PR-YAML：护栏漏洞 Y1 + 写作要点一期 Y2

from zt.report.guard import _compact, guard_section  # noqa: E402

_Y1_CODES = ("gaisuan_chengguo", "yusuan_chengguo", "jiesuan_chengguo")
# 程序性陈述的几种写法：写进 gen_prompt 等于替用户断言「做过」（WS12-P07），只能放 claims
_Y1_PROCEDURE_PHRASES = ("现场查勘", "与建设/施工单位核对", "与建设单位、施工单位核对", "核对等程序")


def _tpl(code):
    return next(t for t in _all_templates() if t["template_code"] == code)


def test_y1_chengguo_procedures_not_in_any_gen_prompt():
    """Y1：三套 *_chengguo 的任何一章写作要求里都不再出现现场查勘、与建设/施工单位核对。"""
    hits = [(code, s["code"], p) for code in _Y1_CODES for s in _tpl(code)["sections"]
            for p in _Y1_PROCEDURE_PHRASES if p in s["gen_prompt"]]
    assert hits == []


def test_y1_chengguo_procedures_moved_into_claims():
    """Y1：这两类程序性陈述挪进 bianzhi 章的 claims，前端「确认事项」一步才勾得到。"""
    for code in _Y1_CODES:
        bianzhi = resolve_section(code, "bianzhi")
        assert {c["key"] for c in bianzhi["claims"]} == {"site_check", "party_check"}, code
        assert "【已确认事项】" in bianzhi["gen_prompt"], code
    # key 与估算那套（早已放进 claims 的）一致，DEFAULT_CLAIMS 的「现场查勘」兜底才会随勾选一起放行
    assert "site_check" in {c["key"] for c in resolve_section("guzhi_chengguo", "bianzhi")["claims"]}


def test_y1_chengguo_keeps_quantity_calculation_in_prompt():
    """工程量计算是编制本身的工作（不是可能没发生的外部程序），留在写作要求里、不进 claims。

    PR #786 评审：只把现场查勘、与各方核对挪进 claims，却把原写作要求里的「实施了工程量计算」整个丢了。
    四套 *_chengguo 的 bianzhi 同一骨架，估算那套在 #758 也丢过，一并放回。
    """
    for code in ("guzhi_chengguo", *_Y1_CODES):
        bianzhi = resolve_section(code, "bianzhi")
        # 看【必备要素】这一段：【缺失处理】里提到工程量计算不等于要求写它
        assert "实施了工程量计算" in _part(bianzhi["gen_prompt"], "【必备要素】"), code
        assert all("工程量计算" not in c["text"] for c in bianzhi["claims"]), code


def test_y1_guard_flags_old_chengguo_wording_unless_confirmed():
    """Y1 端到端：模型照旧写出那句程序性陈述，未勾选 → 标【待核】；勾选后放行。"""
    sec = resolve_section("jiesuan_chengguo", "bianzhi")
    old = "我们依据施工合同等资料编制；实施了工程量计算、现场查勘核实及与建设/施工单位核对等程序。"
    ev = []
    r = guard_section(old, title=sec["title"], evidence=ev, claims=sec["claims"])
    assert {f.text for f in r.flags if f.kind == "unconfirmed_claim"} == {"现场查勘核实", "与建设/施工单位核对"}
    assert "现场查勘核实【待核：「现场查勘核实」" in r.content
    ok = guard_section(old, title=sec["title"], evidence=ev, claims=sec["claims"],
                       confirmed=["site_check", "party_check"])
    assert [f for f in ok.flags if f.kind == "unconfirmed_claim"] == []
    assert _compact(ok.content) == _compact(old)


# 与模板库《全过程造价咨询月报》docx 的七章一一对应（造价员把 AI 初稿逐章贴进正式模板）
_MONTHLY_TITLES = ("一、项目工作概况", "二、项目进展情况", "三、项目投资控制总体情况", "四、本期主要咨询工作内容",
                   "五、重大事件", "六、存在问题及建议", "七、下期工作计划")


def test_y2_monthly_rewritten_to_real_report_skeleton():
    m = _tpl("tzkz_monthly_v0")
    assert m["name"].startswith("投资控制月报") and "测试骨架" not in m["name"]
    assert tuple(s["title"] for s in m["sections"]) == _MONTHLY_TITLES
    codes = [s["code"] for s in m["sections"]]
    # 与旧骨架语义相同的四章沿用旧 code，旧初稿这几章的「单章重试」仍能解析
    assert {"gaikuang", "jinzhan", "touzi", "jihua"} <= set(codes)
    assert codes[0] == "gaikuang" and codes[-1] == "jihua"


def _part(prompt, head):
    """四段式写作要求里某一段的正文（到下一个【…】段头为止）。"""
    body = prompt.split(head, 1)[1]
    nxt = [body.find(h) for h in _FOUR_PARTS if h != head and body.find(h) != -1]
    return body[:min(nxt)] if nxt else body


def test_y2_reduction_reasons_come_from_the_materials_verbatim():
    """三套预算审核的对比分析：核减原因只用资料原话分条，资料没写原因的不自拟、不按经验归类（WS12-P07 修法 2）。"""
    for code in ("yusuan_shenhe", "yusuan_shenhe_shizheng", "yusuan_shenhe_yuanlin"):
        p = resolve_section(code, "duibi")["gen_prompt"]
        assert "原因用资料原话" in _part(p, "【格式】"), code
        assert "不自拟原因" in _part(p, "【缺失处理】"), code


def test_y2_monthly_touzi_sources_cover_every_required_number_and_no_computed_deviation():
    """月报投资章：批复概算、合同价、累计数都不是「本期数据」，【取材】必须覆盖到它们的出处；
    偏差只许照抄资料载明的数（PR #786 评审：原写法「只用本统计期间的数据」与必备要素自相矛盾，且③引导做运算）。"""
    p = resolve_section("tzkz_monthly_v0", "touzi")["gen_prompt"]
    src = _part(p, "【取材】")
    for doc in ("概算批复", "施工合同", "计量审核表", "进度款支付审批表", "变更签证台账"):
        assert doc in src, doc
    assert "截至本统计期末" in src
    assert "只用本统计期间的数据" not in p
    must = _part(p, "【必备要素】")
    assert "资料中载明的投资偏差数" in must
    assert "【待补：投资偏差】" in _part(p, "【缺失处理】")


# 较完整的三套结算审核报告与只有金额表的审定单保持原写法，其余一律四段
_FOUR_PART_EXEMPT = {"jiesuan_shenhe_bg", "jiesuan_shenhe_bg_shizheng", "jiesuan_shenhe_bg_yuanlin",
                     "zaojia_shendingdan"}
_FOUR_PARTS = ("【必备要素】", "【取材】", "【格式】", "【缺失处理】")


def test_y2_gen_prompt_has_four_fixed_parts_in_order():
    bad = []
    for t in _all_templates():
        if t["template_code"] in _FOUR_PART_EXEMPT:
            continue
        for s in t["sections"]:
            p = s["gen_prompt"]
            pos = [p.find(h) for h in _FOUR_PARTS]
            if -1 in pos or pos != sorted(pos) or pos[0] != 0:
                bad.append((t["template_code"], s["code"], "missing/order"))
                continue
            bodies = [p[a + len(h):b] for a, h, b in zip(pos, _FOUR_PARTS, pos[1:] + [len(p)])]
            if any(not _compact(x) for x in bodies):
                bad.append((t["template_code"], s["code"], "empty part"))
    assert bad == []


# section code 是旧初稿「单章重试」的定位键（report.py `_resolve_spec` 找不到就 422）。
# 除月报外本 PR 一个都没改；以后要改，先想清楚旧初稿怎么办，再改这张表。
_FROZEN_SECTION_CODES = {
    "guzhi_chengguo": ("fengmian", "feiye", "mulu", "bianzhi", "jiben", "guzhi_qingkuang", "qita", "fubiao"),
    "gaisuan_chengguo": ("fengmian", "feiye", "mulu", "bianzhi", "jiben", "gaisuan_qingkuang", "qita", "fubiao"),
    "yusuan_chengguo": ("fengmian", "feiye", "mulu", "bianzhi", "jiben", "yusuan_qingkuang", "qita", "fubiao"),
    "jiesuan_chengguo": ("fengmian", "feiye", "mulu", "bianzhi", "jiben", "jiesuan_qingkuang", "qita", "fubiao"),
    "guzhi_shuoming": ("yiju", "yuanze", "qita"),
    "gaisuan_shuoming": ("yiju", "yuanze", "qita"),
    "kzj_bz_baogao": ("daoyu", "gaikuang", "zhaobiao_fanwei", "yiju", "yaoqiu", "qufei", "qtxmf", "teshu",
                      "chengguo", "luokuan"),
    "jiesuan_shuoming": ("gaikuang", "yiju", "yuanze", "teshu"),
    "guzhi_shenhe": ("yiju", "yuanze", "qita"),
    "gaisuan_shenhe": ("daoyu", "gaikuang", "yiju", "qingkuang", "jieguo", "duibi", "fujian", "luokuan"),
    "yusuan_shenhe": ("daoyu", "gaikuang", "fanwei", "yiju", "qufei", "shixiang", "jieguo", "duibi", "luokuan"),
    "jiesuan_shenhe_bg": ("daoyu", "gaikuang", "tezheng", "yiju", "shixiang", "jieguo", "duibi", "fujian",
                          "luokuan"),
    "zaojia_shendingdan": ("shendingdan",),
    "kzj_bz_baogao_shizheng": ("daoyu", "gaikuang", "fanwei", "yiju", "qufei", "qtxmf", "shixiang", "chengguo",
                               "luokuan"),
    "kzj_bz_baogao_yuanlin": ("daoyu", "gaikuang", "fanwei", "yiju", "qufei", "shixiang", "chengguo", "luokuan"),
    "gaisuan_shenhe_shizheng": ("daoyu", "gaikuang", "yiju", "qingkuang", "jieguo", "duibi", "fujian", "luokuan"),
    "yusuan_shenhe_shizheng": ("daoyu", "gaikuang", "yiju", "shixiang", "jieguo", "duibi", "luokuan"),
    "yusuan_shenhe_yuanlin": ("daoyu", "gaikuang", "fanwei", "yiju", "qufei", "shixiang", "jieguo", "duibi",
                              "luokuan"),
    "jiesuan_shenhe_bg_shizheng": ("daoyu", "gaikuang", "tezheng", "yiju", "shixiang", "jieguo", "duibi", "fujian",
                                   "luokuan"),
    "jiesuan_shenhe_bg_yuanlin": ("daoyu", "gaikuang", "tezheng", "yiju", "shixiang", "jieguo", "duibi", "fujian",
                                  "luokuan"),
    "qd_bz_shuoming": ("gaikuang", "zhaobiao_fanwei", "yiju", "yaoqiu", "feilv", "qtxmf", "gongxing", "jianzhu",
                       "anzhuang", "yueding"),
    "qd_bz_shuoming_shizheng": ("gaikuang", "zhaobiao_fanwei", "yiju", "yaoqiu", "feilv", "qtxmf", "shixiang"),
    "qd_bz_shuoming_yuanlin": ("gaikuang", "zhaobiao_fanwei", "yiju", "yaoqiu", "feilv", "qtxmf", "shixiang"),
}


def test_section_codes_frozen_except_monthly():
    got = {t["template_code"]: tuple(s["code"] for s in t["sections"])
           for t in _all_templates() if t["template_code"] != "tzkz_monthly_v0"}
    assert got == _FROZEN_SECTION_CODES


# ---------------------------------------------------------------- WS24-q（issue #829，缺陷 02-008 第 1–3 项）

import re  # noqa: E402


# 浙江 11 个地级市。模板是全省项目共用的：写作要求里出现哪个市，模型就把它当成本项目所在地写进正文
# （生产实测：义乌的项目写出「均按国家、浙江省、宁波市现行最新计价规范…执行」，还挂着 [资料6]）。
_ZJ_PREFECTURE_CITIES = ("杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水")
# 「数字 + %」是写死的费率口径（生产实测：「规费费率不低于标准费率的30%」，项目资料里没有招标文件）。
# 全角、千分号、「百分之三十」是同一件事换了写法，一并拦。
_HARDCODED_PERCENT = re.compile(r"[0-9０-９]\s*[%％‰]|百分之[0-9０-９〇零一二两三四五六七八九十百千半]")
# report_compose.build_messages 从章节里取进提示词的就是这五样（见 prompt_version 的 docstring）。
# rag_query 只用来选资料，不进提示词，不在这里查。
_PROMPT_BOUND_FIELDS = ("gen_prompt", "title", "excludes", "claims", "attachment_hints")


def _prompt_bound_text(section: dict, field: str) -> str:
    v = section.get(field)
    if field == "claims":
        return "\n".join(str(c.get("text") or "") for c in v or [] if isinstance(c, dict))
    if isinstance(v, (list, tuple)):
        return "\n".join(str(x) for x in v)
    return str(v or "")


def _hardcoded_hits(templates) -> list[tuple]:
    """(模板, 章, 字段, 命中的文字)：写进提示词的模板文字里出现的地级市名与写死的百分数。"""
    hits = []
    for t in templates:
        for s in t.get("sections") or []:
            for field in _PROMPT_BOUND_FIELDS:
                text = _prompt_bound_text(s, field)
                hits += [(t.get("template_code"), s.get("code"), field, c)
                         for c in _ZJ_PREFECTURE_CITIES if c in text]
                hits += [(t.get("template_code"), s.get("code"), field, m.group())
                         for m in _HARDCODED_PERCENT.finditer(text)]
    return hits


def _selfcheck_scope(raw: dict) -> list[dict]:
    """不经 _parse_templates：enabled=false 的模板也查，免得停用再启用时把旧文字带回来。"""
    return raw.get("templates") or []


def _raw_templates() -> list[dict]:
    return _selfcheck_scope(yaml.safe_load(_DATA_FILE.read_text(encoding="utf-8")))


def test_ws24q_no_city_name_or_hardcoded_percent_in_any_prompt_text():
    """模板自检：全部 172 章写进提示词的文字里，浙江 11 个地级市名 0 处、「数字 + %」0 处。

    总纲 F-50：之后改这份 yaml 的片（WS24-f、WS24-o）不许把这条改红。
    """
    assert _hardcoded_hits(_raw_templates()) == []


def test_ws24q_selfcheck_scans_all_172_sections():
    """自检查的是全部章节：章数对不上（yaml 结构变了、键名改了）时别让上一条在空集上通过。"""
    scanned = [(t["template_code"], s["code"]) for t in _raw_templates() for s in t["sections"]
               if _prompt_bound_text(s, "gen_prompt").strip()]
    frozen = sum(len(v) for v in _FROZEN_SECTION_CODES.values()) + len(_MONTHLY_TITLES)
    assert len(scanned) == len(set(scanned)) == frozen == 172


def _one_section(**fields) -> list[dict]:
    base = {"code": "s", "title": "一、概况", "gen_prompt": "【必备要素】按招标文件载明的取费标准写。"}
    return [{"template_code": "t", "sections": [{**base, **fields}]}]


# 样句逐条写死，不从 _ZJ_PREFECTURE_CITIES 生成：从它生成的话，表里删掉一个市，对应用例跟着消失，照样全绿
@pytest.mark.parametrize("text, city", [
    ("价格信息采用杭州市建设工程造价信息", "杭州"),
    ("取费按宁波市区标准", "宁波"),
    ("质量满足温州市园林绿化工程验收标准", "温州"),
    ("按嘉兴市现行计价政策文件执行", "嘉兴"),
    ("苗木规格按湖州市园林绿化用材标准", "湖州"),
    ("均按国家、浙江省、绍兴市现行最新计价规范执行", "绍兴"),
    ("材料价格采用金华市（义乌）信息价", "金华"),
    ("按衢州市区标准取费", "衢州"),
    ("舟山市海岛工程增加费另计", "舟山"),
    ("按台州市造价管理部门文件执行", "台州"),
    ("丽水市山区运输增加费另计", "丽水"),
])
def test_ws24q_selfcheck_catches_each_prefecture_city(text, city):
    assert _hardcoded_hits(_one_section(gen_prompt=f"【必备要素】{text}。")) == [("t", "s", "gen_prompt", city)]


@pytest.mark.parametrize("text, hit", [
    ("③规费（不低于标准费率30%）", "0%"),
    ("下浮 5 %", "5 %"),
    ("不低于标准费率３０％", "０％"),
    ("质保金 3‰", "3‰"),
    ("不低于标准费率的百分之三十", "百分之三"),
    ("按百分之5计", "百分之5"),
])
def test_ws24q_selfcheck_catches_hardcoded_percent(text, hit):
    assert _hardcoded_hits(_one_section(gen_prompt=text)) == [("t", "s", "gen_prompt", hit)]


@pytest.mark.parametrize("text", [
    "养护期按招标文件载明的年限写",       # 没有数字
    "按一般计税、固定税率写，税率数字逐字照抄",  # 提到费率但没写死
    "费率以百分比表示",                 # 「百分比」不是「百分之几」
    "依据浙江省 2018 版概算定额",        # 省名与版本年份不拦
    "（一）至（四）分条，不超过 200 字",    # 篇幅数字不拦
])
def test_ws24q_selfcheck_leaves_neutral_wording_alone(text):
    assert _hardcoded_hits(_one_section(gen_prompt=text)) == []


@pytest.mark.parametrize("field, value", [
    ("title", "十、宁波市清单总体计价约定"),
    ("excludes", ["不写审核结果", "不写宁波市以外的口径"]),
    ("claims", [{"key": "k", "text": "已按宁波市区标准取费"}]),
    ("attachment_hints", ["宁波市造价信息"]),
])
def test_ws24q_selfcheck_covers_every_field_that_reaches_the_prompt(field, value):
    """build_messages 把这四样和 gen_prompt 一起交给模型，地名写在哪一样里都会被照抄。"""
    assert _hardcoded_hits(_one_section(**{field: value})) == [("t", "s", field, "宁波")]


def test_ws24q_selfcheck_includes_disabled_templates():
    """现在 24 套全部启用，真 yaml 走不到这个分支，用造出来的停用模板证明它没被滤掉。"""
    raw = {"templates": [{"template_code": "off", "enabled": False,
                          "sections": [{"code": "s", "title": "一", "gen_prompt": "取费按宁波市区标准"}]}]}
    assert _hardcoded_hits(_selfcheck_scope(raw)) == [("off", "s", "gen_prompt", "宁波")]


def test_ws24q_rag_query_is_not_scanned():
    """检索词不进提示词（只用来选资料）；WS24-f 要改它，不受这条自检约束。"""
    assert _hardcoded_hits(_one_section(rag_query="宁波 造价信息 30%")) == []


# 改写的 11 处：「宁波」8 处（7 行）、「不低于标准费率30%」3 处。只把写死的结论换成「去资料里找什么」，
# 要素本身不能丢（整条删掉，模型就不知道这一章要写规费、要写未尽事宜的备注）。
_WS24Q_REWRITES = (
    ("yusuan_shenhe_yuanlin", "yiju", "资料中载明的工程所在地园林绿化计价配套文件"),
    ("qd_bz_shuoming", "feilv", "③规费（按招标文件载明的费率下限）"),
    ("qd_bz_shuoming", "yueding", "均按国家、浙江省及工程所在地现行最新计价规范、政策文件及本项目招标文件约定执行。"),
    ("qd_bz_shuoming_shizheng", "feilv", "按招标文件载明的取费地区标准"),
    ("qd_bz_shuoming_shizheng", "feilv", "③规费（按招标文件载明的费率下限，各专业分档）"),
    ("qd_bz_shuoming_shizheng", "shixiang", "按国家、浙江省及工程所在地现行有效计价规范、定额、政策文件"),
    ("qd_bz_shuoming_yuanlin", "yaoqiu", "质量满足招标文件载明的园林绿化工程验收标准及养护规范"),
    ("qd_bz_shuoming_yuanlin", "yaoqiu", "按图纸及招标文件载明的园林绿化用材标准执行"),
    ("qd_bz_shuoming_yuanlin", "feilv", "按招标文件载明的取费地区标准"),
    ("qd_bz_shuoming_yuanlin", "feilv", "③规费（按招标文件载明的费率下限，含折算口径）"),
    ("qd_bz_shuoming_yuanlin", "shixiang", "按国家、浙江省及工程所在地现行有效计价规范、定额、政策文件"),
)


@pytest.mark.parametrize("template_code, section_code, wording", _WS24Q_REWRITES)
def test_ws24q_rewritten_elements_are_kept_and_point_to_the_materials(template_code, section_code, wording):
    must = _part(resolve_section(template_code, section_code)["gen_prompt"], "【必备要素】")
    assert wording in must


# ---------------------------------------------------------------- WS24-f（issue #863，缺陷 02-006 第 3 项）

from zt.report.compose import query_terms  # noqa: E402

# 「同一个检索词不得出现在超过一半章节里」只对 4 章及以上的模板有意义：3 章的模板里一个词出现 2 次就算过半，
# 而它们的主题词（估算、概算、审核）本来就该每章都有
_RAG_SELFCHECK_MIN_SECTIONS = 4
_QD_TEMPLATES = ("qd_bz_shuoming", "qd_bz_shuoming_shizheng", "qd_bz_shuoming_yuanlin")


def _common_rag_terms(templates) -> list[tuple]:
    """(模板, 检索词, 出现章数, 章数)：同一套模板里出现在超过一半章节 rag_query 里的检索词。

    检索词是用来区分章节、给块打分的。一个词在过半章节里都有，它在每章给的分都一样，选材就分不出章节；
    「清单 项目特征 计量」更糟 —— 清单 xlsx 的每一块里都有，每块都命中到封顶（生产运行 B）。
    """
    hits = []
    for t in templates:
        secs = t.get("sections") or []
        if len(secs) < _RAG_SELFCHECK_MIN_SECTIONS:
            continue
        counts: dict[str, int] = {}
        for s in secs:
            for w in query_terms(s.get("rag_query") or ""):
                counts[w] = counts.get(w, 0) + 1
        hits += [(t.get("template_code"), w, n, len(secs)) for w, n in sorted(counts.items()) if n * 2 > len(secs)]
    return hits


def test_ws24f_no_rag_term_shared_by_more_than_half_of_a_templates_sections():
    assert _common_rag_terms(_raw_templates()) == []


def test_ws24f_rag_selfcheck_covers_the_three_qd_templates():
    """三套清单编制说明（10 + 7 + 7 = 24 章）都在自检范围里，别让上一条在空集上通过。"""
    scope = {t["template_code"]: len(t["sections"]) for t in _raw_templates()
             if len(t["sections"]) >= _RAG_SELFCHECK_MIN_SECTIONS}
    assert {c: scope.get(c) for c in _QD_TEMPLATES} == {"qd_bz_shuoming": 10, "qd_bz_shuoming_shizheng": 7,
                                                       "qd_bz_shuoming_yuanlin": 7}


def test_ws24f_rag_selfcheck_catches_the_generic_prefix():
    """自检的牙：把「清单 项目特征 计量」加回任一套清单编制说明的全部章节，就被点名。"""
    raw = [{"template_code": "qd", "sections": [
        {"code": f"s{i}", "rag_query": f"清单 项目特征 计量 主题{i}"} for i in range(7)]}]
    assert [(h[1], h[2]) for h in _common_rag_terms(raw)] == [("清单", 7), ("计量", 7), ("项目特征", 7)]


def test_ws24f_qd_sections_keep_their_topic_terms():
    """只删通用词，不删各章自己的主题词。"""
    assert query_terms(resolve_section("qd_bz_shuoming", "feilv")["rag_query"])[:2] == ["费率", "最低限价"]
    assert "项目概况" in query_terms(resolve_section("qd_bz_shuoming", "gaikuang")["rag_query"])


# ---------------------------------------------------------------- WS24-o（issue #884，R24-42、R24-46）

# 内部说明里的用语（「来源 doc 附件6-4…」「PM 拍板 2026-07-22」「jiesuan_shenhe_bg_shizheng」）不许出现在给用户看的说明里
_INTERNAL_WORDING = re.compile(r"[A-Za-z]|拍板|附件\d|附样")


def test_ws24o_every_template_has_a_note_for_users():
    """24 套模板都有 note_user：一句话说这套模板写什么、要哪几类资料；不带内部用语、地名、写死的百分数。"""
    bad = []
    for t in _raw_templates():
        note = (t.get("note_user") or "").strip()
        if not note:
            bad.append((t["template_code"], "缺 note_user"))
            continue
        if _INTERNAL_WORDING.search(note):
            bad.append((t["template_code"], _INTERNAL_WORDING.search(note).group()))
        bad += [(t["template_code"], c) for c in _ZJ_PREFECTURE_CITIES if c in note]
        bad += [(t["template_code"], m.group()) for m in _HARDCODED_PERCENT.finditer(note)]
        if "需要" not in note:
            bad.append((t["template_code"], "没写需要哪些资料"))
    assert len(_raw_templates()) == 24
    assert bad == []


def test_ws24o_internal_note_is_what_the_check_would_catch():
    """自检的牙：把现在的内部 note 拿来当 note_user，24 套全部会被点名（23 套含「来源 doc」或「PM 拍板」，
    月报那条含「docx」）。"""
    caught = [t["template_code"] for t in _raw_templates() if _INTERNAL_WORDING.search(t.get("note") or "")]
    assert len(caught) == 24


def test_ws24o_settlement_note_names_the_materials_it_needs():
    t = next(x for x in _all_templates() if x["template_code"] == "jiesuan_shenhe_bg")
    for doc in ("送审结算书", "审定单", "施工合同", "【待补】"):
        assert doc in t["note_user"], doc


def test_ws24o_summary_returns_note_user():
    ts = _listed()
    assert all(t["note_user"] for t in ts)
    assert next(t for t in ts if t["template_code"] == "qd_bz_shuoming")["note_user"].startswith("工程量清单编制说明")


# ---------------------------------------------------------------- WS24-p（issue #915，D-R154）

import json  # noqa: E402

from zt.report.compose import prompt_version  # noqa: E402
from zt.report.templates import spec_of  # noqa: E402

_GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "prompt_versions.json").read_text(encoding="utf-8"))


def _endpoint_sections():
    return [(t["template_code"], s) for t in templates() for s in t["sections"]]


def test_ws24p_every_section_has_a_prompt_version():
    secs = _endpoint_sections()
    assert len(secs) == 172, "章数对不上时别让下一条在空集上通过"
    bad = [(tc, s["code"]) for tc, s in secs if not re.fullmatch(r"[0-9a-f]{16}", s.get("prompt_version") or "")]
    assert bad == []


def test_ws24p_template_prompt_version_equals_report_section_for_every_section():
    """模板列表里的值与 section_prepare 用的值逐章相同：两边都经 spec_of 造 SectionSpec。"""
    diff = [(tc, s["code"]) for tc, s in _endpoint_sections() if prompt_version(spec_of(s)) != s["prompt_version"]]
    assert diff == []


def test_prompt_version_equals_old_engine_for_every_section():
    """zt 迁入的验收：172 章逐章与旧引擎算出的 prompt_version 相同（金标由旧仓代码生成，见夹具 _说明）。
    不同就说明提示词口径变了：要么是迁移改坏了，要么是有意改措辞 —— 后者要升 PROMPT_TEMPLATE_VERSION 并重做金标。"""
    from zt.report.compose import PROMPT_TEMPLATE_VERSION

    assert PROMPT_TEMPLATE_VERSION == _GOLDEN["PROMPT_TEMPLATE_VERSION"]
    got = {t["template_code"]: {s["code"]: s["prompt_version"] for s in t["sections"]} for t in templates()}
    assert got == _GOLDEN["templates"]
    assert sum(len(v) for v in got.values()) == 172


def test_ws24p_prompt_version_differs_where_the_prompt_differs():
    """不是常量：172 章里写作要求不同的章，版本号就不同（防一个恒等的假值让上一条照样通过）。"""
    secs = _endpoint_sections()
    by_prompt = {}
    for tc, s in secs:
        key = (s["title"], s["gen_prompt"], tuple(s["attachment_hints"]), tuple(s["excludes"]),
               tuple((c["key"], c["text"]) for c in s["claims"]))
        by_prompt.setdefault(key, set()).add(s["prompt_version"])
    assert all(len(v) == 1 for v in by_prompt.values()), "同样的提示词字段必须同一个版本"
    assert len({v for vs in by_prompt.values() for v in vs}) == len(by_prompt), "不同的提示词字段必须不同的版本"


def test_ws24p_section_prepare_returns_the_same_prompt_version_as_the_template():
    """端到端：section_prepare 回来的 prompt_version 与模板列表这一章的值相同。"""
    tc, code = "jiesuan_shenhe_bg", "daoyu"
    want = next(s["prompt_version"] for t, s in _endpoint_sections() if t == tc and s["code"] == code)
    ctx = {"files": [{"index": 1, "file_id": "f1", "file_name": "合同.pdf", "text": "受委托对本工程结算进行审核。",
                      "text_source": "text_layer"}], "unreadable": []}
    env = service.section_prepare(list(templates()), tc, code, ctx)
    assert env.data["prompt_version"] == want
