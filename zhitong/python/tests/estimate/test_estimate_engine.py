# 来源：engine-service/tests/test_estimate_engine.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""概算模板固化 + 确定性求值器测试（spec I-2.1 / I-2.2）。

分层：
- 模板结构断言：9 sheet / 211 输入位 / 515 公式 / 8 类条数 / 三缺陷修正留痕；
- L2 回归金标：tests/fixtures/estimate_gsyz_v1_synthetic.json ——合成输入 +
  LibreOffice headless 独立重算交叉验证后固化的期望值（见
  scripts/crosscheck_estimate_libreoffice.py），入仓可 CI；
- 费率三档：1% / 5% / 8% 均可算，软区间外仅 warning（不设硬闸——用户裁决）；
- 求值语义：空输入不炸、文本透传、未知输入位 warning、非数值输入报错。

L1 验收金标（含真实数据，不入仓）另见 test_estimate_golden_replay.py（环境变量门控）。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from zt.estimate import engine as ee

FIXTURE = Path(__file__).parent / "fixtures" / "estimate_gsyz_v1_synthetic.json"


@pytest.fixture(scope="module")
def tpl() -> dict:
    return ee.load_template("gsyz_v1")


@pytest.fixture(scope="module")
def synthetic() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 模板结构
def test_template_shape(tpl):
    assert [s["name"] for s in tpl["sheets"]] == [
        "经济技术指标", "估概算总表", "1.建筑工程费", "2.安装工程费", "3.专项工程费",
        "4.室外及配套工程费", "5.工程建设其他费用", "1.1概算建筑项目清单", "2.1估概算安装项目清单",
    ]
    assert len(tpl["inputs"]) == 211
    assert len(tpl["formulas"]) == 515
    counts: dict[str, int] = {}
    for f in tpl["formulas"]:
        counts[f["class"]] = counts.get(f["class"], 0) + 1
    assert counts == tpl["formula_class_counts"] == {
        "sum_children": 30, "add_chain": 15, "cross_ref": 215, "unit_cost": 224,
        "ratio": 12, "difference": 1, "composite": 1, "rate": 1, "dispimg": 16,
    }


def test_template_metadata(tpl):
    by_name = {s["name"]: s for s in tpl["sheets"]}
    assert by_name["1.建筑工程费"]["freeze"] == "A15"
    assert by_name["3.专项工程费"]["freeze"] == "A29"
    assert "A1:I1" in by_name["估概算总表"]["merges"]
    assert sum(len(s["merges"]) for s in tpl["sheets"]) == 64  # 脱敏验收记录的合并格总数
    # 实证事实#9：折叠隐藏态必须强制展开
    assert all(s["force_expand_outline"] for s in tpl["sheets"])
    hidden = [r for s in tpl["sheets"] for r in s["rows"] if r.get("outline", {}).get("hidden")]
    assert hidden, "模板应保留原表大纲隐藏态元数据"


def test_fix_f30(tpl):
    fx = {f["id"]: f for f in tpl["fixes"]}
    ch = fx["F30_wrong_ref"]["changes"][0]
    assert ch == {
        "cell": "估概算总表!F30",
        "before": "='3.专项工程费'!E35",
        "after": "='3.专项工程费'!E46",
    }
    f30 = next(f for f in tpl["formulas"] if f["cell"] == "估概算总表!F30")
    assert f30["formula"] == "='3.专项工程费'!E46" and f30.get("fixed")


def test_fix_sentinel_sum(tpl):
    fx = {f["id"]: f for f in tpl["fixes"]}
    changes = {c["cell"]: c for c in fx["sentinel_sum_inclusion"]["changes"]}
    assert len(changes) == 12
    # 总表死行 44 复活进小计
    assert changes["估概算总表!C34"]["after"] == "=SUM(C35:C44)"
    # 安装 6/6、室外 4/4、其他费复合公式内的 SUM 均扩围
    assert sum(1 for c in changes if c.startswith("2.安装工程费")) == 6
    assert sum(1 for c in changes if c.startswith("4.室外及配套工程费")) == 4
    assert changes["5.工程建设其他费用!C5"]["after"] == "=C6+C9+SUM(C14:C31)"
    # 1.建筑原本 6/6 已含哨兵行，不应出现在修正清单
    assert not any(c.startswith("1.建筑工程费") for c in changes)


