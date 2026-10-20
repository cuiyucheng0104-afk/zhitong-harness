"""upload.sh：用假 rclone 记录调用，检查先 dry-run、再上传、最后 check；排除 _tools/；dry-run 有删除时中止。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from zt.migration.relayout import ZHITONG_ROOT

SCRIPT = ZHITONG_ROOT / "migration" / "upload.sh"
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="upload.sh 只在 Linux ECS 上运行，需要 bash")

FAKE_RCLONE = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_CALLS"
if [ "$1" = listremotes ]; then echo "tos:"; exit 0; fi
log=""
prev=""
for a in "$@"; do
  if [ "$prev" = "--log-file" ]; then log="$a"; fi
  prev="$a"
done
case " $* " in
  *" --dry-run "*)
    echo "NOTICE: 项目/a.pdf: Skipped copy as --dry-run is set (size 10)" >> "$log"
    if [ -n "${FAKE_DELETES:-}" ]; then echo "NOTICE: 旧/b.pdf: Skipped delete as --dry-run is set (size 3)" >> "$log"; fi
    ;;
esac
exit 0
"""


@pytest.fixture()
def env(tmp_path: Path) -> dict:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "rclone"
    fake.write_text(FAKE_RCLONE, encoding="utf-8")
    fake.chmod(0o755)
    mirror = tmp_path / "out" / "mirror"
    (mirror / "项目").mkdir(parents=True)
    (mirror / "案例索引.md").write_text("# 案例索引\n", encoding="utf-8")
    calls = tmp_path / "calls.txt"
    e = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", FAKE_CALLS=str(calls))
    return {"env": e, "mirror": mirror, "calls": calls, "tmp": tmp_path}


def _run(env: dict, *args: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], env=env["env"] | (extra_env or {}), capture_output=True,
                          text=True, stdin=subprocess.DEVNULL, check=False)


def _calls(env: dict) -> list[str]:
    return env["calls"].read_text(encoding="utf-8").splitlines()


def test_syntax() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_mirror_sync_dry_run_then_upload_then_check(env: dict) -> None:
    r = _run(env, "--bucket", "bkt", "--prefix", "/某咨询/", "--src", str(env["mirror"]), "--yes")
    assert r.returncode == 0, r.stderr
    calls = _calls(env)
    assert calls[0] == "listremotes"
    dry, real, check = calls[1], calls[2], calls[3]
    assert dry.startswith(f"sync {env['mirror']}/ tos:bkt/某咨询/ --checksum") and "--dry-run" in dry
    assert real.startswith("sync ") and "--dry-run" not in real and "--checksum" in real
    assert check.startswith(f"check {env['mirror']}/ tos:bkt/某咨询/")
    for c in (dry, real, check):
        assert "--exclude _tools/**" in c and "--exclude **/_tools/**" in c
    assert "新上传 1、更新 0、删除 0" in r.stdout
    assert (env["tmp"] / "out" / "logs").is_dir()


def test_deletions_abort_without_allow_delete(env: dict) -> None:
    r = _run(env, "--bucket", "bkt", "--prefix", "p", "--src", str(env["mirror"]), "--yes", extra_env={"FAKE_DELETES": "1"})
    assert r.returncode == 3
    assert not any(c.startswith("sync") and "--dry-run" not in c for c in _calls(env))
    r = _run(env, "--bucket", "bkt", "--prefix", "p", "--src", str(env["mirror"]), "--yes", "--allow-delete",
             extra_env={"FAKE_DELETES": "1"})
    assert r.returncode == 0, r.stderr


def test_non_interactive_without_yes_stops_after_dry_run(env: dict) -> None:
    r = _run(env, "--bucket", "bkt", "--prefix", "p", "--src", str(env["mirror"]))
    assert r.returncode == 4
    assert sum(1 for c in _calls(env) if c.startswith("sync")) == 1


def test_subdir_upload(env: dict) -> None:
    (env["mirror"] / "项目" / "2024-001-甲").mkdir()
    r = _run(env, "--bucket", "bkt", "--prefix", "p", "--src", str(env["mirror"]), "--subdir", "项目/2024-001-甲", "--yes")
    assert r.returncode == 0, r.stderr
    assert _calls(env)[1].startswith(f"sync {env['mirror']}/项目/2024-001-甲/ tos:bkt/p/项目/2024-001-甲/")


def test_knowledge_seed_copy_excludes_tools_and_root_readme(env: dict) -> None:
    seed = ZHITONG_ROOT / "knowledge-seed"
    r = _run(env, "--from-knowledge-seed", str(seed), "--bucket", "bkt", "--prefix", "p", "--yes",
             "--log-dir", str(env["tmp"] / "logs"))
    assert r.returncode == 0, r.stderr
    calls = _calls(env)
    assert calls[1].startswith(f"copy {seed}/ tos:bkt/p/知识库/") and "--dry-run" in calls[1]
    assert "--exclude _tools/**" in calls[2] and "--exclude /README.md" in calls[2]
    assert calls[3].startswith("check ") and "--one-way" in calls[3]


def test_missing_remote_and_bad_prefix_fail(env: dict) -> None:
    r = _run(env, "--bucket", "bkt", "--remote", "other", "--src", str(env["mirror"]), "--yes")
    assert r.returncode == 2 and "other" in r.stderr
    r = _run(env, "--bucket", "bkt", "--prefix", "a/../b", "--src", str(env["mirror"]), "--yes")
    assert r.returncode == 2
