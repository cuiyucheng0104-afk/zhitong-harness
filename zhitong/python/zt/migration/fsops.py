"""迁移用的文件系统操作：只读遍历源目录、sha256（带缓存）、文件名清洗、硬链接或复制到镜像目录。

源目录只读：本模块对源路径只做 ``stat``、``open(..., "rb")`` 与 ``os.link`` 的源端，从不写、改名或删除源文件。
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator, Optional

from zt.common import ZtError

LINK_MODES = ("hard", "copy")

# 系统生成物：操作系统 / NAS / Office / CAD 留下的文件与目录，不是客户资料（spec §6 第 3 条「系统生成物」）
_JUNK_NAMES = frozenset({".ds_store", "thumbs.db", "ehthumbs.db", "desktop.ini", ".localized", "icon\r"})
_JUNK_PREFIXES = ("~$", "._", ".~lock.")
_JUNK_SUFFIXES = (".dwl", ".dwl2")
JUNK_DIRS = frozenset({"__MACOSX", ".Trashes", ".Spotlight-V100", ".fseventsd", ".TemporaryItems",
                       "@eaDir", "#recycle", "$RECYCLE.BIN", "System Volume Information"})
_UNSAFE = re.compile(r'[\\:*?"<>|\x00-\x1f]')
_HASH_CHUNK = 1 << 20


def nfc(s: str) -> str:
    """Unicode NFC 规范化（macOS 上传的文件名可能是 NFD）。

    :param s: 文本。
    :returns: NFC 文本。
    """
    return unicodedata.normalize("NFC", s)


def is_junk_name(name: str) -> bool:
    """文件名是否是系统生成物（``.DS_Store``、``Thumbs.db``、``~$`` 临时文件、AutoCAD 锁文件等）。

    :param name: 文件名（不含目录）。
    :returns: 是系统生成物时为 True。
    """
    low = name.lower()
    return low in _JUNK_NAMES or name.startswith(_JUNK_PREFIXES) or low.endswith(_JUNK_SUFFIXES)


def in_junk_dir(rel: str) -> bool:
    """相对路径是否落在系统目录（``@eaDir``、``__MACOSX``、``#recycle`` 等）里。

    :param rel: ``/`` 分隔的相对路径。
    :returns: 任一目录段是系统目录时为 True。
    """
    return any(seg in JUNK_DIRS for seg in PurePosixPath(rel).parts[:-1])


def safe_segment(seg: str) -> str:
    """把一个路径段清洗成 Windows 与 TOS 都能用的名字：``\\:*?"<>|`` 与控制字符换成 ``_``，去掉首尾空白与结尾的点。

    :param seg: 目录名或文件名。
    :returns: 清洗后的名字；清洗后为空时为 ``_``。
    """
    cleaned = _UNSAFE.sub("_", nfc(seg)).strip().rstrip(".").strip()
    return cleaned or "_"


def safe_rel(rel: str) -> str:
    """逐段清洗相对路径。

    :param rel: ``/`` 分隔的相对路径。
    :returns: 清洗后的相对路径。
    """
    return "/".join(safe_segment(p) for p in rel.split("/") if p not in ("", "."))


def walk_files(root: Path) -> Iterator[str]:
    """列出 ``root`` 下所有普通文件的相对路径（``/`` 分隔），不跟随符号链接。

    :param root: 源目录。
    :returns: 相对路径迭代器，按目录与文件名排序。
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        base = Path(dirpath)
        for fn in sorted(filenames):
            full = base / fn
            if full.is_symlink() or not full.is_file():
                continue
            yield full.relative_to(root).as_posix()


def encodable(rel: str) -> bool:
    """路径能否按 UTF-8 编码（磁盘上非 UTF-8 的文件名在 Python 里带代理字符，写不进 JSON）。

    :param rel: 路径。
    :returns: 能编码时为 True。
    """
    try:
        rel.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


