"""给没有 ``项目说明.md`` 的项目目录生成草稿。

草稿从目录名取项目编号与工程名，从目录结构生成概览，从文件名规则给「关键文件指引」填候选路径。
咨询类型与阶段不猜：没给就写「待确认」，之后的盘点会因此报错并要求用户确认，不会悄悄按通用清单跑。
候选路径只是按文件名判断的线索，备注里标「待确认」，agent 必须打开核对后才能去掉。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Optional

from zt.inventory.projectdoc import render_template, replace_section
from zt.inventory.rules import ClassifyInput
from zt.inventory.scan import InventoryData, ScanResult, scan_files

UNDECIDED = "待确认"
_DIR_NAME = re.compile(r"^(?P<code>\d{4}-\d{3})-(?P<name>.+)$")

# 关键文件指引的行 → 清单口径类目（分类器类目经折算后比较）
KEY_FILE_ROWS: tuple[tuple[str, frozenset[str]], ...] = (
    ("合同", frozenset({"施工合同及补充协议"})),
    ("招标文件 / 招标控制价", frozenset({"招标控制价", "招标文件"})),
    ("工程量清单", frozenset({"工程量清单"})),
    ("送审计价表", frozenset({"结算送审书"})),
    ("审定计价表", frozenset({"审定单"})),
    ("设计说明", frozenset({"设计说明图"})),
)
_OVERVIEW_MAX_FOLDERS = 40
_MAX_CANDIDATES = 3


def split_dir_name(name: str) -> tuple[str, str]:
    """把目录名 ``<编号>-<工程名>`` 拆开。

    :param name: 项目目录名。
    :returns: ``(编号, 工程名)``；不符合格式时编号为空串，工程名是整个目录名。
    """
    m = _DIR_NAME.match(name)
    return (m["code"], m["name"]) if m else ("", name)


def key_file_candidates(scan: ScanResult, data: InventoryData) -> dict[str, list[str]]:
    """按文件名强规则找每个关键文件行的候选路径（路径短的在前，每行至多 3 个）。

    :param scan: 已登记的文件。
    :param data: 盘点数据。
    :returns: ``{行标签: [rel_path]}``，没有候选的行也在表里。
    """
    canon = data.audit_rules.vocab.canonical
    found: dict[str, list[str]] = {label: [] for label, _ in KEY_FILE_ROWS}
    for f in scan.files:
        o = data.engine.classify_one(ClassifyInput(f.rel_path, f.name, f.ext, ancestors=list(f.ancestors)))
        if o.evidence != "filename_rule" or not o.doc_category:
            continue
        cat = canon(o.doc_category)
        for label, cats in KEY_FILE_ROWS:
            if cat in cats or o.doc_category in cats:
                found[label].append(f.rel_path)
    return {k: sorted(v, key=lambda p: (len(p), p))[:_MAX_CANDIDATES] for k, v in found.items()}


def overview(scan: ScanResult) -> str:
    """目录结构概览：每个二级目录下的文件数。

    :param scan: 已登记的文件。
    :returns: Markdown 列表正文。
    """
    counts: dict[str, int] = {}
    for f in scan.files:
        parts = PurePosixPath(f.rel_path).parts
        key = "/".join(parts[:2]) + "/" if len(parts) > 2 else (parts[0] + "/" if len(parts) > 1 else "（项目根）")
        counts[key] = counts.get(key, 0) + 1
    items = sorted(counts.items())
    lines = [f"- `{k}` {n} 个文件" for k, n in items[:_OVERVIEW_MAX_FOLDERS]]
    if len(items) > _OVERVIEW_MAX_FOLDERS:
        lines.append(f"- 另有 {len(items) - _OVERVIEW_MAX_FOLDERS} 个目录未列出")
    return "\n".join(lines) if lines else "项目目录里还没有资料文件。"


def draft_project_doc(project_dir: Path, data: InventoryData, template: str, *,
                      code: Optional[str] = None, name: Optional[str] = None,
                      consulting_type: Optional[str] = None, stage: Optional[str] = None,
                      today: Optional[date] = None) -> str:
    """生成项目说明草稿。

    :param project_dir: 项目目录。
    :param data: 盘点数据。
    :param template: 项目说明模板全文。
    :param code: 项目编号；缺省取目录名前缀，取不到为空（之后必须补）。
    :param name: 工程名称；缺省取目录名去掉编号的部分。
    :param consulting_type: 咨询类型；缺省「待确认」。
    :param stage: 阶段；缺省「待确认」。
    :param today: 建立日期；缺省今天。
    :returns: 草稿全文。
    :raises zt.common.ZtError: 项目目录不存在。
    """
    dir_code, dir_name = split_dir_name(project_dir.resolve().name)
    scan = scan_files(project_dir)
    values: dict[str, Any] = {
        "项目编号": code if code is not None else dir_code,
        "工程名称": name or dir_name,
        "咨询类型": consulting_type or UNDECIDED,
        "阶段": stage or UNDECIDED,
        "业态": "", "规模": "", "别名": [], "旧系统项目ID": "", "状态": "进行中",
        "建立日期": (today or date.today()).isoformat(),
    }
    text = render_template(template, values)
    cands = key_file_candidates(scan, data)
    rows = ["| 资料 | 位置 | 备注 |", "|---|---|---|"]
    for label, _cats in KEY_FILE_ROWS:
        paths = cands[label]
        rows.append(f"| {label} | {'；'.join(paths)} | {'按文件名判断，待确认' if paths else ''} |")
    rows.append("| 图纸 | 图纸/ | |")
    guide_intro = ("agent 找文件的入口：写资料在项目内的相对路径。下表的位置是按文件名判断的候选，"
                   "打开核对后把备注里的「待确认」去掉；不确定的留空，不要猜。\n\n")
    text = replace_section(text, "关键文件指引", guide_intro + "\n".join(rows))
    text = replace_section(text, "目录概览", "草稿生成时的目录结构（文件数），之后不自动更新。\n\n" + overview(scan))
    return text