def test_fix_seq_rebuild(tpl):
    fx = {f["id"]: f for f in tpl["fixes"]}
    changes = fx["seq_rebuild"]["changes"]
    as_map = {(c["sheet"], c["row"]): (c["before"], c["after"]) for c in changes}
    # 3.专项：3.1 节下错编的 3.3.x → 3.1.x（12 行）
    assert as_map[("3.专项工程费", 7)] == ("3.3.1", "3.1.1")
    assert sum(1 for (s, _r) in as_map if s == "3.专项工程费") == 12
    # 4.室外：表内序号 5.x → 4.x（根行归位）
    assert as_map[("4.室外及配套工程费", 5)] == ("5", "4")
    assert as_map[("4.室外及配套工程费", 6)] == ("5.1", "4.1")
    # 重号修复：1.建筑 1.2.2 出现两次；经济技术指标 3.1 出现两次
    assert as_map[("1.建筑工程费", 18)] == ("1.2.2", "1.2.3")
    assert as_map[("经济技术指标", 8)] == ("3.1", "3.2")
    # float 塌缩复原：清单表第 10 项 1.10 存成 1.1，重建为字符串 "1.10"
    assert as_map[("2.1估概算安装项目清单", 15)] == ("1.1", "1.10")
    # 序号一律字符串
    for s in tpl["sheets"]:
        for r in s["rows"]:
            if r["seq"] is not None:
                assert isinstance(r["seq"], str)


def test_seq_no_duplicates_within_sheet(tpl):
    for s in tpl["sheets"]:
        seqs = [r["seq"] for r in s["rows"] if r["seq"] is not None]
        assert len(seqs) == len(set(seqs)), f"{s['name']} 重建后仍有重号"


# ---------------------------------------------------------------- L2 回归金标
def test_synthetic_regression(synthetic):
    """引擎结果与「LibreOffice 独立重算一致」的固化期望逐格比对（499 格）。"""
    out = ee.run(synthetic["inputs"], rates=synthetic["rates"])
    assert len(synthetic["expected"]) == 499  # 515 - 16 DISPIMG
    bad = []
    for cell, want in synthetic["expected"].items():
        sheet, coord = cell.split("!", 1)
        got = out["sheets"][sheet].get(coord)
        if isinstance(want, str):
            ok = got == want
        else:
            ok = isinstance(got, (int, float)) and math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9)
        if not ok:
            bad.append((cell, want, got))
    assert not bad, f"{len(bad)} 格与 L2 金标不一致，前几例：{bad[:5]}"


def test_synthetic_covers_f30_fix(synthetic):
    """合成数据上 E35 != E46，F30 的期望值取 E46——修正被数值级覆盖（金标里两者
    巧合相等，L1 无法在数值层面区分对错，这里补上）。"""
    e35 = synthetic["inputs"]["3.专项工程费!E35"]
    e46 = synthetic["inputs"]["3.专项工程费!E46"]
    assert e35 != e46
    assert synthetic["expected"]["估概算总表!F30"] == e46


# ---------------------------------------------------------------- 费率三档
@pytest.mark.parametrize("rate,expect_warn", [(0.01, True), (0.05, False), (0.08, False)])
def test_reserve_rate_tiers(synthetic, rate, expect_warn):
    out = ee.run(synthetic["inputs"], rates={"reserve_rate": rate})
    zb = out["sheets"]["估概算总表"]
    c5, c45, c46 = zb["C5"], zb["C45"], zb["C46"]
    assert math.isclose(c46, (c5 + c45) * rate, rel_tol=1e-9)
    warned = [w for w in out["warnings"] if w["code"] == "rate_out_of_range"]
    assert bool(warned) == expect_warn, "软区间校验只出 warning：1% 必须能算，5%/8% 不告警"
    # 预备费变化要传导进静态/动态总投资
    assert math.isclose(zb["C47"], c5 + c45 + c46, rel_tol=1e-9)


def test_reserve_rate_not_hardcoded(synthetic):
    """同一输入下三档结果必须不同——费率没有被写死。"""
    c46 = {
        r: ee.run(synthetic["inputs"], rates={"reserve_rate": r})["sheets"]["估概算总表"]["C46"]
        for r in (0.01, 0.05, 0.08)
    }
    assert c46[0.01] < c46[0.05] < c46[0.08]
    assert math.isclose(c46[0.08] / c46[0.01], 8.0, rel_tol=1e-9)


# ---------------------------------------------------------------- #130 未知费率键与生效值
def test_unknown_rate_key_warns_and_falls_back_to_default(synthetic):
    """键名拼错（驼峰 reserveRate）不再静默：出 unknown_rate warning、费率按模板
    默认 5% 计、rates_used 落真实生效值而非入参回显（#130 审计失真的三个修复点）。"""
    out = ee.run(synthetic["inputs"], rates={"reserveRate": 0.01})
    unknown = [w for w in out["warnings"] if w["code"] == "unknown_rate"]
    assert unknown and unknown[0]["cell"] == "reserveRate"
    zb = out["sheets"]["估概算总表"]
    assert math.isclose(zb["C46"], (zb["C5"] + zb["C45"]) * 0.05, rel_tol=1e-9), \
        "未知键回落默认 5% 是既定行为（本测试不改它，只要求不再静默）"
    assert out["rates_used"] == {"reserve_rate": 0.05}, "rates_used 必须是生效值，不是入参"


