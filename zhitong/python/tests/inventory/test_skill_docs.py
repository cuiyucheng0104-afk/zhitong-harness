"""三份 SKILL.md 与脚本不漂移：frontmatter、长度、引用的文件存在、示例命令的子命令和参数真实存在。"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from tests.inventory.test_skill_scripts import load_script
from zt.inventory.cli import cli as inventory_cli
from zt.textextract.cli import cli as textextract_cli

SKILLS = Path(__file__).resolve().parents[3] / "skills"
NAMES = ("zt-project", "zt-ask", "zt-archive")
BODY_MAX_CHARS = 8000  # 上游工具结果修剪阈值 8192

# 脚本 → (Cli, 固定子命令)；固定子命令的脚本调用时不写子命令
_SCRIPT_CLIS = {
    ("zt-project", "inventory"): (inventory_cli, None),
    ("zt-project", "new_project"): (load_script("zt-project", "new_project").cli, None),
    ("zt-project", "project_doc"): (load_script("zt-project", "project_doc").cli, None),
    ("zt-archive", "archive"): (load_script("zt-archive", "archive").cli, None),
    ("zt-ask", "read_doc"): (textextract_cli, "extract"),
    ("zt-ask", "find_text"): (textextract_cli, "search"),
    ("zt-ask", "check_answer"): (textextract_cli, "check-answer"),
}


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    assert m, "缺 frontmatter"
    fields = dict(re.findall(r"^(\w+):\s*(.+)$", m.group(1), re.M))
    return fields, text[m.end():]


def _options(cli, sub: str) -> set[str]:
    parser = cli.build_parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert sub in action.choices, f"{cli.prog} 没有子命令 {sub}"
    return {o for o in action.choices[sub]._option_string_actions if o.startswith("--")}


@pytest.mark.parametrize("skill", NAMES)
def test_frontmatter_and_size(skill):
    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    fields, body = _frontmatter(text)
    assert fields["name"] == skill and fields["description"].strip() and fields["whenToUse"].strip()
    assert len(body) <= BODY_MAX_CHARS, f"正文 {len(body)} 字符，超过 {BODY_MAX_CHARS}"
    assert text.endswith("\n") and not text.endswith("\n\n")


@pytest.mark.parametrize("skill", NAMES)
def test_referenced_files_exist(skill):
    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    refs = set(re.findall(r"`((?:scripts|references|templates|data)/[^`\s]+)`", text))
    refs |= set(re.findall(r"\b((?:scripts|references)/[\w./-]+\.(?:py|md))", text))
    assert refs, "SKILL.md 没有引用任何文件？"
    missing = [r for r in sorted(refs) if not (SKILLS / skill / r.rstrip("/")).exists()
               and not (SKILLS / "zt-project" / r.rstrip("/")).exists()]
    assert not missing, missing


@pytest.mark.parametrize("skill", NAMES)
def test_example_commands_use_real_subcommands_and_flags(skill):
    text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
    checked = 0
    for m in re.finditer(r"scripts/(\w+)\.py((?:\s|\\\n|[^\n`])*)", text):
        name, tail = m.group(1), m.group(2)
        key = next((k for k in _SCRIPT_CLIS if k[1] == name), None)
        assert key is not None, f"SKILL.md 里的脚本 {name}.py 没有登记到测试"
        cli, forced = _SCRIPT_CLIS[key]
        tokens = tail.replace("\\\n", " ").split()
        sub = forced or (tokens[0] if tokens and not tokens[0].startswith(("-", "<", "[")) else None)
        if sub is None or sub.startswith("|") or "<" in sub:
            continue  # 行内写 scripts/x.py `<a|b>` 之类的概述
        sub = sub.strip("`")
        if "|" in sub:
            continue
        opts = _options(cli, sub)
        flags = re.findall(r"(?<![\w-])(--[a-z][\w-]*)", tail)
        unknown = [f for f in flags if f not in opts]
        assert not unknown, f"{skill}: scripts/{name}.py {sub} 没有参数 {unknown}"
        checked += 1
    assert checked, "没有检查到任何示例命令（正则漂移？）"


def test_check_answer_command_in_zt_ask_uses_real_flags():
    text = (SKILLS / "zt-ask" / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"scripts/check_answer\.py((?:\s|\\\n|[^\n`])*)", text)
    assert m
    flags = re.findall(r"(?<![\w-])(--[a-z][\w-]*)", m.group(1))
    assert flags and set(flags) <= _options(textextract_cli, "check-answer")


def test_zt_project_documents_every_subcommand():
    text = (SKILLS / "zt-project" / "SKILL.md").read_text(encoding="utf-8")
    for needle in ("allocate", "create", "show", "draft", "scan"):
        assert re.search(rf"\b{needle}\b", text), needle
