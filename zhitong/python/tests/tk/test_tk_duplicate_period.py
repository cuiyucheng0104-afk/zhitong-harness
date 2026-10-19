# 来源：engine-service/tests/test_tk_duplicate_period.py（zhitong-cost-ai@991ff5cd）
"""#22 [D-12] duplicate 规则期次意识:判重边界从「同一送审文件」升级为「同一期次」。

期次来源实地调研(nas-data/project 真实语料,2026-08-29,详见 tk_engine 内注释):
  · 文件名是唯一实测可靠的来源(30003「…进度款2024年4月-土建.xlsx」年月式;
    30002「1、进度款027号.rtf」期次号式),优先级最高;
  · 表内 sheet 标题实测有陈旧模板(5月文件里写着 2023年12月),刻意不采用;
  · 目录名实测全是「未命名文件夹」/雪花ID,无期次信息;
  · 兜底:识别不到期次 → 每份文件视为独立期次(保持 source_file 保守口径,
    不回退 issue #22 的 4423 条跨期误报)。

变异验证口径:把 rule_duplicate 分组键改回不分组的 (project_id, major, ident),
本文件的 test_cross_period_* / test_no_period_* 必须变红;真阳性守护测试
(test_within_period_*)在正确实现下必须绿。

跑法: cd engine-service && ./.venv/bin/pytest tests/test_tk_duplicate_period.py -v
"""
from __future__ import annotations

import io

from openpyxl import Workbook

from zt.tk import engine as tk_engine
from zt.tk.engine import period_of

# ---------- 期次识别单测(样式全部来自真实语料或 issue 正文) ----------


def test_period_year_month_from_real_30003_filenames():
    """30003 真实文件名:年月式,三份文件必须落进三个不同期次。"""
    k4, l4 = period_of("审核-建设二村项目进度款2024年4月-土建.xlsx")
    k5, _ = period_of("审核-建设二村项目进度款2024年5月-土建.xlsx")
    k7, _ = period_of("审核-建设二村项目进度款2024年7月-土建.xlsx")
    assert k4 == "ym:2024-04" and l4 == "2024年4月"
    assert len({k4, k5, k7}) == 3


def test_period_year_month_separator_variants():
    assert period_of("进度款2024-04.xlsx")[0] == "ym:2024-04"
    assert period_of("进度款2024.4申报.xlsx")[0] == "ym:2024-04"
    assert period_of("2025_12结算书.xlsx")[0] == "ym:2025-12"


def test_period_seq_from_real_30002_filenames():
    """30002 真实文件名:期次号式;前导「1、」是列表序号,不得被当成期次。"""
    assert period_of("1、进度款027号.rtf") == ("no:27", "第27期")
    assert period_of("进度款01号.rtf") == ("no:1", "第1期")
    assert period_of("第5期进度款.xlsx") == ("no:5", "第5期")  # issue 正文给的样式


def test_period_bare_month():
    """无年份的裸月式(「4月进度款」):同批内可区分,优先级最低。"""
    assert period_of("4月进度款.xlsx") == ("m:4", "4月")


def test_period_no_false_hit_on_real_corpus_names():
    """真实语料里的非期次文件名,一律不得误配期次(兜底=按文件独立)。"""
    for name in (
        "2092051860741865472.xlsx",      # 30003 平台雪花ID命名
        "3、审核汇总表(1).xls",           # 30002:「(1)」是副本号不是期次
        "设计说明-案例.xlsx",
        "招标文件——最终版.pdf",
        "1205-20241120-补充协议（涉及4177及提档内容汇总）12.5改1.docx",  # 30002 真实文件名
    ):
        key, label = period_of(name)
        assert key == "file:" + name and label is None, name


def test_period_scans_path_components_filename_first():
    """带路径的 source_file:文件名优先;文件名无期次时退而扫父目录名。"""
    assert period_of("2024年4月/进度款2024年5月.xlsx")[0] == "ym:2024-05"
    assert period_of("2024年4月报审/明细表.xlsx")[0] == "ym:2024-04"


# ---------- 分组行为(内存行级) ----------


def _row(source_file, code="010101001001", name="挖一般土方", amount=1000.0) -> dict:
    return {
        "project_id": "P30003", "major": "土石方工程", "sheet": "分部分项",
        "source_file": source_file, "item_code": code, "item_name": name,
        "item_feature": "三类土", "unit": "m3",
        "submit_qty": 100, "submit_price": 10, "submit_amount": amount,
    }


