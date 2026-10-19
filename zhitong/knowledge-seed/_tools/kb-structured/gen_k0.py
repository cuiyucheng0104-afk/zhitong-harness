#!/usr/bin/env python3
"""KB-GATE：生成知识库 K0《【清单】清单编码类资料版本与使用说明》。

K0 是说明页（方案 §1.2 K0）：列出清单编码类资料 K1–K9 各自的版本、覆盖范围和优先级，写明使用规则
（报编码默认按浙江2025；国标2013 只作计算规则和工作内容的参考；不含金额），并登记已知源数据问题与处理（已在 K8 勘误改正的、仍照录待修源的）。

确定性：文件清单取自 out/ 目录（按固定规则排序、编号），计数全部从受控源和成品现场重算：
  · 章名、各章编码数：git show <commit>:engine-service/app/engine/data/gb50854_zj2025.yaml
  · 规则条数：git show <commit>:engine-service/app/engine/data/quantity_rules.yaml
  · K7 行数、改正数、待核数；K9 两节行数与异名数：从 out/ 下成品表格行现场数
同一输入 + 同一 --generated-at → 字节级相同输出。

文件头里的方案 sha256：执行方案 kb_plan.md 含生产环境信息，不入仓；默认写入登记值 PLAN_SHA256
（生成 K0 时方案文件的 sha256）。在有方案文件的机器上可用 --plan 现算，与登记值不同会在 stderr 提示。

用法（默认 --repo 仓根、--out out/）：
  python3 gen_k0.py [--repo <仓根>] [--out DIR] [--plan kb_plan.md] [--generated-at 2026-10-01T01:47:10+08:00]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import yaml

from kbsrc import SNAPSHOT_REPO, git_show_bytes

HERE = Path(__file__).resolve().parent
REPO = str(SNAPSHOT_REPO)   # 源快照根（见 kbsrc.py）；--repo 可改
COMMIT = "33601ca8"
ZJ_PATH = "engine-service/app/engine/data/gb50854_zj2025.yaml"
QR_PATH = "engine-service/app/engine/data/quantity_rules.yaml"
PLAN_SHA256 = "74cce567be8866095b179280f5aef09c2e7935224cc4e21666f8bd8c51bc9a13"   # 生成 K0 时 kb_plan.md 的 sha256
MD2013_MD5 = "26504c410ebb4c458f53d8db3377103e"
SCRIPT = "gen_k0.py"
DECLARATION = "本文件由脚本从受控源确定性生成，不含任何金额；引用编码必须注明版本（浙江2025 / 国标2013）"

K0_NAME = "【清单】清单编码类资料版本与使用说明.md"
ZJ_PREFIX = "【清单·房屋建筑】浙江2025清单编码表-"
K6_KEY = "浙江2025清单易混淆编码与列项校核规则"
K7_KEY = "设计做法对应浙江2025清单编码参考表"
K8_KEY = "GB50854-2013工程量计算规范全文"
K9_KEY = "国标2013与浙江2025清单同码异名对照表"
# 方案 §1.2 的 K1–K5 分组（按首章归组；组内被拆成多份时编号加 a/b）
GROUPS = [("K1", ["0101", "0102", "0103", "0104"]), ("K2", ["0105", "0106", "0107"]),
          ("K3", ["0108", "0109", "0110"]), ("K4", ["0111", "0112", "0113", "0114", "0115"]),
          ("K5", ["0116", "0118"])]


def git_show(path: str) -> bytes:
    return git_show_bytes(REPO, COMMIT, path)


def chapter_of(code: str) -> str:
    return code.lstrip("Z")[:4]


def chapters_in_name(name: str) -> list[str]:
    m = re.search(r"（([0-9、\-]+)）\.md$", name)
    if not m:
        raise SystemExit(f"文件名里没有章码范围：{name}")
    spec = m.group(1)
    if "-" in spec:
        a, b = spec.split("-")
        return [f"{i:04d}" for i in range(int(a), int(b) + 1)]
    return spec.split("、")


def table_rows(text: str, after_heading: str | None = None, until_heading: bool = True) -> list[str]:
    """取某个 ## 标题下的表格数据行（去掉表头和分隔行）。after_heading=None 取全文。"""
    lines = text.split("\n")
    rows, on, seen_head = [], after_heading is None, False
    for ln in lines:
        if after_heading is not None and ln.startswith("## "):
            if ln.startswith(after_heading):
                on, seen_head = True, False
                continue
            if on and until_heading:
                break
        if not on or not ln.startswith("|"):
            continue
        if re.fullmatch(r"\|(\s*:?-+:?\s*\|)+", ln):
            continue
        if not seen_head:
            seen_head = True  # 表头
            continue
        rows.append(ln)
    return rows


