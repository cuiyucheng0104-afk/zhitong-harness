"""规则分档引擎（文件名 + 祖先目录两层，纯函数）。

来源：/home/user/zhitong-cost-ai/engine-service/app/engine/classify_rules.py（``ClassifyEngine``，
旧 WS13 重排后的判定顺序）。规则数据在 ``zhitong/skills/zt-project/data/classify_rules.yaml``（原文件逐字迁入，
签核状态见该文件头）。

改动：

- 规则从调用方传入的路径加载，不在导入时读文件、不缓存全局；
- 运行参数（置信度、疑词、CAD 扩展名等）原来是旧仓 ``_DEFAULTS`` 硬编码的出厂值，现在是 :class:`EngineConfig`
  的字段，取值逐项照抄，调用方可覆盖；
- 去掉正文标题信号（``classify_by_content`` / ``classify_by_office_title``）与 LLM 兜底相关代码：
  盘点只看文件名与目录，不读正文；
- 系统生成物（``INDEX.md`` / ``.ocr.txt`` 旁车）的判据改用 :mod:`zt.sidecar`；
- 类目只供盘点比对，不写出为文件标签。

判定顺序（命中即停）：

① noise → ② 系统生成物 → ③ 黑名单 + 升档 / 疑词 → ④ archive_ext → ⑤ all_of 复合 → ⑥ 白名单特指
→ ⑦ 带类目的归档词 → ⑧ 设计文档 / CAD 细分 → ⑨ 直属父目录 = 专业词 → ⑩ 祖先目录继承 → ⑪ 白名单裸词
→ ⑫ 只命中无类目专业词 → ⑬ 默认档。

证据级别（``ClassifyOutcome.evidence``）：只有 ``filename_rule`` 是强证据，其余都是弱证据，
核查层（:mod:`zt.inventory.audit`）据此区分「已备」与「待确认」。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from zt.common import ZtError
from zt.sidecar.locate import is_sidecar_name

RULES_VERSION = "zt-inventory-rules-1"

# ClassifyOutcome.evidence 取值
EV_RULE = "filename_rule"          # 文件名命中特指 / 复合 / 带类目归档词 / 设计文档 / 扩展名
EV_BARE = "filename_bareword"      # 文件名只命中裸词（tier: bare）
EV_INHERIT = "ancestor_inherit"    # 自身无信号，继承祖先目录语境
EV_PARENT = "parent_dir_rule"      # 直属父目录名恰好等于专业词（目录信号，不是文件名）
EV_SYSTEM = "system"               # 系统生成物：不是资料，永不当证据

DISPOSITION_SYSTEM = "system"

_STAGE_PERIOD = "施工过程"
# 文件名期次：第N期 / N月(份)进度款|产值 / YYYY年M月…产值|进度款
_PERIOD_RE = re.compile(
    r"第\s*[0-9一二三四五六七八九十百]+\s*期"
    r"|[0-9一二三四五六七八九十]+\s*月份?\s*(?:进度款|产值)"
    r"|\d{4}\s*年\s*\d{1,2}\s*月.{0,8}?(?:产值|进度款)"
)
# 期次覆盖只对这些类目生效（外加 stage_policy: context 的行）：它们既可能是审定成果，
# 也可能是某一期的过程文件，名字带期次就一定是后者。
_PERIOD_CATEGORIES = frozenset({"审核报告", "汇总表", "价款对比分析", "土建对比表", "安装对比表"})

CAD_SUBTYPE_DEFAULT: tuple[tuple[str, str], ...] = (
    ("钢结构", "钢结构图纸"), ("给排水", "给排水图纸"), ("总平面", "总平面图"), ("总图", "总平面图"),
    ("暖通", "暖通图纸"), ("通风", "暖通图纸"), ("空调", "暖通图纸"),
    ("弱电", "智能化图纸"), ("智能化", "智能化图纸"), ("消防", "消防图纸"), ("幕墙", "幕墙图纸"),
    ("精装修", "精装修图纸"), ("装修", "精装修图纸"), ("装饰", "精装修图纸"), ("景观", "景观图纸"), ("绿化", "景观图纸"),
    ("市政", "市政图纸"), ("电气", "电气图纸"), ("结构", "结构图纸"),
    ("平面", "建筑平面图"), ("立面", "建筑立面图"), ("剖面", "建筑剖面图"), ("建筑", "建筑图纸"),
    ("设计说明", "设计说明图"),
)


@dataclass(frozen=True)
class EngineConfig:
    """分档运行参数。默认值是旧仓 ``_DEFAULTS`` 的出厂值（其中 ``confidence_*`` 为旧 WS13 新增，未经客户确认）。"""

    confidence_threshold: float = 0.6
    default_disposition: str = "skip"
    conf_whitelist: float = 0.85
    conf_bare: float = 0.65
    conf_archive: float = 0.95
    conf_blacklist: float = 0.9
    conf_blacklist_doubt: float = 0.6
    conf_parent_inherit: float = 0.7
    conf_ancestor_step: float = 0.05
    conf_ancestor_floor: float = 0.6
    blacklist_doubt_words: tuple[str, ...] = ("费", "价", "款", "签证", "合同", "结算", "预算", "清单")
    section_extract_keywords: tuple[str, ...] = ("施工组织设计", "施工方案")
    section_extract_parent_keywords: tuple[str, ...] = ("控制价", "投标", "招标")
    archive_keyword_ext_skip: frozenset[str] = frozenset({"xls", "xlsx", "xlsm", "csv", "doc", "docx"})
    cad_drawing_exts: frozenset[str] = frozenset({"dwg", "dwf"})
    cad_drawing_default_category: str = "设计图纸"
    design_doc_exts: frozenset[str] = frozenset({"pdf", "doc", "docx"})
    design_indicator_keywords: tuple[str, ...] = (
        "设计说明", "施工图", "详图", "大样", "系统图", "平面图", "立面图", "剖面图", "节点图", "说明书",
        "设计图", "图纸",
    )


@dataclass(frozen=True)
class Rule:
    """一行分类规则。"""

    match_type: str          # contains / all_of / regex / ext
    pattern: str
    priority: int
    doc_category: Optional[str] = None
    cost_stage: Optional[str] = None
    needs_export: bool = False
    note: str = ""
    tier: str = "specific"                 # "bare" = 裸词
    exclude_any: tuple[str, ...] = ()      # 文件名含其一 → 不命中
    require_any: tuple[str, ...] = ()      # 文件名或任一祖先含其一才命中
    veto_ancestors: tuple[str, ...] = ()   # 任一祖先含其一 → 不命中
    stage_policy: Optional[str] = None     # "context" = 阶段按语境


@dataclass
class ClassifyInput:
    """分档输入。``ancestors`` 由近及远，已剔项目目录与 资料/图纸/成果 容器根。"""

    file_id: str
    file_name: str
    file_ext: str
    parent_dir: Optional[str] = None
    has_text_layer: Optional[bool] = None  # PDF 文字层探针；None = 未探测
    ancestors: Optional[list[str]] = None

    def __post_init__(self) -> None:
        if self.ancestors is None:
            self.ancestors = [self.parent_dir] if self.parent_dir else []
        else:
            self.ancestors = [a for a in self.ancestors if a and str(a).strip()]
            if self.parent_dir is None and self.ancestors:
                self.parent_dir = self.ancestors[0]


@dataclass
class ClassifyOutcome:
    """分档结果。"""

    file_id: str
    disposition: str
    doc_category: Optional[str]
    cost_stage: Optional[str]
    confidence: float
    reason: str
    needs_manual: bool
    evidence: Optional[str] = None   # 见 EV_*；无类目时为 None


RuleBuckets = dict[str, list[Rule]]


def norm_ext(ext: str) -> str:
    """规范扩展名：小写、去点。

    :param ext: 扩展名。
    :returns: 规范化结果。
    """
    return (ext or "").lower().lstrip(".")


def system_artifact_kind(file_name: Optional[str]) -> Optional[str]:
    """系统生成物种类：``system_index`` / ``ocr_sidecar``；不是系统生成物返回 None。

    :param file_name: 文件名。
    :returns: 种类或 None。
    """
    lower = (file_name or "").strip().lower()
    if lower == "index.md":
        return "system_index"
    if is_sidecar_name(lower):
        return "ocr_sidecar"
    return None


def _words(row: dict, key: str) -> tuple[str, ...]:
    return tuple(str(w) for w in (row.get(key) or []) if str(w).strip())


def load_rules(path: Path) -> RuleBuckets:
    """加载 classify_rules.yaml，按 kind 分桶并按 priority 排序。

    :param path: 规则文件路径。
    :returns: ``{kind: [Rule]}``。
    :raises ZtError: 文件缺失、不是合法 YAML、或规则行含未知 tier / stage_policy（``rules_invalid``）。
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ZtError("rules_not_found", f"找不到分类规则文件：{path}",
                      hint="skill 的 data/classify_rules.yaml 缺失，重新安装 zt-project") from None
    except yaml.YAMLError as e:
        raise ZtError("rules_invalid", f"分类规则文件不是合法 YAML：{path}（{e}）") from e
    buckets: RuleBuckets = {
        "noise": [], "blacklist": [], "upgrade_whitelist": [],
        "archive_ext": [], "whitelist": [], "archive_keyword": [],
        "ancestor_context": [],
    }
    for row in (raw or {}).get("rules", []):
        kind = row["kind"]
        tier = str(row.get("tier") or "specific")
        if tier not in ("specific", "bare"):
            raise ZtError("rules_invalid", f"classify_rules.yaml: 未知 tier={tier!r}（{row.get('pattern')}）")
        policy = row.get("stage_policy")
        if policy not in (None, "context"):
            raise ZtError("rules_invalid",
                          f"classify_rules.yaml: 未知 stage_policy={policy!r}（{row.get('pattern')}）")
        buckets.setdefault(kind, []).append(Rule(
            match_type=row["match"],
            pattern=str(row["pattern"]),
            priority=int(row.get("priority", 999)),
            doc_category=row.get("doc_category"),
            cost_stage=row.get("cost_stage"),
            needs_export=bool(row.get("needs_export", False)),
            note=row.get("note", ""),
            tier=tier,
            exclude_any=_words(row, "exclude_any"),
            require_any=_words(row, "require_any"),
            veto_ancestors=_words(row, "veto_ancestors"),
            stage_policy=policy,
        ))
    for rows in buckets.values():
        rows.sort(key=lambda r: r.priority)
    return buckets


