# 来源：engine-service/tests/test_quantity_rules.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""工程量清单生成的确定性规则（WS11，issue #763）：语义一致性闸、做法词表、专业范围、标段排除、签名。"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from zt import code_registry
from zt.quantity import rules
from tests.quantity.fixtures.shapes import NOT_EXCLUSION_SENTENCES, OWNER_INLINE_LAYERS

# ============================================================ QTY-02 语义一致性闸（错码例与正例各半）

# (编码, 原文, 上下文, 期望违反的规则 id；None = 一致)
CASES = [
    # —— QA 错码证据（全部应违反） ——
    ("Z011201001", "10厚1:2水泥砂浆罩面压实赶光", "踢脚 踢脚做法 地下汽车库", "skirting"),
    ("Z011201001", "8厚地砖踢脚", "楼地面 门厅", "skirting"),
    ("Z011301001", "刷白色乳胶漆两遍", "顶棚 顶棚做法 地下汽车库", "ceiling_paint"),
    ("Z010902002", "1.5厚聚氨酯防水涂料", "楼地面 卫生间 楼面2", "floor_coating_waterproof"),
    ("010903002", "水泥基渗透结晶型防水涂料", "楼地面 地下室地面", "floor_coating_waterproof"),
    ("Z010902001", "4厚SBS改性沥青防水卷材", "基础 底板 地下室底板", "slab_membrane"),
    ("010402001", "C30钢筋混凝土挡土墙", "室外工程", "retaining_wall"),
    ("011101001", "40厚C20细石混凝土面层", "楼地面 地面1", "fine_concrete_not_cement_floor"),
    ("011101001", "20厚1:3水泥砂浆找平层", "屋面 屋面1", "roof_leveling_not_floor"),
    ("011203003", "10厚防滑地砖面层", "楼地面 楼面3", "floor_tile_not_wall"),
    ("Z011301001", "9.5厚纸面石膏板", "顶棚 吊顶", "ceiling_suspended_not_plaster"),
    ("Z010902001", "1.5厚聚氨酯防水涂料", "墙面 内墙 卫生间墙面", "wall_waterproof_not_roof"),
    # R4F-d：新造错码与部位/当前层正控，不作为专业质量金标。
    ("Z010902004", "37厚C25细石混凝土保护层", "楼地面 楼面31 合成设备间", "floor_fine_concrete_not_roof"),
    ("011404001", "2厚普通地坪漆面层", "楼地面 楼面32 合成储藏间", "floor_paint_not_wall"),
    ("011001003", "90厚普通砌块保护层", "墙面 内墙31 合成井壁", "block_protection_not_insulation"),
    ("Z010902004", "47厚C25细石混凝土刚性层", "屋面31 合成平屋顶", None),
    ("011404001", "刷普通乳胶漆两遍", "墙面 内墙32 合成值班间", None),
    ("011001003", "75厚岩棉保温层", "墙面 外墙31 合成外墙", None),
    ("011001003", "95厚保温砌块保护层", "墙面 外墙33", None),
    # —— 正例（全部应一致） ——
    ("011105001", "10厚1:2水泥砂浆罩面压实赶光", "踢脚 踢脚做法 地下汽车库", None),
    ("011105003", "8厚地砖踢脚", "楼地面 门厅", None),
    ("011404002", "刷白色乳胶漆两遍", "顶棚 顶棚做法 地下汽车库", None),
    ("Z010904002", "1.5厚聚氨酯防水涂料", "楼地面 卫生间 楼面2", None),
    ("Z010905001", "4厚SBS改性沥青防水卷材", "基础 底板 地下室底板", None),
    ("010502026", "C30钢筋混凝土挡土墙", "室外工程", None),
    ("011101002", "40厚C20细石混凝土面层", "楼地面 地面1", None),
    ("Z011101006", "20厚1:3水泥砂浆找平层", "屋面 屋面1", None),
    ("011102003", "10厚防滑地砖面层", "楼地面 楼面3", None),
    ("Z011302001", "9.5厚纸面石膏板", "顶棚 吊顶", None),
    ("010903002", "1.5厚聚氨酯防水涂料", "墙面 内墙 卫生间墙面", None),
    ("011001001", "60厚挤塑聚苯板保温层", "屋面 屋面1", None),
    # —— WS29-k2（E30）：坡道编成台阶、楼梯踏步砂浆编成楼地面、防水砂浆编成涂膜防水 ——
    ("011107001", "90厚C20细石混凝土坡道面层，随捣随抹", "坡道 坡道2 细石混凝土坡道 地下汽车坡道", "ramp_not_step"),
    ("011107002", "20厚毛面花岗石板，干水泥擦缝", "坡道 坡道1 石材坡道1 非机动车坡道", "ramp_not_step"),
    ("011101001", "楼梯踏步 20厚1:2水泥砂浆面层", "楼梯 楼梯1", "stair_not_floor"),
    ("Z011101006", "30厚DS15预拌砂浆抹压平整", "楼地面 楼面9 水泥砂浆楼面2 人防楼梯", "stair_not_floor"),
    ("010905002", "20厚1：2水泥防水砂浆", "外墙 地下室外墙", "waterproof_mortar_not_coating"),
    ("Z010904002", "20厚1:2.5水泥防水砂浆，内掺防水剂", "楼地面 卫生间", "waterproof_mortar_not_coating"),
    # 正例与「做对的不许被误伤」（C-R16）
    ("011107002", "30厚花岗岩台阶面层", "台阶 其它2 花岗岩台阶 一层入口台阶", None),
    ("011107002", "30厚花岗石板铺面", "台阶 其它2 花岗石台阶 入口台阶及无障碍坡道", None),   # 部位提到坡道，但这是台阶
    ("011107001", "现浇或砖砌台阶基层", "坡道 坡道1 石材坡道1", None),                        # 原文写着台阶：不拦
    ("010502031", "90厚C20细石混凝土坡道面层，随捣随抹", "坡道 坡道2 细石混凝土坡道", None),
    ("011106001", "楼梯踏步 20厚1:2水泥砂浆面层", "楼梯 楼梯1", None),
    ("011101001", "20厚1:2水泥砂浆面层", "楼地面 地面2 门厅", None),                          # 不是楼梯：照常过
    ("011102001", "20厚花岗岩面层（踏步设防滑条）", "楼梯 楼面9 楼梯间", None),                 # 楼梯里的石材不归这条
    ("010903003", "20厚1：2水泥防水砂浆", "外墙 地下室外墙", None),
    ("Z010904003", "20厚1:2.5水泥防水砂浆，内掺防水剂", "楼地面 卫生间", None),
    ("010905002", "1.5厚聚合物水泥防水涂料", "基础 底板 地下室底板", None),                     # 真的是涂膜：照常过
]


