"""页级降级链：文字层 → 旁车 → 缺页（需看图）；DocText 不变量；页眉页码去除；page_limit / max_chars。

迁移自旧仓 engine-service/tests/test_doc_text_pages.py（旧 WS04-P2）。
改动：OCR 服务一档已不存在，原「混合 PDF 的扫描页交给 OCR」的用例改成「扫描页只靠旁车，没有旁车就记缺页、
failure=needs_vision」；OCR 预算 / 熔断用例不迁移；HTTP 异常改为 ZtError。

PDF 全在测试里用 pypdf 现造，六种页型见 tests/textextract/ws04_fixtures.py：文字页、真空白页、1×1 图像页、
只有矢量路径的页（内容流 > 64 字节）、只有 CamScanner 水印的页、私用区字符乱码页。
"""
from __future__ import annotations

import pytest

from tests.textextract import ws04_fixtures as fx
from zt.common import ZtError
from zt.textextract.extract import extract_text, load_document
from zt.textextract.model import DocText, ExtractFailure
from zt.textextract.pdf import SCANNED_PAGE_REASON, page_status, pdf_page_texts, strip_running_headers


@pytest.fixture
def root(tmp_path):
    return tmp_path


def _put(root, name: str, data: bytes | str) -> str:
    p = root / name
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return name


# ---------------------------------------------------------------- 页状态判定


def test_page_status_kinds():
    raw = pdf_page_texts(fx.build_pdf(["text", "blank", "image", "vector", "watermark", "garbled"]))
    got = [(page_status(p.text, p.has_image, p.content_len).status,
            page_status(p.text, p.has_image, p.content_len).flags) for p in raw]
    assert got == [
        ("usable", ()),
        ("blank", ()),
        ("scanned", ()),
        ("scanned", ()),
        ("scanned", ("watermark_only",)),
        ("scanned", ("garbled",)),
    ]


def test_page_status_uni_escapes_decoded():
    text = "/uni4E2D/uni534E/uni4EBA/uni6C11/uni5171/uni548C/uni56FD" * 3
    st = page_status(text, False, 500)
    assert st.status == "usable"
    assert "中华人民共和国" in st.text


# ---------------------------------------------------------------- 混合 PDF


def test_mixed_pdf_scanned_pages_without_sidecar_are_missing(root):
    """R23 形状：6 页里第 4、6 页是扫描页，没有旁车。文字层页照出，扫描页记缺页并提示看图。"""
    rel = _put(root, "R23.pdf", fx.build_pdf(["text", "text", "blank", "image", "text", "vector"]))
    doc = load_document(root, rel)
    assert doc.pages_text_layer == [1, 2, 5]
    assert doc.pages_blank == [3]
    assert doc.pages_missing == [4, 6]
    assert doc.text_source == "text_layer"
    assert doc.complete is False
    assert fx.text_line(5) in doc.text
    assert f"[p4] ｜未取得正文（{SCANNED_PAGE_REASON}）" in doc.text
    assert "read_image" in SCANNED_PAGE_REASON
    prov = doc.provenance()
    assert prov["pages_total"] == 6 and prov["pages_ok"] == [1, 2, 5] and prov["pages_missing"] == [4, 6]


def test_purely_scanned_pdf_without_sidecar_fails_with_needs_vision(root):
    rel = _put(root, "纯扫描.pdf", fx.build_pdf(["image", "image"]))
    doc = load_document(root, rel)
    assert doc.text == ""
    assert doc.text_source == "none"
    assert doc.failure is not None and doc.failure.code == "needs_vision"
    assert doc.pages_missing == [1, 2]
    assert "read_image" in doc.failure.detail


@pytest.mark.parametrize("kind", ["blank", "image"])
def test_sidecar_pages_fill_scanned_pages(root, kind):
    """3 页扫描 PDF + 旁车（p1 ok、p2 failed、p3 ok）：p1、p3 取旁车，p2 仍缺。"""
    rel = _put(root, "扫描件.pdf", fx.build_pdf([kind] * 3))
    _put(root, "扫描件.pdf.ocr.txt", fx.paged_sidecar([
        ("ok", ["第一页旁车正文 合同金额 100 万元"]), ("failed", []), ("ok", ["第三页旁车正文"])]))
    doc = load_document(root, rel)
    assert doc.pages_sidecar == [1, 3]
    assert doc.pages_missing == [2]
    assert doc.text_source == "ocr_sidecar"
    assert doc.ocr_derived is True
    assert "第一页旁车正文" in doc.text and "第三页旁车正文" in doc.text
    assert "sidecar_pages:2" in doc.quality_flags
    assert doc.complete is False


