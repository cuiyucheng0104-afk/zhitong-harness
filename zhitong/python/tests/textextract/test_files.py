"""项目目录内的安全路径解析（POSIX 与 Windows 写法）。

迁移自旧仓 engine-service/app/files.py ``resolve_safe_path`` 的行为约定；旧用例散在端点测试里
（``test_sidecar_lookup_respects_file_root`` 等），这里按纯函数重写。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from zt.common import ZtError
from zt.textextract.files import file_ext, read_project_file, resolve_project_file


@pytest.mark.parametrize("bad", [
    "", ".", "/etc/passwd", "\\windows\\system32", "C:\\Users\\x\\a.pdf", "c:/x/a.pdf",
    "\\\\nas\\share\\a.pdf", "../x", "资料/../../x", "资料\\..\\..\\x", "a/./../../b",
])
def test_rejects_absolute_and_escaping_paths(tmp_path, bad):
    (tmp_path / "资料").mkdir()
    with pytest.raises(ZtError) as e:
        resolve_project_file(tmp_path, bad)
    assert e.value.code == "invalid_path"


def test_accepts_both_separators_and_chinese_space_names(tmp_path):
    d = tmp_path / "资料 一期" / "合同 (1)"
    d.mkdir(parents=True)
    (d / "施工 合同.pdf").write_bytes(b"x")
    for rel in ("资料 一期/合同 (1)/施工 合同.pdf", "资料 一期\\合同 (1)\\施工 合同.pdf", "./资料 一期//合同 (1)/施工 合同.pdf"):
        assert resolve_project_file(tmp_path, rel) == (d / "施工 合同.pdf").resolve()
    assert read_project_file(tmp_path, "资料 一期/合同 (1)/施工 合同.pdf") == b"x"


def test_missing_file_and_directory_are_file_not_found(tmp_path):
    (tmp_path / "资料").mkdir()
    for rel in ("资料/不存在.pdf", "资料"):
        with pytest.raises(ZtError) as e:
            resolve_project_file(tmp_path, rel)
        assert e.value.code == "file_not_found"


def test_symlink_pointing_outside_root_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("秘密", encoding="utf-8")
    try:
        os.symlink(secret, root / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("当前平台不允许创建符号链接")
    with pytest.raises(ZtError) as e:
        resolve_project_file(root, "link.txt")
    assert e.value.code == "invalid_path"


def test_read_failure_is_read_failed(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_bytes(b"x")

    def boom(self):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(ZtError) as e:
        read_project_file(tmp_path, "a.txt")
    assert e.value.code == "read_failed"


@pytest.mark.parametrize("name,ext", [
    ("a.PDF", "pdf"), ("资料/合同.docx", "docx"), ("资料\\合同.XLSX", "xlsx"), ("no_ext", ""),
    ("a.b/c", ""), ("a.pdf.ocr.txt", "txt"),
])
def test_file_ext(name, ext):
    assert file_ext(name) == ext
