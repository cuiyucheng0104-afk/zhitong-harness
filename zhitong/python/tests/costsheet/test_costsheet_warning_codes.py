# 来源：engine-service/tests/test_costsheet_warning_codes.py（zhitong-cost-ai@991ff5cd）
"""计价表链路告警码单一真源（costsheet_warnings.COSTSHEET_WARNING_CODES；issue #724）。

扫源码：计价表解析、接线层（zt.costsheet.service）与三个调用方里发出的每一个告警码，只要没在登记表里，就红。
（仿 test_warning_codes.py：常量只防写错已有的码，防不住**新加**一个码却忘了登记。）
"""
from __future__ import annotations

import re
from pathlib import Path

from zt.costsheet import warning_codes as cw
from zt.common.envelope import WarningLevel

ZT = Path(__file__).resolve().parents[2] / "zt"
SOURCES = [
    ZT / "costsheet" / "parser.py",
    ZT / "costsheet" / "xlsx_tolerant.py",
    ZT / "costsheet" / "service.py",
    ZT / "reconcile" / "engine.py",
    ZT / "tk" / "engine.py",
    ZT / "indicator" / "engine.py",
]
# 两种发码写法：warn("xxx", …) / _warn("xxx", …)（indicator_engine 的局部包装）与 dict 字面量 "code": "xxx"。
# ⚠ \bwarn 匹配不到 _warn（下划线是单词字符，没有词边界）—— 只认 \bwarn 时 _warn 发的码整批逃出本闸
_WARN_CALL = re.compile(r'(?:\b|_)warn\(\s*\n?\s*"([a-z_]+)"', re.MULTILINE)
_DICT_CODE = re.compile(r'"code":\s*"([a-z_]+)"')


def _emitted() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for p in SOURCES:
        src = p.read_text(encoding="utf-8")
        for rx in (_WARN_CALL, _DICT_CODE):
            for code in rx.findall(src):
                out.setdefault(code, set()).add(p.name)
    return out


def test_scan_actually_finds_codes():
    """负控：扫描器自己得扫得到东西，否则下一条恒绿。"""
    found = _emitted()
    assert {"column_ambiguous", "sheet_skipped_has_items", "stylesheet_patched",
            "file_unpriced", "amounts_identical_suspect",
            # WS08-B：_warn 包装发的码、投控基准与对账算术的码也得扫得到
            "area_missing", "files_failed", "fee_total_unavailable", "fee_total_unreadable",
            "baseline_rows_invalid",
            "baseline_coverage_low", "calc_error_rows",
            # zt：本机不转换 .xls
            "xls_unsupported"} <= set(found)


def test_every_emitted_code_is_registered():
    unregistered = {c: sorted(f) for c, f in _emitted().items() if c not in cw.COSTSHEET_WARNING_CODES}
    assert not unregistered, f"这些 code 发出来了却没在 costsheet_warnings.py 登记：{unregistered}"


def test_registry_entries_are_well_formed():
    for code, meta in cw.COSTSHEET_WARNING_CODES.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code)
        assert meta["level"] in {lv.value for lv in WarningLevel}, f"{code} 级别不在 C2 的 info/warn/error 里"
        assert meta["label"] and meta["hint"]


def test_warn_helper_rejects_unregistered_code():
    import pytest
    with pytest.raises(KeyError):
        cw.warn("not_a_registered_code", "x")