@pytest.mark.parametrize("code,text,ctx,rule", CASES)
def test_consistency_gate_table(code, text, ctx, rule):
    assert code_registry.lookup(code) is not None, f"夹具编码必须在码表里：{code}"
    got = [v.rule_id for v in rules.check_consistency(code, text, ctx)]
    if rule is None:
        assert got == [], f"{code} 与「{text}」一致，不该降级：{got}"
    else:
        assert rule in got, f"{code} 与「{text}」应违反 {rule}，实得 {got}"


def test_consistency_cases_are_balanced():
    bad = sum(1 for c in CASES if c[3])
    good = sum(1 for c in CASES if c[3] is None)
    assert bad >= 8 and good >= 8 and len(CASES) >= 16


def test_every_rule_has_a_violating_case():
    covered = {c[3] for c in CASES if c[3]}
    ids = set(rules.rule_summary().ids)
    assert ids - covered <= {"roof_membrane", "roof_coating", "floor_membrane_not_roof", "wall_tile_not_floor",
                             "wall_paint_not_plaster", "roof_insulation"}, ids - covered
    # 其余规则的违反例
    assert "roof_membrane" in [v.rule_id for v in rules.check_consistency("Z010904001", "3厚SBS卷材", "屋面 屋面1")]
    assert "roof_coating" in [v.rule_id for v in rules.check_consistency("Z010904002", "2厚聚氨酯", "屋面")]
    assert "floor_membrane_not_roof" in [v.rule_id for v in rules.check_consistency("Z010902001", "3厚卷材", "楼面")]
    assert "wall_tile_not_floor" in [v.rule_id for v in rules.check_consistency("011102003", "5厚釉面砖", "内墙")]
    assert "wall_paint_not_plaster" in [v.rule_id for v in rules.check_consistency("Z011201001", "刷乳胶漆", "内墙")]
    assert "roof_insulation" in [v.rule_id for v in rules.check_consistency("011001003", "60厚挤塑板", "屋面")]


