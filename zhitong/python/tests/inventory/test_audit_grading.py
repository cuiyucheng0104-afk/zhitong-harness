"""迁移自旧仓 engine-service/tests/test_audit_evidence_grading.py；未迁移其中走 /engine/audit/check 端点的用例。

WS13-P13 / P18 / P19（issue #759）：核查层按证据定级、三档要求级别、零标注输入。

复现基线（origin/dev 02f27170）—— check_checklist_detailed 只要类目或别名对上就算命中：
  - 42008 施工合同只被一份 LLM 错标的「勘察外业见证合同」命中 → 已备（QA P3 施工过程 rate 0.5，两条命中全是假的）；
  - 「22 进度款…/…清单审计」文件命中 42005 工程量清单 → 控制价阶段 rate=1.0（QA A15 金义，人工口径 0.0）；
  - requirement_level=important 与 optional 同样处理：缺了不报、不进分母（42016 竣工图纸 26 次运行一次都没报过缺）；
  - files_with_tags=[] 照样给出「0% + 全部缺件」。

定级口径（spec P13）：confirmed（人工确认 / source=manual）> strong（evidence=filename_rule）> weak（其余，
含缺 evidence 的旧行）。**不按 needs_manual 定级** —— 「施工合同.pdf 待 OCR」needs_manual=True 但它是文件名
强规则命中，是真证据（QA 龙芯的施工合同.pdf，GT 判定存在）。
"""
from __future__ import annotations

from tests.inventory._support import check_checklist_detailed, check_checklist_graded

ITEM_42008 = {"stage_code": "施工过程", "doc_category": "施工合同及补充协议", "item_name": "施工合同及补充协议",
              "requirement_level": "required", "aliases": []}
ITEM_42005 = {"stage_code": "招标控制价", "doc_category": "工程量清单", "item_name": "工程量清单",
              "requirement_level": "required", "aliases": []}
ITEM_42016 = {"stage_code": "结算", "doc_category": "竣工图", "item_name": "竣工图纸",
              "requirement_level": "important", "aliases": ["竣工图"]}


def _f(fid, cat, stage=None, **kw):
    return {"file_id": fid, "file_name": kw.pop("file_name", f"{fid}.pdf"), "doc_category": cat,
            "cost_stage": stage, "doc_key": kw.pop("doc_key", fid), **kw}


def test_1_llm_only_evidence_is_pending_not_numerator():
    """① 42008 只有 llm 证据 → 进 pending，不进分子。变异：一律定为 strong → 转红。"""
    g = check_checklist_graded([_f("k1", "施工合同及补充协议", "施工过程", source="llm", evidence="llm",
                                   needs_manual=True, file_name="勘察外业见证合同.docx")], [ITEM_42008])
    assert g["coverage_rate"] == 0.0
    assert g["coverage_rate_upper"] == 1.0
    assert (g["required_covered"], g["required_pending"]) == (0, 1)
    assert [p["item_name"] for p in g["pending"]] == ["施工合同及补充协议"]
    assert g["pending"][0]["best_grade"] == "weak"
    assert g["missing"] == [] and g["covered"] == []


def test_2_filename_rule_with_needs_manual_is_covered():
    """② 施工合同.pdf：filename_rule 且 needs_manual=True（扫描件待 OCR）→ 已备。变异：按 needs_manual 定级 → 转红。"""
    g = check_checklist_graded([_f("c1", "施工合同及补充协议", "施工过程", source="rule", evidence="filename_rule",
                                   needs_manual=True, file_name="施工合同.pdf")], [ITEM_42008])
    assert g["coverage_rate"] == 1.0
    assert [c["item_name"] for c in g["covered"]] == ["施工合同及补充协议"]
    assert g["covered"][0]["matched_files"][0]["grade"] == "strong"


def test_3_bill_audit_file_under_progress_payment_dir_conflicts():
    """③ 清单审计文件在「22 进度款」下命中 42005 → 进 pending，带 conflict。变异：冲突表置空 → 转红。"""
    f = _f("q1", "工程量清单", "招标控制价", source="rule", evidence="filename_rule",
           file_name="(10月进度款)某工程.清单审计", ancestors=["第3期", "22 进度款审核及付款建议"],
           display_path="/22 进度款审核及付款建议/第3期/(10月进度款)某工程.清单审计")
    g = check_checklist_graded([f], [ITEM_42005])
    assert g["coverage_rate"] == 0.0
    [row] = g["pending"]
    hit = row["matched_files"][0]
    assert hit["grade"] == "weak"
    assert hit["conflict"]["word"] == "进度款"
    assert "22 进度款" in hit["conflict"]["segment"]


