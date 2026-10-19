"""案例索引与项目说明的读写：表格解析、编号流水号、YAML 头、小节替换。"""
from __future__ import annotations

import pytest

from zt.common import ZtError
from zt.inventory.casebook import COLUMNS, Casebook, max_seq_in_codes, parse_casebook
from zt.inventory.projectdoc import (
    find_section,
    read_project_doc,
    render_template,
    replace_section,
    section_bullets,
    section_table,
    set_front_matter_fields,
    split_front_matter,
    write_text_atomic,
)

INDEX = """# 案例索引

前言一行。

| 编号 | 工程名 | 业态 | 规模 | 咨询类型 | 关键指标 | 成果链接 | 状态 |
|---|---|---|---|---|---|---|---|
| 2025-014 | 老项目 | 住宅 | 1 万平 | 结算审核 | 单方 3200 \\| 含税 | 项目/2025-014-老项目/成果/ | 已归档 |
| 2026-002 | 某某医院 | 医疗 | | 全过程造价咨询 | | | 进行中 |

备注一行。
"""


# ---------------------------------------------------------------- casebook


def test_parse_and_render_roundtrip_keeps_prose_and_escaped_pipes():
    book = parse_casebook(INDEX)
    assert [r["编号"] for r in book.rows] == ["2025-014", "2026-002"]
    assert book.rows[0]["关键指标"] == "单方 3200 | 含税"
    out = book.render()
    assert out.startswith("# 案例索引\n\n前言一行。\n\n| 编号 |") and out.endswith("备注一行。\n")
    assert parse_casebook(out).rows == book.rows
    assert "单方 3200 \\| 含税" in out


def test_upsert_updates_in_place_or_appends_and_validates_code():
    book = parse_casebook(INDEX)
    assert book.upsert({"编号": "2026-002", "关键指标": "单方 5000", "状态": "已归档"}) is True
    assert book.find("2026-002")["关键指标"] == "单方 5000" and book.find("2026-002")["工程名"] == "某某医院"
    assert book.upsert({"编号": "2026-003", "工程名": "新项目"}) is False
    assert [r["编号"] for r in book.rows] == ["2025-014", "2026-002", "2026-003"]
    with pytest.raises(ZtError) as e:
        book.upsert({"编号": "26-3"})
    assert e.value.code == "invalid_project_code"


def test_unknown_extra_column_is_kept():
    text = INDEX.replace("| 状态 |", "| 状态 | 备注 |").replace("|---|---|---|---|---|---|---|---|", "|---|---|---|---|---|---|---|---|---|")
    book = parse_casebook(text)
    assert book.header[-1] == "备注" and book.rows[0]["备注"] == ""
    assert "| 备注 |" in book.render()


def test_empty_and_broken_index():
    assert parse_casebook("").rows == [] and parse_casebook("   \n").header == list(COLUMNS)
    with pytest.raises(ZtError) as e:
        parse_casebook("# 随便写的\n\n没有表格\n")
    assert e.value.code == "casebook_invalid"


@pytest.mark.parametrize("codes,year,expected", [
    (["2026-001", "2026-009", "2025-100"], 2026, 9),
    (["2026-001", "2026-010-某工程", " 2026-004"], 2026, 10),
    (["2025-100"], 2026, 0),
    (["2026-1000", "2026-12", "x2026-005", "", None], 2026, 0),       # 格式不对的忽略
])
def test_max_seq_in_codes(codes, year, expected):
    assert max_seq_in_codes(codes, year) == expected
    assert Casebook(rows=[{"编号": c or ""} for c in codes]).max_seq(year) == expected


# ---------------------------------------------------------------- projectdoc

DOC = """---
项目编号: 2026-007
工程名称: "某:工程 #1"
咨询类型: 结算审核
阶段: 审定
别名: ["合同号 HT-1"]
---
# 标题

## 基本信息

正文。

## 关键文件指引

| 资料 | 位置 | 备注 |
|---|---|---|
| 合同 | 资料/合同.pdf | 已核对 |
| 图纸 | | |

## 已出成果

- 成果/报告.docx
- 成果/汇总.xlsx

## 工作记录

无。
"""


def test_front_matter_and_required_fields():
    head, body = split_front_matter(DOC)
    assert head["工程名称"] == "某:工程 #1" and body.startswith("# 标题")
    fields = read_project_doc(DOC, require=("项目编号", "阶段"))
    assert fields["项目编号"] == "2026-007" and fields["别名"] == ["合同号 HT-1"]
    with pytest.raises(ZtError) as e:
        read_project_doc("---\n项目编号: 2026-007\n---\n", require=("阶段",))
    assert e.value.code == "project_doc_incomplete"
    with pytest.raises(ZtError) as e:
        read_project_doc("---\n项目编号: 26-7\n---\n")
    assert e.value.code == "invalid_project_code"
    assert split_front_matter("没有头") == ({}, "没有头")
    with pytest.raises(ZtError):
        split_front_matter("---\n- a\n- b\n---\n")


def test_numeric_looking_code_is_read_as_text():
    # YAML 会把 2026-007 之外的纯数字当整数；编号仍按字符串返回
    assert read_project_doc("---\n项目编号: 2026-007\n阶段: 审定\n---\n")["阶段"] == "审定"


def test_sections_tables_and_bullets():
    assert find_section(DOC, "不存在") is None
    rows = section_table(DOC, "关键文件指引")
    assert rows == [{"资料": "合同", "位置": "资料/合同.pdf", "备注": "已核对"}, {"资料": "图纸", "位置": "", "备注": ""}]
    assert section_bullets(DOC, "已出成果") == ["成果/报告.docx", "成果/汇总.xlsx"]
    assert section_bullets(DOC, "基本信息") == [] and section_table(DOC, "已出成果") == []


def test_replace_section_replaces_or_appends_and_keeps_the_rest():
    out = replace_section(DOC, "已出成果", "- 成果/新.docx")
    assert section_bullets(out, "已出成果") == ["成果/新.docx"]
    assert out.count("## ") == DOC.count("## ") and "## 工作记录\n\n无。" in out
    added = replace_section(DOC, "目录概览", "- 资料/ 3 个文件")
    assert added.rstrip().endswith("- 资料/ 3 个文件") and "## 目录概览" in added


def test_set_front_matter_fields_updates_or_adds_without_touching_body():
    out = set_front_matter_fields(DOC, {"阶段": "结算", "状态": "已归档"})
    fields = read_project_doc(out)
    assert fields["阶段"] == "结算" and fields["状态"] == "已归档" and fields["工程名称"] == "某:工程 #1"
    assert out.split("---\n", 2)[2] == DOC.split("---\n", 2)[2]
    with pytest.raises(ZtError):
        set_front_matter_fields("没有头", {"阶段": "x"})


def test_render_template_modes_and_missing_fields():
    tpl = "---\n名: {{名|yaml}}\n别名: {{别名|yaml}}\n---\n# {{名}} {{别名}} {{空}}"
    out = render_template(tpl, {"名": '含"引号"的:名', "别名": ["a", "b"], "空": None})
    assert read_project_doc(out + "\n")["名"] == '含"引号"的:名'
    assert out.endswith('# 含"引号"的:名 [a, b] ')
    with pytest.raises(ZtError) as e:
        render_template("{{缺}}", {})
    assert e.value.code == "template_field_missing"


def test_write_text_atomic_lf_and_parent_dirs(tmp_path):
    p = write_text_atomic(tmp_path / "新 目录" / "文件.md", "a\nb\n")
    assert p.read_bytes() == b"a\nb\n" and not list(p.parent.glob(".*.tmp"))
