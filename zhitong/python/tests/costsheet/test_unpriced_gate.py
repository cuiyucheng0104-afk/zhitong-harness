# 来源：engine-service/tests/test_unpriced_gate.py（zhitong-cost-ai@991ff5cd）
"""WS08-04 无价清单闸（issue #724，铁律 8）。

只有工程量、没有单价和合价的招标清单，旧版：指标 200 + 总额 0 + 单方造价 0.0；投控 200 + 0 条
异常，前端显示「本次检测完成，未检出异常」—— 没有任何告警（R1:ENG-15）。

变异验收：删掉全无价的 raise → 422 用例转红（实际得到 200）；删掉逐文件剔除 → files_used /
file_unpriced 断言转红；总额为 0 时恢复给 0.0 → null 断言转红。
"""
from __future__ import annotations


from tests.costsheet.fixtures.endpoint import HEADERS, client
from zt.indicator import engine as indicator_engine
from tests.costsheet.fixtures import costsheet_shapes as shapes



def _unpriced():
    return shapes.put(shapes.unpriced_bill(), "室外配套-招标清单.xlsx", "U1")


def _priced():
    return shapes.put(shapes.priced_bill(), "室外配套-控制价.xlsx", "P1")


def test_costsheet_meta_marks_unpriced():
    from zt.costsheet.parser import parse_costsheet
    out = parse_costsheet(shapes.unpriced_bill(), "招标清单.xlsx")
    m = out["meta"]
    assert (m["leaf_rows"], m["priced_rows"], m["unpriced"]) == (3, 0, True)
    assert m["sheets_detail"][0]["status"] == "unpriced"
    assert m["coverage"]["status"] == "unpriced"
    priced = parse_costsheet(shapes.priced_bill(), "控制价.xlsx")["meta"]
    assert (priced["leaf_rows"], priced["priced_rows"], priced["unpriced"]) == (2, 2, False)


def test_indicator_all_unpriced_returns_422():
    r = client.post("/engine/indicator/calc", headers=HEADERS,
                    json={"baseline": {"gross_area": 1000}, "price_files": [_unpriced()]})
    assert r.status_code == 422, r.text
    msg = r.json()["detail"]["message"]          # WS26-e：解析类 422 的 detail 是对象
    assert "清单无单价/金额" in msg and "室外配套-招标清单.xlsx" in msg


def test_tk_all_unpriced_returns_422():
    r = client.post("/engine/tk/detect", headers=HEADERS,
                    json={"project_id": "P1", "submission_files": [_unpriced()]})
    assert r.status_code == 422, r.text
    assert "送审文件均无金额" in r.json()["detail"]["message"]


def test_reconcile_either_side_unpriced_returns_422():
    for sub, app_ in ((_unpriced(), _priced()), (_priced(), _unpriced())):
        r = client.post("/engine/reconcile/run", headers=HEADERS,
                        json={"submitted_file": sub, "approved_file": app_})
        assert r.status_code == 422, r.text
        assert "无单价/金额" in r.json()["detail"]["message"]


def test_indicator_mixed_priced_and_unpriced_drops_unpriced_with_warning():
    r = client.post("/engine/indicator/calc", headers=HEADERS,
                    json={"baseline": {"gross_area": 1000}, "price_files": [_priced(), _unpriced()]})
    assert r.status_code == 200, r.text
    body = r.json()
    w = [w for w in body["warning_items"] if w["code"] == "file_unpriced"]
    assert len(w) == 1 and w[0]["level"] == "error" and w[0]["file"] == "室外配套-招标清单.xlsx"
    by = {row["indicator_code"]: row for row in body["indicators"]}
    assert by["total_amount"]["value"] == 48000.0
    assert by["unit_cost"]["value"] == 48.0 and by["unit_cost"]["value"] > 0
    assert body["coverage"]["files_total"] == 2 and body["coverage"]["files_used"] == 1
    skipped = [s for s in body["coverage"]["skipped"] if s["file_name"] == "室外配套-招标清单.xlsx"]
    assert skipped and "无单价" in skipped[0]["reason"]


def test_engine_files_used_lists_priced_files_only():
    res = indicator_engine.run([(shapes.priced_bill(), "控制价.xlsx"), (shapes.unpriced_bill(), "招标清单.xlsx")],
                               {"gross_area": 1000}, None)
    assert res["files_used"] == ["控制价.xlsx"]


def test_tk_mixed_reports_checked_rows():
    r = client.post("/engine/tk/detect", headers=HEADERS,
                    json={"project_id": "P1", "submission_files": [_priced(), _unpriced()]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["coverage"]["rows_parsed"] == 2, "checked_rows：前端据此区分「检出 0 条」与「没有可检测的金额」"
    assert "file_unpriced" in [w["code"] for w in body["warning_items"]]


def test_zero_total_gives_null_unit_cost_and_share_not_zero():
    """总额为 0 时单方造价和占比给 null（旧版给 0.0，读起来像「这一章没花钱」）。"""
    out = indicator_engine.compute_indicators(
        [{"code": "010101001001", "name": "平整场地", "amount": None},
         {"code": "010401003001", "name": "实心砖墙", "amount": 0.0}],
        {"gross_area": 1000})
    assert out["unit_cost"] is None and out["unit_cost_itemized"] is None
    assert all(c["pct"] is None for c in out["chapters"])
    assert all(t["pct"] is None for t in out["top_items"])


def test_warning_items_is_always_a_list():
    """stubs：warning_items 恒为 list，没有告警也不给 None。

    WS08-16 起没有费用表时会出 fee_total_unavailable（info，说明总造价口径）—— 用户录入总造价
    才是「没有任何告警」的输入形状。"""
    r = client.post("/engine/indicator/calc", headers=HEADERS,
                    json={"gross_area": 1000, "total_amount": 50000, "price_files": [_priced()]})
    assert r.status_code == 200
    assert r.json()["warning_items"] == []


def test_quantity_only_header_is_unpriced_not_ambiguous():
    """表头压根没有单价/金额列（工程量清单框架、招标清单的另一种导出）→ unpriced，不是「口径歧义」。
    本机 30003「2092051860741865472.xlsx」就是这个形状。"""
    import io
    from openpyxl import Workbook
    from zt.costsheet.parser import parse_costsheet
    wb = Workbook()
    ws = wb.active
    ws.title = "表1-2 分部分项工程量清单与计价表"
    ws.append(["序号", "项目编码", "项目名称", "项目特征描述", "计量单位", "工程量", "来源依据"])
    ws.append([None, None, "砌筑工程"])
    ws.append([1, "010401003001", "多孔砖墙", "墙厚200", "m³", None, "设计说明"])
    buf = io.BytesIO()
    wb.save(buf)
    out = parse_costsheet(buf.getvalue(), "清单框架.xlsx")
    assert out["meta"]["unpriced"] is True
    assert out["meta"]["sheets_detail"][0]["status"] == "unpriced"
    assert "column_ambiguous" not in [w["code"] for w in out["warning_items"]]