def test_3b_conflict_ignores_the_project_container_root():
    """冲突只看已剔容器根的 ancestors：项目根叫「××结算审核项目」不能把整项目的清单都降级。"""
    f = _f("q2", "工程量清单", "招标控制价", evidence="filename_rule", file_name="工程量清单.xlsx",
           ancestors=["4 招标文件及清单(控制价)"],
           display_path="/某某结算审核项目/4 招标文件及清单(控制价)/工程量清单.xlsx")
    g = check_checklist_graded([f], [ITEM_42005])
    assert g["coverage_rate"] == 1.0, g


def test_4_manual_confirmation_beats_weak():
    """④ 人工确认与 weak 同时命中 → 人工确认胜出。"""
    g = check_checklist_graded([
        _f("w1", "施工合同及补充协议", "施工过程", evidence="ancestor_inherit"),
        _f("m1", "施工合同及补充协议", "施工过程", source="manual", evidence="manual", confirm_state="confirmed"),
    ], [ITEM_42008])
    assert g["coverage_rate"] == 1.0
    assert g["covered"][0]["best_grade"] == "confirmed"
    assert g["covered"][0]["matched_files"][0]["file_id"] == "m1"


def test_5_legacy_row_without_evidence_is_weak():
    """⑤ 缺 evidence 字段的旧行 → weak（不许「缺字段当 strong」：那会把 Java 漏传变成静默虚高）。"""
    g = check_checklist_graded([_f("o1", "施工合同及补充协议", "施工过程")], [ITEM_42008])
    assert g["coverage_rate"] == 0.0 and g["required_pending"] == 1


def test_rejected_rows_are_not_evidence():
    g = check_checklist_graded([_f("r1", "施工合同及补充协议", "施工过程", evidence="filename_rule",
                                   confirm_state="rejected")], [ITEM_42008])
    assert [m["item_name"] for m in g["missing"]] == ["施工合同及补充协议"]
    assert g["input_stats"]["ignored_rejected"] == 1


def test_projection_keeps_pending_out_of_the_old_shapes():
    """旧五元组是 graded 的投影：弱证据项既不算已备，也不冒充缺件。"""
    missing, rate, total, covered, _deg = check_checklist_detailed(
        [_f("k1", "施工合同及补充协议", "施工过程", evidence="llm")], [ITEM_42008])
    assert (missing, covered, rate, total) == ([], [], 0.0, 1)


# ---------------------------------------------------------------- P18 三档

def test_important_missing_goes_to_advisory_not_missing_nor_denominator():
    g = check_checklist_graded([_f("c1", "施工合同及补充协议", "施工过程", evidence="filename_rule")],
                               [ITEM_42008, ITEM_42016])
    assert [a["item_name"] for a in g["advisory"]] == ["竣工图纸"]
    assert [m["item_name"] for m in g["missing"]] == []
    assert g["required_total"] == 1 and g["important_total"] == 1
    assert g["coverage_rate"] == 1.0


def test_important_hit_goes_to_covered():
    g = check_checklist_graded([_f("d1", "竣工图", "结算", evidence="filename_rule")], [ITEM_42016])
    assert [c["item_name"] for c in g["covered"]] == ["竣工图纸"]
    assert g["advisory"] == [] and g["coverage_rate"] is None


def test_numeric_level_two_is_important():
    g = check_checklist_graded([], [{**ITEM_42016, "requirement_level": "2"}])
    assert g["important_total"] == 1


# ---------------------------------------------------------------- P19 零输入

def test_empty_input_has_no_rate():
    g = check_checklist_graded([], [ITEM_42008, ITEM_42005])
    assert g["input_empty"] is True
    assert g["coverage_rate"] is None and g["coverage_rate_upper"] is None


def test_uncategorized_only_input_is_empty_too():
    g = check_checklist_graded([_f("n1", None), _f("n2", "")], [ITEM_42008])
    assert g["input_empty"] is True and g["coverage_rate"] is None
    assert g["input_stats"]["ignored_uncategorized"] == 2