def test_rule_codes_exist_in_registry():
    reg = code_registry.load_registry("zj2025")
    bare = {c[1:] if c.startswith("Z") else c for c in reg}
    for r in rules.load_rules()["consistency_rules"]:
        for p in (r.get("expect") or []) + (r.get("forbid") or []) + (r.get("suggest") or []):
            assert any(b.startswith(p) for b in bare), f"规则 {r['id']} 的前缀 {p} 在码表里一个都对不上"


@pytest.mark.parametrize("code,text,ctx,rule,want", [
    ("011107001", "90厚C20细石混凝土坡道面层", "坡道 坡道2", "ramp_not_step", ("010502031",)),
    ("011101001", "楼梯踏步 20厚1:2水泥砂浆面层", "楼梯 楼梯1", "stair_not_floor", ("011106001",)),
    ("010905002", "20厚1：2水泥防水砂浆", "外墙", "waterproof_mortar_not_coating", ("010903003", "010904003")),
])
def test_forbid_rules_carry_expected_codes_for_the_suggestion(code, text, ctx, rule, want):
    """WS29-k2：forbid 型规则命中后建议栏要写出期望的码（D-R184：只给建议，码由造价员定）。"""
    v = next(v for v in rules.check_consistency(code, text, ctx) if v.rule_id == rule)
    assert v.suggest == want and not v.expect


# 外露铁件（E31）：漆类层原来一个材料词都不中，整组落成 other；「除锈」仍不是做法层，由「块内未识别行」交代
@pytest.mark.parametrize("text", ["氟碳金属面漆（颜色另详）", "氟碳金属底漆", "刷专用防锈漆", "罩面漆", "专用底漆一道",
                                  "刷氟碳漆两遍", "调和油漆两遍", "木作清漆三遍"])
def test_paint_layers_are_practice_in_block(text):
    assert rules.looks_like_practice(text, in_block=True), text


def test_derusting_line_is_still_not_a_practice_layer():
    assert not rules.looks_like_practice("清理基层，除锈等级不应低于Sa2.5或St3级", in_block=True)


# ============================================================ QTY-03 做法词表

QA_MISSES = [
    "20厚陶粒混凝土找坡",
    "油毡一层",
    "40厚细石混凝土保护层",
    "界面剂一道",
    "水泥基渗透结晶型防水涂料",
    "50厚岩棉板",
    "U型轻钢龙骨中距600",
    "9.5厚纸面石膏板",
    "铝板网一层",
]


@pytest.mark.parametrize("text", QA_MISSES)
def test_practice_lexicon_catches_qa_misses(text):
    assert rules.looks_like_practice(text, in_block=True), f"做法块里的「{text}」必须识别为做法层"


def test_loose_line_needs_thickness_or_strength():
    assert not rules.looks_like_practice("外墙涂料颜色详见立面图", in_block=False)
    assert rules.looks_like_practice("屋面防水：2.0厚聚氨酯防水涂料", in_block=False)
    assert rules.looks_like_practice("M7.5水泥砂浆砌筑", in_block=False)


# ============================================================ QTY-07 专业范围

def test_file_scope_counts_domains():
    road = rules.file_scope("道路路基 路面沥青 车行道 人行道 桥梁 箱梁 伸缩缝 " * 5)
    assert road.out_of_scope and road.domain == rules.MUNICIPAL
    hvac = rules.file_scope("空调风管 风机盘管 配电箱 桥架 电缆 " * 5)
    assert hvac.out_of_scope and hvac.domain == rules.INSTALLATION
    building = rules.file_scope("楼地面做法 屋面防水 内墙乳胶漆 顶棚 踢脚 " * 5 + "配电箱 电缆 " * 3)
    assert not building.out_of_scope, "房建说明里偶尔出现几个安装词不算越界"


