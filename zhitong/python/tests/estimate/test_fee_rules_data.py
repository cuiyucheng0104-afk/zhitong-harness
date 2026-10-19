# 来源：engine-service/tests/test_fee_rules_data.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""费率规则数据的自证性校验（I-2.5）。

这批数据由 LLM 看图转录，330 个数字里错一个就会静默污染每一份概算。
本文件不做"再读一遍图"式的验证——那还是同一类风险；这里只做**不依赖图像、
纯靠数据内部关系就能自证**的检查：

1. 签字位不许被悄悄翻掉（上线闸）
2. 每个数值必须带溯源三件套，否则无法人工复查
3. 档位上界必须严格递增
4. **差额分档累进：速算扣除数法 == 逐档累加法**（任务书点名"务必做"的硬验证）
5. 差额累进在档界处必须连续 —— 这解释了为什么这 4 项不声明闭开性也是对的
6. 结果不连续的范式则必须显式声明闭开性
"""
import json
import math
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[2] / "zt/estimate/data/fee_rules_zj2018.json"


@pytest.fixture(scope="module")
def fee():
    return json.loads(DATA.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 上线闸
def test_signoff_markers_present(fee):
    """转录来源与签字状态必须在数据里明示。

    signoff_status 从 pending 翻成已签，必须是造价员真看过之后的人工动作；
    这条测试的作用是让"悄悄翻掉"变成一次显式的、评审可见的改动。
    """
    assert fee["transcribed_by"] == "llm"
    assert fee["requires_human_signoff"] is True
    assert fee["signoff_status"] in ("pending", "signed"), fee["signoff_status"]
    if fee["signoff_status"] == "signed":
        assert fee.get("signoff_by"), "标为已签必须写明签字人"
        assert fee.get("signoff_kind") in ("cost_engineer", "owner_release"), (
            "已签署必须写明**签的是谁**：cost_engineer（造价员对图逐值核毕）或 "
            f"owner_release（仓主默认放行）。当前 {fee.get('signoff_kind')!r}")


def test_owner_release_never_impersonates_a_cost_engineer(fee):
    """🔴 #159：仓主默认放行时，`signoff_by` 不许**看起来像**一个造价员签的字。

    为什么要有这条：`signoff_kind=owner_release` 解闸的效果与造价员签署一模一样
    （13 个输入位都出建议值）。差别只活在 `signoff_by` 这一个字符串里 ——
    如果哪天有人为了"好看"把它改成一个人名，审计链条就开始撒谎：将来出问题时，
    那个人从没看过这 393 个数字。

    判据是**正向**的（必须含「非造价员签署」字样），不是"不含某个黑名单人名" ——
    黑名单永远列不全，而正向判据只有故意删掉才会失效，删掉就是红。
    """
    if fee.get("signoff_kind") != "owner_release":
        return  # 造价员真签了字时本条不适用（那时 signoff_by 就该是人名）
    by = fee.get("signoff_by") or ""
    assert "非造价员签署" in by, (
        f"signoff_by={by!r} 没有如实声明这不是造价员签的字。"
        "owner_release 与 cost_engineer 解闸效果相同，这个字符串是唯一的区分点。")
    note = fee.get("signoff_note") or ""
    for must in ("不是造价员签署", "逐值核对"):
        assert must in note, f"signoff_note 没说清代价，缺「{must}」：{note[:120]}"
    unresolved = [c["id"] for c in fee["signoff_checklist"] if not c.get("resolution")]
    assert unresolved, (
        "5 处语义歧义全都填了 resolution，却仍标着 owner_release —— "
        "要么是造价员真核过了（那就把 signoff_kind 改成 cost_engineer），"
        "要么是有人替造价员填了结论。两种都必须显式处理。")


# ---------------------------------------------------------------- 签署闸（O-05）
def test_signoff_checklist_is_machine_readable_and_complete(fee):
    """5 处语义歧义必须在数据里机器可读，不能只活在 md 正文里。

    只写在 fee_rules_transcription.md 的清单，签署时没有任何东西强制逐条走过；
    落进数据后，「签了但 SC-2 还没解」在下一条测试里就是红的。
    """
    cl = fee["signoff_checklist"]
    assert [c["id"] for c in cl] == ["SC-1", "SC-2", "SC-3", "SC-4", "SC-5"]
    items = {i["item_id"] for i in fee["items"]}
    for c in cl:
        assert c["item_id"] in items, f"{c['id']} 指向不存在的条目 {c['item_id']}"
        assert c["source_image"], f"{c['id']} 缺原图指针，造价员无从对图"
        assert c["question"], f"{c['id']} 缺问题正文"


def test_signed_by_cost_engineer_requires_every_checklist_item_resolved(fee):
    """**造价员**签署是逐条的：signoff_kind=cost_engineer 而 5 条歧义还挂着 → 红。

    ⚠ 2026-09-10 之后这条只约束 `cost_engineer` 这一种签署。仓主默认放行
    （`owner_release`，issue #159）**明确不声称**这 5 条已对图解决 ——
    恰恰相反，`test_owner_release_never_impersonates_a_cost_engineer` 要求它们
    保持未解决，并要求 signoff_by/signoff_note 如实说明。
    把两种签署混在一条断言里，等于逼着放行的人去伪造 resolution。
    """
    if fee.get("signoff_kind") != "cost_engineer":
        # 不 skip：跳过会让「造价员签署的形状要求」在跳过棘轮里消失。
        # 这里做的是**形状校验**——数据没到那个态时，校验 checklist 结构本身。
        cl = fee["signoff_checklist"]
        assert all(("resolution" in c and "resolved_by" in c) for c in cl), \
            "checklist 缺 resolution/resolved_by 位，造价员签署时无处落笔"
        return
    assert fee.get("signoff_by"), "标为已签必须写明签字人"
    assert fee.get("signoff_at"), "标为已签必须写明签署时间"
    unresolved = [c["id"] for c in fee["signoff_checklist"] if not c.get("resolution")]
    assert not unresolved, f"这些语义歧义未逐条对图核毕就签了字：{unresolved}"


def test_unsigned_ruleset_yields_no_amount_at_all(unsigned_ruleset):
    """**闸的本体**：未签署时 `suggest_all` 的每一条 suggested / range 都必须是 None。

    只出一条 fee_rules_unsigned 告警**不算通过** —— 告警拦不住前端预填。铁律 2：
    未经造价员签署的 LLM 转录费率不得驱动金额。

    同时验证扣留是「只扣金额面」：16 条齐全、落点/依据/来源照出，
    且金额不会从别的口子漏出去（basis.closure_alternative.suggested、
    fee_band_closure_unconfirmed 的告警正文都扫过）。

    ⚠ 夹具说明（#159）：仓里的数据自 2026-09-10 起是 `signed`（仓主默认放行）。
    这条闸测**不再依赖仓里数据恰好是 pending** —— `unsigned_ruleset` 夹具把
    signoff 字段强制打回 pending（见 conftest.py）。此前它写的是
    `if fr.is_signed(): pytest.skip(...)`，那样一放行就整条静默失效，
    用例名还挂着「未签署时不出金额」而夹具永远到不了那个分支（§5.2）。
    """
    fr = unsigned_ruleset

    bases = {"工程费用": 12000.0, "中标金额": 6000.0, "建安工程造价": 9000.0,
             "总建筑面积": 12.0, "建筑面积": 40000.0, "受电容量": 2000.0,
             "专利计费基数": 3000.0}
    r = fr.suggest_all(bases, {"region": "urban", "building_use": "residential"})

    assert len(r["items"]) == 16, "扣留金额不等于少给条目：16 条必须齐全"
    for s in r["items"]:
        assert s["suggested"] is None, f"{s['item_id']} 未签署却出了金额 {s['suggested']}"
        assert s["range"] == [None, None], f"{s['item_id']} 未签署却出了区间 {s['range']}"
        assert s["unavailable_reason"], f"{s['item_id']} 扣留了却没说原因"
        alt = (s["basis"] or {}).get("closure_alternative")
        if isinstance(alt, dict):
            assert alt["suggested"] is None, f"{s['item_id']} 金额从 basis 漏出去了"

    codes = {w["code"] for w in r["warnings"]}
    assert "fee_rules_unsigned" in codes
    assert "fee_suggestion_withheld" in codes, "被扣留的条目必须逐条说明为什么没有值"

    # 告警正文不得夹带被扣留的金额：闭开性告警原本会写「按 X 算得 nnn 万元」
    for w in r["warnings"]:
        if w["code"] == "fee_band_closure_unconfirmed":
            assert "万元" not in w["message"], f"扣留的金额从告警正文漏出去了：{w['message']}"


def test_ungated_path_still_computes_so_the_gate_is_provably_a_gate():
    """闸必须是「算得出但不给」，不是「本来就算不出」。

    没有这条，上一条测试在求值器整体坏掉时也会全绿 —— 那是误导性成功。
    """
    from zt.estimate import fee_rules as fr

    raw = fr._suggest_all_ungated({"工程费用": 12000.0},
                                  {"region": "urban", "project_nature": "production"})
    got = [s["item_id"] for s in raw["items"] if s["suggested"] is not None]
    assert len(got) >= 8, f"未过闸时也只有 {len(got)} 条出数，求值器本身有问题：{got}"


def _rate_nodes(obj, path=""):
    """递归找出所有"带 value 的数值节点"。"""
    if isinstance(obj, dict):
        if "value" in obj and isinstance(obj["value"], (int, float)):
            yield path, obj
        for k, v in obj.items():
            yield from _rate_nodes(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _rate_nodes(v, f"{path}[{i}]")


def test_every_numeric_value_carries_provenance(fee):
    """每个转录出来的数值都要能查回原图的具体格子。

    造价员签字时必须能定位「这个数字出自哪张图、哪一格、原样写的什么」。
    `source_image` 允许从条目层继承（矩阵型条目就是这么组织的：图在条目上，
    格子坐标在每个单元格上），但 `source_cell` 与 `raw_text` 必须逐值写明。
    """
    bad = []
    for item in fee["items"]:
        has_item_image = bool(item.get("source_image"))
        for path, node in _rate_nodes(item):
            if not (node.get("source_image") or has_item_image):
                bad.append(f"{item['fee_name']}{path} 无 source_image（条目层也没有）")
            for key in ("source_cell", "raw_text"):
                if not node.get(key):
                    bad.append(f"{item['fee_name']}{path} 缺 {key}")
    assert not bad, f"{len(bad)} 处数值溯源不全：{bad[:8]}"


# ---------------------------------------------------------------- 档位结构
def _uppers_of(item):
    if "bands" in item:
        return [b.get("upper") for b in item["bands"]]
    if "band_uppers" in item:
        return list(item["band_uppers"])
    return None


def test_band_uppers_strictly_increasing(fee):
    """档位上界必须严格递增，且只有最后一档可以开口（None）。"""
    for item in fee["items"]:
        ups = _uppers_of(item)
        if not ups:
            continue
        finite = [u for u in ups if u is not None]
        assert finite == sorted(set(finite)), f"{item['fee_name']} 档位上界非严格递增：{ups}"
        nones = [i for i, u in enumerate(ups) if u is None]
        assert nones in ([], [len(ups) - 1]), f"{item['fee_name']} 开口档不在末位：{ups}"


def test_column_rate_counts_match_bands(fee):
    """多列费率表：每一列的费率个数必须与档位数一致，少一个就是转录漏档。"""
    for item in fee["items"]:
        ups = item.get("band_uppers")
        cols = item.get("columns")
        if not ups or not isinstance(cols, dict):
            continue
        for name, col in cols.items():
            rates = col.get("rates_permille") or col.get("rates_percent") or col.get("rates")
            assert rates is not None, f"{item['fee_name']}/{name} 无费率数组"
            assert len(rates) == len(ups), (
                f"{item['fee_name']}/{name} 费率 {len(rates)} 个 != 档位 {len(ups)} 个（疑似转录漏档）"
            )


# ---------------------------------------------------------------- 速算扣除数
def _tiered(x, uppers, rates):
    """逐档累加法：每档只对落在本档区间内的部分计费。"""
    total, lower = 0.0, 0.0
    for up, r in zip(uppers, rates):
        if up is None or x <= up:
            return total + (x - lower) * r
        total += (up - lower) * r
        lower = up
    return total


def _quick_deductions(uppers, rates):
    """QD_k = b_{k-1}*r_k - Σ_{i<k}(b_i - b_{i-1})*r_i"""
    qds, acc, lower = [], 0.0, 0.0
    for up, r in zip(uppers, rates):
        qds.append(lower * r - acc)
        if up is not None:
            acc += (up - lower) * r
            lower = up
    return qds


def _by_quick_deduction(x, uppers, rates, qds):
    """速算扣除数法：x * 所在档费率 - 该档速算扣除数。"""
    for up, r, qd in zip(uppers, rates, qds):
        if up is None or x <= up:
            return x * r - qd
    raise AssertionError("落不进任何档")


def _bands_of(node):
    """从一个节点取 (uppers, rates)——认得出两种写法，认不出返回 None。"""
    if node.get("bands"):
        return ([b.get("upper") for b in node["bands"]],
                [b["rate"]["value"] for b in node["bands"]])
    ups = node.get("band_uppers")
    if ups:
        rates = node.get("rates_permille") or node.get("rates_percent") or node.get("rates")
        if rates:
            return (list(ups), list(rates))
    return None


def _progressive_series(fee):
    """产出 (名称, 档位上界, 费率数组)。

    三种结构都要认：条目级 bands、条目级 band_uppers + 列级 rates_*、
    以及**列级各自带 bands**（工程招标代理费就是这种，band_uppers 为 None）。
    第三种我第一版漏了，导致该条目整个没进校验而断言仍绿——补上。
    """
    for item in fee["items"]:
        if item.get("paradigm") != "progressive_difference":
            continue
        got = _bands_of(item)
        if got:
            yield (item["fee_name"], *got)
        cols = item.get("columns")
        if isinstance(cols, dict):
            for name, col in cols.items():
                sub = _bands_of(col)
                if sub:
                    yield (f"{item['fee_name']}/{name}", *sub)
                elif item.get("band_uppers"):
                    rates = (col.get("rates_permille") or col.get("rates_percent")
                             or col.get("rates"))
                    if rates:
                        yield (f"{item['fee_name']}/{name}", list(item["band_uppers"]), list(rates))


def test_progressive_series_coverage(fee):
    """守住覆盖面：4 个差额累进条目**每一个**都必须至少产出一条序列。

    这条不是凑数。第一版 _progressive_series 漏认了「列级各自带 bands」这种写法，
    导致工程招标代理费整个条目没进校验，而当时的 `len(series) >= 4` 断言照样绿——
    因为另一个条目的 10 个列已经把数量凑够了。按条目点名才堵得住这种漏。
    """
    series = list(_progressive_series(fee))
    covered = {name.split("/")[0] for name, _, _ in series}
    expected = {i["fee_name"] for i in fee["items"]
                if i.get("paradigm") == "progressive_difference"}
    assert expected <= covered, f"这些差额累进条目未被任何序列覆盖：{expected - covered}"


def test_golden_examples_reproduce(fee):
    """**真正的外部验证**：用转录出来的档位复算原表自带的算例。

    这是本文件里唯一一条能证伪「数字抄错了」的测试——期望值 22.55 万元印在原表注2里，
    不是我们算出来的。档位上界或费率抄错任何一个，这里就对不上。

    （对照：下面那条速算扣除数等价性测试**证明不了数据对错** —— 两种算法都从同一组
    (uppers, rates) 推导，代数上恒等，抄错了也照样相等。那条守的是将来求值器的实现，
    不是数据。这个区别我第一版没想清楚，记在这里免得后人误读它的效力。）
    """
    checked = 0
    for item in fee["items"]:
        ex = item.get("golden_example")
        if not ex:
            continue
        col = item.get("columns", {}).get(ex["column"]) if ex.get("column") else None
        got = _bands_of(col) if col else _bands_of(item)
        assert got, f"{item['fee_name']} 有 golden_example 却取不到档位"
        ups, rates = got
        actual = _tiered(ex["base"], ups, [r / 100.0 for r in rates])
        assert math.isclose(actual, ex["expected_fee"], rel_tol=1e-9, abs_tol=1e-6), (
            f"{item['fee_name']} 复算原表算例不符：base={ex['base']} "
            f"算得 {actual} 期望 {ex['expected_fee']}（{ex['desc'][:60]}）"
        )
        checked += 1
    assert checked >= 1, "一条 golden_example 都没跑到——转录数据里的算例是最硬的验证，不该丢"


def test_quick_deduction_equals_tiered_accumulation(fee):
    """速算扣除数法 == 逐档累加法，逐点一致。

    ⚠ 效力边界，别误读：两种算法都从同一组 (uppers, rates) 推导，**代数上恒等**，
    所以它证明不了「数字抄得对不对」——抄错了两边也照样相等。
    它守的是**将来求值器的实现**：I-2.5 的求值器要按 spec 用速算扣除数法出数，
    这条锁死那种写法与逐档累加等价，防止实现走形。
    数据正确性靠上面的 golden_example 复算。
    """
    checked = 0
    for name, ups, rates in _progressive_series(fee):
        qds = _quick_deductions(ups, rates)
        probes = []
        lower = 0.0
        for up in ups:
            if up is None:
                probes += [lower * 1.5 + 1, lower * 10 + 1]
                break
            probes += [lower + (up - lower) * f for f in (0.001, 0.5, 0.999)] + [up]
            lower = up
        for x in probes:
            a = _tiered(x, ups, rates)
            b = _by_quick_deduction(x, ups, rates, qds)
            assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), (
                f"{name} 在 x={x}：逐档累加={a} 速算扣除={b}"
            )
            checked += 1
    assert checked >= 40, f"探测点只有 {checked} 个，覆盖不足"


def test_progressive_is_continuous_at_band_boundaries(fee):
    """差额累进在档界处必须连续。

    这条同时解释了一件事：这 4 项**不声明闭开性也是对的**——档界处两侧结果
    相等，"1000 算第 1 档还是第 2 档"在数值上没有区别。而下一条测试要求的
    那些范式则不然。
    """
    for name, ups, rates in _progressive_series(fee):
        for up in ups:
            if up is None:
                continue
            left = _tiered(up, ups, rates)
            right = _tiered(up + 1e-7, ups, rates)
            assert math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-6), (
                f"{name} 在档界 {up} 处不连续：{left} vs {right}"
            )


# 已知缺口：这两项有数值档位却未声明闭开性。
# 不擅自补 —— 闭开性决定档界处用哪一档的基价/费率，属于影响金额的语义，
# 必须由造价员对着原图确认，不能靠推测。登记在此是为了让缺口可见且有界：
# 新增条目若漏声明会直接判红，而这两项的消化需要人来拍板。
# 只有勘察设计费一项。工程监理费曾被误列在这里——它用的是 anchors（16 个插值
# 锚点）而非档位，锚点间插值天然连续，没有「档界归属」这回事，故不适用。
CLOSURE_KNOWN_GAPS = {"勘察设计费"}


def _has_numeric_bands(item):
    """认得出全部三种档位写法。漏认一种就会让缺口从这张网里溜走。"""
    return bool(item.get("bands") or item.get("band_uppers") or item.get("rate_bands"))


def test_banded_items_declare_closure(fee):
    """有数值档位的条目必须声明闭开性——差额累进除外。

    差额累进豁免是有证明的（见上一条连续性测试）：档界两侧结果相等，
    「1000 算第几档」在数值上没有区别。其余分档范式则不然：档界归属直接
    决定用哪一档的基价/费率。
    """
    missing = [
        i["fee_name"] for i in fee["items"]
        if _has_numeric_bands(i)
        and i.get("paradigm") != "progressive_difference"
        and not i.get("band_closure")
        and i["fee_name"] not in CLOSURE_KNOWN_GAPS
    ]
    assert not missing, f"以下分档条目未声明 band_closure，档界归属无解：{missing}"


def test_closure_known_gaps_do_not_grow(fee):
    """已知缺口只许缩小不许扩大。

    造价员确认后给对应条目补上 band_closure，再把名字从 CLOSURE_KNOWN_GAPS 删掉，
    这条测试会确保删除是真的（补完才删得掉）。
    """
    still_missing = {
        i["fee_name"] for i in fee["items"]
        if _has_numeric_bands(i)
        and i.get("paradigm") != "progressive_difference"
        and not i.get("band_closure")
    }
    stale = CLOSURE_KNOWN_GAPS - still_missing
    assert not stale, f"这些条目已补上 band_closure，请从 CLOSURE_KNOWN_GAPS 移除：{stale}"


from zt.estimate import fee_rules as fr  # noqa: E402


# ---------------------------------------------- 条目级闸：档界闭开性未确认（#159）
#
# 规则集放行之后，`勘察设计费` 是**唯一**仍被扣留的条目。它的判据不能建在
# 「规则集没签」上（那已经不成立了），也不能建在 `affects_amount` 上 ——
# 见下面两条对 True/False 两个分支的覆盖。

@pytest.mark.parametrize(
    "base,expect_differs",
    [
        # 12000 万元落在第③档正中间：两种闭开性都落进同一档，算得的金额一致
        (12000.0, False),
        # 60000 万元（6 亿）正好是第③档的上界：默认侧（上界含）算得出数，
        # 另一侧（上界不含）整个落表外、算不出 —— 这就是「档界归属决定结果」
        (60000.0, True),
    ],
    ids=["档内·两侧一致", "档界上·两侧不同"],
)
def test_closure_gap_item_is_withheld_on_both_branches(base, expect_differs):
    """🔴 `勘察设计费` 无条件扣留 —— `affects_amount` 的两个分支都覆盖。

    为什么不按 `affects_amount` 放行（本轮明确否掉的一个设计）：
    那个字段说的是「在**本次这个基数**上两侧算得的金额是否相同」，
    不是「档界归属已经确定」。按它放行的后果是同一条费用**时有时无** ——
    大多数基数给值，正好卡在档界上时不给值。而卡在档界上那次恰恰是最危险的一次，
    用户只会以为引擎坏了。档界归属未知就是规则未知（铁律 3）。

    这条同时是**夹具穷尽性**的交代：expect_differs 两个取值都被真实基数走到了，
    不是"名字覆盖整个概念、夹具只覆盖一半"。
    """
    raw = fr._suggest_one_ungated("survey_design_fee", base)
    alt = (raw["basis"] or {}).get("closure_alternative")
    assert alt is not None, "该条目不再走闭开性降级分支，本条失去判据"
    assert alt["affects_amount"] is expect_differs, (
        f"base={base} 的 affects_amount 变成了 {alt['affects_amount']}，"
        "夹具选的基数不再落在它声称的那个分支上（§5.2）")
    # 对照组：未过闸时**至少默认侧**算得出数，否则"扣留"就成了"本来就没有"
    assert raw["suggested"] is not None, "未过闸时也没有金额，闸测无从判定"

    gated = fr.suggest_one("survey_design_fee", base)
    assert gated["suggested"] is None, f"base={base} 档界未确认却出了金额"
    assert gated["range"] == [None, None]
    assert gated["unavailable_reason"] == "band_closure_unconfirmed"
    # 结构与出处照留（扣的是金额面，不是把这条藏起来）
    assert gated["basis"].get("source_image"), "出处被顺手吃掉了，造价员无从对图"
    assert (gated["basis"].get("band") or {}).get("rate_min") is not None
    # 逐条说明为什么没有值，且**不许**说成「规则集未签署」——规则集已经放行了
    msgs = [w["message"] for w in gated["warnings"] if w["code"] == "fee_suggestion_withheld"]
    assert msgs, "扣留了却没有 fee_suggestion_withheld 告警"
    assert "档位闭开性" in msgs[0], msgs[0]
    if fr.is_signed():
        assert "规则集未签署" not in msgs[0], (
            f"规则集已放行，扣留理由却还写着「未签署」—— 这条指示不可执行：{msgs[0]}")


def test_closure_gap_is_the_only_item_withheld_once_the_ruleset_is_released():
    """放行后**只有**这一条被扣留 —— 既证明放行真的生效，也证明扣留不是无差别的。

    两个方向缺一不可：全扣 = #159 没解决；全放 = 在档界上编了金额（铁律 3）。
    """
    assert fr.is_signed(), (
        "规则集回到了未签署态。若这是有意撤销 #159 的放行，请连同本条一起改 —— "
        "它钉的是「放行后只扣 1 条」这条性质，不是环境前提。")
    bases = {"工程费用": 12000.0, "中标金额": 6000.0, "建安工程造价": 10000.0,
             "总建筑面积": 6.0, "建筑面积": 60000.0, "受电容量": 2000.0,
             "专利计费基数": 500.0}
    # WS10-P03：三条带适用性的规则给在允许值上（杭州市区 / 生产性），本条钉的仍是「放行后
    # 只扣档界未确认那 1 条」；适用性扣留是另一件事，见 test_fee_rules_applicability.py。
    r = fr.suggest_all(bases, {"project_city": "hangzhou_core", "project_nature": "production"})
    inputs = [s for s in r["items"] if s["write_target"] == "input"]
    assert len(inputs) == 13, f"输入位不再是 13 个（{len(inputs)}），本条口径要重定"
    priced = [s for s in inputs if s["suggested"] is not None]
    blank = [s for s in inputs if s["suggested"] is None]
    assert len(priced) == 12, [s["item_id"] for s in priced]
    assert [(s["item_id"], s["unavailable_reason"]) for s in blank] == \
        [("survey_design_fee", "band_closure_unconfirmed")], blank
    assert "fee_rules_unsigned" not in {w["code"] for w in r["warnings"]}
    assert "fee_rules_owner_released" in {w["code"] for w in r["warnings"]}, \
        "放行了却不声明放行方式 —— 铁律 2 的最后一句：不许因为难看就藏起来"


# ---------------------------------------------------------------- 签署闸的金额面
#
# 上面那条 `test_unsigned_gate_withholds_amounts` 只断言 `suggested is None`。
# 对抗复核实证：那是**半截闸** —— 16 条里 9 条 suggested 已扣留，
# `basis["steps"]` 里照样带着「逐档累加合计 = 185 万元」这样的结论行，而界面把
# steps 逐条渲染在**同一行的手填输入框旁边**（Wizard.vue:724 的 v-for 紧挨着
# 700-707 的 a-input-number）：展开读到 185，抬手填进去，随后进 compute → C5 →
# C47 → C50 总投资。未签署的 LLM 转录费率就这样驱动了金额（铁律 2）。
#
# 所以这里换一条判据：**拿未过闸的真值做对照，扫过闸结果的每一个角落**。
# 「只扣 suggested」「只扣 steps」这类半截修复会立刻转红。

import json as _json
import re as _re

# 刻意选不整齐的基数：整数基数算出 40 / 90 这类小整数，会与费率、档界等无关数字
# 撞出假阳性，让这条扫描要么误报要么被迫放宽。
_LEAK_BASES_LARGE = {
    "工程费用": 12345.67, "中标金额": 12345.67, "建安工程造价": 12345.67,
    "总建筑面积": 3.21, "建筑面积": 32100.0, "受电容量": 1234.0,
    "专利计费基数": 12345.67,
}
# 小基数把另外两条只在边界上出现的告警逼出来：fee_min_fee_applied（正文里印了
# 「按档位算得 X 万元，低于最低收费 Y 万元」）与 fee_base_out_of_table 的外推分支
# （正文里印了外推算式 y0×base/x0）。只跑大基数的话这两条永远扫不到。
_LEAK_BASES_SMALL = {
    "工程费用": 1.23, "中标金额": 1.23, "建安工程造价": 1.23,
    "总建筑面积": 0.01, "建筑面积": 11.0, "受电容量": 3.0, "专利计费基数": 1.23,
}


def _amount_literals(v) -> set:
    """一个金额在下发文本里可能长的样子。`_num` 是引擎自己的格式化口径。"""
    return {fr._num(v), str(round(float(v), 4)), str(round(float(v), 2))}


def _appears(literal: str, text: str) -> bool:
    """数字边界匹配：`40` 不该被 `40000` 或 `1.40` 命中。"""
    return bool(_re.search(r"(?<![\d.])" + _re.escape(literal) + r"(?![\d])", text))


@pytest.mark.parametrize("bases", [_LEAK_BASES_LARGE, _LEAK_BASES_SMALL],
                         ids=["大基数", "小基数"])
def test_unsigned_gate_leaks_no_amount_anywhere_in_the_item(bases, unsigned_ruleset):
    """过闸后的**整条** FeeSuggestion（含 basis 每一个键、含每条 warning）序列化后，
    不得出现该条未过闸时算出的任何一个金额字面量。

    对照组用 `_suggest_all_ungated` 取真值 —— 没有对照组，这条测试在求值器整体
    坏掉（人人都算不出数）时也会全绿，那是误导性成功。
    """
    attrs = {s["name"]: s["default"] for s in fr.required_attrs()}
    raw = fr._suggest_all_ungated(bases, attrs)
    gated = fr._gate(fr._suggest_all_ungated(bases, attrs), fr.DEFAULT_RULESET)
    by_id = {s["item_id"]: s for s in gated["items"]}

    priced = [s for s in raw["items"] if s["suggested"] is not None]
    assert len(priced) >= 10, \
        f"对照组只有 {len(priced)} 条出数，求值器本身有问题，闸测无从判定"

    leaks = []
    for s in priced:
        text = _json.dumps(by_id[s["item_id"]], ensure_ascii=False)
        for v in [s["suggested"], *(s["range"] or [])]:
            if v is None:
                continue
            for lit in _amount_literals(v):
                if _appears(lit, text):
                    leaks.append((s["item_id"], lit))
    assert not leaks, (
        f"{len(leaks)} 处未签署金额从过闸结果里漏出去了（界面会把它渲染在手填框旁边）："
        f"{sorted(set(leaks))[:8]}")


def test_unsigned_gate_leaks_no_amount_through_the_top_level_warnings(unsigned_ruleset):
    """顶层 warnings 是另一条下发通道（前端结果页按 code 分组渲染），单独扫一遍。

    `_gate` 重建顶层 warnings 时用的是**过闸后**每条 item 的 warnings；哪天有人
    改成直接沿用 `result["warnings"]`，这条立刻红。
    """
    attrs = {s["name"]: s["default"] for s in fr.required_attrs()}
    raw = fr._suggest_all_ungated(_LEAK_BASES_SMALL, attrs)
    gated = fr._gate(fr._suggest_all_ungated(_LEAK_BASES_SMALL, attrs),
                     fr.DEFAULT_RULESET)
    amounts = {}
    for s in raw["items"]:
        for v in [s["suggested"], *(s["range"] or [])]:
            if v is not None:
                amounts.setdefault(s["item_id"], set()).update(_amount_literals(v))
    leaks = [(w["code"], w.get("item_id"), lit)
             for w in gated["warnings"]
             for lit in amounts.get(w.get("item_id"), ())
             if _appears(lit, w["message"] or "")]
    assert not leaks, f"告警正文里漏出了未签署金额：{leaks[:5]}"


def test_the_gate_still_discloses_the_structure_it_is_supposed_to_disclose(unsigned_ruleset):
    """闸是「算得出但不给金额」，不是「把 basis 清空」。

    没有这条，把 `_withhold` 写成 `basis = {}` 也能让上面两条全绿 —— 而那会让
    造价员既看不到金额、也看不到该签署什么，评审无从下手。
    """
    r = fr.suggest_all(_LEAK_BASES_LARGE,
                       {s["name"]: s["default"] for s in fr.required_attrs()})
    kept = 0
    for s in r["items"]:
        b = s["basis"]
        assert b.get("paradigm"), f"{s['item_id']} 连范式都没了"
        assert b.get("source_table") or b.get("source_image") or b.get("manual_reason"), \
            f"{s['item_id']} 的出处被闸顺手吃掉了，造价员无从对图复核"
        assert b.get("signoff_status") == "pending"
        if b.get("band") or b.get("variant") or b.get("matrix_row") or b.get("column"):
            kept += 1
    assert kept >= 10, f"只有 {kept} 条还留着档位/情形/取费列，basis 被清得太狠"


def test_steps_are_replaced_not_emptied_so_the_ui_says_why(unsigned_ruleset):
    """steps 被换成一句说明，而不是空数组：界面 `v-for steps` 渲染空数组等于
    什么都不显示 —— 用户只看到一个没有依据的空白，不知道是「没有规则」还是
    「有规则但未签署」。
    """
    r = fr.suggest_all({"工程费用": 12345.67}, {"region": "urban"})
    withheld = [s for s in r["items"] if s.get("unavailable_reason") == "ruleset_unsigned"]
    assert withheld, "没有任何条目被扣留，本条失去判据"
    for s in withheld:
        steps = s["basis"].get("steps")
        assert steps, f"{s['item_id']} 的 steps 被清成空，界面会显示一片空白"
        assert any("金额被扣留" in x for x in steps), f"{s['item_id']} 的 steps 没说明为什么"


def test_per_run_derived_rate_is_withheld_even_though_it_is_not_an_amount():
    """`basis.interpolated_rate` 上面那条字面量扫描**看不见** —— 它是费率不是金额。
    但它是按**本次 base_value** 插出来的等效费率：base_value × 它 = 本次金额，
    一次乘法。所以它属于「本次结果」而非「规则参数」，必须一并扣留。

    判据不是「字段为 None」，而是先证明**未过闸时它确实能还原出金额**，
    再断言过闸后拿不到 —— 否则求值器哪天不再产出这个键，这条会假绿。
    """
    bases = {"工程费用": 12345.67}
    raw = next(s for s in fr._suggest_all_ungated(bases, {})["items"]
               if s["item_id"] == "survey_design_fee")
    rate = (raw["basis"] or {}).get("interpolated_rate")
    assert rate is not None, "survey_design_fee 不再产出 interpolated_rate，本条失去判据"
    recovered = bases["工程费用"] * float(rate) / 100.0
    assert recovered == pytest.approx(raw["suggested"], rel=1e-4), (
        f"interpolated_rate 已不能还原金额（{recovered} vs {raw['suggested']}），"
        "本条的前提变了，请重新判断它该不该扣留")

    gated = next(s for s in fr.suggest_all(bases, {})["items"]
                 if s["item_id"] == "survey_design_fee")
    assert gated["basis"].get("interpolated_rate") is None, \
        "按本次基数插出来的等效费率没扣留 —— 一次乘法就还原出未签署的金额"
    # 表内那一档的费率区间是**规则参数**，保留（那正是签署评审要看的东西）
    assert (gated["basis"].get("band") or {}).get("rate_min") == 2.15


def test_required_attrs_is_not_a_bypass_around_the_signoff_gate():
    """`required_attrs()` 是**静态出口，不过 `_gate`** —— 它下发什么就是什么。

    所以它一个转录费率都不许带。第一版把 `raw_text` 当 `source_hint` 带出来，
    实测漏的是「住宅：150元/平方米」「250」这类未签署的转录单价（铁律 2）。

    判据分两条：
      1. 选项的键集必须正好是 {value, label} —— 换个键名把原文重新带出来照样红；
      2. 除选项的 `value`（那是数据自己的键，本来就必须下发）之外，
         下发的任何一个字符串都不许等于数据里的某条 `raw_text`。
    """
    raw_texts = set()

    def _collect(o):
        if isinstance(o, dict):
            t = o.get("raw_text")
            if isinstance(t, str) and t.strip():
                raw_texts.add(t.strip())
            for v in o.values():
                _collect(v)
        elif isinstance(o, list):
            for v in o:
                _collect(v)

    _collect(fr._load())
    assert len(raw_texts) > 50, f"规则数据里只找到 {len(raw_texts)} 条 raw_text，本条失去判据"

    specs = fr.required_attrs()
    for spec in specs:
        for opt in spec["options"]:
            assert set(opt) == {"value", "label"}, (
                f"{spec['name']}.{opt.get('value')} 的选项多了键 "
                f"{sorted(set(opt) - {'value', 'label'})} —— 静态出口不过签署闸，"
                f"多带的键很容易就是转录费率")

    emitted: list[str] = []

    def _leaves(o, in_option_value=False):
        if isinstance(o, dict):
            for k, v in o.items():
                _leaves(v, in_option_value=(k == "value"))
        elif isinstance(o, list):
            for v in o:
                _leaves(v)
        elif isinstance(o, str) and not in_option_value:
            emitted.append(o.strip())

    _leaves(specs)
    leaked = sorted(set(emitted) & raw_texts)
    assert not leaked, f"计费属性清单里夹带了未签署的转录费率原文：{leaked[:5]}"


# ------------------------------------------------- 分支覆盖 · 对抗复核第 2 轮
#
# 上面那两条泄漏扫描只跑手写的大 / 小两组基数。实证漏洞：`fee_band_open_ended`
# 的两条正文把被扣留的建议金额逐字印出来（「建议值取区间中值 207 万元」），
# 还顺带把「原文 184.0~230.0」这个金额区间一并带出 —— 而 basis.band.raw_text
# 恰恰就是因为这个理由在扣留时被 pop 掉的，正文这一份是漏网的第二份。
# 触发它需要基数落进可行性研究费的开口档（下界 500000 万元 = 50 亿），
# 大基数组的 12345.67 万元差了两个数量级 → 闸有洞，守洞的扫描也有洞，全绿。
#
# 结论：基数不能手写。下面按**每条规则自己的档界**自动构造探针基数，把
# 开口档 / 最低收费 / 表外外推 / 矩阵格这些只在边界上出现的分支逼出来。

import ast as _ast  # noqa: E402
import inspect as _inspect  # noqa: E402

_BOUNDARY_KEYS = ("lower", "upper", "x")


def _axis_boundaries(node, out: set) -> set:
    """递归收出一条规则里所有**基数轴**上的边界（档界 lower/upper、锚点 x、band_uppers）。

    只收基数轴，不收 fee_min/fee_max/rate/price 这些金额或费率轴 —— 拿费率当基数
    构造出来的探针落点是随机的，覆盖不到「档界正上方」这类真正危险的位置。
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _BOUNDARY_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                out.add(float(v))
            elif k == "band_uppers" and isinstance(v, list):
                out.update(float(x) for x in v if isinstance(x, (int, float)))
            else:
                _axis_boundaries(v, out)
    elif isinstance(node, list):
        for v in node:
            _axis_boundaries(v, out)
    return out


