"""``python -m zt.volc.cli <子命令>``：火山引擎运维。

子命令（凡写操作都有 ``--dry-run`` 出计划，需要确认的操作没有 ``--yes`` 以退出码 2 结束）::

    whoami                                     验证 profile（ve sts GetCallerIdentity）
    ecs-list / ecs-status / ecs-start / ecs-stop / ecs-reboot
    sg-show / sg-authorize / sg-revoke / sg-sync-ip
    tos-buckets / tos-stat / tos-ls / tos-lifecycle / tos-versioning
    ssh-hosts / ssh-exec

公共选项：``--profile`` ``--region`` ``--config``（名称来源见 :mod:`zt.volc.config`）、``--timeout``。
"""
from __future__ import annotations

import argparse

from zt.common.cli import Call, Cli
from zt.common.envelope import Envelope, ok
from zt.common.errors import ZtError
from zt.volc import ecs, sg, ssh, tos, validate
from zt.volc.config import VolcSettings, load_settings
from zt.volc.ve import Ve

cli = Cli("zt.volc", "火山引擎运维：ve CLI 与 SSH 封装")


def _common(p: argparse.ArgumentParser, *, ve: bool = True) -> None:
    p.add_argument("--profile", help="ve profile 名（默认取 ZT_VOLC_PROFILE 或配置文件）")
    p.add_argument("--region", help="region，如 cn-beijing（默认沿用 profile）")
    p.add_argument("--config", help="配置文件路径（默认取 ZT_VOLC_CONFIG）")
    p.add_argument("--timeout", type=float, default=60.0, help="单次子进程超时秒数，默认 60")


def _write(p: argparse.ArgumentParser) -> None:
    p.add_argument("--yes", action="store_true", help="用户已确认，执行该操作")
    p.add_argument("--dry-run", action="store_true", help="只输出将执行的命令，不执行")


def _settings(call: Call) -> VolcSettings:
    a = call.args
    return load_settings(profile=a.profile, region=a.region, config=a.config)


def _ve(call: Call) -> Ve:
    return Ve(_settings(call), timeout=validate.timeout_seconds(call.args.timeout))


@cli.command("whoami", help="验证 profile：ve sts GetCallerIdentity", arguments=_common)
def whoami(call: Call) -> Envelope:
    ve = _ve(call)
    result = ve.call("sts", "GetCallerIdentity")
    if not result:
        raise ZtError("ve_bad_output", "GetCallerIdentity 没有返回 Result。")
    return ok({"profile": ve.settings.profile, "region": ve.settings.region, "identity": result})


def _ecs_list_args(p: argparse.ArgumentParser) -> None:
    _common(p)
    p.add_argument("--status", help="按状态过滤，如 RUNNING / STOPPED")
    p.add_argument("--name", help="按实例名过滤")


@cli.command("ecs-list", help="列出 ECS 实例", arguments=_ecs_list_args)
def ecs_list(call: Call) -> Envelope:
    return ecs.list_envelope(_ve(call), status=call.args.status, name=call.args.name)


def _instance_args(p: argparse.ArgumentParser) -> None:
    _common(p)
    p.add_argument("--instance-id", required=True, help="实例 ID（i-…）")


@cli.command("ecs-status", help="查一台 ECS 实例的状态与绑定的安全组", arguments=_instance_args)
def ecs_status(call: Call) -> Envelope:
    return ecs.status_envelope(_ve(call), validate.instance_id(call.args.instance_id))


def _power_args(p: argparse.ArgumentParser) -> None:
    _instance_args(p)
    _write(p)
    p.add_argument("--force-stop", action="store_true", help="强制关机（stop/reboot）")
    p.add_argument("--wait", type=float, default=0, metavar="秒", help="轮询到目标状态，最多等这么久")
    p.add_argument("--poll-interval", type=float, default=5.0, help="轮询间隔秒，默认 5")


def _power(op: str, call: Call) -> Envelope:
    a = call.args
    if a.wait < 0 or a.poll_interval < 0:
        raise ZtError("invalid_timeout", "--wait 与 --poll-interval 不能为负。")
    return ecs.power_envelope(_ve(call), op, validate.instance_id(a.instance_id), yes=a.yes, dry_run=a.dry_run,
                              force_stop=a.force_stop, wait_seconds=a.wait, poll_interval=a.poll_interval)


