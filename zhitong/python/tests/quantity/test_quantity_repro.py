# 来源：engine-service/tests/test_quantity_repro.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""WS11 复现用例（issue #763）：只看对外行为（prepare → agent 作答 → finalize），不依赖内部结构。

zt 改动：旧版打桩 ``quantity_list.chat``；现在假 agent 按 prepare 的片段作答。QTY-01（每次 LLM 调用显式
max_tokens）在 zt 里没有模型调用，跳过。
"""
from __future__ import annotations

import pytest

from zt.quantity import pipeline
from tests.quantity.fixtures.shapes import FakeAgent
from tests.quantity.support import run


def _txt(text: str, name: str = "做法说明.txt"):
    return [(text.encode("utf-8"), name, "txt")]


def _by_text(pick):
    return FakeAgent(lambda s: pick(s.get("原文", "")))


PRACTICE_TXT = (
    "地面1：地砖地面\n"
    "1. 10厚防滑地砖面层\n"
    "2. 20厚1:3水泥砂浆结合层\n"
    "踢脚1：地砖踢脚\n"
    "1. 10厚地砖踢脚\n"
)


@pytest.mark.skip(reason="zt 不调用模型：QTY-01 验的是每次 LLM 调用显式 max_tokens，没有对应物")
def test_repro_qty01_llm_call_without_max_tokens():
    pass


def test_repro_qty05_empty_llm_result_is_not_success():
    with pytest.raises(pipeline.QuantityRejected) as ei:
        # 修复前：空码回答被当成功，返回只有表头的 xlsx（铁律 8）
        run(_txt(PRACTICE_TXT), agent=_by_text(lambda t: ("main", "")))
    assert ei.value.reason_code == "no_items"


def test_repro_qty07_installation_text_never_reaches_agent():
    agent = _by_text(lambda t: ("main", "Z010506028"))
    hvac = "\n".join(["空调风管采用镀锌钢板，风机盘管吊装，排烟风机设于屋顶，新风机组、配电箱、桥架、电缆、照明灯具、"
                      "插座、弱电综合布线、监控摄像机、消火栓、喷淋喷头、报警阀"] * 5)
    with pytest.raises(pipeline.QuantityRejected):
        run(_txt(hvac, "暖通说明.txt"), agent=agent)
    assert agent.batches == [], "QTY-07：非房建专业的文件不交给 agent"


def test_repro_qty02_skirting_as_wall_plaster_goes_to_pending():
    def pick(text):
        if "踢脚" in text:
            return "main", "Z011201001"  # QA r9：踢脚被判成墙面抹灰（单位 m² 而不是 m）
        return "main", "011102003"

    out = run(_txt(PRACTICE_TXT), agent=_by_text(pick))
    assert all(i["base_code"] != "Z011201001" for i in out["items"]), "QTY-02：错码不许顶着码表原文进正式清单"


def test_repro_qty03_dropped_segment_is_accounted():
    class DropLast(FakeAgent):
        def answer(self, prep):
            obj = super().answer(prep)
            obj["r"] = obj["r"][:-1]   # agent 漏答最后一条
            return obj

    out = run(_txt(PRACTICE_TXT), agent=DropLast(lambda s: ("main", "011102003")))
    cov = out.get("coverage_detail") or {}
    assert cov.get("practice_segments"), "QTY-03：结果必须带逐片段覆盖核算"
    assert sum(cov["by_destination"].values()) == cov["practice_segments"]
    assert cov["by_destination"]["llm_failed"] == 1 and out["status"] == "partial"
