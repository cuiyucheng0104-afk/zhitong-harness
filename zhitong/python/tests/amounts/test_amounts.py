# 来源：engine-service/tests/test_amounts.py（zhitong-cost-ai@991ff5cd）
"""金额 / 费率 / 工期的保数值解析（整改 WS07 K3）。数值一律按 Decimal 断言，不碰浮点。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from zt.amounts.amounts import format_yuan, parse_amount, parse_days, parse_rate, same_amount


@pytest.mark.parametrize("raw,value,unit,precision,negative", [
    ("13,687,563元", "13687563", "元", "1", False),
    ("13，687，563元", "13687563", "元", "1", False),      # 全角千分位
    ("1368.7563万元", "13687563.0000", "万元", "1", False),
    ("1189.43万元", "11894300", "万元", "100", False),
    ("(1234.00)", "-1234.00", "", "0.01", True),            # 会计式负数
    ("（1,234.00）", "-1234.00", "", "0.01", True),
    ("-1234", "-1234", "", "1", True),
    ("－1234元", "-1234", "元", "1", True),                  # 全角负号
    ("¥1,418,635.50", "1418635.50", "", "0.01", False),
    ("1418635.49813269", "1418635.49813269", "", "0.00000001", False),
    ("壹仟零陆拾壹万叁仟捌佰玖拾叁元整", "10613893", "元", "1", False),
    ("叁元伍角陆分", "3.56", "元", "0.01", False),
    ("壹亿贰仟万元整", "120000000", "元", "1", False),
])
def test_parse_amount_accepts(raw, value, unit, precision, negative):
    a = parse_amount(raw)
    assert a is not None, raw
    assert a.value == Decimal(value), (raw, a)
    assert a.unit == unit
    assert a.precision_yuan == Decimal(precision), (raw, a.precision_yuan)
    assert a.negative is negative


@pytest.mark.parametrize("raw", [
    "招标控制价", "", "   ", None, "送审金额11894328元", "约7.3万元",
    "11894328元，审定10613893元", "1418635.50元（含税）", "第一期", True,
])
def test_parse_amount_rejects(raw):
    """不含数字、或整串不是**一个**金额 → None。夹着别的字就不猜，交给核验剔除（铁律 3）。"""
    assert parse_amount(raw) is None, raw


@pytest.mark.parametrize("a,b", [
    ("1418635", "1418635.49813269"),
    ("1189.43万元", "11894328"),
    ("109405.32592", "109405"),
    ("10613893", "壹仟零陆拾壹万叁仟捌佰玖拾叁元整"),
    ("1418635.50", "1418636"),
])
def test_same_amount_true(a, b):
    assert same_amount(a, b) and same_amount(b, a)


@pytest.mark.parametrize("a,b", [
    ("1418635", "1280435"),
    ("1234567.00", "-1234567.00"),       # 符号相反不是同一笔钱
    ("1189.43万元", "11894500"),          # 超出半个精度（50 元）
    ("招标控制价", "招标控制价"),         # 解析不了不算相等（铁律 8）
    ("330", "3.3"),
])
def test_same_amount_false(a, b):
    assert not same_amount(a, b)


def test_parse_rate_and_days():
    r = parse_rate("10.77%")
    assert r is not None and r.value == Decimal("10.77") and r.precision == Decimal("0.01")
    assert parse_rate("10.77％").value == Decimal("10.77")
    assert parse_rate("10.77") is None, "没有 % 的裸数不是费率"
    assert parse_rate("核减率") is None
    d = parse_days("180日历天")
    assert d is not None and d.value == Decimal(180) and d.unit == "天"
    assert parse_days("6个月").unit == "月"
    assert parse_days("合同工期180日历天，实际213天") is None


def test_format_yuan_rounds_to_fen():
    assert format_yuan(Decimal("1418635.498")) == "1418635.50"
    assert format_yuan(Decimal("11894327.9609491")) == "11894327.96"
    assert format_yuan(parse_amount("1189.43万元").value) == "11894300.00"


def test_number_index_ordinals_are_opt_in():
    """R3F-f（R3-008）：「第N」形式的数默认不进来源索引（report_guard、evidence_check、问答选出处的用法不变），
    只有问答数字回链打开 include_ordinals 时才收；「N 年 / N 页」这类原有的跳过不受影响。"""
    from zt.amounts.amounts import NumberIndex, find_numbers

    form = (Decimal(1716), Decimal(1), False)
    assert not NumberIndex(["源文件第 1716 行"]).contains(form)
    assert NumberIndex(["源文件第 1716 行"], include_ordinals=True).contains(form)
    assert NumberIndex(["源文件第1716行"], include_ordinals=True).contains(form)
    assert not NumberIndex(["2024年、12页"], include_ordinals=True).contains((Decimal(2024), Decimal(1), False))
    # 答案侧：find_numbers 的跳过规则不变
    assert [m.raw for m in find_numbers("源文件第 1715、1716 行")[1]] == ["1716"]
