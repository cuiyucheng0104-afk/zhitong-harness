"""迁移自旧仓 engine-service/tests/test_audit_gt_regression.py；清单改读 data/checklist.yaml，夹具逐字拷贝。

WS13-P13（issue #759）：核查回归 —— 人工判缺失的必备项，一项都不许被判成已备。

复现基线（origin/dev 02f27170）：QA 用生产 R1–R5 的真实标签复算，5 次「全部阶段」运行判定 50 个
必备项，错 5 个，**全部**是把缺失判成存在。本夹具把 spec 逐条写明的那几例合成成项目快照
（tests/fixtures/ws13_audit_gt/cases.json，_readme 写明来源与局限），两条管线各走一遍：

  legacy       —— 生产现存标签的形态：旧引擎的类目、**没有 evidence 列**（迁移前的行）；
  reclassified —— 用现行 ClassifyEngine 重新标注（文件名 + 已剔容器根的祖先链）再核查。

断言：
  1. 两条管线下，gt=missing 的清单项都不在 covered（已备）里 —— 可以在 pending（待确认）里；
  2. reclassified 管线下 gt=present 的召回数做棘轮（只许升不许降）。
变异：grade_of 恒回 strong（回退定级）→ legacy 管线的假存在全部回来，用例 1 转红。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.inventory._support import CHECKLIST, check_checklist_graded, engine
from zt.inventory.rules import ClassifyInput

CASES = json.loads((Path(__file__).parent / "fixtures" / "audit_gt_cases.json")
                   .read_text(encoding="utf-8"))["cases"]

# reclassified 管线下 gt=present 的已备条数下限（棘轮：只许升）。2026-09-30 首次入仓实测 3/4。
RECALL_FLOOR = 3

# 夹具的清单项 id 都是通用 ALL 那一套
SEED = {it["item_id"]: it for it in CHECKLIST.items if it["consulting_type"] == "ALL"}
assert len(SEED) >= 19, f"通用清单只读到 {len(SEED)} 条"


def _tags(case: dict, pipeline: str) -> list[dict]:
    out = []
    for i, f in enumerate(case["files"]):
        dirs = f["dirs"]
        ancestors = list(reversed(dirs[1:]))          # 剔容器根（TagInputFilter 口径）
        base = {"file_id": f"{i}", "file_name": f["file_name"], "doc_key": f"{i}",
                "display_path": "/" + "/".join([*dirs, f["file_name"]]), "ancestors": ancestors}
        if pipeline == "legacy":
            out.append({**base, **f["legacy"]})
        else:
            ext = f["file_name"].rsplit(".", 1)[-1]
            o = engine.classify_one(ClassifyInput(
                file_id=base["file_id"], file_name=f["file_name"], file_ext=ext,
                has_text_layer=not f.get("scanned", False), ancestors=ancestors))
            out.append({**base, "doc_category": o.doc_category, "cost_stage": o.cost_stage,
                        "source": "rule", "evidence": o.evidence, "needs_manual": o.needs_manual})
    return out


def _run(case: dict, pipeline: str) -> dict:
    return check_checklist_graded(_tags(case, pipeline), list(SEED.values()))


def _covered_ids(g: dict) -> set[str]:
    return {c["item_id"] for c in g["covered"]}


@pytest.mark.parametrize("pipeline", ["legacy", "reclassified"])
@pytest.mark.parametrize("case", CASES, ids=[c["name"][:12] for c in CASES])
def test_gt_missing_items_are_never_covered(case, pipeline):
    g = _run(case, pipeline)
    false_present = [SEED[i]["item_name"] for i, v in case["gt"].items() if v == "missing" and i in _covered_ids(g)]
    assert not false_present, f"{case['name']}（{pipeline}）：人工判缺失，却被判成已备：{false_present}"


def test_gt_present_recall_ratchet():
    hit = total = 0
    for case in CASES:
        covered = _covered_ids(_run(case, "reclassified"))
        for i, v in case["gt"].items():
            if v == "present":
                total += 1
                hit += i in covered
    assert total >= 4, f"gt=present 只有 {total} 项 —— 夹具被删了？"
    assert hit >= RECALL_FLOOR, f"召回 {hit}/{total} 低于棘轮 {RECALL_FLOOR}"


def test_fixture_reaches_the_failure_shape():
    """§5.2 自检：legacy 管线里这些文件确实**命中**了 gt=missing 的清单项（在 pending 里）——
    不是因为类目对不上才「没被判成已备」。命中都没有的话，用例 1 恒绿、测不到定级。"""
    reached = 0
    for case in CASES:
        g = _run(case, "legacy")
        pend = {p["item_id"] for p in g["pending"]}
        reached += sum(1 for i, v in case["gt"].items() if v == "missing" and i in pend)
    assert reached >= 5, f"legacy 管线只有 {reached} 个 gt=missing 项被弱证据命中 —— 夹具够不到失败分支"
