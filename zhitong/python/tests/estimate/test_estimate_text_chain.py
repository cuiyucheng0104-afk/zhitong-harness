# 来源：engine-service/tests/test_estimate_text_chain.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""WS10-P13（issue #761）：概算抽取的 PDF 文本层判定改走 WS04 的质量感知入口。

改前 `api/estimate.py::_read_text` 只判「文字层非空」：乱码 / 极短的文字层直接当正文，
跳过旁车与 OCR，最后报 not_found 而不是 no_text（与 WS04 SYS:02 同根因）。
现在一律经 `text_chain.load_document_text`（统一约定 C6）：按页判可用 → 旁车 → OCR，
降级链走完仍无正文才落 no_text，且 detail 写明原因。

PDF 与旁车全部现造（复用 WS04 的 `_ws04_fixtures`），LLM 打桩、OCR 不联网。
"""
from __future__ import annotations

import json
import shutil

import pytest
from pypdf import PdfWriter

from zt.estimate import extract as estimate_extract
from tests.textextract import ws04_fixtures as fx
from tests.estimate.fixtures import endpoint
from tests.estimate.fixtures.endpoint import HEADERS, client  # zt 改动：旧端点的转接

_DIR = "_engine_test/estimate_text_chain"


def _headers():
    return HEADERS


class _U:
    prompt_tokens = 1
    completion_tokens = 1
    latency_ms = 1
    model = "stub"
    finish_reason = ""
    cache_hits = 0


@pytest.fixture
def put():
    d = endpoint.ROOT / _DIR   # zt 改动：文件落在转接的临时项目目录
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)

    def _put(name: str, content: bytes, sidecar: str | None = None) -> dict:
        (d / name).write_bytes(content)
        if sidecar is not None:
            (d / f"{name}.ocr.txt").write_text(sidecar, encoding="utf-8")
        return {"file_id": name, "rel_path": f"{_DIR}/{name}", "file_name": name}

    yield _put
    shutil.rmtree(d, ignore_errors=True)


def _ocr(monkeypatch, ready: bool):
    """zt 改动：没有 OCR 服务（扫描件靠旁车或 read_image），这里不再切换开关。"""


def _stub_llm(monkeypatch, seen: list[str]):
    def fake_chat(messages, **kw):
        seen.append(messages[0]["content"])
        return json.dumps({"buildings": [], "checks": {}, "cells": {
            "经济技术指标!D4": [{"value": "12000", "quote": "用地面积 12000 平方米"}]}},
            ensure_ascii=False), _U()
    monkeypatch.setattr(endpoint, "AGENT", fake_chat)


def _garbled_pdf() -> bytes:
    w = PdfWriter()
    fx.add_garbled_page(w)
    return fx.to_bytes(w)


def _blank_pdf(pages: int = 2) -> bytes:
    # 页数与 F1 旁车卷头（2 页）一致，旁车才能按页对位（页数对不上时 WS04 不按页采用）
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    return fx.to_bytes(w)


def test_garbled_text_layer_with_sidecar_reads_the_sidecar(put, monkeypatch):
    """文字层是乱码（非空！）、同名旁车有正文 → text_source = ocr_sidecar，正文取自旁车。

    改前：`extract_text` 取到一串私用区字符，`not text.strip()` 为假 → 当 text_layer 直接送 LLM，
    旁车被跳过。变异：_read_text 恢复「文字层非空就用」→ 本条转红。
    """
    _ocr(monkeypatch, False)
    sidecar = fx.paged_sidecar([("ok", ["项目概况：用地面积 12000 平方米，总建筑面积 30000 平方米。"])],
                               name="设计说明.pdf")
    f = put("设计说明.pdf", _garbled_pdf(), sidecar)
    seen: list[str] = []
    _stub_llm(monkeypatch, seen)
    r = client.post("/engine/estimate/extract", headers=_headers(), json={"files": [f]})
    assert r.status_code == 200, r.text
    body = r.json()
    d4 = next(c for c in body["candidates"] if c["cell"] == "经济技术指标!D4")
    assert d4["text_source"] == "ocr_sidecar"
    assert d4["confidence"] == 1.0            # 引文在旁车正文里、值在引文里
    assert "用地面积 12000 平方米" in seen[0]   # 送给模型的是旁车正文，不是乱码


def test_failed_sidecar_without_ocr_is_no_text_with_the_reason(put, monkeypatch):
    """空白扫描件 + 全失败旁车（生产 754 份那种）+ OCR 未配置 → 不再是 not_found：
    单文件 422、说清「扫描件、OCR 未配置」；与一份有字的文件同送 → 200 + no_text 带原因。"""
    _ocr(monkeypatch, False)
    scan = put("扫描件.pdf", _blank_pdf(), fx.F1)
    r = client.post("/engine/estimate/extract", headers=_headers(), json={"files": [scan]})
    assert r.status_code == 422, r.text
    assert "旁车" in r.json()["detail"]

    good = put("说明.txt", "用地面积 12000 平方米".encode("utf-8"))
    seen: list[str] = []
    _stub_llm(monkeypatch, seen)
    r = client.post("/engine/estimate/extract", headers=_headers(), json={"files": [good, scan]})
    assert r.status_code == 200, r.text
    nt = [u for u in r.json()["unresolved"] if u["reason"] == "no_text"]
    assert len(nt) == 1 and nt[0]["source_file_id"] == "扫描件.pdf"
    # detail 写明原因（失败码 + 人话），不再是一句笼统的「可能是扫描件」
    # zt 改动：没有 OCR 服务，失败码是 needs_vision（由 agent 用 read_image 看图补旁车）
    assert "（needs_vision）" in nt[0]["detail"] and "旁车" in nt[0]["detail"]


def test_partly_scanned_pdf_discloses_missing_pages(put, monkeypatch):
    """有正文但缺页（混合 PDF 的扫描页没识别）→ 200 + source_text_incomplete，缺页不吞（C5）。"""
    _ocr(monkeypatch, False)
    w = PdfWriter()
    fx.add_text_page(w, "Land area 12000 square meters, gross floor area 30000 square meters")
    fx.add_image_page(w)
    f = put("混合.pdf", fx.to_bytes(w))
    seen: list[str] = []
    _stub_llm(monkeypatch, seen)
    r = client.post("/engine/estimate/extract", headers=_headers(), json={"files": [f]})
    assert r.status_code == 200, r.text
    w = [x for x in r.json()["warnings"] if x["code"] == "source_text_incomplete"]
    assert len(w) == 1 and "第 2 页" in w[0]["message"]


@pytest.mark.skip(reason="zt 没有 OCR 服务：「OCR 服务不可用 → 502」没有对应物")
def test_ocr_unavailable_for_every_file_is_502():
    pass