# 系数一律取"难看"的数：与上面 `_LEAK_BASES_*` 同一条纪律 —— 整齐基数会算出
# 9 / 15 / 1.0 这类小整数，跟档界、费率、"注3" 里的数字撞出一堆假阳性，逼得扫描
# 要么误报要么被迫放宽。乘完这几个系数，落点仍在原来那一档里（0.49997… 仍在下半档、
# 1.0000137 仍是档界正上方那一格），但算出来的金额一定带一长串有效数字。
_UGLY_FACTORS = (0.4999731, 1.0000137, 0.8137291, 3.1717233)


def _probe_bases(item: dict) -> list:
    """由档界派生一组探针基数：档界正上下方、档内、表下、表外 / 开口档。"""
    b = sorted(x for x in _axis_boundaries(item, set()) if x > 0)
    vals = {1.2337, 7.7731}              # 表下 / 最低收费侧
    for x in b:
        for f in _UGLY_FACTORS:
            vals.add(x * f)
    if b:
        vals.add(b[-1] * 2.1379)         # 表外 / 开口档
        vals.add(b[-1] * 11.3171)        # 再远一档，逼出末锚点外推
    return sorted(vals)


def _columns_of(item: dict) -> list:
    """该条规则的取费列取值（含「不给、让它回落默认」这一种）。"""
    cols = item.get("columns")
    if not isinstance(cols, dict):
        return [{}]
    attr = fr.COLUMN_ATTR.get(item["item_id"], "column")
    return [{}] + [{attr: k} for k in sorted(cols)]


