"""参数校验：所有会进入 ``ve`` 或 ``ssh`` 参数列表的值先过这里。

值以独立 argv 元素传递（不经 shell），校验的目的是在调用前给出明确错误，并防止以 ``-`` 开头的值被当成选项。
"""
from __future__ import annotations

import ipaddress
import re
from typing import Optional

from zt.common.errors import ZtError

_INSTANCE_ID = re.compile(r"^i-[a-z0-9]{6,40}$")
_SG_ID = re.compile(r"^sg-[a-z0-9]{6,40}$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_LABEL = re.compile(r"^[A-Za-z0-9_.:-]{1,40}$")
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_TEXT = re.compile(r"^[A-Za-z0-9 _.:/@-]{1,255}$")

PROTOCOLS = ("tcp", "udp", "icmp", "all")
POLICIES = ("accept", "drop")
PORT_ANY = -1


def instance_id(value: str) -> str:
    """校验 ECS 实例 ID（``i-…``）。

    :param value: 候选值。
    :returns: 原值。
    :raises ZtError: 格式不对（``invalid_instance_id``）。
    """
    if not _INSTANCE_ID.match(value):
        raise ZtError("invalid_instance_id", f"实例 ID 不合法：{value!r}", hint="形如 i-yeXXXXXXXX，可用 ecs-list 查")
    return value


def security_group_id(value: str) -> str:
    """校验安全组 ID（``sg-…``）。

    :param value: 候选值。
    :returns: 原值。
    :raises ZtError: 格式不对（``invalid_sg_id``）。
    """
    if not _SG_ID.match(value):
        raise ZtError("invalid_sg_id", f"安全组 ID 不合法：{value!r}", hint="形如 sg-XXXXXXXX，可用 ecs-status 看实例绑定的安全组")
    return value


def bucket_name(value: str) -> str:
    """校验 TOS 桶名（小写字母、数字、连字符，3–63）。

    :param value: 候选值。
    :returns: 原值。
    :raises ZtError: 格式不对（``invalid_bucket``）。
    """
    if not _BUCKET.match(value):
        raise ZtError("invalid_bucket", f"桶名不合法：{value!r}", hint="3–63 位小写字母、数字、连字符，首尾为字母或数字")
    return value


def object_prefix(value: str) -> str:
    """校验 TOS 对象前缀：不含控制字符、反斜杠、``..`` 段，不以 ``-`` 开头。

    :param value: 候选值，首尾 ``/`` 会被去掉。
    :returns: 规范化后的前缀；空串表示桶根。
    :raises ZtError: 不合法（``invalid_prefix``）。
    """
    prefix = value.strip("/")
    if prefix.startswith("-") or "\\" in prefix or any(ord(c) < 32 for c in prefix) or ".." in prefix.split("/"):
        raise ZtError("invalid_prefix", f"对象前缀不合法：{value!r}", hint="不能含反斜杠、控制字符、.. 段，不能以 - 开头")
    return prefix


def ssh_alias(value: str) -> str:
    """校验 SSH 主机别名的字符集（不以 ``-`` 开头，防止被 ssh 当作选项）。

    :param value: 候选值。
    :returns: 原值。
    :raises ZtError: 不合法（``invalid_ssh_alias``）。
    """
    if not _ALIAS.match(value):
        raise ZtError("invalid_ssh_alias", f"主机别名不合法：{value!r}", hint="只允许字母、数字、_ . -，且不能以符号开头")
    return value


def label(value: str) -> str:
    """校验规则描述里的标签（用于区分同一安全组里不同人的白名单）。

    :param value: 候选值。
    :returns: 原值。
    :raises ZtError: 不合法（``invalid_label``）。
    """
    if not _LABEL.match(value):
        raise ZtError("invalid_label", f"标签不合法：{value!r}", hint="1–40 位字母、数字、_ . : -")
    return value


def description(value: str) -> str:
    """校验安全组规则描述（ASCII 受限字符集，≤255）。

    :param value: 候选值。
    :returns: 原值。
    :raises ZtError: 不合法（``invalid_description``）。
    """
    if not _TEXT.match(value) or value.startswith("-"):
        raise ZtError("invalid_description", f"规则描述不合法：{value!r}", hint="1–255 位字母、数字、空格和 _ . : / @ -")
    return value


def protocol(value: str) -> str:
    """校验并小写化协议。

    :param value: ``tcp``/``udp``/``icmp``/``all``（大小写不敏感）。
    :returns: 小写协议名。
    :raises ZtError: 不在范围内（``invalid_protocol``）。
    """
    low = value.lower()
    if low not in PROTOCOLS:
        raise ZtError("invalid_protocol", f"协议不支持：{value!r}", hint=f"可选 {', '.join(PROTOCOLS)}")
    return low


def policy(value: str) -> str:
    """校验规则策略。

    :param value: ``accept`` 或 ``drop``。
    :returns: 小写策略。
    :raises ZtError: 不在范围内（``invalid_policy``）。
    """
    low = value.lower()
    if low not in POLICIES:
        raise ZtError("invalid_policy", f"策略不支持：{value!r}", hint=f"可选 {', '.join(POLICIES)}")
    return low


def priority(value: int) -> int:
    """校验规则优先级（1–100）。

    :param value: 优先级。
    :returns: 原值。
    :raises ZtError: 越界（``invalid_priority``）。
    """
    if not 1 <= value <= 100:
        raise ZtError("invalid_priority", f"优先级必须在 1–100：{value}")
    return value


def port_range(proto: str, start: int, end: int) -> tuple[int, int]:
    """校验端口范围。tcp/udp 必须 1–65535 且 start≤end；icmp/all 允许 -1。

    :param proto: 已规范化的协议。
    :param start: 起始端口。
    :param end: 结束端口。
    :returns: ``(start, end)``。
    :raises ZtError: 越界或颠倒（``invalid_port``）。
    """
    if proto in ("icmp", "all") and (start, end) == (PORT_ANY, PORT_ANY):
        return start, end
    if not (1 <= start <= 65535 and 1 <= end <= 65535):
        raise ZtError("invalid_port", f"端口必须在 1–65535：{start}-{end}", hint="icmp/all 可用 -1")
    if start > end:
        raise ZtError("invalid_port", f"起始端口大于结束端口：{start}-{end}")
    return start, end


def ports_list(value: str) -> list[int]:
    """解析逗号分隔的单端口列表（如 ``22,2222``）。

    :param value: 文本。
    :returns: 去重后保持顺序的端口列表。
    :raises ZtError: 为空或含非法端口（``invalid_port``）。
    """
    out: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part.isdigit() or not 1 <= int(part) <= 65535:
            raise ZtError("invalid_port", f"端口列表不合法：{value!r}", hint="逗号分隔的 1–65535 整数，如 22 或 22,2222")
        if int(part) not in out:
            out.append(int(part))
    return out


def cidr(value: str, *, allow_world: bool = False) -> str:
    """校验 CIDR（IPv4 或 IPv6）。全网段（``/0``）需要 ``allow_world``。

    :param value: 候选值，如 ``203.0.113.7/32``。
    :param allow_world: 是否允许 ``0.0.0.0/0`` 与 ``::/0``。
    :returns: 规范化文本。
    :raises ZtError: 格式不对（``invalid_cidr``）或未授权的全网段（``world_open_refused``）。
    """
    try:
        net = ipaddress.ip_network(value, strict=True)
    except ValueError:
        raise ZtError("invalid_cidr", f"CIDR 不合法：{value!r}", hint="形如 203.0.113.7/32，主机位必须为 0") from None
    if net.prefixlen == 0 and not allow_world:
        raise ZtError("world_open_refused", "拒绝向全网段（/0）开放。", hint="确需如此，在用户明确同意后加 --allow-world")
    return str(net)


def public_ip(value: str) -> str:
    """校验公网 IP 地址（拒绝私网、回环、链路本地等）。

    :param value: IP 文本。
    :returns: 规范化文本。
    :raises ZtError: 不是 IP（``invalid_ip``）或不是公网地址（``ip_not_public``）。
    """
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        raise ZtError("invalid_ip", f"不是合法 IP：{value[:60]!r}") from None
    if not addr.is_global:
        raise ZtError("ip_not_public", f"{addr} 不是公网地址，不能写入白名单。", hint="用 --ip 给出出口公网 IP")
    return str(addr)


def host_cidr(addr: str) -> str:
    """把单个 IP 转成主机 CIDR（IPv4 ``/32``，IPv6 ``/128``）。

    :param addr: 已校验的 IP 文本。
    :returns: CIDR 文本。
    """
    ip = ipaddress.ip_address(addr)
    return f"{ip}/{ip.max_prefixlen}"


def timeout_seconds(value: float, *, maximum: Optional[float] = 3600) -> float:
    """校验超时秒数。

    :param value: 秒。
    :param maximum: 上限。
    :returns: 原值。
    :raises ZtError: 非正数或超上限（``invalid_timeout``）。
    """
    if value <= 0 or (maximum is not None and value > maximum):
        raise ZtError("invalid_timeout", f"超时必须在 0–{maximum} 秒之间：{value}")
    return value
