# 来源：engine-service/tests/test_costsheet_audit_summary.py（zhitong-cost-ai@991ff5cd）
"""#21 [D-11] 审核汇总表格式支持 —— parse_costsheet 的第二种可识别版式。

真实语料(nas-data/project/30002/3、审核汇总表(1).xlsx,金义新区中心医院)的结构:

    行0  「2024年8月进度款审核对比表」(标题)
    行1  编号：032
    行2  工程名称：… | 合同价（元） | 973076000
    行3  序号 | 工程名称 | 报审金额（元） | 审核金额（元） | 核减金额（元） | 完成比例（%）   ← 表头
    行4-21   序号 1..18:各专业工程一行(土建/安装/钢结构/…)                                  ← 明细区
    行22+    累计完成总产值(1—17之和) / 截止上期累计完成产值 / 本期完成产值
             / 其中××本期完成产值(与明细区同名!如「钢结构」) / 本期支付金额 / 备注          ← 派生段

判别依据(不是硬编码某一份文件):表头行同时出现 **报审金额 + 审核金额(或核减金额)**
成对列 —— 广联达明细表的金额列词表(综合单价/合价/金额)不会成对出现这组词。
明细区以**第一条聚合行(累计/总产值/本期完成/合计…)结束**:派生段的行名会与明细区
重名(实测「钢结构」),逐行关键词过滤无法区分,只能按段截断。

跑法: cd engine-service && ./.venv/bin/pytest tests/test_costsheet_audit_summary.py -v
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from openpyxl import Workbook

from zt.costsheet.parser import parse_costsheet

# zt 改动：真实语料根目录由环境变量 ZT_NAS_DATA 指定（旧仓写死开发机路径）；未设置时这些用例跳过
NAS_DATA = Path(os.environ.get("ZT_NAS_DATA") or "/nonexistent/zt-nas-data")
REAL_SAMPLE = (NAS_DATA / "project/30002/3、审核汇总表(1).xlsx")


def _audit_summary_xlsx() -> bytes:
    """按真实 30002 样例的结构造一份最小审核汇总表(结构同型,数字自拟)。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["2024年8月进度款审核对比表"])
    ws.append([None, None, None, None, "编号：032"])
    ws.append(["工程名称：某医院新建工程", None, None, "合同价（元）", 973076000])
    ws.append(["序号", "工程名称", "报审金额（元）", "审核金额（元）", "核减金额（元）", "完成比例（%）"])
    ws.append([1, "土建工程", 289061595.12, 288950262.04, 111333.08, None])
    ws.append([2, "安装工程", 191911823, 189002591, 2909232, None])
    ws.append([3, "钢结构", 2421814.19, 2421814.19, 0, None])
    ws.append([4, "气动物流", 1359527, 981497, 378030, None])
    # —— 派生段:全部不得计入 items ——
    ws.append([5, "累计完成总产值（1——4之和）", 484754759.31, 481356164.23, 3398595.08, 92.17])
    ws.append([6, "截止上期累计完成产值", 471348085, 471348085.06, "/", 90.57])
    ws.append([7, "本期完成产值（5-6）", 13406674.31, 10008079.17, 3398595.14, 1.59])
    ws.append([7.1, "其中土建工程本期完成产值", 1483812.76, 1372479.68, 111333.08, None])
    ws.append([7.2, "钢结构", 0, 0, 0, None])  # 与明细区同名的派生行 —— 不得混入
    ws.append([8, "本期支付金额：（6）×70%（含农民工工资性工程款）", 9384672.02, 7005655.42, 2379016.6, 1.11])
    ws.append(["备注：", None, None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_audit_summary_parses_leaf_rows_only():
    """明细区 4 行全部解析;派生段(累计/本期/其中××/支付/备注)全部排除。"""
    out = parse_costsheet(_audit_summary_xlsx(), "3、审核汇总表.xlsx")
    names = [i["name"] for i in out["items"]]
    assert names == ["土建工程", "安装工程", "钢结构", "气动物流"]
    # 派生段的同名「钢结构」(0 金额)不得混入:钢结构只出现一次且金额是明细区那条的
    steel = [i for i in out["items"] if i["name"] == "钢结构"]
    assert len(steel) == 1
    assert steel[0]["amount"] == 2421814.19


def test_audit_summary_amount_semantics():
    """amount=报审金额;审核金额/核减金额以 audit_amount/deduct_amount 附带,
    供下游(对账/核减率)按字段取用。"""
    out = parse_costsheet(_audit_summary_xlsx(), "3、审核汇总表.xlsx")
    it = out["items"][0]
    assert it["amount"] == 289061595.12
    assert it["audit_amount"] == 288950262.04
    assert it["deduct_amount"] == 111333.08
    # parsed_total = 明细区报审金额之和(不含派生段,否则翻倍)
    assert out["meta"]["parsed_total"] == round(289061595.12 + 191911823 + 2421814.19 + 1359527, 2)


def test_audit_summary_meta_and_schema():
    """meta 标注 format=audit_summary;items 仍是 costsheet 统一 schema
    (code/name/unit/qty/price 字段存在,消费端 reconcile/indicator/tk 不需要特判)。"""
    out = parse_costsheet(_audit_summary_xlsx(), "3、审核汇总表.xlsx")
    assert out["meta"].get("format") == "audit_summary"
    for it in out["items"]:
        for k in ("code", "name", "feature", "unit", "qty", "price", "amount",
                  "chapter", "chapter_name", "sheet", "row"):
            assert k in it


def test_detail_format_not_affected():
    """回归:广联达明细表(既有支持格式)不得被审核汇总表路径抢走/改变口径。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "分部分项工程量清单计价表"
    ws.append(["项目编码", "项目名称", "项目特征", "计量单位", "工程量", "综合单价", "综合合价"])
    ws.append(["010101001001", "平整场地", "土壤类别三类", "m2", 1000, 12.5, 12500])
    buf = io.BytesIO()
    wb.save(buf)
    out = parse_costsheet(buf.getvalue(), "送审-计价表.xlsx")
    assert len(out["items"]) == 1
    assert out["items"][0]["code"] == "010101001001"
    assert out["items"][0]["qty"] == 1000
    assert out["meta"].get("format", "detail") == "detail"


@pytest.mark.skipif(not REAL_SAMPLE.exists(), reason="真实语料不入仓；设置 ZT_NAS_DATA 指向 nas-data 目录后才跑")
def test_real_30002_audit_summary_parses():
    """真实金义样例:此前 parse=0 条(issue #21 实测)。修复后应解析出 18 条明细区行,
    且派生段(行22起)不混入。"""
    out = parse_costsheet(REAL_SAMPLE.read_bytes(), REAL_SAMPLE.name)
    assert out["meta"].get("format") == "audit_summary"
    assert len(out["items"]) == 18
    names = [i["name"] for i in out["items"]]
    assert names[0] == "土建工程"
    assert "累计完成总产值（1——17之和）" not in names
    assert all("本期完成产值" not in n for n in names)
    # 明细区首行的报审/审核/核减三列
    assert out["items"][0]["amount"] == 289061595.12
    assert out["items"][0]["audit_amount"] == 288950262.04
    assert round(out["items"][0]["deduct_amount"], 2) == 111333.08
