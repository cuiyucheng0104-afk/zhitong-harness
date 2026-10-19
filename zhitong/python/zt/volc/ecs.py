"""ECS 实例查询与启停（``ve ecs ...``）。

用到的 OpenAPI（volcengine-go-sdk ``service/ecs``）：``DescribeInstances``（``InstanceIds.N``、``Status``、
``InstanceName``、``MaxResults``、``NextToken``）、``StartInstance``/``StopInstance``/``RebootInstance``
（必填 ``InstanceId``，``StopInstance``/``RebootInstance`` 可选 ``ForceStop``）。
停止与重启会中断服务，需要 ``--yes``；启动不需要。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Optional

from zt.common.envelope import Envelope, WarningItem, WarningLevel, ok, partial
from zt.common.errors import ZtError
from zt.volc.confirm import require_confirmation
from zt.volc.ve import Ve

PAGE_SIZE = 100
MAX_PAGES = 20

_TARGET = {"start": "RUNNING", "stop": "STOPPED", "reboot": "RUNNING"}
_ACTION = {"start": "StartInstance", "stop": "StopInstance", "reboot": "RebootInstance"}
_NEEDS_YES = {"start": False, "stop": True, "reboot": True}


def summarize(inst: dict[str, Any]) -> dict[str, Any]:
    """把 ``DescribeInstances`` 的一个实例压缩成常用字段。

    :param inst: 响应里的实例对象。
    :returns: ``instance_id``、``name``、``status``、``zone_id``、``private_ip``、``public_ip``、``security_group_ids``。
    """
    nics = [n for n in inst.get("NetworkInterfaces") or [] if isinstance(n, dict)]
    eip = inst.get("EipAddress") if isinstance(inst.get("EipAddress"), dict) else {}
    sgs: list[str] = []
    for nic in nics:
        for sg in nic.get("SecurityGroupIds") or []:
            if sg not in sgs:
                sgs.append(sg)
    return {
        "instance_id": inst.get("InstanceId"),
        "name": inst.get("InstanceName"),
        "status": inst.get("Status"),
        "zone_id": inst.get("ZoneId"),
        "private_ip": nics[0].get("PrimaryIpAddress") if nics else None,
        "public_ip": eip.get("IpAddress") or None,
        "security_group_ids": sgs,
    }


def list_instances(ve: Ve, *, status: Optional[str] = None, name: Optional[str] = None) -> tuple[list[dict[str, Any]], bool]:
    """分页列出实例。

    :param ve: ``ve`` 调用器。
    :param status: 按状态过滤（如 ``RUNNING``）。
    :param name: 按实例名过滤。
    :returns: ``(实例摘要列表, 是否因页数上限被截断)``。
    """
    items: list[dict[str, Any]] = []
    token = ""
    for _ in range(MAX_PAGES):
        params: dict[str, Any] = {"MaxResults": PAGE_SIZE}
        if status:
            params["Status"] = status.upper()
        if name:
            params["InstanceName"] = name
        if token:
            params["NextToken"] = token
        result = ve.call("ecs", "DescribeInstances", params)
        items += [summarize(i) for i in result.get("Instances") or [] if isinstance(i, dict)]
        token = result.get("NextToken") or ""
        if not token:
            return items, False
    return items, True


def get_instance(ve: Ve, instance_id: str) -> dict[str, Any]:
    """查一台实例。

    :param ve: ``ve`` 调用器。
    :param instance_id: 实例 ID。
    :returns: 实例摘要。
    :raises ZtError: 实例不存在（``instance_not_found``）。
    """
    result = ve.call("ecs", "DescribeInstances", {"InstanceIds": [instance_id]})
    found = [i for i in result.get("Instances") or [] if isinstance(i, dict) and i.get("InstanceId") == instance_id]
    if not found:
        raise ZtError("instance_not_found", f"当前 profile/region 下没有实例 {instance_id}。",
                      hint="核对 profile 与 region（ecs-list 可列出可见实例）")
    return summarize(found[0])


def list_envelope(ve: Ve, *, status: Optional[str], name: Optional[str]) -> Envelope:
    """``ecs-list`` 的信封。

    :param ve: ``ve`` 调用器。
    :param status: 状态过滤。
    :param name: 名称过滤。
    :returns: ``ok``；无实例时仍是 ``ok`` 且 ``instances`` 为空列表并带 ``total``。
    """
    items, truncated = list_instances(ve, status=status, name=name)
    data = {"instances": items, "total": len(items)}
    if truncated:
        return partial(data, coverage={"pages": MAX_PAGES, "page_size": PAGE_SIZE, "listed": len(items)},
                       warnings=[WarningItem(code="listing_truncated", level=WarningLevel.WARN,
                                             message=f"实例超过 {MAX_PAGES * PAGE_SIZE} 台，只列出前 {len(items)} 台。",
                                             hint="加 --status 或 --name 缩小范围")])
    return ok(data)


def status_envelope(ve: Ve, instance_id: str) -> Envelope:
    """``ecs-status`` 的信封。

    :param ve: ``ve`` 调用器。
    :param instance_id: 实例 ID（已校验）。
    :returns: ``ok``，``data.instance`` 为摘要。
    """
    return ok({"instance": get_instance(ve, instance_id)})


def power_envelope(
    ve: Ve,
    op: str,
    instance_id: str,
    *,
    yes: bool,
    dry_run: bool,
    force_stop: bool = False,
    wait_seconds: float = 0,
    poll_interval: float = 5,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Envelope:
    """启动、停止或重启实例。

    先查当前状态：已在目标状态则不调用写接口；状态不允许（如启动中途的停止）直接报错。
    ``--dry-run`` 只返回将执行的命令；停止与重启没有 ``--yes`` 时报 ``confirmation_required``。

    :param ve: ``ve`` 调用器。
    :param op: ``start`` / ``stop`` / ``reboot``。
    :param instance_id: 实例 ID（已校验）。
    :param yes: 已显式确认。
    :param dry_run: 只出计划。
    :param force_stop: 强制关机（仅 stop/reboot），不让系统正常关闭。
    :param wait_seconds: 大于 0 时轮询到目标状态，最多等这么久。
    :param poll_interval: 轮询间隔秒。
    :param sleep: 睡眠函数（测试替换）。
    :param clock: 单调时钟（测试替换）。
    :returns: ``ok``；等待超时为 ``partial``。
    :raises ZtError: 实例不存在、状态不允许、缺少确认。
    """
    if force_stop and op == "start":
        raise ZtError("invalid_option", "--force-stop 只用于 stop 与 reboot。")
    before = get_instance(ve, instance_id)
    status = str(before["status"] or "").upper()
    target = _TARGET[op]

    if (op == "start" and status == "RUNNING") or (op == "stop" and status == "STOPPED"):
        return ok({"changed": False, "reason": f"already_{status.lower()}", "instance": before})
    if status != ("STOPPED" if op == "start" else "RUNNING"):
        raise ZtError("instance_state_conflict", f"实例 {instance_id} 当前状态 {status or '未知'}，不能执行 {op}。",
                      hint="等待状态稳定（STARTING/STOPPING 等是过渡态）后用 ecs-status 复查")

    params: dict[str, Any] = {"InstanceId": instance_id}
    if force_stop:
        params["ForceStop"] = True
    plan = ve.argv("ecs", _ACTION[op], params, confirm=False)
    label = f"{op} 实例 {instance_id}（{before['name']}，当前 {status}）" + ("，强制关机" if force_stop else "")
    if dry_run:
        return ok({"dry_run": True, "would": label, "command": plan, "needs_yes": _NEEDS_YES[op], "instance": before})
    if _NEEDS_YES[op]:
        require_confirmation(yes=yes, summary=f"{label}会中断该机器上的服务")

    ve.call("ecs", _ACTION[op], params, confirm=yes and _NEEDS_YES[op])
    data: dict[str, Any] = {"changed": True, "requested": op, "target_status": target, "instance": before}
    if wait_seconds <= 0:
        return ok(data)

    deadline = clock() + wait_seconds
    after = before
    while True:
        after = get_instance(ve, instance_id)
        if str(after["status"] or "").upper() == target:
            return ok({**data, "instance": after, "waited": True})
        if clock() >= deadline:
            break
        sleep(poll_interval)
    return partial(
        {**data, "instance": after},
        coverage={"target_status": target, "last_status": after["status"], "waited_seconds": wait_seconds},
        warnings=[WarningItem(code="wait_timeout", level=WarningLevel.WARN,
                              message=f"等待 {wait_seconds:g} 秒后实例仍为 {after['status']}，请求已发出但未到 {target}。",
                              hint="稍后用 ecs-status 复查；不要重复发请求")],
    )