def _probe_matrix(ruleset: str = fr.DEFAULT_RULESET):
    """(item_id, attrs, base) 全体探针。"""
    for item in fr._load(ruleset)["items"]:
        for attrs in _columns_of(item):
            for base in _probe_bases(item):
                yield item["item_id"], attrs, base


@pytest.fixture
def probe_runs(unsigned_ruleset):
    """每个探针跑一遍「未过闸真值 / 过闸结果」两侧，供下面几条测试共用。

    ⚠ 由 module 级降成 function 级（#159）：它现在依赖 function 级的
    `unsigned_ruleset` 夹具。此前的 `assert not fr.is_signed()` 是靠仓里数据
    恰好是 pending 才成立的，仓主放行后会**直接把这三条探针测打红**（而不是
    静默跳过）—— 那是好事，但判据不该建在数据状态上。现在两个态都构造得出来。
    """
    fr = unsigned_ruleset
    runs = []
    for item_id, attrs, base in _probe_matrix():
        raw = fr._suggest_one_ungated(item_id, base=base, attrs=dict(attrs))
        gated = fr.suggest_one(item_id, base=base, attrs=dict(attrs))
        runs.append((item_id, attrs, base, raw, gated))
    assert len(runs) > 300, f"只构造出 {len(runs)} 个探针，覆盖面不足以判定"
    return runs


