"""TOS 桶管理（只读）：经 ``ve tosutil ...`` 透传官方 ``tosutil``。

``ve tosutil <原生命令>`` 会在首次调用时自动安装 tosutil（官方文档 docs/7-ProxyCLI-zh.md）；透传命令不经过
``ve`` 的客户端安全策略，所以本模块只封装只读命令：``ls``、``stat``，以及 ``lifecycle``、``versioning`` 的查询。

- ``ls`` / ``stat`` 属于 tosutil 文档列出的核心命令。
- ``lifecycle`` / ``versioning`` 的命令名与 ``-method get`` 写法**没有在官方文档里核实**（沙箱访问不到
  volcengine.com）；因此调用前先跑 ``ve tosutil help`` 确认该命令存在，不存在就报 ``tosutil_verb_missing``，
  存在也在结果里带一条 ``tosutil_syntax_unverified`` 提示，由人按 ``tosutil help <命令>`` 核对。
- 不提供删桶、改生命周期、改版本控制：公司桶是唯一真源（spec §5），这些操作由用户在控制台完成。
"""
from __future__ import annotations

import re

from zt.common.envelope import Envelope, WarningItem, WarningLevel, empty, ok, partial
from zt.common.errors import ZtError
from zt.volc.ve import Ve

MAX_LINES = 200

_BUCKET_URI = re.compile(r"tos://([a-z0-9][a-z0-9-]{1,61}[a-z0-9])(?![a-z0-9-])")


def _tosutil(ve: Ve, *args: str) -> str:
    return ve.raw(["tosutil", *args])


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def _cap(lines: list[str]) -> tuple[list[str], bool]:
    return lines[:MAX_LINES], len(lines) > MAX_LINES


def buckets_envelope(ve: Ve) -> Envelope:
    """``tos-buckets``：列出当前凭据可见的桶（``ve tosutil ls``）。

    :param ve: ``ve`` 调用器。
    :returns: ``ok``，``data.buckets`` 为桶名；没有桶为 ``empty``。
    :raises ZtError: 有输出但认不出任何桶（``tosutil_output_unrecognized``），避免把格式变化当成「没有桶」。
    """
    text = _tosutil(ve, "ls")
    lines = _lines(text)
    names = list(dict.fromkeys(_BUCKET_URI.findall(text)))
    if not lines:
        return empty("no_buckets", warnings=[WarningItem(code="no_buckets", level=WarningLevel.INFO,
                                                          message="当前凭据下没有可见的桶。")])
    if not names:
        raise ZtError("tosutil_output_unrecognized", f"tosutil ls 的输出里认不出桶：{lines[0][:120]!r}",
                      hint="tosutil 版本变化？直接看 ve tosutil ls 的原始输出")
    return ok({"buckets": names, "total": len(names)})


def stat_envelope(ve: Ve, bucket: str) -> Envelope:
    """``tos-stat``：桶的基本信息（``ve tosutil stat tos://<bucket>``）。

    :param ve: ``ve`` 调用器。
    :param bucket: 桶名（已校验）。
    :returns: ``ok``，``data.lines`` 为 tosutil 原样输出（最多 200 行）。
    :raises ZtError: tosutil 无输出（``tosutil_empty_output``）。
    """
    lines = _lines(_tosutil(ve, "stat", f"tos://{bucket}"))
    if not lines:
        raise ZtError("tosutil_empty_output", f"tosutil stat tos://{bucket} 没有输出。", hint="桶不存在或无权限？")
    shown, truncated = _cap(lines)
    return _with_truncation({"bucket": bucket, "lines": shown}, truncated, len(lines))


def ls_envelope(ve: Ve, bucket: str, prefix: str) -> Envelope:
    """``tos-ls``：列桶内对象（``ve tosutil ls tos://<bucket>/<prefix>``）。

    :param ve: ``ve`` 调用器。
    :param bucket: 桶名（已校验）。
    :param prefix: 对象前缀（已校验，可为空）。
    :returns: ``ok``，``data.lines`` 为原样输出（最多 200 行）；没有对象为 ``empty``；超出为 ``partial``。
    """
    uri = f"tos://{bucket}/{prefix}" if prefix else f"tos://{bucket}"
    lines = _lines(_tosutil(ve, "ls", uri))
    if not lines:
        return empty("no_objects", coverage={"uri": uri})
    shown, truncated = _cap(lines)
    return _with_truncation({"uri": uri, "lines": shown}, truncated, len(lines))


def _with_truncation(data: dict[str, object], truncated: bool, total: int) -> Envelope:
    if not truncated:
        return ok(data)
    return partial(data, coverage={"lines_total": total, "lines_shown": MAX_LINES},
                   warnings=[WarningItem(code="output_truncated", level=WarningLevel.WARN,
                                         message=f"输出共 {total} 行，只返回前 {MAX_LINES} 行。",
                                         hint="用更长的 --prefix 缩小范围")])


def config_envelope(ve: Ve, verb: str, bucket: str) -> Envelope:
    """``tos-lifecycle`` / ``tos-versioning``：查询桶的生命周期或版本控制配置。

    :param ve: ``ve`` 调用器。
    :param verb: ``lifecycle`` 或 ``versioning``。
    :param bucket: 桶名（已校验）。
    :returns: ``ok``，``data.lines`` 为原样输出；带 ``tosutil_syntax_unverified`` 提示。
    :raises ZtError: 本机 tosutil 没有该命令（``tosutil_verb_missing``）或无输出。
    """
    if verb not in ("lifecycle", "versioning"):
        raise ZtError("invalid_option", f"不支持的 tosutil 命令：{verb}")
    help_text = _tosutil(ve, "help")
    if not re.search(rf"(?<![A-Za-z0-9_-]){verb}(?![A-Za-z0-9_-])", help_text):
        raise ZtError("tosutil_verb_missing", f"本机 tosutil 的 help 里没有 {verb} 命令。",
                      hint="先 ve tosutil help 看实际命令名；查不到时请用户在 TOS 控制台查看，并不要猜测配置")
    lines = _lines(_tosutil(ve, verb, "-method", "get", f"tos://{bucket}"))
    if not lines:
        raise ZtError("tosutil_empty_output", f"tosutil {verb} 没有输出。", hint="桶不存在、无权限，或命令写法与本机 tosutil 不符")
    shown, truncated = _cap(lines)
    env = _with_truncation({"bucket": bucket, "setting": verb, "lines": shown}, truncated, len(lines))
    env.warning_items.append(WarningItem(
        code="tosutil_syntax_unverified", level=WarningLevel.INFO,
        message=f"`tosutil {verb} -method get` 的写法未对照官方文档核实。",
        hint=f"结果存疑时运行 ve tosutil help {verb} 核对，或让用户在控制台确认"))
    return env
