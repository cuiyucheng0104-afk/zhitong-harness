# 来源：engine-service/tests/test_costsheet_real_shapes.py（zhitong-cost-ai@991ff5cd）
"""WS08-20 真实版式端到端金标 + 真实样本回归（issue #724）。

tests/test_golden.py 的 4 份旧金标只用自造的单表单行表头样例 —— 够不到任何真实版式的
失败分支（§5.2）。这里对真实版式夹具走一遍 HTTP 端点，期望值逐项手写（夹具构造真值），
不是「从当前实现生成、跟上次一样」的回归快照。

本机有 nas-data 真实样本时（开发机），另跑 skipif 形式的真实样本回归。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.costsheet.fixtures.endpoint import HEADERS, client
from zt.costsheet.parser import parse_costsheet
from tests.costsheet.fixtures import costsheet_shapes as shapes

# zt 改动：真实语料根目录由环境变量 ZT_NAS_DATA 指定（旧仓写死开发机路径）；未设置时这些用例跳过
NAS_DATA = Path(os.environ.get("ZT_NAS_DATA") or "/nonexistent/zt-nas-data")
NAS = (NAS_DATA / "project")


def test_items_carry_file_and_file_id_for_same_named_sheets():
    """同名 sheet、不同标段的两份文件：每个 item 都带自己的 file / file_id / sheet / row，
    下游（WS08-08 异常身份键、WS08-09 回源定位）才分得开。"""
    got = []
    for raw, name in shapes.same_name_sheets_two_lots():
        out = parse_costsheet(raw, name, file_id=f"id-{name}")
        (it,) = out["items"]
        got.append((it["file"], it["file_id"], it["sheet"], it["row"], it["code"], it["amount"]))
    assert got == [
        ("进度款-标段一.xlsx", "id-进度款-标段一.xlsx", "分部分项清单与计价表", 2, "010101001001", 12500.0),
        ("进度款-标段二.xlsx", "id-进度款-标段二.xlsx", "分部分项清单与计价表", 2, "010101001001", 9000.0),
    ]


def test_tk_endpoint_on_zheda_progress_file():
    f = shapes.put(shapes.zheda_three_row_header(), "C1-浙大第五期-送审.xlsx", "C1")
    r = client.post("/engine/tk/detect", headers=HEADERS, json={"project_id": "P1", "submission_files": [f]})
    assert r.status_code == 200, r.text
    body = r.json()
    big = sorted(a["item_code"] for a in body["anomalies"] if a["type"] == "big_amount")
    assert big == ["010501001001", "010502001001"]
    assert not [a for a in body["anomalies"] if a["type"] == "self_check"]
    assert body["coverage"] == {"files_total": 1, "files_used": 1, "rows_parsed": 3, "unmatched": None,
                                "skipped": []}
    assert {a["major"] for a in body["anomalies"]} == {"房屋建筑与装饰工程"}


def test_indicator_endpoint_on_labor_tables_and_wan_estimate():
    """指标：工日/台班表不计入；万元估算表（没有国标编码）require_gb_code 排除。"""
    a = shapes.put(shapes.labor_machine_tables(), "run05-市政控制价.xlsx", "R5")
    b = shapes.put(shapes.wan_estimate(), "run11-设备估算表.xlsx", "R11")
    r = client.post("/engine/indicator/calc", headers=HEADERS,
                    json={"baseline": {"gross_area": 100}, "price_files": [a, b]})
    assert r.status_code == 200, r.text
    body = r.json()
    by = {row["indicator_code"]: row for row in body["indicators"]}
    assert by["total_amount"]["value"] == 8000.0, "估算表 3,400,000 不得混入，工日台班不得混入"
    assert by["unit_cost"]["value"] == 80.0
    assert body["coverage"]["files_used"] == 1
    assert "sheets_skipped_non_list" in [w["code"] for w in body["warning_items"]]
    assert {c["chapter_name"] for c in body["chapters"]} == {"土石方工程"}


def test_reconcile_endpoint_on_door_workbook():
    f = shapes.put(shapes.door_three_block(), "R1-门窗一期-审核.xlsx", "R1")
    r = client.post("/engine/reconcile/run", headers=HEADERS, json={"submitted_file": f, "approved_file": f})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_diff"] == 9000.0
    assert (body["summary"]["a_total"], body["summary"]["b_total"]) == (158400.0, 149400.0)
    assert len(body["rows"]) == 5
    assert body["summary"]["coverage_ok"] is True


def test_reconcile_endpoint_ambiguous_file_is_422_with_basis_hint():
    f = shapes.put(shapes.a1_period_qty("split"), "A1-歧义.xlsx", "A1")
    r = client.post("/engine/reconcile/run", headers=HEADERS, json={"submitted_file": f, "approved_file": f})
    assert r.status_code == 422
    detail = r.json()["detail"]                   # WS26-e：对象，多组列分不清时 reason_code=column_ambiguous
    assert "表头存在多组金额列，无法确定口径，请选择对比口径" in detail["message"]
    assert detail["reason_code"] == "column_ambiguous"


# ---------------------------------------------------------------- 真实样本回归（本机才有）

_R30003 = NAS / "30003" / "审核-建设二村项目进度款2024年4月-土建.xlsx"


@pytest.mark.skipif(not _R30003.exists(), reason="真实语料不入仓；设置 ZT_NAS_DATA 指向 nas-data 目录后才跑")
def test_real_30003_progress_workbook():
    """30003 进度款：表头是「2023年6月上报产值 / 已完工程量|已完产值」这种按月份分组的列，
    没有「本期」字样 → auto 按合价口径（D45），不能判歧义、不能 0 行；两张汇总表只勾稽不计入。"""
    out = parse_costsheet(_R30003.read_bytes(), _R30003.name, side="submit")
    m = out["meta"]
    status = [d["status"] for d in m["sheets_detail"]]
    assert "ambiguous" not in status
    assert status.count("used") >= 30
    assert m["basis_used"] == "plain"
    assert m["coverage"]["level"] == "ok"
    assert "sheet_total_mismatch" not in [w["code"] for w in out["warning_items"]]
    assert all(i["chapter_name"] != "其他" for i in out["items"])
