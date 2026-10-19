"""SSH 到生产服务器执行命令（``pssh`` 的功能）：用 ``~/.ssh/config`` 里的主机别名，不经本机 shell。

- 别名必须出现在配置文件的 ``ssh.hosts[].alias`` 或 OpenSSH 配置的 ``Host`` 行里（:mod:`zt.volc.config`）；
  地址、端口、用户、密钥全部由 OpenSSH 配置决定，本模块从不接触。
- 连接参数 ``BatchMode=yes``（不弹口令提示，失败即失败）与 ``ConnectTimeout``；``--`` 位于主机之前，
  别名不可能被当成选项。
- 只读命令（见 ``_READONLY``）直接执行；其他命令、含重定向/命令替换/后台符的命令需要 ``--yes``。
  这是便利性分级，不是沙箱：远端命令以登录用户的权限运行。
"""
from __future__ import annotations

import shlex
import subprocess
from typing import Any, Callable, Sequence

from zt.common.envelope import Envelope, WarningItem, WarningLevel, ok
from zt.common.errors import ZtError
from zt.volc import validate
from zt.volc.config import VolcSettings
from zt.volc.confirm import require_confirmation
from zt.volc.ve import redact

CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_OUTPUT_BYTES = 65536
SSH_CONNECT_FAILURE = 255

Runner = Callable[..., "subprocess.CompletedProcess[bytes]"]

_READONLY = frozenset({
    "ls", "cat", "head", "tail", "wc", "grep", "sort", "cut", "tr", "df", "du", "free", "uptime", "ps", "pgrep",
    "whoami", "id", "date", "uname", "pwd", "stat", "ss", "nproc", "lsblk", "journalctl", "echo",
})
# 白名单命令里会写文件或改系统状态的选项前缀；命中即降为需要确认。
_MUTATING_OPTIONS = {
    "sort": ("-o", "--output"),
    "date": ("-s", "--set"),
    "journalctl": ("--vacuum", "--rotate", "--flush", "--sync", "--relinquish"),
}
_READONLY_SUBCOMMANDS = {
    "docker": frozenset({"ps", "logs", "images", "stats", "version", "info"}),
    "systemctl": frozenset({"status", "is-active", "is-enabled", "list-units", "list-unit-files"}),
}
_FOLLOW_FLAGS = frozenset({"-f", "--follow"})
_FOLLOWING = frozenset({"tail", "journalctl"})
_SHELL_META = ("`", "$(", ">", "<", "\n", "&", "${")
_SEPARATORS = ("||", "&&", ";", "|")


def classify(command: str) -> tuple[bool, str]:
    """判断命令是否为只读白名单内的命令。

    :param command: 远端命令文本。
    :returns: ``(是否只读, 原因)``。非只读的原因用于确认提示。
    :raises ZtError: 为空，或要持续跟随输出（``tail -f`` 等，会一直挂到超时）。
    """
    text = command.strip()
    if not text:
        raise ZtError("empty_command", "远端命令不能为空。")
    if any(m in text.replace("&&", "") for m in _SHELL_META):
        return False, "含重定向、命令替换或后台符"
    segments = [text]
    for sep in _SEPARATORS:
        segments = [part for seg in segments for part in seg.split(sep)]
    for seg in segments:
        try:
            tokens = shlex.split(seg)
        except ValueError:
            return False, "引号不成对，无法判断"
        if not tokens:
            return False, "含空的管道段"
        head, rest = tokens[0], tokens[1:]
        if head in _READONLY_SUBCOMMANDS:
            sub = next((t for t in rest if not t.startswith("-")), "")
            if sub not in _READONLY_SUBCOMMANDS[head]:
                return False, f"{head} {sub or '…'} 不在只读白名单"
        elif head not in _READONLY:
            return False, f"{head} 不在只读白名单"
        elif any(t.startswith(_MUTATING_OPTIONS.get(head, ())) for t in rest):
            return False, f"{head} 带有会写入或修改状态的选项"
        follows = _FOLLOW_FLAGS & set(rest)
        if follows and (head in _FOLLOWING or (head == "docker" and "logs" in rest)):
            raise ZtError("follow_not_supported", "不支持持续跟随输出（-f/--follow）。", hint="去掉 -f，用 tail -n 取最近若干行")
    return True, "只读命令"