def test_sidecar_all_pages_ok_makes_complete(root):
    rel = _put(root, "全旁车.pdf", fx.build_pdf(["image", "image"]))
    _put(root, "全旁车.pdf.ocr.txt", fx.paged_sidecar([("ok", ["甲页正文"]), ("ok", ["乙页正文"])]))
    doc = load_document(root, rel)
    assert doc.pages_sidecar == [1, 2] and doc.complete is True
    assert doc.text_source_detail == "ocr_sidecar"


def test_text_layer_wins_over_sidecar(root):
    """文字层可用的页不读旁车：原生文字层永远比 OCR 结果准。"""
    rel = _put(root, "有字.pdf", fx.build_pdf(["text", "image"]))
    _put(root, "有字.pdf.ocr.txt", fx.paged_sidecar([("ok", ["旁车一页"]), ("ok", ["旁车二页"])]))
    doc = load_document(root, rel)
    assert doc.pages_text_layer == [1] and doc.pages_sidecar == [2]
    assert "旁车一页" not in doc.text and "旁车二页" in doc.text
    assert doc.text_source_detail == "mixed"


def test_use_sidecar_false_ignores_sidecar(root):
    rel = _put(root, "不用旁车.pdf", fx.build_pdf(["image"]))
    _put(root, "不用旁车.pdf.ocr.txt", fx.paged_sidecar([("ok", ["旁车正文"])]))
    doc = load_document(root, rel, use_sidecar=False)
    assert doc.failure is not None and doc.failure.code == "needs_vision"


def test_blank_page_with_failed_sidecar_verdict_becomes_missing(root):
    """旁车说「识别失败、不是空白页」：这页不当空白，记缺页。"""
    rel = _put(root, "空白冒充.pdf", fx.build_pdf(["text", "blank"]))
    _put(root, "空白冒充.pdf.ocr.txt", fx.paged_sidecar([("ok", ["甲"]), ("failed", [])]))
    doc = load_document(root, rel)
    assert doc.pages_missing == [2]


def test_watermark_and_garbled_pages_are_scanned_candidates(root):
    rel = _put(root, "水印.pdf", fx.build_pdf(["text", "watermark", "garbled"]))
    doc = load_document(root, rel)
    assert doc.pages_missing == [2, 3]
    assert "watermark_only" in doc.quality_flags and "garbled" in doc.quality_flags


def test_image_file_needs_vision_unless_sidecar(root):
    _put(root, "现场.jpg", b"\xff\xd8\xff\xe0 fake jpeg")
    doc = load_document(root, "现场.jpg")
    assert doc.failure is not None and doc.failure.code == "needs_vision"
    _put(root, "现场.jpg.ocr.txt", "某某工程现场签证单")
    doc = load_document(root, "现场.jpg")
    assert doc.failure is None and doc.text_source == "ocr_sidecar" and "签证单" in doc.text
    assert doc.complete is True


def test_running_headers_removed_on_six_pages(root):
    """6 页计价表：页眉只留首页一份、页码全删；≤40 字且逐页数值不同的清单行和本页小计一行不少。"""
    rel = _put(root, "页眉.pdf", fx.build_pdf(["ledger"] * 6))
    doc = load_document(root, rel)
    assert doc.text.count(fx.LEDGER_HEADER) == 1
    for i in range(1, 7):
        assert f"- {i} -" not in doc.text
    assert "running_headers_removed:11" in doc.quality_flags  # 5 份页眉 + 6 个页码
    for i in range(1, 7):
        for line in fx.ledger_lines(i)[1:5]:
            assert line in doc.text, line
    assert doc.complete is True


def test_running_headers_use_real_page_numbers_in_mixed_pdf(root):
    """混合 PDF 的文字层页不连续（1、3、4、5）：页码要按真实页号对，第 1 页的「- 1 -」也得删。"""
    rel = _put(root, "混合页码.pdf", fx.build_pdf(["ledger", "image", "ledger", "ledger", "ledger"]))
    doc = load_document(root, rel)
    assert doc.pages_text_layer == [1, 3, 4, 5]
    for i in (1, 3, 4, 5):
        assert f"- {i} -" not in doc.text
        for line in fx.ledger_lines(i)[1:5]:
            assert line in doc.text, line


def test_strip_running_headers_skips_short_docs():
    pages = ["页眉\n正文一", "页眉\n正文二", "页眉\n正文三"]
    assert strip_running_headers(pages) == (pages, 0)


