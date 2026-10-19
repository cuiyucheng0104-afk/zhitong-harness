"""``ve`` CLI 子进程封装（火山引擎官方 CLI，npm 包 ``@volcengine/cli``）。

调用形态（官方文档 docs/4-Usage-zh.md）::

    ve <service> <Action> --Param value ... [--profile P] [--region R] [--output json] [--yes]

- 参数名与值之间用空格，不写 ``--Param=value``；数组参数用 1 起的连续下标 ``--InstanceIds.1 i-x``。
- ``ve`` 的客户端安全策略（``ve configure safety-policy``）命中 ``confirm`` 时需要 ``--yes``；
  本封装只在调用方已完成自己的确认（``confirm=True``）后才追加 ``--yes``，且 ``--yes`` 绕不过 ``deny``。
- 响应是 ``{"ResponseMetadata": {...}, "Result": {...}}``；``ResponseMetadata.Error`` 存在即业务失败。
- 子进程不经 shell；stdout 只取 JSON，stderr 脱敏后才进入错误信息。
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence, Union

from zt.common.errors import ZtError
from zt.volc.config import VolcSettings

log = logging.getLogger("zt.volc.ve")

ParamValue = Union[str, int, bool, Sequence[str]]
Runner = Callable[..., "subprocess.CompletedProcess[bytes]"]

# 形如 AK/SK、令牌的长串与 --secret-key/--access-key 之后的值：错误信息里一律抹掉。
_SECRET_PATTERNS = (
    re.compile(r"(?i)(secret[-_ ]?key|access[-_ ]?key|session[-_ ]?token|password)(\s*[=:]?\s*)\S+"),
    re.compile(r"\bAK[A-Z]{2}[A-Za-z0-9]{12,}\b"),
)
_MAX_STDERR_CHARS = 600


def redact(text: str) -> str:
    """抹掉文本里形似密钥的片段。

    :param text: 任意文本（通常是子进程 stderr）。
    :returns: 脱敏后的文本。
    """
    out = text
    out = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", out)
    out = _SECRET_PATTERNS[1].sub("<redacted>", out)
    return out


def flatten_params(params: Mapping[str, ParamValue]) -> list[str]:
    """把参数字典展开成 ``ve`` 的 argv 片段。

    列表按 ``--Name.1 a --Name.2 b`` 展开，布尔写成 ``true``/``false``，整数转十进制。

    :param params: 参数名到值的映射；值为 None 的项由调用方事先剔除。
    :returns: argv 片段。
    """
    argv: list[str] = []
    for name, value in params.items():
        if isinstance(value, bool):
            argv += [f"--{name}", "true" if value else "false"]
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value, start=1):
                argv += [f"--{name}.{i}", str(item)]
        else:
            argv += [f"--{name}", str(value)]
    return argv


@dataclass(frozen=True)
class Ve:
    """绑定设置的 ``ve`` 调用器。

    :ivar settings: 运行设置（profile、region、可执行文件）。
    :ivar timeout: 单次子进程超时秒数。
    :ivar runner: 子进程运行函数；默认 :func:`subprocess.run`，测试可替换。
    """

    settings: VolcSettings
    timeout: float = 60.0
    runner: Runner = subprocess.run

    def argv(self, service: str, action: str, params: Mapping[str, ParamValue], *, confirm: bool = False) -> list[str]:
        """构造一次 OpenAPI 调用的完整 argv（不执行）；用于 ``--dry-run`` 展示。

        :param service: 服务名，如 ``ecs``、``vpc``。
        :param action: 动作名，如 ``DescribeInstances``。
        :param params: 动作参数。
        :param confirm: 调用方已确认时追加 ``--yes``。
        :returns: argv，首元素是 ``ve`` 可执行文件。
        :raises ZtError: 未配置 profile。
        """
        argv = [self.settings.ve_bin, service, action, "--profile", self.settings.require_profile()]
        if self.settings.region:
            argv += ["--region", self.settings.region]
        argv += flatten_params(params)
        argv += ["--output", "json"]
        if confirm:
            argv.append("--yes")
        return argv

    def call(self, service: str, action: str, params: Mapping[str, ParamValue] | None = None, *,
             confirm: bool = False) -> dict[str, Any]:
        """调用 OpenAPI 并返回 ``Result``。

        :param service: 服务名。
        :param action: 动作名。
        :param params: 动作参数。
        :param confirm: 调用方已确认。
        :returns: 响应的 ``Result`` 对象（缺失时为空字典）。
        :raises ZtError: ``ve`` 不存在、超时、非零退出、输出不是 JSON，或响应带业务错误。
        """
        stdout = self._run(self.argv(service, action, params or {}, confirm=confirm))
        try:
            doc = json.loads(stdout)
        except json.JSONDecodeError:
            raise ZtError("ve_bad_output", f"ve {service} {action} 的输出不是 JSON。",
                          hint="确认 ve 版本是否过旧（ve version / ve upgrade），或 profile 是否已登录") from None
        if not isinstance(doc, dict):
            raise ZtError("ve_bad_output", f"ve {service} {action} 的输出不是 JSON 对象。")
        meta = doc.get("ResponseMetadata") if isinstance(doc.get("ResponseMetadata"), dict) else {}
        error = meta.get("Error")
        if isinstance(error, dict):
            code = str(error.get("Code") or "unknown")
            message = redact(str(error.get("Message") or ""))
            raise ZtError("ve_api_error", f"{service} {action} 失败：{code}：{message}",
                          hint="Code 对照火山引擎 OpenAPI 错误码；权限类错误请核对 profile 的 IAM 策略")
        result = doc.get("Result")
        return result if isinstance(result, dict) else {}

    def raw(self, args: Sequence[str]) -> str:
        """透传 ``ve <args...>``（用于 ``ve tosutil ...``），返回 stdout 文本。

        透传命令不在 ``ve`` 安全策略的拦截范围内，也不追加 ``--yes``；本包只透传只读命令。

        :param args: ``ve`` 之后的参数。
        :returns: stdout 文本。
        :raises ZtError: ``ve`` 不存在、超时或非零退出。
        """
        argv = [self.settings.ve_bin, *args]
        return self._run(argv).decode("utf-8", errors="replace")

    def _run(self, argv: Sequence[str]) -> bytes:
        log.debug("run %s", " ".join(argv))
        try:
            proc = self.runner(list(argv), capture_output=True, timeout=self.timeout, check=False)
        except FileNotFoundError:
            raise ZtError("ve_not_found", f"找不到 ve 可执行文件：{argv[0]}",
                          hint="安装官方 CLI：npm i -g @volcengine/cli；或用 ZT_VE_BIN 指向它") from None
        except subprocess.TimeoutExpired:
            raise ZtError("ve_timeout", f"ve {argv[1]} 超过 {self.timeout:g} 秒未返回。",
                          hint="网络或 profile 异常；写操作超时后先用只读命令确认实际状态，不要直接重试") from None
        if proc.returncode != 0:
            tail = redact(proc.stderr.decode("utf-8", errors="replace").strip())[-_MAX_STDERR_CHARS:]
            raise ZtError("ve_failed", f"ve {argv[1]} 退出码 {proc.returncode}：{tail or '（无 stderr）'}",
                          hint="未登录或 profile 不存在时先 ve configure list；被客户端安全策略拦截时需用户确认后重试")
        return proc.stdout
