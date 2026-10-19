# 来源：engine-service/app/api/report_templates.py（zhitong-cost-ai@991ff5c，W3 搬入 zt；改动见本文件内「zt 改动」注释）
"""报告模板（24 套 AI 初稿模板 / 172 章）的读取与章节解析。

数据源：``zhitong/skills/zt-report/data/report_templates.yaml``（旧仓 ``engine/data/report_templates.yaml`` 原样迁入）。
定位顺序（与 ``zt.inventory.data`` 同一种做法）：

1. 调用方显式传入的目录（CLI 的 ``--data-dir``）；
2. 环境变量 ``ZT_REPORT_DATA``（skill 脚本启动时设置为自己旁边的 ``data/``）；
3. 源码树里的 ``zhitong/skills/zt-report/data``（开发与测试）。

章节字段：``code/title/seq/rag_query/gen_prompt/excludes/claims/facts_allowed/attachment_hints``。写作要求只按
``template_code + section_code`` 从 YAML 解析，不接受调用方传入的 ``gen_prompt``（P07）。每章的
``prompt_version`` 由 :func:`zt.report.compose.prompt_version` 现算，与旧引擎逐章相同（tests/report 钉着）。

zt 改动：去掉 FastAPI 路由与进程级缓存（CLI 每次只读一次）；读不到或格式不对抛 :class:`zt.common.ZtError`；
新增 :func:`claims_to_confirm`（整套模板的程序性陈述，供「确认事项」一步）。
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Optional

import yaml

from zt.common import ZtError
from zt.report.compose import SectionSpec, prompt_version

ENV_DATA_DIR = "ZT_REPORT_DATA"
TEMPLATES_FILE = "report_templates.yaml"
DOCX_DIR = "docx-templates"

# zhitong/python/zt/report/templates.py → parents[3] = zhitong/
_SOURCE_TREE_DATA = Path(__file__).resolve().parents[3] / "skills" / "zt-report" / "data"


def data_dir(override: Optional[str | Path] = None) -> Path:
    """解析 zt-report 数据目录并确认模板文件在。

    :param override: 显式目录；None 时依次看环境变量与源码树。
    :returns: 数据目录。
    :raises ZtError: 目录里没有 ``report_templates.yaml``（``data_dir_invalid``）。
    """
    if override is not None:
        base = Path(override)
    elif os.environ.get(ENV_DATA_DIR):
        base = Path(os.environ[ENV_DATA_DIR])
    else:
        base = _SOURCE_TREE_DATA
    if not (base / TEMPLATES_FILE).is_file():
        raise ZtError("data_dir_invalid", f"zt-report 数据目录里没有 {TEMPLATES_FILE}：{base}",
                      hint=f"用 --data-dir 指定，或设置环境变量 {ENV_DATA_DIR}")
    return base


def _str_list(v: Any) -> list[str]:
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def _claims(v: Any) -> list[dict]:
    out = []
    for c in v or []:
        if isinstance(c, dict) and c.get("key") and c.get("text"):
            out.append({"key": str(c["key"]).strip(), "text": str(c["text"]).strip()})
    return out


def spec_of(sec: dict) -> SectionSpec:
    """章节字典 → :class:`SectionSpec`（与旧引擎 ``api/report._resolve_spec`` 同样的字段）。

    :param sec: :func:`load_templates` 给出的一章。
    :returns: 章节定义。
    """
    return SectionSpec(
        code=sec["code"], title=sec["title"], gen_prompt=sec["gen_prompt"], rag_query=sec["rag_query"] or "",
        excludes=tuple(sec["excludes"]), claims=tuple(sec["claims"]), facts_allowed=tuple(sec["facts_allowed"]),
        attachment_hints=tuple(sec["attachment_hints"]),
    )


def _section(s: dict) -> dict:
    sec = {
        "code": s.get("code", ""),
        "title": s.get("title", ""),
        "seq": s.get("seq", 0),
        "rag_query": s.get("rag_query", ""),
        "gen_prompt": (s.get("gen_prompt") or "").strip(),
        "excludes": _str_list(s.get("excludes")),
        "claims": _claims(s.get("claims")),
        "facts_allowed": _str_list(s.get("facts_allowed")),
        "attachment_hints": _str_list(s.get("attachment_hints")),
    }
    sec["prompt_version"] = prompt_version(spec_of(sec))
    return sec


def parse_templates(raw: dict) -> list[dict]:
    """过滤 ``enabled=false``（缺省视为启用），章节按 seq 升序，note / note_user 缺省补空串。

    :param raw: YAML 解析结果。
    :returns: 模板列表。
    """
    out: list[dict] = []
    for t in raw.get("templates") or []:
        if not t.get("enabled", True):
            continue
        sections = sorted(t.get("sections") or [], key=lambda s: s.get("seq", 0))
        out.append({
            "template_code": t.get("template_code", ""),
            "name": t.get("name", ""),
            "note": t.get("note") or "",
            "note_user": (t.get("note_user") or "").strip(),
            "sections": [_section(s) for s in sections],
        })
    return out


def load_templates(data: Optional[str | Path] = None) -> list[dict]:
    """读模板 YAML。

    :param data: 数据目录；None 按模块说明的顺序定位。
    :returns: 启用的模板列表（每章带 ``prompt_version``）。
    :raises ZtError: 数据目录不对（``data_dir_invalid``）或 YAML 非法（``data_file_invalid``）。
    """
    path = data_dir(data) / TEMPLATES_FILE
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ZtError("data_file_invalid", f"{path.name} 不是合法 YAML：{e}") from None
    if not isinstance(raw, dict):
        raise ZtError("data_file_invalid", f"{path.name} 顶层应为映射")
    return parse_templates(raw)


def find_template(templates: list[dict], template_code: str) -> dict:
    """按模板码取一套模板（深拷贝）。

    :param templates: :func:`load_templates` 的结果。
    :param template_code: 模板码。
    :returns: 模板。
    :raises ZtError: 模板不存在（``template_not_found``）。
    """
    for t in templates:
        if t["template_code"] == template_code:
            return copy.deepcopy(t)
    raise ZtError("template_not_found", f"模板不存在：{template_code}",
                  hint="先运行 templates 子命令列出可用的模板码")


def resolve_section(templates: list[dict], template_code: str, section_code: str) -> dict:
    """按 ``template_code + section_code`` 取章节定义（深拷贝）。

    :param templates: :func:`load_templates` 的结果。
    :param template_code: 模板码。
    :param section_code: 章节码（单章重试的定位键）。
    :returns: 章节定义。
    :raises ZtError: 模板或章节不存在（``template_not_found`` / ``section_not_found``）。
    """
    t = find_template(templates, template_code)
    for s in t["sections"]:
        if s["code"] == section_code:
            return s
    raise ZtError("section_not_found", f"模板章节不存在：template_code={template_code} section_code={section_code}",
                  hint="用 templates --template <模板码> 列出这套模板的章节码")


def template_fact_keys(template: dict) -> list[str]:
    """这套模板各章 ``facts_allowed`` 的并集，按出现顺序。

    :param template: 一套模板。
    :returns: 事实键列表。
    """
    out: list[str] = []
    for s in template["sections"]:
        for k in s["facts_allowed"]:
            if k not in out:
                out.append(k)
    return out


def claims_to_confirm(template: dict) -> list[dict]:
    """整套模板要用户确认的程序性陈述：按 key 去重，每个 key 取第一条文案（与提示词里写的那条相同）。

    :param template: 一套模板。
    :returns: ``[{"key", "text", "sections": [章节码…]}]``。
    """
    by_key: dict[str, dict] = {}
    for s in template["sections"]:
        for c in s["claims"]:
            hit = by_key.get(c["key"])
            if hit is None:
                by_key[c["key"]] = {"key": c["key"], "text": c["text"], "sections": [s["code"]]}
            elif s["code"] not in hit["sections"]:
                hit["sections"].append(s["code"])
    return list(by_key.values())
