"""清单编码回链 ``zt.report.codes.verify_codes``（迁自旧仓 tests/test_answer_guard.py 的 WS21-e a–f 与非编码用例）。

旧用例经 ``review_answer(mode="filetree", code_backlink=True)`` 间接调用，这里直接调 ``verify_codes``；
``sources`` 对应 ``evidence_texts``，``prior_texts`` 同名。
"""
from __future__ import annotations

from zt.report.codes import verify_codes

_B2R3_CONCLUSION = "屋面变形缝应列 Z010901008「屋面变形缝」，计量单位 m。"
_K3_L77 = "| 010901008 | 屋面变形缝 | m | 浙江2025 | 0109 | 1.变形缝尺寸；2.嵌缝材料种类 | zj2025.yaml codes.010901008 |"


def _marked(res, answer: str) -> list[str]:
    return [answer[s["start"]:s["end"]] for s in res.segments]


def test_a_fabricated_code_is_named_with_the_original_spelling():
    res = verify_codes(_B2R3_CONCLUSION, [_K3_L77, "屋面的变形缝呢？"])
    note = next(n for n in res.notes if "Z010901008" in n)
    assert "未能在检索到的原文中逐字找到" in note and "原文写法为 010901008" in note
    assert _marked(res, _B2R3_CONCLUSION) == ["Z010901008"]
    assert res.unverified == ["Z010901008"]


def test_b_main_code_compared_whole_not_by_substring():
    src = ["| Z010905001 | 基础卷材防水 | m² |"]
    bare = verify_codes("应列 010905001。", src)
    assert bare.unverified == ["010905001"]
    assert "原文写法为 Z010905001" in bare.notes[0]
    assert verify_codes("应列 Z010905001。", src).notes == []


def test_c_nine_and_twelve_digit_codes():
    assert verify_codes("独立基础 010502001。", ["010502001001 独立基础"]).notes == []
    for src, ans in ((["010502001 独立基础"], "列 010502001001。"),
                     (["010502001001 独立基础"], "列 010502001002。")):
        res = verify_codes(ans, src)
        assert len(res.notes) == 1 and "顺序码未在检索到的原文中找到" in res.notes[0], (src, ans)
        assert "主码 010502001 在原文中" in res.notes[0]
        assert _marked(res, ans) == [ans[2:14]]
    assert verify_codes("列 010502001001。", ["010502001001 独立基础"]).notes == []


def test_d_codes_in_the_users_own_input_are_not_flagged():
    ans = "未查到 011101001 的综合单价数值。"
    assert verify_codes(ans, ["水泥砂浆楼地面"], user_inputs=["011101001 的综合单价是多少？"]).notes == []
    assert verify_codes(ans, ["水泥砂浆楼地面"]).unverified == ["011101001"]


def test_f_code_from_prior_text_gets_its_own_wording_and_is_not_evidence():
    ans = "楼(地)面卷材防水 Z010904001 的计量单位是 m²。"
    res = verify_codes(ans, ["| 楼(地)面卷材防水 | m² |"], prior_texts=["楼(地)面卷材防水 Z010904001 的计量单位是什么？"])
    assert res.unverified == ["Z010904001"]
    assert "来自上文对话" in res.notes[0] and "本轮检索到的原文里没有逐字出现" in res.notes[0]
    assert _marked(res, ans) == ["Z010904001"]


def test_nine_digit_numbers_that_are_not_codes_and_phone_numbers_are_ignored():
    res = verify_codes("概算总投资 123456789 元。", ["概算总投资 123,456,789 元"])
    assert res.unverified == [] and not any("编码" in n for n in res.notes)
    for ans in ("建设单位电话 057188888888。", "联系方式：057188888888", "传真 057188888889"):
        assert verify_codes(ans, ["建设单位"]).unverified == [], ans
    assert verify_codes("应列 057188888888。", ["建设单位"]).unverified == ["057188888888"]
