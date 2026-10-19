# 来源：engine-service/tests/test_report_guard.py（zhitong-cost-ai@991ff5c，W3 搬入；只改了 import 与夹具路径）
"""AI 报告初稿确定性护栏（WS12-B，issue #758）：app/engine/report_guard.py。

夹具数字取自 spec P01 的生产取证形状（数值为虚构，不含客户数据）：
- r23：资料有送审 321721、审定 319786，LLM 自己算出「减少1935元」；
- v03：LLM 写「6.34%」；资料有 9602，LLM 写「约0.96万元」；
- w01：资料 567856.44，LLM 转写成 567855.64（差 0.8 元）。
"""
from __future__ import annotations

import pytest

from zt.report.guard import (
    MARK_META,
    MARK_NEGATION,
    MARK_NO_SOURCE,
    MARK_UNBACKED,
    MARK_UNREADABLE,
    EvidenceFile,
    backlink,
    check_claims,
    check_negations,
    check_transcription,
    check_unreadable_claims,
    guard_section,
    meaningful_chars,
    normalize_blank_lines,
    rewrite_meta_talk,
    strip_title,
    _compact,
)

EV = [EvidenceFile("f1", "审定单.xlsx",
                   "[R3] A:土建\tB:321721\tC:319786\n审定金额 329388 元。管理费 9602 元。审核日期 2024-03-15。\n"
                   "合计 567856.44")]


def _flagged(out: str) -> list[str]:
    _, flags, _ = backlink(out, EV)
    return [f.text for f in flags]


# ================================================================ P01 数字回链

def test_1_fabricated_difference_is_flagged():
    """① r23：资料只有送审与审定，差额 1935 是 LLM 自己算的。"""
    text, flags, _ = backlink("审定金额较送审减少1935元。", EV)
    assert [f.text for f in flags] == ["1935元"]
    assert text == f"审定金额较送审减少1935元{MARK_UNBACKED}。", "标注插在数字与单位之后、原位不动"
    assert flags[0].kind == "unbacked_number"


def test_2_wan_yuan_conversion_is_flagged():
    """② v03：资料 9602，输出「约0.96万元」—— 不做单位换算，换算出来的数没有出处。"""
    assert _flagged("管理费约0.96万元。") == ["0.96万元"]


def test_3_ratio_is_flagged():
    """③ 比例是 LLM 算的。"""
    assert _flagged("核减率约6.34%。") == ["6.34%"]


def test_transcription_off_by_0_8_yuan_is_flagged():
    """w01：差 0.8 元的转写（WS07 的 1 元容差会放过它 —— 这正是 WS12 判据更严的原因）。"""
    assert _flagged("合计567855.64元。") == ["567855.64元"]


def test_4_verbatim_number_with_thousands_date_and_row_number_are_not_flagged():
    """④ 正控：资料有 329388，输出「329,388元」（千分位、全角）；日期、行首序号、规范号、文号都豁免。"""
    out = ("1. 审定金额为329,388元，另 ３２９３８８ 元为同一数。\n"
           "（2）审核日期2024年3月15日（2024-03-15），依据GB 50500-2013及浙建〔2018〕61号，"
           "C30混凝土，见3.2.1条。")
    text, flags, refs = backlink(out, EV)
    assert flags == []
    assert text == out, "没有要标的数时正文一字不改（千分位、全角不被规整掉）"
    assert {r["value"] for r in refs} == {"329388"}
    assert refs[0]["file_ids"] == ["f1"]


def test_sign_is_not_part_of_the_match():
    """「核减1935元」对应资料里的 -1935 算同一个数（正负号是文字表达，不是换算）。"""
    ev = [EvidenceFile("f1", "a.xlsx", "核减 -1935")]
    _, flags, _ = backlink("核减1935元。", ev)
    assert flags == []


def test_numbers_inside_markers_are_not_rechecked():
    """护栏自己插的标注、[资料n]、〔Fn〕不参与回链（否则会把标注再标一遍）。"""
    out = "见[资料12]，金额〔F3〕，【待补：资料《A》无法读取】。"
    _, flags, _ = backlink(out, EV)
    assert flags == []


def test_chinese_uppercase_amount_backlinked_by_value():
    out = "审定金额叁拾贰万玖仟叁佰捌拾捌元整。"
    _, flags, _ = backlink(out, EV)
    assert flags == []
    _, flags, _ = backlink("审定金额壹拾万元整。", EV)
    assert [f.text for f in flags] == ["壹拾万元整"]


# ================================================================ P02 读不出的资料

UNREADABLE = [{"file_id": "g1", "file_name": "审核版.GBQ7", "reason": "格式不支持"}]


def test_absence_claim_flagged_when_some_file_unreadable():
    text, flags = check_unreadable_claims("安装工程资料未列示分项。其余照常。", UNREADABLE)
    assert [f.kind for f in flags] == ["unreadable_claim"]
    assert text == f"安装工程资料未列示分项{MARK_UNREADABLE}。其余照常。"


def test_absence_claim_not_flagged_when_everything_readable():
    """对照：unreadable 为空时同一句不标（资料都读到了，「未列示」就是资料本身的状态）。"""
    text, flags = check_unreadable_claims("安装工程资料未列示分项。", [])
    assert flags == [] and text == "安装工程资料未列示分项。"


# ================================================================ P06 AI 元话语

def test_meta_talk_rewritten_as_todo_and_recorded():
    text, missing = rewrite_meta_talk("本节信息不足，无法撰写审核结果。工程位于某市。")
    assert "信息不足" not in text
    assert text.startswith(MARK_META)
    assert "工程位于某市" in text
    assert missing and "信息不足" in missing[0]


def test_content_claims_are_not_meta_talk():
    text, missing = rewrite_meta_talk("安装工程资料未列示分项。")
    assert missing == [] and text == "安装工程资料未列示分项。"


# ---------------------------------------------------------------- WS24-f（R24-32）「资料 n 未提供」

@pytest.mark.parametrize("raw, kept", [
    # 运行 B 第十章（7 处之一）：标记挂在句末，整句换掉，句号留下
    ("本编制说明与图纸、规范、招标文件不一致时，以本编制说明为准【待补：资料1至资料24未提供正文，编制说明原文无法读取】。",
     "【待补：本章缺少相关资料】。"),
    # 标记在句号之后自成一句：前一句保留，只换标记
    ("本编制说明未尽事宜按招标文件执行。【待补：资料1至资料24未提供正文，编制说明原文无法读取】",
     "本编制说明未尽事宜按招标文件执行。【待补：本章缺少相关资料】"),
    # 运行 D 第四章：「资料n《文件名》未提供」，分号分句，各自整句换掉，不相干的句子留下
    ("计价口径按项目资料所载内容执行【待补：资料1《X_面积统计表.xlsx》未提供】；"
     "暂估价按项目资料所载内容执行【待补：资料5《一标段.xlsx》未提供】；工程位于义乌[资料3]。",
     "【待补：本章缺少相关资料】；【待补：本章缺少相关资料】；工程位于义乌[资料3]。"),
    # 不在标记里、带方括号编号的写法
    ("[资料1]至[资料24]均未提供本章所需内容。", "【待补：本章缺少相关资料】。"),
])
def test_missing_source_claims_rewritten_whole_sentence(raw, kept):
    text, missing = rewrite_meta_talk(raw)
    assert text == kept
    assert missing and all("未提供" in m for m in missing)
    assert MARK_NO_SOURCE in text


