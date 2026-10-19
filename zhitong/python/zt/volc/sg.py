"""VPC 安全组入方向白名单（``ve vpc ...``），含 ``ssh-access-sync.sh`` 的同步逻辑。

用到的 OpenAPI（volcengine-go-sdk ``service/vpc``，版本 2020-04-01）：

- ``DescribeSecurityGroupAttributes``：``SecurityGroupId`` 必填；返回 ``Permissions[]``，每条含
  ``Direction``、``Protocol``、``PortStart``、``PortEnd``、``CidrIp``、``Policy``、``Priority``、``Description``。
- ``AuthorizeSecurityGroupIngress`` / ``RevokeSecurityGroupIngress``：``SecurityGroupId``、``Protocol``、
  ``PortStart``、``PortEnd`` 必填；可选 ``CidrIp``、``Description``、``Policy``、``Priority``。

改安全组一律需要 ``--yes``；撤销前必须在现有规则里找到完全匹配的一条，找不到就报错，不凭输入盲撤。
"""
from __future__ import annotations

import ipaddress
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from zt.common.envelope import Envelope, WarningItem, WarningLevel, ok, partial
from zt.common.errors import ZtError
from zt.volc import validate
from zt.volc.confirm import require_confirmation
from zt.volc.ve import Ve

DEFAULT_MARKER = "zt-ssh-sync"
_IP_RESPONSE_LIMIT = 256

Opener = Callable[..., Any]


def normalize_rule(perm: dict[str, Any]) -> dict[str, Any]:
    """把 ``Permissions[]`` 的一项整理成稳定字段。

    :param perm: 响应里的规则对象。
    :returns: ``direction``、``protocol``、``port_start``、``port_end``、``cidr_ip``、``policy``、``priority``、
        ``description``、``source_group_id``。
    """
    return {
        "direction": str(perm.get("Direction") or "").lower(),
        "protocol": str(perm.get("Protocol") or "").lower(),
        "port_start": perm.get("PortStart"),
        "port_end": perm.get("PortEnd"),
        "cidr_ip": perm.get("CidrIp") or None,
        "policy": str(perm.get("Policy") or "").lower() or None,
        "priority": perm.get("Priority"),
        "description": perm.get("Description") or "",
        "source_group_id": perm.get("SourceGroupId") or None,
    }


def describe_group(ve: Ve, sg_id: str) -> dict[str, Any]:
    """查安全组及其全部规则。

    :param ve: ``ve`` 调用器。
    :param sg_id: 安全组 ID（已校验）。
    :returns: ``{"security_group_id", "name", "vpc_id", "status", "rules": [...]}``。
    :raises ZtError: 响应里没有该安全组。
    """
    result = ve.call("vpc", "DescribeSecurityGroupAttributes", {"SecurityGroupId": sg_id})
    if result.get("SecurityGroupId") != sg_id:
        raise ZtError("sg_not_found", f"当前 profile/region 下没有安全组 {sg_id}。", hint="核对 profile 与 region")
    return {
        "security_group_id": sg_id,
        "name": result.get("SecurityGroupName"),
        "vpc_id": result.get("VpcId"),
        "status": result.get("Status"),
        "rules": [normalize_rule(p) for p in result.get("Permissions") or [] if isinstance(p, dict)],
    }


def _same_cidr(a: Optional[str], b: str) -> bool:
    if a is None:
        return False
    try:
        return ipaddress.ip_network(a, strict=False) == ipaddress.ip_network(b, strict=False)
    except ValueError:
        return False


def find_rule(rules: list[dict[str, Any]], *, protocol: str, port_start: int, port_end: int, cidr_ip: str) -> Optional[dict[str, Any]]:
    """在现有入方向规则里找完全匹配（协议、端口段、CIDR）的一条。

    :param rules: :func:`normalize_rule` 的结果列表。
    :param protocol: 小写协议。
    :param port_start: 起始端口。
    :param port_end: 结束端口。
    :param cidr_ip: CIDR。
    :returns: 匹配的规则；没有时 None。
    """
    for r in rules:
        if (r["direction"] == "ingress" and r["protocol"] == protocol and r["port_start"] == port_start
                and r["port_end"] == port_end and _same_cidr(r["cidr_ip"], cidr_ip)):
            return r
    return None


def show_envelope(ve: Ve, sg_id: str, *, direction: Optional[str]) -> Envelope:
    """``sg-show`` 的信封。

    :param ve: ``ve`` 调用器。
    :param sg_id: 安全组 ID。
    :param direction: ``ingress`` / ``egress`` 过滤；None 表示全部。
    :returns: ``ok``。
    """
    group = describe_group(ve, sg_id)
    if direction:
        group["rules"] = [r for r in group["rules"] if r["direction"] == direction]
    group["rule_count"] = len(group["rules"])
    return ok(group)