def test_probe_matrix_actually_reaches_every_amount_bearing_branch(probe_runs):
    """**先证明探针有效**：四类只在边界上出现的分支必须真的被走到过。

    没有这条，下面那条泄漏扫描在探针构造坏掉（比如档界收集器返回空集）时
    也会全绿 —— 那正是本轮被抓到的那种误导性成功：607 条全绿，而闸有洞。
    """
    seen = set()
    for _id, _a, _b, raw, _g in probe_runs:
        for w in raw["warnings"]:
            if w["code"] == "fee_band_open_ended":
                seen.add("open_" + str((raw["basis"] or {}).get("open_band_rule")))
            else:
                seen.add(w["code"])
        where = (raw["basis"] or {}).get("extrapolated")
        if where:
            seen.add("extrapolated_" + where)
        if (raw["basis"] or {}).get("matrix_row"):
            seen.add("matrix_row")
    required = {
        "open_lower_bound_only",     # 开口档 · 原表只给下限（环评报告书 >100 亿）
        "open_range_midpoint",       # 开口档 · 原表给区间、取中值（可行性研究费 >50 亿）
        "fee_min_fee_applied",       # 最低收费（造价咨询费 不足 2000 元）
        "extrapolated_below_table",  # 表下按首锚点外推（监理费）
        "extrapolated_above_table",  # 表上按末锚点外推（监理费）
        "fee_base_out_of_table",     # 落不进任何档 / 不外推
        "matrix_row",                # 单价矩阵格
    }
    missing = sorted(required - seen)
    assert not missing, f"探针没走到这些分支，泄漏扫描对它们无判据：{missing}"


