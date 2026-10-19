# 来源：engine-service/tests/test_golden.py 的 _normalize / _diff（zhitong-cost-ai@991ff5cd）
"""D-18 金标比对：核对、指标、投控三个零模型引擎的输出冻结回归。

金标能证明什么、不能证明什么：能检测无意的漂移；不能证明输出是对的 —— 金标从旧实现生成，来源是
``tests/costsheet/fixtures/*.xlsx``（openpyxl 自造的广联达格式样例），**不是真实项目数据**。

zt 改动：

- 金标 JSON 原样搬自旧仓 ``tests/golden/``，形状是旧 HTTP 响应。比对前去掉只属于 HTTP 层的键
  （:data:`HTTP_ONLY_KEYS`：``usage``、旧字符串告警 ``warnings``、透传字段），zt 一侧去掉 ``needs_manual`` 标注。
- 对象只比金标里有的键（金标里的键在新输出里消失 → 红；新输出多出的键不比）。
- 重新生成改用环境变量：``ZT_REGEN_GOLDEN=1 uv run pytest tests/<area>/test_golden.py``（旧仓是 ``--regen-golden``）。
  重新生成会写成新形状；必须人工确认新输出正确后才提交。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

# 非确定性字段：只有耗时。**不要往这里加业务字段** —— 每加一个，金标就少守一块。
_VOLATILE_KEYS = {"latency_ms"}
# 旧 HTTP 响应独有、zt 信封没有的顶层键
HTTP_ONLY_KEYS = {"usage", "warnings", "operator_id", "project_id", "sys_company_code"}
FIXTURES = Path(__file__).resolve().parent


def normalize(obj: Any) -> Any:
    """剥离非确定性字段与 ``needs_manual`` 标注，浮点保留 6 位（杀尾差，保住 4 位精度的比率）。

    :param obj: JSON 结构。
    :returns: 归一化后的结构。
    """
    if isinstance(obj, dict):
        return {k: normalize(v) for k, v in sorted(obj.items()) if k not in _VOLATILE_KEYS and k != "needs_manual"}
    if isinstance(obj, list):
        return [normalize(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    return obj


def project(expected: Any, actual: Any) -> Any:
    """把 ``actual`` 投影到 ``expected`` 的键上（逐层；列表按位置）。缺的键保留为哨兵以便报「消失」。

    :param expected: 金标。
    :param actual: 新输出。
    :returns: 投影后的新输出。
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        return {k: project(v, actual[k]) if k in actual else "<消失>" for k, v in expected.items()}
    if isinstance(expected, list) and isinstance(actual, list):
        return [project(e, a) for e, a in zip(expected, actual)] + actual[len(expected):]
    return actual


def diff(expected: Any, actual: Any, name: str) -> str:
    """可读的差异定位。

    :param expected: 金标。
    :param actual: 新输出（已投影）。
    :param name: 金标名。
    :returns: 差异说明（最多 40 行）。
    """
    lines = [f"金标 {name} 不匹配。若本次算法变更是有意的，确认新输出正确后跑",
             f"  ZT_REGEN_GOLDEN=1 uv run pytest -k {name}", "差异："]

    def walk(e, a, path=""):
        if type(e) is not type(a):
            lines.append(f"  {path or '<root>'}: 类型 {type(e).__name__} → {type(a).__name__} ({a!r})"[:200])
            return
        if isinstance(e, dict):
            for k in sorted(set(e) | set(a)):
                if k not in a:
                    lines.append(f"  {path}.{k}: 消失（原 {e[k]!r}）"[:200])
                else:
                    walk(e[k], a[k], f"{path}.{k}")
        elif isinstance(e, list):
            if len(e) != len(a):
                lines.append(f"  {path}: 长度 {len(e)} → {len(a)}")
            for i, (ee, aa) in enumerate(zip(e, a)):
                walk(ee, aa, f"{path}[{i}]")
        elif e != a:
            lines.append(f"  {path}: {e!r} → {a!r}"[:200])

    walk(expected, actual)
    return "\n".join(lines[:40])


def check(path: Path, flat_response: dict) -> None:
    """比对（或在 ``ZT_REGEN_GOLDEN=1`` 时重新生成）一份金标。

    :param path: 金标 JSON。
    :param flat_response: :class:`tests.costsheet.fixtures.endpoint.Response` 的 ``json()``。
    """
    actual = normalize(flat_response)
    if os.environ.get("ZT_REGEN_GOLDEN") == "1":
        path.write_text(json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip(f"已重新生成金标：{path.name}（请人工确认新输出正确后再提交）")
    assert path.exists(), f"金标缺失：{path}"
    expected = {k: v for k, v in normalize(json.loads(path.read_text(encoding="utf-8"))).items()
                if k not in HTTP_ONLY_KEYS}
    projected = project(expected, actual)
    if projected != expected:
        pytest.fail(diff(expected, projected, path.stem))


def assert_not_empty(path: Path) -> None:
    """负控：金标存在但内容为空或极小时，比对形同虚设。

    :param path: 金标 JSON。
    """
    assert path.exists(), f"{path.name} 不存在"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and len(json.dumps(data)) >= 200, f"{path.name} 内容过小，疑似被清空"