def test_rates_used_reports_effective_value(synthetic):
    """键名正确时 rates_used 回本次生效值，且不误报 unknown_rate。"""
    out = ee.run(synthetic["inputs"], rates={"reserve_rate": 0.01})
    assert out["rates_used"] == {"reserve_rate": 0.01}
    assert not [w for w in out["warnings"] if w["code"] == "unknown_rate"]


def test_rates_used_present_without_rates(synthetic):
    """不传 rates 也要回 rates_used（全默认值）——审计口径恒有值可落。"""
    out = ee.run(synthetic["inputs"])
    assert out["rates_used"] == {"reserve_rate": 0.05}


# ---------------------------------------------------- 费率字面量不许写成科学计数法（O-15）
@pytest.mark.parametrize("rate", [1e-5, 1.2345e-5, 1e-11, 0.0001, 0.0])
def test_tiny_reserve_rate_does_not_crash_the_parser(synthetic, rate):
    """铁律 7：预备费率不设硬闸。而崩溃是最硬的闸。

    原写法 `f"{rate:.10g}"` 在 rate < 1e-4 时吐 `1e-05`，拼成
    `=(C5+C45)*1e-05` 后分词器不认 `e`，整个 compute 被打成 422。
    造价员填 0.001%（阶段性小额预备费，合法输入）就崩。
    """
    out = ee.run(synthetic["inputs"], rates={"reserve_rate": rate})
    zb = out["sheets"]["估概算总表"]
    assert math.isclose(zb["C46"], (zb["C5"] + zb["C45"]) * rate, rel_tol=1e-9, abs_tol=1e-12)


def test_rate_literal_never_uses_exponent_notation():
    assert ee.decimal_literal(1e-5) == "0.00001"
    assert ee.decimal_literal(1e-11) == "0.00000000001"
    assert ee.decimal_literal(0.05) == "0.05"
    assert ee.decimal_literal(1234567890.0) == "1234567890"
    for x in (1e-5, 1e-11, 1.2345e-5, 0.05, 1e12, -1e-5):
        assert "e" not in ee.decimal_literal(x).lower(), x


def test_tokenizer_also_tolerates_exponent_form():
    """两头都堵：万一别处再拼出指数形式，也不该炸成 422。"""
    assert ee._Parser("=1e-05*2", "X").parse() == ("mul", ("num", 1e-05), ("num", 2.0))
    assert ee._Parser("=1.5E+3+1", "X").parse() == ("add", ("num", 1500.0), ("num", 1.0))


def test_one_percent_still_passes(synthetic):
    """铁律 7 的正面守卫：1% 出 warning，但必须算得出来。"""
    out = ee.run(synthetic["inputs"], rates={"reserve_rate": 0.01})
    assert out["sheets"]["估概算总表"]["C46"] > 0
    assert [w["code"] for w in out["warnings"] if w["code"] == "rate_out_of_range"]


# ---------------------------------------------------------------- 求值语义
def test_empty_inputs_run(tpl):
    """211 输入全缺省按 0 计：不炸；占比/单方指标产生除 0 → None + warning。"""
    out = ee.run({})
    zb = out["sheets"]["估概算总表"]
    assert zb["C5"] == 0.0 and zb["C47"] == 0.0
    assert zb["D5"] is None  # C5/C50 = 0/0
    assert any(w["code"] == "div_by_zero" for w in out["warnings"])


def test_text_passthrough(synthetic):
    out = ee.run(synthetic["inputs"])
    zb = out["sheets"]["估概算总表"]
    assert zb["B25"] == "设备专项工程"
    assert zb["B35"] == "室外园林工程"


def test_template_fix_warning_surfaced(synthetic):
    out = ee.run(synthetic["inputs"])
    fixes = [w for w in out["warnings"] if w["code"] == "template_fix"]
    assert any(w["cell"] == "估概算总表!F30" for w in fixes)


def test_unknown_input_warns_and_ignored(synthetic):
    out = ee.run({**synthetic["inputs"], "估概算总表!C5": 1.0})  # C5 是公式位，不是输入位
    assert any(w["code"] == "unknown_input" and w["cell"] == "估概算总表!C5" for w in out["warnings"])
    # 公式位没有被覆写
    assert out["sheets"]["估概算总表"]["C5"] != 1.0


def test_non_numeric_input_raises():
    with pytest.raises(ee.EstimateTemplateError):
        ee.run({"经济技术指标!D4": "一万"})


def test_unknown_template_raises():
    with pytest.raises(ee.EstimateTemplateError):
        ee.run({}, template_code="不存在")


def test_indicators_shape(synthetic):
    out = ee.run(synthetic["inputs"])
    ind = {i["label"]: i for i in out["indicators"]}
    assert len(out["indicators"]) == 17  # 经济技术指标 数据行数
    assert ind["总建筑面积"]["unit"] == "㎡"
    assert math.isclose(
        ind["总建筑面积"]["value"],
        ind["地下总建筑面积"]["value"] + ind["地上总建筑面积"]["value"],
        rel_tol=1e-9,
    )
