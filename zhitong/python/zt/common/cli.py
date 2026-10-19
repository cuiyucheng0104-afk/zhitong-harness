"""脚本 CLI 基类：子命令分发、``--in``/``--out``、stderr 日志、异常到退出码。

约定（zhitong/CONVENTIONS.md「Python」）：

- 调用形态 ``python -m zt.<area>.cli <子命令> [--in request.json] [--out result.json|目录/] [子命令参数]``。
- stdout 只输出一个 JSON：成功时没有 ``--out`` 就是完整信封；有 ``--out`` 时完整信封写入文件，
  stdout 输出摘要 ``{"status", "status_reason", "warning_items", "out"}``。``--out`` 是已存在目录或以分隔符结尾时，
  结果写到其中的 ``result.json``。
- 日志只走 stderr；``-v`` 打开 DEBUG。
- 失败：:class:`ZtError` 与参数错误都以退出码 2 结束，stdout 为 ``{"error": {...}}``；
  未预期的异常同样退出码 2，code 为 ``internal_error``，并在 stderr 打印栈。

用法::

    cli = Cli("zt.reconcile", "送审与审定计价表核对")

    @cli.command("run", help="核对两张计价表", arguments=lambda p: p.add_argument("--submitted", required=True))
    def run(call: Call) -> Envelope:
        ...

    if __name__ == "__main__":
        raise SystemExit(cli.main())
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Callable, NoReturn, Optional, Sequence

from pydantic import ValidationError

from zt.common.envelope import Envelope
from zt.common.errors import EXIT_ERROR, ZtError
from zt.common.jsonio import emit, read_json, to_jsonable, write_json

EXIT_OK = 0
RESULT_FILENAME = "result.json"

log = logging.getLogger("zt.cli")


@dataclass
class Call:
    """一次子命令调用的输入。

    :ivar args: argparse 解析结果（含子命令自定义参数）。
    :ivar request: ``--in`` 指向的 JSON；未给 ``--in`` 时为空字典。
    :ivar out: ``--out`` 解析后的结果文件路径；未给时为 None。
    """

    args: argparse.Namespace
    request: Any = field(default_factory=dict)
    out: Optional[Path] = None

    @property
    def out_dir(self) -> Optional[Path]:
        """结果文件所在目录，子命令可把 xlsx 等附件写在这里。

        :returns: 目录；未给 ``--out`` 时为 None。
        """
        return None if self.out is None else self.out.parent


Handler = Callable[[Call], "Envelope | dict[str, Any]"]


@dataclass
class _Command:
    name: str
    help: str
    handler: Handler
    arguments: Optional[Callable[[argparse.ArgumentParser], Any]]


class _Parser(argparse.ArgumentParser):
    """参数错误改为抛 :class:`ZtError`，以便输出错误 JSON 而不是 argparse 的 usage 文本。"""

    def error(self, message: str) -> NoReturn:
        raise ZtError("usage", message, hint=self.format_usage().strip())


class Cli:
    """子命令分发器。

    :param prog: 程序名，通常为模块路径（如 ``zt.reconcile``）。
    :param description: 一句话说明。
    """

    def __init__(self, prog: str, description: str) -> None:
        self.prog = prog
        self.description = description
        self._commands: dict[str, _Command] = {}

    def command(
        self,
        name: str,
        *,
        help: str,
        arguments: Optional[Callable[[argparse.ArgumentParser], Any]] = None,
    ) -> Callable[[Handler], Handler]:
        """注册子命令的装饰器。

        :param name: 子命令名。
        :param help: 一句话说明。
        :param arguments: 可选回调，为子命令添加自定义参数。
        :returns: 原样返回被装饰函数的装饰器。
        :raises ValueError: 子命令重名。
        """

        def register(fn: Handler) -> Handler:
            if name in self._commands:
                raise ValueError(f"子命令重复注册：{name}")
            self._commands[name] = _Command(name, help, fn, arguments)
            return fn

        return register

    def build_parser(self) -> argparse.ArgumentParser:
        """构造 argparse 解析器（供测试与 ``--help``）。

        :returns: 解析器。
        """
        parser = _Parser(prog=self.prog, description=self.description)
        parser.add_argument("-v", "--verbose", action="store_true", help="stderr 输出 DEBUG 日志")
        sub = parser.add_subparsers(dest="command", metavar="<子命令>", parser_class=_Parser)
        sub.required = True
        for cmd in self._commands.values():
            p = sub.add_parser(cmd.name, help=cmd.help, description=cmd.help)
            p.add_argument("--in", dest="in_path", metavar="request.json", help="请求 JSON；- 表示 stdin")
            p.add_argument("--out", dest="out_path", metavar="result.json", help="结果 JSON 路径或目录")
            if cmd.arguments is not None:
                cmd.arguments(p)
        return parser

    def main(
        self,
        argv: Optional[Sequence[str]] = None,
        *,
        stdout: Optional[IO[str]] = None,
    ) -> int:
        """解析参数、执行子命令并输出 JSON。

        :param argv: 参数列表；默认 ``sys.argv[1:]``。
        :param stdout: 输出流；默认 ``sys.stdout``（测试可注入）。
        :returns: 退出码：成功 0，失败 2。
        """
        out_stream = stdout if stdout is not None else _utf8_stdout()
        _configure_logging(argv)
        try:
            args = self.build_parser().parse_args(argv)
            cmd = self._commands[args.command]
            call = Call(
                args=args,
                request=read_json(args.in_path) if args.in_path else {},
                out=_resolve_out(args.out_path),
            )
            result = cmd.handler(call)
            payload = result.to_json() if isinstance(result, Envelope) else to_jsonable(result)
            if not isinstance(result, Envelope):
                # 子命令返回字典时同样按信封校验，杜绝「成功 + 空」。
                payload = Envelope.model_validate(payload).to_json()
            if call.out is not None:
                write_json(call.out, payload)
                emit({
                    "status": payload["status"],
                    "status_reason": payload["status_reason"],
                    "warning_items": payload["warning_items"],
                    "out": str(call.out),
                }, out_stream)
            else:
                emit(payload, out_stream)
            return EXIT_OK
        except ZtError as exc:
            log.debug("ZtError %s: %s", exc.code, exc.message)
            emit(exc.to_json(), out_stream)
            return EXIT_ERROR
        except ValidationError as exc:
            log.error("结果信封校验失败：%s", exc)
            emit(ZtError("invalid_result", f"脚本输出违反结果契约：{exc.errors()[0]['msg']}").to_json(), out_stream)
            return EXIT_ERROR
        except Exception as exc:  # noqa: BLE001 - 最外层：任何异常都要变成错误 JSON + 退出码 2
            traceback.print_exc(file=sys.stderr)
            emit(ZtError("internal_error", f"{type(exc).__name__}: {exc}").to_json(), out_stream)
            return EXIT_ERROR


def _resolve_out(raw: Optional[str]) -> Optional[Path]:
    if raw is None:
        return None
    p = Path(raw)
    if p.is_dir() or raw.endswith(("/", "\\", os.sep)):
        return p / RESULT_FILENAME
    return p


def _utf8_stdout() -> IO[str]:
    # Windows 控制台默认 GBK；脚本输出约定为 UTF-8。
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    return sys.stdout


def _configure_logging(argv: Optional[Sequence[str]]) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    level = logging.DEBUG if ("-v" in args or "--verbose" in args) else logging.INFO
    reconfigure = getattr(sys.stderr, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")
    root = logging.getLogger("zt")
    root.setLevel(level)
    if not any(isinstance(h, _StderrHandler) for h in root.handlers):
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """每次写日志时取当前的 ``sys.stderr``，避免绑定到已被替换或关闭的流。"""

    @property  # type: ignore[override]
    def stream(self) -> IO[str]:
        return sys.stderr

    @stream.setter
    def stream(self, _value: IO[str]) -> None:
        pass
