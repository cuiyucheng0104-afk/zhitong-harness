"""zt-project 数据目录的定位与 YAML 读取。

数据文件（分类规则、清单、类目折算表、证据冲突表）放在 ``zhitong/skills/zt-project/data/``，是普通文件，
可事后修改；Python 不内嵌它们。定位顺序：

1. 调用方显式传入的目录（CLI 的 ``--data-dir``）；
2. 环境变量 ``ZT_PROJECT_DATA``（skill 脚本启动时设置为自己旁边的 ``data/``）；
3. 源码树里的 ``zhitong/skills/zt-project/data``（开发与测试）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

from zt.common import ZtError

ENV_DATA_DIR = "ZT_PROJECT_DATA"
CLASSIFY_RULES = "classify_rules.yaml"
CHECKLIST = "checklist.yaml"
CATEGORY_MAP = "doc_category_map.yaml"
EVIDENCE_RULES = "audit_evidence_rules.yaml"
REQUIRED_FILES = (CLASSIFY_RULES, CHECKLIST, CATEGORY_MAP, EVIDENCE_RULES)

# zhitong/python/zt/inventory/data.py → parents[3] = zhitong/
_SOURCE_TREE_DATA = Path(__file__).resolve().parents[3] / "skills" / "zt-project" / "data"


def data_dir(override: Optional[str | Path] = None) -> Path:
    """解析 zt-project 数据目录并确认四个数据文件都在。

    :param override: 显式目录；None 时依次看环境变量与源码树。
    :returns: 数据目录。
    :raises ZtError: 目录不存在或缺文件（``data_dir_invalid``）。
    """
    if override is not None:
        base = Path(override)
    elif os.environ.get(ENV_DATA_DIR):
        base = Path(os.environ[ENV_DATA_DIR])
    else:
        base = _SOURCE_TREE_DATA
    missing = [n for n in REQUIRED_FILES if not (base / n).is_file()]
    if missing:
        raise ZtError("data_dir_invalid", f"zt-project 数据目录不完整：{base}（缺 {'、'.join(missing)}）",
                      hint=f"用 --data-dir 指定，或设置环境变量 {ENV_DATA_DIR}")
    return base


def read_yaml(path: Path) -> Any:
    """读 UTF-8 YAML。

    :param path: 文件路径。
    :returns: 解析结果；空文件为 ``{}``。
    :raises ZtError: 文件缺失（``data_file_not_found``）或 YAML 非法（``data_file_invalid``）。
    """
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise ZtError("data_file_not_found", f"找不到数据文件：{path}") from None
    except yaml.YAMLError as e:
        raise ZtError("data_file_invalid", f"数据文件不是合法 YAML：{path}（{e}）") from e