def test_heading_scope():
    assert rules.heading_scope("（五）桥梁工程") == rules.MUNICIPAL
    assert rules.heading_scope("六、电气照明") == rules.INSTALLATION
    assert rules.heading_scope("（四）屋面工程") is None
    assert rules.heading_scope("道路两侧外墙装修") is None, "混了房建词的标题不判越界"


# ============================================================ QTY-11 标段（D54）

@pytest.mark.parametrize("name,lot", [
    ("某站房工程III标", 3), ("某站房工程Ⅲ标段", 3), ("第三标段施工", 3), ("某工程IV标", 4),
    ("某工程Ⅳ标", 4), ("某工程4标段", 4), ("某工程第十二标段", 12), ("某工程", None), ("标准层改造", None),
    ("某工程2标准层", None),
])
def test_roman_numeral_normalization(name, lot):
    assert rules.parse_project_lot(name) == lot


def test_exclusion_sentence_parsed():
    ex = rules.find_exclusions("盖边柱、道路两侧柱、盖板顶棚涂料等盖板装修计入IV标。")
    assert ex == [("lot", ["盖边柱", "道路两侧柱", "盖板顶棚", "盖板"], 4)]
    assert rules.find_exclusions("卫生间洁具由业主另行发包")[0][:2] == ("owner", ["卫生间洁具"])
    assert rules.find_exclusions("20厚1:3水泥砂浆找平层") == []


def test_match_exclusion_uses_objects():
    ex = rules.Exclusion("e1", "lot", "盖边柱…计入IV标", ["盖边柱"], 4)
    assert rules.match_exclusion([ex], "喷真石漆两遍 外墙2 盖边柱真石漆") is ex
    assert rules.match_exclusion([ex], "刷乳胶漆两遍 内墙1") is None


# ============================================================ WS29-f 范围规则（issue #835）
# 实测「范围排除」22 条全错：否定句、定语、引用、条文号都被认成排除句的对象。下面的句式取自生产原文。

@pytest.mark.parametrize("sentence", NOT_EXCLUSION_SENTENCES)
def test_secondary_needs_predicate(sentence):
    # 否定（不需 / 不需要 / 无）、无谓词、引用、表注：都不是排除句。改前谓词可选，7 句全部命中
    assert rules.find_exclusions(sentence) == [], sentence
    assert rules.scope_related_words(sentence) == ["二次装修"], "这些句子要能进「范围相关原文」清单"


@pytest.mark.parametrize("sentence,objects", [
    ("楼地面面层均为二次装修", ["楼地面面层"]),
    ("楼地面面层均为二次装修，另行招标。", ["楼地面面层"]),
    ("卫生间墙面属于二次装修。", ["卫生间墙面"]),
    ("公共走道吊顶另做二次装修", ["公共走道吊顶"]),
    ("本工程卫生间作为二次装修。", ["卫生间"]),
    ("楼地面面层做法由二次装修设计确定。", ["楼地面面层"]),
])
def test_secondary_predicate_sentences_still_global(sentence, objects):
    assert rules.find_exclusions(sentence) == [("secondary", objects, None)]


@pytest.mark.parametrize("sentence", [
    "卫生间墙面不属于二次装修。",          # 否定
    "卫生间墙面属于二次装修范围以外",       # 「二次装修」后面不是句末
    "需二次装修墙面（燃烧性能A级）",         # 定语
    "外墙涂料为二次装修的预留做法",
])
def test_secondary_negation_and_attributive_not_matched(sentence):
    assert rules.find_exclusions(sentence) == []


