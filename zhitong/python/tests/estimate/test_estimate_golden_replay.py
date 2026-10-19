# 来源：engine-service/tests/test_estimate_golden_replay.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""L1 验收金标回放（spec I-2.1 验收：515 条公式结果逐格一致）。

金标《房屋建筑工程概算指引.xlsx》含客户真实项目金额，**不入仓**——路径经环境变量
`TG_GOLDEN_XLSX` 注入，本地/专用环境跑，缺失时整文件 skip（CI 常态即 skip，
CI 的公式接线回归靠 test_estimate_engine.py 的 L2 合成金标）。

比对口径（515 条）：
- 489 条数值公式：引擎结果 vs 金标缓存值，rel_tol/abs_tol 1e-9；
- 10 条文本透传（总表 B25~B33、B35）：字符串全等；
- 16 条 DISPIMG（WPS 私有图片函数）：不参与求值，断言缓存形态即“=DISPIMG(...)”字符串；
- 估概算总表!F30 特殊口径：模板已修正错引 E35→E46，故与金标缓存比对的期望值取
  '3.专项工程费'!E46 的值。本份金标中 E35 与 E46 数值恰好相等（这正是原缺陷肉眼
  不可见的原因），因此该格与缓存值也一致；若未来换一份 E35≠E46 的金标，
  该口径依旧正确，而“与缓存值直接比对”会预期地对不上——那是修正的正确行为。
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from zt.estimate import engine as ee

_ENV = "TG_GOLDEN_XLSX"

GOLDEN = os.environ.get(_ENV, "")
pytestmark = pytest.mark.skipif(
    not GOLDEN or not Path(GOLDEN).is_file(),
    reason=f"未设 {_ENV} 或文件不存在——L1 金标回放仅本地执行（金标含真实数据不入仓）",
)

# 哨兵行（B 列「……」）的 C 格坐标：SUM 扩围值中立的前提是金标里这些格为空
_SENTINEL_C = {
    "估概算总表": [44],
    "1.建筑工程费": [14, 23, 29, 35, 41, 46],
    "2.安装工程费": [13, 21, 30, 39, 48, 55],
    "4.室外及配套工程费": [9, 14, 20, 26, 32],
    "5.工程建设其他费用": [31],
}


@pytest.fixture(scope="module")
def golden():
    openpyxl = pytest.importorskip("openpyxl")
    return openpyxl.load_workbook(GOLDEN, data_only=True)


@pytest.fixture(scope="module")
def tpl():
    return ee.load_template("gsyz_v1")


@pytest.fixture(scope="module")
def replay(golden, tpl):
    inputs = {}
    for i in tpl["inputs"]:
        sheet, coord = i["cell"].split("!", 1)
        v = golden[sheet][coord].value
        assert isinstance(v, (int, float)), f"金标输入位非数值：{i['cell']}={v!r}"
        inputs[i["cell"]] = float(v)
    assert len(inputs) == 211
    return inputs, ee.run(inputs)  # 默认费率 5% —— 与原表写死值同口径


def test_golden_formulas_intact(golden, tpl):
    """金标与模板公式逐字符一致（脱敏未动公式）；13 个 fixed 格按**修正前**形态比对。

    改动理由（#131）：原实现对 `fixed` 格一律 `continue`，等于 13 个格子不比对——
    而它们恰恰是最需要证据的那 13 个。现在改成用 `fixes[].changes[].before`
    断言金标里的原始形态：金标是修正**前**的原表，所以它应当逐字符等于 before。
    F30 的单点特判随之并入通用路径（它的 before 就是 `='3.专项工程费'!E35`）。

    ⚠ 本文件整体受 `TG_GOLDEN_XLSX` 门控，**CI 里恒 skip**。所以这条改动的价值
    只在「将来接上金标的那一次」兑现，不构成日常防线。三处修正的日常机器证据
    在 `test_estimate_template_fixes.py`（读入仓脱敏种子，CI 无条件跑）。
    """
    import openpyxl

    before_by_cell = {
        c["cell"]: c["before"]
        for fx in tpl["fixes"]
        for c in fx.get("changes", [])
        if "cell" in c
    }
    assert len(before_by_cell) == 13, (
        f"预期 13 个 fixed 格，清单里有 {len(before_by_cell)} 个 —— "
        "modules 变了就得重看这条断言，别让它悄悄少比几格")

    wb_f = openpyxl.load_workbook(GOLDEN)
    diffs = []
    for f in tpl["formulas"]:
        sheet, coord = f["cell"].split("!", 1)
        gf = wb_f[sheet][coord].value
        # fixed 格期望金标是修正**前**的形态；其余格期望与模板一致
        want = before_by_cell.get(f["cell"], f["formula"])
        if gf != want:
            diffs.append((f["cell"], gf, want))
    assert not diffs, f"模板与金标公式漂移：{diffs[:5]}"


def test_sentinel_cells_empty_in_golden(golden):
    bad = [
        f"{sheet}!C{r}"
        for sheet, rows in _SENTINEL_C.items()
        for r in rows
        if golden[sheet][f"C{r}"].value is not None
    ]
    assert not bad, f"哨兵格非空，SUM 扩围不再值中立：{bad}"


def test_replay_515_cells(golden, tpl, replay):
    _inputs, out = replay
    numeric = text = dispimg = 0
    mismatches = []
    e46 = golden["3.专项工程费"]["E46"].value
    for f in tpl["formulas"]:
        sheet, coord = f["cell"].split("!", 1)
        cached = golden[sheet][coord].value
        if f["class"] == "dispimg":
            assert isinstance(cached, str) and cached.startswith("=DISPIMG")
            dispimg += 1
            continue
        got = out["sheets"][sheet].get(coord)
        if f["cell"] == "估概算总表!F30":
            cached = e46  # 修正后口径：期望值 = 专项!E46（见模块 docstring）
        if isinstance(cached, str):
            if got == cached:
                text += 1
            else:
                mismatches.append((f["cell"], f["class"], cached, got))
            continue
        if isinstance(got, (int, float)) and math.isclose(
            got, float(cached), rel_tol=1e-9, abs_tol=1e-9
        ):
            numeric += 1
        else:
            mismatches.append((f["cell"], f["class"], cached, got))
    assert not mismatches, f"{len(mismatches)} 格回放不一致：{mismatches[:10]}"
    assert (numeric, text, dispimg) == (489, 10, 16)


def test_reserve_rate_5pct_reproduces_golden(golden, replay):
    """默认 5% 档必须复现金标预备费缓存值；1%/8% 档可算且线性传导。"""
    inputs, out5 = replay
    cached_c46 = float(golden["估概算总表"]["C46"].value)
    assert math.isclose(out5["sheets"]["估概算总表"]["C46"], cached_c46, rel_tol=1e-9)
    c46 = {
        r: ee.run(inputs, rates={"reserve_rate": r})["sheets"]["估概算总表"]["C46"]
        for r in (0.01, 0.08)
    }
    assert math.isclose(c46[0.01], cached_c46 / 5, rel_tol=1e-9)
    assert math.isclose(c46[0.08], cached_c46 * 8 / 5, rel_tol=1e-9)