_SUBTOTALS = ["1,204,356.78", "86,210.00", "455,102.35", "3,300,000.00", "12,000.50", "98,765.43"]


def _ledger_page(no: int, subtotal: str) -> str:
    return "\n".join([
        "某某工程 分部分项工程量清单计价表",
        f"序号 {3 * no - 2} 挖土方 m3 {100 + no}.5",
        f"序号 {3 * no - 1} 回填土 m3 {200 + no}.25",
        f"序号 {3 * no} 余方弃置 m3 {30 + no}.75",
        f"本页小计 {subtotal}",
        f"第 {no} 页 共 6 页",
    ])


def test_strip_keeps_per_page_subtotals():
    """负控（评审①）：「本页小计 <金额>」逐页不同，数字归一后 4 页撞成「本页小计 #,#.#」——
    旧实现删掉第 3、5、6 页的小计（removed=19）。只许删页眉 5 份 + 页码 6 个。"""
    pages = [_ledger_page(i, s) for i, s in enumerate(_SUBTOTALS, start=1)]
    out, removed = strip_running_headers(pages)
    assert removed == 11
    for i, (page, s) in enumerate(zip(out, _SUBTOTALS), start=1):
        assert f"本页小计 {s}" in page
        assert f"序号 {3 * i - 2} 挖土方 m3 {100 + i}.5" in page
        assert f"第 {i} 页" not in page
    assert sum(p.count("某某工程 分部分项工程量清单计价表") for p in out) == 1


def test_strip_keeps_short_body_on_three_line_pages():
    """负控（评审②）：每页只有 页眉 / ≤40 字正文 / 页码 三行 —— 正文 6 页都得在。"""
    pages = ["\n".join(["某某工程资源量报告", "控制资源量 29.78 万m3", f"- {i} -"]) for i in range(1, 7)]
    out, _ = strip_running_headers(pages)
    assert [("控制资源量 29.78 万m3" in p) for p in out] == [True] * 6
    assert not any(f"- {i} -" in p for i, p in enumerate(out, start=1))


def test_strip_never_empties_short_pages():
    """负控（评审③）：4 页短页、每行都在首尾 2 行里 —— 旧实现把第 2–4 页删空，仍记 text_layer、
    complete=True。短页不做页眉去重；任何一页都不许删空。"""
    pages = ["\n".join(["工程概况", f"第{i}节 说明", f"{i}"]) for i in range(1, 5)]
    out, removed = strip_running_headers(pages)
    assert out == ["\n".join(["工程概况", f"第{i}节 说明"]) for i in range(1, 5)]
    assert removed == 4
    only_no = ["- 1 -", "- 2 -", "- 3 -", "- 4 -"]
    out2, removed2 = strip_running_headers(only_no)
    assert out2 == only_no and removed2 == 0


def test_strip_keeps_lone_integers_that_do_not_track_page_numbers():
    """页边单独成行的工程量（1200、36、458、7）形状像页码，但对不上页序，不是纯页码行。"""
    qty = ["12", "13", "458", "1200"]  # 12、13 在相邻两页上恰好差同一个常数：两页不够认页码
    pages = ["\n".join(["工程量汇总", f"分项{c}", "混凝土 C30", "钢筋 HRB400", q])
             for c, q in zip("甲乙丙丁", qty)]
    out, _ = strip_running_headers(pages)
    assert [p.splitlines()[-1] for p in out] == qty


def test_strip_decimal_parts_are_not_page_number_evidence():
    """小数的整数部分不算「随页号走的数字」：桩长 101.5 / 102.5 / … 逐页 +1，若把 101、102 拆出来
    当证据，偏移 100 就成了「页码」，第 3 页单独成行的工程量 103 会被当页码删掉。"""
    qty = ["7", "36", "103", "458"]
    pages = ["\n".join(["工程量计算书", f"分项{c}", "说明", f"桩长 {100 + i}.5 m", q])
             for i, (c, q) in enumerate(zip("甲乙丙丁", qty), start=1)]
    out, _ = strip_running_headers(pages)
    assert [p.splitlines()[-1] for p in out] == qty


def test_strip_amount_lines_with_page_number_compared_verbatim():
    """带金额的行只逐字比：「第 N 页 本页小计 5,000.00」逐页金额相同，但页号不同就不是同一行
    —— 不许把页号归一后当页脚删掉第 2–6 页的小计。"""
    pages = ["\n".join(["付款计划表", f"{c}期 进度款", "按月支付", "备注 无", f"第 {i} 页 本页小计 5,000.00"])
             for i, c in zip(range(1, 7), "甲乙丙丁戊己")]
    out, _ = strip_running_headers(pages)
    for i, p in enumerate(out, start=1):
        assert f"第 {i} 页 本页小计 5,000.00" in p