@pytest.mark.parametrize("raw", [
    "建设单位未提供签证资料[资料3]。",          # 对资料内容的陈述：「未提供」前面不是「资料+编号」
    "资料3中，施工单位未提供竣工图[资料3]。",
    "【待补：资料1至资料24及资料25中可读取的编制说明相关内容】",   # 没说「未提供」
    "安装工程资料未列示分项。",                 # 归 P02，不是这条规则的事
])
def test_content_about_missing_documents_is_not_rewritten(raw):
    text, missing = rewrite_meta_talk(raw)
    assert text == raw and missing == []


def test_missing_source_split_on_masked_text_so_marker_inner_semicolon_does_not_cut():
    """【…】里的「；」不切句：否则半个标记被换掉，剩下「其余见附表】」这种残片。"""
    text, _ = rewrite_meta_talk("【待补：资料1未提供；其余见附表】")
    assert text == MARK_NO_SOURCE


# ================================================================ P07 程序性陈述

def test_unconfirmed_procedural_claim_flagged():
    text, flags = check_claims("我公司对本项目进行了全过程审核。", [], [], _compact("送审资料"))
    assert [f.text for f in flags] == ["全过程审核"]
    assert "【待核：「全过程审核」未经确认、资料中也未见】" in text


def test_confirmed_claim_not_flagged():
    claims = [{"key": "full_process_audit", "text": "全过程审核"}]
    _, flags = check_claims("我公司对本项目进行了全过程审核。", claims, ["full_process_audit"], "")
    assert flags == []


def test_claim_present_in_evidence_not_flagged():
    _, flags = check_claims("经现场踏勘核对。", [], [], _compact("监理日志：2024年3月现场踏勘。"))
    assert flags == []


# PR-YAML Y1：「现场查勘」「现场查勘核实」进 DEFAULT_CLAIMS（key 与 yaml 的 site_check 一致）

def test_site_check_default_claim_flagged_without_template_claims():
    """模板没列 claims 也要标：兜底来自 DEFAULT_CLAIMS。"""
    text, flags = check_claims("经现场查勘，确认围墙已拆除。", [], [], _compact("送审资料"))
    assert [f.text for f in flags] == ["现场查勘"]
    assert "现场查勘【待核：「现场查勘」未经确认、资料中也未见】" in text


def test_nested_claim_flagged_once_as_the_longer_phrase():
    """「现场查勘核实」包含「现场查勘」：只标长的那条，标注不能插进短语中间。"""
    text, flags = check_claims("实施了现场查勘核实等程序。", [], [], _compact("送审资料"))
    assert [f.text for f in flags] == ["现场查勘核实"]
    assert text == "实施了现场查勘核实【待核：「现场查勘核实」未经确认、资料中也未见】等程序。"


def test_nested_suppression_does_not_hide_a_separate_occurrence():
    text, flags = check_claims("现场查勘核实完毕。次日再次现场查勘。", [], [], _compact("送审资料"))
    assert [f.text for f in flags] == ["现场查勘核实", "现场查勘"]
    assert text.count("【待核") == 2


def test_site_check_confirmed_by_key_not_flagged():
    """用户在「确认事项」勾了 site_check（yaml 的 key），两条兜底一并放行。"""
    _, flags = check_claims("实施了现场查勘核实。经现场查勘确认。", [], ["site_check"], "")
    assert flags == []


def test_longer_claim_flagged_but_says_which_shorter_one_the_evidence_has():
    """资料里有「现场查勘记录」、正文写「现场查勘核实」：照标（「核实」没有依据），
    但提示写「资料中只见「现场查勘」」，不能说「资料中也未见」（PR #786 评审：那句会误导人）。"""
    text, flags = check_claims("实施了现场查勘核实等程序。", [], [], _compact("附：现场查勘记录一份"))
    assert [f.text for f in flags] == ["现场查勘核实"]
    assert text == "实施了现场查勘核实【待核：「现场查勘核实」未经确认、资料中只见「现场查勘」】等程序。"
    assert "资料中也未见" not in flags[0].message and "资料中只见「现场查勘」" in flags[0].message


def test_evidence_without_any_part_of_the_claim_keeps_the_original_wording():
    text, _ = check_claims("实施了现场查勘核实等程序。", [], [], _compact("附：竣工图一套"))
    assert "【待核：「现场查勘核实」未经确认、资料中也未见】" in text


# ================================================================ P10 全称否定

def test_unsupported_negation_flagged():
    text, flags = check_negations("本工程未涉及工程量核减事项。", _compact("送审金额 321721"))
    assert [f.kind for f in flags] == ["unsupported_negation"]
    assert MARK_NEGATION in text


def test_negation_backed_by_evidence_not_flagged():
    _, flags = check_negations("本工程未发生核增。", _compact("说明：本期未发生核增。"))
    assert flags == []


def test_same_negation_word_about_something_else_is_flagged():
    """资料里有「未发生核增」，不等于「未发生工程量核减」也有依据：判据看否定词 + 后接短语，不只看否定词。"""
    text, flags = check_negations("本工程未发生工程量核减。", _compact("说明：本期未发生核增。"))
    assert [f.kind for f in flags] == ["unsupported_negation"]
    assert MARK_NEGATION in text


# ================================================================ P05 转写成稿报告

REPORT = EvidenceFile("r1", "结算审核报告.docx",
                      "受贵方委托我公司对某某中学迁建工程竣工结算进行审核现将审核结果报告如下审定金额见附表",
                      kind="finished_report")


def test_30_char_verbatim_overlap_is_transcribed():
    out = "受贵方委托我公司对某某中学迁建工程竣工结算进行审核现将审核结果报告如下。"
    flags = check_transcription(out, [REPORT])
    assert [f.kind for f in flags] == ["transcribed"] and flags[0].file_id == "r1"


def test_20_char_overlap_is_not_transcribed():
    out = "受贵方委托我公司对某某中学迁建工程竣工。另起一句完全不同的话，写别的内容。"
    assert check_transcription(out, [REPORT]) == []


# ================================================================ P09 标题与空行

@pytest.mark.parametrize("first", ["五、审核结果", "五、 审核结果", "# 五、审核结果", "**五、审核结果**", "五 审核结果："])
def test_strip_title_variants(first):
    assert strip_title(f"{first}\n正文第一句。", "五、审核结果") == "正文第一句。"


def test_strip_title_keeps_unequal_sentence():
    body = "五、审核结果如下：送审总造价见表。"
    assert strip_title(body, "五、审核结果") == body


def test_normalize_blank_lines():
    assert normalize_blank_lines("\n\n一\n\n\n\n二  \n\n") == "一\n\n二"


# ================================================================ 流水线

def test_guard_section_pipeline_and_meaningful_chars():
    g = guard_section("五、审核结果\n\n审定金额329,388元[资料1]，减少1935元。\n\n\n本节信息不足。",
                      title="五、审核结果", evidence=EV)
    assert g.content.startswith("审定金额329,388元[资料1]")
    assert MARK_UNBACKED in g.content
    assert "信息不足" not in g.content and MARK_META in g.content
    assert [f.kind for f in g.flags] == ["unbacked_number"]
    assert g.missing_items
    assert meaningful_chars("【待补：x】[资料1]" + "字" * 29) == 29