def rule_categories(rules: RuleBuckets) -> set[str]:
    """规则文件里出现过的全部类目。

    :param rules: :func:`load_rules` 的结果。
    :returns: 类目集合。
    """
    return {r.doc_category for bucket in rules.values() for r in bucket if r.doc_category}


def classifier_vocabulary(rules: RuleBuckets, config: Optional[EngineConfig] = None) -> list[str]:
    """分类器能产出的全部类目：规则文件里的类目，加 CAD / 设计文档细分子类与 CAD 默认类目。

    :param rules: :func:`load_rules` 的结果。
    :param config: 运行参数。
    :returns: 排序后的类目列表。
    """
    cfg = config or EngineConfig()
    cad = {cat for _kw, cat in CAD_SUBTYPE_DEFAULT} | {cfg.cad_drawing_default_category}
    return sorted(rule_categories(rules) | cad)


def rule_hit(rule: Rule, text: str, ancestors: tuple[str, ...] | list[str] = ()) -> bool:
    """规则是否命中。语境字段先判：裸词只做 ``pattern in text`` 时，「招标代理合同」会被「招标」判成招标文件。

    :param rule: 规则行。
    :param text: 文件名（或目录段）。
    :param ancestors: 祖先目录链。
    :returns: 命中为 True。
    """
    if rule.exclude_any and any(w in text for w in rule.exclude_any):
        return False
    if rule.veto_ancestors and any(w in a for a in ancestors for w in rule.veto_ancestors):
        return False
    if rule.require_any and not any(w in seg for seg in (text, *ancestors) for w in rule.require_any):
        return False
    if rule.match_type == "contains":
        return rule.pattern in text
    if rule.match_type == "all_of":
        return all(w and w in text for w in rule.pattern.split("+"))
    if rule.match_type == "regex":
        return re.search(rule.pattern, text) is not None
    return False