@cli.command("ecs-start", help="启动实例（无需 --yes）", arguments=_power_args)
def ecs_start(call: Call) -> Envelope:
    return _power("start", call)


@cli.command("ecs-stop", help="停止实例（需要 --yes）", arguments=_power_args)
def ecs_stop(call: Call) -> Envelope:
    return _power("stop", call)


@cli.command("ecs-reboot", help="重启实例（需要 --yes）", arguments=_power_args)
def ecs_reboot(call: Call) -> Envelope:
    return _power("reboot", call)


def _sg_show_args(p: argparse.ArgumentParser) -> None:
    _common(p)
    p.add_argument("--sg-id", required=True, help="安全组 ID（sg-…）")
    p.add_argument("--direction", choices=["ingress", "egress"], help="只看一个方向")


@cli.command("sg-show", help="查看安全组规则", arguments=_sg_show_args)
def sg_show(call: Call) -> Envelope:
    return sg.show_envelope(_ve(call), validate.security_group_id(call.args.sg_id), direction=call.args.direction)


def _rule_args(p: argparse.ArgumentParser, *, authorize: bool) -> None:
    _common(p)
    _write(p)
    p.add_argument("--sg-id", required=True, help="安全组 ID（sg-…）")
    p.add_argument("--protocol", required=True, help="tcp / udp / icmp / all")
    p.add_argument("--port-start", type=int, required=True)
    p.add_argument("--port-end", type=int, required=True)
    p.add_argument("--cidr", required=True, help="来源 CIDR，如 203.0.113.7/32")
    if authorize:
        p.add_argument("--description", help="规则描述")
        p.add_argument("--policy", help="accept / drop")
        p.add_argument("--priority", type=int, help="优先级 1–100")
        p.add_argument("--allow-world", action="store_true", help="允许 /0 全网段（须用户明确同意）")


def _rule_common(call: Call, *, allow_world: bool) -> tuple[str, str, int, int, str]:
    a = call.args
    proto = validate.protocol(a.protocol)
    ps, pe = validate.port_range(proto, a.port_start, a.port_end)
    return validate.security_group_id(a.sg_id), proto, ps, pe, validate.cidr(a.cidr, allow_world=allow_world)


@cli.command("sg-authorize", help="新增入方向规则（需要 --yes）", arguments=lambda p: _rule_args(p, authorize=True))
def sg_authorize(call: Call) -> Envelope:
    a = call.args
    sg_id, proto, ps, pe, cidr = _rule_common(call, allow_world=a.allow_world)
    return sg.authorize_envelope(
        _ve(call), sg_id, protocol=proto, port_start=ps, port_end=pe, cidr_ip=cidr,
        description=validate.description(a.description) if a.description else None,
        policy=validate.policy(a.policy) if a.policy else None,
        priority=validate.priority(a.priority) if a.priority is not None else None,
        yes=a.yes, dry_run=a.dry_run)


@cli.command("sg-revoke", help="撤销入方向规则（需要 --yes）", arguments=lambda p: _rule_args(p, authorize=False))
def sg_revoke(call: Call) -> Envelope:
    a = call.args
    sg_id, proto, ps, pe, cidr = _rule_common(call, allow_world=True)
    return sg.revoke_envelope(_ve(call), sg_id, protocol=proto, port_start=ps, port_end=pe, cidr_ip=cidr,
                              yes=a.yes, dry_run=a.dry_run)


def _sync_args(p: argparse.ArgumentParser) -> None:
    _common(p)
    _write(p)
    p.add_argument("--sg-id", required=True, help="安全组 ID（sg-…）")
    p.add_argument("--ports", default="22", help="逗号分隔的端口，默认 22")
    p.add_argument("--protocol", default="tcp", help="默认 tcp")
    p.add_argument("--ip", help="要放行的公网 IP；不给则用 --ip-url / ZT_PUBLIC_IP_URL 探测")
    p.add_argument("--ip-url", help="返回纯文本公网 IP 的 http(s) 地址")
    p.add_argument("--marker", default=sg.DEFAULT_MARKER, help=f"规则描述前缀，默认 {sg.DEFAULT_MARKER}")
    p.add_argument("--label", help="区分同一安全组里不同人的标签")


