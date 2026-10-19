# zt：skill 脚本的共享 Python 包

uv 项目，包名 `zt`。各 skill 的 `scripts/*.py` 是薄 CLI，只 import `zt`。约定见 [../CONVENTIONS.md](../CONVENTIONS.md)。

```sh
uv sync                    # 建 .venv（Python ≥ 3.11），安装 zt（可编辑）与依赖
uv run pytest              # 全部测试；tests/<分区>/ 与 zt/<分区>/ 一一对应
```

## zt.common

| 模块 | 内容 |
|---|---|
| `envelope` | 结果信封 `Envelope`（`ok`/`partial`/`empty`/`insufficient` 与组合约束）、`WarningItem`、`FileCoverage`、`manual()` 标注 `needs_manual` |
| `evidence` | 证据定位 `EvidenceRef`（相对项目目录，quote ≤ 200 字） |
| `errors` | `ZtError(code, message, hint)`；脚本失败以退出码 2 + `{"error": …}` 结束 |
| `jsonio` | UTF-8 JSON 读写（原子写入、中文不转义、`Decimal` 写成字符串） |
| `cli` | `Cli` 子命令分发：`--in`/`--out`、stdout 只输出一行 JSON、日志走 stderr、异常转退出码 2 |
| `paths` | 跨平台相对路径规范化、`resolve_within`、项目目录名 `<编号>-<工程名>` |

一个分区的 CLI 写在 `zt/<分区>/cli.py`：

```python
from zt.common import Call, Cli, Envelope, ok, empty

cli = Cli("zt.indicator", "单方造价与章节占比")

@cli.command("run", help="计算指标", arguments=lambda p: p.add_argument("--area", type=float, required=True))
def run(call: Call) -> Envelope:
    ...

if __name__ == "__main__":
    raise SystemExit(cli.main())
```

调用：`$ZT_PYTHON -m zt.indicator.cli run --in request.json --out 工作/2026-10-19-指标/ --area 12000`。

## 各分区 CLI 入口

开发时在本目录 `uv run python -m zt.<分区>.cli <子命令> --help` 查参数。skill 里一律调用对应的 `scripts/*.py`：脚本先经 `skills/_shared/zt_launch.py` 选解释器（`ZT_PYTHON` → 桌面版 primary runtime → `python3`）并把 skills 旁的 `python/` 加进 `sys.path`，`zt` 不可导入时输出 `zt_not_importable` 错误 JSON（退出码 2）。

| 模块 | 子命令 | skill 脚本 |
|---|---|---|
| `zt.textextract.cli` | `extract`、`search`、`check-answer` | `zt-ask/scripts/read_doc.py`、`find_text.py`、`check_answer.py`（各固定一个子命令） |
| `zt.sidecar.cli` | `parse`、`locate` | 无（`textextract` 内部使用；排查旁车时直接调用） |
| `zt.inventory.cli` | `scan` | `zt-project/scripts/inventory.py`；编号与项目说明见 `new_project.py`（`allocate`/`create`）、`project_doc.py`（`show`/`draft`），归档见 `zt-archive/scripts/archive.py`（`check`/`apply`） |
| `zt.costsheet.cli` | `probe` | `zt-reconcile/scripts/probe.py` |
| `zt.reconcile.cli` | `run` | `zt-reconcile/scripts/reconcile.py` |
| `zt.indicator.cli` | `run` | `zt-indicator/scripts/indicator.py` |
| `zt.tk.cli` | `detect`、`review`、`progress` | `zt-tk/scripts/tk.py` |
| `zt.report.cli` | `templates`、`context`、`facts`、`section_prepare`、`section_finalize`、`export`、`fill_template` | `zt-report/scripts/report.py` |
| `zt.quantity.cli` | `prepare`、`finalize`、`render` | `zt-quantity/scripts/quantity.py` |
| `zt.estimate.cli` | `extract_prepare`、`extract_finalize`、`suggest`、`compute`、`template` | `zt-estimate/scripts/estimate.py` |
| `zt.volc.cli` | `whoami`、`ecs-list`、`ecs-status`、`ecs-start`、`ecs-stop`、`ecs-reboot`、`sg-show`、`sg-authorize`、`sg-revoke`、`sg-sync-ip`、`tos-buckets`、`tos-stat`、`tos-ls`、`tos-lifecycle`、`tos-versioning`、`ssh-hosts`、`ssh-exec` | `zt-volc/scripts/volc.py` |

`zt-knowledge/scripts/check_knowledge.py` 不经 `zt` 分区 CLI，直接读知识库目录。

## 运行时依赖与桌面版

`pyproject.toml` 的依赖闭包（pydantic、pydantic-core、annotated-types、typing-inspection、typing-extensions、openpyxl、et-xmlfile、pypdf、PyYAML、python-docx、lxml）都锁在上游 `scripts/primary-runtime/lock.json` 的 cp312 wheel 里，桌面版内置 Python 3.12 直接可用。`zt` 本身不进 wheel 列表：打包时 `zhitong/scripts/pack-desktop.mjs` 把 `zt/` 复制进 `@zhitong/bundle/python/zt`，与 skills 一起解到 asar 外，由启动器加入 `sys.path`。改了依赖要同步更新 lock.json 的五个目标（URL 与 sha256 取自 PyPI JSON API）。
