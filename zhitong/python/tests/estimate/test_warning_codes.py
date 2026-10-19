# 来源：engine-service/tests/test_warning_codes.py（zhitong-cost-ai@991ff5cd，W4 迁入 zt；改动见「zt 改动」注释）
"""warning code 单一真源（O-13）。

本文件的核心是**一条扫源码的测试**：概算链路的模块里发出的每一个 code，
只要没在 `warning_codes.WARNING_CODES` 里登记，就红。

为什么用源码扫描而不是"各模块改用常量"：常量只防写错已有的码，防不住
**新加**一个码却忘了登记 —— 而后者正是实际发生过的事（前端 WARNING_CODE_CN
缺 8 个码，结果页把英文码当分组标题渲染给造价员看）。扫描两者都拦得住。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from zt.estimate import warning_codes as wc

# zt 改动：扫 zt/estimate 的模块（旧版扫 app/engine/estimate_*.py、fee_rules.py、app/api/estimate.py 与报表管理）
PKG = Path(__file__).resolve().parents[2] / "zt" / "estimate"
SOURCES = sorted(p for p in PKG.glob("*.py") if p.name not in ("warning_codes.py", "__init__.py"))

# 两种发码写法：dict 字面量 `"code": "xxx"` 与 fee_rules 的 `_warn("xxx", ...)`
_DICT_CODE = re.compile(r'"code":\s*"([a-z_]+)"')
_WARN_CALL = re.compile(r'_warn\(\s*\n?\s*"([a-z_]+)"', re.MULTILINE)
# unresolved 的 reason 走 _drop("xxx", ...)
_DROP_REASON = re.compile(r'_drop\(\s*"([a-z_]+)"')


def _emitted() -> dict[str, set[str]]:
    """→ {code: {发它的文件名}}。"""
    out: dict[str, set[str]] = {}
    for p in SOURCES:
        src = p.read_text(encoding="utf-8")
        for rx in (_DICT_CODE, _WARN_CALL):
            for code in rx.findall(src):
                out.setdefault(code, set()).add(p.name)
    return out


def _emitted_reasons() -> set[str]:
    src = (PKG / "suggest.py").read_text(encoding="utf-8")
    return set(_DROP_REASON.findall(src))


def test_every_emitted_code_is_registered():
    """发得出来就必须登记得上。漏一个，结果页就把英文码给造价员看。"""
    unregistered = {c: sorted(f) for c, f in _emitted().items() if c not in wc.WARNING_CODES}
    assert not unregistered, f"这些 code 发出来了却没在 warning_codes.py 登记：{unregistered}"


def test_every_emitted_unresolved_reason_is_registered():
    unregistered = _emitted_reasons() - set(wc.UNRESOLVED_REASONS)
    assert not unregistered, f"这些 unresolved reason 没登记：{sorted(unregistered)}"


def test_the_scanner_actually_finds_codes():
    """扫描器自己不许静默失效 —— 正则写坏了会让上面两条永远全绿。"""
    found = _emitted()
    assert len(found) >= 30, f"只扫到 {len(found)} 个 code，扫描正则大概率坏了：{sorted(found)}"
    # 两种写法各至少命中一个已知的码
    assert "fee_bases_absent" in found          # dict 字面量写法
    assert "fee_rules_unsigned" in found        # _warn() 写法
    assert len(_emitted_reasons()) >= 4


def test_every_registered_code_has_chinese_and_severity():
    """22 个码全部有中文（本轮实测已到 32 个）。"""
    assert len(wc.WARNING_CODES) >= 22
    for code, meta in {**wc.WARNING_CODES, **wc.UNRESOLVED_REASONS}.items():
        assert meta["label"] and meta["hint"], code
        assert meta["severity"] in ("warn", "info"), code
        # label/hint 必须是中文（前端直接渲染，英文码当标题正是本条在修的缺陷）
        assert re.search(r"[一-鿿]", meta["label"]), f"{code} 的中文名是空的"


def test_no_registered_code_is_dead():
    """登记了却没人发 = 字典和实现漂移的另一半，同样要拦。"""
    emitted = set(_emitted())
    # zt 改动：compute 拒算时 CLI 用闸的码出一条 error 级告警（GateRejected.code），不是字典字面量
    from zt.estimate import gates
    emitted |= set(gates.ORDER)
    dead = sorted(set(wc.WARNING_CODES) - emitted)
    assert not dead, f"这些 code 登记了但源码里没人发（实现改了、字典没跟）：{dead}"


def test_describe_and_payload():
    assert wc.describe("fee_rules_unsigned")["severity"] == "warn"
    assert wc.describe("no_rule")["severity"] == "warn"
    assert wc.describe("no_such_code") is None
    p = wc.payload()
    assert set(p) == {"warnings", "unresolved_reasons"}
    # 出口必须是副本：调用方原地改不该污染模块常量
    p["warnings"].pop("fee_rules_unsigned")
    assert "fee_rules_unsigned" in wc.WARNING_CODES


def test_template_endpoint_ships_the_dictionary():
    # zt 改动：经 template 子命令的服务函数（旧版经 GET /engine/estimate/template）
    from zt.estimate import service

    body = service.template("gsyz_v1")
    d = body["code_dictionary"]
    assert d["warnings"]["fee_cell_dual_source"]["label"]
    assert d["unresolved_reasons"]["no_rule"]["label"]


@pytest.mark.parametrize("code", ["deviation_unsupported"])
def test_removed_codes_are_not_resurrected(code):
    """O-22 删掉的码不该重新出现在实现或字典里。"""
    assert code not in wc.WARNING_CODES
    assert code not in _emitted()