def test_strip_page_numbers_with_fixed_offset():
    """封面、目录不编号：物理第 3 页印「1」。页码 = 页号 − 2，仍按页码删；随页号走的
    页眉（「第 N 页」嵌在标题行里）归一后去重。"""
    tags = "甲乙丙丁戊己"
    pages = ["\n".join([f"咨询报告 第 {i - 2} 页", f"{c}段正文 说明文字", "正文续行", f"{c}段末行", f"{i - 2}"])
             for i, c in zip(range(3, 9), tags)]
    out, removed = strip_running_headers(pages, list(range(3, 9)))
    assert removed == 6 + 5
    assert out[0].splitlines()[0] == "咨询报告 第 1 页"
    for p, c in zip(out, tags):
        assert p.splitlines() == ([f"咨询报告 第 1 页"] if c == "甲" else []) + [
            f"{c}段正文 说明文字", "正文续行", f"{c}段末行"]


def test_extract_text_blank_pdf_stays_empty():
    """守门：只要正文字符串的出口对 PDF 不加页锚，否则扫描件变非空串，「整份判空」全失效。"""
    assert extract_text(fx.build_pdf(["blank", "image", "blank"]), "pdf") == ""


def test_sidecar_page_count_mismatch_adopts_whole(root):
    rel = _put(root, "对不上.pdf", fx.build_pdf(["image", "image"]))
    _put(root, "对不上.pdf.ocr.txt", fx.paged_sidecar(
        [("ok", ["甲"]), ("ok", ["乙"]), ("ok", ["丙页正文"])]))
    doc = load_document(root, rel)
    assert doc.text_source == "ocr_sidecar"
    assert "丙页正文" in doc.text
    assert "sidecar_page_count_mismatch" in doc.quality_flags
    assert doc.complete is False


def test_invariant_blank_text_requires_failure():
    with pytest.raises(ValueError):
        DocText(text="", text_source="text_layer")
    with pytest.raises(ValueError):
        DocText(text="正文", text_source="text_layer", failure=ExtractFailure("no_text", "x"))
    with pytest.raises(ValueError):
        DocText(text="", text_source="none")


def test_path_errors_are_zt_errors(root):
    with pytest.raises(ZtError) as e:
        load_document(root, "../../etc/passwd")
    assert e.value.code == "invalid_path"
    with pytest.raises(ZtError) as e:
        load_document(root, "不存在.pdf")
    assert e.value.code == "file_not_found"


def test_page_limit_reads_only_first_pages(root):
    """tag 取首页信号用 page_limit=1：只处理第 1 页，截断如实记下。"""
    rel = _put(root, "五页.pdf", fx.build_pdf(["text"] * 5))
    doc = load_document(root, rel, page_limit=1)
    assert doc.pages_total == 5
    assert doc.pages_text_layer == [1]
    assert doc.truncated is True and doc.complete is False
    assert fx.text_line(1) in doc.text and fx.text_line(2) not in doc.text


def test_max_chars_cuts_on_page_boundary(root):
    rel = _put(root, "字数.pdf", fx.build_pdf(["text"] * 4))
    full = load_document(root, rel)
    budget = len(full.text) // 2
    doc = load_document(root, rel, max_chars=budget)
    assert "char_capped" in doc.quality_flags
    assert doc.truncated is True and doc.complete is False
    assert len(doc.text) <= len(full.text)
    kept = [i for i in range(1, 5) if fx.text_line(i) in doc.text]
    assert kept and kept == list(range(1, len(kept) + 1)), kept  # 整页保留，前缀连续
    assert doc.pages_missing == list(range(len(kept) + 1, 5))
    assert "超过本次调用的字数上限" in doc.text


def test_max_chars_first_page_alone_over_budget(root):
    """首页自身超限只能页内截断；此后的页一律算超限（哪怕它们短到装得下剩余预算）。"""
    from pypdf import PdfWriter

    w = PdfWriter()
    fx.add_text_page(w, fx.text_line(1), extra_lines=[fx.text_line(1)] * 8)
    fx.add_text_page(w, fx.text_line(2))
    fx.add_text_page(w, fx.text_line(3))
    rel = _put(root, "首页超长.pdf", fx.to_bytes(w))
    doc = load_document(root, rel, max_chars=120)
    assert doc.failure is None and doc.text
    assert doc.pages_missing == [2, 3]
    assert fx.text_line(2) not in doc.text
