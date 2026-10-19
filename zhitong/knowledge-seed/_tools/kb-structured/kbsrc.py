"""受控源读取：优先读 `--repo` 目录下按仓内相对路径存放的快照文件，其次回退到 `git show <commit>:<path>`。

迁移说明：原仓（zhitong-cost-ai）的生成器只用 `git show 33601ca8:<path>` 取源。迁入 zhitong 后原 commit
不可达，所以默认 `--repo` 指向 `sources/repo-snapshot/`，那里放同相对路径的源文件副本。
`gb50854_zj2025.yaml` 副本的 sha256 与原 commit 登记值一致；`quantity_rules.yaml` 与 `quantity_rules.py`
取自迁移时旧仓工作树，不一定等于 33601ca8 版本（见 README「迁入后的差异」）。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNAPSHOT_REPO = HERE / "sources" / "repo-snapshot"


def git_show_bytes(repo: str, commit: str, path: str) -> bytes:
    """返回源文件字节。

    Args:
        repo: 快照根目录，或含 `commit` 的 git 仓库。
        commit: 受控源 commit（仅在 git 回退时使用）。
        path: 相对仓根的源文件路径。

    Returns:
        文件原始字节。

    Raises:
        FileNotFoundError / subprocess.CalledProcessError: 快照与 git 都取不到。
    """
    local = Path(repo) / path
    if local.is_file():
        return local.read_bytes()
    return subprocess.run(["git", "-C", repo, "-c", "core.quotepath=false", "show", f"{commit}:{path}"],
                          check=True, capture_output=True).stdout


def full_commit(repo: str, commit: str) -> str:
    """返回完整 commit；快照目录不是 git 仓库时原样返回传入的简写。"""
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", f"{commit}^{{commit}}"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else commit


def source_available(repo: str, commit: str, path: str) -> bool:
    """快照文件存在，或 git 里能取到该 commit 下的文件。"""
    if (Path(repo) / path).is_file():
        return True
    return subprocess.run(["git", "-C", repo, "cat-file", "-e", f"{commit}:{path}"],
                          capture_output=True).returncode == 0