def _rule_params(sg_id: str, protocol: str, ps: int, pe: int, cidr_ip: str, *, description: Optional[str] = None,
                 policy: Optional[str] = None, priority: Optional[int] = None) -> dict[str, Any]:
    params: dict[str, Any] = {"SecurityGroupId": sg_id, "Protocol": protocol, "PortStart": ps, "PortEnd": pe, "CidrIp": cidr_ip}
    if description:
        params["Description"] = description
    if policy:
        params["Policy"] = policy
    if priority is not None:
        params["Priority"] = priority
    return params


def authorize_envelope(
    ve: Ve,
    sg_id: str,
    *,
    protocol: str,
    port_start: int,
    port_end: int,
    cidr_ip: str,
    description: Optional[str],
    policy: Optional[str],
    priority: Optional[int],
    yes: bool,
    dry_run: bool,
) -> Envelope:
    """新增一条入方向规则；同样的规则已存在时不重复添加。

    :param ve: ``ve`` 调用器。
    :param sg_id: 安全组 ID。
    :param protocol: 小写协议。
    :param port_start: 起始端口。
    :param port_end: 结束端口。
    :param cidr_ip: 已校验的 CIDR。
    :param description: 规则描述。
    :param policy: ``accept`` / ``drop``。
    :param priority: 优先级。
    :param yes: 已显式确认。
    :param dry_run: 只出计划。
    :returns: ``ok``。
    :raises ZtError: 缺少确认或 ``ve`` 失败。
    """
    group = describe_group(ve, sg_id)
    existing = find_rule(group["rules"], protocol=protocol, port_start=port_start, port_end=port_end, cidr_ip=cidr_ip)
    if existing is not None:
        return ok({"changed": False, "reason": "rule_already_present", "rule": existing})
    params = _rule_params(sg_id, protocol, port_start, port_end, cidr_ip, description=description, policy=policy, priority=priority)
    summary = f"在安全组 {sg_id}（{group['name']}）放行 {cidr_ip} 访问 {protocol} {port_start}-{port_end}"
    if dry_run:
        return ok({"dry_run": True, "would": summary, "command": ve.argv("vpc", "AuthorizeSecurityGroupIngress", params)})
    require_confirmation(yes=yes, summary=summary)
    ve.call("vpc", "AuthorizeSecurityGroupIngress", params, confirm=True)
    return ok({"changed": True, "added": {k: v for k, v in params.items() if k != "SecurityGroupId"}})


def revoke_envelope(
    ve: Ve,
    sg_id: str,
    *,
    protocol: str,
    port_start: int,
    port_end: int,
    cidr_ip: str,
    yes: bool,
    dry_run: bool,
) -> Envelope:
    """撤销一条入方向规则；必须在现有规则里找到完全匹配的一条。

    :param ve: ``ve`` 调用器。
    :param sg_id: 安全组 ID。
    :param protocol: 小写协议。
    :param port_start: 起始端口。
    :param port_end: 结束端口。
    :param cidr_ip: CIDR。
    :param yes: 已显式确认。
    :param dry_run: 只出计划。
    :returns: ``ok``。
    :raises ZtError: 规则不存在（``rule_not_found``）、缺少确认或 ``ve`` 失败。
    """
    group = describe_group(ve, sg_id)
    found = find_rule(group["rules"], protocol=protocol, port_start=port_start, port_end=port_end, cidr_ip=cidr_ip)
    if found is None:
        raise ZtError("rule_not_found", f"安全组 {sg_id} 没有匹配的入方向规则：{protocol} {port_start}-{port_end} {cidr_ip}",
                      hint="用 sg-show 核对现有规则；协议、端口段、CIDR 必须完全一致")
    params = _rule_params(sg_id, protocol, port_start, port_end, found["cidr_ip"] or cidr_ip,
                          policy=found["policy"], priority=found["priority"])
    summary = (f"从安全组 {sg_id}（{group['name']}）撤销 {found['cidr_ip']} 访问 {protocol} {port_start}-{port_end} 的规则"
               f"（描述：{found['description'] or '无'}），该来源将立即失去访问")
    if dry_run:
        return ok({"dry_run": True, "would": summary, "command": ve.argv("vpc", "RevokeSecurityGroupIngress", params)})
    require_confirmation(yes=yes, summary=summary)
    ve.call("vpc", "RevokeSecurityGroupIngress", params, confirm=True)
    return ok({"changed": True, "revoked": found})


def detect_public_ip(url: str, *, timeout: float = 10.0, opener: Opener = urllib.request.urlopen) -> str:
    """从返回纯文本 IP 的地址取当前出口公网 IP。

    :param url: ``http(s)`` 地址。
    :param timeout: 超时秒数。
    :param opener: 打开 URL 的函数（测试替换）。
    :returns: 校验过的公网 IP 文本。
    :raises ZtError: 地址协议不对、请求失败或响应不是公网 IP。
    """
    if not url.lower().startswith(("http://", "https://")):
        raise ZtError("invalid_ip_url", f"探测地址必须是 http(s)：{url[:80]!r}")
    try:
        with opener(url, timeout=timeout) as resp:
            body = resp.read(_IP_RESPONSE_LIMIT).decode("ascii", errors="replace").strip()
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ZtError("public_ip_unreachable", f"探测公网 IP 失败：{type(exc).__name__}",
                      hint="改用 --ip 直接给出出口 IP") from None
    return validate.public_ip(body)


