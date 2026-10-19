"""zt-reconcile / zt-indicator / zt-tk 三个 skill：SKILL.md 约定、薄脚本可运行、共用告警码表与登记表一致。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.costsheet.fixtures.golden import FIXTURES
from zt.costsheet.warning_codes import COSTSHEET_WARNING_CODES

PYTHON_ROOT = Path(__file__).resolve().parents[2]
SKILLS = PYTHON_ROOT.parent / "skills"
BODY_MAX = 8000  # 上游工具结果修剪阈值 8192 留余量（CONVENTIONS「Skill」）


def _split(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, flags=re.S)
    assert m, f"{path} 缺 frontmatter"
    return yaml.safe_load(m.group(1)), m.group(2)


@pytest.mark.parametrize("name", ["zt-reconcile", "zt-indicator", "zt-tk"])
def test_skill_md_frontmatter_and_budget(name):
    meta, body = _split(SKILLS / name / "SKILL.md")
    assert meta["name"] == name and meta["description"].strip() and meta.get("whenToUse", "").strip()
    assert len(body) <= BODY_MAX, f"{name} 正文 {len(body)} 字符，超过 {BODY_MAX}"
    assert "../_shared/costsheet/告警码.md" in body
    for rel in re.findall(r"`(scripts/[\w.]+\.py)", body):
        assert (SKILLS / name / rel).is_file(), f"{name} 引用了不存在的 {rel}"


def test_shared_warning_code_table_lists_every_registered_code():
    text = (SKILLS / "_shared" / "costsheet" / "告警码.md").read_text(encoding="utf-8")
    listed = set(re.findall(r"^\| `([a-z_]+)` \| (?:info|warn|error) \|", text, flags=re.M))
    assert listed == set(COSTSHEET_WARNING_CODES), sorted(listed ^ set(COSTSHEET_WARNING_CODES))


@pytest.mark.parametrize("script,args", [
    ("zt-reconcile/scripts/reconcile.py", ["run", "--submitted", str(FIXTURES / "送审-计价表.xlsx"),
                                           "--approved", str(FIXTURES / "审定-计价表.xlsx")]),
    ("zt-reconcile/scripts/probe.py", ["probe", "--files", str(FIXTURES / "送审-计价表.xlsx")]),
    ("zt-indicator/scripts/indicator.py", ["run", "--files", str(FIXTURES / "指标-计价表.xlsx"),
                                           "--gross-area", "5000"]),
    ("zt-tk/scripts/tk.py", ["detect", "--files", str(FIXTURES / "送审-异常样例.xlsx")]),
])
def test_thin_scripts_run(script, args, tmp_path):
    env = {**os.environ, "PYTHONPATH": str(PYTHON_ROOT)}
    proc = subprocess.run([sys.executable, str(SKILLS / script), *args], capture_output=True, cwd=tmp_path,
                          env=env, check=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert json.loads(proc.stdout.decode("utf-8"))["status"] == "ok"
