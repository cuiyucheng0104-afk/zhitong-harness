#!/usr/bin/env python3
"""zt-knowledge 校验脚本：知识库目录与条目的来源纪律检查（零模型，只读）。

检查对象是 knowledge-seed 或本机知识库缓存（与桶 `知识库/` 同构）。规则：

- ``missing_readme``：根目录和每个子目录都要有 ``README.md``。例外：``repo-snapshot`` 目录内部的镜像子目录
  （它们复刻旧仓路径，只在 ``repo-snapshot/README.md`` 登记）。
- ``missing_source``：内容目录（根下不以 ``_`` 或 ``.`` 开头的目录）里除 ``README.md`` 外的每个 ``.md`` 条目必须有来源字段，
  形态二选一：头部 YAML 的 ``来源``（非空字符串或字符串列表，且不是「搜不到」之类占位），
  或脚本生成件文件头前 40 行内的 ``> 来源：`` 行。
- ``missing_date``：YAML 条目要有 ``抓取日期`` 或 ``日期``（以 YYYY-MM-DD 开头）；来源含 http(s) URL 的条目必须是 ``抓取日期``。
  生成件要有 ``> 生成：`` 行且含 YYYY-MM-DD。
- ``missing_scope``：YAML 条目要有非空 ``适用范围``。
- ``bad_frontmatter``：头部 YAML 无法解析。

用法::

    python3 check_knowledge.py [--root 知识库根目录]

stdout 只输出一个 JSON（结果信封字段）。退出码：0 全部通过；1 有违规（status=partial，warning_items 逐条列出）；
2 调用错误（根目录不存在等，stdout 为 {"error": ...}）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "_shared"))
import zt_launch  # noqa: E402  解释器与 zt 定位：../../_shared/zt_launch.py

zt_launch.ensure(__file__)

import argparse
import json
import re
from typing import Any

import yaml

README = "README.md"
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
MIRROR_PARENT = "repo-snapshot"
PLACEHOLDERS = {"搜不到", "无", "待补", "待补充", "tbd", "todo", "n/a", "-", ""}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
ANY_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
GENERATED_HEAD_LINES = 40
SOURCE_LINE_RE = re.compile(r"^>\s*来源[:：]\s*\S")
STAMP_LINE_RE = re.compile(r"^>\s*生成[:：]")


def split_frontmatter(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """切出头部 YAML。

    :param text: 文件全文。
    :returns: ``(字段字典, 错误)``；没有头部时 ``(None, None)``；头部存在但解析失败时 ``(None, 错误说明)``。
    """
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return None, None
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return None, None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            try:
                data = yaml.safe_load("\n".join(lines[1:idx]))
            except yaml.YAMLError as exc:
                return None, str(exc).replace("\n", " ")
            if not isinstance(data, dict):
                return None, "头部 YAML 不是键值映射"
            return data, None
    return None, "头部 YAML 没有结束的 ---"


def source_values(raw: Any) -> list[str]:
    """把 ``来源`` 字段规整为非占位的字符串列表。"""
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for item in items:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if value.lower() in PLACEHOLDERS:
            continue
        out.append(value)
    return out


def check_entry(path: Path, rel: str) -> list[dict[str, str]]:
    """检查一个条目文件，返回告警列表（空表示通过）。"""
    text = path.read_text(encoding="utf-8")
    meta, err = split_frontmatter(text)
    problems: list[dict[str, str]] = []

    def add(code: str, message: str, hint: str) -> None:
        problems.append({"code": code, "level": "error", "message": f"{rel}：{message}", "hint": hint})

    if err:
        add("bad_frontmatter", f"头部 YAML 解析失败（{err}）", "含「: 」的值加引号，或改写")
        return problems
    if meta is not None:
        sources = source_values(meta.get("来源"))
        if not sources:
            add("missing_source", "缺少非空的 来源 字段", "写 URL 或内部来源路径；搜不到的内容写在正文「搜不到」一节，不当作来源")
        date = meta.get("抓取日期") if meta.get("抓取日期") is not None else meta.get("日期")
        if date is None or not DATE_RE.match(str(date).strip()):
            add("missing_date", "缺少 YYYY-MM-DD 开头的 抓取日期 或 日期", "补日期")
        if any(URL_RE.match(s) for s in sources) and not DATE_RE.match(str(meta.get("抓取日期", "")).strip()):
            add("missing_date", "来源含 URL 但没有 抓取日期", "网页来源必须写 抓取日期")
        scope = meta.get("适用范围")
        if not (isinstance(scope, str) and scope.strip()):
            add("missing_scope", "缺少非空的 适用范围", "写地区、专业、适用阶段")
        return problems
    head = text.lstrip("﻿").split("\n")[:GENERATED_HEAD_LINES]
    if not any(SOURCE_LINE_RE.match(line) for line in head):
        add("missing_source", "没有头部 YAML，文件头前 40 行也没有「> 来源：」行", "按条目格式补头部 YAML")
    stamp = [line for line in head if STAMP_LINE_RE.match(line)]
    if not any(ANY_DATE_RE.search(line) for line in stamp):
        add("missing_date", "生成件文件头没有含 YYYY-MM-DD 的「> 生成：」行", "由生成器写入，不手补")
    return problems


def walk_dirs(root: Path) -> list[Path]:
    """列出 root 及其全部子目录（跳过 SKIP_DIRS），排序稳定。"""
    found = [root]
    for path in sorted(root.rglob("*")):
        if path.is_dir() and not (set(path.relative_to(root).parts) & SKIP_DIRS):
            found.append(path)
    return found


def is_mirror_interior(path: Path, root: Path) -> bool:
    """``repo-snapshot`` 目录内部的镜像子目录（不含 repo-snapshot 本身）。"""
    parts = path.relative_to(root).parts
    return MIRROR_PARENT in parts and parts[-1] != MIRROR_PARENT


def run(root: Path) -> dict[str, Any]:
    """检查 root，返回结果信封字典。"""
    warnings: list[dict[str, str]] = []
    dirs = [d for d in walk_dirs(root) if not is_mirror_interior(d, root)]
    for directory in dirs:
        if not (directory / README).is_file():
            rel = directory.relative_to(root).as_posix() or "."
            warnings.append({"code": "missing_readme", "level": "error",
                             "message": f"{rel}：目录缺少 README.md", "hint": "写明目录内容与来源"})
    entries: list[Path] = []
    for top in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")) and p.name not in SKIP_DIRS):
        for path in sorted(top.rglob("*.md")):
            if path.name != README and not (set(path.relative_to(root).parts) & SKIP_DIRS):
                entries.append(path)
    for path in entries:
        warnings.extend(check_entry(path, path.relative_to(root).as_posix()))
    failed = bool(warnings)
    coverage = {"directories_checked": len(dirs), "entries_checked": len(entries),
                "violations": len(warnings)}
    return {
        "status": "partial" if failed else "ok",
        "status_reason": "violations_found" if failed else None,
        "coverage": coverage,
        "warning_items": warnings,
        "data": {"root": root.as_posix(), **coverage},
        "needs_manual": True,
    }


def main(argv: list[str] | None = None) -> int:
    """命令行入口，返回退出码。"""
    default_root = Path(__file__).resolve().parents[3] / "knowledge-seed"
    parser = argparse.ArgumentParser(description="检查知识库目录与条目的来源纪律")
    parser.add_argument("--root", default=str(default_root), help="知识库根目录（默认 zhitong/knowledge-seed）")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(json.dumps({"error": {"code": "root_not_found", "message": f"目录不存在：{root}",
                                    "hint": "用 --root 指向知识库根目录"}}, ensure_ascii=False))
        return 2
    result = run(root)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["warning_items"] else 0


if __name__ == "__main__":
    sys.exit(main())
