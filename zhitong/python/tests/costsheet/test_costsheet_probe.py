# 来源：engine-service/tests/test_costsheet_probe.py（zhitong-cost-ai@991ff5cd）
"""计价表预检（WS26-i，spec WS26 §3.9，决策 D-R82；缺陷 03-003 / RF-26 / TK-B01）。

现场：指标 / 投控的选文件框把 22 份 Excel 混在一组，唯一的计价表「…一标段.xlsx」（355 张表，其中 113 张清单表）
排在最后一项，界面没有任何区分。预检给每份文件一个标签：计价表 / 未找到清单表头 / 未预检（原因）。

守的性质（每条都有够得到失败分支的夹具）：
  1. 清单工作簿 → costsheet；list_sheets 只数清单表（封面、费用表、综合单价分析表按正式解析的同一份表名词表跳过），
     basis_available 是表头里真有的期次（不分期 → ["plain"]；进度款三行表头 → 合同 / 本期 / 累计）。
  2. 结构说明 / 面积表这类「有表头、不是清单」的 → other（读过了，没有清单表头）。
  3. 没读的、没读完的一律 unknown，不许说成 other（铁律 8）：.xls（不转换、不读字节）、损坏文件、读不到的文件、
     预算用完后剩下的文件。
  4. 返回里没有任何金额字段（铁律 2）：出参白名单 + 夹具里的金额不出现在响应里 + 源码不碰取金额的函数、不调模型。

zt 改动：端点换成 zt.costsheet.probe_files（CLI ``python -m zt.costsheet.cli probe``）；413 改为 ZtError；没有服务令牌。
  5. 审核汇总版式（对账审定侧的正当输入）算 costsheet，不被标成「未找到清单表头」把人指错。
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from openpyxl import Workbook

from tests.costsheet.fixtures.endpoint import HEADERS, client
from zt.costsheet import probe as cp
from zt.costsheet import probe_files as api_mod
from zt.costsheet.probe_files import ProbeFile as CostsheetProbeFile
from zt.common import ZtError
from tests.costsheet.fixtures import costsheet_shapes as shapes


FAR = 10 ** 9  # 用不完的预算


def _save(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _bill_sheet(ws, title: str, rows: list) -> None:
    ws.title = title
    ws.append(["分部分项工程和单价措施项目清单与计价表"])
    ws.append(["单位(专业)工程名称：6#楼【建筑】"])
    ws.append(["序号", "项目编码", "项目名称", "项目特征描述", "计量单位", "工程量", "综合单价", "合价"])
    for r in rows:
        ws.append(r)


def bill_workbook() -> bytes:
    """广联达控制价导出件的缩影：封面、2 张清单表、单位工程费用表、综合单价分析表。
    真值：list_sheets=2（费用表、综合单价分析、封面按表名跳过），sheets_total=5，basis_available=["plain"]。
    金额 36000.37 / 12000.58 / 51234.56 / 99999.99 只用来证明它们不会出现在预检的响应里。"""
    wb = Workbook()
    cover = wb.active
    cover.title = "封面"
    cover.append(["某住宅项目一标段 招标控制价"])
    _bill_sheet(wb.create_sheet(), "表-08 分部分项(6#楼)", [
        [1, "010101001001", "平整场地", "三类土", "m2", 1200, 30.0003, 36000.37],
        [2, "010103001001", "回填方", "密实度 93%", "m3", 800, 15.0007, 12000.58],
    ])
    _bill_sheet(wb.create_sheet(), "表-08 分部分项(7#楼)", [
        [1, "010501001001", "垫层", "C15", "m3", 100, 512.3456, 51234.56],
    ])
    fee = wb.create_sheet("单位工程费用表")
    fee.append(["序号", "汇总内容", "金额(元)"])
    fee.append([1, "分部分项工程", 99999.99])
    ana = wb.create_sheet("综合单价分析表")
    ana.append(["序号", "项目编码", "项目名称", "计量单位", "工程量", "综合单价", "合价"])
    ana.append([1, "010101001001", "平整场地", "m2", 1200, 30, 36000])
    return _save(wb)


def structure_note_workbook() -> bytes:
    """结构说明 / 面积统计这类工作簿：有「序号 | 名称」样子的表头（表头块认得出），但不是清单 —— 没有清单编码、
    表名也不像计价表。现场 16 份「结构说明」+ 面积表 + 装修界面表都是这个形状。真值：other，list_sheets=0。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["1. 工程概况", None, "3.2 ±0.000 相当于国家高程"])
    ws.append(["表1.1 结构基本概况"])
    ws.append(["序号", "楼号", "名称", "地上层数", "地下层数", "高度(m)", "结构类型", "数量"])
    ws.append([1, "6#", "住宅", 18, 1, 54.6, "剪力墙", 1])
    ws.append([2, "7#", "住宅", 18, 1, 54.6, "剪力墙", 1])
    area = wb.create_sheet("一标段(西区)")
    area.append(["工程幢号", "总建筑面积", "总计容", "计容", "不计容"])
    area.append(["6#", 7713.91, 7606.18, 7072.79, 203.38])
    return _save(wb)


