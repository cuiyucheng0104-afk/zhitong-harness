"""路径工具在 POSIX 与 Windows 写法下的行为。"""
from __future__ import annotations

from pathlib import Path

import pytest

from zt.common import ZtError
from zt.common.paths import is_absolute_any, project_dir_name, resolve_within, safe_project_name, to_rel_posix


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("资料/合同.pdf", "资料/合同.pdf"),
        ("资料\\合同.pdf", "资料/合同.pdf"),
        ("./工作//2026-10-19-核对/", "工作/2026-10-19-核对"),
        ("图纸\\.cache\\a.png", "图纸/.cache/a.png"),
    ],
)
def test_to_rel_posix_normalizes_both_separators(raw: str, expected: str) -> None:
    assert to_rel_posix(raw) == expected


@pytest.mark.parametrize("bad", ["", ".", "/abs", "\\abs", "C:\\x", "c:/x", "\\\\nas\\share", "a/../b", "..\\b"])
def test_to_rel_posix_rejects_absolute_and_parent(bad: str) -> None:
    with pytest.raises(ZtError) as info:
        to_rel_posix(bad)
    assert info.value.code == "invalid_path"


def test_is_absolute_any() -> None:
    assert is_absolute_any("/x")
    assert is_absolute_any("C:\\x")
    assert is_absolute_any("C:x")  # 盘符相对路径同样拒收
    assert not is_absolute_any("资料/x")


def test_resolve_within(tmp_path: Path) -> None:
    target = resolve_within(tmp_path, "资料\\子目录/文件 1.xlsx")
    assert target == tmp_path.resolve() / "资料" / "子目录" / "文件 1.xlsx"
    with pytest.raises(ZtError):
        resolve_within(tmp_path, "../escape")


def test_resolve_within_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前平台不允许创建符号链接")
    with pytest.raises(ZtError):
        resolve_within(root, "link/secret.txt")


def test_project_names() -> None:
    assert safe_project_name(' 某某 小区/一期:*?"<>|\t工程 ') == "某某小区一期工程"
    assert project_dir_name("2026-007", "某某小区 一期") == "2026-007-某某小区一期"
    with pytest.raises(ZtError) as info:
        project_dir_name("26-7", "x")
    assert info.value.code == "invalid_project_code"
    with pytest.raises(ZtError) as info:
        safe_project_name(" / ")
    assert info.value.code == "invalid_project_name"
