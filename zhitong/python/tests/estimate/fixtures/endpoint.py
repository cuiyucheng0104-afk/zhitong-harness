"""旧端点用例的转接：把 ``client.post("/engine/estimate/...", json=...)`` 映射到 :mod:`zt.estimate.service`。

旧仓用例对 FastAPI 端点断言 HTTP 状态码与响应体。zt 没有 HTTP 层，这里按旧口径换算：

- 成功 → ``status_code == 200``，``json()`` 是服务返回的字典（compute 另带 ``xlsx_base64``）；不带 usage 与透传字段
  （sys_company_code / project_id / operator_id 在请求里丢掉，不回显）；
- :class:`zt.estimate.service.GateRejected`（四道闸）→ 422，``{"detail": 闸的原文案}``；
- :class:`zt.common.ZtError` → 按 code 换算：renderer_unavailable / engine_unavailable → 501、render_failed → 500、
  invalid_answers / answers_missing（旧版模型输出不可解析）→ 502，其余 → 422；``{"detail": message}``。

extract 走两半：extract_prepare → :data:`AGENT`（旧用例打桩的 ``estimate_extract.chat``，签名 ``(messages, **kw)``，
返回文本或 ``(文本, usage)``，可抛异常）逐份作答 → extract_finalize。文件读取在 :data:`ROOT` 下进行；
:func:`stub_chain` 按 rel_path 给正文（prepare 与 finalize 各读一遍，同一 rel_path 给同一段正文）。
"""
from __future__ import annotations

import atexit
import base64
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from zt.common import ZtError
from zt.estimate import extract as estimate_extract
from zt.estimate import policy as estimate_policy
from zt.estimate import service

HEADERS: dict[str, str] = {}
PASSTHROUGH = ("sys_company_code", "project_id", "operator_id")
ROOT = Path(tempfile.mkdtemp(prefix="zt-estimate-tests-"))
atexit.register(shutil.rmtree, ROOT, ignore_errors=True)

AGENT: Optional[Callable[..., Any]] = None

_STATUS = {"renderer_unavailable": 501, "engine_unavailable": 501, "render_failed": 500,
           "invalid_answers": 502, "answers_missing": 502}


class Response:
    """旧 TestClient 响应的替身。"""

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body

    @property
    def text(self) -> str:
        return json.dumps(self._body, ensure_ascii=False)


def _strip(body: Any) -> dict:
    return {k: v for k, v in dict(body or {}).items() if k not in PASSTHROUGH}


def _compute(body: dict) -> dict:
    out, xlsx = service.compute(body)
    return {**out, "xlsx_base64": base64.b64encode(xlsx).decode("ascii") if xlsx is not None else None}


def _agent_answers(prep: dict, template_code: str) -> dict:
    pol = estimate_policy.load_policy(template_code)
    cell_specs = estimate_extract.cell_hint_specs(template_code, pol)
    checks = estimate_policy.extract_checks(pol)
    with_buildings = bool(estimate_policy.slot_cells(pol))
    files = []
    for f in prep["files"]:
        messages = [{"role": "user", "content": estimate_extract._prompt(f["window"], cell_specs, checks,
                                                                           with_buildings)}]
        if AGENT is None:
            raise AssertionError("用例没有打桩 AGENT")
        got = AGENT(messages, max_tokens=estimate_extract.extract_max_tokens(template_code, pol))
        text = got[0] if isinstance(got, tuple) else got
        if isinstance(text, dict):
            obj = text
        else:
            m = re.search(r"\{.*\}", text or "", re.S)
            try:
                obj = json.loads(m.group(0)) if m else None
            except json.JSONDecodeError:
                obj = None
        files.append({"file_id": f["file_id"], **(obj if isinstance(obj, dict) else {"_unparseable": text})})
    return {"files": files}


def _extract(body: dict) -> dict:
    prep = service.extract_prepare(body, ROOT)
    answers = _agent_answers(prep, prep["template_code"])
    return service.extract_finalize(body, ROOT, answers, prep["prepare_fingerprint"])


ROUTES: dict[str, Callable[[dict], Any]] = {
    "/engine/estimate/compute": _compute,
    "/engine/estimate/suggest": service.suggest,
    "/engine/estimate/extract": _extract,
}


class _Client:
    def post(self, url: str, *, headers: Any = None, json: Any = None) -> Response:  # noqa: A002 —— 旧调用形态
        return self._call(lambda: ROUTES[url](_strip(json)))

    def get(self, url: str, *, headers: Any = None, params: Optional[dict] = None) -> Response:
        assert url == "/engine/estimate/template", url
        code = (params or {}).get("template_code", "gsyz_v1")
        return self._call(lambda: service.template(code))

    @staticmethod
    def _call(fn: Callable[[], Any]) -> Response:
        try:
            return Response(200, fn())
        except service.GateRejected as e:
            return Response(422, {"detail": e.detail})
        except ZtError as e:
            return Response(_STATUS.get(e.code, 422), {"detail": e.message, "code": e.code})


client = _Client()


def stub_chain(monkeypatch, per_file_text: list[str], answers: list) -> None:
    """正文与 agent 回答的桩（旧 ``_stub_chain``）。

    正文按 rel_path 第一次出现的顺序依次取 ``per_file_text``：空串 → 失败码 no_text 的 DocText，非空 → text_layer。
    回答按调用顺序取：dict（原样）、str（原样文本）或 Exception 实例（抛出）。

    :param monkeypatch: pytest monkeypatch。
    :param per_file_text: 每份文件的正文。
    :param answers: 每份可读文件的回答。
    """
    from zt.textextract.model import DocText, failed_doc

    texts = list(per_file_text)
    by_rel: dict[str, str] = {}

    def fake_load(root, rel_path, file_name=None, **kw):
        if rel_path not in by_rel:
            by_rel[rel_path] = texts.pop(0)
        t = by_rel[rel_path]
        return DocText(text=t, text_source="text_layer") if t.strip() else failed_doc("no_text", "空文件")

    monkeypatch.setattr(service, "load_document", fake_load)
    queue = list(answers)

    def fake_agent(messages, **kw):
        a = queue.pop(0)
        if isinstance(a, Exception):
            raise a
        return a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)

    monkeypatch.setattr(__import__(__name__, fromlist=["AGENT"]), "AGENT", fake_agent)