_CFG = {"min_amount": 0}


def test_cross_period_same_item_not_duplicate():
    """跨期次(4423 条误报的根因场景):三个月各报一次同一清单项 → 不判重。"""
    rows = [_row(f"审核-建设二村项目进度款2024年{m}月-土建.xlsx") for m in (4, 5, 7)]
    assert tk_engine.rule_duplicate(rows, _CFG, conf=0.7) == []


def test_same_period_split_files_is_duplicate():
    """同期次拆成多份文件上传(重开评论②量化过的漏报):必须判重。
    这是期次意识相对 source_file 口径的净收益——source_file 键下此场景=0。"""
    rows = [
        _row("进度款2024年4月-土建A标段.xlsx"),
        _row("进度款2024年4月-土建B标段.xlsx"),
    ]
    out = tk_engine.rule_duplicate(rows, _CFG, conf=0.7)
    assert len(out) == 2
    assert all(a["period"] == "2024年4月" for a in out)


def test_within_period_true_positive_still_reported():
    """真阳性守护:同一文件(必然同期次)内两条相同编码 → 仍然必须判重。"""
    rows = [_row("进度款2024年4月.xlsx"), _row("进度款2024年4月.xlsx")]
    out = tk_engine.rule_duplicate(rows, _CFG, conf=0.7)
    assert len(out) == 2
    assert {a["subtype"] for a in out} == {"duplicate"}


def test_no_period_files_are_independent_periods():
    """兜底策略:无期次标识的文件各自独立判重,互相不判。
    文件名取自真实语料:30003 两份雪花ID命名文件是内容完全相同的两份清单
    (空白工程量版)——同类文件一旦带上量价,若"无期次归同一组",全部同项会
    互判重复,重现 issue #22 的误报形态。故兜底选"按文件独立"。"""
    rows = [_row("2092051860741865472.xlsx"), _row("2092059268151164928.xlsx")]
    assert tk_engine.rule_duplicate(rows, _CFG, conf=0.7) == []


def test_no_period_same_file_still_duplicate():
    """兜底口径下,同一份无期次文件内部的真重复仍然要报(period=None 如实标注)。"""
    rows = [_row("2092051860741865472.xlsx"), _row("2092051860741865472.xlsx")]
    out = tk_engine.rule_duplicate(rows, _CFG, conf=0.7)
    assert len(out) == 2
    assert all(a["period"] is None for a in out)


def test_cross_period_seq_style_not_duplicate():
    """期次号式同样具备期次意识:第26号 vs 第27号进度款 → 不判重。"""
    rows = [_row("1、进度款026号.rtf"), _row("1、进度款027号.rtf")]
    assert tk_engine.rule_duplicate(rows, _CFG, conf=0.7) == []


# ---------- 真 parser 端到端(与 test_tk_duplicate_scope 同一套真实广联达格式) ----------


def _xlsx_bytes(data_rows: list[list]) -> bytes:
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


def test_run_cross_period_not_duplicate_end_to_end():
    """端到端:三份不同年月的进度款表各含同一清单项 → 0 条 duplicate。"""
    files = [(_xlsx_bytes([_ITEM]), f"进度款2024年{m}月-土建.xlsx") for m in (4, 5, 7)]
    result = tk_engine.run(files, baseline=None, project_id="P30003")
    assert [a for a in result["anomalies"] if a["subtype"] == "duplicate"] == []


def test_run_same_period_split_files_duplicate_end_to_end():
    """端到端:同期次拆两份文件、各含同一清单项一次 → 判重,且带期次标注。"""
    files = [
        (_xlsx_bytes([_ITEM]), "进度款2024年4月-A标段.xlsx"),
        (_xlsx_bytes([_ITEM]), "进度款2024年4月-B标段.xlsx"),
    ]
    result = tk_engine.run(files, baseline=None, project_id="P30003")
    dup = [a for a in result["anomalies"] if a["subtype"] == "duplicate"]
    # WS08-08：异常身份按 (文件, 表, 行)，两份文件各一行 → 两条，各自回得到原表（旧版按编码折成 1 条）
    assert len(dup) == 2
    assert {a["source_file"] for a in dup} == {"进度款2024年4月-A标段.xlsx", "进度款2024年4月-B标段.xlsx"}
    assert all(a["period"] == "2024年4月" for a in dup)
    assert all("同期次[2024年4月]" in a["baseline_source"] for a in dup)