def test_clause_number_is_not_an_object():
    # 段落文本带自动编号前缀「13.13 」。改前只去一级编号，剩下「13」当对象词，子串匹配排掉 14 个片段
    assert rules.find_exclusions("13.13 二次装修室内空间应考虑隔声降噪措施。") == []
    assert rules.find_exclusions("13.13 楼地面面层均为二次装修。") == [("secondary", ["楼地面面层"], None)]
    assert rules.find_exclusions("13.13、卫生间洁具由业主另行发包") == [("owner", ["卫生间洁具"], None)]
    assert rules.find_exclusions("23.3 住宅套内墙面不在本次设计范围") == [("not_in_scope", ["住宅套内墙面"], None)]
    assert rules.find_exclusions("（3）卫生间洁具由业主另行发包") == [("owner", ["卫生间洁具"], None)]
    # 厚度不是条文号：「1.5厚」不能被削成「厚…」
    assert rules.find_exclusions("1.5厚聚氨酯防水层由业主另行发包")[0][1] == ["1.5厚聚氨酯防水层"]


@pytest.mark.parametrize("sentence,expected", [
    ("注：1. 卫生间洁具、橱柜由业主另行发包。", ("owner", ["卫生间洁具", "橱柜"], None)),
    ("注： 2、楼地面面层均为二次装修。", ("secondary", ["楼地面面层"], None)),
    ("备注：3. 卫生间洁具由业主另行发包", ("owner", ["卫生间洁具"], None)),
    ("附注：（2）屋面保温不在本次设计范围", ("not_in_scope", ["屋面保温"], None)),
    ("说明：1、盖边柱真石漆计入IV标", ("lot", ["盖边柱真石漆"], 4)),
])
def test_clause_number_behind_note_label_is_not_an_object(sentence, expected):
    # 表注「注：1. …」：去掉前缀「注：」之后露出的序号也要去。改前对象词是「1. 卫生间洁具」，
    # 哪个片段都匹配不上，这条排除句列在清单里、却一层也排不掉（PR #839 评审）
    assert rules.find_exclusions(sentence) == [expected]


def test_thickness_behind_note_label_is_kept():
    assert rules.find_exclusions("注：1.5厚聚氨酯防水层由业主另行发包") == [("owner", ["1.5厚聚氨酯防水层"], None)]


@pytest.mark.parametrize("sentence", [
    "13.13 楼地面面层均为二次装修。", "13.13、卫生间洁具由业主另行发包", "1#、2#、13#住宅外墙保温计入IV标",
    "3、5、7层卫生间洁具由业主另行发包", "15.18 屋面保温不在本次设计范围", "A、B区地下室顶板防水计入IV标",
])
def test_objects_never_pure_number(sentence):
    found = rules.find_exclusions(sentence)
    assert found, "夹具必须是能认出来的排除句（否则对象词为空，下面是空比空）"
    for _kind, objs, _lot in found:
        for o in objs:
            assert len(re.findall(r"[\u4e00-\u9fff]", o)) >= 2, f"对象词不足 2 个汉字：{o!r} ← {sentence}"
            assert not re.match(r"\d+(?:[.．]\d+)+|\d+\s", o), f"对象词带着条文号：{o!r} ← {sentence}"
    assert rules.find_exclusions("1#、2#、13#住宅外墙保温计入IV标") == [("lot", ["13#住宅外墙保温"], 4)]


def test_object_bracket_fragments_removed():
    # 「（详」这样的括号残片不能留在对象词里
    assert rules.find_exclusions("卫生间洁具（详设备表）由业主另行发包") == [("owner", ["卫生间洁具"], None)]
    assert rules.find_exclusions("内掺建筑胶）地下室车库墙面均为二次装修") == [("secondary", ["地下室车库墙面"], None)]
    for _kind, objs, _lot in rules.find_exclusions("阳台栏杆（详见大样）、空调百叶计入IV标"):
        assert not any(ch in o for o in objs for ch in "()（）")


def test_generic_object_never_global():
    # 泛指词子串匹配会排掉半张表：不能单独作全局对象词
    for s in ("面层详二次装修", "注：面层为二次装修", "面层由业主自理", "装修由甲方另行发包"):
        assert rules.find_exclusions(s) == [], s
    scan = rules.scan_exclusions("注：面层为二次装修")
    assert scan.too_generic == (("secondary", ["面层"]),) and scan.rejected
    assert rules.scan_exclusions("面层详二次装修").rejected is False, "引用句不是排除句式，谈不上对象词泛指"
    # 与具体对象并列时只丢泛指词
    assert rules.find_exclusions("卫生间洁具、面层均由业主另行发包") == [("owner", ["卫生间洁具"], None)]
    assert rules.find_exclusions("不需、详由业主自理") == [], "功能词不能作对象词"


