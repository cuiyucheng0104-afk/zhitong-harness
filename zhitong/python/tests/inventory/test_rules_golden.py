"""迁移自旧仓 engine-service/tests/test_classify_golden_ws13.py；夹具逐字拷贝。

WS13-P01 金标闸：「不许自信地错」（issue #720）。

贯穿 WS13 的验收不变量：任何一条标签，要么判对，要么明示待复核。所以本闸只守两条：
  1. **自信错标 = 0**：清单口径类目（category_vocab.canonical 折算后）与期望不同、
     且 needs_manual=False 的行数为 0；
  2. **完全正确的行数不低于入仓基线**（棘轮，只许升不许降）。

夹具 tests/fixtures/ws13_classify_golden.json（脱敏，D7）来自 spec WS13 各问题的复现表与
QA 缺陷索引里写明的判例；每行另带 `baseline_d25a4637` —— 修改前的旧引擎在同一输入上的实际
输出。下面有一条断言专门钉住「旧引擎在这份夹具上确实自信错标」，证明夹具够得到失败分支
（CLAUDE.md §5.2），而不是一份新旧都绿的摆设。

⚠ 这不是 spec 原定的 QA 金标（ground_truth_sample60.json / census_verdicts.json 本机不可得），
规模也小得多（47 行 vs 约 186 行）。它守的是底线，不是准确率。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.inventory._support import canonical, engine
from zt.inventory.rules import ClassifyInput

FIXTURE = Path(__file__).parent / "fixtures" / "classify_golden.json"

# 入仓基线：本 PR 合入时新引擎在夹具上的「完全正确」行数。规则改好了就往上调，**不许往下调**。
RATCHET_FULL_CORRECT = 44



@pytest.fixture(scope="module")
def rows():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rows = data["rows"]
    assert len(rows) >= 40, f"金标夹具只有 {len(rows)} 行 —— 读错文件或被截断（铁律 8）"
    return rows


def _classify(row):
    return engine.classify_one(ClassifyInput(
        "g", row["file_name"], row["file_ext"], ancestors=list(row["ancestors"]), has_text_layer=True))


def _confident_wrong(row, cat, needs_manual) -> bool:
    return canonical(cat) != canonical(row["expect"]["doc_category"]) and not needs_manual


def _fully_correct(row, cat, stage) -> bool:
    exp = row["expect"]
    if canonical(cat) != canonical(exp["doc_category"]):
        return False
    return "cost_stage" not in exp or stage == exp["cost_stage"]


def test_fixture_reaches_the_failure_shape(rows):
    """夹具必须含「旧引擎自信错标」的形状，否则下一条闸对被修的缺陷没有牙齿。"""
    old_wrong = [r["file_name"] for r in rows
                 if _confident_wrong(r, r["baseline_d25a4637"]["doc_category"],
                                     r["baseline_d25a4637"]["needs_manual"])]
    assert len(old_wrong) >= 20, f"旧引擎在夹具上只有 {len(old_wrong)} 行自信错标：{old_wrong}"


def test_no_confident_mislabel(rows):
    bad = []
    for r in rows:
        o = _classify(r)
        if _confident_wrong(r, o.doc_category, o.needs_manual):
            bad.append(f"{r['file_name']}（祖先 {r['ancestors']}）→ {o.doc_category}/"
                       f"needs_manual={o.needs_manual}，期望 {r['expect']['doc_category']}；{o.reason}")
    assert not bad, "自信错标（类目错且不待复核）：\n  " + "\n  ".join(bad)


def test_fully_correct_ratchet(rows):
    correct = sum(1 for r in rows if _fully_correct(r, *(lambda o: (o.doc_category, o.cost_stage))(_classify(r))))
    old = sum(1 for r in rows if _fully_correct(
        r, r["baseline_d25a4637"]["doc_category"], r["baseline_d25a4637"]["cost_stage"]))
    assert correct >= RATCHET_FULL_CORRECT, (
        f"完全正确 {correct}/{len(rows)} 低于入仓基线 {RATCHET_FULL_CORRECT}（旧引擎 {old}）")
    assert correct > old, f"新引擎完全正确 {correct} 不高于旧引擎 {old}"
