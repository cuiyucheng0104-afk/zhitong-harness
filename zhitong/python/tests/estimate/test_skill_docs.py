"""zt-estimate：SKILL.md 约定、references 与代码同源、签核状态如实写出、薄脚本可运行。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

from zt.estimate import extract as ex
from zt.estimate import policy
from zt.estimate.cli import cli

PYTHON_ROOT = Path(__file__).resolve().parents[2]
SKILL = PYTHON_ROOT.parent / "skills" / "zt-estimate"
BODY_MAX = 8000  # 上游工具结果修剪阈值 8192 留余量（CONVENTIONS「Skill」）


def _split(path: Path) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", path.read_text(encoding="utf-8"), flags=re.S)
    assert m, f"{path} 缺 frontmatter"
    return yaml.safe_load(m.group(1)), m.group(2)


def test_skill_md_frontmatter_budget_and_commands():
    meta, body = _split(SKILL / "SKILL.md")
    assert meta["name"] == "zt-estimate" and meta["description"].strip() and meta.get("whenToUse", "").strip()
    assert len(body) <= BODY_MAX, f"正文 {len(body)} 字符，超过 {BODY_MAX}"
    for rel in re.findall(r"`(scripts/[\w.]+\.py)", body) + re.findall(r"`(references/[^`]+)`", body):
        assert (SKILL / rel).is_file(), f"引用了不存在的 {rel}"
    used = set(re.findall(r"zt\.estimate\.cli (\w+)", body))
    assert used == set(cli._commands), f"SKILL.md 的子命令与 CLI 不一致：{sorted(used ^ set(cli._commands))}"


def test_skill_states_the_fee_rules_signoff_honestly():
    fee = json.loads((PYTHON_ROOT / "zt" / "estimate" / "data" / "fee_rules_zj2018.json").read_text("utf-8"))
    assert fee["signoff_kind"] == "owner_release", "数据文件的签核状态不能被改成造价员已签"
    body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "owner_release" in body and "CLOSURE_KNOWN_GAPS" in body and "勘察设计费" in body


def test_extract_reference_is_generated_from_the_code():
    pol = policy.load_policy("gsyz_v1")
    text = ex.instructions(ex.cell_hint_specs("gsyz_v1", pol), policy.extract_checks(pol),
                           bool(policy.slot_cells(pol)))
    ref = next((SKILL / "references").glob("*.md")).read_text(encoding="utf-8")
    assert ex.ESTIMATE_PROMPT_VERSION in ref and text in ref, "改了抽取说明或策略，references 要同步"


def test_thin_script_runs_template(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(PYTHON_ROOT)}
    proc = subprocess.run([sys.executable, str(SKILL / "scripts" / "estimate.py"), "template"],
                          capture_output=True, cwd=tmp_path, env=env, check=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    body = json.loads(proc.stdout.decode("utf-8"))
    assert body["status"] == "ok" and len(body["data"]["required_inputs"]) == 11
