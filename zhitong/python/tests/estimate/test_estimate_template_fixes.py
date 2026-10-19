# 来源：engine-service/tests/test_estimate_template_fixes.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""概算模板三处修正的**独立机器证据**（#131）。

## issue 说的问题成立，但它开的药方救不了 F30

issue 的判词是「三处修正只有 `fixes[].reason` 那段人工论证，没有独立验证」，成立。
但它给的解法（把 `TG_GOLDEN_XLSX` 接进持有金标的环境跑一次）**对 F30 是失明的**——
issue 自己写了「原表里 E35 与 E46 数值恰好相等」，那么 489 格数值逐格比对在这一格
**恒等通过**，金标接上也发现不了。金标能证明的只有「489 格缓存值与上次一致」。

## 真正的独立证据在仓里：修正**前**的形态

入仓的脱敏种子 `gsyz_v1_template.xlsx` 保留的正是三处修正之前的公式（实测
13/13、515/515 精确匹配）。于是「修正前长什么样」不再是 `fixes[].reason` 的
自述，而是可机器校验的入仓事实——**且不需要客户金标、不需要 LibreOffice、
在 CI 里无条件跑**。

## 两条结构不变量各自独立指认 F30

不求值、不重算，纯结构比对（实测数据见各用例）：

1. **同行三列引用一致性**：总表 B/C/F 三列引用同一张表时行号应当一致。
   种子里 20~44 行共 8 行可比对，**行号不一致的恰好 1 行，就是第 30 行**
   （B→专项!46、C→专项!46、而 F→专项!35）。
2. **引用不重不漏**：总表 F26..F33 引用专项表 E 列，种子里 **E35 被引用两次
   （F28、F30），而 E46 一次都没被引用**。

两条不变量各自独立地把矛头指向同一处，且只有「F30 → E46」能同时满足两者——
把 F30 改成任何别的行（哪怕看着也合理的 E42）都会被第 2 条抓住。

## 刻意不做的

不重算、不比数值。数值级证据需要 LibreOffice（不在 CI）或客户金标（不入仓），
而 issue 批评的正是「同源闭环」——用引擎自己的求值结果去证明引擎自己的修正。
本文件全部证据来自**两个入仓文件的结构比对**，与求值器无关。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

_DATA = Path(__file__).resolve().parents[2] / "zt" / "estimate" / "data" / "estimate_templates"
_JSON = _DATA / "gsyz_v1.json"
_SEED = _DATA / "gsyz_v1_template.xlsx"

pytestmark = pytest.mark.skipif(
    not (_JSON.is_file() and _SEED.is_file()),
    reason="模板 JSON 或脱敏种子不在本分支",
)

_REF = re.compile(r"'?([^'!=]+)'?!\$?([A-Z]+)\$?(\d+)")


