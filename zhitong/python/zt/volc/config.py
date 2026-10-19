"""zt-volc 的运行设置：profile、region、ve/ssh 可执行文件、可用的 SSH 主机别名。

只从环境变量与配置文件路径读取**名称**，从不读取、保存或回显密钥值：

==========================  ===========================================================================
环境变量                    含义
==========================  ===========================================================================
``ZT_VOLC_PROFILE``         ``ve --profile`` 的 profile 名；命令行 ``--profile`` 优先
``ZT_VOLC_REGION``          ``ve --region``；可选
``ZT_VOLC_CONFIG``          配置文件路径（客户配置包 ``zhitong.config.json`` 的 JSON 形态）；只读其中
                            ``volc.profile``、``volc.region``、``ssh.hosts[].alias``，其余字段（含密钥）不读取
``ZT_SSH_CONFIG``           OpenSSH 配置文件路径；默认 ``~/.ssh/config``，只读 ``Host`` 行的别名
``ZT_VE_BIN``               ``ve`` 可执行文件；默认 ``ve``
``ZT_SSH_BIN``              ``ssh`` 可执行文件；默认 ``ssh``
``ZT_PUBLIC_IP_URL``        ``sg-sync-ip`` 探测当前公网 IP 的地址；可被 ``--ip-url`` 覆盖
==========================  ===========================================================================
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from zt.common.errors import ZtError

ENV_PROFILE = "ZT_VOLC_PROFILE"
ENV_REGION = "ZT_VOLC_REGION"
ENV_CONFIG = "ZT_VOLC_CONFIG"
ENV_SSH_CONFIG = "ZT_SSH_CONFIG"
ENV_VE_BIN = "ZT_VE_BIN"
ENV_SSH_BIN = "ZT_SSH_BIN"
ENV_PUBLIC_IP_URL = "ZT_PUBLIC_IP_URL"

_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PROFILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_REGION_RE = re.compile(r"^[a-z]{2}-[a-z0-9-]{3,30}$")


@dataclass(frozen=True)
class VolcSettings:
    """一次调用的设置。

    :ivar ve_bin: ``ve`` 可执行文件。
    :ivar ssh_bin: ``ssh`` 可执行文件。
    :ivar profile: ``ve`` profile 名；未配置时为 None（调用 ``ve`` 前用 :meth:`require_profile` 检查）。
    :ivar region: ``ve`` region；None 表示沿用 profile 里的值。
    :ivar ssh_aliases: 允许登录的主机别名（配置文件与 ssh 配置的并集）。
    :ivar public_ip_url: 探测公网 IP 的地址。
    """

    ve_bin: str = "ve"
    ssh_bin: str = "ssh"
    profile: Optional[str] = None
    region: Optional[str] = None
    ssh_aliases: tuple[str, ...] = field(default_factory=tuple)
    public_ip_url: Optional[str] = None

    def require_profile(self) -> str:
        """返回 profile 名。

        :returns: profile 名。
        :raises ZtError: 未配置（``volc_profile_missing``）。
        """
        if not self.profile:
            raise ZtError(
                "volc_profile_missing",
                "没有配置火山引擎 profile 名。",
                hint=f"传 --profile，或设置环境变量 {ENV_PROFILE}，或在 {ENV_CONFIG} 指向的配置文件里写 volc.profile。",
            )
        return self.profile


def load_settings(
    *,
    profile: Optional[str] = None,
    region: Optional[str] = None,
    config: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> VolcSettings:
    """合并命令行、环境变量与配置文件，得到设置。优先级：命令行 > 环境变量 > 配置文件。

    :param profile: 命令行 ``--profile``。
    :param region: 命令行 ``--region``。
    :param config: 命令行 ``--config``（配置文件路径）。
    :param env: 环境变量映射；默认 ``os.environ``。
    :returns: 设置。
    :raises ZtError: 配置文件不可读或字段不合法。
    """
    environ = os.environ if env is None else env
    config_path = config or environ.get(ENV_CONFIG)
    file_profile, file_region, file_aliases = _read_config_names(Path(config_path)) if config_path else (None, None, ())
    chosen_profile = profile or environ.get(ENV_PROFILE) or file_profile
    chosen_region = region or environ.get(ENV_REGION) or file_region
    if chosen_profile is not None and not _PROFILE_RE.match(chosen_profile):
        raise ZtError("invalid_profile", f"profile 名不合法：{chosen_profile!r}", hint="只允许字母、数字、_ . -，且不能以符号开头")
    if chosen_region is not None and not _REGION_RE.match(chosen_region):
        raise ZtError("invalid_region", f"region 不合法：{chosen_region!r}", hint="形如 cn-beijing")
    ssh_config_path = environ.get(ENV_SSH_CONFIG) or str(Path.home() / ".ssh" / "config")
    aliases = tuple(dict.fromkeys([*file_aliases, *_read_ssh_config_aliases(Path(ssh_config_path))]))
    return VolcSettings(
        ve_bin=environ.get(ENV_VE_BIN) or "ve",
        ssh_bin=environ.get(ENV_SSH_BIN) or "ssh",
        profile=chosen_profile,
        region=chosen_region,
        ssh_aliases=aliases,
        public_ip_url=environ.get(ENV_PUBLIC_IP_URL) or None,
    )


def _read_config_names(path: Path) -> tuple[Optional[str], Optional[str], tuple[str, ...]]:
    """只取配置文件里的名称字段；其余内容（含密钥）读入后即丢弃。"""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ZtError("config_unreadable", f"读不了配置文件 {path}：{type(exc).__name__}",
                      hint=f"检查 {ENV_CONFIG} 或 --config 指向的路径；zip 形态的配置包请先解压出 zhitong.config.json") from None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ZtError("config_invalid", f"配置文件 {path} 不是合法 JSON（第 {exc.lineno} 行）。") from None
    if not isinstance(doc, dict):
        raise ZtError("config_invalid", f"配置文件 {path} 顶层必须是对象。")
    volc = doc.get("volc") if isinstance(doc.get("volc"), dict) else {}
    ssh = doc.get("ssh") if isinstance(doc.get("ssh"), dict) else {}
    profile = volc.get("profile") if isinstance(volc.get("profile"), str) else None
    region = volc.get("region") if isinstance(volc.get("region"), str) else None
    aliases: list[str] = []
    for host in ssh.get("hosts", []) if isinstance(ssh.get("hosts"), list) else []:
        alias = host.get("alias") if isinstance(host, dict) else None
        if isinstance(alias, str) and _ALIAS_RE.match(alias):
            aliases.append(alias)
    return profile, region, tuple(aliases)


def _read_ssh_config_aliases(path: Path) -> tuple[str, ...]:
    """读 OpenSSH 配置的 ``Host`` 行；含通配符与取反的模式不算别名。文件不存在时返回空。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()
    aliases: list[str] = []
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "host":
            for name in parts[1].split("#", 1)[0].split():
                if _ALIAS_RE.match(name):
                    aliases.append(name)
    return tuple(aliases)