def sync_ip_envelope(
    ve: Ve,
    sg_id: str,
    *,
    ip: str,
    ports: list[int],
    protocol: str,
    marker: str,
    label: Optional[str],
    yes: bool,
    dry_run: bool,
) -> Envelope:
    """把当前公网 IP 同步进安全组白名单（``ssh-access-sync.sh`` 的功能）。

    规则描述 = ``marker``（有 ``label`` 时为 ``marker:label``）。对每个端口：已有同 IP 规则则跳过；
    否则先新增 ``ip/32``，全部新增成功后再撤销描述完全相同、端口在本次范围内、但 CIDR 不是当前 IP 的旧规则。
    只撤销自己标记的规则，不碰别人的；先加后撤，避免中途断连。描述不同的人用不同 ``label``。

    :param ve: ``ve`` 调用器。
    :param sg_id: 安全组 ID。
    :param ip: 已校验的公网 IP。
    :param ports: 要放行的单端口列表。
    :param protocol: 小写协议（通常 ``tcp``）。
    :param marker: 规则描述前缀。
    :param label: 可选标签，区分同一安全组里不同的人。
    :param yes: 已显式确认（有变更时才需要）。
    :param dry_run: 只出计划。
    :returns: ``ok``；新增成功但撤销旧规则失败时为 ``partial``。
    :raises ZtError: 缺少确认；新增失败（此时不撤销任何规则）。
    """
    cidr_ip = validate.host_cidr(ip)
    desc = marker if not label else f"{marker}:{label}"
    group = describe_group(ve, sg_id)
    to_add = [p for p in ports if find_rule(group["rules"], protocol=protocol, port_start=p, port_end=p, cidr_ip=cidr_ip) is None]
    stale = [r for r in group["rules"]
             if r["direction"] == "ingress" and r["description"] == desc and r["protocol"] == protocol
             and r["port_start"] == r["port_end"] and r["port_start"] in ports and not _same_cidr(r["cidr_ip"], cidr_ip)]
    base = {"security_group_id": sg_id, "ip": ip, "cidr": cidr_ip, "description": desc, "protocol": protocol, "ports": ports}
    if not to_add and not stale:
        return ok({**base, "changed": False, "reason": "already_in_sync"})

    add_cmds = [ve.argv("vpc", "AuthorizeSecurityGroupIngress", _rule_params(sg_id, protocol, p, p, cidr_ip, description=desc)) for p in to_add]
    revoke_params = [_rule_params(sg_id, protocol, r["port_start"], r["port_end"], r["cidr_ip"],
                                  policy=r["policy"], priority=r["priority"]) for r in stale]
    revoke_cmds = [ve.argv("vpc", "RevokeSecurityGroupIngress", p) for p in revoke_params]
    plan = {**base, "to_add_ports": to_add, "to_revoke": [{"cidr": r["cidr_ip"], "port": r["port_start"]} for r in stale]}
    summary = (f"安全组 {sg_id}（{group['name']}）：放行 {cidr_ip} 的 {protocol} 端口 {to_add or '（已有）'}"
               + (f"，并撤销本标记下的旧来源 {sorted({r['cidr_ip'] for r in stale})}" if stale else ""))
    if dry_run:
        return ok({**plan, "dry_run": True, "would": summary, "commands": [*add_cmds, *revoke_cmds]})
    require_confirmation(yes=yes, summary=summary)

    added: list[int] = []
    for p in to_add:
        try:
            ve.call("vpc", "AuthorizeSecurityGroupIngress", _rule_params(sg_id, protocol, p, p, cidr_ip, description=desc), confirm=True)
        except ZtError as exc:
            raise ZtError(exc.code, f"{exc.message}（已新增端口 {added or '无'}，未撤销任何旧规则）", hint=exc.hint) from None
        added.append(p)

    revoked: list[dict[str, Any]] = []
    for r, params in zip(stale, revoke_params):
        try:
            ve.call("vpc", "RevokeSecurityGroupIngress", params, confirm=True)
        except ZtError as exc:
            return partial(
                {**plan, "changed": True, "added_ports": added, "revoked": revoked},
                coverage={"revoke_planned": len(stale), "revoke_done": len(revoked)},
                warnings=[WarningItem(code="stale_rule_revoke_failed", level=WarningLevel.ERROR,
                                      message=f"新 IP 已放行，但撤销旧规则 {r['cidr_ip']} 端口 {r['port_start']} 失败：{exc.message}",
                                      hint="旧 IP 仍有访问权；用 sg-show 核对后，经用户确认再 sg-revoke")],
            )
        revoked.append({"cidr": r["cidr_ip"], "port": r["port_start"]})
    return ok({**plan, "changed": True, "added_ports": added, "revoked": revoked})
