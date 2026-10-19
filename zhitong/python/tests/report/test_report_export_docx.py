# 来源：engine-service/tests/test_report_export_docx.py（zhitong-cost-ai@991ff5c，W3 搬入；去掉 HTTP 端点用例，只改了 import）
"""docx 导出（WS12-B P09，issue #758）：zipfile + ElementTree 逐个部件解析。

改前（生产 r/w 取证）：47 段里 19 段空段、章标题重复、只有 Normal 一种段落样式、无任何「AI 初稿」标记；
正文里一个 \\x0b 就让整份 docx 打不开。
"""
from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET

from zt.report.export import APPENDIX_TITLE, DEFAULT_DISCLAIMER, build_docx

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _parts(b: bytes) -> dict[str, ET.Element]:
    z = zipfile.ZipFile(io.BytesIO(b))
    return {n: ET.fromstring(z.read(n)) for n in z.namelist()}


def _paragraphs(doc: ET.Element) -> list[tuple[str, str]]:
    out = []
    for p in doc.iter(f"{W}p"):
        st = p.find(f"{W}pPr/{W}pStyle")
        text = "".join(t.text or "" for t in p.iter(f"{W}t"))
        out.append((st.get(f"{W}val") if st is not None else "", text))
    return out


SECTIONS = [
    {"title": "一、项目概况", "content": "一、项目概况\n\n\n工程位于某市。[资料1]\n\n合同价 329388 元。",
     "quality": "ok"},
    # WS24-g：护栏标过的数在正文里有【待核】、缺的分项在正文里是【待补】（与生产落库的形状一致）；附录从正文数
    {"title": "五、审核结果",
     "content": "审定金额 319786 元\x0b（含垂直制表符），较送审减少1935元【待核：资料中未找到此数】。\x0c"
                "安装工程：【待补：安装工程分项】",
     "quality": "partial", "flags": [{"kind": "unbacked_number", "text": "1935元", "message": "资料中找不到"}],
     "missing_items": ["安装工程分项"]},
]
APPENDIX = {"source_files": ["审定单.xlsx", "施工合同.pdf"], "unreadable_files": ["审核版.GBQ7"],
            "hidden_sheets": ["审定单.xlsx：示例（隐藏）"]}


def _build(**kw):
    return build_docx("某某项目结算审核报告（AI 初稿）", SECTIONS, appendix=APPENDIX, **kw)


def test_all_parts_present_and_parse_even_with_control_chars():
    parts = _parts(_build())
    assert set(parts) == {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml",
                          "word/header1.xml", "word/_rels/document.xml.rels"}
    ct = ET.tostring(parts["[Content_Types].xml"], encoding="unicode")
    assert "/word/styles.xml" in ct and "/word/header1.xml" in ct


def test_header_carries_disclaimer():
    hdr = ET.tostring(_parts(_build())["word/header1.xml"], encoding="unicode")
    assert DEFAULT_DISCLAIMER in hdr
    hdr2 = ET.tostring(_parts(_build(disclaimer="自定义声明"))["word/header1.xml"], encoding="unicode")
    assert "自定义声明" in hdr2


def test_document_references_header_and_styles_have_east_asia_fonts():
    parts = _parts(_build())
    doc = ET.tostring(parts["word/document.xml"], encoding="unicode")
    assert "headerReference" in doc
    styles = parts["word/styles.xml"]
    ids = {s.get(f"{W}styleId") for s in styles.iter(f"{W}style")}
    assert {"Normal", "Title", "Heading1"} <= ids
    for f in styles.iter(f"{W}rFonts"):
        assert f.get(f"{W}eastAsia"), "中文字体必须显式设 eastAsia"


def test_no_empty_paragraphs_and_title_not_repeated():
    paras = _paragraphs(_parts(_build())["word/document.xml"])
    assert all(text.strip() for _, text in paras), [p for p in paras if not p[1].strip()]
    assert [t for _, t in paras].count("一、项目概况") == 1, "章标题只出现一次"
    styles = {st for st, _ in paras}
    assert {"Title", "Heading1", "Normal"} <= styles


def test_appendix_lists_sources_quality_todo_and_verify():
    texts = [t for _, t in _paragraphs(_parts(_build())["word/document.xml"])]
    assert APPENDIX_TITLE in texts
    joined = "\n".join(texts)
    assert "审定单.xlsx、施工合同.pdf" in joined
    assert "无法读取的资料：审核版.GBQ7" in joined
    assert "已跳过隐藏工作表：审定单.xlsx：示例（隐藏）" in joined
    assert "五、审核结果：含待核 1 处" in texts, "标签按正文里【待核】的处数（WS24-g）"
    i = texts.index("待补清单：")
    assert texts[i + 1] == "五、审核结果：安装工程分项"
    j = texts.index("待核清单：")
    assert texts[j + 1] == "五、审核结果：较送审减少1935元（资料中未找到此数）"


def test_table_section_renders_real_table():
    b = build_docx("t", [{"title": "五、审核结果", "content": "见下表。",
                          "table": {"headers": ["分项", "送审"], "rows": [["建筑工程", "321721"]]}}])
    doc = _parts(b)["word/document.xml"]
    assert len(list(doc.iter(f"{W}tbl"))) == 1


# zt 改动：旧的 test_export_endpoint_accepts_new_fields 测 FastAPI 端点（响应头 filename*），端点已去掉；
# 导出子命令的等价用例在 tests/report/test_cli.py（test_export_*）。


# ================================================================ WS24-g 附录：标签与清单从正文数（issue #947，R24-37 / R24-08）

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from zt.report.export import section_label  # noqa: E402

_G = {c["id"]: c for c in json.loads(
    (Path(__file__).parent / "fixtures" / "report_guard" / "ws24g_realrun.json").read_text(encoding="utf-8"))["chapters"]}
