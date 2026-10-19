"""项目目录内的安全路径解析。

来源：/home/user/zhitong-cost-ai/engine-service/app/files.py ``resolve_safe_path`` / ``read_file_bytes`` /
``existing_file`` / ``file_ext``。
改动：

- 去掉租户子树授权与 HTTP 异常，失败抛 :class:`zt.common.ZtError`；
- 旧实现把绝对路径当相对路径处理（``lstrip("/\\\\")``）；本仓直接拒收绝对路径、Windows 盘符和 UNC，
  与证据定位 ``EvidenceRef.rel_path`` 同口径；
- 越界判定依赖 ``resolve()``：``..`` 与符号链接在那一步已经生效，所以「用 ``../`` 爬出根目录」和
  「根目录里放一个指向别处的软链」两种逃逸看到的都是落点的真实位置。
"""
from __future__ import annotations

from pathlib import Path

from zt.common import ZtError
from zt.common.paths import resolve_within


def resolve_project_file(root: Path, rel_path: str) -> Path:
    """把项目内相对路径解析成 ``root`` 下的已存在文件。

    :param root: 项目目录（本机缓存里的 ``项目/<编号>-<工程名>/``）。
    :param rel_path: ``/`` 或 ``\\`` 分隔的相对路径。
    :returns: 文件的绝对路径。
    :raises ZtError: 路径为空、绝对、含 ``..`` 或越出 ``root``（``invalid_path``）；
        文件不存在或不是普通文件（``file_not_found``）。
    """
    path = resolve_within(root, rel_path)
    if not path.is_file():
        raise ZtError("file_not_found", f"文件不存在：{rel_path}",
                      hint="先用 tos_ls 确认路径，再用 tos_pull 拉到本机缓存")
    return path


def read_project_file(root: Path, rel_path: str) -> bytes:
    """读项目内相对路径指向的文件字节。

    :param root: 项目目录。
    :param rel_path: 相对路径。
    :returns: 文件内容。
    :raises ZtError: 同 :func:`resolve_project_file`；读取失败为 ``read_failed``。
    """
    path = resolve_project_file(root, rel_path)
    try:
        return path.read_bytes()
    except OSError as e:
        raise ZtError("read_failed", f"读取文件失败：{rel_path}（{e}）") from e


def file_ext(name: str) -> str:
    """小写扩展名（不带点）；没有扩展名返回空串。

    :param name: 文件名或路径，``/`` 与 ``\\`` 都按目录分隔处理。
    :returns: 扩展名。
    """
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    return (base.rsplit(".", 1)[-1] if "." in base else "").lower()