# ================================================================ WS24-o 没有依据的内容（issue #884，缺陷 02-008、02-012）

import json  # noqa: E402
import re  # noqa: E402
from pathlib import Path  # noqa: E402

from tests.report._support import resolve_section  # noqa: E402
from zt.report.guard import (  # noqa: E402
    MARK_BLANK,
    MARK_CITED_NUMBER,
    MARK_TEMPLATE_ECHO,
    check_blank_quantity,
    check_template_echo,
    rewrite_placeholders,
    strip_confirmed_label,
)

_REALRUN = json.loads((Path(__file__).parent / "fixtures" / "report_guard" / "realrun_sentences.json")
                      .read_text(encoding="utf-8"))
_QD = _REALRUN["qd_sheet"]


def _qd(index: int) -> list[EvidenceFile]:
    """生产清单 xlsx 形状的那份资料，按运行里的编号送入（运行 C 是 [资料25]，运行 R 是 [资料23]）。"""
    return [EvidenceFile(f"f{index}", "某街道某地块一标段.xlsx", _QD, index=index)]


def _prompt(section_code: str) -> str:
    return resolve_section(_REALRUN["template_code"], section_code)["gen_prompt"]


def _marks(text: str) -> list[str]:
    import re as _re
    return _re.findall(r"【[^】]*】", text)


# ---------------------------------------------------------------- 1. 模板话术回流（template_echo）

# 首轮运行 A 的写作要求原文（宁波已由 WS24-q 从 yaml 里清掉；护栏要能拦住任何一句照抄进来的写作要求）
_OLD_YUEDING = "⑦末尾备注：「本编制说明未尽事宜，均按国家、浙江省、宁波市现行最新计价规范、政策文件及本项目招标文件约定执行。」"


def test_echo_whole_template_sentence_cited_after_the_period_is_marked_and_uncited():
    """运行 A 第十章：整句照抄写作要求，引用挂在句号之后 → 句末标记，[资料6] 去掉。"""
    out = "本编制说明未尽事宜，均按国家、浙江省、宁波市现行最新计价规范、政策文件及本项目招标文件约定执行。[资料6]"
    ev = [EvidenceFile("f6", "模板冒烟.docx", "工程量清单编制说明 一、项目概况", index=6)]
    g = guard_section(out, title="十、清单总体计价约定", evidence=ev, gen_prompt=_OLD_YUEDING)
    assert g.content == ("本编制说明未尽事宜，均按国家、浙江省、宁波市现行最新计价规范、政策文件及本项目招标文件约定执行"
                         f"{MARK_TEMPLATE_ECHO}。")
    assert [f.kind for f in g.flags] == ["template_echo"]
    assert "[资料6]" not in g.content


def test_echo_seven_char_fragment_with_a_number_is_marked():
    """运行 A / C 第五章：「规费费率不低于标准费率的30%」（片段「不低于标准费率」7 字）。"""
    text, flags = check_template_echo("规费费率不低于标准费率的30%。", "③规费（不低于标准费率30%）",
                                      [EvidenceFile("f1", "清单.xlsx", "规费 1987815.44", index=1)])
    assert [f.text for f in flags] == ["不低于标准费率"]
    assert text == f"规费费率不低于标准费率的30%{MARK_TEMPLATE_ECHO}。"


def test_echo_six_char_fragment_from_the_real_prompt_drops_the_citation():
    """运行 A 第四章：「报价中已包含赶工保质费用」，写作要求是「报价含赶工保质费用」，清单里没有这句。"""
    text, flags = check_template_echo("报价中已包含赶工保质费用[资料25]。", _prompt("yaoqiu"), _qd(25))
    assert [f.kind for f in flags] == ["template_echo"]
    assert "赶工保质费用" in flags[0].text
    assert text == f"报价中已包含赶工保质费用{MARK_TEMPLATE_ECHO}。"


def test_echo_not_marked_when_the_fragment_is_in_the_materials():
    """负向：「安全文明施工基本费」写作要求里有，清单里也有 → 不标、引用留着。"""
    out = "安全文明施工基本费合计 6010726.64[资料25]。"
    text, flags = check_template_echo(out, _prompt("feilv"), _qd(25))
    assert flags == [] and text == out


@pytest.mark.parametrize("heading", ["（一）安全文明施工基本费", "（五）以「项」计量的子目总价包干"])
def test_echo_skips_line_headings(heading):
    """负向：行首小标题本来就照模板写。第二个标题 12 个实义字、模板片段资料里没有 —— 只靠「小标题不查」放行。"""
    out = f"{heading}\n以「项」计量的子目见清单[资料25]。"
    text, flags = check_template_echo(out, _prompt("yueding"), _qd(25))
    assert flags == [] and text == out


def test_echo_skips_inline_heading_before_a_colon():
    """运行 R 第七章「二、土石方渣土外运包干：余方弃置…[资料23]」：冒号前照模板写，冒号后才是转写的正文。"""
    out = "二、土石方渣土外运包干：回填方（借土）的项目特征载明粘土分层夯实[资料23]。"
    text, flags = check_template_echo(out, _prompt("gongxing"), _qd(23))
    assert flags == [] and text == out


def test_echo_five_char_fragment_is_below_the_threshold():
    """负向：最长的模板片段只有 5 个字（「后固定包干」）→ 不标。"""
    out = "签约后固定包干不再调整综合单价[资料25]。"
    text, flags = check_template_echo(out, _prompt("feilv"), _qd(25))
    assert flags == [] and text == out


def test_echo_second_fragment_counts_even_when_the_longest_one_is_in_the_materials():
    """运行 R 第五章：最长的「安全文明施工基本费」清单里有，另一段「分档累进费率」只在写作要求里有 → 标。"""
    out = "安全文明施工基本费按建筑装饰工程分档累进费率及安装工程费率计取[资料23]。"
    text, flags = check_template_echo(out, _prompt("feilv"), _qd(23))
    assert [f.text for f in flags] == ["分档累进费率"]
    assert "[资料23]" not in text and text.endswith(f"{MARK_TEMPLATE_ECHO}。")


def test_echo_label_of_a_backed_value_is_not_an_unsupported_sentence():
    """结算审核报告的写作要求规定了名目的说法（「审核定案总造价」），资料写的是「审定总造价」：
    「审核定案总造价为319786元[资料1]」断言的是那个数，数有出处 → 不标、引用留着（运行 D 第五章的形状）。"""
    prompt = resolve_section("jiesuan_shenhe_bg", "jieguo")["gen_prompt"]
    ev = [EvidenceFile("f1", "审定单.xlsx", "送审总造价 321721 元，审定总造价 319786 元。", index=1)]
    for ok in ("审核定案总造价为319786元[资料1]，送审总造价为321721元[资料1]。",
               "审核定案总造价为〔F2〕[资料5]，送审总造价为〔F1〕[资料5]。"):
        assert check_template_echo(ok, prompt, ev) == (ok, []), ok
    # 对照：名目后面的数资料里没有，名目就没有着落 → 照标
    bad = "审核定案总造价为999999元[资料1]，送审总造价为321721元[资料1]。"
    _, flags = check_template_echo(bad, prompt, ev)
    assert [f.text for f in flags] == ["审核定案总造价"]


