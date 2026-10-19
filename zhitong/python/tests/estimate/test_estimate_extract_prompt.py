"""概算抽取说明的版本钉：改了措辞（或策略里的抽取口径）而不升 ESTIMATE_PROMPT_VERSION → 红。

旧仓按提示词 hash 钉缓存键（test_llm_chat_json.py）；zt 没有模型缓存，但 prompt_version 仍写进 prepare 结果与
抽取说明文件头，用来分辨「这份 answers 是按哪一版说明作答的」。升版本时在 PINS 里追加一行，历史行不许改。
"""
from __future__ import annotations

import hashlib

from zt.estimate import extract as ex
from zt.estimate import policy as estimate_policy

PINS = {
    # zt：agent 作答，正文另存、回答按 file_id 分份（policy gsyz_v1.policy.2026-10-06）
    "estimate-extract/v3-zt1": "f2e6f6bcb8fdc1ad69e3541c18dbccd8dc6d3329aaba455440d75eee4604e86a",
}


def _instructions() -> str:
    pol = estimate_policy.load_policy("gsyz_v1")
    return ex.instructions(ex.cell_hint_specs("gsyz_v1", pol), estimate_policy.extract_checks(pol),
                           bool(estimate_policy.slot_cells(pol)))


def test_prompt_version_pinned():
    digest = hashlib.sha256(_instructions().encode("utf-8")).hexdigest()
    assert ex.ESTIMATE_PROMPT_VERSION in PINS, "升了版本号就在 PINS 里登记新指纹"
    assert PINS[ex.ESTIMATE_PROMPT_VERSION] == digest, (
        f"抽取说明变了（sha256={digest}），但 ESTIMATE_PROMPT_VERSION 没升")


def test_prompt_keeps_the_red_lines():
    text = _instructions()
    assert "严禁输出任何金额、造价、费用数字" in text
    assert "quote 必须是能在正文里逐字找到的原文片段" in text
    assert "全部列出" in text and "不要自行选择" in text
    assert "file_id 照抄" in text
    assert ex._prompt("正文X", [], [], False).endswith("正文：\n正文X")
