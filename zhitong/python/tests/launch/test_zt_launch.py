"""skills/_shared/zt_launch.py：解释器选择、重跑、zt 定位与 zt_not_importable 错误契约。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[2]
SKILLS = PYTHON_ROOT.parent / "skills"
SHARED = SKILLS / "_shared"
SCRIPT = SKILLS / "zt-tk" / "scripts" / "tk.py"

sys.path.insert(0, str(SHARED))
import zt_launch  # noqa: E402


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    """干净环境：没有 ZT_PYTHON，DSH_HOME 指向空目录，zt 不在 PYTHONPATH 上。"""
    env = {k: v for k, v in os.environ.items() if k not in ("ZT_PYTHON", "ZT_LAUNCHED", "PYTHONPATH", "DSH_HOME")}
    env["DSH_HOME"] = str(tmp_path / "dsh-home")
    env.update(extra)
    return env


def _run(python: str | Path, script: Path, args: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([str(python), str(script), *args], capture_output=True, env=env, cwd=cwd, check=False, timeout=120)


def _bare_venv(tmp_path: Path) -> Path:
    """没有任何第三方包的虚拟环境（zt 的依赖都不在）。"""
    venv = tmp_path / "bare"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True, timeout=120)
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def test_runs_under_the_current_interpreter(tmp_path):
    proc = _run(sys.executable, SCRIPT, ["--help"], _env(tmp_path), tmp_path)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert b"detect" in proc.stdout


def test_missing_zt_python_target_is_a_structured_error(tmp_path):
    proc = _run(sys.executable, SCRIPT, ["--help"], _env(tmp_path, ZT_PYTHON=str(tmp_path / "nope" / "python3")), tmp_path)
    assert proc.returncode == 2
    error = json.loads(proc.stdout.decode("utf-8"))["error"]
    assert error["code"] == "zt_not_importable"
    assert "ZT_PYTHON" in error["message"] and error["hint"]


def test_interpreter_without_dependencies_reports_zt_not_importable(tmp_path):
    bare = _bare_venv(tmp_path)
    proc = _run(bare, SCRIPT, ["--help"], _env(tmp_path), tmp_path)
    assert proc.returncode == 2, proc.stderr.decode("utf-8", "replace")
    lines = proc.stdout.decode("utf-8").splitlines()
    assert len(lines) == 1
    error = json.loads(lines[0])["error"]
    assert error["code"] == "zt_not_importable"
    assert "pydantic" in error["message"]
    assert "load_workspace_dependencies" in error["hint"]


def test_zt_python_relaunches_the_script_with_arguments(tmp_path):
    bare = _bare_venv(tmp_path)
    proc = _run(bare, SCRIPT, ["--help"], _env(tmp_path, ZT_PYTHON=sys.executable), tmp_path)
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    assert b"detect" in proc.stdout


@pytest.mark.skipif(os.name == "nt", reason="伪造的 runtime 解释器用 POSIX shell 包装")
def test_installed_desktop_runtime_is_preferred_over_python3(tmp_path):
    home = tmp_path / "dsh-home"
    fake = zt_launch.runtime_python(home / "dsh-runtimes" / "dsh-primary-runtime")
    fake.parent.mkdir(parents=True)
    marker = tmp_path / "used-runtime"
    fake.write_text(f'#!/bin/sh\ntouch "{marker}"\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    fake.chmod(0o755)
    bare = _bare_venv(tmp_path)
    proc = _run(bare, SCRIPT, ["--help"], _env(tmp_path), tmp_path)
    assert proc.returncode == 0, proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    assert marker.exists()


def test_importing_a_script_never_relaunches(tmp_path, monkeypatch):
    monkeypatch.setenv("ZT_PYTHON", str(tmp_path / "nope" / "python3"))
    # 测试进程不是以脚本为 __main__ 运行：不选解释器、不重跑，只保证 zt 可导入。
    zt_launch.ensure(str(SCRIPT), environ=dict(os.environ), argv=[])


def test_bundled_runtime_is_found_from_the_unpacked_archive_layout(tmp_path):
    resources = tmp_path / "DeepSeek Harness.app" / "Contents" / "Resources"
    here = resources / "app.asar.unpacked" / "dsh" / "node_modules" / "@zhitong" / "bundle" / "skills" / "_shared" / "zt_launch.py"
    assert zt_launch.bundled_runtime(here) == resources / "runtime" / "primary-runtime"
    assert zt_launch.bundled_runtime(SHARED / "zt_launch.py") is None
    sources = [source for source, _ in zt_launch.candidates({"DSH_HOME": str(tmp_path)}, here)]
    assert sources == ["installed-runtime", "bundled-runtime"]
    assert zt_launch.candidates({"ZT_PYTHON": "/x/python3", "DSH_HOME": str(tmp_path)}, here) == [("ZT_PYTHON", Path("/x/python3"))]


def test_packed_bundle_layout_puts_zt_beside_the_skills(tmp_path):
    bundle = tmp_path / "bundle"
    shutil.copytree(SHARED, bundle / "skills" / "_shared")
    (bundle / "python" / "zt").mkdir(parents=True)
    (bundle / "python" / "zt" / "__init__.py").write_text("", encoding="utf-8")
    assert zt_launch.zt_source_dir(bundle / "skills" / "_shared" / "zt_launch.py") == bundle / "python"
    assert zt_launch.zt_source_dir(tmp_path / "skills" / "_shared" / "zt_launch.py") is None
