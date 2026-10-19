#!/usr/bin/env python3
"""K6 生成器：浙江2025清单易混淆编码与列项校核规则（系统口径）。

受控源（全部取自同一个 commit，默认 33601ca8）：
  engine-service/app/engine/data/quantity_rules.yaml   consistency_rules（16 条）、confusables（9 条）
  engine-service/app/engine/data/gb50854_zj2025.yaml   把 expect / forbid 前缀展开成编码 + 名称 + 单位

用法（默认 --repo 仓根、--out out/、--report local_only/K6_check.json）：
  python3 gen_rules.py [--repo <仓根>] [--commit 33601ca8] [--out DIR] [--report JSON]
  生成时间取环境变量 SOURCE_DATE_EPOCH（秒），没有则取当前时间；固定它即可逐字节复现。

纪律：只从受控源确定性生成，不转录任何数字，不含任何金额；生成后自检不过就非零退出。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from kbsrc import SNAPSHOT_REPO, full_commit, git_show_bytes

SCRIPT = "gen_rules.py"
RULES_PATH = "engine-service/app/engine/data/quantity_rules.yaml"
ZJ_PATH = "engine-service/app/engine/data/gb50854_zj2025.yaml"
FILE_NAME = "【清单·房屋建筑】浙江2025清单易混淆编码与列项校核规则（系统口径）.md"
TITLE = "浙江2025清单易混淆编码与列项校核规则（系统口径）"

# 规则的场景短名（展示用标签，写进「应列 / 禁列」单元格，保证 GREP 片段里能看到这是哪条规则的应列 / 禁列）。
# 规则 id 集合必须与 yaml 完全一致，yaml 增删规则时这里会先报错，逼人复核。
RULE_LABEL = {
    "skirting": "踢脚",
    "ceiling_paint": "顶棚刷涂料",
    "floor_coating_waterproof": "楼地面涂膜防水",
    "slab_membrane": "基础底板卷材防水",
    "retaining_wall": "挡土墙",
    "fine_concrete_not_cement_floor": "细石混凝土层",
    "roof_leveling_not_floor": "屋面找平层",
    "roof_membrane": "屋面卷材防水",
    "roof_coating": "屋面涂膜防水",
    "wall_waterproof_not_roof": "墙面防水",
    "floor_membrane_not_roof": "楼地面卷材防水",
    "floor_tile_not_wall": "楼地面块料",
    "wall_tile_not_floor": "墙面块料",
    "ceiling_suspended_not_plaster": "吊顶",
    "wall_paint_not_plaster": "墙面刷涂料",
    "roof_insulation": "屋面保温",
}

# 触发条件字段 → 中文。顺序与引擎 _rule_applies 一致；多个条件是「且」。
COND_PHRASE = {
    "any": ("原文或上下文含", True),
    "text_any": ("原文含", True),
    "ctx_any": ("上下文含", True),
    "any_none": ("原文和上下文都不含", False),
    "text_none": ("原文不含", False),
    "ctx_none": ("上下文不含", False),
}
KNOWN_RULE_KEYS = set(COND_PHRASE) | {"id", "expect", "forbid", "message"}

CODE_RE = re.compile(r"(?<![0-9A-Za-z])Z?\d{9}(?!\d)")
DIGITS_RE = re.compile(r"\d{9,}")
MONEY_RE = re.compile(r"\d+(\.\d+)?\s*(元|万元)")
XXX_RE = re.compile(r"(?<![0-9A-Za-z])(Z?)(\d{6})xxx")
SECTION_DASH_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})(?!\d)")
CN_TZ = timezone(timedelta(hours=8))


git_show = git_show_bytes


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def gen_time() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    dt = datetime.fromtimestamp(int(epoch), CN_TZ) if epoch else datetime.now(CN_TZ).replace(microsecond=0)
    return dt.isoformat()


def cell(s: str) -> str:
    """表格单元格：不许换行，| 转义。"""
    s = str(s).replace("\r", "").replace("\n", "；")
    return s.replace("|", "\\|")


def bare(code: str) -> str:
    return code[1:] if code[:1] == "Z" else code


def sort_key(code: str):
    b = bare(code)
    return (b[:4], b[:9], 1 if code[:1] == "Z" else 0)


def line_of(lines: list[str], pattern: str, start: int = 0) -> int:
    rx = re.compile(pattern)
    for i in range(start, len(lines)):
        if rx.search(lines[i]):
            return i + 1
    raise SystemExit(f"源文件里找不到 {pattern!r}")


def words_phrase(words: list[str], positive: bool) -> str:
    q = "".join(f"「{w}」" for w in words)
    if positive and len(words) > 1:
        return q + "之一"
    return q


def trigger_text(rule: dict) -> str:
    parts = []
    for key in rule:  # 按 yaml 里写的顺序
        if key not in COND_PHRASE:
            continue
        head, positive = COND_PHRASE[key]
        parts.append(head + words_phrase(list(rule[key]), positive))
    return "，且".join(parts)


def code_entry(code: str, codes: dict) -> str:
    it = codes[code]
    return f"{code}「{it['name']}」（{it['unit']}）"


def expand(prefix: str, codes: dict) -> list[str]:
    return sorted((c for c in codes if bare(c).startswith(prefix)), key=sort_key)


def prefix_cell(kind: str, label: str, prefixes: list[str], codes: dict, chapters: dict, rule_id: str) -> str:
    if not prefixes:
        return "—"
    chunks = []
    for p in prefixes:
        hits = expand(p, codes)
        if not hits:
            raise SystemExit(f"规则 {rule_id} 的前缀 {p} 在浙江2025码表里一个都对不上")
        if len(p) == 9:
            if len(hits) != 1:
                raise SystemExit(f"规则 {rule_id} 的 9 位前缀 {p} 对上 {len(hits)} 个编码")
            chunks.append(code_entry(hits[0], codes))
        elif len(p) == 6:
            chunks.append(f"{p} 节 {len(hits)} 个：" + "、".join(code_entry(c, codes) for c in hits))
        elif len(p) == 4:
            # 章级前缀：整章几十个码逐个写进一格会让 GREP 片段看不到「禁列」语境，改写章名 + 数量 + 块料类举例，
            # 逐码见浙江2025清单编码表对应章。只允许出现在两条块料规则里，别的规则出现章级前缀先报错复核。
            if rule_id not in ("floor_tile_not_wall", "wall_tile_not_floor"):
                raise SystemExit(f"规则 {rule_id} 出现章级前缀 {p}，需人工复核展开方式")
            tiles = [c for c in hits if "块料" in codes[c]["name"]]
            chunks.append(f"{p} 整章「{chapters[p]}」全部 {len(hits)} 个编码（逐码见浙江2025清单编码表 {p} 章），"
                          f"其中块料类 {len(tiles)} 个：" + "、".join(code_entry(c, codes) for c in tiles))
        else:
            raise SystemExit(f"规则 {rule_id} 的前缀 {p} 长度异常")
    return f"{kind}（{label}）：" + "；".join(chunks)


def confusable_codes(text: str, codes: dict, chapters: dict) -> str:
    out = []
    for m in SECTION_DASH_RE.finditer(text):
        p = m.group(1) + m.group(2)
        hits = expand(p, codes)
        if not hits:
            raise SystemExit(f"confusables 里的 {m.group(0)} 在码表里对不上")
        out.append(f"{m.group(0)}＝{p} 节 {len(hits)} 个编码（逐码见浙江2025清单编码表 {p[:4]} 章）")
    for m in XXX_RE.finditer(text):
        p = m.group(2)
        hits = expand(p, codes)
        if not hits:
            raise SystemExit(f"confusables 里的 {m.group(0)} 在码表里对不上")
        out.append(f"{m.group(0)}＝去掉 Z 后以 {p} 开头的 {len(hits)} 个编码（逐码见浙江2025清单编码表 {p[:4]} 章）")
    seen = set()
    for m in CODE_RE.finditer(text):
        c = m.group(0)
        if c in seen:
            continue
        seen.add(c)
        if c not in codes:
            raise SystemExit(f"confusables 里的编码 {c} 不在浙江2025码表")
        out.append(code_entry(c, codes))
    return "；".join(out) if out else "—"


def annotate_message(msg: str, codes: dict) -> str:
    """规则说明照录；说明里出现、但名称没写出来的编码，在后面用〔码表：…〕补注浙江2025 名称和单位。"""
    extra = []
    for m in CODE_RE.finditer(msg):
        c = m.group(0)
        if c not in codes:
            raise SystemExit(f"规则说明里的编码 {c} 不在浙江2025码表")
        if codes[c]["name"] not in msg and c not in [e[0] for e in extra]:
            extra.append((c, code_entry(c, codes)))
    return msg + ("〔码表：" + "；".join(e[1] for e in extra) + "〕" if extra else "")


def build(repo: str, commit: str) -> tuple[str, dict]:
    commit_full = full_commit(repo, commit)
    rules_b = git_show(repo, commit, RULES_PATH)
    zj_b = git_show(repo, commit, ZJ_PATH)
    rules = yaml.safe_load(rules_b.decode("utf-8"))
    zj = yaml.safe_load(zj_b.decode("utf-8"))
    rlines = rules_b.decode("utf-8").split("\n")
    codes = zj["codes"]
    chapters = {str(k): v for k, v in zj["chapters"].items()}

    crs = rules["consistency_rules"]
    conf = rules["confusables"]
    ids = [r["id"] for r in crs]
    if set(ids) != set(RULE_LABEL) or len(ids) != len(set(ids)):
        raise SystemExit(f"规则 id 与标签表不一致：yaml={ids}")
    for r in crs:
        unknown = set(r) - KNOWN_RULE_KEYS
        if unknown:
            raise SystemExit(f"规则 {r['id']} 有未知字段 {unknown}，需先更新生成器")

    t = gen_time()
    head = [
        f"> 来源：zhitong-cost-ai 仓库 `{RULES_PATH}`（commit {commit_full[:8]}；源文件 sha256 {sha256(rules_b)}）"
        f"的 consistency_rules（{len(crs)} 条）与 confusables（{len(conf)} 条）；编码名称与单位取自 `{ZJ_PATH}`"
        f"（同一 commit；sha256 {sha256(zj_b)}）。",
        f"> 生成：{SCRIPT}，生成时间 {t}",
        "> 声明：本文件由脚本从受控源确定性生成，不含任何金额；引用编码必须注明版本（浙江2025 / 国标2013）。",
        "> 口径：这是智通造价 AI 工程量清单生成的系统校核口径（语义一致性闸与易混淆对照），不是规范原文；"
        "规范原文以 GB50854 及浙江2025版清单为准。",
        "> 版本：本文件所有编码均为浙江2025（GB50854 浙江省2025版）；「Z」开头的是浙江补充编码。"
        "同一 9 位编码在国标2013 中可能是另一个项目，不能混用。",
        "> 读法：表一每行一条规则，列为 规则 id｜触发条件｜应列编码及名称｜禁列编码及名称｜说明｜出处；"
        "表二逐条照录易混淆对照，列为 序号｜易混淆对照（照录）｜涉及编码（浙江2025 名称与单位）｜出处。",
        "",
        f"# {TITLE}",
        "",
        "## 使用说明",
        "",
        f"- 原文、上下文：原文是做法层文字本身；上下文是类别、部位、做法名、标题。触发词按子串匹配（NFKC 规范化后），"
        f"多个条件同时满足才触发。出处：quantity_rules.yaml 第{line_of(rlines, r'^# 字段：')}–"
        f"{line_of(rlines, r'expect：编码')}行注释。",
        "- 应列：编码去掉浙江补充 Z 前缀后，必须以所列前缀之一开头；禁列：去掉 Z 后不许以所列任何前缀开头。"
        "表中 9 位前缀和 6 位节前缀已按浙江2025码表逐码展开成编码、名称和计量单位；4 位整章前缀写章名、编码数和其中的块料类编码，"
        "逐码见浙江2025清单编码表对应章。",
        "- 规则只判不改：不符合规则的清单条目降为「待核」，建议栏写规则期望的码表名称，从不替模型改码。"
        f"出处：quantity_rules.yaml 第{line_of(rlines, r'从不替模型改码')}行注释；quantity_rules.py check_consistency（commit 同上）。",
        "- 「说明」列照录规则原文；原文里只写了编码没写名称的，在〔码表：…〕里补注浙江2025 名称和单位。",
        "- 报编码时写明「浙江2025」；需要国标2013 口径时另查国标2013 全文和同码异名对照表。",
        "",
        f"## 表一 列项校核规则（{len(crs)} 条）",
        "",
        "| 规则 id | 触发条件 | 应列编码及名称 | 禁列编码及名称 | 说明 | 出处 |",
        "|---|---|---|---|---|---|",
    ]
    rows_out = []
    for r in crs:
        rid = r["id"]
        ln = line_of(rlines, rf"^\s*- id: {re.escape(rid)}\s*$")
        exp = prefix_cell("应列", RULE_LABEL[rid], list(r.get("expect") or []), codes, chapters, rid)
        forb = prefix_cell("禁列", RULE_LABEL[rid], list(r.get("forbid") or []), codes, chapters, rid)
        src = f"quantity_rules.yaml consistency_rules[{rid}] 第{ln}行"
        head.append("| " + " | ".join(cell(x) for x in (rid, trigger_text(r), exp, forb, annotate_message(r["message"], codes), src)) + " |")
        rows_out.append({"id": rid, "line": ln})
    head += [
        "",
        f"## 表二 易混淆对照（{len(conf)} 条）",
        "",
        "| 序号 | 易混淆对照（照录） | 涉及编码（浙江2025 名称与单位） | 出处 |",
        "|---|---|---|---|",
    ]
    conf_start = line_of(rlines, r"^confusables:")
    conf_lines = []
    for i, text in enumerate(conf):
        ln = line_of(rlines, r"^\s*- " + re.escape(text) + r"\s*$", conf_start)
        conf_lines.append(ln)
        head.append("| " + " | ".join(cell(x) for x in (
            str(i + 1), text, confusable_codes(text, codes, chapters),
            f"quantity_rules.yaml confusables[{i}] 第{ln}行")) + " |")
    md = "\n".join(head) + "\n"
    meta = {
        "file": FILE_NAME, "script": SCRIPT, "generated_at": t, "commit": commit_full,
        "sources": {RULES_PATH: sha256(rules_b), ZJ_PATH: sha256(zj_b)},
        "rule_lines": rows_out, "confusables_lines": conf_lines,
        "_rules_obj": rules, "_codes": codes,
    }
    return md, meta


# ------------------------------------------------------------------ 自检

def parse_tables(md: str) -> list[dict]:
    """返回 [{header: [...], rows: [(lineno, [cells])]}]；按未转义的 | 切分。"""
    lines = md.split("\n")
    tables, i = [], 0
    split = lambda s: [c.strip() for c in re.split(r"(?<!\\)\|", s.strip())[1:-1]]  # noqa: E731
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|(\s*-+\s*\|)+\s*$", lines[i + 1]):
            header = split(lines[i])
            rows, j = [], i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append((j + 1, split(lines[j])))
                j += 1
            tables.append({"header": header, "rows": rows})
            i = j
        else:
            i += 1
    return tables


def self_check(md: str, meta: dict) -> dict:
    codes = meta["_codes"]
    rules = meta["_rules_obj"]
    problems = []
    raw = md.encode("utf-8")
    if raw.startswith(b"\xef\xbb\xbf"):
        problems.append("有 BOM")
    if b"\r" in raw:
        problems.append("有 CR")
    heads = [l for l in md.split("\n") if l.startswith("#")]
    if len(heads) > 200:
        problems.append(f"标题 {len(heads)} 个 > 200")
    if MONEY_RE.search(md):
        problems.append(f"金额正则命中：{MONEY_RE.search(md).group(0)}")
    # 首个标题前必须是文件头引用块
    first_h = next(i for i, l in enumerate(md.split("\n")) if l.startswith("#"))
    pre = [l for l in md.split("\n")[:first_h] if l.strip()]
    if not pre or not all(l.startswith(">") for l in pre):
        problems.append("文件头不是首个标题前的引用块")
    if "系统校核口径" not in "\n".join(pre) or "不是规范原文" not in "\n".join(pre):
        problems.append("文件头未注明系统校核口径、不是规范原文")
    # 所有 ≥9 位数字串必须是码表里的编码（9 位 / Z+9 位）
    unknown = []
    for m in DIGITS_RE.finditer(md):
        s = m.group(0)
        if len(s) != 9:
            unknown.append(s)
            continue
        z = md[m.start() - 1] == "Z" if m.start() > 0 else False
        code = ("Z" if z else "") + s
        if code not in codes:
            unknown.append(code)
    if unknown:
        problems.append(f"不在浙江2025码表的编码/数字串：{sorted(set(unknown))}")
    # 编码「名称」必须与码表一致
    name_bad = []
    for m in re.finditer(r"(Z?\d{9})「([^」]+)」（([^）]+)）", md):
        c, n, u = m.groups()
        if c not in codes or codes[c]["name"] != n or codes[c]["unit"] != u:
            name_bad.append((c, n, u))
    for m in re.finditer(r"(Z?\d{9})「([^」]+)」", md):
        c, n = m.groups()
        if c not in codes or codes[c]["name"] != n:
            name_bad.append((c, n))
    # 照录文本里「编码 名称」写法（confusables[1] 的 011404002 天棚喷刷涂料）
    for m in re.finditer(r"(Z?\d{9}) (天棚喷刷涂料)", md):
        c, n = m.groups()
        if codes[c]["name"] != n:
            name_bad.append((c, n))
    if name_bad:
        problems.append(f"编码名称/单位与码表不一致：{name_bad}")
    tables = parse_tables(md)
    if len(tables) != 2:
        problems.append(f"表格数 {len(tables)} ≠ 2")
    else:
        t1, t2 = tables
        ids = [r[1][0] for r in t1["rows"]]
        want = [r["id"] for r in rules["consistency_rules"]]
        if ids != want:
            problems.append(f"表一规则 id 与 yaml 不一致：{ids} vs {want}")
        texts = [r[1][1] for r in t2["rows"]]
        if [t.replace("\\|", "|") for t in texts] != list(rules["confusables"]):
            problems.append("表二未逐条照录 confusables")
        for t in tables:
            n = len(t["header"])
            for ln, cells in t["rows"]:
                if len(cells) != n:
                    problems.append(f"第{ln}行单元格数 {len(cells)} ≠ {n}（疑似未转义 |）")
                if t["header"][-1] != "出处" or not cells[-1] or cells[-1] == "—":
                    problems.append(f"第{ln}行出处为空")
    fn = FILE_NAME
    if len(fn) > 60 or len(fn.encode("utf-8")) > 255 - 19 or re.search(r'[|/\\<>:"?*;,]', fn) or fn != fn.strip():
        problems.append("文件名不合规")
    return {
        "file": fn, "chars": len(md), "bytes": len(raw), "lines": md.count("\n"),
        "headings": len(heads), "rules": len(rules["consistency_rules"]),
        "confusables": len(rules["confusables"]),
        "codes_mentioned": sorted(set(c.group(0) for c in CODE_RE.finditer(md)), key=sort_key),
        "over_16000_chars": len(md) > 16000, "problems": problems,
    }


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(SNAPSHOT_REPO))   # 源快照根（见 kbsrc.py）
    ap.add_argument("--commit", default="33601ca8")
    ap.add_argument("--out", default=str(here / "out"))
    ap.add_argument("--report", default=str(here / "local_only" / "K6_check.json"))
    a = ap.parse_args()
    md, meta = build(a.repo, a.commit)
    rep = self_check(md, meta)
    rep.update({k: v for k, v in meta.items() if not k.startswith("_")})
    out = Path(a.out) / FILE_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(md.encode("utf-8"))
    rep["sha256"] = sha256(md.encode("utf-8"))
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("file", "chars", "lines", "headings", "rules", "confusables",
                                          "sha256", "problems")}, ensure_ascii=False, indent=1))
    return 1 if rep["problems"] or rep["over_16000_chars"] else 0


if __name__ == "__main__":
    sys.exit(main())
