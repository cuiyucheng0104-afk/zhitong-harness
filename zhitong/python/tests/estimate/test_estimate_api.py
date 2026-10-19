# 来源：engine-service/tests/test_estimate_api.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""概算三端点测试（spec I-3.1）。

两条验收判据在这里被钉死：
  1. `extract` 响应体**无任何金额字段** —— 递归扫描全响应体的键名（test_extract_*）；
  2. `compute` **拒绝缺失必填输入** —— 11 个根输入位少一个就 422（test_compute_*）。

不打真实 LLM：extract 的 LLM 调用与文件读取全部 monkeypatch，
compute/template 本就是纯确定性代码，直接跑真模板。
"""
from __future__ import annotations

import json
import re
import sys
import types

import pytest

from zt.estimate import extract as estimate_extract


from zt.estimate import service as estimate_api  # noqa: E402  # zt 改动：旧端点模块 → 接线层
from tests.estimate.fixtures import endpoint
from tests.estimate.fixtures.endpoint import HEADERS, client  # zt 改动：旧端点的转接


REQUIRED_11 = [
    "经济技术指标!D4", "经济技术指标!D7", "经济技术指标!D8", "经济技术指标!D10",
    "经济技术指标!D11", "经济技术指标!D12", "经济技术指标!D13", "经济技术指标!D15",
    "经济技术指标!D16", "经济技术指标!D19", "经济技术指标!D20",
]

# 金额/费用味道的键名。extract 响应体里出现任何一个都算违反 spec I-3.1 验收判据。
MONEY_KEY = re.compile(
    r"cost|fee|amount|price|money|budget|total|xlsx|sheet|金额|费用|造价|单价|万元",
    re.I,
)


# 任取一个 kind=="cost" 的成本输入位，让 compute 的产出不是全零。
# 由来：compute 新增了全零闸（只填 11 个必填位、150 个成本位全空 → 422，
# 因为那会出一份七项合计全 0 的"生成成功"概算表）。本常量让既有用例继续验证
# 它们本来要验的东西（totals 形状 / 费率 / 类型校验），而不是撞在全零闸上。
# 实测 1.建筑工程费!C7 = 1.0 万元 → project_cost 1.0、static_total 1.05。
ONE_COST_CELL = "1.建筑工程费!C7"


def _full_inputs(**override) -> dict:
    d = {c: 1000.0 for c in REQUIRED_11}
    d[ONE_COST_CELL] = 1.0
    d.update(override)
    return d


def _walk_keys(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(k)
            _walk_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_keys(v, out)


class _FakeUsage:
    prompt_tokens = 11
    completion_tokens = 22
    latency_ms = 33
    model = "fake-model"
    # 共用助手 chat_json（WS07 K12）要读这两个：finish_reason=length 判截断、cache_hits 记账
    finish_reason = ""
    cache_hits = 0


def _stub_chain(monkeypatch, per_file_text: list[str], llm_answers: list):
    """按调用顺序返回正文与 agent 回答（zt 改动：桩打在接线层的 load_document 与转接的 AGENT 上）。"""
    endpoint.stub_chain(monkeypatch, per_file_text, llm_answers)


def _ans(cells=None, buildings=None, checks=None) -> dict:
    """LLM 应答（WS10-P05/P08/P09 形态）：{buildings, checks, cells}，每格 / 每个总量是数组。"""
    return {"buildings": list(buildings or []), "checks": dict(checks or {}),
            "cells": {k: (v if isinstance(v, list) else [v]) for k, v in (cells or {}).items()}}


def _files(n=1):
    return [
        {"file_id": f"f{i}", "rel_path": f"_engine_test/d{i}.docx", "file_name": f"d{i}.docx"}
        for i in range(n)
    ]


# ------------------------------------------------------------------ 鉴权

@pytest.mark.skip(reason="zt 没有 HTTP 层与鉴权：脚本在本机、按 agent 的会话权限运行")
def test_endpoints_require_token():
    pass


# ------------------------------------------------------------------ extract

def test_extract_response_has_no_money_field(monkeypatch):
    """spec I-3.1 验收判据①：extract 响应体不得出现任何金额字段。"""
    _stub_chain(
        monkeypatch,
        ["用地面积 12000 ㎡，A区地下室 3000 ㎡"],
        [_ans(cells={"经济技术指标!D4": {"value": "12000", "quote": "用地面积 12000 ㎡"}},
              buildings=[{"name": "A区地下室", "level": "underground", "area": "3000",
                          "quote": "A区地下室 3000 ㎡"},
                         {"name": "9#楼", "level": "above_ground", "area": "5000", "quote": "9#楼"},
                         {"name": "10#楼", "level": "above_ground", "area": "5000", "quote": "10#楼"},
                         {"name": "11#楼", "level": "above_ground", "area": "5000", "quote": "11#楼"},
                         {"name": "12#楼", "level": "above_ground", "area": "5000", "quote": "12#楼"}],
              checks={"gross_building_area": [{"value": "30000", "quote": "总建筑面积 30000"}]})],
    )
    r = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": _files(1)})
    assert r.status_code == 200, r.text
    body = r.json()
    # 前置（WS10-P05）：新键都真的出现了，下面的全键扫描才扫得到它们（否则是空扫）
    assert body["buildings"] and body["check_values"] and body["warnings"]
    assert any(u["reason"] == "unmapped_building" for u in body["unresolved"])
    # usage.total_tokens 是 LLM token 计数（issue #706 补给 Java 记账），不是金额。
    # 只按完整路径豁免这一个键，正则不放宽 —— 其余任何位置出现 total* 照样红。
    usage = dict(body.get("usage") or {})
    assert isinstance(usage.pop("total_tokens", 0), int)
    keys = []
    _walk_keys({**body, "usage": usage}, keys)
    offenders = [k for k in keys if MONEY_KEY.search(k)]
    assert offenders == [], f"extract 响应体出现金额字段：{offenders}"
    # 顺带钉死：不出 sheets/totals/xlsx_base64（那是 compute 的活）
    for forbidden in ("sheets", "totals", "xlsx_base64", "indicators"):
        assert forbidden not in body


def test_extract_candidates_always_need_manual(monkeypatch):
    """铁律 2：抽取结果须经用户确认才进计算 —— needs_manual 恒 True，无例外分支。"""
    _stub_chain(
        monkeypatch,
        ["用地面积 12000 ㎡"],
        [_ans(cells={"经济技术指标!D4": {"value": "12000", "quote": "用地面积 12000 ㎡"}})],
    )
    body = client.post("/engine/estimate/extract", headers=HEADERS,
                       json={"files": _files(1)}).json()
    assert body["candidates"]
    assert all(c["needs_manual"] is True for c in body["candidates"])
    # 原文命中 → confidence 1.0（二值命中标记，不是概率）
    assert body["candidates"][0]["confidence"] == 1.0
    assert body["candidates"][0]["value"] == 12000.0


def test_extract_quote_not_in_source_is_confidence_zero(monkeypatch):
    _stub_chain(
        monkeypatch,
        ["用地面积 12000 ㎡"],
        [_ans(cells={"经济技术指标!D4": {"value": "12000", "quote": "本项目占地一万二千平方米"}})],
    )
    body = client.post("/engine/estimate/extract", headers=HEADERS,
                       json={"files": _files(1)}).json()
    assert body["candidates"][0]["confidence"] == 0.0


def test_extract_conflicting_values_go_ambiguous_not_silently_picked(monkeypatch):
    """两份文件给了不同的用地面积 —— 绝不静默选边，落 unresolved(ambiguous)。"""
    _stub_chain(
        monkeypatch,
        ["用地面积 12000 ㎡", "用地面积 9000 ㎡"],
        [_ans(cells={"经济技术指标!D4": {"value": "12000", "quote": "用地面积 12000 ㎡"}}),
         _ans(cells={"经济技术指标!D4": {"value": "9000", "quote": "用地面积 9000 ㎡"}})],
    )
    body = client.post("/engine/estimate/extract", headers=HEADERS,
                       json={"files": _files(2)}).json()
    assert [c["cell"] for c in body["candidates"]] == []
    amb = [u for u in body["unresolved"] if u["reason"] == "ambiguous"]
    assert len(amb) == 1 and amb[0]["cell"] == "经济技术指标!D4"
    assert "12000" in amb[0]["detail"] and "9000" in amb[0]["detail"]


def test_extract_partial_no_text_is_200_with_unresolved(monkeypatch):
    """契约 §5.2：部分文件取不到文本 → 200，失败文件进 unresolved(no_text)。"""
    _stub_chain(
        monkeypatch,
        ["用地面积 12000 ㎡", ""],
        [_ans(cells={"经济技术指标!D4": {"value": "12000", "quote": "用地面积 12000 ㎡"}})],
    )
    r = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": _files(2)})
    assert r.status_code == 200
    body = r.json()
    no_text = [u for u in body["unresolved"] if u["reason"] == "no_text"]
    assert len(no_text) == 1 and no_text[0]["source_file_id"] == "f1"
    assert len(body["candidates"]) == 1


def test_extract_all_no_text_is_422_and_names_ocr_gap(monkeypatch):
    _stub_chain(monkeypatch, ["", ""], [])
    r = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": _files(2)})
    assert r.status_code == 422
    # 降级态必须点明（OCR 未配置时）——与 quantity.py 同款措辞
    # zt 改动：没有 OCR 服务；提示写的是看图补旁车
    assert "所有文件都抽不出可读文本" in r.json()["detail"]


@pytest.mark.skip(reason="zt 不调用模型：DeepSeek 凭据缺失 / 不可用的 502 没有对应物")
def test_extract_llm_unavailable_is_502_not_empty_200():
    pass


def test_extract_llm_garbage_is_502(monkeypatch):
    # 共用助手对「解析不出」重调一次（WS07 K12）：两次都是废话才 502
    _stub_chain(monkeypatch, ["用地面积 12000 ㎡"], ["我觉得应该是一万二", "还是一万二"])
    r = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": _files(1)})
    assert r.status_code == 502


def test_extract_empty_files_422():
    r = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": []})
    assert r.status_code == 422


# ------------------------------------------------------------------ extract：单体不丢、占地提示、文件名（WS29-d，issue #1010）

def test_extract_endpoint_keeps_no_area_buildings_and_carries_the_footprint_hint(monkeypatch):
    """端点整链：无面积单体、推算提示（unresolved.derived）、text_stats 的计数都要真的出现在响应里。

    响应模型 EstimateUnresolvedOut 不声明 derived 时，pydantic 会把它静默丢掉 —— 引擎算出来了，
    前端永远拿不到（这条就是钉这个的）。
    """
    src = ("总用地面积\tm2\t43783.70\n建筑密度\t\t30%\t≤30%\n楼号\t功能\n1#楼\t住宅\t\n2#楼\t住宅\t\n"
           "地下室\t地库\t59300.00")
    _stub_chain(monkeypatch, [src], [{
        "buildings": [
            {"name": "1#楼", "level": "above_ground", "area": None, "quote": "1#楼\t住宅"},
            {"name": "2#楼", "level": "above_ground", "area": None, "quote": "2#楼\t住宅"},
            {"name": "地下室", "level": "underground", "area": "59300.00", "quote": "地下室\t地库\t59300.00"}],
        "checks": {"building_density": [{"value": "30%", "quote": "建筑密度\t\t30%"}]},
        "cells": {"经济技术指标!D4": [{"value": "43783.70", "quote": "总用地面积\tm2\t43783.70"}]}}])
    r = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": [
        {"file_id": "2104518694846009344", "rel_path": "_engine_test/d0.docx", "file_name": "建施说明251016.docx"}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [b["name"] for b in body["buildings"]] == ["1#楼", "2#楼", "地下室"]
    assert [b.get("area_missing") for b in body["buildings"]] == [True, True, None]
    assert "building_area_missing" in [w["code"] for w in body["warnings"]]
    d15 = next(u for u in body["unresolved"] if u["cell"] == "经济技术指标!D15")
    assert d15["derived"]["value"] == 13135.11 and d15["derived"]["scope_basis"] == "whole_site"
    assert "建施说明251016.docx" in d15["detail"] and "2104518694846009344" not in d15["detail"]
    assert all(u.get("derived") is None for u in body["unresolved"] if u["cell"] != "经济技术指标!D15")
    assert "经济技术指标!D15" not in [c["cell"] for c in body["candidates"]]
    st = body["text_stats"][0]
    assert st["file_name"] == "建施说明251016.docx" and st["building_count_raw"] == 3 and st["building_count"] == 3
    assert "completion_tokens" not in st and "llm_calls" not in st   # zt 改动：不再记 token 与调用次数


# ------------------------------------------------------------------ extract：标段口径提示（WS29-s，issue #968）
#
# 实测 08-013 第 3 项：项目叫「…一标段（软件+清单）」，建施说明给的是全地块的总建筑面积 172,389.96 ㎡
# （一标段是 86,639.905 ㎡），页面没有任何提示，照着写入概算规模翻倍。

# 测试项目的原名：带内部序号「7.」和资料说明括注
LOT1_PROJECT = "7.北苑街道国贸大道与丹溪北路交叉口西北侧地块房地产项目一标段（软件+清单）"
SCOPE_CODE = "scope_whole_site_suspect"


def _extract_with_total(monkeypatch, *, source: str, quote: str, project_name=None) -> dict:
    """一份文件：原文 source，模型抄回的总建筑面积引文是 quote（数值 172389.96）。"""
    _stub_chain(monkeypatch, [source],
                [_ans(cells={"经济技术指标!D4": {"value": "43783.70", "quote": "总用地面积 43783.70"}},
                      checks={"gross_building_area": [{"value": "172389.96", "quote": quote}]})])
    body = {"files": _files(1)}
    if project_name is not None:
        body["project_name"] = project_name
    r = client.post("/engine/estimate/extract", headers=HEADERS, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _scope_warnings(body: dict) -> list[dict]:
    return [w for w in body["warnings"] if w.get("code") == SCOPE_CODE]


def test_extract_scope_lot_project_with_unattributed_total_warns(monkeypatch):
    """项目名带「一标段」，总建筑面积的引文里没有标段字样 → scope_whole_site_suspect（实测 ZJ-C04 的形状）。"""
    src = "总用地面积 43783.70 ㎡\n总建筑面积 172389.96 ㎡\n地上总建筑面积 113089.96 ㎡"
    body = _extract_with_total(monkeypatch, source=src, quote="总建筑面积 172389.96 ㎡",
                               project_name=LOT1_PROJECT)
    # 前置：引文真在原文里（核验过），下面的告警不是因为引文没核验上才出的
    assert body["check_values"][0]["verification"]["quote_in_source"] is True
    assert body["scope"] == {"project_lot": 1, "lot_source": "project_name"}
    ws = _scope_warnings(body)
    assert len(ws) == 1, body["warnings"]
    w = ws[0]
    assert w["cell"] is None
    assert "「一标段」" in w["message"] and "172,389.96" in w["message"], w["message"]
    assert "分标段资料" in w["message"]
    # 前端黄条与第 5 步自查直接读这两个键，不从文案里抠
    assert w["lot_label"] == "一标段" and w["values"] == [172389.96]
    # 只是提示：候选照出、一条都不少，也不改 needs_manual（铁律 2）
    assert [c["cell"] for c in body["candidates"]] == ["经济技术指标!D4"]
    assert all(c["needs_manual"] is True for c in body["candidates"])
    # spec I-3.1：新加的键同样不许带金额味道（test_extract_response_has_no_money_field 的请求不带项目名，扫不到它们）
    keys = []
    _walk_keys({"scope": body["scope"], "w": w}, keys)
    assert [k for k in keys if MONEY_KEY.search(k)] == []


def test_extract_scope_project_without_lot_does_not_warn(monkeypatch):
    """项目名没有标段 → 不出这条告警，scope.project_lot 为 null。"""
    body = _extract_with_total(monkeypatch, source="总建筑面积 172389.96 ㎡",
                               quote="总建筑面积 172389.96 ㎡",
                               project_name="北苑街道国贸大道与丹溪北路交叉口西北侧地块房地产项目（软件+清单）")
    assert body["scope"] == {"project_lot": None, "lot_source": None}
    assert _scope_warnings(body) == []


def test_extract_scope_total_quote_names_the_lot_does_not_warn(monkeypatch):
    """总建筑面积的引文里写着「一标段」（分标段资料）→ 不出这条告警。"""
    src = "一标段总建筑面积 172389.96 ㎡"
    body = _extract_with_total(monkeypatch, source=src, quote="一标段总建筑面积 172389.96 ㎡",
                               project_name=LOT1_PROJECT)
    assert body["check_values"][0]["verification"]["quote_in_source"] is True
    assert body["scope"]["project_lot"] == 1
    assert _scope_warnings(body) == []


def test_extract_scope_lot_written_differently_still_matches(monkeypatch):
    """项目名写「第1标段」、引文写「一标段」：按标段号比，不按字面比。"""
    body = _extract_with_total(monkeypatch, source="一标段总建筑面积 172389.96 ㎡",
                               quote="一标段总建筑面积 172389.96 ㎡", project_name="某地块项目第1标段")
    assert body["scope"]["project_lot"] == 1
    assert _scope_warnings(body) == []


def test_extract_scope_total_quote_names_another_lot_warns(monkeypatch):
    """引文写的是「二标段」，本项目是一标段 → 照样提示（这不是本标段的数）。"""
    body = _extract_with_total(monkeypatch, source="二标段总建筑面积 172389.96 ㎡",
                               quote="二标段总建筑面积 172389.96 ㎡", project_name=LOT1_PROJECT)
    assert len(_scope_warnings(body)) == 1


def test_extract_scope_lot_in_a_quote_not_found_in_source_does_not_count(monkeypatch):
    """模型抄回的引文带「一标段」，可原文里没有这句（引文核验不过）→ 不算标段归属，照样提示。

    标段归属只认核验过的引文：模型编一句「一标段总建筑面积…」就能把提示压掉，等于没有提示。
    """
    body = _extract_with_total(monkeypatch, source="总建筑面积 172389.96 ㎡",
                               quote="一标段总建筑面积 172389.96 ㎡", project_name=LOT1_PROJECT)
    assert body["check_values"][0]["verification"]["quote_in_source"] is False
    assert len(_scope_warnings(body)) == 1


def test_extract_scope_old_java_without_project_name(monkeypatch):
    """老 Java 不发 project_name：scope 照出（project_lot 为 null），不出告警，抽取照常。"""
    body = _extract_with_total(monkeypatch, source="总建筑面积 172389.96 ㎡", quote="总建筑面积 172389.96 ㎡")
    assert body["scope"] == {"project_lot": None, "lot_source": None}
    assert _scope_warnings(body) == []
    assert body["candidates"]


def test_extract_scope_lot_project_without_any_total_does_not_warn(monkeypatch):
    """原文没给总建筑面积：没有可以点名的总量，本片不判（逐格的标段归属归 WS29-e）。"""
    _stub_chain(monkeypatch, ["总用地面积 43783.70 ㎡"],
                [_ans(cells={"经济技术指标!D4": {"value": "43783.70", "quote": "总用地面积 43783.70 ㎡"}})])
    body = client.post("/engine/estimate/extract", headers=HEADERS,
                       json={"files": _files(1), "project_name": LOT1_PROJECT}).json()
    assert body["scope"] == {"project_lot": 1, "lot_source": "project_name"}
    assert _scope_warnings(body) == []


def test_extract_scope_names_each_unattributed_total_once(monkeypatch):
    """两份文件：一份给全地块总量、一份给一标段总量 → 只点名没有标段归属的那个数。"""
    _stub_chain(monkeypatch, ["总建筑面积 172389.96 ㎡", "一标段总建筑面积 86639.905 ㎡"],
                [_ans(checks={"gross_building_area": [{"value": "172389.96", "quote": "总建筑面积 172389.96 ㎡"}]}),
                 _ans(checks={"gross_building_area": [{"value": "86639.905",
                                                       "quote": "一标段总建筑面积 86639.905 ㎡"}]})])
    body = client.post("/engine/estimate/extract", headers=HEADERS,
                       json={"files": _files(2), "project_name": LOT1_PROJECT}).json()
    ws = _scope_warnings(body)
    assert len(ws) == 1
    assert ws[0]["values"] == [172389.96]
    assert "172,389.96" in ws[0]["message"] and "86,639.905" not in ws[0]["message"]


# ------------------------------------------------------------------ extract：同内容只读一份（WS29-p，issue #970）
# 夹具是落在 FILE_ROOT 里的真文件（去重按原件字节算 sha256，桩 load_document_text 够不到这一步）；只打桩模型。

_DUP_DIR = "_engine_test/estimate_dedupe"
_DUP_TEXT = "项目概况：用地面积 12000 平方米。A区地下室建筑面积 3000 平方米。"


@pytest.fixture
def put_file():
    import shutil

    root = endpoint.ROOT / _DUP_DIR   # zt 改动：文件落在转接的临时项目目录
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    def _put(rel: str, content: bytes, *, display_path: str | None = None, sidecar: str | None = None) -> dict:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        if sidecar is not None:
            (p.parent / f"{p.name}.ocr.txt").write_text(sidecar, encoding="utf-8")
        ref = {"file_id": rel, "rel_path": f"{_DUP_DIR}/{rel}", "file_name": p.name}
        if display_path:
            ref["display_path"] = display_path
        return ref

    yield _put
    shutil.rmtree(root, ignore_errors=True)


def _counting_llm(monkeypatch) -> list[str]:
    seen: list[str] = []

    def fake_chat(messages, **kw):
        seen.append(messages[-1]["content"])
        return json.dumps(_ans(cells={"经济技术指标!D4": {"value": "12000", "quote": "用地面积 12000 平方米"}},
                               buildings=[{"name": "A区地下室", "level": "underground", "area": "3000",
                                           "quote": "A区地下室建筑面积 3000 平方米"}]),
                          ensure_ascii=False), _FakeUsage()

    monkeypatch.setattr(endpoint, "AGENT", fake_chat)
    return seen


def _dups(body) -> list[dict]:
    return [w for w in body["warnings"] if w["code"] == "source_file_duplicate"]


def test_extract_same_bytes_different_names_calls_model_once(put_file, monkeypatch):
    seen = _counting_llm(monkeypatch)
    raw = _DUP_TEXT.encode("utf-8")
    files = [put_file("建施说明.txt", raw), put_file("建施说明-副本.txt", raw)]
    r = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": files})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(seen) == 1, "两份字节相同的说明只调一次模型"
    assert [(w["level"], w["message"]) for w in _dups(body)] == [
        ("info", "「建施说明.txt」与「建施说明-副本.txt」内容相同，只按「建施说明.txt」抽取")]
    cells = [c["cell"] for c in body["candidates"]]
    assert "经济技术指标!D4" in cells and len(cells) == len(set(cells))
    assert {c["source_file_id"] for c in body["candidates"]} == {"建施说明.txt"}
    assert len(body["buildings"]) == 1, "单体不按两份原文各出一遍"
    assert not [u for u in body["unresolved"] if u["reason"] == "no_text"]
    assert len(body["text_stats"]) == 1


def test_extract_same_name_different_content_not_merged(put_file, monkeypatch):
    seen = _counting_llm(monkeypatch)
    files = [put_file("1.资料/建施说明.txt", _DUP_TEXT.encode("utf-8")),
             put_file("建施说明.txt", (_DUP_TEXT + "（修改版）").encode("utf-8"))]
    body = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": files}).json()
    assert len(seen) == 2 and not _dups(body)


def test_extract_two_of_three_identical_reads_two(put_file, monkeypatch):
    seen = _counting_llm(monkeypatch)
    raw = _DUP_TEXT.encode("utf-8")
    files = [put_file("1.资料/建施说明.txt", raw, display_path="/1.资料/建施说明.txt"),
             put_file("结构说明.txt", "结构说明：地下一层。".encode("utf-8")),
             put_file("建施说明.txt", raw, display_path="/建施说明.txt")]
    body = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": files}).json()
    assert len(seen) == 2
    assert [w["message"] for w in _dups(body)] == [
        "「/1.资料/建施说明.txt」与「/建施说明.txt」内容相同，只按「/1.资料/建施说明.txt」抽取"]


def test_extract_unreadable_first_copy_falls_back_to_the_copy_with_a_sidecar(put_file, monkeypatch):
    """字节相同的扫描件，只有后一份旁边有 OCR 旁车：读后一份，前一份不报「取不到正文」。"""
    from pypdf import PdfWriter

    from tests.textextract import ws04_fixtures as fx

    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    pdf = fx.to_bytes(w)
    seen = _counting_llm(monkeypatch)
    files = [put_file("扫描说明.pdf", pdf),
             put_file("旁车/扫描说明.pdf", pdf, sidecar=fx.paged_sidecar([("ok", [_DUP_TEXT])], name="扫描说明.pdf"))]
    r = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": files})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(seen) == 1 and "用地面积 12000 平方米" in seen[0]
    assert not [u for u in body["unresolved"] if u["reason"] == "no_text"]
    assert [w["message"] for w in _dups(body)] == [
        "「扫描说明.pdf（第 2 份）」与「扫描说明.pdf（第 1 份）」内容相同，只按「扫描说明.pdf（第 2 份）」抽取"]
    assert body["candidates"][0]["text_source"] == "ocr_sidecar"


def test_extract_all_copies_unreadable_each_reports_no_text(put_file, monkeypatch):
    seen = _counting_llm(monkeypatch)
    files = [put_file("空.txt", b""), put_file("空-副本.txt", b""), put_file("说明.txt", _DUP_TEXT.encode("utf-8"))]
    body = client.post("/engine/estimate/extract", headers=HEADERS, json={"files": files}).json()
    assert len(seen) == 1 and not _dups(body)
    assert sorted(u["source_file_id"] for u in body["unresolved"] if u["reason"] == "no_text") == ["空-副本.txt", "空.txt"]


@pytest.mark.parametrize("raw,expect", [
    ("12000", 12000.0),
    ("12,000", 12000.0),
    ("1.2万", 12000.0),
    ("1.2 万", 12000.0),
    ("约 12000㎡（含地下 3000㎡）", 12000.0),
    (12000, 12000.0),
    ("一万二", None),
    ("", None),
    (None, None),
    (True, None),          # bool 是 int 子类，必须显式挡掉
])
def test_parse_quantity_is_deterministic(raw, expect):
    assert estimate_extract.parse_quantity(raw) == expect


# ------------------------------------------------------------------ compute

def test_compute_rejects_missing_required_input():
    """spec I-3.1 验收判据②：compute 拒绝缺失必填输入。"""
    inputs = _full_inputs()
    inputs.pop("经济技术指标!D7")
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": inputs, "render": False})
    assert r.status_code == 422
    assert "缺少必填输入位" in r.json()["detail"]
    assert "经济技术指标!D7" in r.json()["detail"]


def test_compute_rejects_empty_inputs():
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": {}, "render": False})
    assert r.status_code == 422
    detail = r.json()["detail"]
    for c in REQUIRED_11:
        assert c in detail


def test_compute_ok_returns_7_totals_and_17_indicators():
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": _full_inputs(), "render": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["totals"]) == {
        "project_cost", "other_cost", "reserve_fee", "static_total",
        "financing_fee", "initial_working_capital", "dynamic_total",
    }
    assert body["totals"]["project_cost"]["cell"] == "估概算总表!C5"
    # 实测 17 行（经济技术指标 role=row 的行数），不是 11（那是输入位个数）
    assert len(body["indicators"]) == 17
    assert body["xlsx_base64"] is None          # render=false


def test_compute_rate_1_percent_passes_with_warning_only():
    """铁律 7：预备费率不设硬闸 —— 1% 必须能算出结果，只出 warning。"""
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": _full_inputs(), "rates": {"reserve_rate": 0.01},
                          "render": False})
    assert r.status_code == 200
    body = r.json()
    codes = [w["code"] for w in body["warnings"]]
    assert "rate_out_of_range" in codes
    # #130：响应必须回本次生效费率，Java 审计据此落 ratesUsed
    assert body["rates_used"] == {"reserve_rate": 0.01}


def test_compute_unknown_rate_key_is_disclosed_not_silent():
    """#130：rates 未知键不再静默回落——unknown_rate warning + rates_used 落默认生效值。
    这是审计失真的现场：入参写 1%，实际按默认 5% 算。"""
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": _full_inputs(), "rates": {"reserveRate": 0.01},
                          "render": False})
    assert r.status_code == 200
    body = r.json()
    unknown = [w for w in body["warnings"] if w["code"] == "unknown_rate"]
    assert unknown and unknown[0]["cell"] == "reserveRate"
    assert body["rates_used"] == {"reserve_rate": 0.05}, "落的必须是生效值（默认 5%），不是入参"


@pytest.mark.parametrize("bad", ["一万二", "12000", True, False, None, [1], {"a": 1}])
def test_compute_non_numeric_input_is_422(bad):
    """契约 §5.2：inputs 值非数值（**含 bool**）→ 422。

    ⚠ 回归钉：inputs 曾声明为 `dict[str, float]`，实测 pydantic 会把 JSON `true`
    静默转成 1.0、把 "12000" 静默转成 12000.0 —— 根输入位吃进一个由 bool 变来的
    1.0，下游 500 多个格全错且零告警。现声明 Any + 引擎严格校验。
    """
    inputs = _full_inputs()
    inputs["经济技术指标!D4"] = bad
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": inputs, "render": False})
    assert r.status_code == 422, f"{bad!r} 被静默接受了：{r.text[:200]}"


@pytest.mark.parametrize("bad", ["5%", True, None])
def test_compute_non_numeric_rate_is_422(bad):
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": _full_inputs(), "rates": {"reserve_rate": bad},
                          "render": False})
    assert r.status_code == 422, f"费率 {bad!r} 被静默接受了：{r.text[:200]}"


def test_compute_accepts_int_and_float():
    """整数 JSON 字面量（Java 侧 12000 而不是 12000.0）必须照收。"""
    inputs = {c: 1000 for c in REQUIRED_11}
    inputs[ONE_COST_CELL] = 1              # 整数字面量，且避开全零闸
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": inputs, "render": False})
    assert r.status_code == 200, r.text
    assert r.json()["indicators"][0]["value"] == 1000.0


def test_compute_unknown_template_is_422():
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": _full_inputs(), "template_code": "no_such_tpl",
                          "render": False})
    assert r.status_code == 422


def test_compute_render_true_without_renderer_is_501_not_silent_null():
    """I-2.6 渲染器未落地时：必须显式 501，不许 200+xlsx_base64=null 糊弄调用方。

    ⚠ 本用例会随 app/engine/estimate_render.py 落地而自动切换到 200 分支 ——
    那时它验证的是"渲染器在位则出 base64"，两种断言都写在这里，不留悬空。
    """
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": _full_inputs(), "render": True})
    try:
        import zt.estimate.render  # noqa: F401
        has_renderer = True
    except ImportError:
        has_renderer = False
    if has_renderer:
        assert r.status_code == 200 and r.json()["xlsx_base64"]
    else:
        assert r.status_code == 501
        assert "estimate_render" in r.json()["detail"]


# ------------------------------------------------------------------ template

def test_template_is_trimmed_and_drives_form():
    r = client.get("/engine/estimate/template", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["template_code"] == "gsyz_v1"
    assert "formulas" not in body, "515 条公式不下发（前端不求值）"
    assert len(body["inputs"]) == 211
    assert len(body["optional_inputs"]) == 4
    assert len(body["sheets"]) == 9
    assert body["required_inputs"] == REQUIRED_11
    assert "reserve_rate" in body["rate_params"]
    assert body["rate_params"]["reserve_rate"]["soft_range"] == [0.03, 0.08]
    assert {f["id"] for f in body["fixes"]} == {
        "F30_wrong_ref", "sentinel_sum_inclusion", "seq_rebuild",
        "static_text_fixes"}   # WS10-P14：占位符 / 错别字 / 单位的 static 修正


def test_template_required_inputs_match_compute_gate():
    """模板端点公布的必填位 = compute 实际卡的必填位，同一来源函数，不许漂移。"""
    body = client.get("/engine/estimate/template", headers=HEADERS).json()
    assert body["required_inputs"] == estimate_api._required_input_cells("gsyz_v1")


def test_template_editable_marks_input_cells_on_right_column():
    body = client.get("/engine/estimate/template", headers=HEADERS).json()
    tech = next(s for s in body["sheets"] if s["name"] == "经济技术指标")
    row4 = next(r for r in tech["rows"] if r["row"] == 4)
    assert row4["editable"] is True
    assert [c["cell"] for c in row4["input_cells"]] == ["经济技术指标!D4"]
    assert row4["input_kind"] == "quantity"
    # 表头行不可编辑
    row3 = next(r for r in tech["rows"] if r["row"] == 3)
    assert row3["editable"] is False and row3["input_cells"] == []
    # 一行两个输入格（估概算总表 行 48：C48 融资费用 + D48 其单方指标）
    summary = next(s for s in body["sheets"] if s["name"] == "估概算总表")
    row48 = next(r for r in summary["rows"] if r["row"] == 48)
    assert [c["col"] for c in row48["input_cells"]] == ["C", "D"]
    assert all(c["optional"] for c in row48["input_cells"])


def test_template_seq_is_string_never_float():
    """DDL 教训：seq 是 varchar，1.10 当数字会塌缩成 1.1 与真正的 1.1 重号。"""
    body = client.get("/engine/estimate/template", headers=HEADERS).json()
    for s in body["sheets"]:
        for r in s["rows"]:
            assert r["seq"] is None or isinstance(r["seq"], str)


def test_template_response_is_not_shared_mutable_cache():
    a = client.get("/engine/estimate/template", headers=HEADERS).json()
    cached = estimate_api._template_payload("gsyz_v1")
    a["sheets"][0]["rows"][0]["label"] = "被调用方改坏了"
    assert cached["sheets"][0]["rows"][0]["label"] != "被调用方改坏了"


def test_template_unknown_code_is_422():
    r = client.get("/engine/estimate/template", headers=HEADERS,
                   params={"template_code": "no_such_tpl"})
    assert r.status_code == 422


# ------------------------------------------------- 可选输入位（对抗复核 #5/#9 的端点侧）
#
# 缺陷复现（修复前实测）：只提交 11 个根输入位跑 compute，返回
#   financing_fee.value=None / initial_working_capital.value=None
#   static_total.value=0.0  == dynamic_total.value=0.0
# 且 warnings 里只有 div_by_zero / template_fix —— 「建设动态总投资（七）」恒等于
# 「建设静态总投资（四）」而**毫无提示**。对造价员这是静默的错误合计，不是缺失提示。
# 下面几条把「必须出声」和「前端必须拿得到录入元数据」钉死。

OPTIONAL_4 = [
    "估概算总表!C48", "估概算总表!C49", "估概算总表!D48", "估概算总表!D49",
]


def test_compute_warns_when_optional_dynamic_inputs_missing():
    """只填 11 个必填位 → 4 个可选位全未填 → 必须逐个出 optional_input_missing。"""
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": _full_inputs(), "render": False})
    assert r.status_code == 200, r.text
    body = r.json()
    missing = [w for w in body["warnings"] if w["code"] == "optional_input_missing"]
    assert sorted(w["cell"] for w in missing) == sorted(OPTIONAL_4)

    # 静默的证据仍在（合计确实相等），所以 warning 是唯一的告知通道
    assert body["totals"]["dynamic_total"]["value"] == body["totals"]["static_total"]["value"]

    # 文案必须点名「被静默污染的是哪个合计」，否则造价员看不出严重性
    c48 = next(w for w in missing if w["cell"] == "估概算总表!C48")
    assert "建设期融资费用" in c48["message"]
    assert "估概算总表!C50" in c48["message"]


def test_compute_no_optional_warning_once_supplied():
    """补填之后不再刷 warning —— 提示必须能被消掉，否则等于常亮噪声。"""
    inputs = _full_inputs()
    inputs.update({c: 100.0 for c in OPTIONAL_4})
    body = client.post("/engine/estimate/compute", headers=HEADERS,
                       json={"inputs": inputs, "render": False}).json()
    assert [w for w in body["warnings"] if w["code"] == "optional_input_missing"] == []
    # 补填后动态总投资确实高于静态总投资（C50 = C47+C48+C49）
    assert body["totals"]["dynamic_total"]["value"] > body["totals"]["static_total"]["value"]


def test_compute_optional_warning_is_per_cell_not_all_or_nothing():
    """只补 C48 时，剩下 3 个仍要各自报 —— 不许一个填了就整体噤声。"""
    inputs = _full_inputs()
    inputs["估概算总表!C48"] = 88.0
    body = client.post("/engine/estimate/compute", headers=HEADERS,
                       json={"inputs": inputs, "render": False}).json()
    cells = sorted(w["cell"] for w in body["warnings"]
                   if w["code"] == "optional_input_missing")
    assert cells == ["估概算总表!C49", "估概算总表!D48", "估概算总表!D49"]


def test_optional_input_impact_comes_from_the_evaluator_ast():
    """影响面必须与求值器同源（实测：C48→C50/G48，D48→D50），不是硬编码。"""
    impact = estimate_api._optional_input_impact("gsyz_v1")
    assert set(impact) == set(OPTIONAL_4)
    assert impact["估概算总表!C48"] == ("估概算总表!C50", "估概算总表!G48")
    assert impact["估概算总表!C49"] == ("估概算总表!C50", "估概算总表!G49")
    assert impact["估概算总表!D48"] == ("估概算总表!D50",)
    assert impact["估概算总表!D49"] == ("估概算总表!D50",)


def test_template_optional_inputs_carry_label_and_unit():
    """前端要给这 4 个位配录入控件，光有格号配不出来 —— label/unit/量纲必须下发。

    ⚠ 量纲按该表**自己的表头**实测：C=费用（万元）、D=占总投资比例（%）。
    「单方指标（元/x）」是 G 列，不是 D 列。
    """
    body = client.get("/engine/estimate/template", headers=HEADERS).json()
    specs = {s["cell"]: s for s in body["optional_input_specs"]}
    assert sorted(specs) == sorted(OPTIONAL_4)

    c48 = specs["估概算总表!C48"]
    assert c48["label"] == "建设期融资费用"
    assert c48["unit"] == "万元"
    assert c48["col"] == "C" and c48["row"] == 48 and c48["seq"] == "五"
    assert c48["optional"] is True
    assert {a["cell"] for a in c48["affects"]} == {"估概算总表!C50", "估概算总表!G48"}
    assert any(a["label"] == "建设动态总投资（四+五+六）" for a in c48["affects"])

    d48 = specs["估概算总表!D48"]
    assert d48["label"] == "建设期融资费用"
    assert d48["unit"] == "%"          # 占总投资比例，不是单方指标
    assert specs["估概算总表!C49"]["label"] == "铺底流动资金"
    assert specs["估概算总表!D49"]["unit"] == "%"

    # optional_inputs 仍是契约 §3.4 钉死的字符串数组，形状不许变
    assert body["optional_inputs"] == OPTIONAL_4


def test_template_row48_input_cells_have_distinct_units():
    """一行两格且量纲不同：C48 万元 / D48 % —— input_cells 必须分别标对。"""
    body = client.get("/engine/estimate/template", headers=HEADERS).json()
    summary = next(s for s in body["sheets"] if s["name"] == "估概算总表")
    row48 = next(r for r in summary["rows"] if r["row"] == 48)
    by_col = {c["col"]: c for c in row48["input_cells"]}
    assert by_col["C"]["unit"] == "万元" and by_col["D"]["unit"] == "%"
    assert by_col["C"]["label"] == by_col["D"]["label"] == "建设期融资费用"
    assert "费用" in by_col["C"]["column_label"]
    assert "占总投资比例" in by_col["D"]["column_label"]


# ------------------------------------------- 比值位的标度契约（O-10 · 对抗复核第 2 轮）
#
# 缺陷复现（修复前实测，见 commit 正文）：估概算总表 D 列列头写「占总投资比例（%）」，
# 而同列 D45/D46/D47 全是 `=Cn/C50` 的**小数**（0.00% 只是显示格式），且
# `D50=D47+D48+D49`。前端第 1 轮补了 %→小数换算，但那 100 倍换算最终只靠前端对
# `unit` 做 `=== "%"` 的**推断**在守 —— 引擎既不下发 value_scale
# （`_optional_input_specs` 里 4 条 spec 一个 value_scale 键都没有），
# 也不对比值位做任何量级告警：直接打 API 传 D48=3.0 → D50=5.99（599%），
# 端点 200，warnings 与传 0.03 时**完全相同**（都只有一条 template_fix）。
#
# 修完这里守两件事：① spec 里有 value_scale，前端不必再猜；② 引擎自己也有哨兵，
# 不读 spec 的调用方（含前端的裸格号退化路径）照样会被点名。


def test_optional_input_specs_declare_value_scale():
    """4 条 spec 都必须带 value_scale：D 列是 fraction，C 列是 absolute。

    前端 `isPercentScaleSpec` 写的是「引擎给了 value_scale 就按引擎的，
    没给就退到 unit === '%' 这个推断」—— 不下发这一键，那句话在实现上取不到值。
    """
    body = client.get("/engine/estimate/template", headers=HEADERS).json()
    specs = {s["cell"]: s for s in body["optional_input_specs"]}
    assert sorted(specs) == sorted(OPTIONAL_4)
    for cell in OPTIONAL_4:
        assert "value_scale" in specs[cell], f"{cell} 的 spec 没有 value_scale 键"
    assert specs["估概算总表!D48"]["value_scale"] == "fraction"
    assert specs["估概算总表!D49"]["value_scale"] == "fraction"
    assert specs["估概算总表!C48"]["value_scale"] == "absolute"
    assert specs["估概算总表!C49"]["value_scale"] == "absolute"


def test_value_scale_comes_from_the_column_header_not_from_the_cell_address():
    """判据是列头量纲，不是格号 —— 硬编码 "D48"/"D49" 换个模板就静默失效，
    而失效的表现是数字差 100 倍且没有任何提示。

    同时钉住覆盖面：value_scale 覆盖**已声明的全部输入位**（必填 211 + 可选 4），
    而不只是那 4 个可选位；今天 211 个必填位里一个比值列都没有，是实测结论不是假设。
    """
    scales = estimate_api._input_value_scales("gsyz_v1")
    tpl = estimate_api.load_template("gsyz_v1")
    assert len(scales) == len(tpl["inputs"]) + len(tpl["optional_inputs"])
    frac = sorted(c for c, v in scales.items() if v == "fraction")
    assert frac == ["估概算总表!D48", "估概算总表!D49"], frac

    # 同源性：凡判成 fraction 的，其列头量纲必须真的是百分号/千分号
    for cell in frac:
        sheet_name, col, _row = estimate_api._split_cell(cell)
        sheet = next(s for s in tpl["sheets"] if s["name"] == sheet_name)
        assert estimate_api._column_units(sheet)[col] in ("%", "％", "‰")


def test_compute_warns_when_a_ratio_cell_gets_a_percent_number():
    """照列头填 D48=3（想表达 3%）→ 必须出 ratio_scale_suspect，且照算不拦截。

    「照算不拦截」是刻意的（铁律 7 同一条纪律，与 O-06 的 fee_base_magnitude_suspect
    对齐）：引擎不替造价员断定「占总投资比例 > 100%」不可能，只是把这件事说出来。
    """
    inputs = _full_inputs()
    inputs.update({"估概算总表!C48": 500.0, "估概算总表!C49": 300.0,
                   "估概算总表!D48": 3.0, "估概算总表!D49": 2.0})
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": inputs, "render": False})
    assert r.status_code == 200, r.text          # 哨兵不设硬闸
    body = r.json()
    suspect = [w for w in body["warnings"] if w["code"] == "ratio_scale_suspect"]
    assert sorted(w["cell"] for w in suspect) == ["估概算总表!D48", "估概算总表!D49"]
    msg = next(w for w in suspect if w["cell"] == "估概算总表!D48")["message"]
    assert "0.03" in msg, f"告警得说清楚该传什么：{msg}"
    assert "300%" in msg, f"告警得说清楚现在算成了什么：{msg}"


def test_compute_is_silent_when_the_ratio_cells_are_already_fractions():
    """按小数填（D48=0.03）不许刷告警 —— 常亮的哨兵等于没有哨兵。"""
    inputs = _full_inputs()
    inputs.update({"估概算总表!C48": 500.0, "估概算总表!C49": 300.0,
                   "估概算总表!D48": 0.03, "估概算总表!D49": 0.02})
    body = client.post("/engine/estimate/compute", headers=HEADERS,
                       json={"inputs": inputs, "render": False}).json()
    assert [w for w in body["warnings"] if w["code"] == "ratio_scale_suspect"] == []


def test_the_ratio_sentinel_is_not_fired_by_the_money_columns():
    """C48/C49 填成 500/300 万元是完全正常的输入，绝不能被哨兵当成标度错误。

    没有这条，把哨兵写成「任何 > 1 的输入都报」也能让上面那条全绿 ——
    而那会让每一次正常求值都刷 200 多条噪声。
    """
    inputs = _full_inputs()
    inputs.update({"估概算总表!C48": 500.0, "估概算总表!C49": 300.0})
    body = client.post("/engine/estimate/compute", headers=HEADERS,
                       json={"inputs": inputs, "render": False}).json()
    assert [w for w in body["warnings"] if w["code"] == "ratio_scale_suspect"] == []


def test_ratio_sentinel_survives_dollar_signs_and_non_numeric_values():
    """`$C$48` 这种带绝对引用符的键与非数值都不许把哨兵搞崩（端点别的地方也这么规范化）。"""
    assert estimate_api._ratio_scale_warnings(
        "gsyz_v1", {"估概算总表!$D$48": 3.0}) != []
    assert estimate_api._ratio_scale_warnings(
        "gsyz_v1", {"估概算总表!D48": "三个点"}) == []
    assert estimate_api._ratio_scale_warnings("gsyz_v1", None) == []


def test_template_optional_specs_not_shared_mutable_cache():
    a = client.get("/engine/estimate/template", headers=HEADERS).json()
    a["optional_input_specs"][0]["affects"].append({"cell": "污染", "label": "污染"})
    fresh = client.get("/engine/estimate/template", headers=HEADERS).json()
    assert all(x["cell"] != "污染" for x in fresh["optional_input_specs"][0]["affects"])


# ------------------------------------------------------------------ suggest
#
# 对抗复核 #6 的端点侧：契约 §3.2 的 /engine/estimate/suggest **此前根本不存在**，
# §3.5 的 Java /estimate/suggest 也不存在 —— 也就是说，就算前端把 feeBases/feeAttrs
# 传出来，链路上也没有任何一环会去算那 16 条费率规则，fee[] 必然为空，
# 前端第 6 组（5.工程建设其他费用 的 13 个 write_target=input 费用位）恒不渲染。
#
# 下面这组用例钉的是：端点存在、fee_bases/fee_attrs 被**真正消费**、
# 以及缺失依赖时报 501 而不是 200+空 fee[]（空结果对造价员是误导性成功）。

SUGGEST_MOD = "zt.estimate.suggest"
FEE_MOD = "zt.estimate.fee_rules"


def _fake_suggest_module(calls: dict, *, accepts_items: bool = True):
    """伪造引擎泳道的 estimate_suggest（该模块不在本分支，属并行泳道）。"""
    mod = types.ModuleType(SUGGEST_MOD)
    if accepts_items:
        def suggest(inputs, baselines, fee_items=None, template_code="gsyz_v1",
                    dims=None, *, items=None, tolerance=0.20):
            calls["suggest"] = dict(inputs=inputs, baselines=baselines,
                                    fee_items=fee_items, template_code=template_code,
                                    dims=dims, items=items)
            return _suggest_payload(fee_items)
    else:
        def suggest(inputs, baselines, fee_items=None, template_code="gsyz_v1", dims=None):
            calls["suggest"] = dict(inputs=inputs, baselines=baselines,
                                    fee_items=fee_items, template_code=template_code,
                                    dims=dims)
            return _suggest_payload(fee_items)
    mod.suggest = suggest
    return mod


def _suggest_payload(fee_items):
    return {
        "suggestions": [{"cell": "1.建筑工程费!C7", "suggested_cost": 641.98, "editable": True}],
        "unresolved": [],
        "fee": list(fee_items or []),
        "coverage": {"cost_inputs": 150, "suggested": 1, "unresolved": 0, "rate": 0.01},
        "warnings": [],
    }


def _fake_fee_module(calls: dict):
    mod = types.ModuleType(FEE_MOD)

    def suggest_all(bases, attrs=None, ruleset="fee_rules_zj2018"):
        calls["fee"] = dict(bases=bases, attrs=attrs, ruleset=ruleset)
        return {
            "items": [{"item_id": "supervision_fee", "fee_name": "工程监理费",
                       "target_cell": "5.工程建设其他费用!C14", "write_target": "input",
                       "suggested": 128.4, "editable": True}],
            "warnings": [{"code": "fee_rules_unsigned", "cell": None,
                          "message": "费率数据未经造价员签署"}],
        }

    mod.suggest_all = suggest_all
    return mod


def _install(monkeypatch, **mods):
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)


def test_suggest_feeds_fee_bases_and_fee_attrs_into_fee_rules(monkeypatch):
    """核心回归：fee_bases/fee_attrs 必须一路传到费率引擎，且产物并进 fee[]。

    这正是原缺陷的形状 —— 参数在签名里声明了，却没有任何一环真的传/用它。
    """
    calls: dict = {}
    _install(monkeypatch, **{SUGGEST_MOD: _fake_suggest_module(calls),
                             FEE_MOD: _fake_fee_module(calls)})
    r = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "inputs": _full_inputs(),
        "baselines": [{"indicator_code": "GSYZ-JZ-R07", "unit_cost": 1234.5678}],
        "dims": {"project_type": "房屋建筑", "region": None},
        "fee_bases": {"工程费用": 12000.0},
        "fee_attrs": {"region": "urban"},
    })
    assert r.status_code == 200, r.text

    # 1) 费率引擎确实收到了这两个参数（不是被丢在半路）
    assert calls["fee"]["bases"] == {"工程费用": 12000.0}
    assert calls["fee"]["attrs"] == {"region": "urban"}

    # 2) 费率产物作为 fee_items 传进了 suggest
    assert calls["suggest"]["fee_items"][0]["item_id"] == "supervision_fee"

    # 3) 响应体 fee[] 非空 —— 前端第 6 组才有东西可渲染
    body = r.json()
    assert [f["target_cell"] for f in body["fee"]] == ["5.工程建设其他费用!C14"]
    # 4) 费率引擎自己的 warning 一并透出（如"费率未签署"）
    assert "fee_rules_unsigned" in [w["code"] for w in body["warnings"]]
    # 5) 纯规则端点，零 token


def test_suggest_without_fee_bases_derives_project_cost_from_this_run(monkeypatch):
    """O-06 起口径改了：没传 fee_bases **不再**直接放弃，而是用本次求值的
    工程费用合计（估概算总表!C5）兜底调费率引擎，并出 `fee_base_derived` 说破这件事。

    原口径（fee[] 恒空 + fee_bases_absent）是「二段式时序契约没定义」的后果：
    16 条规则里 7 条以 C5 为基数，而 C5 正是同一步在填的合计，于是前端干脆不传，
    877 行费率求值器一次也不会被真实用户触发。兜底不是猜——C5 就是这次 inputs
    按模板公式算出来的数，与前端自己汇总必然一致。
    """
    calls: dict = {}
    _install(monkeypatch, **{SUGGEST_MOD: _fake_suggest_module(calls),
                             FEE_MOD: _fake_fee_module(calls)})
    body = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "inputs": _full_inputs(), "baselines": [],
    }).json()
    codes = [w["code"] for w in body["warnings"]]
    assert "fee_base_derived" in codes, "引擎替调用方补了基数就必须说破，不许静默"
    assert "fee_bases_absent" not in codes
    assert body["fee"], "兜底成功时 fee[] 不该为空"
    assert calls["fee"]["bases"]["工程费用"] > 0
    derived = [w for w in body["warnings"] if w["code"] == "fee_base_derived"][0]
    assert derived["cell"] == "估概算总表!C5"


def test_suggest_without_fee_bases_and_zero_cost_still_says_why(monkeypatch):
    """成本位一个没填时 C5=0，兜底无从谈起 → 回到 fee_bases_absent。

    这条守的是「别把『还没到时候』伪装成『算过了但没结果』」：拿 0 去调费率引擎
    只会刷出 16 条 fee_base_non_positive，看着像认真算过。
    """
    calls: dict = {}
    _install(monkeypatch, **{SUGGEST_MOD: _fake_suggest_module(calls),
                             FEE_MOD: _fake_fee_module(calls)})
    body = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        # 只有 11 个根输入，150 个成本位一个不填 → C5 = 0
        "inputs": {c: 1000.0 for c in REQUIRED_11}, "baselines": [],
    }).json()
    codes = [w["code"] for w in body["warnings"]]
    assert "fee_bases_absent" in codes
    assert "fee_base_derived" not in codes
    assert body["fee"] == []
    assert "fee" not in calls          # 没基数就不该去调费率引擎
    assert calls["suggest"]["fee_items"] is None


def test_suggest_with_fee_bases_but_no_fee_engine_is_loud_not_silent(monkeypatch):
    """带了 fee_bases 却没有费率引擎 → 主产出照出，缺口用 fee_rules_unavailable 明码点出。
    绝不 200 + fee[] 为空 + 零告警。

    fee_rules.py 实测在 main / feat/fee-rules-w2b / feat/phase-i-engine-core 三条
    分支上都不存在（w2b 只有 fee_rules_zj2018.json 数据，没有模块）。

    ⚠ 本用例原先断言 501（api 泳道口径）。对抗复核第 2 轮 #2 合并两条泳道时改判为
    软降级 + 告警（engine 泳道口径），理由：suggest 的主产出是 150 个成本位的建议
    金额，费率只是第 6 组；契约 §3.5 让前端每次都带 feeBases，若 fee_rules 未合入
    就 501，向导第 3 步整块不渲染 —— 那正是本轮 #1 在修的缺陷形态（150 个成本位
    在全应用里没有录入口），不能一边修一边再造一个。信息不丢：空 fee[] 的原因
    仍由 warning 明确区分（缺基数 fee_bases_absent / 缺引擎 fee_rules_unavailable）。
    """
    calls: dict = {}
    _install(monkeypatch, **{SUGGEST_MOD: _fake_suggest_module(calls)})
    monkeypatch.delitem(sys.modules, FEE_MOD, raising=False)
    r = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "inputs": _full_inputs(), "baselines": [], "fee_bases": {"工程费用": 12000.0},
    })
    try:
        import zt.estimate.fee_rules  # noqa: F401
        has_fee_engine = True
    except ImportError:
        has_fee_engine = False
    assert r.status_code == 200, r.text
    body = r.json()
    if has_fee_engine:
        assert body["fee"]
    else:
        assert body["fee"] == []
        codes = [w["code"] for w in body["warnings"]]
        assert "fee_rules_unavailable" in codes, "空 fee[] 必须说明原因，不许静默"
        # 传了基数就不该再报 fee_bases_absent —— 两种空态的诊断不能串
        assert "fee_bases_absent" not in codes
        assert "suggest" in calls          # 主产出照出，不因旁支缺失被打死


def test_suggest_without_engine_module_is_501_not_200(monkeypatch):
    """estimate_suggest 属引擎泳道，本分支没有 → 501 点名缺什么，不静默回空。"""
    monkeypatch.delitem(sys.modules, SUGGEST_MOD, raising=False)
    r = client.post("/engine/estimate/suggest", headers=HEADERS,
                    json={"inputs": _full_inputs(), "baselines": []})
    try:
        import zt.estimate.suggest  # noqa: F401
        has_engine = True
    except ImportError:
        has_engine = False
    if has_engine:
        assert r.status_code == 200
    else:
        assert r.status_code == 501, r.text
        assert "estimate_suggest" in r.json()["detail"]


def test_suggest_empty_baselines_is_200_with_zero_coverage(monkeypatch):
    """契约 §3.2：baselines 为空数组 → 200（新租户没灌种子是正常态），不是 422。"""
    calls: dict = {}
    _install(monkeypatch, **{SUGGEST_MOD: _fake_suggest_module(calls)})
    r = client.post("/engine/estimate/suggest", headers=HEADERS,
                    json={"inputs": _full_inputs(), "baselines": []})
    assert r.status_code == 200
    assert calls["suggest"]["baselines"] == []
    assert "coverage" in r.json()


def test_suggest_passes_dims_items_and_template_through(monkeypatch):
    calls: dict = {}
    _install(monkeypatch, **{SUGGEST_MOD: _fake_suggest_module(calls)})
    client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "template_code": "gsyz_v1",
        "inputs": _full_inputs(),
        "baselines": [{"item_code": "X"}],
        "items": [{"item_code": "X", "item_name": "多孔砖墙工程", "seq_no": "1.10"}],
        "dims": {"project_type": "房屋建筑"},
    })
    assert calls["suggest"]["template_code"] == "gsyz_v1"
    assert calls["suggest"]["dims"] == {"project_type": "房屋建筑"}
    # seq_no 是 varchar，必须原样是字符串（1.10 塌缩事故）
    assert calls["suggest"]["items"][0]["seq_no"] == "1.10"


def test_suggest_drops_items_with_warning_when_engine_lacks_the_param(monkeypatch):
    """引擎侧若还没补 items 关键字参数：跳过回链并出 warning，不许 TypeError 打成 500。"""
    calls: dict = {}
    _install(monkeypatch,
             **{SUGGEST_MOD: _fake_suggest_module(calls, accepts_items=False)})
    r = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "inputs": _full_inputs(), "baselines": [], "items": [{"item_code": "X"}],
    })
    assert r.status_code == 200, r.text
    assert "items" not in calls["suggest"]
    assert "items_unsupported" in [w["code"] for w in r.json()["warnings"]]


@pytest.mark.skip(reason="zt 没有 HTTP 层与鉴权")
def test_suggest_requires_service_token():
    pass


# ---------------------------------------------------------------- Java 侧真实载荷契约闸
#
# 下面这段 JSON **不是手写的**：它是 Java 端
# 后端/yidu-nas-server/src/test/java/EstimateSuggestChainTest.java 里那台假引擎
# （com.sun.net.httpserver）实际收到的请求体字节，原样抄回来的。
#
# 为什么要在引擎侧再存一份：本轮修的缺陷就是"两侧各自以为对方会传"。Java 侧的测试
# 只能证明"我发出去了"，引擎侧的测试只能证明"我收到就会用"，中间那道缝——**Java 发的
# 形状引擎认不认**——不放一条钉死载荷的用例就永远没人守。Java 侧一旦把键名改成驼峰、
# 把 seq_no 转成数值、或把 null 维度吞掉，这条会立刻转红。

JAVA_WIRE_BODY = json.loads(r"""
{"baselines":[{"item_code":"GSJZ-01-007","project_type":"房屋建筑","structure_type":null,
"indicator_code":"GSYZ-JZ-R07","price_period":null,"item_name":"多孔砖墙工程","source":"gsyz_v1",
"unit":"㎡","source_row":7,"base_metric":"总建筑面积","source_sheet":"1.建筑工程费",
"unit_cost":1234.5678,"region":null}],
"dims":{"project_type":"房屋建筑","structure_type":null,"price_period":null,"region":null},
"operator_id":"10001","inputs":{"经济技术指标!D4":12000,"经济技术指标!D7":8000},
"template_code":"gsyz_v1","sys_company_code":"1",
"fee_attrs":{"voltage_level":"10","region":"urban"},"project_id":"P-A-001",
"fee_bases":{"工程费用":12000},
"items":[{"seq_no":"1.10","item_code":"GSJZ-01-007","chapter":null,"item_level":2,
"denominator_base":null,"item_name":"多孔砖墙工程","unit":"㎡","parent_code":null,
"numerator_base":null,"list_source":"jz"}]}
""")


def test_java_wire_body_is_accepted_and_fee_bases_are_consumed(monkeypatch):
    """Java 实际发出的那段字节，引擎必须原样吃下并把 fee_bases 送进费率引擎。"""
    calls: dict = {}
    _install(monkeypatch, **{SUGGEST_MOD: _fake_suggest_module(calls),
                             FEE_MOD: _fake_fee_module(calls)})
    r = client.post("/engine/estimate/suggest", headers=HEADERS, json=JAVA_WIRE_BODY)
    assert r.status_code == 200, r.text

    # 缺陷本体：费率基数真的到了费率引擎
    assert calls["fee"]["bases"] == {"工程费用": 12000}
    assert calls["fee"]["attrs"] == {"voltage_level": "10", "region": "urban"}
    # 受控词保持字符串——"10" 变 10 会让规则表匹配变成运气
    assert isinstance(calls["fee"]["attrs"]["voltage_level"], str)
    # 产物并进 fee[]，前端第 6 组才渲染得起来
    assert [f["fee_name"] for f in r.json()["fee"]] == ["工程监理费"]

    # 裁决 A：基准/条目由 Java 查库下发，键名是 DDL 真实列名
    got = calls["suggest"]
    assert got["baselines"][0]["source_sheet"] == "1.建筑工程费"
    assert got["baselines"][0]["source_row"] == 7
    # 事故根因回归：seq_no 是 varchar，1.10 不许塌缩成 1.1
    assert got["items"][0]["seq_no"] == "1.10"
    assert isinstance(got["items"][0]["seq_no"], str)
    # 未断言的维度以 null 到达（不是键缺失）——引擎侧的 NULL 通配过滤据此判断
    assert got["dims"] == {"project_type": "房屋建筑", "structure_type": None,
                           "price_period": None, "region": None}


def test_java_wire_body_missing_engine_module_is_501_not_422(monkeypatch):
    """载荷合法性与"模块没合入"必须区分得开。

    422 = Java 发的形状引擎不认（契约破裂，要改 Java）；
    501 = 形状没问题，只是并行泳道的 estimate_suggest 还没合进来（等合入即可）。
    两者混为一谈，排障的人会去改没坏的那一侧。

    ⚠ 第 3 轮合并修正：本用例原写法是 `del sys.modules[SUGGEST_MOD]`。那在 api 泳道
    成立（那条分支上 app/engine/estimate_suggest.py **不存在**），合进 engine 泳道后
    该文件真的在，删缓存只会让 import 重新成功 → 实际 200，用例转红。
    要模拟"模块还没合入"，必须让 import 本身失败，而不是让缓存落空。
    """
    real_import = estimate_api.importlib.import_module

    def _blocked(name, *args, **kwargs):
        if name == SUGGEST_MOD:
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(estimate_api.importlib, "import_module", _blocked)
    r = client.post("/engine/estimate/suggest", headers=HEADERS, json=JAVA_WIRE_BODY)
    assert r.status_code == 501, f"期望 501（模块缺失），实际 {r.status_code}: {r.text}"
    assert "estimate_suggest" in r.text or "推算" in r.text


# ---------------------------------------------- 真 fee_rules 在场的集成用例（O-02）

def test_suggest_with_real_fee_rules_no_stub():
    """**不打桩**：真 fee_rules 在场时走完整条 suggest → fee_rules 链路。

    为什么要一条不打桩的：上面所有费率用例都靠 monkeypatch sys.modules 装假模块，
    而本轮修的恰恰是「打桩失效、端点其实调的是真模块」这一类漏洞（O-02）：
    `from zt.estimate import fee_rules` 会先 getattr 到包属性，把打桩整条绕过。
    打桩用例全绿并不能证明真模块接得上 —— 只有这条能。

    16 条恒齐全是 fee_rules.suggest_all 的既定语义（查不到基数的条目也照样出现，
    带 fee_base_missing 告警）：少一条比给错一条更危险。
    """
    r = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "inputs": _full_inputs(), "baselines": [],
        "fee_bases": {"工程费用": 12000.0},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["fee"]) == 16, \
        f"实际 {len(body['fee'])} 条：{[f['item_id'] for f in body['fee']]}"
    codes = [w["code"] for w in body["warnings"]]
    # 签署状态必须有一条告警透出来（#159 起有两种形态，见下）
    from zt.estimate import fee_rules as _fr
    _doc = _fr._load()
    if _doc["signoff_status"] != "signed":
        assert "fee_rules_unsigned" in codes, "未签署的费率数据必须出告警"
    elif _doc.get("signoff_kind") != "cost_engineer":
        assert "fee_rules_owner_released" in codes, (
            "仓主默认放行（非造价员签署）必须出告警：建议值出来了，"
            "而这批数字没人对图核过 —— 不许因为难看就不说")
    assert "fee_rules_unavailable" not in codes
    assert "fee_bases_absent" not in codes


# ---------------------------------------------- fee_bases 出口三件套（O-06）

def test_suggest_returns_totals_and_required_fee_bases():
    """二段式时序的两个出口必须在响应体里，且能自我描述。

    `totals`：16 条费率规则里 7 条以「工程费用」=估概算总表!C5 为基数，而 C5
    正是第 3 步在填的合计。把它带出来，前端就不必自己重算一遍汇总（重算必漂移）。
    `required_fee_bases`：基数键名与单位此前只活在 fee_rules.BASE_KEYS 常量里，
    调用方无从知道该传什么 —— 实测后果就是从来没人传。
    """
    r = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "inputs": _full_inputs(), "baselines": [],
        "fee_bases": {"工程费用": 12000.0},
    })
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["totals"]["project_cost"]["cell"] == "估概算总表!C5"
    assert body["totals"]["static_total"]["cell"] == "估概算总表!C47"

    specs = body["required_fee_bases"]
    assert len(specs) == 16, f"16 条规则各自的基数需求必须齐全，实得 {len(specs)}"
    for s in specs:
        assert set(("item_id", "base_key", "unit", "satisfied")) <= set(s)
    by_id = {s["item_id"]: s for s in specs}
    # 单位必须逐项下发：万元 / 万m2 / m2 / kVA 混在一起，名字差一个字量纲差 10^4
    assert by_id["supervision_fee"]["unit"] == "万元"
    assert by_id["energy_assessment_fee"]["unit"] == "万m2"
    assert by_id["municipal_infrastructure_fee"]["unit"] == "m2"
    assert by_id["high_reliability_power_fee"]["unit"] == "kVA"
    # satisfied 反映"本次到底传了没"
    assert by_id["supervision_fee"]["satisfied"] is True       # 工程费用 传了
    assert by_id["bidding_agency_fee"]["satisfied"] is False   # 中标金额 没传


def test_suggest_flags_magnitude_suspect_base():
    """量级哨兵：「总建筑面积」单位是 万m²，传 60000 就是把 m² 的数直接传进来了。

    不设硬闸（照算），但必须出 `fee_base_magnitude_suspect` 并点名换算方向 ——
    静默放大 4300 倍是这条链路上最贵的一种错。
    """
    r = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "inputs": _full_inputs(), "baselines": [],
        "fee_bases": {"工程费用": 12000.0, "总建筑面积": 60000.0},
    })
    assert r.status_code == 200, r.text
    hits = [w for w in r.json()["warnings"] if w["code"] == "fee_base_magnitude_suspect"]
    assert len(hits) == 1, [w["code"] for w in r.json()["warnings"]]
    assert "万m2" in hits[0]["message"] and "10^4" in hits[0]["message"]

    # 合理量级不该误报（哨兵只挡量纲错，不挡"这个项目大"）
    ok = client.post("/engine/estimate/suggest", headers=HEADERS, json={
        "inputs": _full_inputs(), "baselines": [],
        "fee_bases": {"工程费用": 12000.0, "总建筑面积": 6.0},
    }).json()
    assert not [w for w in ok["warnings"] if w["code"] == "fee_base_magnitude_suspect"]


# ---------------------------------------------- compute 成本位覆盖率披露（O-11）

def test_compute_discloses_cost_input_coverage():
    """填 1/150 也能拿到七项合计齐全的 done 任务 —— 那是「误导性成功」的另一种形态。

    全零闸只挡「一个都没填」。这条把「只填了一点点」如实说出来：
    覆盖率 + 缺口最大的表，让造价员一眼看见这份表的完成度。
    只出数据与 warning，**不新增拦截**（概算本就允许分批填、允许某些表为空）。
    """
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": _full_inputs(), "render": False})
    assert r.status_code == 200, r.text
    body = r.json()
    cov = body["input_coverage"]
    assert cov["cost_inputs"] == 150
    assert cov["filled"] == 1        # _full_inputs 只带 1 个成本位
    assert cov["missing"] == 149
    assert cov["rate"] == round(1 / 150, 4)
    # 缺口按表分布，前端据此指路
    assert cov["by_sheet"]["3.专项工程费"]["missing"] == 42
    assert sum(s["cost_inputs"] for s in cov["by_sheet"].values()) == 150

    warn = [w for w in body["warnings"] if w["code"] == "cost_input_incomplete"]
    assert len(warn) == 1
    assert "3.专项工程费 缺 42/42" in warn[0]["message"]


def test_compute_full_cost_inputs_has_no_incomplete_warning():
    """填满就不该再唠叨 —— 覆盖率 1.0 时 cost_input_incomplete 必须消失。"""
    tpl_body = client.get("/engine/estimate/template", headers=HEADERS).json()
    inputs = {c: 1000.0 for c in REQUIRED_11}
    for i in tpl_body["inputs"]:
        if i["kind"] == "cost":
            inputs[i["cell"]] = 10.0
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": inputs, "render": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["input_coverage"]["rate"] == 1.0
    assert body["input_coverage"]["filled"] == 150
    assert not [w for w in body["warnings"] if w["code"] == "cost_input_incomplete"]


def test_all_zero_gate_still_422_after_coverage_disclosure():
    """铁律不放松：覆盖率披露是**增量信息**，不替代全零闸。"""
    r = client.post("/engine/estimate/compute", headers=HEADERS,
                    json={"inputs": {c: 1000.0 for c in REQUIRED_11}, "render": False})
    assert r.status_code == 422, r.text
    assert "全零" in r.json()["detail"]