def test_echo_markers_break_fragments():
    """「送审造价〔F6〕[资料5]，审核定案造价〔F7〕[资料5]，核减造价…」：标记是断点，去掉标点后不许连成写作要求里的
    「…造价核减造价核增造价净核减造价」（运行 D 第五章的分项行）。"""
    prompt = resolve_section("jiesuan_shenhe_bg", "jieguo")["gen_prompt"]
    out = "建筑工程：送审造价〔F6〕[资料5]，审核定案造价〔F7〕[资料5]，核减造价〔F8〕[资料5]，核增造价〔F9〕[资料5]，净核减造价〔F10〕[资料5]。"
    assert check_template_echo(out, prompt, _qd(5)) == (out, [])


def test_echo_needs_twelve_meaningful_chars():
    text, flags = check_template_echo("中标后固定包干。", _prompt("feilv"), _qd(25))
    assert flags == [] and text == "中标后固定包干。"


def test_echo_off_without_a_prompt():
    """旧 Java 窗口期没有模板（gen_prompt 为空）：不查。"""
    out = "规费按招标文件载明的费率下限计取[资料23]。"
    assert check_template_echo(out, "", _qd(23)) == (out, [])


@pytest.mark.parametrize("case", _REALRUN["echo"], ids=lambda c: c["text"][:12])
def test_echo_realrun_r_template_sentences_are_all_marked(case):
    """R1补 运行 R 第五、十章照抄写作要求、挂着 [资料23] 的句子（取材快照里这些话 0 处）：全部标出、引用去掉。"""
    g = guard_section(case["text"], title="", evidence=_qd(case["cite"]), gen_prompt=_prompt(case["section"]))
    assert [f.kind for f in g.flags] == ["template_echo"], g.flags
    assert MARK_TEMPLATE_ECHO in g.content
    assert "[资料" not in g.content


@pytest.mark.parametrize("case", _REALRUN["transcribed"], ids=lambda c: c["text"][:12])
def test_echo_does_not_touch_real_transcriptions_in_the_same_chapter(case):
    g = guard_section(case["text"], title="", evidence=_qd(case["cite"]), gen_prompt=_prompt(case["section"]))
    assert g.flags == [] and g.content == case["text"]


# ---------------------------------------------------------------- 2. 占位符（raw_placeholder）

def test_placeholder_becomes_todo_and_both_citations_go():
    """运行 A 第三章：「…包括：###相关资料依据###[资料6][资料7]。」"""
    out = "本报告编制所依据的相关资料包括：###相关资料依据###[资料6][资料7]。"
    text, flags = rewrite_placeholders(out)
    assert text == "本报告编制所依据的相关资料包括：【待补：相关资料依据】。"
    assert [(f.kind, f.text) for f in flags] == [("raw_placeholder", "###相关资料依据###")]


def test_placeholder_only_touches_its_own_sentence():
    out = "工程名称为###工程名称###[资料6]；地下室合计157320405.57元[资料25]。"
    text, _ = rewrite_placeholders(out)
    assert text == "工程名称为【待补：工程名称】；地下室合计157320405.57元[资料25]。"


def test_placeholder_through_the_pipeline():
    g = guard_section("本报告依据：###相关资料依据###[资料6]。", title="", evidence=_qd(6))
    assert "###" not in g.content and "【待补：相关资料依据】" in g.content and "[资料6]" not in g.content
    assert [f.kind for f in g.flags] == ["raw_placeholder"]


# ---------------------------------------------------------------- 3. 引用内的数字（cited_number）

_TWO = [EvidenceFile("f3", "招标文件.docx", "规费按标准费率的 30% 计取。", index=3),
        EvidenceFile("f6", "清单.xlsx", "[R5] A:规费\tB:1987815.44", index=6)]


def test_number_found_only_in_another_file_is_marked():
    text, flags, refs = backlink("规费费率按30%计取[资料6]。", _TWO)
    assert [(f.kind, f.text) for f in flags] == [("cited_number", "30%")]
    assert text == f"规费费率按30%{MARK_CITED_NUMBER}计取[资料6]。"
    assert refs == []


def test_number_in_the_cited_file_is_fine_and_refs_list_only_the_cited_file():
    both = [*_TWO, EvidenceFile("f9", "另一份.xlsx", "规费 1987815.44", index=9)]
    text, flags, refs = backlink("地下室规费为1987815.44[资料6]。", both)
    assert flags == [] and text == "地下室规费为1987815.44[资料6]。"
    assert refs == [{"raw": "1987815.44", "value": "1987815.44", "file_ids": ["f6"]}]


def test_uncited_sentence_still_checks_all_materials():
    text, flags, refs = backlink("规费费率按30%计取。", _TWO)
    assert flags == [] and refs[0]["file_ids"] == ["f3"]


def test_citation_after_the_period_belongs_to_the_sentence():
    text, flags, _ = backlink("规费费率按30%计取。[资料6]", _TWO)
    assert [f.kind for f in flags] == ["cited_number"]


def test_citing_a_file_this_section_did_not_receive_marks_the_number():
    """运行 R 第三章引用了 28 份本章没送入的资料：所引的那份模型根本没看到，数字不能算有出处。"""
    _, flags, _ = backlink("地下室规费为1987815.44[资料12]。", _TWO)
    assert [f.kind for f in flags] == ["cited_number"]


def test_materials_without_index_fall_back_to_all_materials():
    """评测脚本、旧调用方的资料不带编号：对不上 [资料n]，按全部资料查（不因此多标）。"""
    plain = [EvidenceFile("f3", "a.docx", "费率 30%")]
    _, flags, _ = backlink("规费费率按30%计取[资料6]。", plain)
    assert flags == []


def test_unbacked_number_keeps_its_own_mark():
    text, flags, _ = backlink("规费为1935元[资料6]。", _TWO)
    assert [f.kind for f in flags] == ["unbacked_number"] and MARK_UNBACKED in text


# ---------------------------------------------------------------- 4. 量词前缺内容（blank_quantity）

def test_blank_quantity_marks_each_hole():
    """运行 A 第一章照抄了带空的模板成稿。"""
    text, flags = check_blank_quantity("总建筑面积约万平米，地上建筑约万平米；由幢二类高层住宅组成；本工程为项目；")
    assert [f.text for f in flags] == ["约万平米", "约万平米", "由幢", "为项目"]
    assert text == (f"总建筑面积约万平米{MARK_BLANK}，地上建筑约万平米{MARK_BLANK}；由幢{MARK_BLANK}二类高层住宅组成；"
                    f"本工程为项目{MARK_BLANK}；")


def test_blank_quantity_through_the_pipeline():
    g = guard_section("本工程为项目；总建筑面积约万平米，地上建筑约万平米。", title="", evidence=_qd(25))
    assert [f.kind for f in g.flags] == ["blank_quantity"] * 3
    assert g.content.count(MARK_BLANK) == 3


@pytest.mark.parametrize("ok", [
    "总建筑面积约 17.23 万平米。",
    "表中金额单位为万元。",
    "计量单位为平方米。",
    "由项目部组织实施。",
    "作为项目负责人，统筹协调。",
    "设计层高 3.0 米。",
    "合计层数为 18 层。",
])
def test_blank_quantity_leaves_normal_wording_alone(ok):
    assert check_blank_quantity(ok) == (ok, [])


# ---------------------------------------------------------------- 「[已确认事项]」（R24-42）

