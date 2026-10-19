# 来源：engine-service/tests/test_stubs_sync_limits.py（zhitong-cost-ai@991ff5cd）的送检上限部分
"""WS08-12（issue #760）送检上限：超过份数或合计大小，在读任何一个字节、解析任何一张表之前拦下。

zt 改动：旧端点回 413、上限来自环境变量 COSTSHEET_MAX_FILES / COSTSHEET_MAX_TOTAL_MB；zt 抛 ZtError
（too_many_files / input_too_large，CLI 退出码 2），上限是 run() 的参数（CLI 的 --max-files / --max-total-mb）。
旧文件里「三个端点是普通 def、解析期间 /engine/health 不被卡住」两条闸针对 FastAPI 事件循环，zt 没有服务进程，不再适用。
"""
from __future__ import annotations

import pytest

from tests.costsheet.fixtures import costsheet_shapes as S
from zt.common import ZtError
from zt.costsheet import service as svc
from zt.indicator import service as indicator
from zt.reconcile import service as reconcile
from zt.tk import engine as tk_engine
from zt.tk import service as tk


def _refs(n: int) -> list[dict]:
    ref = S.put(S.detail_with_total(), "ws08b-many.xlsx", "F-MANY")
    return [dict(ref, file_id=f"F-{i}") for i in range(n)]


def test_61_files_is_rejected_before_reading_anything(monkeypatch):
    calls = []
    monkeypatch.setattr(tk_engine, "run", lambda *a, **kw: calls.append(1))
    with pytest.raises(ZtError) as exc:
        tk.run(tk.TkRequest(project_id="P", submission_files=_refs(61)))
    assert exc.value.code == "too_many_files"
    assert "60" in exc.value.message and "分批" in (exc.value.hint or "")
    assert calls == [], "超限必须在解析之前拦下"
    # 对照：60 份不拦（上限是「超过」才拦，不是「达到」）
    env = indicator.run(indicator.IndicatorRequest(gross_area=100, price_files=_refs(60)))
    assert env.status.value in ("ok", "partial")


def test_total_size_limit():
    ref = S.put(S.detail_with_total(), "ws08b-big.xlsx", "F-BIG")
    for run in (lambda: indicator.run(indicator.IndicatorRequest(price_files=[ref]), max_total_mb=0.001),
                lambda: reconcile.run(reconcile.ReconcileRequest(submitted_file=ref, approved_file=ref),
                                      max_total_mb=0.001)):
        with pytest.raises(ZtError) as exc:
            run()
        assert exc.value.code == "input_too_large" and "MB" in exc.value.message


def test_baseline_files_count_towards_the_limit():
    """合同/中标清单也要读、也要解析 —— 算进上限，不能靠把文件挪到基准组绕过。"""
    refs = _refs(4)
    with pytest.raises(ZtError) as exc:
        tk.run(tk.TkRequest(project_id="P", submission_files=refs[:2], baseline_files=refs[2:]), max_files=3)
    assert exc.value.code == "too_many_files"


def test_missing_file_is_an_error_not_an_empty_result(tmp_path):
    """读不到文件是调用方的错，退出码 2；不给「成功 + 空」。"""
    with pytest.raises(ZtError) as exc:
        svc.load_files([str(tmp_path / "不存在.xlsx")])
    assert exc.value.code == "input_not_found"