def test_unsigned_gate_leaks_no_amount_on_any_branch(probe_runs):
    """**闸的本体（分支覆盖版）**：任何一个探针上，过闸结果的任何一个角落，
    都不得出现该探针未过闸时算出的建议金额或区间端点。

    撤掉 `_WARNING_SCRUBBERS["fee_band_open_ended"]` 这一行，本条立刻点名
    feasibility_study_fee / eia_fee。
    """
    leaks, checked = [], 0
    for item_id, attrs, base, raw, gated in probe_runs:
        if raw["suggested"] is None and raw["range"] == [None, None]:
            continue
        text = _json.dumps(gated, ensure_ascii=False)
        for v in [raw["suggested"], *(raw["range"] or [])]:
            if v is None:
                continue
            # 只留 3 个字符以上的字面量。1~2 字符的（"0" "1" "3"）会命中 "注3："、
            # `"index": 1` 这类散文与结构里的数字 —— 实测 12 处全是这种撞车，而且
            # 从 "注3" 里读出一个 "3" 也复原不出被扣留的金额。本轮那条真漏洞的
            # 字面量是 "207" 与 "184.0"，都在门槛之上，判据没被这条放宽掉。
            lits = {lit for lit in _amount_literals(v) if len(lit) >= 3}
            checked += bool(lits)
            for lit in lits:
                if _appears(lit, text):
                    leaks.append((item_id, attrs, base, lit))
    assert checked > 1000, f"只比对了 {checked} 个金额字面量，扫描面不足以判定"
    assert not leaks, (
        f"{len(leaks)} 处未签署金额从过闸结果里漏出去了（界面会把它渲染在手填框旁边）；"
        f"前 5 处：{leaks[:5]}")