# ---------------------------------------------------------------- 1. 清单工作簿

def test_bill_workbook_is_costsheet_with_only_list_sheets_counted():
    r = cp.probe_workbook(bill_workbook(), "F1", "一标段.xlsx", deadline=FAR, clock=lambda: 0)
    assert r["kind"] == "costsheet"
    assert r["list_sheets"] == 2, "封面、单位工程费用表、综合单价分析表都不算清单表（与正式解析同一份表名词表）"
    assert r["sheets_total"] == 5
    assert r["basis_available"] == ["plain"]
    assert r["reason_code"] is None


def test_progress_payment_header_reports_its_periods():
    """进度款三行表头（投标价 / 本期 / 累计）：口径核对（WS26-e 的选文件框确认）靠这里给的期次。"""
    r = cp.probe_workbook(shapes.zheda_three_row_header(), "F2", "第5期.xlsx", deadline=FAR, clock=lambda: 0)
    assert r["kind"] == "costsheet"
    assert r["list_sheets"] == 1
    assert {"current", "cumulative"} <= set(r["basis_available"]), r["basis_available"]


def test_audit_summary_form_counts_as_costsheet():
    """审定单（送审 | 审定 | 核减，没有编码 / 单位 / 量价）是对账审定侧的正当输入，正式解析走 _audit_rows。
    标成「未找到清单表头」会把人从正确的文件上指走。"""
    r = cp.probe_workbook(shapes.approval_form(), "F3", "审定单.xlsx", deadline=FAR, clock=lambda: 0)
    assert r["kind"] == "costsheet", r


def test_unpriced_bill_is_still_a_list_header():
    """招标工程量清单（只有工程量）：表头是清单表头，预检只回答「是不是清单」；无价由正式解析判（WS08-04）。"""
    r = cp.probe_workbook(shapes.unpriced_bill(), "F4", "工程量清单.xlsx", deadline=FAR, clock=lambda: 0)
    assert r["kind"] == "costsheet"


# ---------------------------------------------------------------- 2. 结构说明类

def test_structure_note_is_other_not_costsheet():
    r = cp.probe_workbook(structure_note_workbook(), "S1", "结构说明1.xlsx", deadline=FAR, clock=lambda: 0)
    assert r["kind"] == "other"
    assert r["list_sheets"] == 0 and r["sheets_total"] == 2
    assert r["basis_available"] == []
    assert r["reason"] == "未找到清单表头"


def test_labor_and_machine_tables_are_not_list_sheets():
    """工日 / 台班 / 材料一览表的列头与清单表相似（编码 | 名称 | 单位 | 数量 | 单价 | 合价），正式解析按表名与表内标题
    （「表-09」第 1 行写「主要材料价格表」）跳过；预检用同一份词表。夹具 4 张表里只有「分部分项清单与计价表」是清单表。"""
    r = cp.probe_workbook(shapes.labor_machine_tables(), "L1", "市政控制价.xlsx", deadline=FAR, clock=lambda: 0)
    assert r["kind"] == "costsheet"
    assert (r["list_sheets"], r["sheets_total"]) == (1, 4), r


# ---------------------------------------------------------------- 3. 没读的不许说成 other

