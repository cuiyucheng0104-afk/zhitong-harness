#!/usr/bin/env python3
"""一键重建知识库「清单编码类」结构化资料 K0–K9（11 个 md），并与 expected_manifest.json 逐文件核对 sha256。

顺序（K0 要列出其余文件、现数 K7/K9 的行，所以最后生成）：
  gen_zj2025.py（K1–K5，6 份） → gen_rules.py（K6） → gen_map.py（K7，另出 xlsx 审签件到 local_only/）
  → gen_2013.py（K8、K9） → gen_k0.py（K0）
生成时间按 expected_manifest.json 的 pins 固定，所以同一源 + 同一依赖版本 → 逐字节相同。

受控源全部在仓里或可由仓复现：
  · 浙江2025 码表、quantity_rules（及引擎 quantity_rules.py）：git show 33601ca8:<path>
    （33601ca8 在 origin/main 上、不在 dev 的祖先链上；--single-branch / 浅克隆取不到，脚本开头先查、给出补取命令）
  · 国标2013：sources/GB50854-2013.md（原件只删去第 43 行版权页定价）
  · SKILL.md 映射表、clause_llm.py 的 _MAPPING_REF：sources/k7_sources_snapshot.json

用法：
  python3 build_all.py [--out DIR] [--local DIR] [--repo <仓根>] [--check] [--force]
    --out    默认 out/（已 gitignore）。目录里已有 .md 时拒绝执行（K0 按目录列文件，旧产物会混进来），--force 先清掉 .md
    --local  默认 local_only/（xlsx 审签件、各生成器自检 JSON、check_kb 报告；已 gitignore，不上传、不入仓）
    --check  生成并核对 sha256 后，再跑 check_kb.py 七条门槛（报告写 --local）
退出码：0 = 11 个文件与登记逐字节一致（--check 时还要七条全过）；1 = 不一致或门槛不过；2 = 参数 / 前置不对
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from kbsrc import SNAPSHOT_REPO, source_available

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "expected_manifest.json"
SRC_COMMIT = "33601ca8"   # 受控源 commit：origin/main 上 #785 的合并提交，不在 dev 的祖先链上


def commit_reachable(repo: str) -> bool:
    """受控源可用：快照目录里有源文件，或 git 里取得到 SRC_COMMIT。"""
    return source_available(repo, SRC_COMMIT, "engine-service/app/engine/data/gb50854_zj2025.yaml")


def run(cmd: list[str], env_extra: dict[str, str] | None = None) -> None:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    print("$", " ".join(Path(c).name if i == 1 else c for i, c in enumerate(cmd)), flush=True)
    r = subprocess.run(cmd, env=env)
    if r.returncode != 0:
        raise SystemExit(f"✗ {Path(cmd[1]).name} 退出码 {r.returncode}（生成器自检不过或源不对），停止")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--local", default=str(HERE / "local_only"))
    ap.add_argument("--repo", default=str(SNAPSHOT_REPO))
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--partial", action="store_true",
                    help="只生成并核对 K1–K5、K8、K9（码表 + 国标全文链）；K0/K6/K7 依赖 33601ca8 版 quantity_rules.yaml，"
                         "快照里的现行版规则数已变，见 README「迁入后的差异」。不跑 check_kb（它要求 11 个文件齐全）")
    a = ap.parse_args()

    if not commit_reachable(a.repo):
        print(f"✗ {a.repo} 下没有受控源快照，也取不到 commit {SRC_COMMIT}；用 --repo 指向 sources/repo-snapshot。",
              file=sys.stderr)
        return 2
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pins = man["pins"]
    out, local = Path(a.out), Path(a.local)
    out.mkdir(parents=True, exist_ok=True)
    local.mkdir(parents=True, exist_ok=True)
    old = sorted(out.glob("*.md"))
    if old and not a.force:
        print(f"✗ {out} 里已有 {len(old)} 个 .md；换空目录，或加 --force 先清掉", file=sys.stderr)
        return 2
    for p in old:
        p.unlink()

    py = sys.executable
    run([py, str(HERE / "gen_zj2025.py"), "--repo", a.repo, "--out", str(out),
         "--stats", str(local / "zj2025_stats.json"), "--generated-at", pins["gen_zj2025.py"]])
    epoch = {"SOURCE_DATE_EPOCH": str(pins["gen_rules.py+gen_map.py SOURCE_DATE_EPOCH"])}
    if not a.partial:
        run([py, str(HERE / "gen_rules.py"), "--repo", a.repo, "--out", str(out),
             "--report", str(local / "K6_check.json")], epoch)
        run([py, str(HERE / "gen_map.py"), "--repo", a.repo, "--out", str(out), "--local", str(local)], epoch)
    run([py, str(HERE / "gen_2013.py"), "--repo", a.repo, "--out", str(out),
         "--stats", str(local / "gen_2013_stats.json"), "--generated-at", pins["gen_2013.py"]])
    if not a.partial:
        run([py, str(HERE / "gen_k0.py"), "--repo", a.repo, "--out", str(out), "--generated-at", pins["gen_k0.py"]])

    partial_ids = {"K1", "K2", "K3", "K4a", "K4b", "K5", "K8", "K9"}
    want = {f["name"]: f for f in man["files"] if not a.partial or f["id"] in partial_ids}
    got = {p.name: p for p in out.glob("*.md")}
    bad = 0
    print()
    for name in sorted(set(want) | set(got)):
        w, g = want.get(name), got.get(name)
        if w is None or g is None:
            print(f"✗ {name}：{'登记里没有（多出来的产物）' if w is None else '没生成出来'}")
            bad += 1
            continue
        h = hashlib.sha256(g.read_bytes()).hexdigest()
        same = h == w["sha256"]
        bad += not same
        print(f"{'✓' if same else '✗'} {w['id']:<4} {h[:16]}…  {name}", flush=True)
    print(f"\n生成 {len(got)} 个 / 登记 {len(want)} 个，sha256 不一致 {bad} 个", flush=True)
    if bad or len(got) != len(want):
        return 1
    if a.check:
        r = subprocess.run([py, str(HERE / "check_kb.py"), "--repo", a.repo, "--out", str(out),
                            "--manifest", str(local / "manifest.json"), "--report", str(local / "KB-GATE-校验报告.md"),
                            "--json", str(local / "KB-GATE-校验结果.json")])
        if r.returncode != 0:
            return 1
    print("RESULT PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