@pytest.fixture(scope="module")
def tpl() -> dict:
    return json.loads(_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def seed():
    return openpyxl.load_workbook(_SEED, data_only=False)


@pytest.fixture(scope="module")
def before_by_cell(tpl) -> dict:
    """fixes 清单里「修正前」的公式：cell → before。"""
    return {
        c["cell"]: c["before"]
        for fx in tpl["fixes"]
        # 只看公式修正：WS10-P14 的 static 修正（占位符 / 错别字 / 单位）由本文件末尾另一组用例对种子核
        if fx.get("kind") == "formula"
        for c in fx.get("changes", [])
        if "cell" in c
    }


def _cell(wb, ref: str):
    sheet, coord = ref.split("!", 1)
    return wb[sheet][coord].value


# ────────────────────────────────── ① 清单自洽
def test_fix_manifest_and_fixed_flag_are_bijective(tpl, before_by_cell):
    """`fixes[].changes` 与 `formulas[].fixed` 必须一一对应，且 after 真的写进了公式。

    补的是现有测试的真空：`test_fix_sentinel_sum` 只校验 changes 清单本身，
    **从没校验 formulas[] 里真的写进了那个 after** —— 清单说 SUM(C35:C44)
    而公式写别的，今天全绿。
    """
    flagged = {f["cell"] for f in tpl["formulas"] if f.get("fixed")}
    assert set(before_by_cell) == flagged, (
        f"清单 {len(before_by_cell)} 条与 fixed 标记 {len(flagged)} 条对不上："
        f"清单多 {set(before_by_cell) - flagged}，标记多 {flagged - set(before_by_cell)}")
    by_cell = {f["cell"]: f["formula"] for f in tpl["formulas"]}
    after_by_cell = {
        c["cell"]: c["after"]
        for fx in tpl["fixes"] if fx.get("kind") == "formula"
        for c in fx.get("changes", []) if "cell" in c
    }
    bad = [(k, by_cell.get(k), v) for k, v in after_by_cell.items() if by_cell.get(k) != v]
    assert not bad, f"清单的 after 与 formulas[] 实际公式不一致：{bad[:3]}"


# ────────────────────────────────── ② 修正前形态有入仓来源
def test_fix_before_forms_match_committed_seed(tpl, seed, before_by_cell):
    """13 个 fixed 格的「修正前」必须与入仓种子逐字符一致。

    这条把 `fixes[].reason` 的人工论证升级成机器可校验的事实：
    「原表当初就是这么写的」不再是自述。
    """
    bad = [
        (ref, repr(_cell(seed, ref)), repr(want))
        for ref, want in before_by_cell.items()
        if _cell(seed, ref) != want
    ]
    assert not bad, f"{len(bad)} 个 fixed 格的 before 与种子不符：{bad[:3]}"


def test_whole_template_matches_seed_under_fix_manifest(tpl, seed, before_by_cell):
    """全部 515 条公式：fixed 取 before、其余取 after，必须与种子逐格一致。

    把 `build_estimate_template.py` 里那句只在重生成时才跑的断言变成常驻闸——
    堵住「JSON 被手改而种子没动」的漂移。
    """
    diffs = []
    for f in tpl["formulas"]:
        want = before_by_cell.get(f["cell"], f["formula"])
        got = _cell(seed, f["cell"])
        if got != want:
            diffs.append((f["cell"], repr(got)[:40], repr(want)[:40]))
    assert not diffs, f"{len(diffs)}/{len(tpl['formulas'])} 条与种子不一致：{diffs[:3]}"


# ────────────────────────────────── ③ F30 的两条独立结构证据
def _row_parity(get_formula) -> list[tuple[int, dict]]:
    """总表 20~44 行里，B/C/F 三列引用同一张表却行号不一致的行。"""
    out = []
    for row in range(20, 45):
        refs = {}
        for col in "BCF":
            v = get_formula(f"{col}{row}")
            if isinstance(v, str) and v.startswith("="):
                m = _REF.search(v)
                if m:
                    refs[col] = (m.group(1).strip(), int(m.group(3)))
        if len(refs) == 3 and len({s for s, _ in refs.values()}) == 1:
            if len({r for _, r in refs.values()}) > 1:
                out.append((row, dict(refs)))
    return out


def test_seed_has_exactly_one_row_parity_violation_and_it_is_f30(seed):
    """不变量①（对种子跑）：原表**恰好一处**违反同行引用一致性，就是 F30。

    「恰好一处」比「F30 有问题」强得多：它说明这不是普遍现象，
    而是原表里唯一的例外 —— 例外正是缺陷的形状。
    """
    ws = seed["估概算总表"]
    bad = _row_parity(lambda c: ws[c].value)
    assert len(bad) == 1, f"预期恰好 1 处违例，实得 {len(bad)}：{bad}"
    row, refs = bad[0]
    assert row == 30, f"违例行应为 30（F30），实得 {row}"
    assert refs["B"][1] == refs["C"][1] == 46, f"B/C 应指第 46 行：{refs}"
    assert refs["F"][1] == 35, f"F 应指第 35 行（错引）：{refs}"


def test_fixed_template_has_no_row_parity_violation(tpl):
    """不变量①（对修正后模板跑）：修正后一处违例都不许有。"""
    by_cell = {f["cell"]: f["formula"] for f in tpl["formulas"]}
    bad = _row_parity(lambda c: by_cell.get(f"估概算总表!{c}"))
    assert not bad, f"修正后仍有同行引用行号不一致：{bad}"


def test_special_column_refs_are_unique_and_complete(tpl, seed):
    """不变量②：总表 F26..F33 对专项表 E 列的引用，不该重复、不该遗漏。

    种子（原表）：E35 被引用两次、E46 零引用 —— 这是缺陷的正面证据。
    修正后：8 个引用两两不同。**这条锁的是唯一解**：把 F30 改成 E42
    （一个"看着也挺合理"的错值）会因为 E42 已被 F29 占用而被抓住。
    """
    def refs_of(get):
        out = {}
        for row in range(26, 34):
            v = get(f"F{row}")
            if isinstance(v, str):
                m = _REF.search(v)
                if m:
                    out.setdefault(f"{m.group(2)}{m.group(3)}", []).append(row)
        return out

    ws = seed["估概算总表"]
    seed_refs = refs_of(lambda c: ws[c].value)
    assert seed_refs.get("E35") == [28, 30], f"种子里 E35 应被 F28/F30 双引用：{seed_refs.get('E35')}"
    assert "E46" not in seed_refs, "种子里 E46 本不该有人引用（这正是缺陷）"

    by_cell = {f["cell"]: f["formula"] for f in tpl["formulas"]}
    fixed_refs = refs_of(lambda c: by_cell.get(f"估概算总表!{c}"))
    dup = {k: v for k, v in fixed_refs.items() if len(v) > 1}
    assert not dup, f"修正后仍有重复引用：{dup}"
    assert "E46" in fixed_refs, "修正后 F30 应指向 E46"


# ────────────────────────────────── ④ 哨兵行 SUM
def test_sentinel_sum_value_neutrality_holds_in_seed(seed, tpl):
    """哨兵行 SUM 扩围的前提：那些哨兵格在原表里是空的。

    前提成立，扩围才是「值中立的口径修正」而非「改变了金额」——
    这是给客户/造价员解释这处修正时最关键的一句，**而它不需要金标就能验**。
    """
    fx = {f["id"]: f for f in tpl["fixes"]}
    sent = fx.get("sentinel_sum_inclusion")
    assert sent, "模板缺 sentinel_sum_inclusion 修正条目"
    rows_by_sheet: dict[str, set[int]] = {}
    for s in tpl["sheets"]:
        rows_by_sheet[s["name"]] = {
            r["row"] for r in s["rows"] if r.get("role") == "sentinel"
        }
    checked = 0
    for c in sent["changes"]:
        sheet = c["cell"].split("!", 1)[0]
        for row in rows_by_sheet.get(sheet, ()):
            v = seed[sheet][f"C{row}"].value
            assert v in (None, ""), f"{sheet}!C{row} 哨兵格在种子里非空（{v!r}），值中立前提不成立"
            checked += 1
    assert checked, "一个哨兵格都没校验到 —— role=sentinel 的标注可能没了"


def test_sentinel_sum_covers_the_sentinel_row(tpl):
    """修正后每条小计 SUM 的末行必须覆盖到该组哨兵行。"""
    fx = {f["id"]: f for f in tpl["fixes"]}
    changes = fx["sentinel_sum_inclusion"]["changes"]
    rng = re.compile(r"SUM\([A-Z]+(\d+):[A-Z]+(\d+)\)")
    bad = []
    for c in changes:
        m = rng.search(c["after"])
        if not m:
            continue
        end_before = rng.search(c["before"])
        if end_before and int(m.group(2)) <= int(end_before.group(2)):
            bad.append((c["cell"], c["before"], c["after"]))
    assert not bad, f"这些修正没有扩大 SUM 区间：{bad[:3]}"


# ────────────────────────────────── ⑤ 序号重建
def test_seq_rebuild_before_matches_seed(tpl, seed):
    """seq_rebuild 的 before 必须与种子 A 列原值一致（同样把自述变成事实）。"""
    fx = {f["id"]: f for f in tpl["fixes"]}
    sq = fx.get("seq_rebuild")
    assert sq, "模板缺 seq_rebuild 修正条目"
    bad = []
    for c in sq["changes"]:
        got = seed[c["sheet"]][f"A{c['row']}"].value
        if str(got) != str(c["before"]):
            bad.append((c["sheet"], c["row"], repr(got), repr(c["before"])))
    assert not bad, f"{len(bad)} 条 seq before 与种子不符：{bad[:3]}"


# ────────────────────────────────── ④ WS10-P14：static 修正（占位符 / 错别字 / 单位）
def test_static_fixes_are_recorded_and_their_before_forms_come_from_the_seed(tpl, seed):
    """每条 static 修正：before 与入仓种子逐字符一致（修正前的形态有独立来源），
    after 真的写进了模板 static，行名列的修正同步进了行 label。

    变异：从 build_estimate_template.STATIC_FIXES 删一条再重生成 → 本条（条数）与
    test_estimate_render_notes 的占位符扫描各自转红。
    """
    fix = next(f for f in tpl["fixes"] if f["id"] == "static_text_fixes")
    assert fix["kind"] == "static" and len(fix["changes"]) == 16
    rows = {(s["name"], r["row"]): r for s in tpl["sheets"] for r in s["rows"]}
    for ch in fix["changes"]:
        sheet, coord = ch["cell"].split("!", 1)
        col = coord.rstrip("0123456789")
        row_no = int(coord[len(col):])
        assert seed[sheet][coord].value == ch["before"], ch["cell"]
        r = rows[(sheet, row_no)]
        assert r["static"][col] == ch["after"], ch["cell"]
        if col == "B" and r["role"] == "row":
            assert r["label"] == ch["after"], ch["cell"]
    labels = {i["cell"]: i["label"] for i in tpl["inputs"]}
    assert labels["5.工程建设其他费用!C17"] == "勘察设计费"
    assert labels["4.室外及配套工程费!C13"] == "海绵城市工程"