def hosts_envelope(settings: VolcSettings) -> Envelope:
    """``ssh-hosts``：列出可用的主机别名。

    :param settings: 运行设置。
    :returns: ``ok``；没有别名时报错。
    :raises ZtError: 没有任何别名（``ssh_no_hosts``）。
    """
    if not settings.ssh_aliases:
        raise ZtError("ssh_no_hosts", "没有可用的 SSH 主机别名。",
                      hint="在 ~/.ssh/config 里配 Host，或设置 ZT_VOLC_CONFIG 指向含 ssh.hosts 的配置文件")
    return ok({"hosts": list(settings.ssh_aliases), "total": len(settings.ssh_aliases)})


def _decode(blob: bytes, limit: int) -> tuple[str, bool]:
    cut = blob[:limit]
    return redact(cut.decode("utf-8", errors="replace")), len(blob) > limit


def exec_envelope(
    settings: VolcSettings,
    alias: str,
    command: str,
    *,
    yes: bool,
    dry_run: bool,
    timeout: float = 60.0,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    runner: Runner = subprocess.run,
) -> Envelope:
    """在别名主机上执行一条命令。

    :param settings: 运行设置。
    :param alias: 主机别名。
    :param command: 远端命令（单个字符串，由远端 shell 解释）。
    :param yes: 已显式确认；非只读命令需要。
    :param dry_run: 只返回将执行的 ssh 命令与分级。
    :param timeout: 超时秒数（含连接）。
    :param max_output_bytes: stdout 与 stderr 各自的保留上限。
    :param runner: 子进程运行函数（测试替换）。
    :returns: ``ok``；远端退出码非零时仍是 ``ok``，但 ``data.exit_code`` 非零并带 ``remote_nonzero_exit`` 告警。
    :raises ZtError: 别名未知、缺少确认、ssh 不存在、连接失败（退出码 255）或超时。
    """
    validate.ssh_alias(alias)
    if alias not in settings.ssh_aliases:
        raise ZtError("ssh_host_unknown", f"别名 {alias!r} 不在可用主机里。",
                      hint=f"可用别名：{', '.join(settings.ssh_aliases) or '（无）'}；用 ssh-hosts 查看")
    readonly, why = classify(command)
    argv = [settings.ssh_bin, "-o", "BatchMode=yes", "-o", f"ConnectTimeout={CONNECT_TIMEOUT_SECONDS}", "--", alias, command]
    if dry_run:
        return ok({"dry_run": True, "alias": alias, "command": command, "readonly": readonly, "classification": why, "argv": argv})
    if not readonly:
        require_confirmation(yes=yes, summary=f"在 {alias} 上执行 `{command}`（{why}）")
    return _run(argv, alias, command, readonly, timeout, max_output_bytes, runner)


def _run(argv: Sequence[str], alias: str, command: str, readonly: bool, timeout: float, limit: int, runner: Runner) -> Envelope:
    try:
        proc = runner(list(argv), capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError:
        raise ZtError("ssh_not_found", f"找不到 ssh 可执行文件：{argv[0]}", hint="安装 OpenSSH 客户端，或用 ZT_SSH_BIN 指向它") from None
    except subprocess.TimeoutExpired:
        raise ZtError("ssh_timeout", f"在 {alias} 上执行超过 {timeout:g} 秒未返回。",
                      hint="远端命令可能仍在运行，先用只读命令（ps、journalctl）确认，不要直接重试写操作") from None
    stdout, out_cut = _decode(proc.stdout, limit)
    stderr, err_cut = _decode(proc.stderr, limit)
    if proc.returncode == SSH_CONNECT_FAILURE:
        raise ZtError("ssh_connect_failed", f"ssh 到 {alias} 失败：{stderr.strip()[-300:] or '（无 stderr）'}",
                      hint="白名单可能过期（先 sg-sync-ip）、密钥未加载或主机不可达")
    warnings: list[WarningItem] = []
    if proc.returncode != 0:
        warnings.append(WarningItem(code="remote_nonzero_exit", level=WarningLevel.WARN,
                                    message=f"远端命令退出码 {proc.returncode}。", hint="看 stderr；退出码非零不等于连接失败"))
    if out_cut or err_cut:
        warnings.append(WarningItem(code="output_truncated", level=WarningLevel.WARN,
                                    message=f"输出超过 {limit} 字节已截断。", hint="加 head/tail/grep 缩小输出"))
    data: dict[str, Any] = {"alias": alias, "command": command, "readonly": readonly, "exit_code": proc.returncode,
                            "stdout": stdout, "stderr": stderr, "stdout_truncated": out_cut, "stderr_truncated": err_cut}
    return ok(data, warnings=warnings)
