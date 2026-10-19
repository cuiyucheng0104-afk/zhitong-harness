# 来源：engine-service/tests/test_code_registry.py（zhitong-cost-ai@991ff5cd）
"""GB50854 码表查表模块测试。码表是受控基础数据，查表必须确定性、零 LLM。"""
import pytest
from zt.code_registry import registry as code_registry


def test_load_registry_has_490_codes():
    reg = code_registry.load_registry("zj2025")
    assert len(reg) == 490


def test_lookup_known_code_returns_name_and_unit():
    item = code_registry.lookup("010103001", "zj2025")
    assert item is not None
    assert item["name"] == "平整场地"
    assert item["unit"] == "m²"


def test_lookup_zhejiang_prefixed_code():
    item = code_registry.lookup("Z010101001", "zj2025")
    assert item is not None
    assert item["name"] == "挖单独土方"


def test_lookup_unknown_code_returns_none():
    assert code_registry.lookup("999999999", "zj2025") is None


def test_chapter_of_strips_z_prefix():
    assert code_registry.chapter_of("Z010101001") == "0101"
    assert code_registry.chapter_of("010103001") == "0101"


def test_chapter_name_resolves_chinese():
    assert code_registry.chapter_name("0101", "zj2025") == "土石方工程"


def test_chapter_name_unknown_returns_other():
    assert code_registry.chapter_name("9999", "zj2025") == "其他"


def test_available_versions_includes_zj2025():
    assert "zj2025" in code_registry.available_versions()


def test_unknown_version_raises():
    with pytest.raises(ValueError):
        code_registry.load_registry("nonexistent2099")


def test_every_chapter_prefix_in_data_has_a_name():
    """章节映射不能有缺口：数据里出现的每个章节前缀都必须能查到中文名。
    ⚠ 490 条数量校验挡不住这类错误——编码抓全了但章节没映射上，
       会静默归为「其他」，让 indicator 汇总时漏掉整个章节。"""
    reg = code_registry.load_registry("zj2025")
    prefixes = {item["chapter"] for item in reg.values()}
    unmapped = {p for p in prefixes
                if code_registry.chapter_name(p, "zj2025") == code_registry.UNKNOWN_CHAPTER_NAME}
    assert not unmapped, f"这些章节前缀没有中文名映射: {sorted(unmapped)}"


def test_zhejiang_measure_items_map_to_0118():
    """8 条浙江补充措施项目（Z0118xxxxx）应该映射到「措施项目」而非「其他」。
    这是 0117→0118 修正的防回归测试。"""
    reg = code_registry.load_registry("zj2025")
    z0118_codes = [code for code in reg.keys() if code.startswith("Z0118")]
    assert len(z0118_codes) == 8, f"期望 8 条 Z0118 编码，实际 {len(z0118_codes)} 条"
    for code in z0118_codes:
        item = reg[code]
        assert item["chapter"] == "0118", f"{code} 的章节码不是 0118，而是 {item['chapter']}"
        assert item["chapter_name"] == "措施项目", f"{code} 的章节名应是'措施项目'，实际是'{item['chapter_name']}'"


# ---------------------------------------------------------------- 章名兜底（WS26-h2，07-010 第 1 项，RF-30）

@pytest.mark.parametrize("code,key,appendix_name", [
    ("060201001001", "0602", "矿山工程"),            # 生产：10 条「预埋铁件」显示成「矿山工程·0602」
    ("080901001001", "0809", "城市轨道交通工程"),    # 生产：1 条「电梯调试」显示成「城市轨道交通工程·0809」
    ("020101001001", "0201", "仿古建筑工程"),
])
def test_chapter_not_in_name_tables_is_written_as_code_not_appendix_name(code, key, appendix_name):
    """章码在两张章名表里都查不到时，章名写「章码 0602（章名表里没有）」——不再拿附录名顶上去。
    0602 不是「矿山工程」的一章：查不到就说查不到（铁律 3）。附录名仍在 appendix_name 字段里，不显示成章名。"""
    ch = code_registry.classify_chapter(code)
    assert ch.key == key
    assert ch.name == f"章码 {key}（章名表里没有）"
    assert appendix_name not in ch.name
    assert ch.appendix_name == appendix_name
    assert not ch.standard, "兜底章名不算标准章名（chapter_coverage 不数它）"


def test_section_chapter_not_in_tables_uses_same_fallback():
    """无编码行靠分部标题里的章码归章，查不到同样写章码，不写附录名。"""
    ch = code_registry.classify_chapter("", section="0602 预埋件")
    assert (ch.key, ch.name) == ("0602", "章码 0602（章名表里没有）")


def test_fallback_names_are_unique_per_code_so_labels_need_no_suffix():
    chapters = [{"chapter": "0602", "chapter_name": code_registry.classify_chapter("060201001001").name},
                {"chapter": "0809", "chapter_name": code_registry.classify_chapter("080901001001").name}]
    code_registry.unique_chapter_labels(chapters)
    assert [c["label"] for c in chapters] == ["章码 0602（章名表里没有）", "章码 0809（章名表里没有）"]
