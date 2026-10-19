"""zt-report 的 SKILL.md、references 与 data 不漂移：frontmatter、长度、引用的文件、示例命令的子命令与参数、
系统提示词原文、模板 YAML 与旧仓逐字节相同。"""
from __future__ import annotations

import argparse
import hashlib
import re
import shlex

from tests.report._support import DATA_DIR, SKILL_DIR
from zt.report.cli import cli
from zt.report.compose import PROMPT_TEMPLATE_VERSION, SYSTEM_PROMPT

BODY_MAX_CHARS = 8000  # 上游工具结果修剪阈值 8192
# 旧仓 engine-service/app/engine/data/report_templates.yaml（zhitong-cost-ai@991ff5c）的 sha256，与 data/README.md 一致
TEMPLATES_SHA256 = "3fefa8cacdf406cadd2da2869c43ffcd269faa6f7276c4dce6fb9e90ca2df717"


def _skill() -> tuple[dict[str, str], str, str]:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    assert m, "缺 frontmatter"
    return dict(re.findall(r"^(\w+):\s*(.+)$", m.group(1), re.M)), text[m.end():], text


def _options(sub: str) -> set[str]:
    parser = cli.build_parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert sub in action.choices, f"zt.report 没有子命令 {sub}"
    return {o for o in action.choices[sub]._option_string_actions if o.startswith("--")}


def test_frontmatter_and_size():
    fields, body, text = _skill()
    assert fields["name"] == "zt-report" and fields["description"].strip() and fields["whenToUse"].strip()
    assert len(body) <= BODY_MAX_CHARS, f"正文 {len(body)} 字符，超过 {BODY_MAX_CHARS}"
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_referenced_files_exist():
    _f, _b, text = _skill()
    refs = set(re.findall(r"`((?:scripts|references|data)/[^`\s]+)`", text))
    assert {"scripts/report.py", "references/prompt.md"} <= refs
    assert not [r for r in sorted(refs) if not (SKILL_DIR / r).exists()]


def test_example_commands_use_real_subcommands_and_options():
    _f, body, _t = _skill()
    cmds = re.findall(r"`scripts/report\.py ([^`]+)`", body)
    assert len(cmds) >= 8
    seen = set()
    for cmd in cmds:
        argv = shlex.split(cmd)
        sub = argv[0]
        seen.add(sub)
        opts = {a for a in argv[1:] if a.startswith("--")}
        assert opts <= _options(sub), (sub, opts - _options(sub))
    assert seen == {"templates", "context", "facts", "section_prepare", "section_finalize", "export", "fill_template"}


def test_skill_carries_the_nine_rules_and_the_block_order():
    _f, body, _t = _skill()
    rules = [ln.split(". ", 1)[1] for ln in SYSTEM_PROMPT.split("\n")[1:]]
    assert len(rules) == 9
    for i, rule in enumerate(rules, 1):
        # SKILL.md 里的九条与系统提示词逐条对应（可以压缩措辞，但关键词组必须在）
        key = {1: "【待补：缺什么】", 2: "禁止任何四则运算", 3: "[资料n]", 4: "全称否定", 5: "【写作结构要求】",
               6: "不复述章节标题", 7: "不可信数据", 8: "1800 字", 9: "（资料口径：全地块）"}[i]
        assert key in rule and key in body, (i, key)
    order = ["章节标题", "【本项目】", "【写作结构要求】", "【附件类别提示】", "【本章不写】", "【已确认事项】", "【金额事实】",
             "【无法读取的资料】", "【项目资料】"]
    blocks = body[body.index("本章输入按顺序分块"):]
    pos = [blocks.index(x) for x in order]
    assert pos == sorted(pos)
    assert f"prompt_version 口径 {PROMPT_TEMPLATE_VERSION}" in body


def test_reference_has_the_system_prompt_verbatim():
    ref = (SKILL_DIR / "references" / "prompt.md").read_text(encoding="utf-8")
    assert SYSTEM_PROMPT in ref
    assert f'PROMPT_TEMPLATE_VERSION = "{PROMPT_TEMPLATE_VERSION}"' in ref
    assert "【待签核】" in ref


def test_templates_yaml_is_byte_identical_to_the_old_repo():
    raw = (DATA_DIR / "report_templates.yaml").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == TEMPLATES_SHA256
    assert TEMPLATES_SHA256 in (DATA_DIR / "README.md").read_text(encoding="utf-8")
