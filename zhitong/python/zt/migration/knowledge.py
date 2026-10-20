"""旧系统知识库目录 → 桶 ``知识库/<规范|定额|费率|模板|公司经验>/`` 的映射与各子目录 README（spec §5、§6 第 6 条）。

旧目录：``<base>/knowledge/<sysCompanyCode>/<分类名__categoryId>/.../<disk_file_name>``（旧仓
``TenantKnowledgePaths``）；没跑过租户迁移脚本的旧文件仍在平铺的 ``<base>/knowledge/<分类名__id>/``。
映射规则在 ``zhitong/migration/data/knowledge_map.yaml``，未映射的一级目录报错，不猜去向。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from zt.common import ZtError

SUBDIRS = ("规范", "定额", "费率", "模板", "公司经验")
ROOT_KEY = "(根目录)"
_ID_SUFFIX = re.compile(r"__\d+$")

SUBDIR_PURPOSE = {
    "规范": "国家与地方标准、工程量计算规范、清单计价规范与清单编码资料。",
    "定额": "消耗量定额、计价定额及其说明。",
    "费率": "取费标准、费率表、其他费用定额。",
    "模板": "报告、函件与表格模板。",
    "公司经验": "工作中形成的口径与经验，由 agent 在工作中回写，每条带来源与日期。",
}


def strip_category_id(seg: str) -> str:
    """去掉旧目录名的 ``__<分类id>`` 后缀。

    :param seg: 目录名，如 ``定额__1712``。
    :returns: 分类名，如 ``定额``；没有后缀时原样返回。
    """
    return _ID_SUFFIX.sub("", seg) or seg


@dataclass
class KnowledgeMap:
    """一级目录到子目录的映射。"""

    exclude: set[str] = field(default_factory=set)
    exact: dict[str, str] = field(default_factory=dict)
    rules: list[tuple[str, str, str]] = field(default_factory=list)  # (contains|regex, 模式, 子目录)

    def resolve(self, top: Optional[str]) -> Optional[str]:
        """一级目录的去向。

        :param top: 一级目录原名；文件直接在根下时为 None。
        :returns: 子目录名；排除的目录为 ``""``；没有规则命中为 None。
        """
        if top is None:
            return self.exact.get(ROOT_KEY)
        if top in self.exclude:
            return ""
        name = strip_category_id(top)
        for key in (top, name):
            if key in self.exact:
                return self.exact[key]
        for kind, pattern, to in self.rules:
            if (kind == "contains" and pattern in name) or (kind == "regex" and re.search(pattern, name)):
                return to
        return None


def load_knowledge_map(path: Path) -> KnowledgeMap:
    """读映射文件。

    :param path: YAML 文件。
    :returns: 映射。
    :raises ZtError: 文件缺失或内容不合法（``knowledge_map_invalid``）。
    """
    if not path.is_file():
        raise ZtError("knowledge_map_invalid", f"找不到知识库映射文件：{path}")
    try:
        doc: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise ZtError("knowledge_map_invalid", f"知识库映射文件不是合法 YAML：{e}") from e
    if not isinstance(doc, dict):
        raise ZtError("knowledge_map_invalid", "知识库映射文件必须是映射")

    def check(to: Any, where: str) -> str:
        if to not in SUBDIRS:
            raise ZtError("knowledge_map_invalid", f"{where} 的去向 {to!r} 不是 {'/'.join(SUBDIRS)} 之一")
        return str(to)

    km = KnowledgeMap(exclude={str(x) for x in doc.get("exclude") or []})
    for k, v in (doc.get("exact") or {}).items():
        km.exact[str(k)] = check(v, f"exact[{k}]")
    for i, r in enumerate(doc.get("rules") or []):
        if not isinstance(r, dict) or ("contains" in r) == ("regex" in r):
            raise ZtError("knowledge_map_invalid", f"rules[{i}] 必须恰好有 contains 或 regex 之一")
        kind = "contains" if "contains" in r else "regex"
        pattern = str(r[kind])
        if kind == "regex":
            try:
                re.compile(pattern)
            except re.error as e:
                raise ZtError("knowledge_map_invalid", f"rules[{i}] 的正则不合法：{e}") from e
        km.rules.append((kind, pattern, check(r.get("to"), f"rules[{i}]")))
    return km


def render_readme(sub: str, seed_readme: Optional[str], categories: dict[str, int],
                  roots: list[str], no_text_pdfs: list[str]) -> str:
    """生成 ``知识库/<sub>/README.md``。

    :param sub: 子目录名。
    :param seed_readme: knowledge-seed 里同名子目录的 README 全文；没有为 None。
    :param categories: 旧系统迁入的 ``{分类目录（子目录内相对路径）: 文件数}``。
    :param roots: 旧知识库源目录（写进来源说明）。
    :param no_text_pdfs: 迁入的、没有可用旁车的 PDF（子目录内相对路径）。
    :returns: README 全文。
    """
    if seed_readme is not None:
        head = seed_readme.rstrip("\n")
    else:
        head = f"# {sub}\n\n{SUBDIR_PURPOSE[sub]}"
    lines = [head, "", "## 旧系统迁入", ""]
    if not categories:
        lines.append("迁移时旧系统知识库没有归入本目录的文件。")
    else:
        src = "、".join(f"`{r}`" for r in roots) if roots else "旧系统知识库"
        lines.append(f"来源：旧系统知识库目录 {src}，按 `zhitong/migration/data/knowledge_map.yaml` 归入本目录；"
                     "目录名去掉了旧分类 id 后缀，文件名还原为旧系统的显示名。各分类的文件数：")
        lines.append("")
        lines += [f"- `{k}/` {n} 个文件" for k, n in sorted(categories.items())]
        if no_text_pdfs:
            lines += ["", "下列 PDF 没有可用的 OCR 旁车，可能是无文字层的扫描书，由 zt-knowledge 用看图逐页补文本：", ""]
            lines += [f"- `{p}`" for p in sorted(no_text_pdfs)]
    return "\n".join(lines).rstrip("\n") + "\n"