def test_find_exclusions_kind_filter():
    s = "盖边柱真石漆计入IV标，卫生间洁具由业主另行发包"
    assert {k for k, _o, _l in rules.find_exclusions(s)} == {"lot", "owner"}
    assert [k for k, _o, _l in rules.find_exclusions(s, rules.GLOBAL_IN_LAYER)] == ["lot"]


@pytest.mark.parametrize("layer", OWNER_INLINE_LAYERS)
def test_inline_owner_marker(layer):
    m = rules.find_inline_marker(layer)
    assert m is not None and m.code == rules.OWNER_INLINE and m.matched == "用户自理", layer
    assert rules.find_exclusions(layer) == [], "层内自理不产生全局排除句"


@pytest.mark.parametrize("layer,subject", [
    ("防滑地砖面层由业主自理", "业主"), ("面层住户自行铺贴", "住户"), ("涂料面层由租户另行委托", "租户"),
    ("面层由使用单位另行发包", "使用单位"), ("面层购房人自理", "购房人"),
])
def test_inline_owner_subjects(layer, subject):
    m = rules.find_inline_marker(layer)
    assert m is not None and m.code == rules.OWNER_INLINE and m.matched.startswith(subject)


@pytest.mark.parametrize("layer", ["面层为二次装修 详见装修图", "面层为二次装修 注：", "面层属于二次装修\t由装修单位深化"])
def test_inline_secondary_survives_merged_continuation(layer):
    # 续行并进上一层时中间隔一个空白。改前「二次装修」后面只认句末和标点，并完续行标记就丢了：
    # 这一层既不进范围排除，也不留痕，照常送模型
    assert rules.find_inline_marker(layer).code == rules.SECONDARY_INLINE


@pytest.mark.parametrize("layer", ["外墙涂料为二次装修的预留做法", "面层不属于二次装修 详见装修图",
                                   "卫生间墙面属于二次装修范围以外"])
def test_inline_secondary_attributive_and_negation_still_not_matched(layer):
    assert rules.find_inline_marker(layer) is None


def test_inline_marker_priority():
    both = rules.find_inline_marker("面层瓷砖用户自理（详二次装修）")
    assert both.code == rules.OWNER_INLINE and both.also == "详二次装修", "自理优先于精装修引用，引用写进原因"
    either = rules.find_inline_marker("面层瓷砖用户自理或（详精装修设计）")
    assert either.code == rules.OWNER_AMBIGUOUS, "「自理或…」不替人选"
    assert rules.find_inline_marker("面层用户自理或者详精装修设计").code == rules.OWNER_AMBIGUOUS
    sec = rules.find_inline_marker("面层为二次装修（详精装修设计）")
    assert sec.code == rules.SECONDARY_INLINE and sec.also == "详精装修设计"
    assert rules.find_inline_marker("面层由二次装修设计确定").code == rules.SECONDARY_INLINE


@pytest.mark.parametrize("layer,matched", [
    ("防滑地砖面层（详精装修设计）", "详精装修设计"),
    ("1.5厚Ⅱ型聚合物水泥防水涂料（详精装修设计）", "详精装修设计"),
    ("12厚DP15预拌砂浆找平（详精装修设计）", "详精装修设计"),
    ("装修吊顶（详二次装修图纸）", "详二次装修图纸"),
    ("面层详见精装修", "详见精装修"),
    ("面层按二次装修设计", "按二次装修设计"),
])
def test_inline_fitout_reference(layer, matched):
    m = rules.find_inline_marker(layer)
    assert m is not None and m.code == rules.FITOUT_PROVISIONAL and m.matched == matched and m.where == "layer"


