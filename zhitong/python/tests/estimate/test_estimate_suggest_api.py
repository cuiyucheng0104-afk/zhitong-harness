# 来源：engine-service/tests/test_estimate_suggest_api.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""`POST /engine/estimate/suggest` 端点测试（契约裁决 B / §3.2）。

**这个文件存在的唯一理由**：对抗复核实证 `app/engine/estimate_suggest.py` 是死代码——
模块本身能跑（tests/test_estimate_suggest.py 全绿），但引擎没有任何路由把它接出去，
Java 没有 Controller 映射，前端向导第 3 步 `POST /nas/costai/estimate/suggest` 必然 404。
本文件只负责钉死**引擎侧那一段接线**：路由在、鉴权在、出参形状与 §3.2 一致、
空基准不 422、坏入参 422。Java/前端两段属 feat/phase-i-api 与 feat/phase-i-ui-wizard 泳道。

为什么单开文件而不是并进 test_estimate_api.py：那个文件是 api 泳道的交付物，
同一轮修复里 api 泳道大概率也在改它，分开写把合并冲突面压到 0。
"""
from __future__ import annotations

import pytest
from tests.estimate.fixtures.endpoint import HEADERS, client  # zt 改动：旧端点的转接





# 与 tests/test_estimate_suggest.py 同一组根输入（契约 §3.3 的 11 个必填位）。
# 数值是测试自造的规模，不是任何真实项目数据。
ROOT_INPUTS = {
    "经济技术指标!D4": 12000.0,
    "经济技术指标!D7": 5200.0,
    "经济技术指标!D8": 3100.0,
    "经济技术指标!D10": 8800.0,
    "经济技术指标!D11": 7600.0,
    "经济技术指标!D12": 6400.0,
    "经济技术指标!D13": 5900.0,
    "经济技术指标!D15": 4200.0,
    "经济技术指标!D16": 3300.0,
    "经济技术指标!D19": 260.0,
    "经济技术指标!D20": 140.0,
}
DIMS = {"region": None, "price_period": None,
        "project_type": "房屋建筑", "structure_type": None}

SUGGEST_URL = "/engine/estimate/suggest"


def _body(baselines, **kw) -> dict:
    d = {"inputs": dict(ROOT_INPUTS), "baselines": baselines, "dims": dict(DIMS)}
    d.update(kw)
    return d


# ------------------------------------------------------------------ 路由存在性

def test_suggest_entry_is_wired():
    """zt 改动：没有路由；钉住 CLI 真的注册了 suggest 子命令、接到 service.suggest。"""
    from zt.estimate.cli import cli

    assert "suggest" in cli._commands


@pytest.mark.skip(reason="zt 没有 HTTP 层与鉴权")
def test_suggest_requires_token():
    pass


def test_suggest_is_not_404_for_the_wizard_path():
    """前端向导第 3 步就是打这个路径。404 = 第 3 步整步废掉。"""
    r = client.post(SUGGEST_URL, headers=HEADERS, json=_body([]))
    assert r.status_code != 404, "路由缺席，向导第 3 步必然 404"
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ 出参形状（§3.2）

def test_suggest_returns_contract_shape(concept_baselines):
    r = client.post(SUGGEST_URL, headers=HEADERS, json=_body(concept_baselines))
    assert r.status_code == 200, r.text
    body = r.json()
    # zt 改动：没有 usage 与透传字段
    for k in ("suggestions", "unresolved", "fee", "coverage", "warnings"):
        assert k in body, f"§3.2 出参缺键：{k}"
    cov = body["coverage"]
    assert cov["cost_inputs"] == 150          # 模板实测 150 个 kind=="cost" 输入位
    assert cov["suggested"] + cov["unresolved"] == 150


def test_suggest_end_to_end_matches_module_output(concept_baselines):
    """端点不许在模块结果上二次加工——HTTP 出来的数必须等于 suggest() 直接算的数。"""
    from zt.estimate.suggest import suggest as suggest_fn
    expect = suggest_fn(ROOT_INPUTS, concept_baselines, dims=DIMS)
    got = client.post(SUGGEST_URL, headers=HEADERS,
                      json=_body(concept_baselines)).json()
    assert got["coverage"]["suggested"] == expect["coverage"]["suggested"] == 77
    assert got["suggestions"] == expect["suggestions"]
    assert got["unresolved"] == expect["unresolved"]


def test_suggest_every_amount_is_traceable(concept_baselines):
    """铁律 3：每一分建议金额都要回链得到基准行，且恒可覆盖。"""
    body = client.post(SUGGEST_URL, headers=HEADERS,
                       json=_body(concept_baselines)).json()
    assert body["suggestions"]
    for s in body["suggestions"]:
        assert s["baseline_ref"]
        assert s["editable"] is True
        assert s["match"] in ("cell", "semantic", "item_code", "item_name")
        assert s["baseline_ref"] in s["evidence"]["baseline_refs"]


@pytest.mark.skip(reason="zt 没有透传字段（sys_company_code / project_id / operator_id 属旧 Java 记账）")
def test_suggest_passthrough_is_echoed():
    pass


# ------------------------------------------------------------------ 降级与错误（§3.2 / §5.2）

def test_empty_baselines_is_200_not_422():
    """§3.2 明文：新租户没灌种子是正常态 → 200 + rate=0 + 全部 unresolved。"""
    r = client.post(SUGGEST_URL, headers=HEADERS, json=_body([]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestions"] == []
    assert body["coverage"]["rate"] == 0.0
    assert len(body["unresolved"]) == 150
    # WS10-P02：包干额 28 格不走基准查表（baseline_not_scalable / manual_required），
    # 其余按面积推算的格查不到基准 → no_baseline
    assert {u["reason"] for u in body["unresolved"]} == {
        "no_baseline", "baseline_not_scalable", "manual_required"}


def test_missing_root_inputs_is_200_with_no_quantity(concept_baselines):
    """suggest 是纯查询，不是 compute —— 不套 11 个必填闸（那是裁决 C 给 compute 的）。

    根输入缺失的后果是推不出数量，逐条落 unresolved，不是 422。实测分布
    （空 inputs + 224 条种子基准）：quantity_zero 105 条（数量格是跨表引用，
    根输入空→按 0 计→除不出金额）+ no_quantity 45 条（数量格本身是待填输入位）。
    关键是 **suggested 恒 0 —— 一分钱都不许凭空出**。
    """
    r = client.post(SUGGEST_URL, headers=HEADERS,
                    json={"inputs": {}, "baselines": concept_baselines, "dims": DIMS})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestions"] == []
    assert body["coverage"]["suggested"] == 0
    assert body["coverage"]["unresolved"] == 150
    # 包干额 28 格（WS10-P02）在查数量之前就分流了，不参与「缺数量」的计数
    assert {u["reason"] for u in body["unresolved"]} == {
        "quantity_zero", "no_quantity", "baseline_not_scalable", "manual_required"}


@pytest.mark.parametrize("bad", ["一万二", True, None, [1], {"a": 1}])
def test_non_numeric_input_is_422(bad, concept_baselines):
    """契约 §5.2：inputs 值非数值（含 bool）→ 422，不许 pydantic 静默转 1.0。"""
    inputs = dict(ROOT_INPUTS)
    inputs["经济技术指标!D4"] = bad
    r = client.post(SUGGEST_URL, headers=HEADERS,
                    json={"inputs": inputs, "baselines": concept_baselines})
    assert r.status_code == 422, f"{bad!r} 被静默接受了：{r.text[:200]}"


def test_unknown_template_is_422(concept_baselines):
    r = client.post(SUGGEST_URL, headers=HEADERS,
                    json=_body(concept_baselines, template_code="no_such_tpl"))
    assert r.status_code == 422


def test_fee_bases_without_fee_rules_engine_warns_loudly(concept_baselines):
    """调用方明确要了费率建议但 fee_rules 泳道尚未落地时：**不许静默回空**。

    要么 fee 段有数（模块已合入），要么 warnings 里有一条 fee_rules_unavailable
    把缺口点明。空 fee + 零告警 = 又一次「空结果=误导性成功」。
    """
    body = client.post(SUGGEST_URL, headers=HEADERS, json=_body(
        concept_baselines, fee_bases={"工程费用": 12000.0},
        fee_attrs={"region": "urban"})).json()
    codes = [w["code"] for w in body["warnings"]]
    assert body["fee"] or "fee_rules_unavailable" in codes, \
        "fee_bases 给了却既没出费用建议也没告警"


# ------------------------------------------------------------------ 偏离阈值（§1.2）
#
# ⚠ O-22：`with_deviation` 开关与 `deviations` 出口已删除。服务端 `check_deviation()`
# 从 Java 到前端全程无调用方（实测 grep 零命中），而前端 estimateModel.ts 另有一份
# 本地实现在真的跑 —— 两份会漂移的实现 + 其中一份没人调，是最差的形态。
# 前端本地算的理由成立：偏离率随用户改一个数就变，走后端等于改一格回一次网络，
# 150 个成本位填下来会等到用户放弃。
#
# 留下来的是**阈值**：它是判 info/warn 的口径，必须由引擎单点下发。

def test_tolerance_is_always_returned(concept_baselines):
    """阈值恒下发，不再是"要了才给"——前端每次都要用它。"""
    body = client.post(SUGGEST_URL, headers=HEADERS,
                       json=_body(concept_baselines)).json()
    assert body["tolerance"] == 0.20


def test_deviation_fields_are_gone_for_good(concept_baselines):
    """删掉的字段不许因为"看着像漏了"被加回来。"""
    body = client.post(SUGGEST_URL, headers=HEADERS,
                       json=_body(concept_baselines)).json()
    assert "deviations" not in body

    # zt 改动：没有老调用方要兼容（spec 决策 2）；请求里多余的字段一律拒收并点名，免得 agent 拼错键名被静默忽略
    r = client.post(SUGGEST_URL, headers=HEADERS,
                    json=dict(_body(concept_baselines), with_deviation=True))
    assert r.status_code == 422 and "with_deviation" in r.json()["detail"], r.text


def test_range_is_the_sample_spread_not_the_tolerance(concept_baselines):
    """WS10-P01：前端本地判偏离靠 range，而 range 现在是样本成员的 [min, max]
    （单成员为 [null, null]、range_basis=single_value），不再是 ±tolerance 的对称放缩。
    tolerance 仍下发（费率侧与老调用方在用），但不再是基准侧 range 的来源。"""
    body = client.post(SUGGEST_URL, headers=HEADERS,
                       json=_body(concept_baselines)).json()
    row = next(s for s in body["suggestions"] if s["cell"] == "1.建筑工程费!C7")
    assert row["range_basis"] == "sample_min_max"
    assert row["range"] == [124.8, 130.0]      # 种子 R16=240、R07=250 × 5200 ㎡ / 10000
    single = next(s for s in body["suggestions"] if s["cell"] == "1.建筑工程费!C44")
    assert single["range"] == [None, None] and single["range_basis"] == "single_value"


# ---------------------------------------------- Java 侧下发报文的线上形状（对抗复核第 2 轮 #1）
#
# Java 侧的 EstimateServiceImpl#baselineToEngineRow / #itemToEngineRow 手工把实体转成
# 引擎要的 snake_case 行。**这一步没有编译器保护**：写成 camelCase 引擎不会报错，
# 只是一条都匹配不上 —— 200 + coverage.rate=0，一次静默的"没有基准"。
# 本机无 JDK、CI 也不编译 Java（.github/workflows/ci.yml 只有 pytest），所以那半边由
# 后端/yidu-nas-server/src/test/java/EstimateSuggestBridgeTest.java 断言"Java 发出的键
# 就是这些"，这边断言"引擎吃这些键真的出得了建议"。两边合起来才闭环，各自都不作数。
#
# 下面这行是照 baselineToEngineRow 的 put 顺序逐字段抄下来的（含 unit_cost 为 JSON
# 数字、source_row 为 JSON 整数），不是另造一份形状。

_JAVA_BASELINE_ROW = {
    "indicator_code": "GSYZ-JZ-R07",
    "region": None,
    "price_period": None,
    "project_type": "房屋建筑",
    "structure_type": None,
    "item_code": None,
    "item_name": "土石方工程",
    "unit": "㎡",
    "unit_cost": 1234.5678,
    "base_metric": "总建筑面积",
    "source": "gsyz_v1",
    "source_sheet": "1.建筑工程费",
    "source_row": 7,
}

_JAVA_ITEM_ROW = {
    "item_code": "GSJZ-01-007",
    "item_name": "土石方工程",
    "list_source": "jz",
    "seq_no": "1.10",          # varchar，绝不数值化（1.10 塌缩事故）
    "unit": "㎡",
    "denominator_base": None,
    "numerator_base": None,
    "chapter": "01",
    "item_level": 2,
}


def test_java_shaped_payload_produces_a_suggestion():
    """Java 手工转出来的 snake_case 行，引擎必须真的能用它出建议。"""
    r = client.post(SUGGEST_URL, headers=HEADERS, json={
        "inputs": dict(ROOT_INPUTS),
        "baselines": [dict(_JAVA_BASELINE_ROW)],
        "items": [dict(_JAVA_ITEM_ROW)],
        "dims": dict(DIMS),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    hit = next((s for s in body["suggestions"] if s["cell"] == "1.建筑工程费!C7"), None)
    assert hit is not None, f"Java 形状的基准没能命中；unresolved 头部：{body['unresolved'][:2]}"
    assert hit["match"] == "cell"                 # source_sheet + source_row 走的是第一级
    assert hit["baseline_ref"] == "GSYZ-JZ-R07"   # 可追溯回 concept_indicator_baseline
    assert hit["unit_cost"] == 1234.5678
    assert hit["editable"] is True


def test_java_shaped_payload_with_camel_case_keys_matches_nothing():
    """负控：同一行改成 camelCase → 引擎不报错，但一条都匹配不上。

    这正是"静默失败"的形状，也正是 Java 侧必须手工转 snake_case、且必须有测试盯着
    的理由。若哪天引擎改成两种键名都吃，本条会转红 —— 那时要同步放宽 Java 侧断言，
    而不是删掉这条。
    """
    camel = {
        "indicatorCode": "GSYZ-JZ-R07", "itemName": "土石方工程", "itemCode": None,
        "unit": "㎡", "unitCost": 1234.5678, "baseMetric": "总建筑面积",
        "sourceSheet": "1.建筑工程费", "sourceRow": 7, "projectType": "房屋建筑",
        "region": None, "pricePeriod": None, "structureType": None,
    }
    r = client.post(SUGGEST_URL, headers=HEADERS, json={
        "inputs": dict(ROOT_INPUTS), "baselines": [camel], "dims": dict(DIMS)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestions"] == []
    assert body["coverage"]["rate"] == 0.0


def test_java_shaped_unit_cost_as_string_is_dropped_not_guessed():
    """负控：unit_cost 若被写成 JSON 字符串（BigDecimal 转 String 的经典事故），
    引擎判该行无可用 unit_cost 并丢弃，同时出 baseline_row_invalid 告警 —— 不静默。"""
    row = dict(_JAVA_BASELINE_ROW)
    row["unit_cost"] = "1234.5678"
    body = client.post(SUGGEST_URL, headers=HEADERS, json={
        "inputs": dict(ROOT_INPUTS), "baselines": [row], "dims": dict(DIMS)}).json()
    assert body["suggestions"] == []
    assert "baseline_row_invalid" in [w["code"] for w in body["warnings"]]


def test_java_shaped_payload_with_absent_nullable_keys():
    """线上报文里这些键其实是**缺席**的，不是 null —— 引擎必须照样匹配。

    hutool 的 JSONUtil 默认 ignoreNullValue=true：Java 侧 baselineToEngineRow 里
    put(null) 的列根本不会写进报文。首批 224 条种子除 project_type 外四维全 NULL，
    所以生产报文长的就是下面这样。若引擎哪天改成"缺键即不匹配"，本条会转红 ——
    那是真的会让全部 224 条基准在线上一条都用不上的改动，必须当场拦住。
    """
    row = {k: v for k, v in _JAVA_BASELINE_ROW.items() if v is not None}
    assert "region" not in row and "item_code" not in row and "structure_type" not in row

    r = client.post(SUGGEST_URL, headers=HEADERS, json={
        "inputs": dict(ROOT_INPUTS), "baselines": [row], "dims": dict(DIMS)})
    assert r.status_code == 200, r.text
    hit = next((s for s in r.json()["suggestions"] if s["cell"] == "1.建筑工程费!C7"), None)
    assert hit is not None, "缺席的可空列被当成了不匹配 —— 线上 224 条基准会一条都用不上"
    assert hit["match"] == "cell"
    assert hit["baseline_ref"] == "GSYZ-JZ-R07"


# ------------------------------------------------------------------ 受控下拉（O-08）
#
# ⚠ 这组测试**不打桩**：走真 fee_rules、真模板、真 HTTP 出参模型。
# 打桩版本会绿在一个 `EstimateSuggestOut` 根本不下发该字段的世界里 ——
# 那正是本条 finding 的形态：前端消费与降级都写好了，引擎从没产出过这个键，
# 而回归闸喂的是自造夹具，所以真链路缺字段时它照样绿。

FEE_ATTRS_FOR_THE_WIZARD = ("bidding_type", "consulting_service", "eia_doc_type")


def test_required_fee_attrs_survives_the_response_model(concept_baselines):
    """`EstimateSuggestOut` 是逐字段构造的 pydantic 模型：没在模型里声明的键会被
    **静默剥掉**。所以断言必须落在 HTTP body 上，不能落在 suggest() 的返回值上。
    """
    r = client.post(SUGGEST_URL, headers=HEADERS, json=_body(concept_baselines))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "required_fee_attrs" in body, \
        f"出参没有 required_fee_attrs，前端一个受控下拉都渲染不出来；现有键：{sorted(body)}"
    specs = body["required_fee_attrs"]
    assert len(specs) >= 3, f"清单只有 {len(specs)} 条"
    names = {s["name"] for s in specs}
    missing = set(FEE_ATTRS_FOR_THE_WIZARD) - names
    assert not missing, f"向导第 4 步点名的三个下拉缺：{sorted(missing)}（实得 {sorted(names)}）"


def test_every_fee_attr_spec_can_actually_render_a_dropdown(concept_baselines):
    """前端 `feeAttrRows()` 的丢弃规则：`name` 为空、或 `options` 为空 → 整条丢掉（静默）。
    引擎发一条渲染不出来的规格，等于没发。
    """
    specs = client.post(SUGGEST_URL, headers=HEADERS,
                        json=_body(concept_baselines)).json()["required_fee_attrs"]
    bad = []
    for s in specs:
        if not str(s.get("name") or "").strip():
            bad.append(("空 name", s))
        opts = s.get("options") or []
        if not [o for o in opts if str(o.get("value") or "").strip()]:
            bad.append((f"{s.get('name')} 没有可选值", s))
        if s.get("default") and s["default"] not in [o.get("value") for o in opts]:
            bad.append((f"{s.get('name')} 的 default 不在自己的 options 里", s))
    assert not bad, f"这些规格前端会静默丢弃或渲染出一个选不中默认值的下拉：{bad[:3]}"


def test_fee_attrs_supplied_are_marked_satisfied(concept_baselines):
    """传了属性 → 该条 satisfied=True；没传 → False。前端据此知道「还差哪几个」，
    而不是看着一堆 fee_attr_defaulted 告警反推。
    """
    body = client.post(SUGGEST_URL, headers=HEADERS, json=_body(
        concept_baselines, fee_attrs={"eia_doc_type": "report_form"})).json()
    by_name = {s["name"]: s for s in body["required_fee_attrs"]}
    assert by_name["eia_doc_type"]["satisfied"] is True
    assert by_name["bidding_type"]["satisfied"] is False, \
        "没传的属性被标成已满足 —— 前端会以为用户确认过了"


def test_the_dropdowns_cover_what_the_engine_would_otherwise_default(concept_baselines):
    """闭环：引擎发几条 `fee_attr_defaulted`（= 我替你选了个影响金额的值），
    清单就必须覆盖到那几条对应的规则条目。这条比「长度 ≥3」硬得多。
    """
    from zt.estimate import fee_rules as fr
    bases = {i["base_key"]: 12000.0 for i in fr.required_bases() if i["base_key"]}
    body = client.post(SUGGEST_URL, headers=HEADERS,
                       json=_body(concept_baselines, fee_bases=bases)).json()
    defaulted = {w.get("item_id") for w in body["warnings"]
                 if w.get("code") == "fee_attr_defaulted"}
    assert defaulted, "本次一条 fee_attr_defaulted 都没发，这条测试失去判据"
    covered = {i for s in body["required_fee_attrs"] for i in (s.get("item_ids") or [])}
    assert defaulted <= covered, \
        f"这些条目在按默认值算钱，用户却没有下拉可以纠正：{sorted(defaulted - covered)}"
