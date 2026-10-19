"""迁移自旧仓 engine-service/tests/test_audit_coverage_disclosure.py；未迁移其中三元返回的向后兼容用例（本仓无旧调用方）。

齐套核查的命中明细与降级披露（issue：静默降级 + hits 被丢弃）。

**这个文件要钉住两件此前不可见的事：**

1. **降级是静默的**：`audit_check` 的规则是「清单项有阶段、文件也有阶段 ⇒ 要求一致；
   任一侧缺 ⇒ 只按类目匹配」。而 `classify_rules.yaml` 里 42 条 `archive_keyword`
   规则带 `cost_stage` 的是 **0 条** —— 走归档路线的文件必然「有类目、无阶段」，
   **100% 触发降级**，覆盖施工图、图纸会审、竣工图、项目立项、可研、地勘等主力件。
   不标出来，就会拿一个系统性偏高的齐套率去验收，而且没人会发现。

2. **`hits` 算出来被丢弃**：此前只用作 `if hits:` 布尔判断，命中项根本不返回。
   客户问「你这 80% 怎么来的」时列不出依据。

⚠️ 本文件的断言全部走**真函数**，不模拟分母裁剪 —— 此前 `test_audit_stage_scope.py`
就栽在这：把阶段判定整条改成 `if False:`，该文件断言逐位不变（用例名声称钉住
「阶段裁剪后的真实齐套率」，实际只钉住了测试自己那行列表推导）。
"""

import itertools

from tests.inventory._support import check_checklist_detailed

_ids = itertools.count(1)


def _item(cat, stage=None, level="required"):
    d = {"doc_category": cat, "requirement_level": level}
    if stage is not None:
        d["stage_code"] = stage
    return d


def _file(cat, stage=None):
    # WS13-P13（#759）：核查按证据定级，只有 confirmed / strong 进分子。本文件测的是「命中与降级披露」，
    # 夹具一律给强证据（文件名强规则），各自带不同 file_id（同 doc_key 才算同一份文档）。
    d = {"file_id": f"f{next(_ids)}", "doc_category": cat, "evidence": "filename_rule"}
    if stage is not None:
        d["cost_stage"] = stage
    return d


# ── 三条阶段一致性断言（交接件 C 点名的三条）────────────────────────────

def test_阶段一致则命中且不标降级():
    _m, rate, total, covered, deg = check_checklist_detailed(
        [_file("施工图", "施工过程")], [_item("施工图", "施工过程")]
    )
    assert (rate, total) == (1.0, 1)
    assert len(covered) == 1
    assert covered[0]["matched_by"] == "stage_and_category"
    assert deg == 0, "两侧阶段都在且一致，不该记为降级"


def test_阶段不一致则不命中():
    """此前零覆盖 —— 正是「把阶段判定改成 if False 而断言不变」测出来的那个洞。"""
    missing, rate, total, covered, deg = check_checklist_detailed(
        [_file("施工图", "结算")], [_item("施工图", "施工过程")]
    )
    assert (rate, total) == (0.0, 1)
    assert covered == [], "阶段不一致不应产生任何命中"
    assert len(missing) == 1
    assert deg == 0


def test_任一侧缺阶段则降级为只按类目_且标记必须在():
    """归档路线的真实形状：文件有类目、无阶段。"""
    for files, items, why in [
        ([_file("施工图")], [_item("施工图", "施工过程")], "文件侧缺阶段（归档路线）"),
        ([_file("施工图", "施工过程")], [_item("施工图")], "清单项侧缺阶段"),
    ]:
        _m, rate, total, covered, deg = check_checklist_detailed(files, items)
        assert (rate, total) == (1.0, 1), why
        assert covered[0]["matched_by"] == "category_only", f"{why}：降级标记缺失"
        assert deg == 1, f"{why}：degraded_matches 未计数"


def test_两侧都无阶段不算降级():
    """都没有阶段可校验，不是"跳过了校验"，别虚报降级。"""
    _m, _r, _t, covered, deg = check_checklist_detailed(
        [_file("施工图")], [_item("施工图")]
    )
    assert covered[0]["matched_by"] == "stage_and_category"
    assert deg == 0


# ── 命中明细 ────────────────────────────────────────────────────────────

def test_命中明细能回答_这个数字怎么来的():
    files = [_file("施工图", "施工过程"), _file("图纸会审", "施工过程")]
    checklist = [_item("施工图", "施工过程"), _item("图纸会审", "施工过程"),
                 _item("竣工图", "施工过程")]
    _m, rate, total, covered, _d = check_checklist_detailed(files, checklist)
    assert (rate, total) == (round(2 / 3, 4), 3)
    # 关键：能列出「哪两项命中了、各自被哪些文件命中」
    got = {c["doc_category"]: [f["doc_category"] for f in c["matched_files"]] for c in covered}
    assert got == {"施工图": ["施工图"], "图纸会审": ["图纸会审"]}


def test_多份文件命中同一项_分子只加一次():
    """分子计数语义：三份文件命中同一清单项 → 分子加 1，不是 3。"""
    files = [_file("施工图", "施工过程") for _ in range(3)]
    _m, rate, total, covered, _d = check_checklist_detailed(
        files, [_item("施工图", "施工过程")]
    )
    assert (rate, total) == (1.0, 1)
    assert len(covered) == 1
    assert len(covered[0]["matched_files"]) == 3, "明细要列全三份，但分子只算一次"


def test_optional_项命中也进_covered_但不进分母():
    _m, rate, total, covered, _d = check_checklist_detailed(
        [_file("现场照片", "施工过程")],
        [_item("现场照片", "施工过程", level="optional")],
    )
    assert (rate, total) == (None, 0), "没有 required 项 ⇒ 没有比例可言"
    assert len(covered) == 1, "optional 命中仍应出现在明细里"