def test_open_ended_gate_keeps_the_signal_it_is_supposed_to_keep(probe_runs):
    """闸是「数扣、信号留」：开口档告警改写后仍须说得出「落在开口档」这件事，
    并区分「原表只给下限」与「原表给了区间、取中值」两条支路。

    没有这条，把 `_scrub_open_ended` 写成 `return dict(w, message="")` 也能让
    上面那条全绿 —— 而那会让造价员看不出这条为什么没有值。
    """
    by_rule = {}
    for _id, _a, _b, raw, gated in probe_runs:
        rule = (raw["basis"] or {}).get("open_band_rule")
        if rule is None:
            continue
        msgs = [w["message"] for w in gated["warnings"] if w["code"] == "fee_band_open_ended"]
        assert msgs, f"{_id} 走了开口档，过闸后却把这条告警整条弄丢了"
        by_rule.setdefault(rule, set()).update(msgs)
    assert set(by_rule) == {"lower_bound_only", "range_midpoint"}, sorted(by_rule)
    for rule, msgs in by_rule.items():
        for m in msgs:
            assert "开口档" in m, f"{rule}: 改写后连「开口档」这个信号都没了：{m}"
    lower_txt = " ".join(sorted(by_rule["lower_bound_only"]))
    mid_txt = " ".join(sorted(by_rule["range_midpoint"]))
    assert "只给下限" in lower_txt, lower_txt
    assert "中值" in mid_txt, mid_txt
    assert lower_txt != mid_txt, "两条支路改写成了同一句话，造价员分不出原表给的是什么"


