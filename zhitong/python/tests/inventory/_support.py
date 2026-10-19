"""inventory 测试共用：加载一次 zt-project 数据，导出引擎、折算表与核查入口。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from zt.inventory.audit import check_checklist_graded as _graded
from zt.inventory.scan import load_inventory_data

DATA = load_inventory_data()
engine = DATA.engine
RULES = engine.rules
AUDIT_RULES = DATA.audit_rules
VOCAB = AUDIT_RULES.vocab
canonical = VOCAB.canonical
CHECKLIST = DATA.checklist
FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_PROJECT = FIXTURES / "sample-project"


def check_checklist_graded(files: list[dict], checklist: list[dict]) -> dict[str, Any]:
    """用真实数据目录里的折算表与冲突表跑核查。"""
    return _graded(files, checklist, AUDIT_RULES)


def check_checklist_detailed(files: list[dict], checklist: list[dict]):
    """旧五元组形状：``(missing, coverage_rate, required_total, covered, degraded_matches)``，是 graded 的投影。"""
    g = check_checklist_graded(files, checklist)
    return g["missing"], g["coverage_rate"], g["required_total"], g["covered"], g["degraded_matches"]