def test_literal_confirmed_label_is_removed_and_the_sentence_stays():
    g = guard_section("本次审核已进行现场踏勘[已确认事项]。", title="", evidence=_qd(25), confirmed=["site_survey"])
    assert g.content == "本次审核已进行现场踏勘。"
    assert g.flags == []
    assert strip_confirmed_label("见【已确认事项】与［已确认事项］。") == "见与。"


# ---------------------------------------------------------------- 做对的部分不许被误伤（C-R16）

@pytest.mark.parametrize("case", _REALRUN["clean"], ids=lambda c: c["text"][:12])
def test_realrun_clean_sentences_get_no_new_marks(case):
    """运行 C 第一、五、六、九章带引用且查得到的句子：四条新规则下一个标记都不多，引用一个都不少。"""
    g = guard_section(case["text"], title="", evidence=_qd(case["cite"]), gen_prompt=_prompt(case["section"]))
    assert g.flags == [], [f.as_dict() for f in g.flags]
    assert g.content == case["text"]


def test_realrun_clean_sentences_as_whole_chapters():
    """同一章的句子连成一段（与生产上整章过护栏一样），结论不变；数字全部登记到所引的那份资料。"""
    by_sec: dict[str, list[str]] = {}
    for c in _REALRUN["clean"]:
        by_sec.setdefault(c["section"], []).append(c["text"])
    assert len(_REALRUN["clean"]) == 20 and set(by_sec) == {"gaikuang", "feilv", "qtxmf", "anzhuang"}
    for sec, texts in by_sec.items():
        chapter = "\n".join(texts)
        g = guard_section(chapter, title="", evidence=_qd(25), gen_prompt=_prompt(sec))
        assert g.flags == [] and g.content == chapter, sec
        assert g.amount_refs and all(r["file_ids"] == ["f25"] for r in g.amount_refs), sec


# ================================================================ WS24-g 护栏误报与〔Fn〕止血（issue #947）

from zt.report.guard import (  # noqa: E402
    MARK_FACT_TODO,
    MARK_UNBACKED_CODE,
    is_mostly_todo,
    meaningful_chars as _mchars,
    stop_fact_placeholders,
    strip_todo_citations,
    todo_count,
)

_G = json.loads((Path(__file__).parent / "fixtures" / "report_guard" / "ws24g_realrun.json").read_text(encoding="utf-8"))
_CH = {c["id"]: c for c in _G["chapters"]}
# spec WS24-g 测试清单里的文件名（读不出的那份 GBQ7 + 一份送入的清单说明）
_NAMES = ["某街道一标段1022.GBQ7", "结构说明5.xlsx", "1200.xlsx"]
_EV_NONE = [EvidenceFile("f1", "清单.xlsx", "[R5] A:1\tB:010101002001\tC:挖一般土方\tD:3218", index=1)]


def _bl(text: str, names=_NAMES, ev=_EV_NONE):
    out, flags, _ = backlink(text, ev, names)
    return out, [(f.kind, f.text) for f in flags]


# ---------------------------------------------------------------- 1. 文件名里的数字（R24-07，K-R19 共用函数）

@pytest.mark.parametrize("text", [
    "资料《某街道一标段1022.GBQ7》无法读取。",       # 全名，带书名号
    "某街道一标段1022里的工程量未能读取。",            # 主名，省略扩展名、不带书名号（模型常这么写）
    "《结构说明5.xlsx》载明的做法见附表。",
    "结构说明5.xlsx 与 某街道一标段1022.GBQ7 均为本项目资料。",
])
def test_filename_numbers_are_not_flagged_and_names_stay_whole(text):
    out, flags = _bl(text)
    assert flags == [] and out == text


@pytest.mark.parametrize("text, raw", [
    ("依据《合同价1022万元的说明》。", "1022万元"),   # 书名号里不是任何资料的名字：书名号不是后门
    ("见一标段1022的说明。", "1022"),                 # 主名只对了一半
    ("合同价1200元。", "1200元"),                     # 纯数字主名不豁免（K-R19：1200.xlsx 不能让 1200 元逃过回链）
])
def test_text_that_is_not_a_file_name_is_still_backlinked(text, raw):
    _, flags = _bl(text)
    assert flags == [("unbacked_number", raw)]


def test_filename_exemption_needs_the_name_list():
    """不传文件名（旧调用方）时行为与改前相同：文件名里的数照查。"""
    _, flags = _bl("资料《某街道一标段1022.GBQ7》无法读取。", names=())
    assert flags == [("unbacked_number", "1022")]


@pytest.mark.parametrize("cid", ["B-gaikuang", "B-yaoqiu", "C-zhaobiao_fanwei", "D-shixiang", "R-qtxmf", "R-yiju"])
def test_realrun_file_names_no_longer_flagged(cid):
    """实测 6 章（运行 B、C、D、R）：改前文件名被切成「…一标段1022【待核…】.GBQ7」「《0【待核…】-A3封面-…》」。
    证据取这一章正文本身、但把文件名挖掉 —— 正文里别的数都「有出处」，还会被标的只能是只出现在文件名里的数。"""
    c = _CH[cid]
    ev_text = c["raw"]
    for n in sorted(c["file_names"], key=len, reverse=True):
        ev_text = ev_text.replace(n, " ")
    # 不带编号：引用内的数字退回按全部资料查（这里只看文件名，不看引用对不对得上）
    ev = [EvidenceFile("e", "e", ev_text)]
    assert c["flags_before"], "夹具：改前这一章确有误报（生产落库的 flags）"
    _, flags_old, _ = backlink(c["raw"], ev)               # 对照：不给文件名 = 改前
    assert flags_old, f"{cid}：对照组要复现改前的误报"
    out, flags, _ = backlink(c["raw"], ev, c["file_names"])
    assert flags == [], [(f.kind, f.text) for f in flags]
    assert out == c["raw"]


# ---------------------------------------------------------------- 2. 清单编码（R24-31）

def test_nine_digit_prefix_of_a_twelve_digit_code_is_found():
    out, flags = _bl("土石方工程使用010101002等编码[资料1]。")
    assert flags == [] and "【待核" not in out


def test_code_missing_from_the_materials_gets_its_own_mark():
    out, flags = _bl("土石方工程使用010109999等编码[资料1]。")
    assert flags == [("unbacked_code", "010109999")]
    assert out == f"土石方工程使用010109999{MARK_UNBACKED_CODE}等编码[资料1]。"


def test_twelve_digit_with_a_wrong_sequence_number_is_flagged():
    _, flags = _bl("编码010101002001与010101002009[资料1]。")
    assert flags == [("unbacked_code", "010101002009")]


@pytest.mark.parametrize("text, raw", [
    ("金额10101002元[资料1]。", "10101002元"),        # 不以 0 开头：按数字回链
    ("单价010101002.5元[资料1]。", "010101002.5元"),   # 带小数点：是一个数，不是编码
    ("联系电话 057188888888[资料1]。", "057188888888"),  # 电话：verify_codes 不当编码，这里也照常回链
])
def test_numbers_that_look_like_codes_are_still_backlinked(text, raw):
    _, flags = _bl(text)
    assert flags == [("unbacked_number", raw)]


def test_code_inside_a_file_name_is_left_to_the_file_name():
    _, flags = _bl("见《010109999补充说明.xlsx》。", names=["010109999补充说明.xlsx"])
    assert flags == []


