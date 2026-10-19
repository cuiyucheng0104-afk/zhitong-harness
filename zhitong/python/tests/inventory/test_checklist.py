"""清单数据与口径：与旧仓种子 SQL 对账、阶段累计口径、咨询类型分套、类目闸。

迁移自旧仓 engine-service/tests/test_audit_stage_scope.py（累计口径与分母数字）与
test_category_vocabulary_gate.py（类目闸 a–e）。旧测试读旧仓的种子 SQL；本仓的数据源是
``data/checklist.yaml``，所以这里多一条「与旧仓种子 SQL 逐列对账」，旧仓不在本机时跳过。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.inventory._support import CHECKLIST, DATA, RULES, VOCAB, canonical, check_checklist_graded, engine
from zt.common import ZtError
from zt.inventory.checklist import ALL, BASIS_ALL_STAGES, BASIS_CUMULATIVE, load_checklist
from zt.inventory.rules import ClassifyInput, classifier_vocabulary

OLD_SEED_SQL = Path("/home/user/zhitong-cost-ai/后端/sql/tenant-init/tenant-seed-template.sql")

_ITEM_RE = re.compile(
    r"INSERT\s+IGNORE\s+INTO\s+`cfg_checklist_item`[^V]*VALUES\s*\("
    r"\s*'(?P<id>[^']*)'\s*,\s*@tenant_code\s*,\s*'(?P<stage>[^']*)'\s*,\s*'(?P<cat>[^']*)'\s*,"
    r"\s*'(?P<item>[^']*)'\s*,\s*(?P<level>\d+)\s*,\s*'(?P<aliases>.*?)'\s*,\s*'(?P<ctype>[^']*)'\s*,", re.S)
_STAGE_RE = re.compile(
    r"INSERT\s+IGNORE\s+INTO\s+`cfg_checklist_stage`[^V]*VALUES\s*\("
    r"\s*'(?P<id>[^']*)'\s*,\s*@tenant_code\s*,\s*'(?P<code>[^']*)'\s*,\s*'(?P<name>[^']*)'\s*,\s*(?P<sort>\d+)\s*,", re.S)
_LEVEL = {"1": "required", "2": "important", "3": "optional"}

ITEMS = CHECKLIST.items
BY_ID = {it["item_id"]: it for it in ITEMS}


def _required(items):
    return [i for i in items if i["requirement_level"] == "required"]


# ---------------------------------------------------------------- 与旧仓种子 SQL 对账


@pytest.mark.skipif(not OLD_SEED_SQL.is_file(), reason="旧仓种子 SQL 不在本机：跳过 ≠ 通过")
def test_checklist_yaml_matches_old_seed_sql_column_by_column():
    sql = OLD_SEED_SQL.read_text(encoding="utf-8")
    old_items = {}
    for m in _ITEM_RE.finditer(sql):
        old_items[m["id"]] = dict(
            consulting_type=m["ctype"], stage_code=m["stage"], doc_category=m["cat"], item_name=m["item"],
            requirement_level=_LEVEL[m["level"]], aliases=json.loads(m["aliases"].replace('\\"', '"') or "[]"))
    old_stages = {m["code"]: (m["name"], int(m["sort"])) for m in _STAGE_RE.finditer(sql)}
    assert len(old_items) == 36 and len(old_stages) == 5, "旧仓种子形态变了，正则要跟着改"
    assert set(BY_ID) == set(old_items)
    for iid, old in old_items.items():
        new = {k: BY_ID[iid][k] for k in old}
        assert new == old, iid
    assert {s.code: (s.name, s.sort) for s in CHECKLIST.stages} == old_stages


def test_every_item_has_a_signoff_status_and_none_claims_customer_confirmation():
    """数据文件头要求：没有任何一条被标成「客户已确认」。"""
    statuses = {it["signoff"] for it in ITEMS}
    assert statuses <= {"seed", "provisional", "unconfirmed"}, statuses
    text = (DATA.data_dir / "checklist.yaml").read_text(encoding="utf-8")
    assert "待签核" in text.split("consulting_types:")[0]


def test_set_sizes():
    sizes = {}
    for it in ITEMS:
        sizes[it["consulting_type"]] = sizes.get(it["consulting_type"], 0) + 1
    assert sizes == {"ALL": 20, "20002": 12, "20003": 4}


# ---------------------------------------------------------------- 阶段累计口径


@pytest.mark.parametrize("stage,codes", [
    ("概算", ["概算"]),
    ("招标控制价", ["概算", "招标控制价"]),
    ("施工过程", ["概算", "招标控制价", "施工过程"]),
    ("结算", ["概算", "招标控制价", "施工过程", "结算"]),
    ("审定", ["概算", "招标控制价", "施工过程", "结算", "审定"]),
])
def test_stage_scope_is_cumulative(stage, codes):
    scope = CHECKLIST.stage_scope(stage)
    assert list(scope.stage_codes) == codes and scope.basis == BASIS_CUMULATIVE and scope.selected_stage == stage


def test_no_stage_means_all_stages_explicitly():
    scope = CHECKLIST.stage_scope(None)
    assert scope.basis == BASIS_ALL_STAGES and scope.selected_stage is None and len(scope.stage_codes) == 5
    assert CHECKLIST.stage_scope("  ").basis == BASIS_ALL_STAGES


def test_unknown_stage_fails_strictly():
    with pytest.raises(ZtError) as e:
        CHECKLIST.stage_scope("竣工")
    assert e.value.code == "unknown_stage" and "审定" in e.value.hint


def test_same_sort_stages_are_both_included(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "consulting_types: []\nstages:\n  - {stage_code: 甲, stage_name: 甲, sort: 1}\n"
        "  - {stage_code: 乙, stage_name: 乙, sort: 1}\n  - {stage_code: 丙, stage_name: 丙, sort: 2}\n"
        "items:\n  - {item_id: '1', consulting_type: ALL, stage_code: 甲, doc_category: x, item_name: x, "
        "requirement_level: required}\n", encoding="utf-8")
    assert list(load_checklist(p).stage_scope("甲").stage_codes) == ["甲", "乙"]


def test_real_denominators_per_stage_for_generic_set():
    """分母由清单项数决定：同一份清单，累计口径下各阶段的必备项数。"""
    expected = {"概算": 1, "招标控制价": 3, "施工过程": 7, "结算": 8, "审定": 11}
    got = {}
    for stage in expected:
        pick = CHECKLIST.pick(None, CHECKLIST.stage_scope(stage).stage_codes)
        got[stage] = len(_required(pick.items))
    assert got == expected, got


def test_denominator_matches_the_engine_not_the_test():
    """分母必须是核查函数自己算出的 required_total，而不是测试里数的列表。"""
    for stage, n in {"概算": 1, "审定": 11}.items():
        pick = CHECKLIST.pick(None, CHECKLIST.stage_scope(stage).stage_codes)
        g = check_checklist_graded([], pick.items)
        assert g["required_total"] == n and g["coverage_rate"] is None  # 空输入没有比例


# ---------------------------------------------------------------- 咨询类型分套


@pytest.mark.parametrize("raw,code", [
    ("20002", "20002"), ("结算审核", "20002"), ("结算审核（20002）", "20002"), ("全过程造价咨询", "20001"),
    ("招标控制价编制", "20003"), ("ALL", ALL), ("all", ALL), ("", None), (None, None), ("  ", None),
])
def test_resolve_consulting_type(raw, code):
    assert CHECKLIST.resolve_consulting_type(raw) == code


def test_unknown_consulting_type_lists_valid_ones():
    with pytest.raises(ZtError) as e:
        CHECKLIST.resolve_consulting_type("工程审计")
    assert e.value.code == "invalid_consulting_type" and "结算审核（20002）" in e.value.hint


def test_pick_uses_own_set_else_falls_back_to_all():
    stages = CHECKLIST.stage_scope("审定").stage_codes
    own = CHECKLIST.pick("20002", stages)
    assert own.checklist_set == "20002" and not own.fallback and len(own.items) == 12
    fb = CHECKLIST.pick("20001", stages)
    assert fb.checklist_set == ALL and fb.fallback and len(fb.items) == 20
    generic = CHECKLIST.pick(None, stages)
    assert generic.checklist_set == ALL and not generic.fallback
    # 累计口径照样作用在专属清单上：选「结算」不含审定阶段的成果件
    settle = CHECKLIST.pick("20002", CHECKLIST.stage_scope("结算").stage_codes)
    assert {i["stage_code"] for i in settle.items}.isdisjoint({"审定"}) and settle.items


def test_20003_at_stage_where_no_own_rows_in_scope_falls_back():
    """20003 的专属行最早在「概算」（42104）；选的阶段范围里没有任何专属行时才退回 ALL。"""
    own = CHECKLIST.pick("20003", CHECKLIST.stage_scope("概算").stage_codes)
    assert [i["item_id"] for i in own.items] == ["42104"] and not own.fallback


def test_load_checklist_rejects_bad_rows(tmp_path):
    bad = tmp_path / "c.yaml"
    bad.write_text("stages:\n  - {stage_code: 甲, sort: 1}\nitems:\n  - {item_id: '1', consulting_type: ALL, "
                   "stage_code: 乙, doc_category: x, item_name: x, requirement_level: required}\n", encoding="utf-8")
    with pytest.raises(ZtError) as e:
        load_checklist(bad)
    assert e.value.code == "checklist_invalid"


# ---------------------------------------------------------------- 类目闸（旧 WS13-P14）


def test_a_every_seed_category_and_alias_is_producible():
    vocab = set(classifier_vocabulary(RULES))
    assert len(vocab) >= 60, f"分类器类目词表只有 {len(vocab)} 个 —— 读错了规则文件？"
    names = [(it["item_name"], n) for it in ITEMS for n in [it["doc_category"], *it["aliases"]] if n]
    assert len(names) >= 19
    dead = [f"{item}:{n}" for item, n in names if n not in vocab]
    assert not dead, f"清单里有分类器产不出的类目/别名（死配置，永远命不中）：{dead}"


def test_b_every_classifier_category_has_a_destination():
    targets = {n for it in ITEMS for n in [it["doc_category"], *it["aliases"]] if n}
    vocab = classifier_vocabulary(RULES)
    orphans = [c for c in vocab if canonical(c) not in targets and c not in VOCAB.not_audited]
    assert not orphans, f"这些分类器类目既映射不到清单，也没登记 not_audited：{orphans}"
    both = set(VOCAB.not_audited) & set(VOCAB.mapping)
    assert not both, f"既在 map 又在 not_audited：{both}"
    assert all(str(v).strip() for v in VOCAB.not_audited.values()), "每条 not_audited 必须写理由"


def test_c_map_targets_are_real_checklist_categories():
    cats = {it["doc_category"] for it in ITEMS}
    assert len(VOCAB.mapping) >= 20
    bad = {k: v for k, v in VOCAB.mapping.items() if v not in cats}
    assert not bad, f"map 目标不是清单里的类目：{bad}"


def _classified(name: str, ext: str) -> dict:
    o = engine.classify_one(ClassifyInput("f", name, ext, has_text_layer=True))
    return {"file_id": name, "doc_category": o.doc_category, "cost_stage": o.cost_stage, "evidence": o.evidence}


def _hits(files: list[dict], item_id: str) -> list[str]:
    g = check_checklist_graded(files, [BY_ID[item_id]])
    return [f["file_id"] for c in [*g["covered"], *g["pending"]] for f in c["matched_files"]]


@pytest.mark.parametrize("name,ext", [
    ("建筑施工图.pdf", "pdf"), ("结构施工图.dwg", "dwg"), ("XX项目施工图.dwg", "dwg"), ("一层平面图.dwg", "dwg"),
])
def test_d_drawings_hit_every_construction_drawing_item(name, ext):
    f = _classified(name, ext)
    for item_id in ("42009", "42101", "42208"):
        assert _hits([f], item_id) == [name], f"{name} 判为 {f['doc_category']}，没命中 {item_id}"


def test_d_budget_does_not_hit_construction_drawings():
    for name in ("施工图预算书.xlsx", "关于施工图预算问题的回复.docx"):
        f = _classified(name, name.rsplit(".", 1)[1])
        assert f["doc_category"] is not None
        assert _hits([f], "42009") == [], f"{name}（{f['doc_category']}）不该命中 42009"


@pytest.mark.parametrize("name,item_id", [
    ("结算审定书.pdf", "42017"), ("结算定案表.xlsx", "42017"), ("结算审计报告.pdf", "42015"),
    ("初步设计概算批复.pdf", "42001"), ("工程结算送审书.pdf", "42020"), ("工程结算书(送审).pdf", "42020"),
    ("结算审定书.pdf", "42206"), ("结算审计报告.pdf", "42205"), ("工程结算送审书.pdf", "42204"),
    ("XX工程招标控制价.xlsx", "42102"), ("一标段工程量清单.xlsx", "42103"), ("初步设计概算批复.pdf", "42104"),
])
def test_d_settlement_and_approval_documents_hit_their_items(name, item_id):
    f = _classified(name, name.rsplit(".", 1)[1])
    assert _hits([f], item_id) == [name], f"{name} 判为 {f['doc_category']}/{f['cost_stage']}，没命中 {item_id}"


def test_canonicalizes_both_sides():
    item = {"stage_code": "施工过程", "doc_category": "施工图", "item_name": "施工图纸",
            "requirement_level": "required", "aliases": []}
    g = check_checklist_graded([{"file_id": "a", "doc_category": "建筑图纸", "evidence": "filename_rule"}], [item])
    assert (g["coverage_rate"], g["missing"]) == (1.0, [])
    g2 = check_checklist_graded([{"file_id": "b", "doc_category": "施工图", "evidence": "filename_rule"}],
                                [{**item, "doc_category": "结构图纸"}])
    assert g2["coverage_rate"] == 1.0


_ALLOWED_DEVIATION = {("42101", "stage_code"): "招标控制价"}


def test_e_consulting_sets_copy_the_generic_row():
    generic = {it["doc_category"]: it for it in ITEMS if it["consulting_type"] == "ALL"}
    own = [it for it in ITEMS if it["consulting_type"] != "ALL"]
    assert len(own) == 16
    diffs, used = [], set()
    for it in own:
        g = generic.get(it["doc_category"])
        assert g is not None, f"{it['item_id']} 的类目「{it['doc_category']}」在 ALL 里没有对应行"
        for col in ("item_name", "aliases", "stage_code"):
            key = (it["item_id"], col)
            if key in _ALLOWED_DEVIATION:
                used.add(key)
                assert it[col] == _ALLOWED_DEVIATION[key]
                continue
            if it[col] != g[col]:
                diffs.append(f"{it['item_id']} {col}: 分套={it[col]!r} ALL={g[col]!r}")
    assert not diffs, "分套清单与 ALL 同类目行不一致：\n  " + "\n  ".join(diffs)
    assert used == set(_ALLOWED_DEVIATION)


def test_e_manual_construction_stage_drawing_does_not_hit_42101():
    """人工把施工图标成「施工过程」的文件：42101 在「招标控制价」阶段，两侧阶段不同 → 不命中；
    没有阶段的（文件名规则）照样命中。"""
    manual = {"file_id": "m", "doc_category": "施工图", "cost_stage": "施工过程", "evidence": "manual",
              "confirm_state": "confirmed"}
    ruled = {**_classified("人防电气施工设计说明.docx", "docx"), "file_id": "r"}
    assert ruled["doc_category"] is not None and ruled["cost_stage"] is None
    assert _hits([manual], "42101") == []
    assert _hits([manual], "42009") == ["m"]
    assert _hits([ruled], "42101") == ["r"]