def test_inline_fitout_on_practice_name_and_part():
    m = rules.find_inline_marker("9.5厚纸面石膏板", "顶棚3 装修吊顶（详二次装修图纸）", "")
    assert m.code == rules.FITOUT_PROVISIONAL and m.where == "practice"
    m = rules.find_inline_marker("12厚DP15预拌砂浆找平", "内墙6 需二次装修墙面", "")
    assert m.code == rules.FITOUT_PROVISIONAL and m.matched == "需二次装修"
    m = rules.find_inline_marker("12厚DP15预拌砂浆找平", "内墙6", "住宅套内（详精装修设计）")
    assert m.code == rules.FITOUT_PROVISIONAL and m.where == "part"
    # 「需二次装修」只在名称 / 部位上认；层正文里不认
    assert rules.find_inline_marker("12厚DP15预拌砂浆找平 住宅套内需二次装修的房间") is None


@pytest.mark.parametrize("layer,practice,part", [
    ("基层墙体 楼梯间、门卫等不需二次装修的非配水房间", "", ""),
    ("钢筋混凝土楼板清理 物业用房等无二次装修部分", "", ""),
    ("6厚DP15预拌砂浆找平", "内墙9 不需二次装修墙面", ""),
    ("6厚DP15预拌砂浆找平", "内墙9", "地下室车库等不需要二次装修的墙面"),
    ("6厚DP15预拌砂浆找平", "内墙9", "无需二次装修的设备用房"),
    ("20厚花岗岩面层", "", ""),
    ("住户自行车库地面：50厚C25细石混凝土", "", ""),     # 「自行车」不是「自行」
    ("卫生间墙面不属于二次装修", "", ""),
])
def test_no_inline_marker(layer, practice, part):
    # 「不需二次装修」的部位说明不触发任何标记（基线：它让三个做法整行消失）
    assert rules.find_inline_marker(layer, practice, part) is None


# ============================================================ QTY-09 规格签名

def test_spec_signature_normalization():
    assert rules.spec_signature("屋面防水：2.0厚聚氨酯防水涂料") == rules.spec_signature("2厚聚氨酯防水涂料")
    assert rules.spec_signature("1:3水泥砂浆，内掺5份防水剂") == rules.spec_signature("1:3水泥砂浆，内掺5分防水剂")
    assert rules.spec_signature("20厚1:2水泥砂浆面层") != rules.spec_signature("30厚1:2水泥砂浆面层")
    assert rules.spec_signature("20厚1:2水泥砂浆面层").startswith("20厚1:2"), "配合比的冒号不是标签"


# ============================================================ C2 告警 code 登记

def _emitted_codes() -> set[str]:
    # zt 改动：扫 zt/quantity/*.py（旧版扫 app/engine/quantity_*.py 与 app/api/quantity.py）
    pkg = Path(__file__).resolve().parents[2] / "zt" / "quantity"
    codes: set[str] = set()
    for p in sorted(pkg.glob("*.py")):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and node.value.startswith("quantity_") and node.value.replace("_", "").isalnum() \
                    and node.value.isascii() and node.value != "quantity_generate":
                codes.add(node.value)
    return codes


def test_warning_codes_registered():
    emitted = _emitted_codes()
    assert emitted, "一个 code 都没扫到 —— 扫描写错了？（铁律 8）"
    assert "quantity_llm_failed" in emitted
    unregistered = emitted - set(rules.WARNING_CODES)
    assert not unregistered, f"这些告警 code 发出来了却没在 quantity_rules.WARNING_CODES 登记：{unregistered}"


# ============================================================ 金标（D7：草稿，未签字不作门槛）

def test_golden_segments_are_well_formed():
    import yaml

    doc = yaml.safe_load((Path(__file__).resolve().parent / "fixtures" / "golden_segments.yaml")
                         .read_text(encoding="utf-8"))
    segs = doc["segments"]
    assert len(segs) >= 20 and doc["signed_off"] is False, "未经造价员签字前必须标 signed_off: false"
    reg = code_registry.load_registry("zj2025")
    for g in segs:
        assert g["role"] in ("main", "aux", "base"), g
        if g["role"] == "main":
            assert g["code"] in reg, f"金标编码不在码表：{g}"
            viol = rules.check_consistency(g["code"], g["text"], g.get("ctx", ""))
            assert not viol, f"金标本身违反语义闸（规则过宽，会误降级）：{g} → {[v.rule_id for v in viol]}"
        if g.get("linear"):
            assert reg[g["code"]]["unit"] == "m", g
