#!/usr/bin/env python3
"""KB-GEN-2013：生成知识库 K8、K9（方案 §1.2）。

K8 =《GB50854-2013 工程量计算规范全文》：源文件逐字照录，只做两类改动 ——
     1) 在第一个标题之前加引用块文件头（版本警示、合并单元格说明、勘误与处理表、来源、声明）；
     2) 改动 ERRATA 表所列的行（且只改这些行），每一处都登记在文件头的勘误与处理表里。
K9 =《国标2013与浙江2025清单同码异名对照表》：
     一、同 9 位编码（国标2013 编码 == 浙江2025 非 Z 编码）；
     二、浙江2025 Z 码去掉 Z 后与国标2013 编码撞号。
     计数全部由脚本从两个源重新计算；每行双出处：`GB50854-2013.md 第N行；zj2025.yaml codes.X`。
     国标2013 一侧的名称 / 单位取自「源文件按 ERRATA 改正后」的行（与 K8 正文同一份；勘误不增删行，行号仍是源行号）——
     源文件表 L.2 / L.8 有两组名称上下对调（用户 2026-10-01 裁定按通行版本改正），K9 的同名 / 异名按改正后判定。

受控源：
  · 国标2013：两种形态都认，产物逐字节相同 ——
      原件   算量层研发/building-cost-estimator/GB50854-2013.md（md5 = SRC_MD5，登记在方案里）；
      入仓副本 sources/GB50854-2013.md = 原件把第 43 行版权页「定价：<数字>元」改成「定价：（略）」，其余逐字相同
             （仓里不留任何金额，铁律 2）。sha256 = REPO_COPY_SHA256。
    给原件时，脚本顺带核对「原件按勘误删去定价」== 入仓副本（证明副本只改了这一行）；两种都不是就退出。
    文件头里写的始终是原件的 md5 / sha256（出处以原件为准）。
  · 浙江2025：zhitong-cost-ai 仓库 engine-service/app/engine/data/gb50854_zj2025.yaml，
    默认 `git show <commit>:<path>` 直接读取（不经本地拷贝），记录源字节 sha256。

输出：UTF-8 无 BOM、LF。写完后从磁盘重读做自检（任一不过 → 退出码 1）：
  K8 与源逐行 diff 只落在文件头与 ERRATA 行；K8 标题 ≤ 200；K9 行数 = 重算计数、
  每个编码在两个源都查得到且名称/单位与源逐字一致、出处行号指回该编码所在行；
  两个文件金额正则零命中；表格行无未转义 `|`、单元格无换行；文件名长度/字节/禁用字符合规。

用法（默认值都指向仓内：--src sources/GB50854-2013.md、--repo 仓根、--out out/、--stats local_only/）：
  python3 gen_2013.py [--src <GB50854-2013.md 原件或入仓副本>] [--repo <仓根>] [--commit 33601ca8]
                      [--zj-yaml 本地yaml(仅离线兜底)] [--out DIR] [--stats JSON]
                      [--generated-at 2026-10-01T01:25:35+08:00]
  python3 gen_2013.py --verify-only [--generated-at 与生成时相同]   # 只对已有输出重做自检
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from kbsrc import SNAPSHOT_REPO, git_show_bytes

HERE = Path(__file__).resolve().parent
SCRIPT_NAME = "gen_2013.py"

DEFAULT_SRC = str(HERE / "sources" / "GB50854-2013.md")
SRC_DISPLAY = "算量层研发/building-cost-estimator/GB50854-2013.md"
SRC_TAG = "GB50854-2013.md"
SRC_MD5 = "26504c410ebb4c458f53d8db3377103e"          # 原件（方案登记）
SRC_SHA256 = "6803ace116d14c5cab04a0b25245ceb964822345c1eda620bb187fdc3fa84ab4"   # 原件
REPO_COPY_SHA256 = "2b8bdc7f1afcc96b3aeb2956df74bc8092081b3d128c59ebbcb69007253a3cff"  # 入仓副本（只改第 43 行）
PRICE_LINE = 43
PRICE_REDACTED = "定价：（略）"

DEFAULT_REPO = str(SNAPSHOT_REPO)   # 源快照根（见 kbsrc.py）
DEFAULT_COMMIT = "33601ca8"
ZJ_PATH = "engine-service/app/engine/data/gb50854_zj2025.yaml"
ZJ_TAG = "zj2025.yaml"

K8_NAME = "【清单·房屋建筑】GB50854-2013工程量计算规范全文（国标2013·编码与浙江2025不通用）.md"
K9_NAME = "【清单·房屋建筑】国标2013与浙江2025清单同码异名对照表.md"
K8_TITLE = "【清单·房屋建筑】GB50854-2013工程量计算规范全文（国标2013·编码与浙江2025不通用）"
K9_TITLE = "【清单·房屋建筑】国标2013与浙江2025清单同码异名对照表"

DECLARATION = "本文件由脚本从受控源确定性生成，不含任何金额；引用编码必须注明版本（浙江2025 / 国标2013）"
MONEY_RE = re.compile(r"\d+(\.\d+)?\s*(元|万元)")
FORBIDDEN_NAME_CHARS = set('|/\\<>:"?*;,')
MAX_HEADINGS = 200
MAX_NAME_CHARS = 60
MAX_NAME_BYTES = 255 - 19

K9_COLUMNS = ["编码", "国标2013名称", "国标2013单位", "浙江2025编码", "浙江2025名称", "浙江2025单位", "是否同名", "出处"]
UNIT_EMPTY = "（原表空）"

# 勘误与处理表：只允许改这些行。match 为对源行的精确断言（正则全匹配或子串唯一出现），
# 不在代码里写死被删去的数字。note 进文件头。
ERRATA = [
    {
        "line": 43,
        "kind": "删去金额",
        "match_re": r"定价：\d+(\.\d+)?元",          # 源行必须整行等于「定价：<数字>元」
        "new_line": "定价：（略）",
        "note": "版权页：删去图书定价数字（图书售价，与工程造价无关），改为「定价：（略）」，以保证本知识库不含任何金额",
    },
    {
        "line": 1472,
        "kind": "OCR错字",
        "old_sub": "4. 拒缝材料种类",                  # 源行中必须恰好出现一次
        "new_sub": "4. 嵌缝材料种类",
        "note": "表 J.2 屋面刚性层「项目特征」：OCR 错字「拒缝材料种类」改为「嵌缝材料种类」",
    },
    {
        "line": 1473,
        "kind": "OCR错字",
        "old_sub": "雨水算子安装",
        "new_sub": "雨水箅子安装",
        "note": "表 J.2 屋面排水管「工作内容」：OCR 错字「雨水算子安装」改为「雨水箅子安装」",
    },
    # 名称对调（用户 2026-10-01 裁定）：源文件表 L.2 / 表 L.8 各有两行名称上下写反，按 GB50854-2013 通行版本
    # 把两行名称互换回正确编码（011102003 块料楼地面、011108003 块料零星项目）；另两行用源文件里的「拼碎石材…」写法，
    # 不自造新名称。old_sub 必须恰好是该行「项目名称」单元格（apply_errata 断言）。
    # note 的第一对「」必须是「旧名」改为「新名」—— check_kb.py G3 按它回放改动。
    {
        "line": 1612,
        "kind": "名称对调",
        "old_sub": "块料楼地面",
        "new_sub": "拼碎石材楼地面",
        "note": "表 L.2 编码 011102002：名称「块料楼地面」改为「拼碎石材楼地面」（源文件与下一行 011102003 的名称上下对调；"
                + "据通行版本改正（用户 2026-10-01 裁定），待对照原书核实）",
    },
    {
        "line": 1613,
        "kind": "名称对调",
        "old_sub": "拼碎石材楼地面",
        "new_sub": "块料楼地面",
        "note": "表 L.2 编码 011102003：名称「拼碎石材楼地面」改为「块料楼地面」（源文件与上一行 011102002 的名称上下对调；"
                + "据通行版本改正（用户 2026-10-01 裁定），待对照原书核实）",
    },
    {
        "line": 1715,
        "kind": "名称对调",
        "old_sub": "块料零星项目",
        "new_sub": "拼碎石材零星项目",
        "note": "表 L.8 编码 011108002：名称「块料零星项目」改为「拼碎石材零星项目」（源文件与下一行 011108003 的名称上下对调；"
                + "据通行版本改正（用户 2026-10-01 裁定），待对照原书核实）",
    },
    {
        "line": 1716,
        "kind": "名称对调",
        "old_sub": "拼碎石材零星项目",
        "new_sub": "块料零星项目",
        "note": "表 L.8 编码 011108003：名称「拼碎石材零星项目」改为「块料零星项目」（源文件与上一行 011108002 的名称上下对调；"
                + "据通行版本改正（用户 2026-10-01 裁定），待对照原书核实）",
    },
]

CODE_ROW_RE = re.compile(r"^\|\s*(\d{9})\s*\|")


# ----------------------------------------------------------------------------- 工具
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def esc_cell(s: str) -> str:
    """单元格：去首尾空白，换行并成空格，`|` 转义。"""
    s = (s or "").replace("\r", " ").replace("\n", " ").strip()
    return s.replace("|", "\\|")


def norm_name(s: str) -> str:
    """同名判定口径：去全部空白，全角/半角括号统一。"""
    s = re.sub(r"\s+", "", s or "")
    return s.replace("（", "(").replace("）", ")")


def split_row(line: str) -> list[str]:
    """按未转义的 `|` 切 markdown 表格行，返回去首尾空白的单元格（含转义还原）。"""
    body = line.strip()
    assert body.startswith("|") and body.endswith("|"), line
    body = body[1:-1]
    cells, cur, i = [], [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body) and body[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if ch == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    cells.append("".join(cur).strip())
    return cells


def redact_price(lines: list[str]) -> list[str]:
    """原件 → 入仓副本：只把第 PRICE_LINE 行「定价：<数字>元」改成「定价：（略）」。"""
    out = list(lines)
    if not re.fullmatch(r"定价：\d+(\.\d+)?元", out[PRICE_LINE - 1]):
        sys.exit(f"[FATAL] 原件第 {PRICE_LINE} 行不是「定价：<数字>元」形状")
    out[PRICE_LINE - 1] = PRICE_REDACTED
    return out


def load_src(path: str) -> tuple[bytes, list[str], str]:
    """返回 (源字节, 行, 形态)。形态 = original（原件）/ repo_copy（入仓副本）。"""
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        sys.exit("[FATAL] 源文件含 BOM 或 CR，与预期不符")
    text = raw.decode("utf-8")
    if not text.endswith("\n"):
        sys.exit("[FATAL] 源文件不以 LF 结尾，与预期不符")
    lines = text[:-1].split("\n")   # 去掉末尾换行后按行切；行号 = 下标 + 1
    if md5_bytes(raw) == SRC_MD5:
        copy = ("\n".join(redact_price(lines)) + "\n").encode("utf-8")
        if sha256_bytes(copy) != REPO_COPY_SHA256:
            sys.exit("[FATAL] 原件删去定价后与入仓副本 sha256 不一致：入仓副本不是「只改第 43 行」")
        return raw, lines, "original"
    if sha256_bytes(raw) == REPO_COPY_SHA256:
        if lines[PRICE_LINE - 1] != PRICE_REDACTED:
            sys.exit(f"[FATAL] 入仓副本第 {PRICE_LINE} 行不是「{PRICE_REDACTED}」")
        return raw, lines, "repo_copy"
    sys.exit(f"[FATAL] 源文件既不是原件（md5 {SRC_MD5}）也不是入仓副本（sha256 {REPO_COPY_SHA256}）：{path}")


def load_zj(repo: str, commit: str, local: str | None) -> tuple[bytes, dict, str]:
    if local:
        raw = Path(local).read_bytes()
        where = f"{local}（离线兜底，本地文件）"
    else:
        raw = git_show_bytes(repo, commit, ZJ_PATH)
        where = f"git show {commit}:{ZJ_PATH}"
    doc = yaml.safe_load(raw.decode("utf-8")) or {}
    codes = {str(k): v for k, v in (doc.get("codes") or {}).items()}
    return raw, codes, where


def parse_2013_rows(lines: list[str]) -> dict[str, dict]:
    """国标2013 附录表的编码行：{code: {line, name, unit}}；同码重复即报错。"""
    out: dict[str, dict] = {}
    for i, l in enumerate(lines, 1):
        m = CODE_ROW_RE.match(l)
        if not m:
            continue
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cells) != 6:
            sys.exit(f"[FATAL] 源第 {i} 行列数 {len(cells)} ≠ 6")
        code = m.group(1)
        if code in out:
            sys.exit(f"[FATAL] 源里编码 {code} 重复（第 {out[code]['line']}、{i} 行）")
        out[code] = {"line": i, "name": cells[1], "unit": cells[3]}
    return out


# ----------------------------------------------------------------------------- K8
def apply_errata(src_lines: list[str], mode: str = "original") -> list[str]:
    body = list(src_lines)
    for e in ERRATA:
        idx = e["line"] - 1
        old = body[idx]
        if "match_re" in e:
            if mode == "repo_copy" and e["line"] == PRICE_LINE and old == e["new_line"]:
                continue   # 入仓副本已预先删去定价（与勘误结果逐字相同）
            if not re.fullmatch(e["match_re"], old):
                sys.exit(f"[FATAL] 勘误断言失败：源第 {e['line']} 行不是预期形状")
            body[idx] = e["new_line"]
        else:
            if old.count(e["old_sub"]) != 1:
                sys.exit(f"[FATAL] 勘误断言失败：源第 {e['line']} 行「{e['old_sub']}」出现 {old.count(e['old_sub'])} 次")
            if e["kind"] == "名称对调":
                cells = [c.strip() for c in old.strip().strip("|").split("|")]
                if len(cells) != 6 or not CODE_ROW_RE.match(old) or cells[1] != e["old_sub"]:
                    sys.exit(f"[FATAL] 勘误断言失败：源第 {e['line']} 行的「项目名称」单元格不是「{e['old_sub']}」")
            body[idx] = old.replace(e["old_sub"], e["new_sub"])
    # 名称对调必须成对：A 行旧名 = B 行新名、A 行新名 = B 行旧名，且 A、B 是上下相邻两行
    swaps = {e["line"]: e for e in ERRATA if e["kind"] == "名称对调"}
    for ln, e in swaps.items():
        mate = [m for m in swaps.values() if abs(m["line"] - ln) == 1
                and m["old_sub"] == e["new_sub"] and m["new_sub"] == e["old_sub"]]
        if len(mate) != 1:
            sys.exit(f"[FATAL] 勘误断言失败：源第 {ln} 行「名称对调」找不到相邻的对调另一行")
    return body


def k8_header(h: int, src_sha: str, zj_sha: str, commit: str, gen_at: str) -> list[str]:
    """h = 文件头行数（含其后空行），先用占位值算行数，再用真值重排；两次行数必须相同。"""
    errata_lines = [
        f"> - 源文件第 {e['line']} 行（本文件第 {e['line'] + h} 行）【{e['kind']}】{e['note']}。"
        for e in ERRATA
    ]
    hdr = [
        "> 文件说明：本文件是 GB 50854-2013《房屋建筑与装饰工程工程量计算规范》全文（国标2013版）。正文逐字照录源文件，只改动下方「勘误与处理表」所列的行。",
        "> 版本警示：本文件中的项目编码全部是国标2013版，与浙江2025版清单编码不通用——同一个 9 位编码在两版中可能是不同的项目；浙江2025 的 Z 字头补充编码去掉 Z 后，也可能与本文件的编码撞号。报编码默认按浙江2025；本文件只作计算规则、工作内容和条文说明的参考，引用本文件的编码必须写明「国标2013」。",
        f"> 两版对照：同码异名、Z 码撞号请查本库《{K9_TITLE}》；浙江2025 编码、名称、单位请查本库《【清单·房屋建筑】浙江2025清单编码表-…》系列文件。",
        "> 表格说明：附录 A～S 各表里的「同上」「（同上）」以及空白的计量单位、特征、计算规则、工作内容单元格，来自原书表格的竖向合并单元格（抽取成 Markdown 时拆成了多行），须结合上下相邻行理解，不表示该项没有相应内容。",
        f"> 勘误与处理表（共 {len(ERRATA)} 处；行号指源文件行号，本文件行号 = 源文件行号 + {h}）：",
        *errata_lines,
        f"> 来源：{SRC_DISPLAY}（md5 {SRC_MD5}；sha256 {src_sha}）；两版对照所用码表为 zhitong-cost-ai 仓库 `{ZJ_PATH}`（commit {commit}；sha256 {zj_sha}）。",
        f"> 生成：{SCRIPT_NAME}，生成时间 {gen_at}",
        f"> 声明：{DECLARATION}。",
        "",
    ]
    return hdr


def build_k8(src_lines, src_sha, zj_sha, commit, gen_at, mode="original") -> tuple[str, int]:
    probe = k8_header(0, src_sha, zj_sha, commit, gen_at)
    h = len(probe)
    hdr = k8_header(h, src_sha, zj_sha, commit, gen_at)
    assert len(hdr) == h
    body = apply_errata(src_lines, mode)
    return "\n".join(hdr + body) + "\n", h


# ----------------------------------------------------------------------------- K9
def compute_pairs(g2013: dict, zj: dict) -> dict:
    same, zcol = [], []
    for code, r in g2013.items():
        if code in zj:
            same.append((code, code))
        if "Z" + code in zj:
            zcol.append((code, "Z" + code))
    same.sort(key=lambda p: g2013[p[0]]["line"])
    zcol.sort(key=lambda p: g2013[p[0]]["line"])
    # 交叉核对：从浙江2025 一侧反算，结果必须一致
    same_b = sorted(k for k in zj if not k.startswith("Z") and k in g2013)
    zcol_b = sorted(k for k in zj if k.startswith("Z") and k[1:] in g2013)
    assert sorted(p[1] for p in same) == same_b
    assert sorted(p[1] for p in zcol) == zcol_b

    def stats(pairs):
        diff = [p for p in pairs if norm_name(g2013[p[0]]["name"]) != norm_name(zj[p[1]]["name"])]
        raw_diff = [p for p in pairs if g2013[p[0]]["name"] != zj[p[1]]["name"]]
        fmt_only = [p for p in raw_diff if p not in diff]
        return {"count": len(pairs), "diff_name": len(diff), "raw_diff_name": len(raw_diff),
                "format_only_diff": [f"{a}/{b}" for a, b in fmt_only]}

    return {"same": same, "zcol": zcol, "same_stats": stats(same), "zcol_stats": stats(zcol)}


def k9_row(c13: str, czj: str, g2013: dict, zj: dict) -> str:
    r = g2013[c13]
    z = zj[czj]
    unit13 = r["unit"] if r["unit"] else UNIT_EMPTY
    same = "同名" if norm_name(r["name"]) == norm_name(z["name"]) else "异名"
    src = f"{SRC_TAG} 第{r['line']}行；{ZJ_TAG} codes.{czj}"
    cells = [c13, r["name"], unit13, czj, z.get("name", ""), z.get("unit", ""), same, src]
    return "| " + " | ".join(esc_cell(str(c)) for c in cells) + " |"


def build_k9(pairs, g2013, zj, k8_h, src_sha, zj_sha, commit, gen_at) -> str:
    ss, zs = pairs["same_stats"], pairs["zcol_stats"]
    fmt_n = len(ss["format_only_diff"]) + len(zs["format_only_diff"])
    hdr = [
        f"> 文件说明：本表列出 GB 50854-2013（国标2013）与浙江2025版房屋建筑与装饰工程清单中编码数字相同的全部项目，用来识别同码异名，避免把一个版本的编码当成另一个版本引用。",
        "> 版本规则：报编码默认按浙江2025；国标2013 只作计算规则和工作内容的参考。两版名称不同时，必须按所用版本取名称和单位，并在引用时写明版本。",
        "> 读法：每行从左到右依次是 编码（国标2013）｜国标2013名称｜国标2013单位｜浙江2025编码｜浙江2025名称｜浙江2025单位｜是否同名｜出处；出处里的 GB50854-2013.md 指国标2013、zj2025.yaml 指浙江2025。",
        f"> 统计（由生成脚本从两个源重新计算）：第一节 同 9 位编码 {ss['count']} 个，其中名称不同 {ss['diff_name']} 个；第二节 浙江2025 的 Z 字头编码去掉 Z 后与国标2013 编码撞号 {zs['count']} 个，其中名称不同 {zs['diff_name']} 个。",
        f"> 判定口径：「是否同名」按去掉空白、全角/半角括号统一后比较；另有 {fmt_n} 个仅括号全半角或空格写法不同，判为同名。第二节即使同名，Z 码与不带 Z 的编码也不是同一个编码，引用时必须保留 Z。",
        f"> 单位说明：国标2013单位逐字照录源文件；「（同上）」和「{UNIT_EMPTY}」来自原表竖向合并单元格，须查国标2013全文对应行的上下文确定。",
        f"> 出处说明：「{SRC_TAG} 第N行」是源文件行号，本库《{K8_TITLE}》中对应行号为 N+{k8_h}；「{ZJ_TAG} codes.X」是浙江2025 码表中的编码键。",
        f"> 勘误说明：国标2013名称、单位取自《{K8_TITLE}》按其文件头「勘误与处理表」改正后的正文（表 L.2、表 L.8 各有两行名称在源文件中上下对调，"
        "已据通行版本改正，待对照原书核实），是否同名按改正后的名称判定；出处行号仍是源文件行号（勘误不增删行）。",
        f"> 来源：国标2013 取自 {SRC_DISPLAY}（md5 {SRC_MD5}；sha256 {src_sha}）附录 A～S 表格；浙江2025 取自 zhitong-cost-ai 仓库 `{ZJ_PATH}`（commit {commit}；sha256 {zj_sha}）。",
        f"> 生成：{SCRIPT_NAME}，生成时间 {gen_at}",
        f"> 声明：{DECLARATION}。",
        "",
        "# 国标2013与浙江2025清单同码异名对照表",
        "",
    ]
    th = "| " + " | ".join(K9_COLUMNS) + " |"
    sep = "|" + "---|" * len(K9_COLUMNS)
    out = list(hdr)
    out += [f"## 一、同 9 位编码（{ss['count']} 个，其中名称不同 {ss['diff_name']} 个）", "",
            "两版编码数字完全相同。「异名」表示两版是不同的项目，引用时必须写明版本。", "", th, sep]
    out += [k9_row(a, b, g2013, zj) for a, b in pairs["same"]]
    out += ["", f"## 二、浙江2025 Z 码去掉 Z 后与国标2013 编码撞号（{zs['count']} 个，其中名称不同 {zs['diff_name']} 个）", "",
            "浙江2025 编码带 Z 字头（浙江补充编码），去掉 Z 后与左侧国标2013 编码数字相同，但不是同一个编码。", "", th, sep]
    out += [k9_row(a, b, g2013, zj) for a, b in pairs["zcol"]]
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------- 自检
def check_filename(name: str) -> list[str]:
    errs = []
    stem = name
    if len(stem) > MAX_NAME_CHARS:
        errs.append(f"文件名 {len(stem)} 字 > {MAX_NAME_CHARS}")
    if len(stem.encode("utf-8")) > MAX_NAME_BYTES:
        errs.append(f"文件名 {len(stem.encode('utf-8'))} 字节 > {MAX_NAME_BYTES}")
    bad = sorted(set(stem) & FORBIDDEN_NAME_CHARS)
    if bad:
        errs.append(f"文件名含禁用字符 {bad}")
    if stem != stem.strip():
        errs.append("文件名首尾有空格")
    if re.match(r"^\d{6,}", stem):
        errs.append("文件名以长数字开头")
    return errs


def check_common(path: Path) -> tuple[list[str], dict]:
    errs = []
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        errs.append("含 BOM")
    if b"\r" in raw:
        errs.append("含 CR")
    text = raw.decode("utf-8")
    lines = text[:-1].split("\n") if text.endswith("\n") else text.split("\n")
    heads = [l for l in lines if re.match(r"^#{1,6}\s", l)]
    if len(heads) > MAX_HEADINGS:
        errs.append(f"标题 {len(heads)} 个 > {MAX_HEADINGS}")
    money = [(i, m.group(0)) for i, l in enumerate(lines, 1) for m in [MONEY_RE.search(l)] if m]
    if money:
        errs.append(f"金额正则命中 {len(money)} 处：行 {[i for i, _ in money][:10]}")
    errs += check_filename(path.name)
    st = {
        "name": path.name, "bytes": len(raw), "sha256": sha256_bytes(raw),
        "chars": len(text), "chars_nonspace": len(re.sub(r"\s", "", text)),
        "lines": len(lines), "headings": len(heads), "money_hits": len(money),
        "name_chars": len(path.name), "name_bytes": len(path.name.encode("utf-8")),
    }
    return errs, st, lines


def verify_k8(path: Path, src_lines: list[str], h: int, mode: str = "original") -> tuple[list[str], dict]:
    errs, st, lines = check_common(path)
    # 入仓副本已预先删去定价：该行与 K8 相同，不出现在 diff 里，改为单独核对两边都是「定价：（略）」
    pre_applied = {PRICE_LINE} if mode == "repo_copy" else set()
    hdr, body = lines[:h], lines[h:]
    if not all(l.startswith("> ") for l in hdr[:-1]) or hdr[-1] != "":
        errs.append("文件头不是「引用块 + 空行」形状")
    if any(re.match(r"^#", l) for l in hdr):
        errs.append("文件头含标题行")
    if len(body) != len(src_lines):
        errs.append(f"正文行数 {len(body)} ≠ 源 {len(src_lines)}")
    diff_lines = [i + 1 for i, (a, b) in enumerate(zip(body, src_lines)) if a != b]
    allowed = sorted(e["line"] for e in ERRATA if e["line"] not in pre_applied)
    if diff_lines != allowed:
        errs.append(f"与源 diff 行 {diff_lines} ≠ 勘误表所列 {allowed}")
    for ln in pre_applied:
        if not (src_lines[ln - 1] == body[ln - 1] == PRICE_REDACTED):
            errs.append(f"源第 {ln} 行（入仓副本预先删去定价）与 K8 不是同为「{PRICE_REDACTED}」")
    # 每处勘误都在文件头登记，且登记的本文件行号正确
    for e in ERRATA:
        tag = f"源文件第 {e['line']} 行（本文件第 {e['line'] + h} 行）"
        if not any(tag in l for l in hdr):
            errs.append(f"文件头未登记勘误：{tag}")
    for typo in ("拒缝", "雨水算子"):
        if typo in "\n".join(body):
            errs.append(f"正文仍含「{typo}」")
    if body and body[0] != src_lines[0]:
        errs.append("第一个标题不是源第 1 行")
    diff_detail = []
    for ln in diff_lines:
        old = MONEY_RE.sub("<金额已隐去>", src_lines[ln - 1])
        diff_detail.append({"src_line": ln, "k8_line": ln + h, "old": old[:160], "new": body[ln - 1][:160]})
    st.update({"header_lines": h, "diff_src_lines": diff_lines, "diff_detail": diff_detail,
               "src_mode": mode, "pre_applied_lines": sorted(pre_applied)})
    return errs, st


def verify_k9(path: Path, g2013: dict, zj: dict, fixed_lines: list[str], pairs: dict) -> tuple[list[str], dict]:
    """fixed_lines = 源文件按 ERRATA 改正后的行（行号与源文件相同）；g2013 也从它解析（K9 用勘误后的名称）。"""
    errs, st, lines = check_common(path)
    sections, cur = {"一": [], "二": []}, None
    for i, l in enumerate(lines, 1):
        if l.startswith("## 一、"):
            cur = "一"
        elif l.startswith("## 二、"):
            cur = "二"
        if not l.startswith("|"):
            continue
        cells = split_row(l)
        if len(cells) != len(K9_COLUMNS):
            errs.append(f"第 {i} 行列数 {len(cells)} ≠ {len(K9_COLUMNS)}（疑似未转义 |）")
            continue
        if cells == K9_COLUMNS or set(l.replace("|", "").strip()) <= {"-"}:
            continue
        if cur is None:
            errs.append(f"第 {i} 行表格不在任何一节下")
            continue
        sections[cur].append((i, cells))
    exp = {"一": pairs["same"], "二": pairs["zcol"]}
    for sec, rows in sections.items():
        if len(rows) != len(exp[sec]):
            errs.append(f"第{sec}节行数 {len(rows)} ≠ 重算 {len(exp[sec])}")
        got_pairs = [(c[0], c[3]) for _, c in rows]
        if got_pairs != list(exp[sec]):
            errs.append(f"第{sec}节编码对与重算不一致")
        for i, c in rows:
            c13, n13, u13, czj, nzj, uzj, same, src = c
            r = g2013.get(c13)
            z = zj.get(czj)
            if r is None:
                errs.append(f"第 {i} 行国标2013 编码 {c13} 在源中查不到"); continue
            if z is None:
                errs.append(f"第 {i} 行浙江2025 编码 {czj} 在 yaml 中查不到"); continue
            if sec == "一" and czj != c13:
                errs.append(f"第 {i} 行第一节两码不同")
            if sec == "二" and czj != "Z" + c13:
                errs.append(f"第 {i} 行第二节不是 Z+编码")
            if n13 != r["name"]:
                errs.append(f"第 {i} 行国标2013名称与源不一致")
            if u13 != (r["unit"] or UNIT_EMPTY):
                errs.append(f"第 {i} 行国标2013单位与源不一致")
            if nzj != z.get("name") or uzj != z.get("unit"):
                errs.append(f"第 {i} 行浙江2025名称/单位与 yaml 不一致")
            want_same = "同名" if norm_name(n13) == norm_name(nzj) else "异名"
            if same != want_same:
                errs.append(f"第 {i} 行是否同名判定错")
            m = re.fullmatch(rf"{re.escape(SRC_TAG)} 第(\d+)行；{re.escape(ZJ_TAG)} codes\.(Z?\d{{9}})", src)
            if not m:
                errs.append(f"第 {i} 行出处格式不对：{src}"); continue
            ln, key = int(m.group(1)), m.group(2)
            if key != czj:
                errs.append(f"第 {i} 行出处 yaml 键 {key} ≠ {czj}")
            if not (1 <= ln <= len(fixed_lines)) or not CODE_ROW_RE.match(fixed_lines[ln - 1]) \
                    or CODE_ROW_RE.match(fixed_lines[ln - 1]).group(1) != c13:
                errs.append(f"第 {i} 行出处行号 {ln} 不指向源中 {c13} 所在行")
    n_diff = {s: sum(1 for _, c in rows if c[6] == "异名") for s, rows in sections.items()}
    st.update({
        "section1_rows": len(sections["一"]), "section1_diff_name": n_diff["一"],
        "section2_rows": len(sections["二"]), "section2_diff_name": n_diff["二"],
        "unit13_empty_rows": sum(1 for rows in sections.values() for _, c in rows if c[2] == UNIT_EMPTY),
        "unit13_tongshang_rows": sum(1 for rows in sections.values() for _, c in rows if "同上" in c[2]),
    })
    return errs, st


# ----------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--commit", default=DEFAULT_COMMIT)
    ap.add_argument("--zj-yaml", default=None, help="仅离线兜底：本地 yaml 路径（默认 git show）")
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--stats", default=str(HERE / "local_only" / "gen_2013_stats.json"))
    ap.add_argument("--generated-at", default=None)
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args()

    src_raw, src_lines, src_mode = load_src(a.src)
    src_sha = SRC_SHA256   # 文件头与出处一律写原件的 sha256（入仓副本由 load_src 核对过只改第 43 行）
    zj_raw, zj, zj_where = load_zj(a.repo, a.commit, a.zj_yaml)
    zj_sha = sha256_bytes(zj_raw)
    # K9 的国标2013 名称 / 单位取自勘误后的正文（与 K8 正文同一份），出处行号仍是源文件行号（勘误不增删行）
    fixed_lines = apply_errata(src_lines, src_mode)
    g2013 = parse_2013_rows(fixed_lines)
    pairs = compute_pairs(g2013, zj)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    k8p, k9p = out / K8_NAME, out / K9_NAME

    if a.verify_only:
        if not a.generated_at:
            first = k8p.read_text(encoding="utf-8").split("\n")
            m = next((re.search(r"生成时间 (\S+)", l) for l in first if "生成时间" in l), None)
            gen_at = m.group(1) if m else "?"
        else:
            gen_at = a.generated_at
    else:
        gen_at = a.generated_at or _dt.datetime.now().astimezone().isoformat(timespec="seconds")

    k8_text, h = build_k8(src_lines, src_sha, zj_sha, a.commit, gen_at, src_mode)
    k9_text = build_k9(pairs, g2013, zj, h, src_sha, zj_sha, a.commit, gen_at)
    if a.verify_only:
        for p, t in ((k8p, k8_text), (k9p, k9_text)):
            if p.read_text(encoding="utf-8") != t:
                print(f"[FAIL] {p.name} 与按同一生成时间重新生成的内容不一致（非确定性或被改动）")
                return 1
    else:
        k8p.write_bytes(k8_text.encode("utf-8"))
        k9p.write_bytes(k9_text.encode("utf-8"))

    e8, s8 = verify_k8(k8p, src_lines, h, src_mode)
    e9, s9 = verify_k9(k9p, g2013, zj, fixed_lines, pairs)
    stats = {
        "task": "KB-GEN-2013", "script": SCRIPT_NAME, "generated_at": gen_at,
        "source_2013": {"path": a.src, "mode": src_mode, "file_md5": md5_bytes(src_raw),
                        "file_sha256": sha256_bytes(src_raw), "original_md5": SRC_MD5, "original_sha256": SRC_SHA256,
                        "lines": len(src_lines), "code_rows": len(g2013)},
        "source_zj2025": {"where": zj_where, "commit": a.commit, "sha256": zj_sha, "codes": len(zj)},
        "k9_counts": {"same9": pairs["same_stats"], "zcollide": pairs["zcol_stats"]},
        "K8": s8, "K9": s9, "errors": {"K8": e8, "K9": e9},
    }
    Path(a.stats).parent.mkdir(parents=True, exist_ok=True)
    Path(a.stats).write_text(json.dumps(stats, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ok = not e8 and not e9
    for tag, s, e in (("K8", s8, e8), ("K9", s9, e9)):
        print(f"[{tag}] {s['name']}")
        print(f"      bytes={s['bytes']} chars={s['chars']} lines={s['lines']} headings={s['headings']} "
              f"money_hits={s['money_hits']} name={s['name_chars']}字/{s['name_bytes']}B sha256={s['sha256']}")
        for x in e:
            print(f"      [ERR] {x}")
    print(f"[K8] header_lines={s8['header_lines']} diff_src_lines={s8['diff_src_lines']}")
    print(f"[K9] 同码={s9['section1_rows']}（异名 {s9['section1_diff_name']}） 撞号={s9['section2_rows']}"
          f"（异名 {s9['section2_diff_name']}） 单位原表空={s9['unit13_empty_rows']} 单位同上={s9['unit13_tongshang_rows']}")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