def test_xls_is_unknown_old_format_without_reading_bytes():
    r = cp.probe_workbook(b"", "X1", "结构说明1.xls", deadline=FAR, clock=lambda: 0)
    assert r["kind"] == "unknown"
    assert r["reason"] == "旧格式 .xls，未预检；请用 Excel/WPS 另存为 .xlsx" and r["reason_code"] == "xls"
    assert r["list_sheets"] is None and r["basis_available"] is None


def test_corrupt_xlsx_is_unknown_not_other():
    raw = bill_workbook()
    for bad in (b"this is not a zip file", raw[: len(raw) // 3]):
        r = cp.probe_workbook(bad, "C1", "坏文件.xlsx", deadline=FAR, clock=lambda: 0)
        assert r["kind"] == "unknown", r
        assert r["reason_code"] == "unreadable"
        assert r["reason"].startswith("文件读不开，未预检")
        assert r["basis_available"] is None


def test_damaged_stylesheet_is_still_probed():
    """样式表坏了但数据完好（广联达导出件常见，WS08-05）：容错读取后照常预检，不落成 unknown。"""
    r = cp.probe_workbook(shapes.broken_stylesheet(), "B1", "长兴.xlsx", deadline=FAR, clock=lambda: 0)
    assert r["kind"] == "costsheet"


def test_deadline_mid_workbook_is_unknown_even_after_a_list_sheet():
    """读到一半到点：前面已经认出过清单表也回 unknown —— 没读完，不下结论、不报一个不全的张数。"""
    ticks = iter([0, 0, 0, 99, 99, 99, 99, 99])
    r = cp.probe_workbook(bill_workbook(), "F1", "一标段.xlsx", deadline=10, clock=lambda: next(ticks))
    assert r["kind"] == "unknown" and r["reason_code"] == "timeout"
    assert r["list_sheets"] is None


def test_non_excel_is_unknown():
    r = cp.probe_workbook(b"%PDF", "P1", "说明.pdf", deadline=FAR, clock=lambda: 0)
    assert r["kind"] == "unknown" and r["reason_code"] == "not_excel"


# ---------------------------------------------------------------- 端点

def _post(files, **extra):
    return client.post("/engine/costsheet/probe", json={"files": files, **extra}, headers=HEADERS)


def test_endpoint_labels_each_file_and_keeps_going_past_bad_ones():
    files = [
        shapes.put(bill_workbook(), "ws26i-一标段.xlsx", "F-BILL"),
        shapes.put(structure_note_workbook(), "ws26i-结构说明1.xlsx", "F-NOTE"),
        # .xls 不读字节：磁盘上根本没有这份，结果仍是「旧格式」而不是「读不到」—— 证明没去读
        {"file_id": "F-XLS", "path": "_engine_test/ws08/ws26i-不存在.xls", "file_name": "结构说明1.xls"},
        shapes.put(b"not a zip", "ws26i-坏.xlsx", "F-BAD"),
        {"file_id": "F-GONE", "path": "_engine_test/ws08/ws26i-已删除.xlsx", "file_name": "已删除.xlsx"},
        {"file_id": "F-OUT", "path": "../../etc/passwd.xlsx", "file_name": "越界.xlsx"},
    ]
    r = _post(files)
    assert r.status_code == 200, r.text
    body = r.json()
    by = {f["file_id"]: f for f in body["files"]}
    assert [f["file_id"] for f in body["files"]] == [f["file_id"] for f in files], "逐份返回，顺序不变"
    assert by["F-BILL"]["kind"] == "costsheet" and by["F-BILL"]["list_sheets"] == 2
    assert by["F-NOTE"]["kind"] == "other"
    assert by["F-XLS"]["kind"] == "unknown" and by["F-XLS"]["reason_code"] == "xls"
    assert by["F-BAD"]["kind"] == "unknown" and by["F-BAD"]["reason_code"] == "unreadable"
    for gone in ("F-GONE", "F-OUT"):
        assert by[gone]["kind"] == "unknown" and by[gone]["reason_code"] == "missing", by[gone]
        assert "_engine_test" not in json.dumps(by[gone]) and "etc" not in by[gone]["reason"], "不往外给磁盘路径"
    assert body["complete"] is True, "读不到 / 读不开是这份文件的事实，不算预检没做完"
    assert body["status"] == "ok" and body["coverage"]["files_total"] == 6


def test_endpoint_budget_exhausted_marks_the_rest_unknown(monkeypatch):
    """预算到点：剩下的全是 unknown / timeout，complete=False；已经出结果的那份不受影响。
    时钟换成假的：每预检完一份就过去 9 秒（预算 8 秒）。"""
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    real = cp.probe_workbook

    def slow(*a, **k):
        out = real(*a, **k)
        now[0] += 9
        return out

    monkeypatch.setattr(api_mod.cp, "probe_workbook", slow)
    files = [
        shapes.put(bill_workbook(), "ws26i-t1.xlsx", "T1"),
        shapes.put(bill_workbook(), "ws26i-t2.xlsx", "T2"),
        shapes.put(structure_note_workbook(), "ws26i-t3.xlsx", "T3"),
    ]
    body = _post(files).json()
    kinds = [(f["file_id"], f["kind"], f["reason_code"]) for f in body["files"]]
    assert kinds == [("T1", "costsheet", None), ("T2", "unknown", "timeout"), ("T3", "unknown", "timeout")], kinds
    assert body["complete"] is False
    # 结果契约（C1）：partial 带 coverage（哪几份没轮到）和一条 warn
    assert body["status"] == "partial" and body["status_reason"] == "probe_budget_exhausted"
    assert [s["rel_path"] for s in body["coverage"]["skipped"]] == ["T2", "T3"]
    assert body["coverage"]["files_used"] == 1
    assert any(w["level"] == "warn" for w in body["warning_items"])


def test_endpoint_with_no_files_is_empty_not_ok():
    body = _post([]).json()
    assert body["status"] == "empty" and body["status_reason"] == "no_source_files"
    assert body["files"] == []


def test_endpoint_rejects_more_than_60_files():
    files = [{"file_id": f"F{i}", "path": f"x/{i}.xlsx", "file_name": f"{i}.xlsx"} for i in range(61)]
    with pytest.raises(ZtError) as exc:       # zt 改动：旧端点回 413
        _post(files)
    assert exc.value.code == "too_many_files" and "60" in exc.value.message


def test_deadline_is_capped_at_eight_seconds():
    assert api_mod.deadline_ms(None) == 8000
    assert api_mod.deadline_ms(60_000) == 8000
    assert api_mod.deadline_ms(2000) == 2000


# ---------------------------------------------------------------- 4. 没有金额（铁律 2）

_ALLOWED_KEYS = {"file_id", "kind", "list_sheets", "sheets_total", "basis_available", "reason_code", "reason"}


def test_output_whitelist_has_no_amount_field():
    assert set(CostsheetProbeFile.model_fields) == _ALLOWED_KEYS
    with pytest.raises(Exception):
        CostsheetProbeFile(file_id="x", kind="costsheet", amount=1.0)  # extra=forbid：多一个键就拒


def test_amounts_in_the_workbook_never_reach_the_response():
    body = _post([shapes.put(bill_workbook(), "ws26i-money.xlsx", "F-M")]).json()
    assert body["files"][0]["kind"] == "costsheet"
    text = json.dumps(body, ensure_ascii=False)
    for money in ("36000.37", "12000.58", "51234.56", "99999.99", "36000", "48000"):
        assert money not in text, f"预检响应里出现了金额 {money}"
    for f in body["files"]:
        assert set(f) == _ALLOWED_KEYS


def test_probe_source_does_not_touch_amount_readers_or_llm():
    """源码闸：预检两个模块不引用取金额的函数（读数据行、费用表合计、跳表估额），也不 import 模型客户端。"""
    root = Path(__file__).resolve().parents[2] / "zt" / "costsheet"
    banned = ("parse_costsheet", "_detail_rows", "_audit_rows", "_row_values", "_to_float", "round_money",
              "_estimate_total", "scan_fee_sheet", "resolve_fee_total", "extract_fee_totals", "llm_client",
              "chat_json", "libreoffice_convert")
    for rel in ("probe.py", "probe_files.py", "cli.py"):
        src = (root / rel).read_text(encoding="utf-8")
        hits = [b for b in banned if b in src]
        assert not hits, f"{rel} 引用了 {hits}"
