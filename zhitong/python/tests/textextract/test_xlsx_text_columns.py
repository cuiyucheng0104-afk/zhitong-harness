"""WS04-P6：xlsx 保留列位置（QA:text-ocr-04 的 xlsx 部分；决策 D11 列号坐标式；C6 隐藏表）。

生产 R16『有财政审批表(建筑)』第 8 行：A=14253902、D（审定）为空、G（核减）=14253902、
H（核增）=0、I=14253902。旧输出 `14253902\\t14253902\\t0\\t14253902` —— 空格被塌掉、不带列号，
按表头顺序读成「审定 14253902、核减 0、核增 14253902」，语义正好反了（铁律 2、3）。
另：格内换行把清单第 1 条拆成 5 行（R04）；隐藏表里的示例金额被送进 LLM（WS12-P12）。
"""
from __future__ import annotations

import io

from openpyxl import Workbook

from zt.textextract.extract import extract_document
from zt.textextract.xlsx import read_xlsx, xlsx_lines, xlsx_text

HEADER = ["单位工程", "送审", "", "审定", "", "", "核减", "核增", "合计"]


def _r16_like() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "有财政审批表(建筑)"
    ws.append(["审批表"])
    ws.append(HEADER)
    ws.append(["土建", 14253902, None, None, None, None, 14253902, 0, 14253902])
    ws["A4"] = "清单1\n010101001001\n平整场地\nm2\n1200"
    hidden = wb.create_sheet("示例（隐藏）")
    hidden["B2"] = 1442539
    hidden.sheet_state = "hidden"
    very = wb.create_sheet("深度隐藏")
    very["A1"] = "内部参数 99"
    very.sheet_state = "veryHidden"
    wb.create_sheet("无财政")["A1"] = "无财政表"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_data_row_keeps_column_letters():
    lines = xlsx_lines(_r16_like())
    assert "[R3] A:土建\tB:14253902\tG:14253902\tH:0\tI:14253902" in lines


def test_header_letters_align_with_data():
    lines = xlsx_lines(_r16_like())
    header = next(ln for ln in lines if ln.startswith("[R2] "))
    assert header == "[R2] A:单位工程\tB:送审\tD:审定\tG:核减\tH:核增\tI:合计"
    # 审定列（D）在数据行里是空的：不许出现 D:，也不许让核减的值落进审定的位置
    data = next(ln for ln in lines if ln.startswith("[R3] "))
    assert "D:" not in data


def test_in_cell_newlines_become_spaces():
    lines = xlsx_lines(_r16_like())
    row4 = [ln for ln in lines if ln.startswith("[R4] ")]
    assert row4 == ["[R4] A:清单1 010101001001 平整场地 m2 1200"]
    assert not any(ln.strip() == "010101001001" for ln in lines)


def test_hidden_sheets_skipped_and_reported():
    content = _r16_like()
    text = xlsx_text(content)
    assert "1442539" not in text
    assert "内部参数" not in text
    book = read_xlsx(content)
    assert book.hidden_sheets == ["示例（隐藏）", "深度隐藏"]
    doc = extract_document(content, "xlsx", file_name="R16.xlsx")
    assert doc.hidden_sheets == ["示例（隐藏）", "深度隐藏"]
    assert doc.provenance()["hidden_sheets"] == ["示例（隐藏）", "深度隐藏"]
    assert "[工作表] 无财政" in text


def test_only_hidden_content_is_no_text():
    wb = Workbook()
    wb.active["A1"] = None
    h = wb.create_sheet("隐")
    h["A1"] = 1
    h.sheet_state = "hidden"
    buf = io.BytesIO()
    wb.save(buf)
    doc = extract_document(buf.getvalue(), "xlsx", file_name="空.xlsx")
    assert doc.failure is not None and doc.failure.code == "no_text"
    assert "隐" in doc.failure.detail
