"""跨平台路径工具。

规则：

- 业务路径（证据 ``rel_path``、桶内 key、项目内相对路径）一律用 ``/`` 分隔，与平台无关。
- 落盘路径用 :class:`pathlib.Path`；不假定 ``/tmp``，不拼字符串。
- 项目目录名 ``<编号>-<工程名>``：工程名去掉空格与 ``/\\:*?"<>|``（spec §5）。
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from zt.common.errors import ZtError

# spec §5：工程名去掉空格与 /\:*?"<>|；同时去掉控制字符与全角空格，避免 Windows 拒收。
_NAME_STRIP = re.compile(r'[\s　/\\:*?"<>|\x00-\x1f]')
PROJECT_CODE = re.compile(r"^(?P<year>\d{4})-(?P<seq>\d{3})$")


def is_absolute_any(path: str) -> bool:
    """判断字符串在 POSIX 或 Windows 任一语义下是否为绝对路径（含盘符、UNC、根斜杠）。

    :param path: 待判断的路径字符串。
    :returns: 任一平台视为绝对或带盘符时为 True。
    """
    if path.startswith(("/", "\\")):
        return True
    win = PureWindowsPath(path)
    return bool(win.drive) or win.is_absolute() or PurePosixPath(path).is_absolute()


def to_rel_posix(path: str) -> str:
    """把项目内相对路径规范成 ``/`` 分隔、无 ``.`` 段的形式。

    :param path: 相对路径，可用 ``/`` 或 ``\\`` 分隔。
    :returns: 规范后的相对路径。
    :raises ZtError: 绝对路径、空路径或含 ``..`` 段（code ``invalid_path``）。
    """
    if not path or is_absolute_any(path):
        raise ZtError("invalid_path", f"需要相对路径：{path!r}")
    parts = [p for p in re.split(r"[\\/]+", path) if p not in ("", ".")]
    if not parts:
        raise ZtError("invalid_path", f"需要相对路径：{path!r}")
    if ".." in parts:
        raise ZtError("invalid_path", f"路径不能含 ..：{path!r}")
    return "/".join(parts)


def resolve_within(root: Path, rel: str) -> Path:
    """把项目内相对路径解析到 ``root`` 之下，并确认结果不逃逸 ``root``。

    :param root: 根目录（项目缓存目录或工作目录）。
    :param rel: ``/`` 或 ``\\`` 分隔的相对路径。
    :returns: ``root`` 下的绝对路径。
    :raises ZtError: 路径非法或解析后不在 ``root`` 下（code ``invalid_path``）。
    """
    base = root.resolve()
    target = base.joinpath(*to_rel_posix(rel).split("/")).resolve()
    if target != base and base not in target.parents:
        raise ZtError("invalid_path", f"路径越出根目录：{rel!r}")
    return target


def safe_project_name(name: str) -> str:
    """按 spec §5 清洗工程名：去掉空白与 ``/\\:*?"<>|``。

    :param name: 原始工程名。
    :returns: 清洗后的工程名。
    :raises ZtError: 清洗后为空（code ``invalid_project_name``）。
    """
    cleaned = _NAME_STRIP.sub("", name).strip(".")
    if not cleaned:
        raise ZtError("invalid_project_name", f"工程名清洗后为空：{name!r}", hint="给出包含文字的工程名")
    return cleaned


def project_dir_name(code: str, name: str) -> str:
    """组装项目目录名 ``<编号>-<工程名>``。

    :param code: 项目编号 ``YYYY-NNN``。
    :param name: 原始工程名。
    :returns: 目录名。
    :raises ZtError: 编号格式不对（``invalid_project_code``）或工程名为空。
    """
    if not PROJECT_CODE.match(code):
        raise ZtError("invalid_project_code", f"项目编号应为 YYYY-NNN：{code!r}")
    return f"{code}-{safe_project_name(name)}"
