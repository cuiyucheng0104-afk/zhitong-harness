#!/usr/bin/env python3
"""KB-GATE 独立校验器（方案 §1.3 七条门槛）。

独立性：不 import 任何生成器（gen_*.py），不复用生成器的解析/比对代码；所有比对都从受控源重新读取、
重新解析：
  · 浙江2025 码表、quantity_rules：git show 33601ca8:<path>（每次运行现取，不用本地副本；--repo 默认仓根）
  · 国标2013：默认 sources/GB50854-2013.md（入仓副本：原件只把第 43 行版权页定价改成「定价：（略）」）；
    也可 --gb2013 给原件（md5 26504c41…）。两种都认，登记与比对一律按原件的 md5 / sha256；
    给原件时顺带核对「原件删去定价」== 入仓副本
  · SKILL.md 映射表、clause_llm.py 的 `_MAPPING_REF`：不在仓里。默认读 sources/k7_sources_snapshot.json 里的逐行摘录
    （映射表第 105–155 行原文：表头、分隔行和 49 个数据行，另存表后第 156 行空行作表尾边界；_MAPPING_REF 各行；
    连同原文件 sha256）；在有原文件的机器上用 --skill / --clause
    改读原文件（clause_llm.py 只抽取 `_MAPPING_REF` 这一个变量所在行；不读同包其他文件，尤其 app/config/*.key）
  · 执行方案 kb_plan.md 含生产环境信息，不入仓：给 --plan 时核对方案表里有 K0 行；不给时核对 K0 文件头登记的方案 sha256
成品一律从 out/ 目录按字节读回、严格 UTF-8 解码后解析。

七条门槛：
  G1 回读零差异（K1–K5 ↔ zj2025.yaml 逐字段）
  G2 编码全可查（K0、K6、K7、K9 每个编码在对应版本源里可查；编码后「」内/结构化列里的名称、单位与源一致；
     国标2013 一侧的「源」= 源文件 + 已通过 G3 核验的勘误（仍按源行号定位），所以 main 里 G3 先跑）
  G3 K8 只改了该改的（与源逐行比对，差异只在文件头和勘误表所列行，且改动内容与勘误表描述一致；
     勘误表必须与本文件登记的已裁定勘误 APPROVED_ERRATA 逐条相同；「名称对调」只能改名称列、且上下相邻两行成对）
  G4 不含金额（\\d+(\\.\\d+)?\\s*(元|万元) 零命中，含文件名）
  G5 格式合规（标题 ≤200、表格列数一致无未转义 |、单元格不跨行、文件名 ≤60 字 ≤236 字节无禁用字符、UTF-8 无 BOM/CR；
     K0–K7 单文件 ≤16000 字且模拟引擎 DOC 一次读完；文件头齐全；
     全文与文件名不含本机 / 服务器路径、不含 16 位以上的长数字 id —— 成品要上传到租户知识库，chatbot 会读到）
  G6 行级出处（每个数据行「出处」非空且全部可回源，国标2013 行按「源 + 已核勘误」定位；另按固定种子抽检 20 行，打印定位证据）
  G7 登记清单（生成 manifest.json 后回读核对：sha256/字数/行数齐全且与磁盘一致，与 K0 所列一致，out/ 无多余文件；
     目标类目按「编号 → 类目名」与「文件名前缀 → 类目名」两路独立推出、必须一致；
     类目 id 不入仓 —— 各租户、各环境的 knowledge_category id 都是运行时生成的雪花 id，
     上传前用 --categories 指向本地配置（local_only/，已 gitignore）才写进本地 manifest，并核对其形态）

用法（默认 --out out/，manifest / 报告写到 local_only/）：
  python3 check_kb.py [--out DIR] [--manifest JSON] [--report MD] [--json JSON]
                      [--repo <仓根>] [--gb2013 PATH] [--skill SKILL.md --clause clause_llm.py] [--plan kb_plan.md]
                      [--categories local_only/categories.json]
  --categories 的格式：{"清单": "<目标租户「清单」类目 id>", "清单/房屋建筑": "<「清单/房屋建筑」类目 id>"}；
  不给时 manifest 里 categoryId 记 null（仓内复现、干净环境 --check 都不需要它）。
退出码：0 = 七条全过；1 = 有不过。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import hashlib
import json
import random
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import yaml

from kbsrc import SNAPSHOT_REPO, git_show_bytes, source_available

HERE = Path(__file__).resolve().parent
REPO = str(SNAPSHOT_REPO)   # 源快照根（见 kbsrc.py）；main() 里按 --repo 覆盖
COMMIT = "33601ca8"
ZJ_PATH = "engine-service/app/engine/data/gb50854_zj2025.yaml"
QR_PATH = "engine-service/app/engine/data/quantity_rules.yaml"
SRC2013_DEFAULT = HERE / "sources" / "GB50854-2013.md"
SRC2013_MD5 = "26504c410ebb4c458f53d8db3377103e"                                     # 原件（方案登记）
SRC2013_SHA256 = "6803ace116d14c5cab04a0b25245ceb964822345c1eda620bb187fdc3fa84ab4"  # 原件
SRC2013_REPO_COPY_SHA256 = "2b8bdc7f1afcc96b3aeb2956df74bc8092081b3d128c59ebbcb69007253a3cff"  # 入仓副本
PRICE_LINE, PRICE_REDACTED = 43, "定价：（略）"
SNAPSHOT_DEFAULT = HERE / "sources" / "k7_sources_snapshot.json"
# K8 勘误：校验器自己登记一份「已裁定的勘误」（源行号 → 类型、旧文字、新文字），G3 要求 K8 文件头所列与它逐条相同 ——
# 不只信 K8 自己的勘误表（否则在 K8 头里多登记一条、同步改正文，就能借 G3 把任意改动「洗」成合规）。
# 1612/1613、1715/1716：表 L.2 / L.8 名称上下对调，用户 2026-10-01 裁定按 GB50854-2013 通行版本改正（待对照原书核实）。
APPROVED_ERRATA = {
    43: ("删去金额", None, None),
    1472: ("OCR错字", "拒缝材料种类", "嵌缝材料种类"),
    1473: ("OCR错字", "雨水算子安装", "雨水箅子安装"),
    1612: ("名称对调", "块料楼地面", "拼碎石材楼地面"),
    1613: ("名称对调", "拼碎石材楼地面", "块料楼地面"),
    1715: ("名称对调", "块料零星项目", "拼碎石材零星项目"),
    1716: ("名称对调", "拼碎石材零星项目", "块料零星项目"),
}
PLAN_SHA256 = "74cce567be8866095b179280f5aef09c2e7935224cc4e21666f8bd8c51bc9a13"   # 生成 K0 时 kb_plan.md 的 sha256

# 上传目标类目：仓里只记类目名（方案 §1.2：K0 进「清单」根类目，K1–K9 进「清单/房屋建筑」）。
# 类目 id 不写死（铁律 1 口径）：knowledge_category 的 id 是运行时生成的雪花 id，换租户、换环境都不同 ——
# 上传前用 --categories 给本地配置（PR #788 评审）。
CAT_ROOT_NAME, CAT_HOUSE_NAME = "清单", "清单/房屋建筑"
# 文件名前缀 → 类目名：与「编号 → 类目名」是两路独立来源，G7 要求两路一致
CAT_BY_PREFIX = {"【清单】": CAT_ROOT_NAME, "【清单·房屋建筑】": CAT_HOUSE_NAME}
CATEGORY_ID = re.compile(r"[1-9]\d{0,18}")   # 正整数、不超过 19 位（BIGINT 雪花 id 的形态）
DECL = "本文件由脚本从受控源确定性生成，不含任何金额；引用编码必须注明版本（浙江2025 / 国标2013）"
MONEY = re.compile(r"\d+(\.\d+)?\s*(元|万元)")
# 成品会进租户知识库、被 chatbot 的 GREP / DOC 读到：不许带开发机 / 服务器路径（PR #788 评审：K7 文件头曾写本机路径），
# 也不许带运行时生成的长数字 id（雪花 id 19 位；清单编码最长 12 位、sha256 / md5 是十六进制串，都不会命中）
LOCAL_PATH = re.compile(r"~/|/Users/|/home/|/private/|/tmp/|/opt/|/var/|/mnt/|[A-Za-z]:\\|Desktop|nas-data|scratchpad")
LONG_ID = re.compile(r"(?<![0-9A-Za-z])\d{16,}(?![0-9A-Za-z])")
FORBID_CHARS = set('|/\\<>:"?*;,')
DOC_MAX_CHARS, DOC_MAX_BLOCKS = 16000, 300          # engine-service/app/filetree/tools.py @33601ca8
OUTLINE_MAX = 200
CODE_TOKEN = re.compile(r"(?<![0-9A-Za-z_])(Z?\d{9}(?:\d{3})?)(?![0-9A-Za-z_])")
LONG_DIGITS = re.compile(r"(?<![0-9A-Za-z_])Z?\d{9,}(?![0-9A-Za-z_])")
K0_NAME = "【清单】清单编码类资料版本与使用说明.md"
ZJ_PREFIX = "【清单·房屋建筑】浙江2025清单编码表-"
KEYS = {"K6": "浙江2025清单易混淆编码与列项校核规则", "K7": "设计做法对应浙江2025清单编码参考表",
        "K8": "GB50854-2013工程量计算规范全文", "K9": "国标2013与浙江2025清单同码异名对照表"}
PLAN_GROUPS = [("K1", {"0101", "0102", "0103", "0104"}), ("K2", {"0105", "0106", "0107"}),
               ("K3", {"0108", "0109", "0110"}), ("K4", {"0111", "0112", "0113", "0114", "0115"}),
               ("K5", {"0116", "0118"})]


# ============================================================ 通用小工具（本文件自写）
def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def git_show(path: str) -> bytes:
    return git_show_bytes(REPO, COMMIT, path)


def cells_of(line: str) -> list[str]:
    """按未转义的 | 切表格行；返回去掉首尾空串后的单元格（已 strip、已把 \\| 还原成 |）。"""
    parts = re.split(r"(?<!\\)\|", line.rstrip("\n"))
    if len(parts) < 3 or parts[0].strip() or parts[-1].strip():
        return []
    return [p.strip().replace("\\|", "|") for p in parts[1:-1]]


def is_sep(line: str) -> bool:
    return bool(re.fullmatch(r"\|(\s*:?-{3,}:?\s*\|)+", line.strip()))


def tables(lines: list[str]) -> list[dict]:
    """连续以 | 开头的行为一张表：{start(1基), header, rows:[(lineno, cells, raw)], heading}"""
    out, i, heading = [], 0, None
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#"):
            heading = ln
        if ln.startswith("|"):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            blk = lines[i:j]
            t = {"start": i + 1, "end": j, "heading": heading, "header": cells_of(blk[0]),
                 "sep_ok": len(blk) > 1 and is_sep(blk[1]), "rows": [],
                 "next_line": lines[j] if j < len(lines) else None, "raw_widths": []}
            for k, raw in enumerate(blk[2:], start=i + 3):
                t["rows"].append((k, cells_of(raw), raw))
            t["raw_widths"] = [len(re.split(r"(?<!\\)\|", r)) - 2 for r in blk]
            out.append(t)
            i = j
            continue
        i += 1
    return out


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", "", s)


def strip_z(c: str) -> str:
    return c[1:] if c.startswith("Z") else c


def chapter_of(c: str) -> str:
    return strip_z(c)[:4]


def header_block(lines: list[str]) -> tuple[list[str], int]:
    """文件头 = 开头连续的 > 行；返回(头行, 第一个非头行下标)。"""
    k = 0
    while k < len(lines) and lines[k].startswith(">"):
        k += 1
    return lines[:k], k


def index_2013_rows(lines: list[str]) -> dict[str, list[dict]]:
    """国标2013 附录表编码行：{code: [{line, name, unit, raw}]}（行号 1 基）。"""
    rows: dict[str, list[dict]] = {}
    for i, ln in enumerate(lines, 1):
        m = re.match(r"^\| (\d{9}) \|", ln)
        if m:
            c = cells_of(ln)
            if len(c) == 6:
                rows.setdefault(m.group(1), []).append({"line": i, "name": c[1], "unit": c[3], "raw": ln})
    return rows


# ============================================================ 受控源（全部现取）
class Sources:
    def __init__(self, gb_path: Path, skill_path: Path | None, clause_path: Path | None, snapshot: Path,
                 plan_path: Path | None):
        self.zj_raw = git_show(ZJ_PATH)
        self.zj_sha = sha256(self.zj_raw)
        zj = yaml.safe_load(self.zj_raw)
        self.zj = {str(k): v for k, v in zj["codes"].items()}
        self.zj_ch = {str(k): v for k, v in zj["chapters"].items()}
        self.qr_raw = git_show(QR_PATH)
        self.qr_sha = sha256(self.qr_raw)
        self.qr = yaml.safe_load(self.qr_raw)
        self.qr_lines = self.qr_raw.decode("utf-8").split("\n")
        b = gb_path.read_bytes()
        self.gb_path = gb_path
        self.md_file_md5 = hashlib.md5(b).hexdigest()
        self.md_file_sha = sha256(b)
        self.md_text = b.decode("utf-8")
        self.md_lines = self.md_text.split("\n")
        # 登记与比对一律按原件：原件直接核 md5；入仓副本核 sha256，且第 43 行必须是「定价：（略）」
        if self.md_file_md5 == SRC2013_MD5:
            self.md_mode = "original"
            red = list(self.md_lines)
            if not re.fullmatch(r"定价：\d+(\.\d+)?元", red[PRICE_LINE - 1]):
                raise SystemExit(f"国标2013 原件第 {PRICE_LINE} 行不是「定价：<数字>元」")
            red[PRICE_LINE - 1] = PRICE_REDACTED
            self.copy_chain_ok = sha256("\n".join(red).encode("utf-8")) == SRC2013_REPO_COPY_SHA256
        elif self.md_file_sha == SRC2013_REPO_COPY_SHA256:
            self.md_mode = "repo_copy"
            self.copy_chain_ok = self.md_lines[PRICE_LINE - 1] == PRICE_REDACTED
        else:
            self.md_mode, self.copy_chain_ok = "unknown", False
        known = self.md_mode != "unknown" and self.copy_chain_ok
        self.md_md5 = SRC2013_MD5 if known else self.md_file_md5
        self.md_sha = SRC2013_SHA256 if known else self.md_file_sha
        # 源文件原样的行索引（K0「源文件写作…」这类陈述按它核）
        self.md_raw_rows = index_2013_rows(self.md_lines)
        # 改正后的行：源文件 + 已通过 G3 核验的勘误（main 先跑 G3 再调 apply_fixes）。G2 / G6 拿 K9、K0、K7 的
        # 国标2013 名称回源比对、按「GB50854-2013.md 第N行」定位时一律用它（勘误不增删行，行号仍是源行号）。
        # G3 之前（或 K8 缺失 / 勘误全不过）它就是源文件原样 —— 此时 K9 的改正后名称会被判与源不一致，不会放过。
        self.md_fixed_lines = list(self.md_lines)
        self.md_rows = index_2013_rows(self.md_fixed_lines)
        self.md_fixes_applied: list[int] = []
        if skill_path and clause_path:
            self.k7_src_mode = "source"
            self.skill_path, self.clause_path = str(skill_path), str(clause_path)
            sk = skill_path.read_bytes()
            self.skill_sha = sha256(sk)
            self.skill_lines = sk.decode("utf-8").split("\n")
            # clause_llm.py：只抽 _MAPPING_REF 变量所在的行
            t = clause_path.read_text(encoding="utf-8")
            m = re.search(r'^_MAPPING_REF\s*=\s*"""\\?\n(.*?)^"""', t, re.M | re.S)
            if not m:
                raise SystemExit("clause_llm.py 里找不到 _MAPPING_REF")
            first = t[:m.start(1)].count("\n") + 1
            self.clause_ref = {first + k: s for k, s in enumerate(m.group(1).split("\n")) if s}
            self.clause_var_lines = (t[:m.start()].count("\n") + 1, t[:m.end()].count("\n") + 1)
            del t
        elif skill_path or clause_path:
            raise SystemExit("--skill 与 --clause 要么都给，要么都不给（读快照）")
        else:
            # 快照：映射表原文按行号放回（表外各行留空串；第 105–155 行是表，第 156 行是表后空行）
            self.k7_src_mode = "snapshot"
            snap = json.loads(snapshot.read_text(encoding="utf-8"))
            sk, cl = snap["skill"], snap["clause"]
            if "table_lines" not in sk:
                raise SystemExit("快照缺 skill.table_lines（映射表原文行），无法按行号回源")
            self.skill_path, self.clause_path = f"{sk['label']}（快照 {snapshot.name}）", f"{cl['label']}（快照 {snapshot.name}）"
            self.skill_sha = sk["sha256"]
            last = max(x["line"] for x in sk["table_lines"])
            self.skill_lines = [""] * (last + 1)
            for x in sk["table_lines"]:
                self.skill_lines[x["line"] - 1] = x["text"]
            self.clause_ref = {x["line"]: x["text"] for x in cl["lines"] if x["text"]}
            self.clause_var_lines = (cl["decl_line"], cl["end_line"])
        self.plan_text = plan_path.read_text(encoding="utf-8") if plan_path else None

    def apply_fixes(self, fixes: list[dict]) -> None:
        """fixes = G3 核验通过的勘误 [{src_line, text}]：text 是「源行按勘误描述替换后」的整行（= K8 对应行）。"""
        self.md_fixed_lines = list(self.md_lines)
        for fx in fixes:
            self.md_fixed_lines[fx["src_line"] - 1] = fx["text"]
        self.md_rows = index_2013_rows(self.md_fixed_lines)
        self.md_fixes_applied = sorted(fx["src_line"] for fx in fixes)

    @property
    def zj_units(self):
        return {str(v["unit"]).strip() for v in self.zj.values()}

    def all_names(self, ver):
        if ver == "zj":
            return {norm_name(v["name"]) for v in self.zj.values()}
        return {norm_name(r["name"]) for rs in self.md_rows.values() for r in rs}

    def zj_name(self, c):
        return self.zj[c]["name"].strip() if c in self.zj else None

    def zj_unit(self, c):
        return self.zj[c]["unit"].strip() if c in self.zj else None


# ============================================================ 成品读取
class Doc:
    def __init__(self, path: Path):
        self.path = path
        self.name = path.name
        self.raw = path.read_bytes()
        self.decode_err = None
        try:
            self.text = self.raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as e:
            self.decode_err = str(e)
            self.text = self.raw.decode("utf-8", errors="replace")
        self.lines = self.text.split("\n")
        if self.lines and self.lines[-1] == "":
            self.lines = self.lines[:-1]
        self.tables = tables(self.lines)
        self.head, self.body_at = header_block(self.lines)
        self.label = None


def classify(names: list[str]) -> dict[str, str]:
    lab = {}
    zj = [n for n in names if n.startswith(ZJ_PREFIX)]
    for g, chs in PLAN_GROUPS:
        fs = sorted([n for n in zj if chapters_in_name(n)[0] in chs], key=lambda n: chapters_in_name(n)[0])
        for i, n in enumerate(fs):
            lab[n] = g if len(fs) == 1 else f"{g}{'ab'[i]}"
    for k, key in KEYS.items():
        for n in names:
            if key in n:
                lab[n] = k
    if K0_NAME in names:
        lab[K0_NAME] = "K0"
    return lab


def chapters_in_name(name: str) -> list[str]:
    m = re.search(r"（([0-9、\-]+)）\.md$", name)
    spec = m.group(1)
    if "-" in spec:
        a, b = spec.split("-")
        return [f"{i:04d}" for i in range(int(a), int(b) + 1)]
    return spec.split("、")


# ============================================================ G1
def gate1(docs: dict[str, Doc], S: Sources) -> dict:
    errs, seen, dup, per_file = [], {}, [], []
    cols = ["编码", "项目名称", "计量单位", "版本", "章", "项目特征", "出处"]
    strict_name_diff = 0
    for d in docs.values():
        if not d.label or not re.fullmatch(r"K[1-5][ab]?", d.label):
            continue
        want_chs = chapters_in_name(d.name)
        got_chs, n = [], 0
        for t in d.tables:
            if t["header"] != cols:
                errs.append(f"{d.label} 第{t['start']}行 表头不是方案列：{t['header']}")
                continue
            hm = re.match(r"^## (\d{4}) (.+)（浙江2025，(\d+) 个编码）$", t["heading"] or "")
            if not hm:
                errs.append(f"{d.label} 第{t['start']}行 表格不在「## 章码 章名（浙江2025，N 个编码）」标题下")
                continue
            ch = hm.group(1)
            got_chs.append(ch)
            if hm.group(2) != S.zj_ch.get(ch):
                errs.append(f"{d.label} 章 {ch} 标题章名与 yaml 不一致")
            if int(hm.group(3)) != len(t["rows"]):
                errs.append(f"{d.label} 章 {ch} 标题写 {hm.group(3)} 个编码，实有 {len(t['rows'])} 行")
            for ln, c, raw in t["rows"]:
                n += 1
                if len(c) != 7:
                    errs.append(f"{d.label} 第{ln}行 列数 {len(c)}≠7")
                    continue
                code, name, unit, ver, chc, feat, src = c
                if code in seen:
                    dup.append(code)
                seen[code] = (d.label, ln)
                if code not in S.zj:
                    errs.append(f"{d.label} 第{ln}行 编码 {code} 不在 yaml")
                    continue
                y = S.zj[code]
                if name != y["name"]:
                    strict_name_diff += 1
                if norm_name(name) != norm_name(y["name"]):
                    errs.append(f"{d.label} 第{ln}行 {code} 名称差异")
                if unit != str(y["unit"]).strip():
                    errs.append(f"{d.label} 第{ln}行 {code} 单位差异")
                want_feat = "；".join(s.strip() for s in str(y.get("features_text") or "").splitlines() if s.strip())
                if feat != want_feat:
                    errs.append(f"{d.label} 第{ln}行 {code} 特征差异")
                if ver != "浙江2025":
                    errs.append(f"{d.label} 第{ln}行 版本列={ver}")
                if chc != chapter_of(code) or chc != ch:
                    errs.append(f"{d.label} 第{ln}行 章列={chc}，编码章={chapter_of(code)}，所在标题章={ch}")
                if src != f"zj2025.yaml codes.{code}":
                    errs.append(f"{d.label} 第{ln}行 出处={src}")
        if got_chs != want_chs:
            errs.append(f"{d.label} 章节 {got_chs} 与文件名章码 {want_chs} 不一致")
        hm2 = re.search(r"共 (\d+) 个编码", "\n".join(d.head))
        if not hm2 or int(hm2.group(1)) != n:
            errs.append(f"{d.label} 文件头编码数与表格行数 {n} 不一致")
        per_file.append({"label": d.label, "chapters": got_chs, "rows": n})
    md_set, y_set = set(seen), set(S.zj)
    missing, extra = sorted(y_set - md_set), sorted(md_set - y_set)
    if len(y_set) != 490:
        errs.append(f"yaml 编码数 {len(y_set)}≠490")
    if missing or extra or dup:
        errs.append(f"编码集合：缺 {len(missing)} 多 {len(extra)} 重复 {len(dup)}")
    return {"ok": not errs, "errors": errs, "md_codes": len(md_set), "yaml_codes": len(y_set),
            "missing": missing, "extra": extra, "duplicates": dup, "files": per_file,
            "strict_name_diff": strict_name_diff,
            "evidence": f"K1–K5 共 {len(per_file)} 份解析回 {len(md_set)} 码 / yaml {len(y_set)} 码；缺 {len(missing)} 多 {len(extra)} "
                        f"重复 {len(dup)}；名称（逐字）差异 {strict_name_diff}、单位/特征/版本/章/出处差异 "
                        f"{sum(1 for e in errs if '差异' in e or '列=' in e or '出处=' in e)}"}


# ============================================================ G2
FUNC_WORDS = tuple("只或列取为是按等的用不同与和及在则即中另见两这各共该此，。；、）)")


def scan_codes(text: str):
    for m in CODE_TOKEN.finditer(text):
        yield m


def gate2(docs: dict[str, Doc], S: Sources) -> dict:
    errs, notes, checked, named, freetext = [], [], 0, 0, []
    units_checked = []
    exempt = []
    total_by_file = {}

    def ver_ok(code: str, ver: str) -> bool:
        base = code[:10] if code.startswith("Z") else code[:9]
        if ver == "zj":
            return base in S.zj
        return base in S.md_rows

    def name_of(code, ver):
        base = code[:10] if code.startswith("Z") else code[:9]
        if ver == "zj":
            return S.zj_name(base)
        r = S.md_rows.get(base)
        return r[0]["name"] if r else None

    def check_text(label: str, where: str, text: str, ver: str, allow_missing: set = frozenset()):
        nonlocal checked, named
        for lm in LONG_DIGITS.finditer(text):
            if not CODE_TOKEN.fullmatch(lm.group(0)):
                errs.append(f"{label} {where} 出现非 9/12 位的长数字串 {lm.group(0)}")
        for m in scan_codes(text):
            code = m.group(1)
            checked += 1
            total_by_file[label] = total_by_file.get(label, 0) + 1
            if code in allow_missing:
                continue
            if not ver_ok(code, ver):
                errs.append(f"{label} {where} 编码 {code} 在{'浙江2025' if ver == 'zj' else '国标2013'}源里查不到")
                continue
            tail = text[m.end():]
            q = re.match(r"「([^」]+)」(（([^）]+)）)?", tail)
            if q:
                named += 1
                want = name_of(code, ver)
                if norm_name(q.group(1)) != norm_name(want):
                    errs.append(f"{label} {where} {code}「{q.group(1)}」≠ 源名称「{want}」")
                # 「」后的括注只有在它本身是码表里出现过的计量单位时才算单位声明（否则是规则名、行号等旁注）
                if q.group(3) and ver == "zj" and q.group(3) in S.zj_units:
                    units_checked.append(code)
                    if q.group(3) != S.zj_unit(code[:10] if code.startswith('Z') else code[:9]):
                        errs.append(f"{label} {where} {code} 单位（{q.group(3)}）≠ 源单位")
                continue
            if text[max(0, m.start() - 6):m.start()] == "codes.":
                continue  # 「zj2025.yaml codes.X」是出处键，不是行文引用
            f = re.match(r"^[ \u3000]?([\u4e00-\u9fff（）()、·]+)", tail)
            if f and f.group(1):
                w = f.group(1)
                want = name_of(code, ver)
                if norm_name(w).startswith(norm_name(want)):
                    named += 1
                    freetext.append((label, where, code, w, "名称一致"))
                elif w[0] in "（(":
                    inner = re.match(r"[（(]([^）)]*)[）)]", w)
                    inner = inner.group(1) if inner else w[1:]
                    if norm_name(inner) == norm_name(want):
                        named += 1
                        freetext.append((label, where, code, w, "名称一致"))
                    elif norm_name(inner) in S.all_names(ver):
                        freetext.append((label, where, code, w, "待复核"))
                    else:
                        freetext.append((label, where, code, w, "后接括注（不是名称）"))
                elif w[0] in FUNC_WORDS:
                    freetext.append((label, where, code, w, "后接非名称"))
                else:
                    tok = re.split("[" + "".join(FUNC_WORDS) + "]", w)[0]
                    if tok and norm_name(tok) in norm_name(want) and norm_name(tok) not in S.all_names(ver):
                        freetext.append((label, where, code, w, "名称简写（是源名称的一部分）"))
                    else:
                        freetext.append((label, where, code, w, "待复核"))

    # 国标2013 名称一律按「源文件 + 已通过 G3 核验的勘误」核（S.md_rows；main 先跑 G3 再 S.apply_fixes）
    for d in docs.values():
        lab = d.label
        if lab not in ("K0", "K6", "K7", "K9"):
            continue
        if lab == "K6":
            for i, ln in enumerate(d.lines, 1):
                if ln.startswith("|"):
                    for j, c in enumerate(cells_of(ln)):
                        check_text(lab, f"第{i}行第{j + 1}列", c, "zj")
                else:
                    check_text(lab, f"第{i}行", ln, "zj")
        elif lab == "K7":
            for t in d.tables:
                hdr = t["header"]
                for ln, c, raw in t["rows"]:
                    for j, cell in enumerate(c):
                        col = hdr[j] if j < len(hdr) else "?"
                        allow = set()
                        # 「原写 X」语境：X 是被改正掉的原值，按豁免处理并单独核对
                        for om in re.finditer(r"原写 (Z?\d{9})", cell):
                            allow.add(om.group(1))
                            exempt.append((lab, ln, om.group(1)))
                        if col == "原写编码":
                            allow.add(cell)
                            exempt.append((lab, ln, cell))
                        if col == "原写编码在浙江2025的名称":
                            # 核对「国标2013 同号为X，GB50854-2013.md 第N行」这类旁注
                            mm = re.search(r"国标2013 同号为(.+?)，GB50854-2013\.md 第(\d+)行", cell)
                            if mm:
                                oc = c[hdr.index("原写编码")]
                                r = [x for x in S.md_rows.get(oc, []) if x["line"] == int(mm.group(2))]
                                if not r or r[0]["name"] != mm.group(1):
                                    errs.append(f"K7 第{ln}行 国标2013 旁注与源不符")
                                if oc in S.zj:
                                    errs.append(f"K7 第{ln}行 声称浙江2025无 {oc}，实际有")
                            continue
                        check_text(lab, f"第{ln}行「{col}」列", cell, "zj", allow)
                    if hdr and hdr[0] == "描述特征":
                        code, nm, un = c[2], c[3], c[4]
                        if S.zj_name(code) != nm or S.zj_unit(code) != un:
                            errs.append(f"K7 第{ln}行 {code} 名称/单位列与浙江2025不一致")
                        else:
                            named += 1
                    if hdr and hdr[0] == "序号":
                        oc, onm = c[3], c[4]
                        if oc in S.zj and S.zj_name(oc) != onm:
                            errs.append(f"K7 第{ln}行 原写编码 {oc} 的浙江2025名称写错")
                        if oc not in S.zj and "浙江2025码表无此编码" not in onm:
                            errs.append(f"K7 第{ln}行 原写编码 {oc} 浙江2025查不到但未声明")
            for i, ln in enumerate(d.lines, 1):
                if not ln.startswith("|"):
                    check_text(lab, f"第{i}行", ln, "zj")
            # 「原写 X，该码浙江2025名称为「Y」」旁注核对
            for i, ln in enumerate(d.lines, 1):
                for om in re.finditer(r"原写 (Z?\d{9})，(该码浙江2025名称为「([^」]+)」|浙江2025码表无此编码)", ln):
                    oc = om.group(1)
                    if om.group(3) is not None:
                        if S.zj_name(oc) != om.group(3):
                            errs.append(f"K7 第{i}行 原写 {oc} 的浙江2025名称旁注不符")
                    elif oc in S.zj:
                        errs.append(f"K7 第{i}行 原写 {oc} 声称浙江2025无此编码，实际有")
                    elif oc not in S.md_rows:
                        errs.append(f"K7 第{i}行 原写 {oc} 两版都查不到")
        elif lab == "K9":
            for t in d.tables:
                if t["header"] != ["编码", "国标2013名称", "国标2013单位", "浙江2025编码", "浙江2025名称",
                                   "浙江2025单位", "是否同名", "出处"]:
                    errs.append(f"K9 第{t['start']}行 表头不符")
                    continue
                for ln, c, raw in t["rows"]:
                    c13, n13, u13, czj, nzj, uzj, same, src = c
                    checked += 2
                    total_by_file["K9"] = total_by_file.get("K9", 0) + 2
                    m = re.fullmatch(r"GB50854-2013\.md 第(\d+)行；zj2025\.yaml codes\.(Z?\d{9})", src)
                    if not m:
                        errs.append(f"K9 第{ln}行 出处格式不符")
                        continue
                    # S.md_rows = 源文件 + 已通过 G3 核验的勘误（行号仍是源行号）
                    r = [x for x in S.md_rows.get(c13, []) if x["line"] == int(m.group(1))]
                    if not r:
                        errs.append(f"K9 第{ln}行 国标2013 {c13} 不在源第{m.group(1)}行")
                        continue
                    r = r[0]
                    if n13 != r["name"]:
                        errs.append(f"K9 第{ln}行 国标2013 {c13}「{n13}」≠ 源（勘误后）第{r['line']}行「{r['name']}」")
                    want_u = "（原表空）" if r["unit"] == "" else ("（同上）" if r["unit"] == "同上" else r["unit"])
                    if u13 != want_u:
                        errs.append(f"K9 第{ln}行 国标2013 单位≠源（{u13} / {r['unit']}）")
                    if m.group(2) != czj or czj not in S.zj:
                        errs.append(f"K9 第{ln}行 浙江2025 编码/出处不符")
                        continue
                    if nzj != S.zj_name(czj) or uzj != S.zj_unit(czj):
                        errs.append(f"K9 第{ln}行 浙江2025 名称/单位≠源")
                    if strip_z(czj) != c13:
                        errs.append(f"K9 第{ln}行 两列编码去 Z 后不相等")
                    a = re.sub(r"\s+", "", n13).replace("（", "(").replace("）", ")")
                    b = re.sub(r"\s+", "", nzj).replace("（", "(").replace("）", ")")
                    if same != ("同名" if a == b else "异名"):
                        errs.append(f"K9 第{ln}行 是否同名判定与独立口径不一致（{same}）")
                    named += 2
            for i, ln in enumerate(d.lines, 1):
                if not ln.startswith("|"):
                    for m in scan_codes(ln):
                        errs.append(f"K9 第{i}行 表外出现编码 {m.group(1)}（未按版本核对）")
        elif lab == "K0":
            for i, ln in enumerate(d.lines, 1):
                ver = "md" if ln.startswith("- 国标2013：") else "zj"
                if ln.startswith("|"):
                    for j, c in enumerate(cells_of(ln)):
                        check_text(lab, f"第{i}行第{j + 1}列", c, "zj")
                else:
                    check_text(lab, f"第{i}行", ln, ver)
    # K9 完整性：两节行集合 = 从两个源独立重算的集合
    k9 = next((d for d in docs.values() if d.label == "K9"), None)
    comp = {}
    if k9:
        sec = {}
        cur = None
        for ln in k9.lines:
            if ln.startswith("## 一、"):
                cur = 1
            elif ln.startswith("## 二、"):
                cur = 2
            elif ln.startswith("|") and cur and not is_sep(ln):
                c = cells_of(ln)
                if c and c[0] != "编码":
                    sec.setdefault(cur, []).append(c)
        want1 = sorted(c for c in S.md_rows if c in S.zj)
        want2 = sorted(z for z in S.zj if z.startswith("Z") and z[1:] in S.md_rows)
        got1 = sorted(c[0] for c in sec.get(1, []))
        got2 = sorted(c[3] for c in sec.get(2, []))
        comp = {"sec1_rows": len(got1), "sec1_want": len(want1), "sec1_diff": sum(1 for c in sec.get(1, []) if c[6] == "异名"),
                "sec2_rows": len(got2), "sec2_want": len(want2), "sec2_diff": sum(1 for c in sec.get(2, []) if c[6] == "异名")}
        if got1 != want1 or got2 != want2:
            errs.append(f"K9 行集合与独立重算不一致：一节 {len(got1)}/{len(want1)}，二节 {len(got2)}/{len(want2)}")
        hm = re.search(r"第一节 同 9 位编码 (\d+) 个，其中名称不同 (\d+) 个；第二节 .*?撞号 (\d+) 个，其中名称不同 (\d+) 个",
                       "\n".join(k9.head))
        if not hm or tuple(map(int, hm.groups())) != (comp["sec1_rows"], comp["sec1_diff"], comp["sec2_rows"], comp["sec2_diff"]):
            errs.append("K9 文件头统计与表格行不一致")
    # K7 原写 010902003 这类豁免：必须恰好是改正记录里登记的原写编码
    k7 = next((d for d in docs.values() if d.label == "K7"), None)
    ex_codes = sorted({e[2] for e in exempt})
    if k7:
        reg = sorted({c[3] for t in k7.tables if t["header"] and t["header"][0] == "序号" for _, c, _ in t["rows"]})
        if ex_codes != reg:
            errs.append(f"K7 豁免编码 {ex_codes} 与改正记录登记的原写编码 {reg} 不一致")
    pending = [f for f in freetext if f[4] == "待复核"]
    for p in pending:
        errs.append(f"{p[0]} {p[1]} 编码 {p[2]} 后接「{p[3][:12]}」既不是源名称也不像功能词，需复核")
    # K0 疑点与说明中的事实性陈述逐条核对
    k0 = next((d for d in docs.values() if d.label == "K0"), None)
    k0_claims = []
    if k0:
        def claim(ok, what):
            k0_claims.append({"ok": bool(ok), "claim": what})
            if not ok:
                errs.append(f"K0 陈述不成立：{what}")
        T = k0.text
        k8 = next((d for d in docs.values() if d.label == "K8"), None)
        k9d = next((d for d in docs.values() if d.label == "K9"), None)
        k8t = k8.name[:-3] if k8 else "（缺 K8）"
        fixed_in_k8 = f"已在《{k8t}》勘误改正（据通行版本，待对照原书核实）"

        def raw_nm(c):
            return [r["name"] for r in S.md_raw_rows.get(c, [])]

        def fix_nm(c):
            return [r["name"] for r in S.md_rows.get(c, [])]

        swapped = (("011102002", "块料楼地面", "拼碎石材楼地面"), ("011102003", "拼碎石材楼地面", "块料楼地面"),
                   ("011108002", "块料零星项目", "拼碎石材零星项目"), ("011108003", "拼碎石材零星项目", "块料零星项目"))
        claim(all(raw_nm(c) == [a] for c, a, _ in swapped)
              and "表 L.2 的 011102002、011102003 两行和表 L.8 的 011108002、011108003 两行，名称上下对调"
                  "（源文件把块料写在 002、拼碎石材写在 003）" in T,
              "K0：国标2013 源文件表 L.2 / L.8 两组名称上下对调（块料写在 002、拼碎石材写在 003）")
        claim(all(fix_nm(c) == [b] for c, _, b in swapped) and fixed_in_k8 in T
              and "改正后 011102002「拼碎石材楼地面」、011102003「块料楼地面」、011108002「拼碎石材零星项目」、"
                  "011108003「块料零星项目」" in T,
              "K0：这四行已在 K8 勘误改正（G3 核验通过），改正后 002 拼碎石材、003 块料")
        claim(all(S.zj_name(c) == b for c, _, b in swapped) and "与浙江2025 这两组编码的名称一致" in T,
              "K0：改正后的四个名称与浙江2025 同码名称一致")
        k9_rows = {}
        for t_ in (k9d.tables if k9d else []):
            for _, c_, _ in t_["rows"]:
                if len(c_) == 8:
                    k9_rows.setdefault(c_[0], c_)
        claim(all(c in k9_rows and k9_rows[c][1] == b and k9_rows[c][6] == "同名" for c, _, b in swapped)
              and k9d and f"《{k9d.name[:-3]}》已按改正后的名称判定同名、异名" in T,
              "K0：K9 已按改正后的名称判定（这四个编码在 K9 第一节为改正后名称、同名）")
        claim("010902004" in S.md_lines[1472] and "雨水算子安装" in S.md_lines[1472]
              and "雨水箅子安装" in S.md_fixed_lines[1472] and "雨水算子" not in S.md_fixed_lines[1472]
              and "源文件第 1473 行（表 J.2 编码 010902004 的工作内容）写作「雨水算子安装」，是「雨水箅子安装」的识别错字，"
                  + fixed_in_k8 in T,
              "K0：国标2013 源第1473行 010902004 工作内容写作「雨水算子安装」，K8 勘误已改为「雨水箅子安装」")
        claim("螺纹套简种类" in str(S.zj["Z010506031"]["features_text"])
              and "码表 Z010506031 的项目特征写作「螺纹套简种类」" in T and "本库照录码表未改" in T
              and "需在码表源中另行修正" in T, "K0：浙江2025 Z010506031 特征含「螺纹套简种类」，照录未改、需另修码表源")
        m_e8 = re.search(r"勘误与处理表（共 (\d+) 处", "\n".join(k8.head) if k8 else "")
        m_e0 = re.search(r"勘误与处理 (\d+) 处登记在文件头", T)
        claim(m_e8 and m_e0 and int(m_e8.group(1)) == int(m_e0.group(1)) == len(APPROVED_ERRATA),
              "K0 所写 K8 勘误条数 = K8 文件头勘误条数 = 已裁定勘误条数")
        mk = re.search(r"GB50854-2013\.md（md5 ([0-9a-f]{32})）", T)
        claim(mk and mk.group(1) == S.md_md5 and f"sha256 {S.zj_sha}" in T and f"sha256 {S.qr_sha}" in T,
              "K0：文件头与表格中的源 md5 / sha256 与现取源一致")
        mo = re.search(r"对应第 N\+(\d+) 行", k0.text)
        claim(mo and k8 and int(mo.group(1)) == k8.body_at + 1, "K0 所写 K8 行号偏移 = K8 实际文件头行数+空行")
    return {"ok": not errs, "errors": errs, "codes_checked": checked, "by_file": total_by_file,
            "names_checked": named, "units_checked_after_name": len(units_checked),
            "exempt_original_codes": ex_codes, "k9_completeness": comp,
            "freetext": [{"file": f[0], "where": f[1], "code": f[2], "follow": f[3][:16], "class": f[4]} for f in freetext],
            "k0_claims": k0_claims, "gb2013_fixed_lines": S.md_fixes_applied,
            "evidence": f"扫描编码 {checked} 处（{', '.join(f'{k}:{v}' for k, v in sorted(total_by_file.items()))}），"
                        f"全部在对应版本源中查到；名称/单位核对 {named} 处 0 不符；「原写」豁免编码 {ex_codes}（均为改正记录登记的原值，"
                        f"已单独核对旁注）；K9 两节行集合与独立重算一致 {comp}"}


# ============================================================ G3
def gate3(docs: dict[str, Doc], S: Sources) -> dict:
    errs = []
    d = next((x for x in docs.values() if x.label == "K8"), None)
    if not d:
        return {"ok": False, "errors": ["缺 K8"], "evidence": ""}
    if S.md_mode == "unknown":
        errs.append(f"国标2013 源既不是原件（md5 {SRC2013_MD5}）也不是入仓副本（sha256 {SRC2013_REPO_COPY_SHA256}）")
    elif not S.copy_chain_ok:
        errs.append("国标2013：原件删去第 43 行定价后与入仓副本不一致 / 入仓副本第 43 行不是「定价：（略）」")
    # 入仓副本已预先删去定价：该行与 K8 相同，不进 diff；单独核对两边同为「定价：（略）」
    pre_applied = {PRICE_LINE} if S.md_mode == "repo_copy" else set()
    head = d.head
    h = d.body_at
    if h >= len(d.lines) or d.lines[h] != "":
        errs.append("K8 文件头后没有空行")
    body = d.lines[h + 1:]
    src = S.md_lines[:-1] if S.md_lines and S.md_lines[-1] == "" else S.md_lines
    off = h + 1
    if len(body) != len(src):
        errs.append(f"K8 正文行数 {len(body)} ≠ 源 {len(src)}")
    diffs = [i + 1 for i in range(min(len(body), len(src))) if body[i] != src[i]]
    htxt = "\n".join(head)
    mo = re.search(r"本文件行号 = 源文件行号 \+ (\d+)", htxt)
    if not mo or int(mo.group(1)) != off:
        errs.append(f"文件头声明的行号偏移与实际 {off} 不符")
    errata = []
    for ln in head:
        m = re.search(r"源文件第 (\d+) 行（本文件第 (\d+) 行）【([^】]+)】(.*)", ln)
        if m:
            errata.append({"src_line": int(m.group(1)), "k8_line": int(m.group(2)), "kind": m.group(3), "desc": m.group(4)})
    mc = re.search(r"勘误与处理表（共 (\d+) 处", htxt)
    if not mc or int(mc.group(1)) != len(errata):
        errs.append("勘误表条数声明与条目数不一致")
    listed = sorted(e["src_line"] for e in errata)
    expect_diffs = sorted(n for n in listed if n not in pre_applied)
    if diffs != expect_diffs:
        errs.append(f"正文差异行 {diffs} ≠ 勘误表所列行 {expect_diffs}"
                    + (f"（勘误表 {listed}，其中 {sorted(pre_applied)} 已在入仓副本预先改好）" if pre_applied else ""))
    if len(set(listed)) != len(listed):
        errs.append(f"勘误表同一源行登记了多次：{listed}")
    # 勘误表必须与校验器登记的「已裁定勘误」逐条相同（行号、类型、旧文字、新文字）
    def sig(e):
        q_ = re.search(r"「([^」]+)」改为「([^」]+)」", e["desc"])
        ab = (q_.group(1), q_.group(2)) if q_ and e["kind"] != "删去金额" else (None, None)
        return (e["src_line"], e["kind"], *ab)
    got_sig = {sig(e) for e in errata}
    want_sig = {(n, *v) for n, v in APPROVED_ERRATA.items()}
    if got_sig != want_sig:
        errs.append(f"K8 勘误表与已裁定勘误不一致：多 {sorted(got_sig - want_sig, key=str)} 缺 {sorted(want_sig - got_sig, key=str)}")
    swaps = {}
    detail, fixes = [], []
    for e in errata:
        n = e["src_line"]
        if not (1 <= n <= len(src)) or n > len(body):
            errs.append(f"勘误 源第{n}行超出正文范围")
            continue
        s_, k_ = src[n - 1], body[n - 1]
        if e["k8_line"] != n + off:
            errs.append(f"勘误 源{n} 的本文件行号写 {e['k8_line']}，应为 {n + off}")
        if not (1 <= e["k8_line"] <= len(d.lines)) or d.lines[e["k8_line"] - 1] != k_:
            errs.append(f"勘误 源{n} 本文件行号定位不到改后行")
        # 描述里第一处「旧」改为「新」（OCR错字、名称对调都按它回放）
        q = re.search(r"「([^」]+)」改为「([^」]+)」", e["desc"])
        ok = False
        how = ""
        if e["kind"] in ("OCR错字", "名称对调") and q:
            a, b = q.group(1), q.group(2)
            ok = s_.count(a) == 1 and k_ == s_.replace(a, b)
            how = f"源行含「{a}」1 处，改成「{b}」后与 K8 行逐字相同" if ok else "改动与描述不符"
            if ok and e["kind"] == "名称对调":
                sc, kc = cells_of(s_), cells_of(k_)
                if len(sc) != 6 or len(kc) != 6 or sc[1] != a or kc[1] != b or sc[0] != kc[0]:
                    ok, how = False, f"「{a}」不是该编码行的「项目名称」单元格（名称对调只能改名称列）"
                else:
                    swaps[n] = (sc[0], a, b)
                    how += f"；改的是编码 {sc[0]} 的「项目名称」单元格"
        elif e["kind"] == "删去金额" and n in pre_applied:
            ok = s_ == k_ == PRICE_REDACTED and not MONEY.search(k_)
            how = ("入仓副本已预先删去定价：副本与 K8 该行同为「（略）」；原件该行由 sha256 链核对（只改这一行）"
                   if ok else "入仓副本与 K8 该行不是同为「定价：（略）」")
        elif e["kind"] == "删去金额":
            ok = bool(MONEY.search(s_)) and k_ == MONEY.sub("（略）", s_) and not MONEY.search(k_)
            how = "源行命中金额正则；把命中片段替换为「（略）」后与 K8 行逐字相同；K8 行不再命中" if ok else "改动与描述不符"
        else:
            how = "未知勘误类型"
        if not ok:
            errs.append(f"勘误 源第{n}行：{how}")
        elif n not in pre_applied:
            fixes.append({"src_line": n, "kind": e["kind"], "text": k_})   # 已核：k_ = 源行按描述替换后的整行
        sm = difflib.SequenceMatcher(a=s_, b=k_)
        ops = [(op, i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
        detail.append({"src_line": n, "k8_line": e["k8_line"], "kind": e["kind"], "ok": ok, "check": how, "char_ops": ops})
    # 名称对调必须成对：上下相邻两行，A 的旧名 = B 的新名、A 的新名 = B 的旧名
    for n, (code, a, b) in swaps.items():
        mate = [m for m, (_, a2, b2) in swaps.items() if abs(m - n) == 1 and a2 == b and b2 == a]
        if len(mate) != 1:
            errs.append(f"勘误 源第{n}行（{code}）「名称对调」找不到相邻的对调另一行")
    # 只把核验通过的勘误交给 G2 / G6（main 里 S.apply_fixes）；G3 不过时它们照样按「源 + 已核勘误」核对
    req = ["33601ca8", "md5 " + SRC2013_MD5, "gen_2013.py", DECL, "国标2013", "不通用", "同上"]
    for r_ in req:
        if r_ not in htxt:
            errs.append(f"K8 文件头缺「{r_}」")
    mode_txt = ("原件" if S.md_mode == "original" else
                f"入仓副本（第 {PRICE_LINE} 行已预先删去定价，按原件 md5 登记）" if S.md_mode == "repo_copy" else "未知来源")
    return {"ok": not errs, "errors": errs, "src_md5": S.md_md5, "src_sha256": S.md_sha, "src_mode": S.md_mode,
            "src_file_md5": S.md_file_md5, "src_file_sha256": S.md_file_sha,
            "header_lines": h, "offset": off, "body_lines": len(body), "src_lines": len(src),
            "diff_lines": diffs, "errata": detail, "fixes": fixes,
            "evidence": f"源为{mode_txt}，md5 {S.md_md5}{' 与方案一致' if S.md_md5 == SRC2013_MD5 else ' 与方案不符'}；K8 = {h} 行文件头 + 1 空行 + 正文 {len(body)} 行（源 {len(src)} 行）；"
                        f"逐行比对差异行 = {diffs}（源行号），勘误表所列 {listed}"
                        + (f"（其中 {sorted(pre_applied)} 已在副本预先改好）" if pre_applied else "")
                        + f"；勘误 {len(errata)} 条与校验器登记的已裁定勘误逐条相同，每条的改动内容与描述逐字吻合"
                          f"（名称对调 {len(swaps)} 行两两成对、只改名称列）"}


# ============================================================ G4
def gate4(docs: dict[str, Doc]) -> dict:
    hits = []
    info = []
    for d in docs.values():
        for i, ln in enumerate(d.lines, 1):
            for m in MONEY.finditer(ln):
                hits.append({"file": d.label, "line": i})
            if re.search(r"[￥¥]|亿元", ln):
                info.append({"file": d.label, "line": i})
        if MONEY.search(d.name):
            hits.append({"file": d.label, "line": 0})
    return {"ok": not hits, "errors": [f"{h['file']} 第{h['line']}行命中金额正则" for h in hits],
            "hits": len(hits), "extra_currency_marks": info,
            "evidence": f"{len(docs)} 个文件全文（含文件头）与文件名用 \\d+(\\.\\d+)?\\s*(元|万元) 扫描，命中 {len(hits)}；"
                        f"另扫 ￥/¥/亿元 命中 {len(info)}"}


# ============================================================ G5
def doc_one_read(d: Doc) -> tuple[bool, int]:
    """模拟 tools.py _read_doc_text(offset=0, limit=300)：行按 str.splitlines；逐行累加 len+1，超 16000 截断。"""
    lines = d.text.splitlines()
    hi = min(0 + min(max(DOC_MAX_BLOCKS, 1), DOC_MAX_BLOCKS * 2), len(lines))
    used, chosen = 0, 0
    for i in range(0, hi):
        if chosen and used + len(lines[i]) > DOC_MAX_CHARS:
            hi = i
            break
        chosen += 1
        used += len(lines[i]) + 1
    return hi >= len(lines), used


def gate5(docs: dict[str, Doc]) -> dict:
    errs, rows = [], []
    br_k8 = []
    for d in docs.values():
        e = []
        n = d.name
        if len(n) > 60:
            e.append(f"文件名 {len(n)} 字 > 60")
        if len(n.encode("utf-8")) > 236:
            e.append(f"文件名 {len(n.encode('utf-8'))} 字节 > 236")
        bad = sorted(set(n) & FORBID_CHARS)
        if bad:
            e.append(f"文件名含禁用字符 {bad}")
        if n != n.strip() or re.match(r"^\d", n) or not n.endswith(".md"):
            e.append("文件名首尾空格/数字开头/非 .md")
        if d.decode_err:
            e.append("不是合法 UTF-8")
        if d.raw.startswith(b"\xef\xbb\xbf"):
            e.append("带 BOM")
        if b"\r" in d.raw:
            e.append("含 CR")
        if not d.raw.endswith(b"\n"):
            e.append("末尾无换行")
        if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", d.text):
            e.append("含控制字符")
        for i, ln in enumerate([n] + d.lines):
            where = "文件名" if i == 0 else f"第{i}行"
            for m in LOCAL_PATH.finditer(ln):
                e.append(f"{where} 含本机/服务器路径片段「{m.group()}」")
            for m in LONG_ID.finditer(ln):
                e.append(f"{where} 含 {len(m.group())} 位长数字（疑似运行时 id）")
        heads = sum(1 for ln in d.text.splitlines() if ln.strip().startswith("#"))
        if heads > OUTLINE_MAX:
            e.append(f"# 标题 {heads} > 200")
        trows = 0
        for t in d.tables:
            w = len(t["header"])
            if not t["sep_ok"]:
                e.append(f"第{t['start']}行 表格缺分隔行")
            for k, rw in enumerate(t["raw_widths"]):
                if rw != w:
                    e.append(f"第{t['start'] + k}行 列数 {rw}≠表头 {w}（未转义 | 或缺格）")
            for ln, c, raw in t["rows"]:
                trows += 1
                if not raw.rstrip().endswith("|") or len(c) != w:
                    e.append(f"第{ln}行 表格行不完整")
                if "<br" in raw.lower():
                    if d.label == "K8":
                        br_k8.append(ln)  # 原文照录（源文件表格单元格自带 <br>），物理上仍是一行，GREP 不受影响
                    else:
                        e.append(f"第{ln}行 单元格含 <br>")
            nl = t["next_line"]
            if nl is not None and nl.strip() and not nl.startswith("#"):
                e.append(f"第{t['end'] + 1}行 紧跟表格的非空行（疑似单元格内换行）")
        # 文件头：第一个 # 标题之前的引用块，含固定声明、生成脚本与时间、commit、sha256
        htxt = "\n".join(d.head)
        first_h = next((i for i, ln in enumerate(d.lines) if ln.startswith("#")), None)
        if not d.head or first_h is None or first_h < len(d.head):
            e.append("文件头不在第一个标题之前")
        for need in (DECL, "33601ca8", "sha256"):
            if need not in htxt:
                e.append(f"文件头缺「{need[:12]}」")
        if not re.search(r"生成：\S+\.py，生成时间 \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+08:00", htxt):
            e.append("文件头缺生成脚本/时间")
        chars = len(d.text)
        one, used = doc_one_read(d)
        limit_rule = "K8/K9 按方案单文件保留（K9 约 330 行定为单文件；K8 为全文）" if d.label in ("K8", "K9") else "≤16000 且一次 DOC 读完"
        if d.label not in ("K8", "K9"):
            if chars > DOC_MAX_CHARS:
                e.append(f"{chars} 字 > 16000")
            if not one:
                e.append("模拟引擎 DOC 一次读不完")
        rows.append({"label": d.label, "name": n, "name_chars": len(n), "name_bytes": len(n.encode("utf-8")),
                     "chars": chars, "lines": len(d.text.splitlines()), "headings": heads, "table_rows": trows,
                     "doc_one_read": one, "size_rule": limit_rule, "errors": e})
        errs += [f"{d.label} {x}" for x in e]
    return {"ok": not errs, "errors": errs, "files": rows, "k8_br_rows": len(br_k8),
            "evidence": f"{len(rows)} 个文件：文件名最长 {max(r['name_chars'] for r in rows)} 字 / "
                        f"{max(r['name_bytes'] for r in rows)} 字节；标题最多 {max(r['headings'] for r in rows)} 个；"
                        f"全部 UTF-8 无 BOM 无 CR；不含本机/服务器路径与 16 位以上长数字；"
                        f"表格行 {sum(r['table_rows'] for r in rows)} 行列数全部与表头一致；"
                        f"K0–K7 最大 {max(r['chars'] for r in rows if r['label'] not in ('K8', 'K9'))} 字且模拟 DOC 一次读完"}


# ============================================================ G6
def locate(row_label: str, src: str, cells: list[str], hdr: list[str], S: Sources, docs) -> list[str]:
    """按出处回源定位；返回定位证据列表（空 = 定位失败）。"""
    ev = []
    for m in re.finditer(r"zj2025\.yaml codes\.(Z?\d{9})", src):
        c = m.group(1)
        if c in S.zj and c in cells:
            ev.append(f"zj2025.yaml codes.{c} = {S.zj_name(c)} / {S.zj_unit(c)}")
        elif c in S.zj and row_label == "K7":
            ev.append(f"zj2025.yaml codes.{c} = {S.zj_name(c)}（改正目标）")
        else:
            return []
    for m in re.finditer(r"consistency_rules\[(\w+)\] 第(\d+)行", src):
        rid, n = m.group(1), int(m.group(2))
        if S.qr_lines[n - 1].strip() != f"- id: {rid}" or cells[0] != rid:
            return []
        rule = next((r for r in S.qr["consistency_rules"] if r["id"] == rid), None)
        if rule is None or len(cells) != 6:
            return []
        trig, exp_cell, forb_cell, note = cells[1], cells[2], cells[3], cells[4]
        words = [w for k in ("any", "text_any", "ctx_any", "text_none", "ctx_none", "any_none") for w in rule.get(k, [])]
        if any(f"「{w}」" not in trig for w in words) or rule["message"] not in note:
            return []
        for key, cell in (("expect", exp_cell), ("forbid", forb_cell)):
            pre = [str(x) for x in rule.get(key, [])]
            if not pre:
                if cell != "—":
                    return []
                continue
            listed = set(CODE_TOKEN.findall(cell))
            want = set()
            for p_ in pre:
                if len(p_) == 4:
                    chap = [c for c in S.zj if chapter_of(c) == p_]
                    if f"{p_} 整章" not in cell or f"全部 {len(chap)} 个编码" not in cell:
                        return []
                    if not {c for c in listed if chapter_of(c) == p_} <= set(chap):
                        return []
                    want |= {c for c in listed if chapter_of(c) == p_}
                else:
                    want |= {c for c in S.zj if strip_z(c).startswith(p_)}
            if listed != want:
                return []
        ev.append(f"quantity_rules.yaml 第{n}行 `{S.qr_lines[n - 1].strip()}`；触发词 {len(words)} 个、message、"
                  f"expect/forbid 前缀按码表展开均一致")
    for m in re.finditer(r"confusables\[(\d+)\] 第(\d+)行", src):
        k, n = int(m.group(1)), int(m.group(2))
        txt = S.qr["confusables"][k]
        if S.qr_lines[n - 1].strip() != f"- {txt}" or txt not in cells or cells[0] != str(k + 1):
            return []
        cc = cells[2]
        for c in CODE_TOKEN.findall(txt):
            if c not in CODE_TOKEN.findall(cc):
                return []
        for mm in re.finditer(r"(Z?)(\d{6})xxx", txt):
            nn = sum(1 for c in S.zj if strip_z(c).startswith(mm.group(2)))
            if f"{mm.group(0)}＝去掉 Z 后以 {mm.group(2)} 开头的 {nn} 个编码" not in cc:
                return []
        for mm in re.finditer(r"(\d{4})-(\d{2})", txt):
            nn = sum(1 for c in S.zj if strip_z(c).startswith(mm.group(1) + mm.group(2)))
            if f"{mm.group(0)}＝{mm.group(1)}{mm.group(2)} 节 {nn} 个编码" not in cc:
                return []
        ev.append(f"quantity_rules.yaml 第{n}行 confusables[{k}] 与照录列逐字相同；文中编码/xxx 前缀/节号全部在涉及编码列展开")
    for m in re.finditer(r"SKILL\.md 第(\d+)行", src):
        n = int(m.group(1))
        sc = cells_of(S.skill_lines[n - 1])
        if len(sc) != 3 or not (105 < n <= 155):
            return []
        code_ok = sc[1] in cells or re.search(rf"原写 {sc[1]}", src) or sc[1] == cells[2]
        desc_ok = sc[0] == cells[0] or f"原「{sc[0]}」" in src
        if not (code_ok and desc_ok):
            return []
        ev.append(f"SKILL.md 第{n}行 `{sc[0]} | {sc[1]} | {sc[2]}`")
    for m in re.finditer(r"clause_llm\.py 第(\d+)行", src):
        n = int(m.group(1))
        if n not in S.clause_ref:
            return []
        line = S.clause_ref[n]
        codes_here = set(CODE_TOKEN.findall(line))
        orig = set(re.findall(r"原写 (Z?\d{9})", src))
        if not ((set(c for c in cells if CODE_TOKEN.fullmatch(c)) | orig) & codes_here):
            return []
        ev.append(f"clause_llm.py 第{n}行（_MAPPING_REF 内）含 {sorted(codes_here & (set(cells) | orig))}")
    m = re.fullmatch(r"GB50854-2013\.md 第(\d+)行；zj2025\.yaml codes\.(Z?\d{9})", src)
    if m:
        n = int(m.group(1))
        # 源文件 + 已通过 G3 核验的勘误（行号仍是源行号）
        if not (1 <= n <= len(S.md_fixed_lines)) or not S.md_fixed_lines[n - 1].startswith(f"| {cells[0]} | {cells[1]} |"):
            return []
        ev.append(f"GB50854-2013.md 第{n}行{'（勘误后）' if n in S.md_fixes_applied else ''} 以「| {cells[0]} | {cells[1]} |」开头")
    # K0 出处
    m = re.fullmatch(r"zj2025\.yaml chapters ([0-9、]+)（commit 33601ca8）", src)
    if m:
        chs = m.group(1).split("、")
        n = sum(1 for c in S.zj if chapter_of(c) in chs)
        mm = re.search(r"共 (\d+) 个编码", cells[3])
        doc = docs.get(cells[1])
        drows = sum(len(t["rows"]) for t in doc.tables) if doc else -1
        if not all(c in S.zj_ch for c in chs) or not mm or int(mm.group(1)) != n or drows != n:
            return []
        ev.append(f"zj2025.yaml 章 {chs} 共 {n} 码 = K0 所写 = 该文件表格行数")
    if src.startswith("quantity_rules.yaml consistency_rules、confusables"):
        mm = re.search(r"列项校核规则 (\d+) 条、易混淆对照 (\d+) 条", cells[3])
        if not mm or (int(mm.group(1)), int(mm.group(2))) != (len(S.qr["consistency_rules"]), len(S.qr["confusables"])):
            return []
        ev.append(f"quantity_rules.yaml 规则 {mm.group(1)} 条、confusables {mm.group(2)} 条")
    if src.startswith("SKILL.md 第105–155行映射表"):
        if "对应GB编码" not in S.skill_lines[104] or len(cells_of(S.skill_lines[154])) != 3 or S.skill_lines[155].strip():
            return []
        if "_MAPPING_REF" not in src:
            return []
        ev.append("SKILL.md 第105行为映射表表头、第155行为最后一行；clause_llm.py _MAPPING_REF 存在")
    m = re.fullmatch(r"GB50854-2013\.md（md5 ([0-9a-f]{32})）", src)
    if m:
        if m.group(1) != S.md_md5:
            return []
        ev.append(f"GB50854-2013.md md5 = {S.md_md5}")
    if src == "GB50854-2013.md 附录表 × zj2025.yaml codes":
        want1 = [c for c in S.md_rows if c in S.zj]
        want2 = [z for z in S.zj if z.startswith("Z") and z[1:] in S.md_rows]
        mm = re.search(r"同 9 位编码 (\d+) 个.*?撞号 (\d+) 个", cells[3])
        if not mm or (int(mm.group(1)), int(mm.group(2))) != (len(want1), len(want2)):
            return []
        ev.append(f"两源重算：同码 {len(want1)}、Z 码撞号 {len(want2)}")
    if src == "kb_plan.md §1.2 K0":
        if S.plan_text is not None:
            if "| K0 | 【清单】清单编码类资料版本与使用说明.md |" not in S.plan_text:
                return []
            ev.append("kb_plan.md §1.2 表中有 K0 行，文件名一致")
        else:
            k0 = next((d for d in docs.values() if d.label == "K0"), None)
            if not k0 or f"sha256 {PLAN_SHA256}" not in "\n".join(k0.head):
                return []
            ev.append(f"kb_plan.md 不入仓；K0 文件头登记的方案 sha256 = 登记值 {PLAN_SHA256[:12]}…（未给 --plan，未核方案原文）")
    return ev


def gate6(docs: dict[str, Doc], S: Sources) -> dict:
    errs, allrows = [], []
    for d in docs.values():
        if d.label == "K8":
            continue  # K8 是原文逐字照录，整份出处 = 源文件（见 G3 逐行比对）
        for t in d.tables:
            hdr = t["header"]
            if "出处" not in hdr:
                errs.append(f"{d.label} 第{t['start']}行 表格没有「出处」列")
                continue
            k = hdr.index("出处")
            for ln, c, raw in t["rows"]:
                src = c[k] if k < len(c) else ""
                if not src or src in ("—", "-"):
                    errs.append(f"{d.label} 第{ln}行 出处为空")
                    continue
                allrows.append((d.label, d.name, ln, c, hdr, src))
    located, failed = 0, []
    for lab, name, ln, c, hdr, src in allrows:
        ev = locate(lab, src, c, hdr, S, docs)
        if ev:
            located += 1
        else:
            failed.append(f"{lab} 第{ln}行 出处「{src[:40]}」回源失败")
    errs += failed
    # K7 覆盖性：SKILL.md 第107–155行每一行、_MAPPING_REF 每一行里的每个编码，都有 K7 行承接（作编码或「原写」）
    k7rows = [r for r in allrows if r[0] == "K7" and r[4] and r[4][0] == "描述特征"]
    cited_skill = {int(x) for r in k7rows for x in re.findall(r"SKILL\.md 第(\d+)行", r[5])}
    miss_skill = sorted(set(range(107, 156)) - cited_skill)
    if miss_skill:
        errs.append(f"K7 没有承接 SKILL.md 第 {miss_skill} 行")
    miss_clause = []
    for n, line in S.clause_ref.items():
        got = set()
        for r in k7rows:
            if re.search(rf"clause_llm\.py 第{n}行", r[5]):
                got |= {r[3][2]} | set(re.findall(r"原写 (Z?\d{9})", r[5]))
        for c in CODE_TOKEN.findall(line):
            if c not in got:
                miss_clause.append((n, c))
    if miss_clause:
        errs.append(f"K7 没有承接 _MAPPING_REF 编码 {miss_clause}")
    coverage = {"skill_rows_cited": len(cited_skill & set(range(107, 156))), "skill_rows_total": 49,
                "clause_lines": sorted(S.clause_ref), "clause_codes_uncovered": miss_clause}
    # 固定种子抽检 20 行：每个文件至少 1 行，其余随机
    rng = random.Random(20261001)
    by = {}
    for r in allrows:
        by.setdefault(r[0], []).append(r)
    sample = [rng.choice(v) for _, v in sorted(by.items())]
    rest = [r for r in allrows if r not in sample]
    sample += rng.sample(rest, max(0, 20 - len(sample)))
    spot = []
    for lab, name, ln, c, hdr, src in sample:
        ev = locate(lab, src, c, hdr, S, docs)
        spot.append({"file": lab, "line": ln, "key": c[0][:30], "出处": src[:80], "located": bool(ev), "evidence": ev})
    if sum(s["located"] for s in spot) != 20:
        errs.append("抽检 20 行有定位失败")
    return {"ok": not errs, "errors": errs, "data_rows": len(allrows), "located": located, "k7_coverage": coverage,
            "per_file": {k: len(v) for k, v in sorted(by.items())}, "spot_check_20": spot,
            "evidence": f"K0–K7、K9 数据行 {len(allrows)} 行出处全部非空，全量回源定位 {located}/{len(allrows)}；"
                        f"固定种子 20261001 抽检 20 行（每文件至少 1 行）定位 {sum(s['located'] for s in spot)}/20；"
                        f"K8 为原文照录，出处由 G3 逐行比对覆盖；K6 表一逐条核对触发词/message/前缀展开，表二核对照录与展开；"
                        f"K7 承接 SKILL.md 映射表 {coverage['skill_rows_cited']}/49 行、_MAPPING_REF 编码未承接 {len(miss_clause)} 个"}


# ============================================================ G7
def load_categories(path: Path | None) -> tuple[dict | None, list[str]]:
    """读 --categories 本地配置：{"清单": id, "清单/房屋建筑": id}。不给 → (None, [])。"""
    if path is None:
        return None, []
    try:
        cats = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as ex:
        return {}, [f"--categories 读不了：{ex}"]
    want = {CAT_ROOT_NAME, CAT_HOUSE_NAME}
    if not isinstance(cats, dict) or set(cats) != want:
        got = sorted(cats) if isinstance(cats, dict) else type(cats).__name__
        return {}, [f"--categories 的键必须正好是 {sorted(want)}，实际 {got}"]
    errs = [f"--categories「{k}」的 id 不是正整数串（≤19 位）：{v!r}"
            for k, v in cats.items() if not isinstance(v, str) or not CATEGORY_ID.fullmatch(v)]
    if len(set(map(str, cats.values()))) != len(cats):
        errs.append("--categories 两个类目的 id 相同")
    return cats, errs


def gate7(docs: dict[str, Doc], S: Sources, out: Path, manifest_path: Path, results: dict, gen_at: str,
          cat_path: Path | None = None) -> dict:
    cats, errs = load_categories(cat_path)
    order = ["K0", "K1", "K2", "K2a", "K2b", "K3", "K4", "K4a", "K4b", "K5", "K6", "K7", "K8", "K9"]
    ds = sorted(docs.values(), key=lambda d: order.index(d.label) if d.label in order else 99)
    entries = []
    for d in ds:
        cat = CAT_ROOT_NAME if d.label == "K0" else CAT_HOUSE_NAME           # 一路：按编号（方案 §1.2）
        by_prefix = next((c for pfx, c in CAT_BY_PREFIX.items() if d.name.startswith(pfx)), None)  # 另一路：按文件名
        if d.label != "?" and by_prefix != cat:       # 无法归类的文件另有报错（main 里的 unknown）
            errs.append(f"{d.label} 目标类目两路不一致：按编号应进「{cat}」，按文件名前缀是「{by_prefix}」")
        entries.append({
            "id": d.label, "name": d.name, "local_path": str(d.path), "bytes": len(d.raw),
            "sha256": sha256(d.raw), "chars": len(d.text), "lines": len(d.text.splitlines()),
            "headings": sum(1 for ln in d.text.splitlines() if ln.strip().startswith("#")),
            "table_rows": sum(len(t["rows"]) for t in d.tables),
            "category": cat, "categoryId": (cats or {}).get(cat), "content_type": "text/markdown",
            "upload": {"status": "not_uploaded", "successList_path": None, "uploaded_at": None},
        })
    man = {
        "_note": "KB-GATE 登记清单：只放本地，不上传。upload 字段由 KB-UPLOAD 回填。",
        "generated_at": gen_at, "generator": "check_kb.py", "baseline_commit": COMMIT,
        "gate_passed_1_to_6": all(results[g]["ok"] for g in ("G1", "G2", "G3", "G4", "G5", "G6")),
        "sources": {
            "zj2025_yaml": {"path": ZJ_PATH, "commit": COMMIT, "sha256": S.zj_sha},
            "quantity_rules_yaml": {"path": QR_PATH, "commit": COMMIT, "sha256": S.qr_sha},
            "gb50854_2013_md": {"path": str(S.gb_path), "mode": S.md_mode, "md5": S.md_md5, "sha256": S.md_sha},
            "skill_md": {"path": S.skill_path, "sha256": S.skill_sha, "lines": "105-155", "mode": S.k7_src_mode},
            "clause_llm_py": {"path": S.clause_path, "only": "_MAPPING_REF", "lines": list(S.clause_var_lines),
                              "mode": S.k7_src_mode},
        },
        "categories": cats if cats else {CAT_ROOT_NAME: None, CAT_HOUSE_NAME: None},
        "categories_source": (str(cat_path) if cat_path else
                              "未给 --categories：categoryId 记 null；上传前用本地配置补（各租户 / 各环境 id 不同，不入仓）"),
        "upload_order": [e["id"] for e in entries],
        "file_count": len(entries),
        "files": entries,
        "not_uploaded_local_only": ["local_only/*（含 K7 xlsx 审签件）", "manifest.json 本身"],
    }
    manifest_path.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # 回读核对
    back = json.loads(manifest_path.read_text(encoding="utf-8"))
    need = ["id", "name", "sha256", "chars", "lines", "category"]
    # 类目 id：回读时另读一遍本地配置核对（不拿写 manifest 时的那个 dict 自己核自己）
    cats_back = None
    if cat_path is not None and cats:
        try:
            cats_back = json.loads(cat_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cats_back = {}
    for e in back["files"]:
        for k in need:
            if e.get(k) in (None, ""):
                errs.append(f"manifest {e.get('id')} 缺 {k}")
        p = out / e["name"]
        if not p.exists() or sha256(p.read_bytes()) != e["sha256"]:
            errs.append(f"manifest {e['id']} sha256 与磁盘不一致")
        txt = p.read_text(encoding="utf-8")
        if len(txt) != e["chars"] or len(txt.splitlines()) != e["lines"]:
            errs.append(f"manifest {e['id']} 字数/行数与磁盘不一致")
        if e.get("category") not in (CAT_ROOT_NAME, CAT_HOUSE_NAME) or (e["id"] == "K0") != (e["category"] == CAT_ROOT_NAME):
            errs.append(f"manifest {e['id']} 目标类目不对：{e.get('category')}")
        if cat_path is None:
            if e.get("categoryId") is not None:
                errs.append(f"manifest {e['id']} 没给 --categories 却写了 categoryId")
        elif cats_back is not None:
            want_id = cats_back.get(e.get("category"))
            if not isinstance(e.get("categoryId"), str) or not CATEGORY_ID.fullmatch(e["categoryId"]) \
                    or e["categoryId"] != want_id:
                errs.append(f"manifest {e['id']} categoryId {e.get('categoryId')!r} 与本地配置「{e.get('category')}」{want_id!r} 不符")
    names = {e["name"] for e in back["files"]}
    on_disk = {p.name for p in out.iterdir() if p.is_file()}
    if on_disk != names:
        errs.append(f"out/ 与 manifest 不一致：多 {sorted(on_disk - names)} 缺 {sorted(names - on_disk)}")
    k0 = next((d for d in docs.values() if d.label == "K0"), None)
    k0_names = set()
    if k0:
        for t in k0.tables:
            if t["header"] and t["header"][:2] == ["编号", "文件名"]:
                k0_names |= {c[1] for _, c, _ in t["rows"]}
                for _, c, _ in t["rows"]:
                    lab = next((e["id"] for e in back["files"] if e["name"] == c[1]), None)
                    if lab != c[0]:
                        errs.append(f"K0 编号 {c[0]} 与 manifest 编号 {lab} 不一致")
        mcount = re.search(r"共 (\d+) 个文件（含本页）", k0.text)
        if not mcount or int(mcount.group(1)) != len(names):
            errs.append("K0 文件头所写文件数与 manifest 不一致")
    if k0_names != names:
        errs.append(f"K0 所列文件与 manifest 不一致：K0 多 {sorted(k0_names - names)} 缺 {sorted(names - k0_names)}")
    logical = {re.sub(r"[ab]$", "", e["id"]) for e in back["files"]}
    if logical != {f"K{i}" for i in range(10)}:
        errs.append(f"K0–K9 不全：{sorted(logical)}")
    return {"ok": not errs, "errors": errs, "manifest": str(manifest_path), "file_count": len(names),
            "logical_set": sorted(logical),
            "categories_given": cat_path is not None,
            "evidence": f"manifest.json 登记 {len(names)} 个文件（逻辑 K0–K9 共 10 项，K4 按章拆成 K4a/K4b），"
                        f"回读核对 sha256/字数/行数全部与磁盘一致；K0 所列文件 = manifest = out/ 目录；"
                        f"目标类目按编号与按文件名前缀两路一致（K0→{CAT_ROOT_NAME}，其余→{CAT_HOUSE_NAME}）；"
                        + (f"类目 id 取自本地配置 {cat_path.name}，回读另读配置核对一致" if cat_path is not None
                           else "未给 --categories，categoryId 记 null（id 不入仓）")}


# ============================================================ 报告
def md_report(res: dict, docs, manifest_path: Path, gen_at: str) -> str:
    L = ["# KB-GATE 校验报告（知识库上传前总校验门）", "",
         f"- 生成：check_kb.py（独立校验，不复用生成器代码），{gen_at}",
         f"- 基线：main={COMMIT}（码表与规则均 git show {COMMIT} 现取）",
         f"- 结论：**{'七条全过' if res['ok'] else '未通过'}**；待上传文件 {res['G7'].get('file_count')} 个（逻辑 K0–K9 共 10 项，K4 按章拆成 2 份）",
         f"- 登记清单：{manifest_path}（只放本地，不上传）", ""]
    names = {"G1": "回读零差异", "G2": "编码全可查", "G3": "K8 只改了该改的", "G4": "不含金额",
             "G5": "格式合规", "G6": "行级出处", "G7": "登记清单"}
    L += ["## 门槛总表", "", "| 门槛 | 结果 | 证据 |", "|---|---|---|"]
    for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"):
        r = res[g]
        L.append(f"| {g} {names[g]} | {'通过' if r['ok'] else '不通过'} | {r['evidence'].replace('|', '/')} |")
    L += ["", "## 文件清单", "", "| 编号 | 文件名 | 字数 | 行数 | 标题 | 表格行 | 文件名字/字节 | 一次 DOC 读完 | 目标类目（id） |",
          "|---|---|---|---|---|---|---|---|---|"]
    man = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"files": []}
    g5 = {r["label"]: r for r in res["G5"]["files"]}
    for e in man["files"]:
        r = g5.get(e["id"], {})
        L.append(f"| {e['id']} | {e['name']} | {e['chars']} | {e['lines']} | {e['headings']} | {e['table_rows']} | "
                 f"{r.get('name_chars')}/{r.get('name_bytes')} | {'是' if r.get('doc_one_read') else '否（' + r.get('size_rule', '') + '）'} | {e['category']}（{e['categoryId'] or '未给'}） |")
    g1f = sorted(res["G1"]["files"], key=lambda x: x["label"])
    L += ["", "## G1 明细", "", "- 各文件：" + "；".join(f"{x['label']} 章 {'、'.join(x['chapters'])} 共 {x['rows']} 码" for x in g1f),
          f"- 缺 {res['G1']['missing']}；多 {res['G1']['extra']}；重复 {res['G1']['duplicates']}", ""]
    g2 = res["G2"]
    L += ["## G2 明细", "", f"- 编码出现次数：{g2['by_file']}；名称/单位核对 {g2['names_checked']} 处",
          f"- 「原写」豁免：{g2['exempt_original_codes']}（K7 改正记录登记的原值；010902003 已核对浙江2025无此码、国标2013 第1472行为屋面刚性层）",
          f"- K9 完整性：{g2['k9_completeness']}",
          "- 编码后直接跟文字（非「」）的自由文本出现："]
    from collections import Counter
    cnt = Counter(f["class"] for f in g2["freetext"])
    L.append(f"  - 分类计数 {dict(cnt)}（「名称一致」= 后接文字以源名称开头；「后接非名称」= 后接连接词/标点，没有写名称）")
    for f in g2["freetext"]:
        if f["class"] != "名称一致":
            L.append(f"  - {f['file']} {f['where']}：{f['code']} 后接「{f['follow']}」→ {f['class']}")
    L.append("- K0 事实陈述核对：")
    for c in g2["k0_claims"]:
        L.append(f"  - {'成立' if c['ok'] else '不成立'}：{c['claim']}")
    g3 = res["G3"]
    L += ["", "## G3 明细", "", f"- 源 md5 {g3.get('src_md5')}，sha256 {g3.get('src_sha256')}",
          f"- K8 文件头 {g3.get('header_lines')} 行 + 空行，正文行号偏移 +{g3.get('offset')}；正文 {g3.get('body_lines')} 行 / 源 {g3.get('src_lines')} 行",
          f"- 差异行（源行号）：{g3.get('diff_lines')}"]
    for e in g3.get("errata", []):
        L.append(f"  - 源第{e['src_line']}行 → K8 第{e['k8_line']}行【{e['kind']}】{'吻合' if e['ok'] else '不吻合'}：{e['check']}；字符级改动 {e['char_ops']}")
    L += ["", "## G4 明细", "", f"- 命中 {res['G4']['hits']}；￥/¥/亿元 {len(res['G4']['extra_currency_marks'])}", ""]
    L += ["## G6 抽检 20 行（固定种子 20261001）", "", "| # | 文件 | 行 | 首列 | 出处 | 定位 | 证据 |", "|---|---|---|---|---|---|---|"]
    for i, s in enumerate(res["G6"]["spot_check_20"], 1):
        ev = "；".join(s["evidence"]).replace("|", "/")
        L.append(f"| {i} | {s['file']} | {s['line']} | {s['key'].replace('|', '/')} | {s['出处'].replace('|', '/')} | {'是' if s['located'] else '否'} | {ev[:160]} |")
    L += ["", "## 未通过项", ""]
    bad = [f"{g}: {e}" for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7") for e in res[g]["errors"]]
    L += [f"- {b}" for b in bad] or ["- 无"]
    return "\n".join(L) + "\n"


def main() -> int:
    global REPO
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--manifest", default=str(HERE / "local_only" / "manifest.json"))
    ap.add_argument("--report", default=str(HERE / "local_only" / "KB-GATE-校验报告.md"))
    ap.add_argument("--json", default=str(HERE / "local_only" / "KB-GATE-校验结果.json"))
    ap.add_argument("--notes", default=None, help="附加到报告末尾的处置说明（markdown）")
    ap.add_argument("--repo", default=REPO, help="取 git show 33601ca8 的仓库（默认本仓）")
    ap.add_argument("--gb2013", default=str(SRC2013_DEFAULT), help="国标2013 原件或入仓副本")
    ap.add_argument("--skill", default=None, help="SKILL.md 原文件（与 --clause 同给；不给读快照）")
    ap.add_argument("--clause", default=None, help="clause_llm.py 原文件（只抽 _MAPPING_REF）")
    ap.add_argument("--snapshot", default=str(SNAPSHOT_DEFAULT))
    ap.add_argument("--plan", default=None, help="执行方案 kb_plan.md（不入仓；不给则核 K0 文件头登记的 sha256）")
    ap.add_argument("--categories", default=None,
                    help='上传目标类目 id 的本地配置 JSON：{"清单": id, "清单/房屋建筑": id}（放 local_only/，不入仓）')
    a = ap.parse_args()
    REPO = a.repo
    if not source_available(REPO, COMMIT, "engine-service/app/engine/data/gb50854_zj2025.yaml"):
        print(f"✗ {REPO} 下没有受控源快照，也取不到 commit {COMMIT}；用 --repo 指向 sources/repo-snapshot", file=sys.stderr)
        return 2
    out = Path(a.out)
    for f in (a.manifest, a.report, a.json):
        Path(f).parent.mkdir(parents=True, exist_ok=True)
    gen_at = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    S = Sources(Path(a.gb2013), Path(a.skill) if a.skill else None, Path(a.clause) if a.clause else None,
                Path(a.snapshot), Path(a.plan) if a.plan else None)
    paths = sorted(p for p in out.iterdir() if p.is_file())
    docs = {p.name: Doc(p) for p in paths}
    labels = classify(list(docs))
    for n, d in docs.items():
        d.label = labels.get(n, "?")
    res = {}
    # G3 先跑：它核验过的勘误（源行按勘误描述替换后的整行）交给 G2 / G6，二者拿国标2013 名称回源时用「源 + 已核勘误」
    res["G3"] = gate3(docs, S)
    S.apply_fixes(res["G3"].get("fixes", []))
    res["G1"] = gate1(docs, S)
    res["G2"] = gate2(docs, S)
    res["G4"] = gate4(docs)
    res["G5"] = gate5(docs)
    res["G6"] = gate6(docs, S)
    unknown = [n for n, d in docs.items() if d.label == "?"]
    res["G7"] = gate7(docs, S, out, Path(a.manifest), res, gen_at, Path(a.categories) if a.categories else None)
    if unknown:
        res["G7"]["errors"].append(f"out/ 有无法归类的文件 {unknown}")
        res["G7"]["ok"] = False
    res["ok"] = all(res[g]["ok"] for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"))
    Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rep = md_report(res, docs, Path(a.manifest), gen_at)
    if a.notes:
        rep += "\n" + Path(a.notes).read_text(encoding="utf-8")
    Path(a.report).write_text(rep, encoding="utf-8")
    for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7"):
        r = res[g]
        print(f"{g} {'PASS' if r['ok'] else 'FAIL'}  {r['evidence']}")
        for e in r["errors"][:30]:
            print("    ", e)
    print("RESULT", "PASS" if res["ok"] else "FAIL")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