def _first_hit(rules: list[Rule], text: str, ancestors: tuple[str, ...] | list[str] = ()) -> Optional[Rule]:
    for r in rules:
        if rule_hit(r, text, ancestors):
            return r
    return None


class ClassifyEngine:
    """按文件名与祖先目录给文件定类目和阶段。

    :param rules: :func:`load_rules` 的结果。
    :param config: 运行参数，缺省为 :class:`EngineConfig` 的出厂值。
    """

    def __init__(self, rules: RuleBuckets, config: Optional[EngineConfig] = None) -> None:
        self.rules = rules
        self.cfg = config or EngineConfig()
        white = rules["whitelist"]
        self._compound = [r for r in white if r.match_type == "all_of"]
        self._specific = [r for r in white if r.match_type != "all_of" and r.tier != "bare"]
        self._bare = [r for r in white if r.match_type != "all_of" and r.tier == "bare"]

    # —— 规则层辅助 ——

    def _archive_keyword_hit(self, name: str, *, skip_categoryless: bool) -> Optional[Rule]:
        """按优先级扫 archive_keyword。

        同名同时命中「无类目」与「有类目」关键词时优先取有类目那条（否则「建筑工程施工许可证.pdf」
        被「建筑」截胡成空类目，齐套核查匹配不上）；``skip_categoryless`` 表示表格 / 文档扩展名跳过无类目裸词。
        返回无类目规则时，调用方只记下它，不据此结束判定。
        """
        fallback: Optional[Rule] = None
        for r in self.rules["archive_keyword"]:
            if r.doc_category is None:
                if not skip_categoryless and fallback is None and rule_hit(r, name):
                    fallback = r
                continue
            if rule_hit(r, name):
                return r
        return fallback

    def _cad_subtype(self, name: str) -> str:
        for kw, cat in CAD_SUBTYPE_DEFAULT:
            if kw in name:
                return cat
        return self.cfg.cad_drawing_default_category

    def _design_doc_subtype(self, name: str, ext: str) -> Optional[tuple[str, str]]:
        if ext not in self.cfg.design_doc_exts:
            return None
        for kw, cat in CAD_SUBTYPE_DEFAULT:
            if name == kw:
                return cat, "裸名精确等于专业词"
        if not any(ind in name for ind in self.cfg.design_indicator_keywords):
            return None
        for kw, cat in CAD_SUBTYPE_DEFAULT:
            if kw in name:
                return cat, "含专业+设计词"
        return None

    def _inherit_from_ancestors(self, ancestors) -> Optional[tuple[Rule, int, str]]:
        """由近及远逐段匹配 ancestor_context，第一个命中就用；返回 (规则, 深度, 目录段)，深度 0 = 直属父目录。"""
        for depth, seg in enumerate(ancestors or ()):
            r = _first_hit(self.rules.get("ancestor_context", []), seg)
            if r is not None and r.doc_category:
                return r, depth, seg
        return None

    def _ancestor_conf(self, depth: int) -> float:
        c = self.cfg
        return round(max(c.conf_ancestor_floor, c.conf_parent_inherit - c.conf_ancestor_step * depth), 4)

    def _ancestor_stage(self, ancestors) -> tuple[Optional[str], Optional[str]]:
        """最近一个带阶段的 ancestor_context 命中 → (阶段, 目录段)；没有 → (None, None)。"""
        for seg in ancestors or ():
            for r in self.rules.get("ancestor_context", []):
                if r.cost_stage and rule_hit(r, seg):
                    return r.cost_stage, seg
        return None, None

    def _resolve_stage(self, rule: Rule, name: str, ancestors) -> tuple[Optional[str], str]:
        """规则命中后的阶段，返回 (阶段, 追加进 reason 的说明)。

        顺序：① 文件名期次 → 施工过程（只对语境行与 ``_PERIOD_CATEGORIES``）；② 语境行取最近带阶段的祖先，
        找不到就是 None；③ 规则行常量；④ 常量为空时走祖先链。
        """
        context = rule.stage_policy == "context"
        if (context or rule.doc_category in _PERIOD_CATEGORIES) and _PERIOD_RE.search(name):
            return _STAGE_PERIOD, f";阶段按文件名期次→{_STAGE_PERIOD}"
        if context:
            st, seg = self._ancestor_stage(ancestors)
            if st:
                return st, f";阶段按目录语境「{seg}」→{st}"
            return None, ";阶段按语境判定,祖先目录无阶段信号→未定"
        if rule.cost_stage:
            return rule.cost_stage, ""
        st, seg = self._ancestor_stage(ancestors)
        if st:
            return st, f";阶段继承祖先目录「{seg}」"
        return None, ""

    def _whitelist_outcome(self, f: ClassifyInput, rule: Rule, via: str) -> ClassifyOutcome:
        name = (f.file_name or "").strip()
        bare = rule.tier == "bare"
        cost_stage, stage_note = self._resolve_stage(rule, name, f.ancestors)
        confidence = self.cfg.conf_bare if bare else self.cfg.conf_whitelist
        evidence = EV_BARE if bare else EV_RULE
        label = "裸词" if bare else "白名单"
        if norm_ext(f.file_ext) == "pdf" and f.has_text_layer is False:
            return ClassifyOutcome(
                f.file_id, "pending_ocr", rule.doc_category, cost_stage, confidence,
                f"命中{label}「{rule.pattern}」但 PDF 无文字层(扫描件)", True, evidence,
            )
        tail = "(裸词不看上下文,待人工复核)" if bare else ""
        return ClassifyOutcome(
            f.file_id, "rag", rule.doc_category, cost_stage, confidence,
            f"{via}命中{label}「{rule.pattern}」→ {rule.doc_category}{stage_note}{tail}",
            bare or confidence < self.cfg.confidence_threshold or rule.doc_category is None, evidence,
        )

    def _inherit_outcome(self, f: ClassifyInput, disposition: str, prefix: str) -> Optional[ClassifyOutcome]:
        hit = self._inherit_from_ancestors(f.ancestors)
        if hit is None:
            return None
        r, depth, seg = hit
        return ClassifyOutcome(
            f.file_id, disposition, r.doc_category, r.cost_stage, self._ancestor_conf(depth),
            f"{prefix}继承第{depth + 1}层祖先目录「{seg}」语境 → {r.doc_category}"
            f"(命中「{r.pattern}」;推断待人工复核)",
            True, EV_INHERIT,
        )

    # —— 判定主流程 ——

    def classify_one(self, f: ClassifyInput) -> ClassifyOutcome:
        """给一个文件定类目。

        空类目不带置信度：除「确定跳过」与系统生成物外，类目为空就是没判出，置信度 0、``needs_manual=True``。

        :param f: 分档输入。
        :returns: 分档结果。
        """
        o = self._classify_one(f)
        if o.doc_category is None and o.disposition not in ("skip", DISPOSITION_SYSTEM):
            o.confidence = 0.0
            o.needs_manual = True
            o.evidence = None
        return o

    def _classify_one(self, f: ClassifyInput) -> ClassifyOutcome:
        c = self.cfg
        name = (f.file_name or "").strip()
        ext = norm_ext(f.file_ext)
        anc = tuple(f.ancestors or ())

        # ① 系统噪音
        if _first_hit(self.rules["noise"], name):
            return ClassifyOutcome(
                f.file_id, c.default_disposition, None, None, 0.0,
                "系统噪音文件名(未命名/标段号),无语义", True,
            )

        # ② 系统生成物：不是资料，不继承目录语境
        kind = system_artifact_kind(name)
        if kind is not None:
            what = "目录索引 INDEX.md" if kind == "system_index" else "OCR 旁车 .ocr.txt"
            return ClassifyOutcome(
                f.file_id, DISPOSITION_SYSTEM, None, None, 0.0,
                f"系统生成物({what}),不是项目资料,不参与盘点", False, EV_SYSTEM,
            )

        # ③ 黑名单 + 升档 / 疑词
        black = _first_hit(self.rules["blacklist"], name)
        if black:
            upgrade = _first_hit(self.rules["upgrade_whitelist"], name)
            if upgrade:
                via = f"黑名单「{black.pattern}」被升档词「{upgrade.pattern}」反超,"
                white = (_first_hit(self._compound, name, anc) or _first_hit(self._specific, name, anc)
                         or _first_hit(self._bare, name, anc))
                if white:
                    return self._whitelist_outcome(f, white, via)
                return ClassifyOutcome(
                    f.file_id, "rag", None, None, 0.0,
                    f"{via}但无白名单类目,待人工归档", True,
                )
            if any(k in name for k in c.section_extract_keywords) and f.parent_dir and any(
                p in f.parent_dir for p in c.section_extract_parent_keywords
            ):
                return ClassifyOutcome(
                    f.file_id, "archive", None, None, c.conf_archive,
                    f"「{black.pattern}」整体归档,needs_section_extract:措施费(父目录「{f.parent_dir}」为计价语境)", True,
                )
            doubt = next((w for w in c.blacklist_doubt_words if w in name), None)
            if doubt:
                return ClassifyOutcome(
                    f.file_id, "skip", None, None, c.conf_blacklist_doubt,
                    f"命中跳过黑名单「{black.pattern}」,但名字含造价疑词「{doubt}」且无升档词,跳过待人工复核", True,
                )
            return ClassifyOutcome(
                f.file_id, "skip", None, None, c.conf_blacklist,
                f"命中跳过黑名单「{black.pattern}」(非造价内容)", False,
            )

        # ④ 扩展名
        for r in self.rules["archive_ext"]:
            if r.match_type == "ext" and r.pattern.lower() == ext:
                if r.needs_export:
                    base = f"二进制计价文件 .{ext},需导出计价表后才能读内容"
                    if r.doc_category:
                        return ClassifyOutcome(
                            f.file_id, "pending_export", r.doc_category, None, c.conf_archive,
                            base, True, EV_RULE,
                        )
                    # 计价文件名本身没有可信的文档类型词(「(10月进度款)XX.清单审计」里的「清单」是软件后缀),
                    # 类目只能按目录推断。
                    inherited = self._inherit_outcome(f, "pending_export", f"{base};类目")
                    if inherited is not None:
                        return inherited
                    return ClassifyOutcome(
                        f.file_id, "pending_export", None, None, 0.0,
                        f"{base};祖先目录无语境,类目待人工归档", True,
                    )
                cat, reason = r.doc_category, f"图形/影像扩展名 .{ext},仅归档"
                if cat is None and ext in c.cad_drawing_exts:
                    cat = self._cad_subtype(name)
                    reason = f"CAD 图纸 .{ext} → {cat}(按文件名专业细分)"
                elif cat is None:
                    # jpg/jpeg/png 在 YAML 里 doc_category=None 又非 CAD:补查同一优先级表(只认带类目的条目)
                    akw = self._archive_keyword_hit(name, skip_categoryless=True)
                    if akw is not None:
                        cat = akw.doc_category
                        reason = f"图形/影像扩展名 .{ext},按归档关键词「{akw.pattern}」→ {cat}"
                return ClassifyOutcome(f.file_id, "archive", cat, None, c.conf_archive, reason, False,
                                       EV_RULE if cat else None)

        # ⑤ 复合 → ⑥ 特指（先于归档词：「施工图预算」不再被「施工图」截走）
        compound = _first_hit(self._compound, name, anc)
        if compound:
            return self._whitelist_outcome(f, compound, "复合")
        specific = _first_hit(self._specific, name, anc)
        if specific:
            return self._whitelist_outcome(f, specific, "")

        # ⑦ 带类目的归档词；无类目专业词只记下，不结束判定（留到 ⑫）
        akw = self._archive_keyword_hit(name, skip_categoryless=ext in c.archive_keyword_ext_skip)
        categoryless: Optional[Rule] = None
        if akw is not None:
            if akw.doc_category:
                return ClassifyOutcome(
                    f.file_id, "archive", akw.doc_category, None, c.conf_archive,
                    f"命中归档关键词「{akw.pattern}」(图形/影像/归档类)", False, EV_RULE,
                )
            categoryless = akw

        # ⑧ 设计文档 / CAD 细分
        design_hit = self._design_doc_subtype(name, ext)
        if design_hit:
            design_cat, via = design_hit
            return ClassifyOutcome(
                f.file_id, "archive", design_cat, None, c.conf_archive,
                f"设计文档 .{ext} {via} → {design_cat}", False, EV_RULE,
            )

        # ⑨ 直属父目录 = 专业词
        if f.parent_dir and ext in (c.design_doc_exts | c.cad_drawing_exts):
            pstem = re.sub(r"^\d+[.、：:\s]*", "", f.parent_dir).strip()
            for kw, cat in CAD_SUBTYPE_DEFAULT:
                if pstem == kw:
                    if not _first_hit(self._bare, name, anc):
                        return ClassifyOutcome(
                            f.file_id, "archive", cat, None, c.conf_archive,
                            f"父目录「{f.parent_dir}」=专业词 → {cat}(目录信号)", False, EV_PARENT,
                        )
                    break

        # ⑩ 祖先目录继承（先于裸词：「22 进度款…」下的「清单」不是招标清单）
        inherited = self._inherit_outcome(f, "rag", "自身无特指造价关键词,")
        if inherited is not None:
            return inherited

        # ⑪ 裸词
        bare = _first_hit(self._bare, name, anc)
        if bare:
            return self._whitelist_outcome(f, bare, "")

        # ⑫ 只命中无类目专业词
        if categoryless is not None:
            return ClassifyOutcome(
                f.file_id, "archive", None, None, 0.0,
                f"仅命中专业词「{categoryless.pattern}」,无文档类型词,不归类待人工归档", True,
            )

        # ⑬ 默认档
        return ClassifyOutcome(f.file_id, c.default_disposition, None, None, 0.0, "不可识别,待人工归档", True)

    def classify(self, files: list[ClassifyInput]) -> list[ClassifyOutcome]:
        """批量分档。

        :param files: 分档输入。
        :returns: 与输入同序的结果。
        """
        return [self.classify_one(f) for f in files]