def test_realrun_b_chapter3_fifty_one_codes_are_all_found():
    """运行 B 第三章：清单里是 12 位编码，模型写 9 位前缀，改前 51 处【待核】。证据按清单形状给 12 位编码
    （夹具重建：9 位写法 + 顺序码 001；原清单不在本机），正文其余的数照原文给。"""
    c = _CH["B-yiju"]
    codes = sorted(set(re.findall(r"(?<!\d)0\d{8}(?!\d)", c["raw"])))
    assert len(codes) >= 40
    ev_text = c["raw"]
    for code in codes:
        ev_text = ev_text.replace(code, code + "001")
    for n in sorted(c["file_names"], key=len, reverse=True):
        ev_text = ev_text.replace(n, " ")
    ev = [EvidenceFile("f25", "清单.xlsx", ev_text)]
    assert sum(1 for t in c["flags_before"] if t in codes) == 51, "对照：生产落库的 flags 里改前 51 处编码"
    out, flags, _ = backlink(c["raw"], ev, c["file_names"])
    assert flags == [], [(f.kind, f.text) for f in flags]
    # 负向：把其中一个编码从资料里拿掉，它就要被标（编码不是一律放行）
    ev_missing = [EvidenceFile("f25", "清单.xlsx", ev_text.replace(codes[0] + "001", ""))]
    _, flags, _ = backlink(c["raw"], ev_missing, c["file_names"])
    assert {(f.kind, f.text) for f in flags} == {("unbacked_code", codes[0])}


# ---------------------------------------------------------------- 3. 【待补】后不挂引用（R24-18）

def test_citation_right_after_a_todo_is_removed():
    assert strip_todo_citations("委托单位：【待补：委托单位】[资料12]") == "委托单位：【待补：委托单位】"
    assert strip_todo_citations("项目名称：【待补：项目名称】 [资料1][资料2]。") == "项目名称：【待补：项目名称】。"


def test_other_citations_in_the_sentence_stay():
    s = "工程名称为某项目[资料25]，建筑面积【待补：面积】。[资料25]"
    assert strip_todo_citations(s) == s


@pytest.mark.parametrize("cid", ["E-shendingdan", "A-qtxmf", "B-gongxing", "D-fujian", "R-feilv"])
def test_realrun_todo_then_citation_is_gone_after_the_guard(cid):
    c = _CH[cid]
    assert re.search(r"【待补[^】\n]*】[ \t]*\[资料", c["raw"]), "夹具：改前确有「【待补】[资料n]」"
    g = guard_section(c["raw"], title=c["title"], evidence=[EvidenceFile("e", "e", c["raw"])],
                      file_names=c["file_names"])
    assert not re.search(r"【待补[^】\n]*】[ \t]*\[资料", g.content)
    assert todo_count(g.content) == todo_count(c["raw"]), "【待补】本身一处不少"


# ---------------------------------------------------------------- 4. 〔Fn〕止血（R24-05）

def test_fact_placeholder_without_known_facts_becomes_todo():
    text, flags = stop_fact_placeholders("审定金额〔F1〕元。")
    assert text == f"审定金额{MARK_FACT_TODO}元。"
    assert [(f.kind, f.text) for f in flags] == [("bad_placeholder", "〔F1〕")]


def test_fact_placeholder_in_the_known_set_is_left_for_substitution():
    text, flags = stop_fact_placeholders("审定金额〔F1〕元，核减〔F2〕元。", known_facts=["F1"])
    assert text == f"审定金额〔F1〕元，核减{MARK_FACT_TODO}元。"
    assert [f.text for f in flags] == ["〔F2〕"]


def test_realrun_d_chapter5_twenty_placeholders_are_all_stopped():
    """运行 D「五、审核结果」：20 个〔F1〕…〔F20〕原样留在正文、每个后面挂 [资料5]。"""
    c = _CH["D-jieguo"]
    n = len(re.findall(r"〔F\d+〕", c["raw"]))
    assert n == 20
    g = guard_section(c["raw"], title=c["title"], evidence=[EvidenceFile("f5", "审定单.xlsx", "审定金额", index=5)],
                      file_names=c["file_names"])
    assert "〔F" not in g.content
    assert g.content.count(MARK_FACT_TODO) == 20
    assert not re.search(r"【待补[^】\n]*】[ \t]*\[资料", g.content), "换成【待补】之后，后面的 [资料5] 一起去掉"
    assert [f.kind for f in g.flags].count("bad_placeholder") == 20


# ---------------------------------------------------------------- 5. 章标题重复（R24-38）

@pytest.mark.parametrize("first", ["一、编制依据", "三、编制依据", "（三）编制依据", "3. 编制依据", "**一、编制依据**",
                                   "第三章 编制依据"])
def test_strip_title_ignores_the_ordinal_on_both_sides(first):
    assert strip_title(f"{first}\n正文。", "三、编制依据") == "正文。"


@pytest.mark.parametrize("first, title", [("一、编制依据如下：甲。", "三、编制依据"), ("2#楼概况", "1#楼概况")])
def test_strip_title_keeps_lines_that_say_more(first, title):
    body = f"{first}\n乙。"
    assert strip_title(body, title) == body


# ---------------------------------------------------------------- 6.「资料不足」的新口径（R24-34）

@pytest.mark.parametrize("cid, todo, mostly", [
    ("E-shendingdan", 23, True),   # 运行 E 审定单：535 字 23 处，改前蓝色「AI 初稿·待核」
    ("B-gaikuang", 10, True),      # 运行 B 第一章：453 字 10 处
    ("C-qtxmf", 13, False),        # 运行 C 第六章：1248 字 13 处，有内容，不判
])
def test_mostly_todo_on_realrun_shapes(cid, todo, mostly):
    c = _CH[cid]
    assert todo_count(c["stored"]) == todo
    assert is_mostly_todo(c["stored"]) is mostly, _mchars(c["stored"])


def test_mostly_todo_needs_at_least_three_todos():
    assert is_mostly_todo("【待补：甲】【待补：乙】" + "字" * 10) is False
    assert is_mostly_todo("【待补：甲】【待补：乙】【待补：丙】" + "字" * 119) is True
    assert is_mostly_todo("【待补：甲】【待补：乙】【待补：丙】" + "字" * 120) is False


# ---------------------------------------------------------------- 做对的部分不许被误伤（C-R16）

def test_ws24o_clean_sentences_still_clean_with_the_file_names_given():
    """WS24-o 的 20 句带引用且查得到的句子：给上文件名、过新护栏，一个标记都不多。"""
    for case in _REALRUN["clean"]:
        g = guard_section(case["text"], title="", evidence=_qd(case["cite"]), gen_prompt=_prompt(case["section"]),
                          file_names=["某街道某地块一标段.xlsx", "结构说明5.xlsx", "某街道某地块一标段1022.GBQ7"])
        assert g.flags == [] and g.content == case["text"], case["text"]


# ================================================================ R3F-e（issue #988，缺陷 R3-002）：模板话术回流不误标有出处的事实
#
# 句子逐字取自 R3 生产复测的产出（13_复测_R3/产出 运行 W1 第五章、W2 第一章、W4 第四章），只把被护栏去掉的
# [资料n] 补回原位；资料按生产取文的形状（[工作表] / [R行] A:…）重建，项目名、地名不出现。

from zt.report.guard import _SEP, _plain  # noqa: E402

