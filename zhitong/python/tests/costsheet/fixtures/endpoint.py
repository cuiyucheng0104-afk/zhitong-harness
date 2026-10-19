"""旧端点用例的转接：把 ``client.post("/engine/...", json=...)`` 映射到 zt 接线层，断言照旧写。

旧仓用例对 FastAPI 端点断言 HTTP 状态码与响应体。zt 没有 HTTP 层，结果契约见 :mod:`zt.costsheet.service`：

- ok / partial / empty → ``status_code == 200``，``json()`` 是 ``{**data, status, status_reason, warning_items, coverage}``
  （旧响应体平铺的形状）；
- insufficient → ``status_code == 422``，``json()`` 是 ``{"detail": data["detail"]}``（解析失败）或
  ``{"detail": {"message", "reason_code"}}``（``.xls``）；
- :class:`zt.common.ZtError`（文件不存在、超上限、请求字段不对）原样抛出，用例用 ``pytest.raises`` 断言。

请求体里的旧字段 ``rel_path`` 不再接受；夹具用 :func:`tests.costsheet.fixtures.costsheet_shapes.put` 生成 ``path``。
"""
from __future__ import annotations

import atexit
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from zt.common.envelope import Envelope, ResultStatus
from zt.costsheet import probe_files
from zt.costsheet.service import parse_request
from zt.indicator import service as indicator
from zt.reconcile import service as reconcile
from zt.tk import service as tk

_SCRATCH: Optional[Path] = None


def scratch_dir() -> Path:
    """本进程共用的临时目录（首次调用时创建，进程退出时删除）。

    :returns: 目录。
    """
    global _SCRATCH
    if _SCRATCH is None:
        _SCRATCH = Path(tempfile.mkdtemp(prefix="zt-costsheet-tests-"))
        atexit.register(shutil.rmtree, _SCRATCH, ignore_errors=True)
    return _SCRATCH


def _reconcile(body: dict) -> Envelope:
    return reconcile.run(parse_request(reconcile.ReconcileRequest, body))


def _indicator(body: dict) -> Envelope:
    return indicator.run(parse_request(indicator.IndicatorRequest, body))


def _tk(body: dict) -> Envelope:
    return tk.run(parse_request(tk.TkRequest, body))


def _probe(body: dict) -> Envelope:
    return probe_files.run(parse_request(probe_files.ProbeRequest, body))


ROUTES = {
    "/engine/reconcile/run": _reconcile,
    "/engine/indicator/calc": _indicator,
    "/engine/tk/detect": _tk,
    "/engine/costsheet/probe": _probe,
}


@dataclass
class Response:
    """旧 TestClient 响应的替身。

    :ivar status_code: 200（ok/partial/empty）或 422（insufficient）。
    :ivar envelope: zt 信封的 JSON。
    """

    status_code: int
    envelope: dict[str, Any]

    def json(self) -> dict[str, Any]:
        """旧响应体形状。

        :returns: 平铺的结果，或 ``{"detail": ...}``。
        """
        env = self.envelope
        if self.status_code == 422:
            data = env["data"]
            if "detail" in data:
                return {"detail": data["detail"]}
            item = env["warning_items"][0]
            return {"detail": {"message": item["message"], "reason_code": env["status_reason"], "hint": item["hint"]}}
        return {**env["data"], "status": env["status"], "status_reason": env["status_reason"],
                "warning_items": env["warning_items"], "coverage": env["coverage"]}

    @property
    def text(self) -> str:
        """调试输出。

        :returns: 信封的字符串形式。
        """
        return str(self.envelope)


class Client:
    """``client.post(url, json=..., headers=...)`` → :class:`Response`；``headers`` 忽略（zt 没有服务令牌）。"""

    def post(self, url: str, json: Optional[dict] = None, headers: Optional[dict] = None, **_: Any) -> Response:
        """调用 ``url`` 对应的接线层。

        :param url: 旧端点路径。
        :param json: 请求体。
        :param headers: 忽略。
        :returns: 响应替身。
        """
        env = ROUTES[url](dict(json or {}))
        code = 422 if env.status is ResultStatus.INSUFFICIENT else 200
        return Response(code, env.to_json())


client = Client()
HEADERS: dict[str, str] = {}