@dataclass
class HashCache:
    """sha256 缓存：键是源文件绝对路径，值带 ``size`` 与 ``mtime_ns``，任一变化即重算。

    :ivar path: 缓存文件；None 表示只在内存里。
    """

    path: Optional[Path]
    entries: dict[str, dict[str, object]]
    dirty: bool = False

    @classmethod
    def load(cls, path: Optional[Path]) -> "HashCache":
        """读缓存文件；不存在或损坏时从空缓存开始。

        :param path: 缓存文件。
        :returns: 缓存。
        """
        entries: dict[str, dict[str, object]] = {}
        if path is not None and path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                entries = loaded if isinstance(loaded, dict) else {}
            except ValueError:
                entries = {}  # 损坏的缓存只影响速度：全部重算
        return cls(path, entries)

    def sha256(self, src: Path) -> tuple[int, str]:
        """源文件的大小与 sha256。

        :param src: 源文件。
        :returns: ``(字节数, sha256 小写十六进制)``。
        """
        st = src.stat()
        key = str(src)
        hit = self.entries.get(key)
        if hit and hit.get("size") == st.st_size and hit.get("mtime_ns") == st.st_mtime_ns:
            return st.st_size, str(hit["sha256"])
        digest = file_sha256(src)
        self.entries[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}
        self.dirty = True
        return st.st_size, digest

    def save(self) -> None:
        """写回缓存文件（有变化且有路径时）。"""
        if self.path is None or not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.entries, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
        self.dirty = False


def file_sha256(path: Path) -> str:
    """整份读文件算 sha256。

    :param path: 文件。
    :returns: 小写十六进制。
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def bytes_sha256(data: bytes) -> str:
    """内存数据的 sha256。

    :param data: 字节。
    :returns: 小写十六进制。
    """
    return hashlib.sha256(data).hexdigest()


def place_file(src: Path, dst: Path, mode: str) -> str:
    """把源文件放到镜像目录里：硬链接或复制；目标已经是同一份时不动。

    :param src: 源文件（只读）。
    :param dst: 镜像里的目标路径。
    :param mode: ``hard`` 或 ``copy``。
    :returns: ``kept``（已是同一份）/ ``linked`` / ``copied`` / ``replaced``（目标存在但不同，已替换）。
    :raises ZtError: 硬链接跨文件系统（``cross_device_link``）或 mode 不认识（``usage``）。
    """
    if mode not in LINK_MODES:
        raise ZtError("usage", f"--link 只能是 {'/'.join(LINK_MODES)}：{mode!r}")
    sst = src.stat()
    existed = dst.exists() or dst.is_symlink()
    if existed and not dst.is_symlink():
        dstat = dst.stat()
        if mode == "hard" and (dstat.st_ino, dstat.st_dev) == (sst.st_ino, sst.st_dev):
            return "kept"
        if mode == "copy" and dstat.st_size == sst.st_size and dstat.st_mtime_ns == sst.st_mtime_ns:
            return "kept"
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f".{dst.name}.zt-tmp")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    if mode == "hard":
        try:
            os.link(src, tmp)
        except OSError as e:
            if e.errno == errno.EXDEV:
                raise ZtError("cross_device_link", f"镜像目录与源目录不在同一文件系统，无法硬链接：{dst.parent}",
                              hint="把 --out 放到源目录所在的文件系统上，或改用 --link copy（会占用同等磁盘空间）") from e
            raise
    else:
        shutil.copy2(src, tmp)
    os.replace(tmp, dst)
    if not existed:
        return "linked" if mode == "hard" else "copied"
    return "replaced"


def write_text_if_changed(path: Path, text: str) -> bool:
    """UTF-8（LF）写文本；内容相同则不写。

    :param path: 目标。
    :param text: 全文。
    :returns: 写了时为 True。
    """
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.zt-tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)
    return True


def is_within(child: Path, parent: Path) -> bool:
    """``child`` 是否就是 ``parent`` 或在其之下（都先 ``resolve``）。

    :param child: 路径。
    :param parent: 路径。
    :returns: 包含关系成立时为 True。
    """
    c, p = child.resolve(), parent.resolve()
    return c == p or p in c.parents