_V = "【待核：资料中未找到此数】"
_TRUNC = "【待补：本章内容超出篇幅上限，后面没有写完】"


def _f(kind, n=1):
    return [{"kind": kind, "text": f"t{i}", "message": "m"} for i in range(n)]


@pytest.mark.parametrize("sec, label", [
    ({"quality": "failed", "content": "【待补：本章未生成】"}, "未生成"),
    ({"quality": "partial", "content": "甲乙丙丁。\n" + _TRUNC}, "未写完"),
    ({"quality": "partial", "content": f"甲1{_V}乙2{_V}。\n" + _TRUNC}, "未写完 · 含待核 2 处"),
    ({"quality": "insufficient", "content": _G["E-shendingdan"]["stored"]}, "资料不足（待补 23 处）"),
    ({"quality": "insufficient", "content": "【待补：本章缺少相关资料】"}, "资料不足"),
    ({"quality": "empty", "content": "【待补：本章没有可读取的资料，未调用 AI 生成】"}, "资料不足"),
    # flags 4 条、正文【待核】3 处：标签说的是正文里的 3 处
    ({"quality": "partial", "content": f"甲1{_V}乙2{_V}丙3{_V}。", "flags": _f("unbacked_number", 3) + _f("unknown_citation")},
     "含待核 3 处"),
    ({"quality": "partial", "content": f"甲1{_V}乙2{_V}丙3{_V}。", "flags": _f("unbacked_number", 3) + _f("transcribed")},
     "含待核 3 处 · 疑似转写"),
    ({"quality": "partial", "content": "照抄的成稿。", "flags": _f("transcribed")}, "疑似转写"),
    ({"quality": "partial", "content": "甲[资料9]乙[资料8]。", "flags": _f("unknown_citation", 2)}, "引用编号有误 2 处"),
    # 运行 A 的 8 个 done 章：partial 只因为相关内容没送入，flags 空、正文 0 处【待核】—— 改前写「含待核」
    ({"quality": "partial", "content": _G["A-qtxmf"]["stored"], "flags": []}, "AI 初稿·待核"),
    ({"quality": "ok", "content": "正文[资料1]。"}, "AI 初稿·待核"),
])
def test_section_label_matches_the_screen(sec, label):
    assert section_label({"title": "x", **sec}) == label


def _appendix_texts(sections):
    texts = [t for _, t in _paragraphs(_parts(build_docx("t", sections, appendix={}))["word/document.xml"])]
    return texts[texts.index(APPENDIX_TITLE):]


def test_todo_list_comes_from_the_body_one_line_per_chapter():
    secs = [{"title": "一、概况", "quality": "partial",
             "content": "面积【待补：面积】，层数【待补：层数】。结构【待补：结构形式】；面积【待补：面积】。"},
            {"title": "二、范围", "quality": "ok", "content": "范围见图纸[资料1]。"}]
    texts = _appendix_texts(secs)
    i = texts.index("待补清单：")
    assert texts[i + 1] == "一、概况：面积；层数；结构形式", "3 处不同的【待补】列 3 条，同章去重"
    assert not any(t.startswith("二、范围：") and "；" in t for t in texts[i + 1:i + 3])
    none = _appendix_texts([{"title": "二、范围", "quality": "ok", "content": "范围见图纸[资料1]。"}])
    assert "待补清单：无" in none


def test_run_a_shape_no_longer_says_todo_none_and_no_verify_contradiction():
    """运行 A：8 章 partial（flags 空、正文 0 处【待核】），正文 29 处【待补】—— 改前附录写「待补清单：无」，
    各章写「含待核」、下一行「待核清单：无」。"""
    secs = [{"title": f"第{i}章", "quality": "partial", "content": _G[cid]["stored"], "flags": []}
            for i, cid in enumerate(["A-qtxmf", "B-gongxing"], 1)]
    texts = _appendix_texts(secs)
    assert "待补清单：无" not in texts
    assert not any("含待核" in t for t in texts), "正文 0 处【待核】的章不写含待核"
    assert "待核清单：无" in texts


def test_verify_list_one_line_each():
    """运行 B 第三章正文 52 处【待核】：改前用「；」挤成一段，现在每条一行，前面是被标的那几个字。"""
    content = _G["B-yiju"]["stored"]
    n = content.count("【待核")
    assert n == 52
    texts = _appendix_texts([{"title": "三、编制依据", "quality": "partial", "content": content, "flags": []}])
    j = texts.index("待核清单：")
    lines = [t for t in texts[j + 1:] if t.startswith("三、编制依据：")]
    assert len(lines) == n
    assert lines[0] == "三、编制依据：土石方工程使用010101002（资料中未找到此数）"
    assert lines[1] == "三、编制依据：010101003（资料中未找到此数）", "小句以顿号为界"
    assert "三、编制依据：含待核 52 处" in texts


def test_verify_list_also_names_flags_that_insert_no_mark():
    texts = _appendix_texts([{"title": "五、结果", "quality": "partial", "content": "甲[资料9]。",
                              "flags": [{"kind": "unknown_citation", "text": "[资料9]", "message": "引用了不存在的资料编号 9"}]}])
    assert "五、结果：引用编号有误 1 处" in texts
    j = texts.index("待核清单：")
    assert texts[j + 1] == "五、结果：[资料9]（引用了不存在的资料编号 9）"


def test_body_drops_a_first_line_that_repeats_the_title_with_another_ordinal():
    texts = [t for _, t in _paragraphs(_parts(build_docx("t", [{"title": "三、编制依据", "content": "一、编制依据\n正文。"}]))
                                       ["word/document.xml"])]
    body = texts[:texts.index(APPENDIX_TITLE)]
    assert body == ["t", "三、编制依据", "正文。"]
