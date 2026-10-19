"""测试辅助：把假 ve / 假 ssh 包成可执行文件，回放夹具，读调用日志。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from zt.volc.config import VolcSettings

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
PYTHON_ROOT = HERE.parents[1]


def make_wrapper(dest: Path, script: Path, env: dict[str, str] | None = None) -> Path:
    """生成调用 ``script`` 的可执行包装（POSIX 为 sh 脚本，Windows 为 .cmd），路径可含空格与中文。

    :param dest: 包装文件路径（不含扩展名）。
    :param script: 要运行的 Python 脚本。
    :param env: 包装内设置的环境变量。
    :returns: 包装文件路径。
    """
    env = env or {}
    if os.name == "nt":
        path = dest.with_suffix(".cmd")
        sets = "".join(f'set "{k}={v}"\r\n' for k, v in env.items())
        path.write_text(f'@echo off\r\n{sets}"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        path = dest
        sets = "".join(f"export {k}='{v}'\n" for k, v in env.items())
        path.write_text(f'#!/bin/sh\n{sets}exec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        path.chmod(0o755)
    return path


class FakeVe:
    """一个临时目录里的假 ve：写夹具、读调用日志。"""

    def __init__(self, root: Path) -> None:
        self.dir = root / "fake ve 目录"
        self.dir.mkdir()
        self.bin = make_wrapper(root / "fake-ve", HERE / "fake_ve.py", {"FAKE_VE_DIR": str(self.dir)})

    def fixture(self, key: str, body: Any, *, n: int | None = None, ext: str = "json") -> None:
        """写一个夹具。

        :param key: ``<service>.<Action>`` 或 ``tosutil.<verb>``。
        :param body: JSON 可序列化对象（ext=json）或文本（ext=txt）。
        :param n: 第几次调用使用；None 表示每次都用。
        :param ext: ``json`` 或 ``txt``。
        """
        name = f"{key}.{n}" if n else key
        text = json.dumps(body, ensure_ascii=False) if ext == "json" else body
        (self.dir / f"{name}.{ext}").write_text(text, encoding="utf-8")

    def copy(self, key: str, fixture_file: str, *, n: int | None = None) -> None:
        """把 ``fixtures/`` 下的文件复制成夹具。

        :param key: 夹具键。
        :param fixture_file: ``fixtures/`` 下的文件名。
        :param n: 第几次调用使用。
        """
        name = f"{key}.{n}" if n else key
        shutil.copyfile(FIXTURES / fixture_file, self.dir / (name + Path(fixture_file).suffix))

    def fail(self, key: str, *, exit_code: int = 1, stderr: str = "", n: int | None = None) -> None:
        """写失败夹具。

        :param key: 夹具键。
        :param exit_code: 退出码。
        :param stderr: stderr 文本。
        :param n: 第几次调用使用。
        """
        name = f"{key}.{n}" if n else key
        (self.dir / f"{name}.fail.json").write_text(json.dumps({"exit": exit_code, "stderr": stderr}), encoding="utf-8")

    def calls(self, key: str | None = None) -> list[list[str]]:
        """读调用日志。

        :param key: 只取某个键；None 取全部。
        :returns: 每次调用 ve 之后的 argv。
        """
        log = self.dir / "calls.jsonl"
        if not log.exists():
            return []
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        return [r["argv"] for r in rows if key is None or r["key"] == key]

    def keys(self) -> list[str]:
        """按顺序返回所有调用的键。"""
        log = self.dir / "calls.jsonl"
        if not log.exists():
            return []
        return [json.loads(line)["key"] for line in log.read_text(encoding="utf-8").splitlines()]

    def settings(self, **overrides: Any) -> VolcSettings:
        """指向假 ve 的设置。

        :param overrides: 覆盖字段。
        :returns: 设置，profile 为 ``test-profile``。
        """
        base = {"ve_bin": str(self.bin), "profile": "test-profile", "region": "cn-beijing"}
        return VolcSettings(**{**base, **overrides})


def run_volc_cli(*args: str, env: dict[str, str] | None = None) -> tuple[int, Any, str]:
    """以子进程运行 ``python -m zt.volc.cli``。

    :param args: 子命令与参数。
    :param env: 额外环境变量。
    :returns: ``(退出码, stdout 的 JSON, stderr 文本)``。
    """
    full = {**os.environ, "PYTHONPATH": str(PYTHON_ROOT), "PYTHONIOENCODING": "ascii", **(env or {})}
    proc = subprocess.run([sys.executable, "-m", "zt.volc.cli", *args], capture_output=True, cwd=PYTHON_ROOT, env=full, check=False)
    lines = proc.stdout.decode("utf-8").splitlines()
    assert len(lines) == 1, (lines, proc.stderr.decode("utf-8", "replace"))
    return proc.returncode, json.loads(lines[0]), proc.stderr.decode("utf-8", "replace")