# 清单 xlsx（运行 W1 的 [资料25]）：表头「其中：人工费+机械费」与金额不在同一行 —— 去掉标点后资料里没有「人工费+机械费1」
_W1_QD = (
    "[工作表] 表10.2.2-13 单位工程招标控制价费用表【地下室】\n"
    "[R5] A:序号\tB:单位工程名称\tC:分部分项工程费\tD:其中：人工费+机械费\tE:施工技术措施项目费\tF:其中：人工费+机械费\n"
    "[R6] A:1\tB:地下室土建工程\tC:51867384.6\tD:6773687.21\tE:9850132.47\tF:5106420.71\n"
    "[R7] A:2\tB:土石方工程\tC:14530886.1\tD:9185210.93\tE:610447.12\tF:137382.74\n"
)
_W1_SENT = ("本标段各单位工程费用表中，分部分项工程费项下\"人工费+机械费\"及施工技术措施项目项下\"人工费+机械费\"的金额"
            "已分别列示，例如地下室土建工程分部分项人工费+机械费6773687.21元、技措项目人工费+机械费5106420.71元，"
            "土石方工程分部分项人工费+机械费9185210.93元、技措项目人工费+机械费137382.74元，其余见[资料25]。")

# 结构说明1（运行 W2 的 [资料1]）：生产取文就是这样乱序的「安全等级为 级。二」
_W2_STRUCT = ("[工作表] 结构设计总说明\n"
              "[R20] A:4.1 建筑结构安全等级为 级。二\n"
              "[R21] A:4.2 结构抗震设防分类为标准设防类建筑\n")
_W2_SENT = "结构形式与耐火、抗震、防水等级口径方面，建筑结构安全等级为二级[资料1]；结构抗震设防分类为标准设防类建筑[资料1]。"

# 送审清单（运行 W4 的 [资料5]）
_W4_QD = ("[工作表] 表10.2.2-13 单位工程招标控制价费用表【地下室-给排水工程】\n"
          "[R5] A:序号\tB:汇总内容\tC:金额（元）\n"
          "[R6] A:1\tB:分部分项工程\tC:3698058.49\n"
          "[R7] A:1.1\tB:其中：人工费+机械费\tC:132095.95\n")
_W4_SENT = "安装工程专项方面，地下室给排水工程分部分项工程费为3698058.49元，其中人工费加机械费为132095.95元[资料5]。"


def test_r3_w1_circled_ordinal_does_not_glue_onto_a_cited_amount():
    """验收 1）的复现夹具：写作要求「…取费基数为人工费＋机械费）；①安全文明施工基本费…」，正文
    「…技措项目人工费+机械费137382.74元[资料25]」。改前 NFKC 把「①」变成「1」，拼出「人工费+机械费1」，
    flags=[('template_echo','人工费+机械费1')]、[资料25] 被去掉（dev 77cf533b 实跑）。改后不标、引用留着。"""
    out = "土石方工程分部分项人工费+机械费9185210.93元、技措项目人工费+机械费137382.74元，其余见[资料25]。"
    ev = [EvidenceFile("f25", "某街道某地块一标段.xlsx", _W1_QD, index=25)]
    assert "①" in _prompt("feilv")
    assert check_template_echo(out, _prompt("feilv"), ev) == (out, [])


def test_r3_w1_chapter5_sentence_keeps_its_citation_through_the_whole_guard():
    """W1 第五章那一句原文（4 个金额清单里都有）：整条护栏走完，一个标记都不多，[资料25] 留着。"""
    ev = [EvidenceFile("f25", "某街道某地块一标段.xlsx", _W1_QD, index=25)]
    g = guard_section(_W1_SENT, title="五、规费、费率及税金报价硬性要求", evidence=ev, gen_prompt=_prompt("feilv"))
    assert g.flags == [] and g.content == _W1_SENT
    assert {r["value"] for r in g.amount_refs} == {"6773687.21", "5106420.71", "9185210.93", "137382.74"}


def test_r3_circled_ordinal_at_the_start_of_a_sentence_is_a_break():
    """模型照写作要求的样子用「①」起头：「①安全文明施工基本费按实际发生项之和进行计算[资料25]」。改前「①」→「1」，
    拼出「1安全文明施工基本费」（写作要求里有、资料里是「1 B:安全文明施工基本费」）→ 整句被标。这一条不靠末尾数字回退，
    只有「带圈序号是硬断点」能放行。"""
    out = "①安全文明施工基本费按实际发生项之和进行计算[资料25]。"
    assert check_template_echo(out, _prompt("feilv"), _qd(25)) == (out, [])


def test_r3_plain_turns_enclosed_ordinals_into_hard_breaks():
    assert "机械费1" not in _plain(_prompt("feilv"))
    assert f"人工费+机械费{_SEP}安全文明施工基本费" in _plain(_prompt("feilv"))
    for ch in "①⑳⑴⒇⒈⒛❶❿㉑㊿㈠㊀":
        assert _plain(f"甲{ch}乙") == f"甲{_SEP}乙", ch
    # 普通数字、全角数字照旧 NFKC
    assert _plain("费率１.５%") == "费率15"


def test_r3_circled_ordinals_still_keep_adjacent_elements_apart():
    """回归（原注释的理由）：写作要求「安全文明施工基本费②企业管理费」，「②」不能被整个删掉，否则与正文
    「安全文明施工基本费、企业管理费…」连成一个资料里没有的 14 字片段。"""
    prompt = "【必备要素】①安全文明施工基本费②企业管理费③规费"
    out = "安全文明施工基本费、企业管理费均按招标文件规定计取[资料25]。"
    assert check_template_echo(out, prompt, _qd(25)) == (out, [])
    # 对照：没有序号隔开时确实连成一段、被标 —— 上面那条放行靠的是硬断点
    _, flags = check_template_echo(out, "【必备要素】安全文明施工基本费企业管理费规费", _qd(25))
    assert [f.text for f in flags] == ["安全文明施工基本费企业管理费"]


# 园林模板写作要求里真有「养护期2年」：正文的数首位「2」会和它对上
_YL_SHIXIANG = resolve_section("qd_bz_shuoming_yuanlin", "shixiang")["gen_prompt"]


def test_r3_trailing_digit_is_cut_back_so_the_fragment_in_the_materials_counts():
    """片段末尾是数字（「绿化工程养护期2」，2 是正文「24个月」的首位）→ 回退到「绿化工程养护期」再查资料：资料里有。"""
    assert "养护期2年" in _YL_SHIXIANG
    ev = [EvidenceFile("f3", "招标文件.docx", "三、绿化工程养护期\n养护期限详见合同条款。\n合同条款：养护期限为24个月。",
                       index=3)]
    out = "本工程绿化工程养护期24个月，养护期满验收合格后移交[资料3]。"
    assert check_template_echo(out, _YL_SHIXIANG, ev) == (out, [])


def test_r3_label_check_reads_the_number_from_the_cut_back_point():
    """资料里没有「绿化工程养护期」这几个字，但「24」有：名目豁免从回退点取数，取到 24（改前取到被劈掉首位的 4）。"""
    ev = [EvidenceFile("f3", "招标文件.docx", "合同条款：养护期限为24个月。", index=3)]
    out = "本工程绿化工程养护期24个月，养护期满验收合格后移交[资料3]。"
    assert check_template_echo(out, _YL_SHIXIANG, ev) == (out, [])
    # 对照：数也查不到 → 照标，片段不以数字结尾
    _, flags = check_template_echo("本工程绿化工程养护期36个月，养护期满验收合格后移交[资料3]。", _YL_SHIXIANG, ev)
    assert [f.text for f in flags] == ["绿化工程养护期"]


