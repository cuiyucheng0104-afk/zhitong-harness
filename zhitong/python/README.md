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
