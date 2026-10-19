# 来源：engine-service/tests/test_tk_duplicate_scope.py（zhitong-cost-ai@991ff5cd）
"""防回归:tk_engine.rule_duplicate 的判重必须限定在"同一送审文件"内。

背景(2026-08-25 裁决,task-3-report.md 有完整记录):`rule_duplicate` 旧版分组键
是 (project_id, major, ident),不含文件维度。真实项目按月导入多份进度款表时
(同一清单项每月都会再出现一次),旧版会把跨月/跨期次的同一清单项全部误判成
"重复计取"——实测项目 30003 三份进度款表合并送检,从单文件 64 条真重复暴涨到
4423 条(几乎全是误报)。

口径演进(#22 重开后):判重边界已从"同一送审文件"升级为"同一期次"——期次由
tk_engine.period_of() 从文件名识别(年月式/期次号式/裸月式),识别不到才退化为
按文件独立判重(即保留本文件所验的保守口径)。本文件的用例全部仍然有效:
文件名带月份的用例分属不同期次,同文件用例必然同期次。期次意识本身的测试
(同期拆多文件判重、跨期不判、无期次兜底)在 tests/test_tk_duplicate_period.py。

跑法: cd engine-service && ./.venv/bin/pytest tests/test_tk_duplicate_scope.py -v
"""
from __future__ import annotations

from zt.tk import engine as tk_engine


def _row(project_id="P30003", major="土石方工程", source_file="a.xlsx",
         code="010101001001", name="挖一般土方", feature="三类土", unit="m3",
         amount=1000.0) -> dict:
    return {
        "project_id": project_id,
        "major": major,
        "sheet": "分部分项",
        "source_file": source_file,
        "item_code": code,
        "item_name": name,
        "item_feature": feature,
        "unit": unit,
        "submit_qty": 100,
        "submit_price": 10,
        "submit_amount": amount,
    }


_CFG = {"min_amount": 0}


def test_same_file_two_rows_same_code_is_duplicate():
    """同一份送审文件内,两条相同编码的行 —— 应报 duplicate。"""
    rows = [
        _row(source_file="4月进度款.xlsx", amount=1000.0),
        _row(source_file="4月进度款.xlsx", amount=1000.0),
    ]
    out = tk_engine.rule_duplicate(rows, _CFG, conf=0.7)
    assert len(out) == 2
    assert {a["subtype"] for a in out} == {"duplicate"}


def test_cross_file_same_code_is_not_duplicate():
    """两份不同送审文件,各有一条相同编码的行(模拟同一清单项跨期次再次出现)
    —— 不应报 duplicate。这是本次修复要防的误报场景(实测 4423 条的根因)。"""
    rows = [
        _row(source_file="4月进度款.xlsx", amount=1000.0),
        _row(source_file="5月进度款.xlsx", amount=1000.0),
        _row(source_file="7月进度款.xlsx", amount=1000.0),
    ]
    out = tk_engine.rule_duplicate(rows, _CFG, conf=0.7)
    assert out == []


def test_code_missing_falls_back_to_name_feature_unit_within_same_file():
    """编码为空时退化用 名称+特征+单位 判重;这个退化行为不因本次改动而改变,
    只是分组键额外加了 source_file 这一维度。"""
    rows = [
        _row(source_file="4月进度款.xlsx", code="", name="平整场地", feature="", unit="m2", amount=200.0),
        _row(source_file="4月进度款.xlsx", code="", name="平整场地", feature="", unit="m2", amount=200.0),
    ]
    out = tk_engine.rule_duplicate(rows, _CFG, conf=0.7)
    assert len(out) == 2


def test_code_missing_cross_file_still_not_duplicate():
    """退化到 名称+特征+单位 判重时,同样遵守"同文件内才判重"边界。"""
    rows = [
        _row(source_file="4月进度款.xlsx", code="", name="平整场地", feature="", unit="m2", amount=200.0),
        _row(source_file="5月进度款.xlsx", code="", name="平整场地", feature="", unit="m2", amount=200.0),
    ]
    out = tk_engine.rule_duplicate(rows, _CFG, conf=0.7)
    assert out == []


def _xlsx_bytes(data_rows: list[list]) -> bytes:
    """造真实的广联达明细格式 xlsx 字节 —— 走真 parser,不用替身。

    历史教训(issue #22 重开记录):旧版此处用 monkeypatch 替换 parse_costsheet,
    其对照组断言「同文件内出现两次同一清单项 → 报 duplicate」只在替身下成立——
    真 parser 的 (code,name,amount) 全簿去重会把第二行吃掉,同样输入实际产出
    0 条异常。测试把产品并不具备的行为固化成了绿灯。故本文件全部改为真 parser
    端到端:parse_costsheet → costsheet_items_to_rows → detect 整条链一起验。"""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "分部分项工程量清单计价表"
    ws.append(["项目编码", "项目名称", "项目特征", "计量单位", "工程量", "综合单价", "综合合价"])
    for r in data_rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_ITEM = ["010101001001", "挖一般土方", "三类土", "m3", 100, 10, 1000]


def test_run_real_parser_cross_file_same_item_not_duplicate():
    """真 parser 端到端:三份不同送审文件各含同一清单项(模拟跨期次)→ 不报 duplicate。
    这同时验证 run() 把 (bytes, filename) 的 filename 接进每行 source_file——
    若接线断了,三行会落进同一个判重组,本测试即红。"""
    files = [(_xlsx_bytes([_ITEM]), f"{m}月进度款.xlsx") for m in (4, 5, 7)]
    result = tk_engine.run(files, baseline=None, project_id="P30003")
    dup = [a for a in result["anomalies"] if a["subtype"] == "duplicate"]
    assert dup == []


def test_run_real_parser_same_file_identical_rows_is_duplicate():
    """真 parser 端到端对照组:同一份文件内两条完全相同的行(同编码同名同金额,
    最典型的重复计取)→ 必须报 duplicate。旧版真 parser 在解析层就把第二行
    去重吃掉,这里产出 0 条 —— 即 issue #22 复核实测的漏报。"""
    raw = _xlsx_bytes([_ITEM, _ITEM])
    result = tk_engine.run([(raw, "4月进度款.xlsx")], baseline=None, project_id="P30003")
    dup = [a for a in result["anomalies"] if a["subtype"] == "duplicate"]
    # WS08-08：异常身份按 (文件, 表, 行)，同表两行同码是两条异常、两个 uid（旧版按编码折成 1 条）
    assert len(dup) == 2
    assert len({a["anomaly_id"] for a in dup}) == 2
    assert sorted(a["row"] for a in dup) == [2, 3]