def main() -> int:
    global REPO
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--plan", default=None, help="执行方案 kb_plan.md（不入仓；不给则用登记的 sha256）")
    ap.add_argument("--generated-at", default=None)
    a = ap.parse_args()
    REPO = a.repo
    out = Path(a.out)
    gen_at = a.generated_at or _dt.datetime.now().astimezone().isoformat(timespec="seconds")

    zj_raw = git_show(ZJ_PATH)
    zj = yaml.safe_load(zj_raw)
    zj_sha = hashlib.sha256(zj_raw).hexdigest()
    chapters = {str(k): v for k, v in zj["chapters"].items()}
    per_ch: dict[str, int] = {}
    for c in zj["codes"]:
        per_ch[chapter_of(str(c))] = per_ch.get(chapter_of(str(c)), 0) + 1
    qr_raw = git_show(QR_PATH)
    qr = yaml.safe_load(qr_raw)
    n_rules, n_conf = len(qr["consistency_rules"]), len(qr["confusables"])
    plan_sha = PLAN_SHA256
    if a.plan:
        plan_sha = hashlib.sha256(Path(a.plan).read_bytes()).hexdigest()
        if plan_sha != PLAN_SHA256:
            print(f"注意：方案文件 sha256 {plan_sha} 与登记值 {PLAN_SHA256} 不同，K0 文件头将写现算值", file=sys.stderr)

    names = sorted(p.name for p in out.glob("*.md") if p.name != K0_NAME)

    def one(key: str) -> str:
        hit = [n for n in names if key in n]
        if len(hit) != 1:
            raise SystemExit(f"{key} 应恰好 1 个文件，实际 {hit}")
        return hit[0]

    zj_files = sorted((n for n in names if n.startswith(ZJ_PREFIX)), key=lambda n: chapters_in_name(n)[0])
    rows = []  # (编号, 文件名, 版本, 覆盖范围, 用途与优先级, 出处)
    rows.append(("K0", K0_NAME, "—", "本说明页：清单编码类资料的版本、覆盖范围、优先级和使用规则",
                 "先读本页，再按下面的优先级查具体文件", "kb_plan.md §1.2 K0"))
    for label, gchs in GROUPS:
        fs = [n for n in zj_files if chapters_in_name(n)[0] in gchs]
        for i, n in enumerate(fs):
            chs = chapters_in_name(n)
            cnt = sum(per_ch.get(c, 0) for c in chs)
            lab = label if len(fs) == 1 else f"{label}{'ab'[i]}"
            cover = "、".join(f"{c} {chapters[c]}" for c in chs) + f"，共 {cnt} 个编码"
            rows.append((lab, n, "浙江2025", cover,
                         "第一优先：查浙江2025 编码、项目名称、计量单位、项目特征（编码、名称、单位以本系列为准）",
                         f"zj2025.yaml chapters {'、'.join(chs)}（commit {COMMIT}）"))
    n_zj_files = len(zj_files)

    k6, k7, k8, k9 = one(K6_KEY), one(K7_KEY), one(K8_KEY), one(K9_KEY)
    k8_head = (out / k8).read_text(encoding="utf-8")
    m_err = re.search(r"勘误与处理表（共 (\d+) 处", k8_head)
    if not m_err:
        raise SystemExit("K8 文件头里没有勘误与处理表")
    k8_errata = int(m_err.group(1))
    k7_text = (out / k7).read_text(encoding="utf-8")
    k7_rows = table_rows(k7_text, "## 映射参考表")
    k7_fix = table_rows(k7_text, "## 改正记录")
    k7_pending = sum(1 for r in k7_rows if "【待核】" in r)
    # 改正记录的序号形如 1-1、1-2、3：同一主序号是同一处改正拆成的多行
    k7_fix_n = len({r.split("|")[1].strip().split("-")[0] for r in k7_fix})
    k9_text = (out / k9).read_text(encoding="utf-8")
    s1 = table_rows(k9_text, "## 一、")
    s2 = table_rows(k9_text, "## 二、")

    def n_diff(rs):
        return sum(1 for r in rs if r.rstrip().split("|")[-3].strip() == "异名")

    rows.append(("K6", k6, "浙江2025", f"列项校核规则 {n_rules} 条、易混淆对照 {n_conf} 条（系统校核口径，不是规范原文）",
                 "第二优先：判断易混淆编码和按部位列项（底板、屋面、楼地面、墙面等）",
                 f"quantity_rules.yaml consistency_rules、confusables（commit {COMMIT}）"))
    rows.append(("K7", k7, "浙江2025",
                 f"设计做法到编码的映射 {len(k7_rows)} 行（按引擎规则改正 {k7_fix_n} 处，改正记录 {len(k7_fix)} 行；【待核】{k7_pending} 行）",
                 "第三优先：仅作参考，待造价员签核；与本库易混淆编码与列项校核规则冲突时以校核规则为准",
                 "SKILL.md 第105–155行映射表；clause_llm.py _MAPPING_REF；按 quantity_rules.yaml 改正"))
    rows.append(("K8", k8, "国标2013",
                 f"GB 50854-2013 全文（正文、附录 A～S 各表、条文说明），勘误与处理 {k8_errata} 处登记在文件头",
                 "只查计算规则、工作内容和条文说明；编码与浙江2025不通用，引用编码必须写明「国标2013」",
                 f"GB50854-2013.md（md5 {MD2013_MD5}）"))
    rows.append(("K9", k9, "国标2013 对照 浙江2025",
                 f"同 9 位编码 {len(s1)} 个（异名 {n_diff(s1)} 个）；浙江2025 Z 码去掉 Z 后撞号 {len(s2)} 个（异名 {n_diff(s2)} 个）",
                 "识别同码异名，避免把一个版本的编码当成另一个版本引用",
                 "GB50854-2013.md 附录表 × zj2025.yaml codes"))

    listed = {r[1] for r in rows}
    if listed != set(names) | {K0_NAME}:
        raise SystemExit(f"out/ 文件与清单不一致：多 {set(names) - listed}，缺 {listed - set(names) - {K0_NAME}}")

    k8_off = None
    m = re.search(r"本文件行号 = 源文件行号 \+ (\d+)", (out / k8).read_text(encoding="utf-8"))
    if m:
        k8_off = int(m.group(1))
    k9_title = k9[:-3]
    k8_title = k8[:-3]

    L = [
        f"> 来源：智通造价 AI 知识库搭建执行方案（kb_plan.md §1.2 K0、§1.3；sha256 {plan_sha}）；"
        f"各文件编码数与章名取自 zhitong-cost-ai 仓库 `{ZJ_PATH}`（commit {COMMIT}；sha256 {zj_sha}），"
        f"规则条数取自同一 commit 的 `{QR_PATH}`（sha256 {hashlib.sha256(qr_raw).hexdigest()}），"
        f"国标2013 全文源文件 GB50854-2013.md（md5 {MD2013_MD5}）。",
        f"> 生成：{SCRIPT}，生成时间 {gen_at}",
        f"> 声明：{DECLARATION}。",
        f"> 范围：本页只说明本库「清单」类目下的清单编码类资料，共 {len(rows)} 个文件（含本页）；"
        "各文件的来源、生成脚本和 sha256 见各自文件头。",
        "",
        "# 清单编码类资料版本与使用说明",
        "",
        "## 一、使用规则",
        "",
        "1. 报清单编码默认按浙江2025（GB50854 浙江省2025版）。「Z」开头的是浙江补充编码，引用时必须保留 Z；"
        "Z 码与去掉 Z 后同号的编码是两个不同的清单项目。",
        "2. 国标2013（GB 50854-2013）只作计算规则、工作内容和条文说明的参考。它的编码与浙江2025不通用，"
        "同一 9 位编码在两版中可能是不同项目；引用国标2013 编码必须写明「国标2013」。",
        "3. 回答编码问题时写明版本、所在文件和行号；两版名称不同时，按所用版本取名称和计量单位。",
        "4. 本类资料只有编码、项目名称、计量单位、项目特征、计算规则和列项口径，不含任何价格、单价、费率或金额。"
        "被问到价格时应说明知识库没有价格资料，不得编造数值。",
        "5. 优先级：浙江2025清单编码表（编码、名称、单位以它为准）＞ 易混淆编码与列项校核规则（系统口径）"
        "＞ 设计做法对应编码参考表（待造价员签核，仅作参考）。国标2013 全文和同码异名对照表只用于识别版本差异、查计算规则和工作内容。",
        f"6. 行号：各文件表格里的「出处」列可回到受控源。同码异名对照表出处里的「GB50854-2013.md 第N行」是源文件行号，"
        f"在《{k8_title}》中对应第 N+{k8_off} 行。",
        "",
        f"## 二、文件清单（共 {len(rows)} 个；浙江2025清单编码表按方案「单文件超过 16000 字按章再拆」分成 {n_zj_files} 份）",
        "",
        "| 编号 | 文件名 | 版本 | 覆盖范围 | 用途与优先级 | 出处 |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        L.append("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |")
    L += [
        "",
        "## 三、已知源数据问题与处理",
        "",
        "- 国标2013：源文件表 L.2 的 011102002、011102003 两行和表 L.8 的 011108002、011108003 两行，名称上下对调"
        "（源文件把块料写在 002、拼碎石材写在 003）。"
        f"已在《{k8_title}》勘误改正（据通行版本，待对照原书核实）：改正后 011102002「拼碎石材楼地面」、"
        "011102003「块料楼地面」、011108002「拼碎石材零星项目」、011108003「块料零星项目」，与浙江2025 这两组编码的名称一致。"
        f"《{k9_title}》已按改正后的名称判定同名、异名；出处行号仍是源文件行号。",
        "- 国标2013：源文件第 1473 行（表 J.2 编码 010902004 的工作内容）写作「雨水算子安装」，是「雨水箅子安装」的识别错字，"
        f"已在《{k8_title}》勘误改正（据通行版本，待对照原书核实）。",
        "- 浙江2025：码表 Z010506031 的项目特征写作「螺纹套简种类」，疑为「螺纹套筒种类」，本库照录码表未改，按「套筒」检索不到该行"
        "（可检索「螺纹套」）。这是浙江2025 码表源数据（引擎数据文件 gb50854_zj2025.yaml）的问题，需在码表源中另行修正后重新生成本库编码表。",
    ]
    text = "\n".join(L) + "\n"
    (out / K0_NAME).write_bytes(text.encode("utf-8"))
    print(f"K0 写出：{K0_NAME}  字 {len(text)}  行 {text.count(chr(10))}  字节 {len(text.encode('utf-8'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
