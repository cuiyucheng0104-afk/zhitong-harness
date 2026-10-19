"""tests/report 共用的小工具。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from zt.report.templates import load_templates
from zt.report.templates import resolve_section as _resolve

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SKILL_DIR = Path(__file__).resolve().parents[3] / "skills" / "zt-report"
DATA_DIR = SKILL_DIR / "data"


@lru_cache(maxsize=1)
def templates() -> tuple:
    """源码树里的模板（只读一次）。"""
    return tuple(load_templates(DATA_DIR))


def resolve_section(template_code: str, section_code: str) -> dict:
    """与旧仓 ``app.api.report_templates.resolve_section`` 同用法：按模板码 + 章节码取章节定义。"""
    return _resolve(list(templates()), template_code, section_code)
