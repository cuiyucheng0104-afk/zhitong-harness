"""``项目说明.md``：agent 开项目时读的入口文件。

文件由 YAML 头（``---`` 包围）加 Markdown 正文组成。YAML 头是脚本读写的机器字段，正文给 agent 与人读：

.. code-block:: text

    ---
    项目编号: 2026-007
    工程名称: 某某医院住院楼
    咨询类型: 结算审核
    阶段: 审定
    别名: [合同号 HT-2026-18]
    ---
    # 某某医院住院楼
    ...

必填字段：``项目编号``、``工程名称``、``咨询类型``、``阶段``。别名、业态、规模、旧系统项目ID、状态可选。
模板在 ``zhitong/skills/zt-project/templates/项目说明.md``，用 ``{{字段}}`` 占位。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

import yaml

from zt.common import ZtError
from zt.common.paths import PROJECT_CODE
from zt.inventory.casebook import split_table_row

REQUIRED_FIELDS = ("项目编号", "工程名称", "咨询类型", "阶段")
# 草稿里的占位值：表示这一项还没有跟用户确认，脚本遇到要报错而不是当成有效值
UNDECIDED_VALUES = ("待确认", "")
_FRONT_RE = re.compile(r"\A\ufeff?---[ \t]*\r?\n(?P<head>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """拆出 YAML 头和正文。

    :param text: 项目说明全文。
    :returns: ``(头字段字典, 正文)``；没有 YAML 头时为 ``({}, 全文)``。
    :raises ZtError: YAML 头存在但不是合法 YAML 映射（``project_doc_invalid``）。
    """
    m = _FRONT_RE.match(text)
    if m is None:
        return {}, text
    try:
        head = yaml.safe_load(m.group("head")) or {}
    except yaml.YAMLError as e:
        raise ZtError("project_doc_invalid", f"项目说明的 YAML 头不合法：{e}") from e
    if not isinstance(head, dict):
        raise ZtError("project_doc_invalid", "项目说明的 YAML 头必须是键值映射")
    return head, text[m.end():]


def read_project_doc(text: str, *, require: tuple[str, ...] = ()) -> dict[str, Any]:
    """读项目说明的 YAML 头。

    :param text: 项目说明全文。
    :param require: 必须存在且非空的字段。
    :returns: 头字段（键保持中文原名；值按 YAML 解析，``项目编号`` 等统一转成字符串）。
    :raises ZtError: 头不合法（``project_doc_invalid``）、缺字段（``project_doc_incomplete``）、
        项目编号格式不是 YYYY-NNN（``invalid_project_code``）。
    """
    head, _body = split_front_matter(text)
    fields = {str(k): v for k, v in head.items()}
    for key in ("项目编号", "咨询类型", "阶段"):
        if key in fields and fields[key] is not None:
            fields[key] = str(fields[key]).strip()
    missing = [k for k in require if fields.get(k) in (None, "")]
    if missing:
        raise ZtError("project_doc_incomplete", f"项目说明缺字段：{'、'.join(missing)}",
                      hint="补全项目说明的 YAML 头后重试")
    code = fields.get("项目编号")
    if code and not PROJECT_CODE.match(code):
        raise ZtError("invalid_project_code", f"项目编号应为 YYYY-NNN：{code!r}")
    return fields


_PLACEHOLDER = re.compile(r"\{\{\s*([^{}\s|]+)(?:\|(yaml))?\s*\}\}")


def render_template(template: str, values: dict[str, Any]) -> str:
    """把模板里的 ``{{字段}}`` 换成值；缺值的占位符抛错，不静默留空。

    ``{{字段}}`` 渲染成正文文字（列表为 ``[a, b]``，None 为空串）；``{{字段|yaml}}`` 渲染成 YAML 标量
    （字符串加双引号并转义），用在 YAML 头里，避免工程名含冒号、井号时把头写坏。

    :param template: 模板全文。
    :param values: 字段值。
    :returns: 渲染结果。
    :raises ZtError: 模板里有 ``values`` 没给的占位符（``template_field_missing``）。
    """
    def text(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            return "[" + ", ".join(str(x) for x in v) + "]"
        return str(v)

    def as_yaml(v: Any) -> str:
        if v is None:
            return '""'
        if isinstance(v, (list, tuple)):
            return json.dumps([str(x) for x in v], ensure_ascii=False)
        return json.dumps(str(v), ensure_ascii=False)

    missing = sorted({m.group(1) for m in _PLACEHOLDER.finditer(template) if m.group(1) not in values})
    if missing:
        raise ZtError("template_field_missing", f"模板占位符没有值：{'、'.join(missing)}")
    return _PLACEHOLDER.sub(
        lambda m: as_yaml(values[m.group(1)]) if m.group(2) else text(values[m.group(1)]), template)


def set_front_matter_fields(text: str, updates: dict[str, Any]) -> str:
    """改写 YAML 头里的字段，其余内容（含正文）原样保留。

    只改已有行的值，没有的字段追加在头的末尾；不重排、不丢注释。

    :param text: 项目说明全文。
    :param updates: ``{字段: 新值}``，值只支持标量。
    :returns: 新全文。
    :raises ZtError: 没有 YAML 头（``project_doc_invalid``）。
    """
    m = _FRONT_RE.match(text)
    if m is None:
        raise ZtError("project_doc_invalid", "项目说明没有 YAML 头，无法改写字段")
    lines = m.group("head").split("\n")
    for key, value in updates.items():
        scalar = json.dumps(value, ensure_ascii=False)  # JSON 标量也是合法 YAML
        pattern = re.compile(rf"^{re.escape(key)}\s*:")
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f"{key}: {scalar}"
                break
        else:
            lines.append(f"{key}: {scalar}")
    head_end = m.start("head")
    return text[:head_end] + "\n".join(lines) + text[m.end("head"):]


def find_section(text: str, title: str) -> Optional[tuple[int, int]]:
    """找 ``## <title>`` 小节的正文范围。

    :param text: 全文。
    :param title: 小节标题（不含 ``##``）。
    :returns: ``(起, 止)`` 字符下标（正文不含标题行，到下一个 ``## `` 或文末）；没有该小节为 None。
    """
    m = re.search(rf"^##[ \t]+{re.escape(title)}[ \t]*\r?\n", text, re.M)
    if m is None:
        return None
    nxt = re.search(r"^##[ \t]+", text[m.end():], re.M)
    return m.end(), m.end() + nxt.start() if nxt else len(text)


def replace_section(text: str, title: str, body: str) -> str:
    """替换 ``## <title>`` 小节的正文；没有该小节则追加到文末。

    :param text: 全文。
    :param title: 小节标题。
    :param body: 新正文（不含标题行，不含末尾空行）。
    :returns: 新全文。
    """
    span = find_section(text, title)
    block = body.rstrip("\n") + "\n\n"
    if span is None:
        return text.rstrip("\n") + f"\n\n## {title}\n{block}"
    start, end = span
    return text[:start] + block + text[end:]


def write_text_atomic(path: Path, text: str) -> Path:
    """UTF-8（LF 换行）原子写文本：先写同目录临时文件，再替换目标。

    :param path: 目标路径；父目录不存在时创建。
    :param text: 全文。
    :returns: 写入的路径。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def section_table(text: str, title: str) -> list[dict[str, str]]:
    """读 ``## <title>`` 小节里的第一张 Markdown 表。

    :param text: 全文。
    :param title: 小节标题。
    :returns: 每行一个 ``{列名: 值}``；小节或表不存在为空列表。
    """
    span = find_section(text, title)
    if span is None:
        return []
    lines = text[span[0]:span[1]].splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.lstrip().startswith("|")), None)
    if start is None or start + 1 >= len(lines):
        return []
    header = split_table_row(lines[start])
    rows: list[dict[str, str]] = []
    for ln in lines[start + 2:]:
        if not ln.lstrip().startswith("|"):
            break
        cells = split_table_row(ln)
        cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return rows


def section_bullets(text: str, title: str) -> list[str]:
    """读 ``## <title>`` 小节里的无序列表项（``- `` 开头的行）。

    :param text: 全文。
    :param title: 小节标题。
    :returns: 列表项文字（去掉 ``- `` 与首尾空白）。
    """
    span = find_section(text, title)
    if span is None:
        return []
    return [ln.strip()[2:].strip() for ln in text[span[0]:span[1]].splitlines() if ln.strip().startswith("- ")]
