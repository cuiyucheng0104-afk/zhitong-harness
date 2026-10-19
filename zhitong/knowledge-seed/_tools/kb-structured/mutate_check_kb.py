#!/usr/bin/env python3
"""check_kb.py 变异测试：把 out/ 复制到临时目录，每次注入一种缺陷，确认对应门槛报 FAIL。
不改动真实 out/、manifest.json。结果写 local_only/check_kb_mutation.json。

先跑两组对照（不注入缺陷）必须 PASS —— 否则「每个变异都被拦下」可能只是因为基线本来就不过（CLAUDE.md §5.2）：
  · 对照 1：不给 --categories（仓内复现口径，categoryId 记 null）
  · 对照 2：给一份形态合法的假类目配置，manifest 里的 categoryId 必须逐个等于配置值
变异函数可以返回额外的 check_kb 命令行参数（用于 --categories 类的变异）。

用法：python3 mutate_check_kb.py [--out DIR]     # 默认 out/（先跑 build_all.py 生成）
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def f(d: Path, key: str) -> Path:
    hit = [p for p in d.iterdir() if key in p.name]
    assert len(hit) == 1, (key, hit)
    return hit[0]


def edit(p: Path, fn):
    t = p.read_text(encoding="utf-8")
    t2 = fn(t)
    assert t2 != t, f"变异没生效：{p.name}"
    p.write_text(t2, encoding="utf-8")


def once(s: str, a: str, b: str) -> str:
    assert a in s, a
    return s.replace(a, b, 1)


def line_edit(p: Path, n: int, fn):
    ls = p.read_text(encoding="utf-8").split("\n")
    new = fn(ls[n - 1])
    assert new != ls[n - 1]
    ls[n - 1] = new
    p.write_text("\n".join(ls), encoding="utf-8")


MUT = [
    ("G1", "K1 名称改一个字", lambda d: edit(f(d, "土石方地基"), lambda t: once(t, "| 挖单独土方 |", "| 挖单独土方X |"))),
    ("G1", "K2 删一行", lambda d: edit(f(d, "混凝土金属木结构"), lambda t: re.sub(r"\n\| 010502013 \|[^\n]*", "", t, count=1))),
    ("G1", "K3 特征少一槽", lambda d: edit(f(d, "门窗屋面"), lambda t: once(t, "1.门洞口尺寸；2.门类型；", "2.门类型；"))),
    ("G2", "K6 「」名称写错", lambda d: edit(f(d, "易混淆"), lambda t: once(t, "011404002「天棚喷刷涂料」", "011404002「天棚抹灰」"))),
    ("G2", "K7 编码改成码表没有的", lambda d: edit(f(d, "设计做法"), lambda t: once(t, "| 010807003 | 金属百叶窗 |", "| 010807009 | 金属百叶窗 |"))),
    ("G2", "K9 国标2013名称改错", lambda d: edit(f(d, "同码异名"), lambda t: once(t, "| 010101003 | 挖沟槽土方 |", "| 010101003 | 挖基坑土方 |"))),
    ("G2", "K7 原写编码的名称旁注写错", lambda d: edit(f(d, "设计做法"), lambda t: once(t, "原写 010903004，该码浙江2025名称为「墙面变形缝」", "原写 010903004，该码浙江2025名称为「屋面变形缝」"))),
    ("G2", "K0 疑点陈述改错", lambda d: edit(f(d, "使用说明"), lambda t: once(t, "写作「雨水算子安装」", "写作「雨水斗安装」"))),
    ("G3", "K8 正文改一个字", lambda d: line_edit(f(d, "规范全文"), 511, lambda s: s + "。")),
    ("G3", "K8 勘误行恢复原错字", lambda d: edit(f(d, "规范全文"), lambda t: once(t, "4. 嵌缝材料种类 5. 钢筋规格", "4. 拒缝材料种类 5. 钢筋规格"))),
    # 变异样本：故意注入一个伪金额，验证 G4 能拦下（样本只存在于临时目录，不是数据）
    ("G4", "K6 加金额", lambda d: edit(f(d, "易混淆"), lambda t: once(t, "## 使用说明", "## 使用说明\n\n参考价 12元"))),
    ("G5", "K7 单元格未转义 |", lambda d: edit(f(d, "设计做法"), lambda t: once(t, "| 金属百叶窗 | m² |", "| 金属|百叶窗 | m² |"))),
    ("G5", "K5 加 BOM", lambda d: f(d, "拆除与措施").write_bytes(b"\xef\xbb\xbf" + f(d, "拆除与措施").read_bytes())),
    ("G5", "K6 单元格内换行", lambda d: edit(f(d, "易混淆"), lambda t: once(t, "踢脚按 0111-05「踢脚线」列项，计量单位 m |", "踢脚按 0111-05「踢脚线」列项，\n计量单位 m |"))),
    ("G6", "K7 出处置空", lambda d: edit(f(d, "设计做法"), lambda t: once(t, "| — | SKILL.md 第126行 |", "| — |  |"))),
    ("G6", "K6 出处行号偏一行", lambda d: edit(f(d, "易混淆"), lambda t: once(t, "consistency_rules[skirting] 第76行", "consistency_rules[skirting] 第77行"))),
    ("G6", "K6 应列展开漏一个码", lambda d: edit(f(d, "易混淆"), lambda t: once(t, "、011105006「金属踢脚线」（m）", ""))),
    ("G7", "out/ 多一个文件", lambda d: (d / "多余.md").write_text("> x\n", encoding="utf-8")),
    ("G7", "K0 少列一个文件", lambda d: edit(f(d, "使用说明"), lambda t: re.sub(r"\n\| K5 \|[^\n]*", "", t, count=1))),
    # PR #788 评审补的四种：本机路径进成品、长数字 id 进成品、文件名前缀与目标类目不一致、类目配置坏
    ("G5", "K7 文件头写回本机路径", lambda d: edit(f(d, "设计做法"), lambda t: once(t, "内部方法论 SKILL.md", "内部方法论 ~/Desktop/x/SKILL.md"))),
    # 变异样本：19 位假 id（不是任何环境的真 id），验证 G5 能拦下运行时 id 进成品
    ("G5", "K6 写进 19 位长数字 id", lambda d: edit(f(d, "易混淆"), lambda t: once(t, "## 使用说明", "## 使用说明\n\n类目 1234567890123456789"))),
    ("G7", "K6 文件名前缀改成根类目（K0 同步改名）", lambda d: rename_prefix(d, "易混淆", "【清单·房屋建筑】", "【清单】")),
    ("G7", "--categories 少一个键", lambda d: cats(d, {"清单": "1000000000000000001"})),
    ("G7", "--categories id 不是数字", lambda d: cats(d, {"清单": "1000000000000000001", "清单/房屋建筑": "房屋建筑"})),
    # 名称对调勘误（用户 2026-10-01 裁定）补的四种：K8 / K9 退回源文件的错误写法、勘误表漏登记、改动与描述不符
    ("G3", "K8 对调行恢复成源错误写法", lambda d: edit(f(d, "规范全文"), lambda t: once(t, "| 011102003 | 块料楼地面 |", "| 011102003 | 拼碎石材楼地面 |"))),
    ("G2", "K9 011102003 名称改回旧名（按源文件错误写法判异名、统计同步）", lambda d: k9_old_name(d)),
    ("G3", "K8 勘误表少登记一条（行数与条数同步，偏移不变）", lambda d: k8_drop_erratum(d, "源文件第 1613 行")),
    ("G3", "K8 对调行改成与勘误描述不符的名称", lambda d: edit(f(d, "规范全文"), lambda t: once(t, "| 011108003 | 块料零星项目 |", "| 011108003 | 块料零星项目X |"))),
]


def k9_old_name(d: Path) -> None:
    """把 K9 的 011102003 写回源文件的错误名称（= 生成器不用勘误后正文时会产出的那一行），并同步文件头和节标题的异名计数 ——
    这样「是否同名」「统计」两条核对都照样过，G2 要红靠「国标2013 名称按源 + 已核勘误比对」
    （另有 K0「K9 已按改正后的名称判定」这条陈述核对也会红；G6 按改正后行定位也会红）。"""
    def fn(t: str) -> str:
        t = once(t, "| 011102003 | 块料楼地面 | m² | 011102003 | 块料楼地面 | m² | 同名 |",
                 "| 011102003 | 拼碎石材楼地面 | m² | 011102003 | 块料楼地面 | m² | 异名 |")
        m = re.search(r"同 9 位编码 (\d+) 个，其中名称不同 (\d+) 个", t)
        n = int(m.group(2))
        t = t.replace(f"同 9 位编码 {m.group(1)} 个，其中名称不同 {n} 个", f"同 9 位编码 {m.group(1)} 个，其中名称不同 {n + 1} 个", 1)
        return once(t, f"## 一、同 9 位编码（{m.group(1)} 个，其中名称不同 {n} 个）", f"## 一、同 9 位编码（{m.group(1)} 个，其中名称不同 {n + 1} 个）")
    edit(f(d, "同码异名"), fn)


def k8_drop_erratum(d: Path, tag: str) -> None:
    """从 K8 文件头勘误表删去一条（换成一行普通引用块，文件头行数不变 → 行号偏移不变），条数同步减 1；正文不动。"""
    def fn(t: str) -> str:
        ls = t.split("\n")
        hit = [i for i, s in enumerate(ls) if s.startswith("> - " + tag)]
        assert len(hit) == 1, hit
        ls[hit[0]] = "> 备注：（无）"
        t = "\n".join(ls)
        m = re.search(r"勘误与处理表（共 (\d+) 处", t)
        return t.replace(m.group(0), f"勘误与处理表（共 {int(m.group(1)) - 1} 处", 1)
    edit(f(d, "规范全文"), fn)


def rename_prefix(d: Path, key: str, old: str, new: str) -> None:
    """改文件名前缀，并把 K0 清单里的文件名同步改掉 —— 这样 K0「所列文件 = manifest」那条照样过，
    G7 要红只能靠「编号 → 类目」与「文件名前缀 → 类目」两路核对（语义回退那条核对后，本变异应转绿）。"""
    src = f(d, key)
    dst = src.name.replace(old, new, 1)
    assert dst != src.name
    edit(f(d, "使用说明"), lambda t: t.replace(src.name, dst))
    src.rename(d / dst)


FAKE_CATS = {"清单": "1000000000000000001", "清单/房屋建筑": "1000000000000000002"}   # 形态合法的假 id


def cats(d: Path, body) -> list[str]:
    """在 out/ 旁边写一份类目配置（不在 out/ 里，免得 G7 把它当多余文件），返回要追加的命令行参数。"""
    p = d.parent / "categories.json"
    p.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return ["--categories", str(p)]


def run_check(td: Path, o: Path, extra: list[str]) -> tuple[subprocess.CompletedProcess, dict]:
    r = subprocess.run([sys.executable, str(HERE / "check_kb.py"), "--out", str(o), "--manifest", str(td / "m.json"),
                        "--report", str(td / "r.md"), "--json", str(td / "r.json"), *extra], capture_output=True, text=True)
    res = json.loads((td / "r.json").read_text(encoding="utf-8")) if (td / "r.json").exists() else {}
    return r, res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out"))
    a = ap.parse_args()
    src_out = Path(a.out)
    if not src_out.is_dir() or not any(src_out.glob("*.md")):
        print(f"✗ {src_out} 里没有成品 .md（先跑 build_all.py）—— 0 个样本不能判「全部拦下」（铁律 8）", file=sys.stderr)
        return 2
    ok_all = True
    rows = []
    # 对照组：不注入缺陷必须全过
    for desc, extra_body in (("对照 1：不给 --categories", None), ("对照 2：给形态合法的假类目配置", FAKE_CATS)):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            o = td / "out"
            shutil.copytree(src_out, o)
            extra = cats(o, extra_body) if extra_body else []
            r, res = run_check(td, o, extra)
            ok = r.returncode == 0 and res.get("ok") is True
            if ok:
                man = json.loads((td / "m.json").read_text(encoding="utf-8"))
                want = (lambda e: FAKE_CATS[e["category"]]) if extra_body else (lambda e: None)
                ok = bool(man["files"]) and all(e["categoryId"] == want(e) for e in man["files"])
            ok_all &= ok
            rows.append({"mutation": desc, "expect": "PASS", "rc": r.returncode, "caught": None, "control_ok": ok})
            print(f"{'CONTROL-OK' if ok else 'CONTROL-BAD'} {desc} → rc={r.returncode}")
    for gate, desc, fn in MUT:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            o = td / "out"
            shutil.copytree(src_out, o)
            ret = fn(o)
            extra = ret if isinstance(ret, list) else []   # 只有 cats() 返回参数列表；write_text 等返回的数字不算
            r, res = run_check(td, o, extra)
            if not res:
                print(f"MISSED {gate} {desc} → check_kb 没写出结果 JSON（rc={r.returncode}）：{r.stderr[-200:]}")
                ok_all = False
                rows.append({"mutation": desc, "expect": gate, "failed_gates": [], "caught": False, "first_error": "无结果 JSON"})
                continue
            failed = [g for g in ("G1", "G2", "G3", "G4", "G5", "G6", "G7") if not res[g]["ok"]]
            caught = gate in failed and r.returncode == 1
            ok_all &= caught
            first = res[gate]["errors"][0] if res[gate]["errors"] else ""
            rows.append({"mutation": desc, "expect": gate, "failed_gates": failed, "caught": caught, "first_error": first[:100]})
            print(f"{'CAUGHT' if caught else 'MISSED'} {gate} {desc} → 不过门槛 {failed}；{first[:90]}")
    (HERE / "local_only").mkdir(exist_ok=True)
    (HERE / "local_only" / "check_kb_mutation.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("MUTATION", "ALL CAUGHT" if ok_all else "SOME MISSED")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
