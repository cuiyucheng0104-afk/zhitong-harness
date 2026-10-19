# 来源：engine-service/tests/test_tk_anomaly_uid_identity.py（zhitong-cost-ai@991ff5cd）
"""D-H6c 跨轮次身份：anomaly_id 必须与 detect() 的折叠键同粒度。

修的现场（第 1 轮对抗复核，两条链路都读码闭合了）：

  引擎侧  tk_engine._mk 曾用 uuid5(project_id|major|sheet|item_code|**rule**) 做指纹，
          而 detect() 末尾只按 (project_id,major,sheet,item_code) 折叠，
          **每条清单行只留置信度最高的那一条规则**。
  Java 侧 TkAnomalyUpsertPlanner 按 anomaly_uid 命中已有行才刷新；没命中就插新行，
          而清扫只删 pending —— 已复核的行一律保留（那是审计留痕，本身没错）。

  两条合起来：两轮之间「获胜规则」一变 → 指纹变 → upsert 认不出 → 插一条新 pending，
  旧的 confirmed 行留在原地。页面上并排「已确认异常」+「待复核」，
  正是 D-H6c 要消灭的那一幕，而且逐轮累积。

「获胜规则会变」不是假想：本仓 golden 里就摆着物证（见 test_golden_v1_v2_same_locator_same_uid）,
同一份送审文件，只是多喂了一份基准，两条清单行的获胜规则就从 big_amount
翻成 price_over_baseline / new_item。真实场景更频繁 —— 数据每期都在变
（进度款/结算按期报审），下一步 D-H6a（清单级基准）会批量翻转获胜规则。

⚠ 本文件是那条不变量的看门人：**指纹字段集 ≡ 折叠键字段集**。
  哪天有人往指纹里加字段（规则名、置信度、金额、期次……），
  只要那字段跨轮次会变，就会把造价师的复核结论从这条异常上甩掉，本文件转红。

WS08-08（issue #760）改写身份口径：(project_id, file_key, sheet, row)，file_key 取 file_id、
没有时取文件名，uid = uuid5("tk2|" + 身份键)。旧口径 project|major|sheet|item_code 让两份不同合同的
同码清单行共用一个 uid —— 复核结论会串到别的期次。「规则翻转、身份不变」两条用例原样保留。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from zt.tk import engine as tk_engine
from zt.tk.engine import _NS, _UID_PREFIX, _key

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"


@pytest.fixture(scope="module")
def cfg() -> dict:
    return tk_engine.load_rules()


def _row(**over) -> dict:
    r = {
        "project_id": "P001",
        "major": "混凝土及钢筋混凝土",
        "sheet": "分部分项工程量清单计价表",
        "item_code": "010501001001",
        "item_name": "现浇混凝土基础",
        "item_feature": "",
        "unit": "m3",
        "submit_qty": 100,
        "submit_price": 500,
        "submit_amount": 50000,
        "source_file": "第1期报审.xlsx",
        "file_id": "F-1",
        "row": 7,
    }
    r.update(over)
    return r


def _baseline(**over) -> dict:
    """合同基准一行。键名照 tk_engine.rule_price_over_baseline 读的那套（base_qty/base_price/…）。"""
    b = {
        "project_id": "P001",
        "item_code": "010501001001",
        "item_name": "现浇混凝土基础",
        "item_feature": "",
        "unit": "m3",
        "base_qty": 100,
        "base_price": 400.0,
        "base_amount": 40000.0,
        "source": "合同清单",
    }
    b.update(over)
    return b


def _only(hits: list[dict]) -> dict:
    assert len(hits) == 1, f"本用例假设只命中一条（折叠后），实际 {len(hits)} 条：{[h['subtype'] for h in hits]}"
    return hits[0]


# ---------------------------------------------------------------------------
# ① 直击缺陷：同一条清单行，两轮之间获胜规则翻转，身份必须不变
# ---------------------------------------------------------------------------
def test_uid_survives_winning_rule_flip(cfg):
    """只改数据不改身份：轮1 自洽不符（self_check, conf .55）→ 轮2 大额（big_amount, conf .3）。

    撤掉修复（把 rule 塞回指纹）时，这条立刻转红 —— 两个 uuid 会完全不同。
    """
    # 轮 1：amount ≠ qty×price → self_check 赢（置信度更高）
    r1 = _only(tk_engine.detect([_row(submit_amount=80000)], cfg))
    # 轮 2：amount = qty×price，自洽了 → 只剩 big_amount
    r2 = _only(tk_engine.detect([_row(submit_amount=50000)], cfg))

    assert r1["subtype"] != r2["subtype"], (
        "夹具失效：两轮必须命中不同规则，否则这条用例根本没打到「规则翻转」这个点上。"
        f" 实际 {r1['subtype']} / {r2['subtype']}"
    )
    assert r1["anomaly_id"] == r2["anomaly_id"], (
        f"同一条清单行跨轮次换了身份：{r1['subtype']}→{r1['anomaly_id']} "
        f"vs {r2['subtype']}→{r2['anomaly_id']}。"
        " Java 的 upsert 会认不出 → 插一条新 pending，旧 confirmed 留在原地（D-H6c 那一幕）。"
    )


def test_uid_survives_baseline_arrival(cfg):
    """D-H6a 预演：同一份送审，先无基准、后有基准 → 获胜规则整体翻转，身份仍不许变。"""
    rows = [_row(submit_price=500, submit_amount=50000)]
    baselines = [_baseline()]
    before = _only(tk_engine.detect(rows, cfg))
    after = _only(tk_engine.detect(rows, cfg, baselines=baselines))

    assert before["subtype"] != after["subtype"], (
        f"夹具失效：喂基准前后必须换规则，实际都是 {before['subtype']}"
    )
    assert before["anomaly_id"] == after["anomaly_id"], (
        "基准到位（D-H6a）会让本轮所有复核结论失效 —— 这正是指纹带规则名的代价。"
        f" {before['subtype']}→{before['anomaly_id']} vs {after['subtype']}→{after['anomaly_id']}"
    )


# ---------------------------------------------------------------------------
# ② 结构不变量：指纹字段集 ≡ 折叠键字段集
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("with_baseline", [False, True])
def test_uid_equals_uuid5_of_folding_key_only(cfg, with_baseline):
    """detect() 返回的每一条，anomaly_id 必须恰好 = uuid5(_NS, 折叠键)。

    折叠键 = 身份键 _key：(project_id, file_key, sheet, row)。
    这条把「指纹」与「折叠」焊在一起：谁改了任一边而没改另一边，这里就红。
    """
    rows = [
        _row(submit_amount=80000),
        _row(row=8, item_code="010601001001", item_name="钢筋工程", submit_price=6500, submit_amount=650000),
        _row(row=9, item_code="010101001001", item_name="平整场地", submit_qty=1, submit_price=99, submit_amount=99),
    ]
    baselines = [_baseline()] if with_baseline else None

    hits = tk_engine.detect(rows, cfg, baselines=baselines)
    assert hits, "夹具没检出任何异常，这条用例会空转"

    for h in hits:
        expect = str(uuid.uuid5(_NS, _UID_PREFIX + "|".join(_key(h))))
        assert h["anomaly_id"] == expect, (
            f"指纹与折叠键脱钩：subtype={h['subtype']} locator={_key(h)} "
            f"anomaly_id={h['anomaly_id']}，按折叠键算应为 {expect}"
        )

    # 折叠键唯一 ⇒ 一轮之内 uid 不会撞（Java 侧 droppedDuplicateInBatch 才不会被触发）
    uids = [h["anomaly_id"] for h in hits]
    assert len(set(uids)) == len(uids), f"同一轮出现重复 uid：{uids}"


def test_uid_still_separates_different_locators(cfg):
    """反向：不许把不同清单行折成同一个身份。身份四元组任一位变化 → uid 必须变。"""
    base = _only(tk_engine.detect([_row(submit_amount=80000)], cfg))
    variants = {
        "project_id": _row(submit_amount=80000, project_id="P002"),
        "file_id": _row(submit_amount=80000, file_id="F-2"),
        "sheet": _row(submit_amount=80000, sheet="措施项目清单计价表"),
        "row": _row(submit_amount=80000, row=8),
    }
    for field, row in variants.items():
        other = _only(tk_engine.detect([row], cfg))
        assert other["anomaly_id"] != base["anomaly_id"], (
            f"改了 {field} 之后 uid 竟然没变 —— 两条不同的清单行会互相顶掉复核结论"
        )


# ---------------------------------------------------------------------------
# ③ 物证：本仓 golden 里那对「同一行、不同获胜规则」
# ---------------------------------------------------------------------------
def test_golden_v1_v2_same_locator_same_uid():
    """tk_detect_v1（无基准）与 v2（同送审 + 基准）：同 locator 的行必须同 uid。

    修复前这两份金标里，010501001001 与 010601001001 各自有**两个不同的 uuid**
    （v1 是 big_amount，v2 分别翻成 price_over_baseline / new_item）——
    那就是缺陷本身留在仓里的物证。修复后两份金标的 uid 必须逐位相同。
    """
    v1 = json.loads((GOLDEN_DIR / "tk_detect_v1.json").read_text(encoding="utf-8"))
    v2 = json.loads((GOLDEN_DIR / "tk_detect_v2_with_baseline.json").read_text(encoding="utf-8"))

    def by_locator(doc):
        return {
            (a["project_id"], a["file_id"], a["sheet"], a["row"]): a
            for a in doc["anomalies"]
        }

    m1, m2 = by_locator(v1), by_locator(v2)
    shared = sorted(set(m1) & set(m2))
    assert shared, "两份金标没有共同 locator，这条用例空转"

    flipped = [loc for loc in shared if m1[loc]["type"] != m2[loc]["type"]]
    assert flipped, (
        "两份金标里没有任何一条清单行的获胜规则发生翻转 —— "
        "夹具已失去意义（本用例靠这个翻转才证明得了东西）"
    )

    for loc in shared:
        assert m1[loc]["anomaly_id"] == m2[loc]["anomaly_id"], (
            f"金标里同一条清单行 {loc} 跨场景换了身份："
            f"{m1[loc]['type']}→{m1[loc]['anomaly_id']} vs "
            f"{m2[loc]['type']}→{m2[loc]['anomaly_id']}"
        )