@cli.command("sg-sync-ip", help="把当前公网 IP 同步进安全组白名单", arguments=_sync_args)
def sg_sync_ip(call: Call) -> Envelope:
    a = call.args
    settings = _settings(call)
    sg_id = validate.security_group_id(a.sg_id)
    proto = validate.protocol(a.protocol)
    ports = validate.ports_list(a.ports)
    marker = validate.label(a.marker)
    label = validate.label(a.label) if a.label else None
    if a.ip:
        ip = validate.public_ip(a.ip)
    else:
        url = a.ip_url or settings.public_ip_url
        if not url:
            raise ZtError("public_ip_unknown", "没有给出要放行的 IP。",
                          hint="传 --ip，或 --ip-url / 环境变量 ZT_PUBLIC_IP_URL 指向返回纯文本 IP 的地址")
        ip = sg.detect_public_ip(url, timeout=min(validate.timeout_seconds(a.timeout), 30))
    return sg.sync_ip_envelope(Ve(settings, timeout=validate.timeout_seconds(a.timeout)), sg_id, ip=ip, ports=ports,
                               protocol=proto, marker=marker, label=label, yes=a.yes, dry_run=a.dry_run)


@cli.command("tos-buckets", help="列出可见的 TOS 桶（只读）", arguments=_common)
def tos_buckets(call: Call) -> Envelope:
    return tos.buckets_envelope(_ve(call))


def _bucket_args(p: argparse.ArgumentParser) -> None:
    _common(p)
    p.add_argument("--bucket", required=True, help="桶名")


@cli.command("tos-stat", help="桶的基本信息（只读）", arguments=_bucket_args)
def tos_stat(call: Call) -> Envelope:
    return tos.stat_envelope(_ve(call), validate.bucket_name(call.args.bucket))


def _ls_args(p: argparse.ArgumentParser) -> None:
    _bucket_args(p)
    p.add_argument("--prefix", default="", help="对象前缀")


@cli.command("tos-ls", help="列桶内对象（只读，最多 200 行）", arguments=_ls_args)
def tos_ls(call: Call) -> Envelope:
    return tos.ls_envelope(_ve(call), validate.bucket_name(call.args.bucket), validate.object_prefix(call.args.prefix))


@cli.command("tos-lifecycle", help="查看桶的生命周期配置（只读）", arguments=_bucket_args)
def tos_lifecycle(call: Call) -> Envelope:
    return tos.config_envelope(_ve(call), "lifecycle", validate.bucket_name(call.args.bucket))


@cli.command("tos-versioning", help="查看桶的版本控制状态（只读）", arguments=_bucket_args)
def tos_versioning(call: Call) -> Envelope:
    return tos.config_envelope(_ve(call), "versioning", validate.bucket_name(call.args.bucket))


@cli.command("ssh-hosts", help="列出可用的 SSH 主机别名", arguments=lambda p: _common(p))
def ssh_hosts(call: Call) -> Envelope:
    return ssh.hosts_envelope(_settings(call))


def _exec_args(p: argparse.ArgumentParser) -> None:
    _common(p)
    _write(p)
    p.add_argument("--host", required=True, help="主机别名（见 ssh-hosts）")
    # dest 不能是 command：它是 Cli 基类子命令分发用的属性名。
    p.add_argument("--command", dest="remote_command", required=True, help="远端命令；只读白名单命令免确认，其他需要 --yes")
    p.add_argument("--max-output-bytes", type=int, default=ssh.DEFAULT_MAX_OUTPUT_BYTES, help="stdout/stderr 各自保留上限")


@cli.command("ssh-exec", help="在服务器上执行命令", arguments=_exec_args)
def ssh_exec(call: Call) -> Envelope:
    a = call.args
    if a.max_output_bytes < 1:
        raise ZtError("invalid_option", "--max-output-bytes 必须为正。")
    return ssh.exec_envelope(_settings(call), a.host, a.remote_command, yes=a.yes, dry_run=a.dry_run,
                             timeout=validate.timeout_seconds(a.timeout), max_output_bytes=a.max_output_bytes)


if __name__ == "__main__":
    raise SystemExit(cli.main())
