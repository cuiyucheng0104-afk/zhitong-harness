"""``整理报告.md``：给人读的整理结果（spec §6 第 7 条「删了什么、改了什么名」）。

数据全部来自整理计划与 manifest；报告只是它们的 Markdown 视图，不含 manifest 里没有的结论。
"""
from __future__ import annotations

from typing import Any

from zt.migration.relayout import NOT_MIGRATED, REASONS, Plan, summarize
from zt.migration.rows import now_iso

RENAME_REASONS = {
    "display_name_restored": "磁盘名还原为显示名",
    "unsafe_chars": "名字含 Windows 不允许的字符或需 Unicode 规范化",
    "name_collision": "还原后同目录重名，加序号",
}


def _cell(v: Any) -> str:
    return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")


def _size(n: Any) -> str:
    if n is None:
        return ""
    n = int(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return str(n)


def render_report(plan: Plan, manifest: dict[str, Any], stats: dict[str, int]) -> str:
    """渲染整理报告。

    :param plan: 整理计划。
    :param manifest: 已写出的 manifest。
    :param stats: :func:`zt.migration.relayout.execute` 的执行统计。
    :returns: Markdown 全文。
    """
    s = summarize(plan)
    lines = [
        "# 整理报告", "",
        f"生成时间：{now_iso()}；源目录：`{manifest['nas']}`；镜像：`{manifest['mirror']}`；放置方式：{manifest['link']}。",
        "源目录只读；本报告与 `manifest.json` 一一对应，逐文件明细以 manifest 为准。", "",
        "## 概要", "",
        "| 项 | 数 |", "|---|---|",
        f"| 项目 | {s['projects']} |",
        f"| 迁入镜像的文件（不含生成的说明文件） | {s['outputs']}（{_size(s['output_bytes'])}） |",
        f"| 其中归入 图纸/ | {s['drawings']} |",
        f"| 其中 OCR 旁车 | {s['outputs_by_kind'].get('sidecar', 0)} |",
        f"| 删除 | {s['deletions']}（{_size(s['deletion_bytes'])}） |",
        f"| 改名（不含只换上级目录的） | {s['renames']} |",
        f"| 空目录（不迁移） | {s['empty_folders']} |",
        f"| 本次新放置 / 已就位 / 替换 | {stats['linked'] + stats['copied']} / {stats['kept']} / {stats['replaced']} |",
        f"| 镜像里删除的陈旧文件 | {stats['stale_removed']} |",
        "",
    ]
    if plan.warnings:
        lines += ["## 告警", ""]
        lines += [f"- `{w.code}` {w.message}" for w in plan.warnings]
        lines.append("")
    lines += ["## 删除（按原因）", "", "| 原因 | 说明 | 文件数 |", "|---|---|---|"]
    for code, n in sorted(s["deletions_by_reason"].items()):
        lines.append(f"| `{code}` | {REASONS.get(code, code)} | {n} |")
    lines += ["", "## 未迁移（按原因）", "", "| 原因 | 说明 | 文件数 |", "|---|---|---|"]
    for code, n in sorted(s["not_migrated_by_reason"].items()):
        lines.append(f"| `{code}` | {NOT_MIGRATED.get(code, code)} | {n} |")
    lines += ["", "## 项目", "", "| 编号 | 目录 | 旧 project.id | 编号来源 | 别名 | 迁入文件 | 删除 |", "|---|---|---|---|---|---|---|"]
    origin = {"state": "沿用上次", "client": "客户编号", "allocated": "按年流水分配"}
    for p in plan.projects:
        n_out = sum(1 for o in plan.outputs if o["group"] == p["id"])
        n_del = sum(1 for d in plan.deletions if d["group"] == p["id"])
        lines.append(f"| {p['code']} | `{_cell(p['dir'])}` | {p['id']} | {origin[p['code_origin']]} | "
                     f"{_cell('、'.join(p['aliases']))} | {n_out} | {n_del} |")
    lines += ["", "## 删除清单", "", "| 归属 | 旧路径（相对源目录） | 原因 | 大小 | 保留件 |", "|---|---|---|---|---|"]
    for d in sorted(plan.deletions, key=lambda d: (d["label"], d["old_rel"])):
        lines.append(f"| {_cell(d['label'])} | `{_cell(d['old_rel'])}` | `{d['reason']}` | {_size(d.get('size'))} | "
                     f"{('`' + _cell(d['kept']) + '`') if d.get('kept') else ''} |")
    lines += ["", "## 未迁移清单", "", "| 归属 | 旧路径（相对源目录） | 原因 |", "|---|---|---|"]
    for d in sorted(plan.not_migrated, key=lambda d: (d["label"], d["reason"], d["old_rel"])):
        lines.append(f"| {_cell(d['label'])} | `{_cell(d['old_rel'])}` | `{d['reason']}` |")
    lines += ["", "## 改名清单", "", "旧路径相对源目录（项目为 `<project.id>/` 之下），新路径相对镜像根。", "",
              "| 旧路径 | 新路径 | 原因 |", "|---|---|---|"]
    for r in sorted(plan.renames, key=lambda r: r["new"]):
        why = "、".join(RENAME_REASONS.get(x, x) for x in r["reasons"])
        lines.append(f"| `{_cell(r['old_rel'])}` | `{_cell(r['new'])}` | {why} |")
    if plan.empty_folders:
        lines += ["", "## 空目录（不迁移）", ""]
        lines += [f"- {_cell(e['label'])}：`{_cell(e['display_path'])}`" for e in plan.empty_folders]
    if manifest.get("stale_removed"):
        lines += ["", "## 镜像里删除的陈旧文件", "", "上次运行留下、本次计划里没有的文件（只删镜像，不碰源目录）：", ""]
        lines += [f"- `{_cell(p)}`" for p in manifest["stale_removed"]]
    return "\n".join(lines).rstrip("\n") + "\n"
