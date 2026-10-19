#!/usr/bin/env python3
"""KB-GEN-ZJ：由受控码表 gb50854_zj2025.yaml 确定性生成知识库 K1–K5（浙江2025 清单编码表）。

来源：zhitong-cost-ai 仓库 `engine-service/app/engine/data/gb50854_zj2025.yaml` @ 33601ca8，
      默认直接 `git show <commit>:<path>` 读取（不经本地拷贝），并记录源字节 sha256。

输出（UTF-8 无 BOM、LF）：每个编码一行 markdown 表格行
      | 编码 | 项目名称 | 计量单位 | 版本 | 章 | 项目特征 | 出处 |
  · 版本 固定「浙江2025」；章 = 4 位章码（Z 码去 Z 后取前 4 位，与引擎 code_registry.chapter_of 一致）
  · 项目特征 = features_text 各行 strip、去空行后用「；」连接
  · 出处 = `zj2025.yaml codes.<编码>`
  · 单元格内 `|` 转义为 `\\|`，不含换行

分组按方案 §1.2（K1 0101-0104 / K2 0105-0107 / K3 0108-0110 / K4 0111-0115 / K5 0116、0118）；
任一文件超过 --split-at（默认 16000，即方案 §1.2「超过 16000 字就按章再拆」）就按章再拆，文件名随章码范围改变；
--max-chars（默认 16000，与引擎 DOC_MAX_CHARS 一致）是回读硬门槛。
KB-GATE 改定（2026-10-01）：默认阈值由 15000 改回方案字面的 16000。未拆的 K2 为 15826 字，
引擎 _read_doc_text 按「各行 len+1 累加、超过 16000 才截断」计数，K2 一次 DOC 能读完，故 K2 不拆；
K4 为 18283 字，仍按章拆成 0111 与 0112-0115 两份。

自带回读：写完后从磁盘重新读取全部输出，用独立解析器解析，与重新 git show 得到的 yaml 逐字段比对
（编码集合正好 490、名称/单位/特征 0 差异），并做格式与金额门槛检查；任一不过 → 退出码 1。

用法（默认 --repo 仓根、--out out/、--stats local_only/zj2025_stats.json）：
  python3 gen_zj2025.py [--repo <仓根>] [--commit 33601ca8]
                        [--src 本地yaml(仅离线兜底)] [--out DIR] [--stats JSON]
                        [--generated-at 2026-10-01T01:45:08+08:00] [--max-chars 16000] [--split-at 16000]
  python3 gen_zj2025.py --verify-only   # 只对已有输出做回读比对
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import yaml

from kbsrc import SNAPSHOT_REPO, git_show_bytes

HERE = Path(__file__).resolve().parent
DEFAULT_REPO = str(SNAPSHOT_REPO)   # 源快照根（见 kbsrc.py）
DEFAULT_COMMIT = "33601ca8"
SRC_PATH = "engine-service/app/engine/data/gb50854_zj2025.yaml"
SRC_TAG = "zj2025.yaml"
SCRIPT_NAME = "gen_zj2025.py"
VERSION_LABEL = "浙江2025"
EXPECTED_TOTAL = 490
FILE_PREFIX = "【清单·房屋建筑】浙江2025清单编码表-"
DECLARATION = "本文件由脚本从受控源确定性生成，不含任何金额；引用编码必须注明版本（浙江2025 / 国标2013）"
K9_NAME = "【清单·房屋建筑】国标2013与浙江2025清单同码异名对照表.md"
COLUMNS = ["编码", "项目名称", "计量单位", "版本", "章", "项目特征", "出处"]

# 方案 §1.2 的 K1–K5 分组：(编号, 标题, 章码列表, 期望码数)
GROUPS = [
    ("K1", "土石方地基桩基砌筑", ["0101", "0102", "0103", "0104"], 82),
    ("K2", "混凝土金属木结构", ["0105", "0106", "0107"], 140),
    ("K3", "门窗屋面防水保温", ["0108", "0109", "0110"], 98),
    ("K4", "装饰工程", ["0111", "0112", "0113", "0114", "0115"], 129),
    ("K5", "拆除与措施项目", ["0116", "0118"], 41),
]
# 按章再拆时用的短名（只在超限拆分时参与文件名）
CHAPTER_SHORT = {
    "0101": "土石方", "0102": "地基处理与边坡支护", "0103": "桩基", "0104": "砌筑",
    "0105": "混凝土及钢筋混凝土", "0106": "金属结构", "0107": "木结构",
    "0108": "门窗", "0109": "屋面及防水", "0110": "保温隔热防腐",
    "0111": "楼地面装饰", "0112": "墙柱面装饰与隔断幕墙", "0113": "天棚",
    "0114": "油漆涂料裱糊", "0115": "其他装饰", "0116": "拆除", "0118": "措施项目",
}
# 拆分后常见片段的可读标题（没有命中时退回 CHAPTER_SHORT 拼接）
SPLIT_TITLES = {
    ("0105",): "混凝土及钢筋混凝土",
    ("0106", "0107"): "金属结构与木结构",
    ("0111",): "楼地面装饰",
    ("0112", "0113", "0114", "0115"): "墙柱面隔断幕墙、天棚、油漆涂料裱糊及其他装饰",
}

MONEY_RE = re.compile(r"\d+(\.\d+)?\s*(元|万元)")
CODE_RE = re.compile(r"^Z?\d{9}$")
FORBIDDEN_NAME_CHARS = set('|/\\<>:"?*;,')
MAX_NAME_CHARS = 60
MAX_NAME_BYTES = 255 - 19
MAX_HEADINGS = 200
MAX_LINES = 600


# ---------------------------------------------------------------- 源读取

def read_source(repo: str, commit: str, src: str | None) -> tuple[bytes, str]:
    """返回 (源字节, 来源描述)。默认 git show，--src 仅作离线兜底。"""
    if src:
        return Path(src).read_bytes(), f"本地文件 {src}"
    raw = git_show_bytes(repo, commit, SRC_PATH)
    return raw, f"git show {commit}:{SRC_PATH}"


def load_codes(raw: bytes) -> tuple[dict, dict, dict]:
    doc = yaml.safe_load(raw.decode("utf-8"))
    chapters = {str(k): v for k, v in (doc.get("chapters") or {}).items()}
    codes = {str(k): v for k, v in (doc.get("codes") or {}).items()}
    meta = {k: doc.get(k) for k in ("standard", "region", "edition", "version", "source")}
    return chapters, codes, meta


def chapter_of(code: str) -> str:
    c = code.strip()
    if c.startswith(("Z", "z")):
        c = c[1:]
    return c[:4]


def feature_lines(ft: str) -> list[str]:
    return [ln.strip() for ln in (ft or "").split("\n") if ln.strip()]


def sort_key(code: str) -> tuple[str, int]:
    return (code.lstrip("Z"), 1 if code.startswith("Z") else 0)


# ---------------------------------------------------------------- 渲染

def esc(cell: str) -> str:
    s = str(cell).replace("\r", " ").replace("\n", " ")
    return s.replace("|", "\\|")


def range_label(chs: list[str]) -> str:
    """连续章码写 a-b，不连续写 a、b。"""
    if len(chs) == 1:
        return chs[0]
    nums = [int(c) for c in chs]
    if all(b - a == 1 for a, b in zip(nums, nums[1:])):
        return f"{chs[0]}-{chs[-1]}"
    return "、".join(chs)


def file_name(title: str, chs: list[str]) -> str:
    return f"{FILE_PREFIX}{title}（{range_label(chs)}）.md"


def render(unit: dict, all_units: list[dict], chapters: dict, codes: dict, meta: dict,
           sha256: str, commit: str, gen_at: str) -> str:
    chs = unit["chapters"]
    ch_codes = {ch: sorted((c for c in codes if chapter_of(c) == ch), key=sort_key) for ch in chs}
    n = sum(len(v) for v in ch_codes.values())
    ch_desc = "、".join(f"{ch} {chapters[ch]}" for ch in chs)
    siblings = "；".join(f"{u['title']}（{range_label(u['chapters'])}）" for u in all_units)
    lines = [
        f"> 来源：zhitong-cost-ai 仓库 `{SRC_PATH}`（commit {commit}；源文件 sha256 {sha256}）",
        f"> 码表元数据：standard={meta['standard']}，region={meta['region']}，"
        f"edition={meta['edition']}，version={meta['version']}（上游 {meta['source']}）",
        f"> 生成：{SCRIPT_NAME}，生成时间 {gen_at}",
        f"> 声明：{DECLARATION}。",
        f"> 本文件范围：{ch_desc}，共 {n} 个编码。浙江2025 全表 {len(codes)} 个编码分 {len(all_units)} 个文件"
        f"（文件名均以「{FILE_PREFIX}」开头）：{siblings}。",
        "> 读法：一码一行，列为 编码｜项目名称｜计量单位｜版本｜章｜项目特征｜出处。"
        "「Z」开头的是浙江补充编码；项目特征是清单特征描述的槽位模板（各槽以「；」分隔），不是具体做法。",
        f"> 同一 9 位编码在国标2013 中可能是另一个项目，不能混用；两版对照见《{K9_NAME[:-3]}》。",
        "",
        f"# 浙江2025清单编码表（房屋建筑与装饰工程）：{unit['title']}（{range_label(chs)}）",
        "",
    ]
    header = "| " + " | ".join(COLUMNS) + " |"
    sep = "|" + "|".join(["---"] * len(COLUMNS)) + "|"
    for ch in chs:
        lines.append(f"## {ch} {chapters[ch]}（浙江2025，{len(ch_codes[ch])} 个编码）")
        lines.append("")
        lines.append(header)
        lines.append(sep)
        for code in ch_codes[ch]:
            it = codes[code]
            cells = [code, it["name"].strip(), it["unit"].strip(), VERSION_LABEL, ch,
                     "；".join(feature_lines(it["features_text"])), f"{SRC_TAG} codes.{code}"]
            lines.append("| " + " | ".join(esc(c) for c in cells) + " |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def plan_units(chapters: dict, codes: dict, meta: dict, sha256: str, commit: str,
               gen_at: str, max_chars: int) -> list[dict]:
    """先按方案分组；超过 max_chars（这里传入的是拆分阈值 --split-at）的组按章二分再拆
    （保持章完整、两边尽量均衡），直到全部不超限。"""
    units = [{"label": g[0], "title": g[1], "chapters": list(g[2]), "expect": g[3]} for g in GROUPS]
    for _round in range(10):
        for u in units:
            u["name"] = file_name(u["title"], u["chapters"])
        texts = [render(u, units, chapters, codes, meta, sha256, commit, gen_at) for u in units]
        over = [i for i, t in enumerate(texts) if len(t) > max_chars]
        if not over:
            for u, t in zip(units, texts):
                u["text"] = t
            return units
        new_units = []
        for i, u in enumerate(units):
            if i not in over:
                new_units.append(u)
                continue
            if len(u["chapters"]) == 1:
                raise SystemExit(f"单章 {u['chapters'][0]} 已超 {max_chars} 字，无法按章再拆")
            # 二分：找一个切点使两边都尽量均衡（按章粒度）
            chs = u["chapters"]
            best = None
            for cut in range(1, len(chs)):
                a, b = chs[:cut], chs[cut:]
                sa = sum(len(render_chapter_probe(ch, chapters, codes)) for ch in a)
                sb = sum(len(render_chapter_probe(ch, chapters, codes)) for ch in b)
                score = max(sa, sb)
                if best is None or score < best[0]:
                    best = (score, a, b)
            _, a, b = best
            for k, part in enumerate((a, b)):
                new_units.append({
                    "label": f"{u['label']}{'ab'[k]}" if len(u['label']) == 2 else f"{u['label']}{k + 1}",
                    "title": SPLIT_TITLES.get(tuple(part)) or (
                        "、".join(CHAPTER_SHORT[c] for c in part) if len(part) <= 3
                        else "、".join(CHAPTER_SHORT[c] for c in part[:2]) + "等"),
                    "chapters": part, "expect": None,
                })
        units = new_units
    raise SystemExit("拆分未收敛")


def render_chapter_probe(ch: str, chapters: dict, codes: dict) -> str:
    rows = []
    for code in sorted((c for c in codes if chapter_of(c) == ch), key=sort_key):
        it = codes[code]
        rows.append("| " + " | ".join(esc(c) for c in [
            code, it["name"], it["unit"], VERSION_LABEL, ch,
            "；".join(feature_lines(it["features_text"])), f"{SRC_TAG} codes.{code}"]) + " |")
    return "\n".join(rows)


# ---------------------------------------------------------------- 回读比对（独立解析）

_SPLIT = re.compile(r"(?<!\\)\|")


def parse_md(text: str) -> dict:
    """独立解析一个输出文件：返回 {rows, headings, header_lines, errors}。"""
    errors: list[str] = []
    rows: list[dict] = []
    headings: list[tuple[int, str]] = []
    first_heading = None
    cur_ch = None
    for i, line in enumerate(text.split("\n"), start=1):
        if line.strip().startswith("#"):
            headings.append((i, line))
            if first_heading is None:
                first_heading = i
            m = re.match(r"^## (\d{4}) ", line)
            cur_ch = m.group(1) if m else cur_ch
            continue
        if not line.startswith("|"):
            if "|" in line and not line.startswith(">"):
                errors.append(f"第{i}行：表格外出现 |")
            continue
        parts = _SPLIT.split(line)
        if parts[0] != "" or parts[-1] != "":
            errors.append(f"第{i}行：表格行首尾不是 |")
            continue
        cells = [p.strip() for p in parts[1:-1]]
        if len(cells) != len(COLUMNS):
            errors.append(f"第{i}行：列数 {len(cells)} ≠ {len(COLUMNS)}（疑似未转义的 |）")
            continue
        if cells == COLUMNS or all(re.fullmatch(r"-{3,}", c) for c in cells):
            continue
        cells = [c.replace("\\|", "|") for c in cells]
        code = cells[0]
        if not CODE_RE.match(code):
            errors.append(f"第{i}行：编码格式不对 {code!r}")
            continue
        rows.append({"line": i, "code": code, "name": cells[1], "unit": cells[2],
                     "version": cells[3], "chapter": cells[4], "features": cells[5],
                     "source": cells[6], "heading_ch": cur_ch})
    return {"rows": rows, "headings": headings, "first_heading": first_heading, "errors": errors}


def check_filename(name: str) -> list[str]:
    errs = []
    if len(name) > MAX_NAME_CHARS:
        errs.append(f"文件名 {len(name)} 字 > {MAX_NAME_CHARS}")
    if len(name.encode("utf-8")) > MAX_NAME_BYTES:
        errs.append(f"文件名 {len(name.encode('utf-8'))} 字节 > {MAX_NAME_BYTES}")
    bad = sorted(set(name) & FORBIDDEN_NAME_CHARS)
    if bad:
        errs.append(f"文件名含禁用字符 {bad}")
    if name != name.strip():
        errs.append("文件名首尾有空格")
    if re.match(r"^\d{6,}", name):
        errs.append("文件名以长数字开头")
    return errs


def verify(out_dir: Path, names: list[str], raw: bytes, commit: str, sha256: str,
           max_chars: int, expect_counts: dict[str, int] | None) -> dict:
    chapters, codes, _meta = load_codes(raw)
    report = {"ok": True, "files": [], "errors": []}
    seen: dict[str, str] = {}
    for name in names:
        p = out_dir / name
        b = p.read_bytes()
        ferr: list[str] = []
        if b.startswith(b"\xef\xbb\xbf"):
            ferr.append("有 BOM")
        if b"\r" in b:
            ferr.append("含 CR（不是纯 LF）")
        text = b.decode("utf-8")  # 解不开直接抛异常
        if unicodedata.normalize("NFC", text) != text:
            ferr.append("文本不是 NFC")
        ferr += check_filename(name)
        parsed = parse_md(text)
        ferr += parsed["errors"]
        n_lines = text.count("\n") + (0 if text.endswith("\n") else 1)
        if len(text) > max_chars:
            ferr.append(f"{len(text)} 字 > {max_chars}")
        if n_lines > MAX_LINES:
            ferr.append(f"{n_lines} 行 > {MAX_LINES}")
        if len(parsed["headings"]) > MAX_HEADINGS:
            ferr.append(f"标题 {len(parsed['headings'])} > {MAX_HEADINGS}")
        money = [m.group(0) for m in MONEY_RE.finditer(text)]
        if money:
            ferr.append(f"金额正则命中 {money[:5]}")
        # 文件头：引用块位于第一个标题之前，含 commit、sha256、生成脚本、声明
        head = text.split("\n")[: (parsed["first_heading"] or 1) - 1]
        head_txt = "\n".join(head)
        if not head or not head[0].startswith(">"):
            ferr.append("文件头引用块不在第一个标题之前")
        for need in (commit, sha256, SCRIPT_NAME, DECLARATION, "生成时间"):
            if need not in head_txt:
                ferr.append(f"文件头缺「{need}」")
        chs_in_file = []
        for r in parsed["rows"]:
            code = r["code"]
            if code in seen:
                ferr.append(f"编码 {code} 重复（另见 {seen[code]}）")
            seen[code] = name
            src = codes.get(code)
            if src is None:
                ferr.append(f"第{r['line']}行：{code} 不在 yaml 中")
                continue
            if r["name"] != src["name"]:
                ferr.append(f"第{r['line']}行 {code} 名称差异：{r['name']!r} ≠ {src['name']!r}")
            if r["unit"] != src["unit"]:
                ferr.append(f"第{r['line']}行 {code} 单位差异：{r['unit']!r} ≠ {src['unit']!r}")
            if r["features"].split("；") != feature_lines(src["features_text"]):
                ferr.append(f"第{r['line']}行 {code} 特征差异")
            if r["version"] != VERSION_LABEL:
                ferr.append(f"第{r['line']}行 {code} 版本列 {r['version']!r}")
            if not (r["chapter"] == chapter_of(code) == r["heading_ch"]):
                ferr.append(f"第{r['line']}行 {code} 章列/所在标题与编码不符")
            if r["source"] != f"{SRC_TAG} codes.{code}":
                ferr.append(f"第{r['line']}行 {code} 出处列 {r['source']!r}")
            if r["chapter"] not in chs_in_file:
                chs_in_file.append(r["chapter"])
        if expect_counts and name in expect_counts and expect_counts[name] != len(parsed["rows"]):
            ferr.append(f"码数 {len(parsed['rows'])} ≠ 方案 {expect_counts[name]}")
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        report["files"].append({
            "name": name, "path": str(p), "bytes": len(b), "chars": len(text), "cjk_chars": cjk,
            "lines": n_lines, "data_rows": len(parsed["rows"]), "headings": len(parsed["headings"]),
            "chapters": chs_in_file, "sha256": hashlib.sha256(b).hexdigest(),
            "name_chars": len(name), "name_bytes": len(name.encode("utf-8")), "errors": ferr,
        })
        if ferr:
            report["ok"] = False
    missing = sorted(set(codes) - set(seen), key=sort_key)
    extra = sorted(set(seen) - set(codes), key=sort_key)
    report["code_total_in_md"] = len(seen)
    report["code_total_in_yaml"] = len(codes)
    report["missing"] = missing
    report["extra"] = extra
    if len(seen) != EXPECTED_TOTAL or len(codes) != EXPECTED_TOTAL or missing or extra:
        report["ok"] = False
        report["errors"].append(f"编码集合不符：md {len(seen)} / yaml {len(codes)} / 期望 {EXPECTED_TOTAL}；"
                                f"缺 {missing[:10]} 多 {extra[:10]}")
    # 抽检：从回读结果随机取 20 行，按出处回源定位（固定种子，可复现）
    import random
    rnd = random.Random(20251001)
    all_rows = []
    for f in report["files"]:
        txt = (out_dir / f["name"]).read_text(encoding="utf-8")
        all_rows += [(f["name"], r) for r in parse_md(txt)["rows"]]
    sample = rnd.sample(all_rows, min(20, len(all_rows)))
    spot = []
    for fname, r in sample:
        key = r["source"].split("codes.", 1)[-1]
        src = codes.get(key)
        hit = bool(src) and src["name"] == r["name"] and src["unit"] == r["unit"]
        spot.append({"file": fname, "line": r["line"], "code": r["code"], "source": r["source"],
                     "located": hit})
        if not hit:
            report["ok"] = False
    report["spot_check_20"] = spot
    return report


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--commit", default=DEFAULT_COMMIT)
    ap.add_argument("--src", default=None, help="仅离线兜底：本地 yaml 路径（默认 git show）")
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--stats", default=str(HERE / "local_only" / "zj2025_stats.json"))
    ap.add_argument("--generated-at", default=None)
    ap.add_argument("--max-chars", type=int, default=16000,
                    help="硬门槛：与引擎 DOC_MAX_CHARS 一致，回读校验时任何文件超过即失败")
    ap.add_argument("--split-at", type=int, default=16000,
                    help="拆分阈值：超过即按章再拆；默认与方案 §1.2 和硬门槛一致（16000）")
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args()

    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw, how = read_source(a.repo, a.commit, a.src)
    sha256 = hashlib.sha256(raw).hexdigest()
    chapters, codes, meta = load_codes(raw)
    gen_at = a.generated_at or _dt.datetime.now().astimezone().isoformat(timespec="seconds")

    if a.split_at > a.max_chars:
        print("--split-at 不能大于 --max-chars", file=sys.stderr)
        return 2
    units = plan_units(chapters, codes, meta, sha256, a.commit, gen_at, a.split_at)
    names = [u["name"] for u in units]
    expect = {u["name"]: u["expect"] for u in units if u["expect"] is not None}

    if not a.verify_only:
        # 只清理本生成器自己的旧产物（同前缀），不碰其他任务放在 out/ 的文件
        for old in out_dir.glob(f"{FILE_PREFIX}*.md"):
            if old.name not in names:
                old.unlink()
        for u in units:
            (out_dir / u["name"]).write_bytes(u["text"].encode("utf-8"))

    raw2, _ = read_source(a.repo, a.commit, a.src)  # 回读比对用重新取的源
    if hashlib.sha256(raw2).hexdigest() != sha256:
        print("源两次读取 sha256 不一致", file=sys.stderr)
        return 1
    rep = verify(out_dir, names, raw2, a.commit, sha256, a.max_chars, expect)
    rep.update({"source": how, "source_sha256": sha256, "commit": a.commit,
                "generated_at": gen_at, "max_chars": a.max_chars, "split_at": a.split_at,
                "units": [{"label": u["label"], "name": u["name"], "chapters": u["chapters"],
                           "expect": u["expect"]} for u in units]})
    Path(a.stats).parent.mkdir(parents=True, exist_ok=True)
    Path(a.stats).write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    for f in rep["files"]:
        print(f"{'OK ' if not f['errors'] else 'BAD'} {f['name']}  码 {f['data_rows']}  字 {f['chars']}"
              f"（汉字 {f['cjk_chars']}）  行 {f['lines']}  标题 {f['headings']}  {f['bytes']}B")
        for e in f["errors"][:20]:
            print("    ", e)
    print(f"编码：md {rep['code_total_in_md']} / yaml {rep['code_total_in_yaml']}；缺 {len(rep['missing'])} 多 {len(rep['extra'])}")
    print(f"抽检 20 行定位成功 {sum(s['located'] for s in rep['spot_check_20'])}/20")
    for e in rep["errors"]:
        print("ERR", e)
    print("RESULT", "PASS" if rep["ok"] else "FAIL")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