def test_r3_w2_lead_phrase_marks_only_the_lead_and_keeps_the_fact_and_citation():
    """W2 第一章：引子「结构形式与耐火、抗震、防水等级口径方面，」照写作要求写，后面「建筑结构安全等级为二级」
    结构说明1 里有。改前整句标、[资料1] 被去掉；改后只在引子后面标，事实与 [资料1] 都留着。"""
    ev = [EvidenceFile("f1", "结构说明1.xlsx", _W2_STRUCT, index=1)]
    g = guard_section(_W2_SENT, title="一、项目概况", evidence=ev, gen_prompt=_prompt("gaikuang"))
    assert g.content == ("结构形式与耐火、抗震、防水等级口径方面" + MARK_TEMPLATE_ECHO
                         + "，建筑结构安全等级为二级[资料1]；结构抗震设防分类为标准设防类建筑[资料1]。")
    assert [(f.kind, f.text) for f in g.flags] == [("template_echo", "结构形式与耐火抗震防水等级口径")]


def test_r3_w4_lead_phrase_marks_only_the_lead_and_keeps_the_amounts_cited():
    """W4（结算审核报告）第四章：「安装工程专项方面，…3698058.49元…132095.95元[资料5]」，两个金额清单里都有。"""
    prompt = resolve_section("jiesuan_shenhe_bg", "shixiang")["gen_prompt"]
    ev = [EvidenceFile("f5", "送审清单.xlsx", _W4_QD, index=5)]
    g = guard_section(_W4_SENT, title="四、相关事项审核说明", evidence=ev, gen_prompt=prompt)
    assert g.content == ("安装工程专项方面" + MARK_TEMPLATE_ECHO
                         + "，地下室给排水工程分部分项工程费为3698058.49元，其中人工费加机械费为132095.95元[资料5]。")
    assert [(f.kind, f.text) for f in g.flags] == [("template_echo", "安装工程专项")]
    assert {r["value"] for r in g.amount_refs} == {"3698058.49", "132095.95"}


def test_r3_lead_with_colon_marks_only_the_lead():
    prompt = resolve_section("jiesuan_shenhe_bg", "shixiang")["gen_prompt"]
    out = "安装工程专项：地下室给排水工程分部分项工程费为3698058.49元[资料5]。"
    text, flags = check_template_echo(out, prompt, [EvidenceFile("f5", "送审清单.xlsx", _W4_QD, index=5)])
    assert text == f"安装工程专项{MARK_TEMPLATE_ECHO}：地下室给排水工程分部分项工程费为3698058.49元[资料5]。"
    assert [f.text for f in flags] == ["安装工程专项"]


@pytest.mark.parametrize("claim, out", [
    ("口径与金额必须有资料支撑",
     "安装工程专项方面，口径与金额必须有资料支撑，地下室给排水工程分部分项工程费为3698058.49元[资料5]。"),
    ("签证是否计取只写资料中载明的处理结果",
     "安装工程专项方面，地下室给排水工程分部分项工程费为3698058.49元，签证是否计取只写资料中载明的处理结果[资料5]。"),
], ids=["claim-right-after-lead", "claim-at-sentence-end"])
def test_r3_lead_plus_a_real_template_claim_still_marks_the_whole_sentence(claim, out):
    """同一句里既有要素名引子（「安装工程专项方面，」），又有一段不是引子的写作要求原话 → 照旧整句标、去引用
    （D-R153）。只放行「全是引子」的句子；混进一段原话就不能按引子只标引子、留着 [资料5]。

    两段都取自 W4 那一章的写作要求原文；原话放引子后面、放句末各一例。"""
    prompt = resolve_section("jiesuan_shenhe_bg", "shixiang")["gen_prompt"]
    ev = [EvidenceFile("f5", "送审清单.xlsx", _W4_QD, index=5)]
    # 前提：去掉那段原话，同一个引子在同样的写作要求和资料下确实按引子标（这句真有「引子＋原话」的形状）
    lead_only = "安装工程专项方面，地下室给排水工程分部分项工程费为3698058.49元[资料5]。"
    assert check_template_echo(lead_only, prompt, ev)[0] == (
        f"安装工程专项方面{MARK_TEMPLATE_ECHO}，地下室给排水工程分部分项工程费为3698058.49元[资料5]。")
    assert claim in prompt and claim not in _W4_QD

    text, flags = check_template_echo(out, prompt, ev)
    assert text == out.replace("[资料5]", "").replace("。", f"{MARK_TEMPLATE_ECHO}。")
    assert [(f.kind, f.text) for f in flags] == [("template_echo", claim)]


def test_r3_a_comma_after_a_template_claim_is_not_a_lead():
    """片段后面只跟一个「，」不是引子：「规费按招标文件载明的费率下限，中标后不再调整」整句标、去引用。"""
    out = "规费按招标文件载明的费率下限，中标后不再调整[资料25]。"
    text, flags = check_template_echo(out, _prompt("feilv"), _qd(25))
    assert [f.text for f in flags] == ["规费按招标文件载明的费率下限"]
    assert text == f"规费按招标文件载明的费率下限，中标后不再调整{MARK_TEMPLATE_ECHO}。"


def test_r3_no_template_echo_fragment_ends_with_a_digit():
    """生产验收口径：flags 里 kind=template_echo 的 text 没有以数字结尾的。把 R1补 的 9 句、本组的句子和
    「①」起头的写法一起过一遍。"""
    cases = [(c["text"], _prompt(c["section"]), _qd(c["cite"])) for c in _REALRUN["echo"]]
    cases += [
        ("规费费率不低于标准费率的30%。", "③规费（不低于标准费率30%）", _qd(25)),
        # 下面两句的数资料里都没有，照样被标；改前记下的片段是「绿化工程养护期2」「人工费+机械费1」
        ("本工程绿化工程养护期24个月，养护期满验收合格后移交[资料3]。", _YL_SHIXIANG,
         [EvidenceFile("f3", "x.docx", "养护期限详见合同条款。", index=3)]),
        ("技措项目人工费+机械费137382.74元，其余见[资料25]。", _prompt("feilv"), _qd(25)),
    ]
    texts = []
    for out, prompt, ev in cases:
        texts += [f.text for f in check_template_echo(out, prompt, ev)[1]]
    assert texts and not [t for t in texts if t[-1].isdigit()], texts
    assert {"绿化工程养护期", "人工费+机械费"} <= set(texts)


def test_r3_r1b_named_template_sayings_are_still_caught():
    """回归：R1补 运行 R 点名的模板说法（夹具 echo 9 句，覆盖「费率下限」「最低限价 / 固定包干」「以本编制说明为准」
    「总价包干」「全部风险因素」「未尽事宜…」）在本片之后仍然全部被标、引用去掉（验收要求至少 5 个）。"""
    caught = 0
    for c in _REALRUN["echo"]:
        g = guard_section(c["text"], title="", evidence=_qd(c["cite"]), gen_prompt=_prompt(c["section"]))
        if [f.kind for f in g.flags] == ["template_echo"] and "[资料" not in g.content:
            caught += 1
    assert caught == len(_REALRUN["echo"]) == 9
