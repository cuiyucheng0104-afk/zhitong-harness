# 来源：engine-service/tests/test_indicator_chapter_name.py（zhitong-cost-ai@991ff5cd）
"""指标引擎的章节码必须解析成中文名——用户看到 chapter_pct:0105 无法理解。

注:brief 原稿假设 compute_indicators(items, baseline=None) 返回 list、每项含
indicator_code——与真实签名不符。真实签名(indicator_engine.py:39)是
compute_indicators(items: list[dict], meta: dict | None = None) -> dict,
返回 dict,其中 "chapters" 是 list,每项形如
{"chapter","chapter_name","amount","count","pct","unit_cost"}。
以下测试按真实签名/返回结构改写,不改 compute_indicators 的对外签名。
"""
from pathlib import Path

from zt.indicator import engine as indicator_engine

_FIXTURES_DIR = Path(__file__).parents[1] / "costsheet" / "fixtures"


def test_chapter_indicator_carries_chinese_name():
    """章节码由编码现算、中文名查受控码表——不依赖上游 item 自带的 chapter/chapter_name。"""
    items = [
        {"code": "010502001", "name": "矩形柱", "amount": 1000.0},
        {"code": "Z010101001", "name": "挖单独土方", "amount": 500.0},
    ]
    out = indicator_engine.compute_indicators(items)
    by_chapter = {c["chapter"]: c for c in out["chapters"]}
    assert by_chapter["0105"]["chapter_name"] == "混凝土及钢筋混凝土工程"
    assert by_chapter["0101"]["chapter_name"] == "土石方工程"


def test_upstream_chapter_name_is_ignored_in_favor_of_registry():
    """即便上游 item 自带 chapter/chapter_name(如 costsheet 的历史手搓映射),
    也必须被受控码表覆盖——两套口径不一致时,以码表为准。"""
    items = [
        {"code": "010502001", "name": "矩形柱", "amount": 1000.0,
         "chapter": "9999", "chapter_name": "上游瞎猜的名字"},
    ]
    out = indicator_engine.compute_indicators(items)
    by_chapter = {c["chapter"]: c for c in out["chapters"]}
    assert "9999" not in by_chapter
    assert by_chapter["0105"]["chapter_name"] == "混凝土及钢筋混凝土工程"


def test_unknown_chapter_never_falls_back_to_bare_other():
    """WS08-06：归章绝不裸写「其他」。附录码 99 不是国标附录（01–09）→ 非国标编号项；
    国标附录里两张章名表都没有的章 → 「章码 0201（章名表里没有）」（WS26-h2；改前是「附录名·章码」）。"""
    items = [{"code": "999999999", "name": "不存在的项", "amount": 100.0},
             {"code": "020101001001", "name": "仿古土方", "amount": 50.0}]
    out = indicator_engine.compute_indicators(items)
    by_chapter = {c["chapter"]: c for c in out["chapters"]}
    assert by_chapter["NG"]["chapter_name"] == "非国标编号项"
    assert by_chapter["0201"]["chapter_name"] == "章码 0201（章名表里没有）"
    assert all(c["chapter_name"] != "其他" for c in out["chapters"])


def test_run_indicator_rows_carry_chapter_name_field_on_real_fixture():
    """跳过 brief Step 5(重启引擎 + 调 Java /nas/costai/indicator/start 真数据端到端验证)
    ——那步需要拉起 engine-service 进程 + Java 后端 + 登录态,超出本任务(Task 2,只改
    indicator_engine 一处)范围,留给集成阶段统一验。

    这里改用等价强度的替代验证:直接喂真实广联达格式的清单计价表 fixture
    (tests/fixtures/指标-计价表.xlsx,与 test_smoke.py::test_indicator_calc_computes_unit_cost
    同一份样例,过 costsheet.parse_costsheet 真解析出的 items,再过 indicator_engine.run()
    完整接线层——覆盖"真实形态 items → 最终 indicator 行"的全链路,只是不经 HTTP/Java。

    fixture 内 3 条清单:010101001001(章 0101→土石方工程)、010401003001(章 0104→砌筑工程)、
    030101001001(安装专业,zj2025 码表只有 01xx,WS08-06 起查 2013 章名表 → 机械设备安装工程;
    此前这里把「0301 → 其他」写成了期望值,等于把缺陷钉成了规格)。
    """
    raw = (_FIXTURES_DIR / "指标-计价表.xlsx").read_bytes()
    out = indicator_engine.run(
        price_files=[(raw, "指标-计价表.xlsx")],
        baseline={"gross_area": 5000},
        wbs_units=None,
    )
    by_code = {row["indicator_code"]: row for row in out["indicators"]}

    row_0101 = by_code["chapter_pct:0101"]
    assert row_0101["chapter_name"] == "土石方工程"
    assert row_0101["label"] == "土石方工程占比"

    row_0104 = by_code["chapter_pct:0104"]
    assert row_0104["chapter_name"] == "砌筑工程"

    # 安装专业编码不在 zj2025 码表 01xx 范围内 → 2013 章名表（WS08-06，spec 明令改正的期望值）
    row_0301 = by_code["chapter_pct:0301"]
    assert row_0301["chapter_name"] == "机械设备安装工程"

    # chapter_unit_cost:* 系列同样要带 chapter_name(gross_area 已提供,必然产出)
    assert by_code["chapter_unit_cost:0101"]["chapter_name"] == "土石方工程"
