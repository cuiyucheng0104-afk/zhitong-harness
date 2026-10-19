# 来源：engine-service/tests/test_tk_new_item_negative.py（zhitong-cost-ai@991ff5cd）
"""防回归：tk_engine.rule_new_item 的过线判定必须取绝对值（H6b 止血，2026-08-30）。

现场（spec《第二轮实测反馈-优化方案》D-H6b，本文件作者实读代码复核确认）：
`rule_new_item` 是 tk_engine 全部 8 条规则里**唯一**没对送审金额取绝对值的一条 ——

    duplicate            max(abs(a) for a in amounts) < cfg["min_amount"]   ✓
    zangu                abs(amt) >= cfg["min_amount"]                      ✓
    self_check           abs(amt) < cfg["min_amount"]                       ✓
    big_amount           abs(amt) >= line                                   ✓
    price_over_baseline  abs(_f(r["submit_amount"])) < cfg["min_amount"]    ✓
    qty_over_baseline    abs(_f(r["submit_amount"])) < cfg["min_amount"]    ✓
    missing_submit       （不比金额）                                        —
    new_item             amt < min_amount                                   ✗ ← 修的就是这条

后果：负数金额一律漏判。真实语料里负数是常态 —— 进度款/结算表的核减行、
红冲行、退场费冲回、上期多计本期扣回，金额列都是负的。一条 −800,000 的
"合同外新增冲回"在旧口径下 `-800000 < 5000` 恒成立 → continue，检不出来。
而 `_mk()` 里 `severity` 写的是 `abs(_f(...))`（涉及金额取绝对值），
过线判定不取绝对值与它自相矛盾：同一条数据，"够不够大"和"多大"两把尺子。

变异验证（撤掉修复该怎么转红）：把 tk_engine.rule_new_item 里的
`if abs(amt) < min_amount:` 改回 `if amt < min_amount:` →
`test_negative_amount_over_line_is_detected` 与
`test_new_item_line_is_symmetric_around_zero` 转红。

跑法: cd engine-service && ./.venv/bin/pytest tests/test_tk_new_item_negative.py -v
"""
from __future__ import annotations

from zt.tk import engine as tk_engine
from zt.tk.align import build_index

# 基准里只有 010101001001；送审行用别的编码 → align_row 必然判 NEW_ITEM
_BASELINE = [
    {
        "project_id": "P30003",
        "item_code": "010101001001",
        "item_name": "挖一般土方",
        "unit": "m3",
        "base_qty": 100,
        "base_price": 10,
        "base_amount": 1000,
        "source": "合同清单",
    }
]

_CFG = {"min_amount": 5000}
_ALIGN_CFG = {"fuzzy_feature_min": 0.0}


def _row(amount, code="010999999999", name="签证-土方外运增补") -> dict:
    return {
        "project_id": "P30003",
        "major": "土石方工程",
        "sheet": "分部分项",
        "source_file": "进度款2024年4月-土建.xlsx",
        "item_code": code,
        "item_name": name,
        "item_feature": "",
        "unit": "m3",
        "submit_qty": None,
        "submit_price": None,
        "submit_amount": amount,
    }


def _run(rows):
    return tk_engine.rule_new_item(rows, _CFG, 0.6, build_index(_BASELINE), _ALIGN_CFG)


def test_positive_amount_over_line_is_detected():
    """正数过线必须检出（原本就对，作为对照锚点，防止修复把正数打坏）。"""
    out = _run([_row(800000.0)])
    assert len(out) == 1
    assert out[0]["subtype"] == "new_item"
    assert out[0]["severity"] == 800000.0


def test_negative_amount_over_line_is_detected():
    """负数过线也必须检出 —— 这就是修复前漏判的那条（核减/红冲行）。"""
    out = _run([_row(-800000.0)])
    assert len(out) == 1, "−80 万的合同外新增冲回被漏判（rule_new_item 未对金额取绝对值）"
    assert out[0]["subtype"] == "new_item"
    # severity=涉及金额，_mk 里本就取绝对值
    assert out[0]["severity"] == 800000.0
    # reported_value 保留原始符号，不能被绝对值污染（复核人要看得到这是笔冲回）
    assert out[0]["reported_value"] == -800000.0


def test_new_item_line_is_symmetric_around_zero():
    """过线阈值必须关于 0 对称：±(min_amount+1) 都检出，±(min_amount-1) 都不检出。"""
    over = _run([_row(5001.0, code="010999999001"), _row(-5001.0, code="010999999002")])
    assert len(over) == 2, f"±5001 应各检出一条，实际 {len(over)} 条"

    under = _run([_row(4999.0, code="010999999003"), _row(-4999.0, code="010999999004")])
    assert under == [], f"±4999 未过线不应检出，实际 {len(under)} 条"


def test_zero_amount_never_detected():
    """0 元行不过线（min_amount>0 时）——边界不因取绝对值而反转。"""
    assert _run([_row(0.0)]) == []


def test_aligned_row_still_not_new_item_even_when_negative():
    """负数但能对上基准的行，仍然不是 new_item（取绝对值只放开金额闸，不放开对齐闸）。"""
    aligned = _row(-800000.0, code="010101001001", name="挖一般土方")
    assert _run([aligned]) == []
