"""skill 脚本的统一启动器：选定 Python 解释器，让 ``zt`` 可导入，导入不了就按结果契约报错。

每个 ``skills/<名>/scripts/*.py`` 在导入 ``zt`` 之前执行（``from __future__`` 之后）::

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
    import zt_launch  # noqa: E402
    zt_launch.ensure(__file__)

解释器按顺序取第一个存在的：

1. 环境变量 ``ZT_PYTHON``（设置了却不存在时直接报错，不往下找）；
2. 桌面版已安装的 primary runtime：``$DSH_HOME/dsh-runtimes/dsh-primary-runtime/dependencies/python/``
   下的 ``bin/python3``（Windows 为 ``python.exe``）；``DSH_HOME`` 未设置时为 ``~/.dsh``；
3. 桌面版安装包自带的 primary runtime：本文件位于 ``<Resources>/app.asar.unpacked/...`` 时的
   ``<Resources>/runtime/primary-runtime/dependencies/python/``；
4. 当前解释器（通常是 ``python3``）。

选中的不是当前解释器时，用它重新运行本脚本，参数原样传递（POSIX 用 ``execv``；Windows 起子进程并转发退出码）。
重跑只发生一次（``ZT_LAUNCHED=1``），且只在脚本作为 ``__main__`` 运行时发生；被测试 ``import`` 时不重跑。

``zt`` 包：当前解释器能导入就用；否则把 skills 目录旁的 ``python/`` 加进 ``sys.path``
（仓库里是 ``zhitong/python``，安装包里是 ``@zhitong/bundle/python``）。

Python 低于 3.11、``zt`` 或其依赖（pydantic、PyYAML、openpyxl、pypdf、python-docx）导入不了时，stdout 输出一行
``{"error": {"code": "zt_not_importable", "message": ..., "hint": ...}}``，退出码 2。

本文件只用 Python 3.6 也能解析的语法，好在旧的系统 ``python3`` 下也能走到报错或重跑这一步。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

EXIT_ERROR = 2
ENV_PYTHON = "ZT_PYTHON"
ENV_LAUNCHED = "ZT_LAUNCHED"
MIN_VERSION = (3, 11)
# 顶层模块名 → 发行包名（报错提示用）
DEPENDENCIES = (
    ("pydantic", "pydantic"),
    ("yaml", "PyYAML"),
    ("openpyxl", "openpyxl"),
    ("pypdf", "pypdf"),
    ("docx", "python-docx"),
)
PRIMARY_RUNTIME = ("dsh-runtimes", "dsh-primary-runtime")


def runtime_python(runtime_root):
    """primary runtime 目录里的解释器路径（不检查是否存在）。

    :param runtime_root: 含 ``runtime.json`` 与 ``dependencies/`` 的目录。
    :returns: 解释器路径。
    """
    python = Path(runtime_root) / "dependencies" / "python"
    return python / "python.exe" if os.name == "nt" else python / "bin" / "python3"


def dsh_home(environ):
    """Harness home：``DSH_HOME``，未设置时 ``~/.dsh``。"""
    configured = environ.get("DSH_HOME", "").strip()
    return Path(os.path.expanduser(configured)) if configured else Path.home() / ".dsh"


def bundled_runtime(here):
    """安装包内 primary runtime 目录；``here`` 不在 ``app.asar.unpacked`` 下时返回 None。"""
    for parent in Path(here).parents:
        if parent.name == "app.asar.unpacked":
            return parent.parent / "runtime" / "primary-runtime"
    return None


def candidates(environ, here):
    """按优先级列出 ``(来源, 解释器路径)``；``ZT_PYTHON`` 设置时它是唯一候选。"""
    explicit = environ.get(ENV_PYTHON, "").strip()
    if explicit:
        return [(ENV_PYTHON, Path(os.path.expanduser(explicit)))]
    found = [("installed-runtime", runtime_python(dsh_home(environ).joinpath(*PRIMARY_RUNTIME)))]
    bundled = bundled_runtime(here)
    if bundled is not None:
        found.append(("bundled-runtime", runtime_python(bundled)))
    return found


def choose(environ, here):
    """选解释器。

    :returns: ``(来源, 路径)``；没有可用候选时 ``(None, None)``，表示用当前解释器。
    :raises LaunchError: ``ZT_PYTHON`` 指向的文件不存在。
    """
    for source, path in candidates(environ, here):
        if path.is_file():
            return source, path
        if source == ENV_PYTHON:
            raise LaunchError(
                "环境变量 ZT_PYTHON 指向的解释器不存在：{}".format(path),
                "把 ZT_PYTHON 改成存在的 Python ≥ 3.11 解释器的绝对路径，或删掉它改用桌面版内置 Python",
            )
    return None, None


def is_current(path):
    """``path`` 是否就是正在运行的解释器。

    路径字面相同即是；字面不同但指向同一文件时，只有两者都不是虚拟环境入口才算同一个
    （venv 的 python 链接到基础解释器，但 site-packages 不同）。
    """
    current = Path(sys.executable)
    if os.path.normcase(os.path.abspath(str(path))) == os.path.normcase(os.path.abspath(str(current))):
        return True
    try:
        same = os.path.samefile(str(path), str(current))
    except OSError:
        return False
    in_venv = (Path(path).parent.parent / "pyvenv.cfg").is_file()
    return same and not in_venv and sys.prefix == getattr(sys, "base_prefix", sys.prefix)


def relaunch(path, script, argv, environ):
    """用 ``path`` 重跑 ``script``；成功时不返回。"""
    env = dict(environ)
    env[ENV_LAUNCHED] = "1"
    args = [str(path), str(script)] + list(argv)
    if os.name == "nt":
        sys.stdout.flush()
        sys.stderr.flush()
        sys.exit(subprocess.call(args, env=env))
    os.execve(str(path), args, env)


def zt_source_dir(here):
    """skills 目录旁的 ``python/``（其中有 ``zt/__init__.py`` 时）；没有则 None。"""
    python_dir = Path(here).resolve().parent.parent.parent / "python"
    return python_dir if (python_dir / "zt" / "__init__.py").is_file() else None


def missing_dependencies():
    """当前解释器里找不到的依赖发行包名。"""
    import importlib.util

    return [dist for module, dist in DEPENDENCIES if importlib.util.find_spec(module) is None]


class LaunchError(Exception):
    """启动失败：转成 ``zt_not_importable`` 错误 JSON。"""

    def __init__(self, message, hint):
        Exception.__init__(self, message)
        self.message = message
        self.hint = hint


def fail(error):
    """输出错误 JSON 并以退出码 2 结束。"""
    body = {"error": {"code": "zt_not_importable", "message": error.message, "hint": error.hint}}
    data = (json.dumps(body, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.flush()
    getattr(sys.stdout, "buffer", sys.stdout).write(data)
    sys.stdout.flush()
    sys.exit(EXIT_ERROR)


def prepare_imports(here, chosen):
    """在当前解释器里让 ``zt`` 及其依赖可导入。

    :param here: 本文件路径。
    :param chosen: ``choose`` 的结果 ``(来源, 路径)``，只用于报错说明。
    :raises LaunchError: 版本过低、``zt`` 或依赖不可导入。
    """
    import importlib.util

    where = "当前解释器 {}（Python {}.{}）".format(sys.executable, sys.version_info[0], sys.version_info[1])
    hint = ("在桌面版里调用 load_workspace_dependencies，用返回的 python 绝对路径运行脚本；"
            "开发环境在 zhitong/python 下执行 uv sync，并把 ZT_PYTHON 设为 .venv 里的 python")
    if chosen[0] is not None:
        where = "{}（来自 {}）".format(where, chosen[0])
    if sys.version_info[:2] < MIN_VERSION:
        raise LaunchError("{} 版本低于 3.11，zt 需要 Python ≥ 3.11".format(where), hint)
    if importlib.util.find_spec("zt") is None:
        source = zt_source_dir(here)
        if source is not None:
            sys.path.insert(0, str(source))
    if importlib.util.find_spec("zt") is None:
        raise LaunchError("{} 找不到 zt 包（skills 旁也没有 python/zt）".format(where), hint)
    missing = missing_dependencies()
    if missing:
        raise LaunchError("{} 缺少 zt 的依赖：{}".format(where, "、".join(missing)), hint)


def force_utf8_stdio():
    """把 stdout/stderr 切到 UTF-8：Windows 控制台与 GitHub runner 默认是本地代码页，中文帮助文本会抛 UnicodeEncodeError。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # 流已关闭或不可重配：保持原样
                pass


def ensure(script, environ=None, argv=None):
    """脚本入口调用：必要时换解释器重跑，然后保证 ``zt`` 可导入；失败时输出错误 JSON 并退出。

    :param script: 调用方的 ``__file__``。
    :param environ: 环境变量映射；默认 ``os.environ``。
    :param argv: 传给重跑的参数；默认 ``sys.argv[1:]``。
    """
    environ = os.environ if environ is None else environ
    argv = sys.argv[1:] if argv is None else argv
    here = Path(__file__)
    force_utf8_stdio()
    try:
        chosen = (None, None)
        main = getattr(sys.modules.get("__main__"), "__file__", None)
        if environ.get(ENV_LAUNCHED) != "1" and main is not None \
                and os.path.abspath(main) == os.path.abspath(str(script)):
            chosen = choose(environ, here)
            if chosen[1] is not None and not is_current(chosen[1]):
                relaunch(chosen[1], os.path.abspath(str(script)), argv, environ)
        prepare_imports(here, chosen)
    except LaunchError as error:
        fail(error)