def test_every_warn_site_that_prints_an_amount_is_registered():
    """元断言（对抗复核第 2 轮提案 ③）：本模块里凡是把 `_num(...) … 万元` 写进
    告警正文的 `_warn` 调用点，其 code 必须登记在 `_WARNING_SCRUBBERS` 里。

    这是「登记纪律」的机器化：`_WARNING_SCRUBBERS` 上方的注释写着「新增任何会把
    金额写进正文的 code 都必须在这里登记」，而实测证明光写注释不管用 ——
    `fee_band_open_ended` 就是这么漏的，且守闸的扫描因基数够不到开口档而恒绿。

    ⚠ 如实标注这条静态扫描**覆盖不到**什么：金额经由局部辅助函数格式化
    （如 `fee_band_closure_unconfirmed` 里的 `_side()`，「万元」三个字在辅助函数
    体内、不在 `_warn(...)` 的源码片段里）时，本条看不见它。那一类由上面的
    `test_unsigned_gate_leaks_no_amount_on_any_branch` 运行时兜底 ——
    两条判据方向不同，谁都不能单独宣布这道闸严密。
    """
    src = _inspect.getsource(fr)
    tree = _ast.parse(src)
    offenders = []
    sites = 0
    for node in _ast.walk(tree):
        if not (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Name)
                and node.func.id == "_warn" and node.args):
            continue
        seg = _ast.get_source_segment(src, node) or ""
        if "_num(" not in seg or "万元" not in seg:
            continue
        sites += 1
        code = node.args[0]
        if not (isinstance(code, _ast.Constant) and isinstance(code.value, str)):
            offenders.append((node.lineno, "<非字面量 code，无法静态判定>"))
            continue
        if code.value not in fr._WARNING_SCRUBBERS:
            offenders.append((node.lineno, code.value))
    assert sites >= 5, f"只扫到 {sites} 处会印金额的告警点，扫描器本身失效了"
    assert not offenders, (
        f"这些 _warn 调用点把金额写进了正文，却没在 _WARNING_SCRUBBERS 里登记改写函数"
        f"（未签署时会连同金额一起下发到手填框旁边）：{offenders}")
