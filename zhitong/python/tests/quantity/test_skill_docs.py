"""zt-quantity：SKILL.md 约定、references 与代码同源、薄脚本可运行。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

from zt.quantity import prompt as qp
from zt.quantity.cli import cli

PYTHON_ROOT = Path(__file__).resolve().parents[2]
SKILL = PYTHON_ROOT.parent / "skills" / "zt-quantity"
BODY_MAX = 8000  # 上游工具结果修剪阈值 8192 留余量（CONVENTIONS「Skill」）
FIXTURES = Path(__file__).parent / "fixtures"


def _split(path: Path) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", path.read_text(encoding="utf-8"), flags=re.S)
    assert m, f"{path} 缺 frontmatter"
    return yaml.safe_load(m.group(1)), m.group(2)


def test_skill_md_frontmatter_budget_and_commands():
    meta, body = _split(SKILL / "SKILL.md")
    assert meta["name"] == "zt-quantity" and meta["description"].strip() and meta.get("whenToUse", "").strip()
    assert len(body) <= BODY_MAX, f"正文 {len(body)} 字符，超过 {BODY_MAX}"
    for rel in re.findall(r"`(scripts/[\w.]+\.py)", body) + re.findall(r"`(references/[^`]+)`", body):
        assert (SKILL / rel).is_file(), f"引用了不存在的 {rel}"
    used = set(re.findall(r"scripts/quantity\.py (\w+)", body))
    assert used == set(cli._commands), f"SKILL.md 的子命令与 CLI 不一致：{sorted(used ^ set(cli._commands))}"
    assert qp.QUANTITY_PROMPT_VERSION in body, "SKILL.md 写明的提示词版本要和代码一致"


def test_prompt_reference_is_generated_from_the_code():
    ref = next((SKILL / "references").glob("*.md")).read_text(encoding="utf-8")
    assert qp.QUANTITY_PROMPT_VERSION in ref
    assert qp.SYSTEM_TEMPLATE in ref and qp.USER_TEMPLATE in ref, "改了提示词措辞，references 要同步"


def test_thin_script_runs_prepare(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(PYTHON_ROOT)}
    case = FIXTURES / "设计说明-案例.xlsx"
    proc = subprocess.run([sys.executable, str(SKILL / "scripts" / "quantity.py"), "prepare",
                           "--root", str(case.parent), "--files", case.name],
                          capture_output=True, cwd=tmp_path, env=env, check=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    body = json.loads(proc.stdout.decode("utf-8"))
    assert body["status"] == "ok" and body["data"]["prompt_version"] == qp.QUANTITY_PROMPT_VERSION
