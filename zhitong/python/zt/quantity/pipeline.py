# 来源：engine-service/app/engine/quantity_list.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""按设计说明生成 GB50854 清单框架 —— 确定性部分（prepare / finalize）。

旧流水线（``quantity_list.run``）一次调用里做完读入、切片、LLM 分类、闸、聚合、特征摘录、渲染。
zt 里模型就是 agent 本身，中间那步拆出去（spec §4.1）：

``prepare``（:func:`prepare`）
  ① extract   内容相同（sha256）的文件只读一份（WS29-p）；xlsx/docx 另走结构化读取
  ② scope     逐文件判专业（QTY-07）；全部非房建 → out_of_scope
  ③ segment   practice / heading / exclusion / other，原文与位置由代码产生（QTY-03/13）
  ④ gate-in   practice 片段数闸（QTY-01）；0 个 → no_practice（QTY-05）
  ④b inline   层内标记（WS29-f）：自理 / 本层为二次装修的层直接写台账、不交给 agent
  → 输出待分类片段（全局编号 s<n>）按文件装批、与本批有关的排除句（全局编号 e<n>）、``prepare_fingerprint``

agent 读 ``清单分类说明.md``（码表 + 易混淆对照）与批次，把每个片段的 ``{id, role, c, ex, why}`` 写进 answers。

``finalize``（:func:`finalize`）重跑 ①–④b（确定性，指纹必须与 prepare 一致），再：
  ⑥ gates     码表存在 → 语义一致性闸（QTY-02，只判不改码，不一致降待核，D52）→ 存疑闸 → 角色闸；标段排除（QTY-11）
  ⑦ aggregate 做法内同码合并、辅层并入、跨来源去重（QTY-09）→ 排序后分配流水号（QTY-12）
  ⑧ features  槽位重编号（QTY-14）→ 确定性槽位 + agent 逐字摘录（``f``）并校验（QTY-06）；
              未作答的槽写「待补」，未作答的任务列在 ``feature_tasks``，agent 补答后带 ``f`` 重跑 finalize
  ⑨ coverage  不变式核算：每个 practice 片段恰好一个去向（QTY-03）

xlsx 由 :mod:`zt.quantity.render` 从 finalize 结果生成。

结果状态：全部片段都有回答 = ok；有片段缺回答 = partial；一个都没回答且没有正式项 = :class:`AnswersMissing`。
语义闸不一致一律降为「待核」，不自动改码（D52）。编码只用 zj2025 并在表头声明（D53）。标段从项目名解析（D54）。
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from zt import code_registry
from zt.quantity import features as feat
from zt.quantity import prompt as qp
from zt.quantity import rules
from zt.quantity import same_content
from zt.quantity import segment as segmod
from zt.quantity.segment import EXCLUSION, OTHER, PRACTICE, Segment
from zt.textextract.extract import extract_document, extract_text

if TYPE_CHECKING:
    from collections.abc import Callable

    from zt.textextract.model import DocText

    # PDF 读取回调：(文件下标, 字节, 文件名) → DocText（文字层 + 并列旁车）。
    # zt 改动：旧版是扫描件降级回调 (下标, 字节, 名) → (文本, 来源[, 说明])，走 OCR 服务；本仓不调 OCR 服务，
    # CLI 注入 zt.textextract.extract.load_document（文字层 → 旁车 → 缺页）。
    PdfLoader = Callable[[int, bytes, str], DocText]

log = logging.getLogger("zt.quantity.pipeline")

QUANTITY_PROMPT_VERSION = qp.QUANTITY_PROMPT_VERSION
SUFFIX_WIDTH = 3  # 编码后缀位数：001 起递增

DEST_ITEM = "item"
DEST_AUX = "aux_merged"
DEST_BASE = "base"
DEST_EXCLUDED = "excluded_scope"
DEST_OUT = "out_of_scope"
DEST_PENDING = "pending_review"
DEST_UNMATCHED = "unmatched"
DEST_LLM_FAILED = "llm_failed"
DESTINATIONS = (DEST_ITEM, DEST_AUX, DEST_BASE, DEST_EXCLUDED, DEST_OUT, DEST_PENDING, DEST_UNMATCHED,
                DEST_LLM_FAILED)
DEST_CN = {
    DEST_ITEM: "正式清单项", DEST_AUX: "并入主项特征", DEST_BASE: "基层（不出项）",
    DEST_EXCLUDED: "范围排除", DEST_OUT: "专业越界", DEST_PENDING: "待核",
    DEST_UNMATCHED: "未匹配", DEST_LLM_FAILED: "模型未完成",
}

SCOPE_NOTE = "适用范围：GB/T 50854 房屋建筑与装饰工程（分部 0101–0118）。安装、市政、道路桥梁等专业不在本能力范围内。"


# ============================================================ 异常（CLI 按类型映射成信封或错误 JSON）

class ParseFailed(RuntimeError):
    """所有输入文件都抽不出可用文本（格式不支持/损坏/纯图片扫描件且无旁车）。"""


class QuantityRejected(RuntimeError):
    """输入前置条件不满足。reason_code ∈ out_of_scope / no_practice / too_many_segments / no_items。

    都带 coverage —— 失败态也要让人看得到「为什么是空的、东西去哪了」（铁律 8）。认出了做法层、只是没有任何正式项、
    但有可展示的待核行时照常出结果（R4F-d fix15 决定 4）；没有可展示的待核 / 未匹配行（全基层 / 辅层、全部层内自理）
    仍按 no_items 拒绝（fix17 裁定 8）。
    """

    def __init__(self, reason_code: str, detail: str, *, coverage: Optional[dict] = None,
                 unmatched: Optional[list] = None, warnings: Optional[list[str]] = None,
                 warning_items: Optional[list[dict]] = None) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail
        self.coverage = coverage
        self.unmatched = unmatched
        self.warnings = warnings
        self.warning_items = warning_items or []


class InputTooLarge(QuantityRejected):
    """practice 片段数超过上限（``max_segments``），在交给 agent 之前拦下。"""


class AnswersMissing(RuntimeError):
    """待分类片段一个回答都没有，且没有形成正式项（旧版：所有批次 LLM 失败 → 502）。"""

    def __init__(self, detail: str, *, coverage: Optional[dict] = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.coverage = coverage


class PrepareMismatch(RuntimeError):
    """finalize 重算出的片段指纹与 prepare 的不一致（输入文件、项目名或参数变了）。"""


class CoverageInvariantError(RuntimeError):
    """片段去向核算不成立（有片段没去向或有两个去向）。绝不静默（铁律 8）。"""


# ============================================================ 配置

@dataclass(frozen=True)
class QuantityConfig:
    """可调参数（CLI 参数或请求字段覆盖）。

    zt 改动：去掉 LLM 的 max_tokens / 并发 / 总时限 / 二分深度；装批参数只决定 agent 一次读多少片段。
    """

    batch_max_segments: int = 40
    batch_max_chars: int = 6000
    max_segments: int = 800

    @classmethod
    def from_request(cls, req: Optional[dict]) -> "QuantityConfig":
        """从请求字段构造；缺省用默认值，非正数视为缺省。

        :param req: 请求字典。
        :returns: 配置。
        """
        req = req or {}

        def num(name: str, default: int) -> int:
            v = req.get(name)
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                return default
            return v

        return cls(batch_max_segments=num("batch_max_segments", cls.batch_max_segments),
                   batch_max_chars=num("batch_max_chars", cls.batch_max_chars),
                   max_segments=num("max_segments", cls.max_segments))


# ============================================================ ① 读取输入文件

def _extract_one(idx: int, content: bytes, file_name: str, file_ext: str,
                 pdf_loader: "PdfLoader | None") -> Optional[dict]:
    """一份文件 → {file_index, file_name, ext, content, text, text_source, notes}；抽不出正文 → None。"""
    notes: list[tuple[str, str]] = []
    source = "text_layer"  # 非 PDF 的原生抽取也归入 text_layer
    if file_ext == "pdf":
        doc = pdf_loader(idx, content, file_name) if pdf_loader is not None else \
            extract_document(content, "pdf", file_name=file_name)
        text = doc.text
        if text.strip():
            if doc.pages_missing:
                notes.append(("quantity_pages_missing",
                              f"「{file_name}」第 {'、'.join(str(p) for p in doc.pages_missing)} 页未取得正文"
                              "（扫描页且无旁车），这些页上的做法不在本次清单里"))
            # zt 改动：来源取页级明细（文字层 / 旁车 / 混合），旁车参与即视为扫描件来源
            detail = doc.text_source_detail
            source = "ocr_sidecar" if detail in ("ocr_sidecar", "mixed") else "text_layer"
    else:
        text = extract_text(content, file_ext)
    if not text.strip():
        return None
    return {"file_index": idx, "file_name": file_name, "ext": file_ext, "content": content,
            "text": text, "text_source": source, "notes": notes}


def _no_text(file_name: str) -> str:
    return f"「{file_name}」未能抽取出可用文本，已跳过"


def read_inputs(
    files: list[tuple[bytes, str, str]],
    pdf_loader: "PdfLoader | None" = None,
    names: Optional[list[str]] = None,
) -> tuple[list[dict], list[str], list[dict]]:
    """① 读入，同内容的文件只读一份（WS29-p）→ (texts, 跳过告警, 被合并的副本)。

    按原件 sha256 分组，组内先出现的那份读得出正文就只读它，读不出才试下一份；一份都读不出时每份各报一句
    「抽不出正文」。names 是告警里点名用的（有 display_path 就是路径）。

    :param files: ``[(字节, 文件名, 扩展名)]``。
    :param pdf_loader: PDF 读取回调。
    :param names: 告警用名字。
    :returns: ``(texts, skipped, dups)``；texts 按 file_index 升序。
    """
    shown = same_content.labels(names or [f[1] for f in files])
    texts: list[dict] = []
    skipped: list[str] = []
    dups: list[dict] = []
    for group in same_content.groups([same_content.content_key(c) for c, _n, _e in files]):
        got = None
        for i in group:
            got = _extract_one(i, *files[i], pdf_loader)
            if got is not None:
                break
        if got is None:
            skipped.extend(_no_text(files[i][1]) for i in group)
            continue
        texts.append(got)
        kept = got["file_index"]
        dups.extend({"file_index": i, "file_name": files[i][1], "kept_index": kept, "label": shown[i],
                     "kept_label": shown[kept]} for i in group if i != kept)
    texts.sort(key=lambda t: t["file_index"])
    return texts, skipped, dups


# ============================================================ 装批（agent 一次读一批）

def batch_exclusions(batch: list[Segment], exclusions: list[rules.Exclusion]) -> list[rules.Exclusion]:
    """与本批有关的排除句：对象词出现在本批某个片段的正文或上下文里（与 decide 判排除用同一个匹配）。

    :param batch: 本批片段。
    :param exclusions: 全部排除句。
    :returns: 有关的排除句。
    """
    hays = [f"{s.text} {s.context()}" for s in batch]
    return [e for e in exclusions if any(rules.match_exclusion([e], h) is e for h in hays)]


def make_batches(segs: list[Segment], cfg: QuantityConfig) -> list[list[Segment]]:
    """同一文件内按片段顺序装批：每批 ≤ batch_max_segments 个、正文合计 ≤ batch_max_chars 字，不跨文件。

    :param segs: 待分类片段。
    :param cfg: 配置。
    :returns: 批次。
    """
    batches: list[list[Segment]] = []
    cur: list[Segment] = []
    chars = 0
    for s in segs:
        if cur and (s.file_index != cur[-1].file_index or len(cur) >= cfg.batch_max_segments
                    or chars + len(s.text) > cfg.batch_max_chars):
            batches.append(cur)
            cur, chars = [], 0
        cur.append(s)
        chars += len(s.text)
    if cur:
        batches.append(cur)
    return batches


# ============================================================ agent 回答

@dataclass
class Answer:
    role: str
    code: str
    ex: str
    why: str


@dataclass
class Failure:
    reason_code: str
    reason: str


@dataclass
class _Stats:
    """回答里的异常情况（旧 LLMStats 去掉 token 计数）。"""

    unknown_ids: list[str] = field(default_factory=list)
    unknown_ex: list[str] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    unknown_feature_keys: list[str] = field(default_factory=list)


_ROLES = {"main", "aux", "base"}


def allowed_exclusions(to_classify: list[Segment], exclusions: list[rules.Exclusion],
                       cfg: QuantityConfig) -> dict[str, set[str]]:
    """每个待分类片段可以引用的排除句编号：它所在批次列出的那几条（与 prepare 的批次一致）。

    :param to_classify: 待分类片段。
    :param exclusions: 全局排除句。
    :param cfg: 装批参数。
    :returns: 片段 id → 排除句编号集合。
    """
    out: dict[str, set[str]] = {}
    for b in make_batches(to_classify, cfg):
        ids = {e.id for e in batch_exclusions(b, exclusions)}
        for s in b:
            out[s.id] = ids
    return out


def parse_answers(answers: Any, to_classify: list[Segment], allowed_ex: dict[str, set[str]],
                  stats: _Stats) -> dict[str, Any]:
    """answers（``{"r": [...]}`` 或数组）→ {片段 id: Answer | Failure}。

    zt 改动：旧 ``_classify_batch`` 在这里调模型、拆批、补问；现在回答由 agent 一次给全。id 是全局片段编号；
    不在待分类片段里的 id 记入 unknown_ids 丢弃；同一 id 答了多次只取第一条（记 duplicate_ids）；role 不合法
    按漏答；ex 必须是该片段所在批次列出的排除句编号，否则记 unknown_ex 并置空（别的批次的编号即使全局存在
    也不认）。缺回答的片段 → Failure("llm_missing")。

    :param answers: agent 的回答。
    :param to_classify: 待分类片段。
    :param allowed_ex: :func:`allowed_exclusions` 的结果。
    :param stats: 收集异常情况。
    :returns: 每个待分类片段一项。
    """
    rows = answers.get("r") if isinstance(answers, dict) else answers
    if not isinstance(rows, list):
        rows = []
    by_id = {s.id: s for s in to_classify}
    got: dict[str, Any] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        sid = r.get("id")
        if not isinstance(sid, str):
            continue
        sid = sid.strip()
        if sid not in by_id:
            stats.unknown_ids.append(sid)
            continue
        role = str(r.get("role") or "").strip().lower()
        if role not in _ROLES:
            continue          # 形状不对按漏答处理
        if sid in got:
            stats.duplicate_ids.append(sid)
            continue
        code = str(r.get("c") or "").strip().upper()
        ex = str(r.get("ex") or "").strip()
        if ex and ex not in allowed_ex.get(sid, set()):
            stats.unknown_ex.append(ex)
            ex = ""
        got[sid] = Answer(role, code, ex, str(r.get("why") or "")[:40])
    for s in to_classify:
        if s.id not in got:
            got[s.id] = Failure("llm_missing", "agent 没有回答这个片段（answers 里缺这个 id）")
    return got


# ============================================================ ⑥ 去向判定（闸）

@dataclass
class LedgerRow:
    seg: Segment
    dest: str
    reason_code: str = ""
    reason: str = ""
    llm_code: Optional[str] = None
    suggested: Optional[str] = None
    item_code: Optional[str] = None      # item / aux_merged 最终归属的清单编码
    exclusion_id: Optional[str] = None   # 被哪条全局排除句排掉的（e1 …），排除句清单按它数 hits


@dataclass
class _RunContext:
    version: str
    cfg: QuantityConfig
    stats: _Stats
    exclusions: list[rules.Exclusion]
    project_lot: Optional[int]
    eng_category_name: Optional[str]
    fingerprint: str


def _expected_names(v: rules.Violation, version: str) -> str:
    reg = code_registry.load_registry(version)
    names: list[str] = []
    # forbid 型规则没有 expect：建议栏按 suggest 写码表名称（WS29-k2）。两样都没有才退回 message
    for p in v.suggest or v.expect:
        for code, hit in sorted(reg.items(), key=lambda kv: qp.code_sort_key(kv[0])):
            bare = code[1:] if code[:1] == "Z" else code
            if bare.startswith(p):
                names.append(f"{code} {hit['name']}（{hit['unit']}）")
            if len(names) >= 4:
                break
    return "规则期望：" + "；".join(names) if names else v.message


def inline_row(seg: Segment) -> Optional[LedgerRow]:
    """层内标记决定去向的层（WS29-f，D-R110）：不交给 agent，直接写台账并引用原句。

    自理 → 范围排除；本层写明为二次装修 → 范围排除；「自理或（详精装修设计）」→ 待核，不替人选。
    只带精装修引用的层返回 None：照常分类，条目与台账带「做法暂定」（D-R111）。

    :param seg: 片段。
    :returns: 台账行或 None。
    """
    m = seg.inline
    if m is None or m.code == rules.FITOUT_PROVISIONAL:
        return None
    also = f"原文同时注明「{m.also}」。" if m.also else ""
    reason = (f"{rules.INLINE_CODES[m.code]}（「{m.matched}」，只管这一层）。{also}"
              f"原句（{seg.file_name} {seg.location}）：{seg.text}")
    return LedgerRow(seg, DEST_PENDING if m.code == rules.OWNER_AMBIGUOUS else DEST_EXCLUDED, m.code, reason)


def is_provisional(seg: Segment) -> bool:
    """片段是否带「做法暂定」标记（详精装修设计）。

    :param seg: 片段。
    :returns: 带标记时为 True。
    """
    return seg.inline is not None and seg.inline.code == rules.FITOUT_PROVISIONAL


def _part_related(s: Segment) -> Optional[tuple[str, str]]:
    """适用部位文字读到了范围字样 → (reason, note)，否则 None。部位不是句子，不进任何排除判断。"""
    if not s.part_full or (s.inline is not None and s.inline.where == "part"):
        return None
    words = rules.scope_related_words(s.part_full)
    scan = rules.scan_exclusions(s.part_full)
    if not words and not scan.found and not scan.rejected:
        return None
    seen = f"含「{'、'.join(words)}」字样" if words else "句式像范围排除句"
    return "not_exclusion", f"适用部位文字{seen}；部位是做法的属性、不是句子，不当作排除句，没有据此排除"


def scope_related(all_segs: list[Segment]) -> list[dict]:
    """「范围相关原文」：读到了「二次装修 / 精装修 / 自理」字样、或句式像排除句，但没有据此排除或标记的句子。

    只列原句和位置，不改任何去向（铁律 8）。

    :param all_segs: 全部片段。
    :returns: 句子列表。
    """
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for s in all_segs:
        if s.kind == PRACTICE:
            part = _part_related(s)
            key = (s.file_name, s.part_location, s.part_full)
            if part is not None and key not in seen:
                seen.add(key)
                out.append({"sentence": s.part_full, "file_name": s.file_name, "location": s.part_location,
                            "segment_id": s.id, "reason": part[0], "note": part[1]})
        if s.kind == EXCLUSION or s.inline is not None:
            continue
        scan = rules.scan_exclusions(s.text)
        words = rules.scope_related_words(s.text)
        if not words and not scan.rejected:
            continue
        key = (s.file_name, s.location, s.text)
        if key in seen:
            continue
        seen.add(key)
        if scan.too_generic:
            generic = "、".join(w for _kind, ws in scan.too_generic for w in ws)
            reason, note = "too_generic", f"句式像范围排除句，但对象只有泛指词「{generic}」，没有据此排除"
        elif scan.no_object:
            reason, note = "no_object", "句式像范围排除句，但没有可用的对象词，没有据此排除"
        else:
            reason, note = "not_exclusion", (f"含「{'、'.join(words)}」字样，但不是排除句式"
                                             "（否定、定语、引用或没有谓词），没有据此排除")
        out.append({"sentence": s.text, "file_name": s.file_name, "location": s.location,
                    "segment_id": s.id, "reason": reason, "note": note})
    return out


def _doubt_of(seg: Segment, code: str):
    """存疑闸（只降级）：本行原文 → 同一单元格 / 段落（R4F-d fix13 → fix17）。命中返回判定，否则 None。"""
    # R4F-d fix15（决定 1）：本行原文里来自另一单元格的部分换成空白再判
    text = seg.scope_text()
    host = seg.host
    if host is not None:
        # fix17：本行原文里明确指向别的层的句子不算本层作用域（决定 1）
        text = rules.doubt_own_scope(text, host.text, [(p.start, p.end, p.role) for p in host.pieces], seg.host_piece)
    doubt = rules.doubt_gate(code, text)
    if doubt is None and host is not None:
        # R4F-d fix14：同一单元格 / 段落里不属于任何层的文字、带明示指代的另一层文字，也在本行的作用域内
        doubt = rules.doubt_host(code, host.text, host.where, [(p.start, p.end, p.role) for p in host.pieces],
                                 seg.host_piece)
    return doubt


def decide(seg: Segment, ans: Any, ctx: _RunContext) -> tuple[LedgerRow, Optional[str]]:
    """单个片段过闸 → (台账行, 角色)。角色 main / aux 的片段在聚合阶段再定最终去向。

    :param seg: 片段。
    :param ans: agent 的回答（Answer）或缺答（Failure）。
    :param ctx: 运行上下文。
    :returns: ``(台账行, 角色或 None)``。
    """
    if isinstance(ans, Failure):
        return LedgerRow(seg, DEST_LLM_FAILED, ans.reason_code, ans.reason), None
    assert isinstance(ans, Answer)
    hay = f"{seg.text} {seg.context()}"
    ex = rules.match_exclusion(ctx.exclusions, hay)
    if ex is not None:
        quote = f"排除句（{ex.file_name} {ex.location}）：{ex.sentence}"
        if ex.kind == "lot":
            if ctx.project_lot is None:
                return LedgerRow(seg, DEST_PENDING, "lot_unknown",
                                 "命中标段排除句，但项目名称里解析不到本项目标段，无法判断是否属于本标段。" + quote,
                                 llm_code=ans.code or None), None
            if ex.target_lot != ctx.project_lot:
                return LedgerRow(seg, DEST_EXCLUDED, "excluded_lot",
                                 f"原文写明计入 {ex.target_lot} 标，本项目为 {ctx.project_lot} 标。" + quote,
                                 llm_code=ans.code or None, exclusion_id=ex.id), None
        else:
            return LedgerRow(seg, DEST_EXCLUDED, f"excluded_{ex.kind}", "原文写明不在本次范围。" + quote,
                             llm_code=ans.code or None, exclusion_id=ex.id), None
    if ans.ex:
        known = {e.id for e in ctx.exclusions}
        if ans.ex in known:
            return LedgerRow(seg, DEST_PENDING, "llm_exclusion_unconfirmed",
                             f"模型判为范围排除（{ans.ex}），但片段里找不到排除句的对象词，请人工确认",
                             llm_code=ans.code or None), None
        ctx.stats.unknown_ex.append(ans.ex)
    lw = rules.layer_words(seg.text)
    role = ans.role
    if lw.base and not lw.standalone:
        role = "base"
    elif lw.aux and not lw.standalone:
        role = "aux"
    elif lw.standalone and not lw.aux and role in ("aux", "base"):
        # 只命中单列词（「防水」「找平」…）却被判成辅层/基层 → 待核
        return LedgerRow(seg, DEST_PENDING, "role_conflict",
                         f"原文含「{'、'.join(lw.standalone)}」，按规范应单独列项，模型却判为"
                         f"{'辅层' if role == 'aux' else '基层'}", llm_code=ans.code or None), None
    if role == "base":
        return LedgerRow(seg, DEST_BASE, "base_layer", "结构基体/基层，不出清单项"), "base"
    if role == "aux":
        # R4F-d fix16：被否定的辅层（「网格布，本层取消」）不静默并进主项特征，与主层同一道存疑闸
        doubt = _doubt_of(seg, ans.code or "")
        if doubt is not None:
            aux_code = ans.code or ""
            hit = code_registry.lookup(aux_code, ctx.version) if aux_code else None
            tail = "；本层按辅层应并入主项特征，因作用域内有否定 / 替代 / 取消表述改列待核，没有并入"
            if hit is not None:
                name = f"{aux_code} {hit['name']}（{hit['unit']}）"
                return LedgerRow(seg, DEST_PENDING, "semantic_mismatch", f"模型给出 {name}。{doubt.describe()}{tail}",
                                 llm_code=aux_code, suggested=f"建议编码：{name}；待人工确认是否采用"), None
            return LedgerRow(seg, DEST_PENDING, "semantic_mismatch", f"{doubt.describe()}{tail}",
                             llm_code=aux_code or None, suggested="待人工确认是否采用（辅层，确认后并入主项特征）"), None
        return LedgerRow(seg, DEST_AUX, "aux_layer", "并入同一做法主项的特征描述"), "aux"
    code = ans.code
    if not code:
        return LedgerRow(seg, DEST_UNMATCHED, "llm_no_code", "模型没有给出码表里的编码（如实标注，不强行归类）"), None
    hit = code_registry.lookup(code, ctx.version)
    if hit is None:
        return LedgerRow(seg, DEST_UNMATCHED, "code_not_in_registry",
                         f"编码「{code}」不在受控码表（{ctx.version}）中", llm_code=code), None
    viol = rules.check_consistency(code, seg.text, seg.context(), category=seg.category)
    if viol:
        v = viol[0]
        return LedgerRow(seg, DEST_PENDING, "semantic_mismatch",
                         f"模型给出 {code} {hit['name']}（{hit['unit']}），与原文不一致：{v.message}",
                         llm_code=code, suggested=_expected_names(v, ctx.version)), None
    doubt = _doubt_of(seg, code)
    if doubt is not None:
        # R4F-d fix13：作用域内有否定 / 替代 / 取消 / 无此项符号 → 降为待核。只降级不升级（铁律 3）
        name = f"{code} {hit['name']}（{hit['unit']}）"
        return LedgerRow(seg, DEST_PENDING, "semantic_mismatch", f"模型给出 {name}。{doubt.describe()}",
                         llm_code=code, suggested=f"建议编码：{name}；待人工确认是否采用"), None
    return LedgerRow(seg, DEST_ITEM, "", "", llm_code=code), "main"


# ============================================================ ⑦ 聚合、去重、排序

@dataclass
class _Item:
    base_code: str
    main: list[Segment] = field(default_factory=list)
    aux: list[Segment] = field(default_factory=list)
    first_order: int = 0
    practices: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    merged_from: int = 1
    code: str = ""
    notes: list[str] = field(default_factory=list)

    def signature(self) -> str:
        return "|".join(rules.spec_signature(s.text) for s in self.main)

    def absorb(self, other: "_Item") -> None:
        self.main.extend(other.main)
        self.aux.extend(other.aux)
        for dst, src in ((self.practices, other.practices), (self.parts, other.parts),
                         (self.categories, other.categories)):
            for x in src:
                if x and x not in dst:
                    dst.append(x)
        self.merged_from += other.merged_from
        self.first_order = min(self.first_order, other.first_order)


def aggregate(ledger: dict[str, LedgerRow], roles: dict[str, str], ordered: list[Segment]) -> list[_Item]:
    """做法内同码合并 → 辅层并入主项（没有主项降待核）→ 跨来源同码同规格去重 → 排序 → 分配流水号。

    :param ledger: 台账（原地更新 item_code 与 aux_without_main）。
    :param roles: 片段 id → main / aux。
    :param ordered: 待分类片段（原文顺序）。
    :returns: 清单项。
    """
    by_practice: dict[str, list[Segment]] = {}
    for s in ordered:
        if roles.get(s.id) in ("main", "aux"):
            by_practice.setdefault(s.practice_key or f"solo:{s.id}", []).append(s)
    items: list[_Item] = []
    for _pk, segs in by_practice.items():
        mains: dict[str, _Item] = {}
        seq: list[tuple[Segment, _Item]] = []
        for s in segs:
            if roles[s.id] != "main":
                continue
            code = ledger[s.id].llm_code or ""
            it = mains.get(code)
            if it is None:
                it = _Item(base_code=code, first_order=s.order)
                for dst, v in ((it.practices, s.practice), (it.parts, s.part), (it.categories, s.category)):
                    if v:
                        dst.append(v)
                mains[code] = it
                items.append(it)
            it.main.append(s)
            seq.append((s, it))
        for s in segs:
            if roles[s.id] != "aux":
                continue
            before = [it for m, it in seq if m.order < s.order]
            after = [it for m, it in seq if m.order > s.order]
            host = before[-1] if before else (after[0] if after else None)
            if host is None:
                ledger[s.id] = LedgerRow(s, DEST_PENDING, "aux_without_main",
                                         "辅层所在做法没有可以并入的主项，请人工确认")
                continue
            host.aux.append(s)
    # 跨来源去重：同码且规格签名相同的合成一项（M 列列出各处来源）
    deduped: list[_Item] = []
    seen: dict[tuple[str, str], _Item] = {}
    for it in items:
        key = (it.base_code, it.signature())
        prev = seen.get(key)
        if prev is not None:
            prev.absorb(it)
            continue
        seen[key] = it
        deduped.append(it)
    # 排序（QTY-12）：分部码、去掉 Z 的 9 位码、是否带 Z、首次出现序号；排序之后才分配流水号
    deduped.sort(key=lambda it: (*qp.code_sort_key(it.base_code), it.first_order))
    counter: dict[str, int] = {}
    for it in deduped:
        n = counter.get(it.base_code, 0) + 1
        counter[it.base_code] = n
        it.code = f"{it.base_code}{n:0{SUFFIX_WIDTH}d}"
        for s in it.main + it.aux:
            ledger[s.id].item_code = it.code
    return deduped


# ============================================================ ⑧ 项目特征

def build_features(items: list[_Item], ctx: _RunContext,
                   answers: Optional[dict[str, dict[str, str]]] = None) -> tuple[dict[str, str], list[dict]]:
    """item.code → D 列文本；返回 (特征, 未作答的摘录任务)。

    zt 改动：摘录由 agent 作答（``f``），按清单项编码对应；未作答的任务原样返回，槽位写「待补」。

    :param items: 清单项。
    :param ctx: 运行上下文。
    :param answers: :func:`zt.quantity.features.parse_feature_answer` 的结果。
    :returns: ``(编码 → D 列文本, feature_tasks)``。
    """
    answers = answers or {}
    reg = code_registry.load_registry(ctx.version)
    fixed: dict[str, dict[int, str]] = {}
    slots_of: dict[str, list[feat.Slot]] = {}
    pending: list[dict] = []
    for it in items:
        slots = feat.parse_slots(reg[it.base_code]["features_text"])
        slots_of[it.code] = slots
        practice = "、".join(it.practices)
        part = "、".join(it.parts)
        vals: dict[int, str] = {}
        todo: dict[int, str] = {}
        for sl in slots:
            det = feat.deterministic_value(sl.label, practice, part)
            if det:
                vals[sl.no] = det
            elif sl.preset:
                vals[sl.no] = sl.preset
            else:
                todo[sl.no] = sl.label
        if todo:
            task = feat.FeatureTask(it.code, it.base_code, reg[it.base_code]["name"], todo,
                                    [s.text for s in it.main + it.aux])
            ans = answers.get(it.code)
            if ans is None:
                pending.append(feat.task_json(task))
            vals.update(feat.fill_values(task, ans))
        fixed[it.code] = vals
    codes = {it.code for it in items}
    ctx.stats.unknown_feature_keys.extend(k for k in answers if k not in codes)
    out: dict[str, str] = {}
    for it in items:
        layers = [s.text for s in sorted(it.main + it.aux, key=lambda s: s.order)]
        out[it.code] = feat.render(slots_of[it.code], fixed[it.code], "、".join(it.parts), layers)
    return out, pending


# ============================================================ 版本撞号（QTY-10，决策 D53）

def other_registries(version: str) -> dict[str, dict]:
    """除本版外的码表（{版本: registry}）。只有一个版本时为空 —— 不产出撞号提示。

    :param version: 本版。
    :returns: 其他版本码表。
    """
    out: dict[str, dict] = {}
    for v in code_registry.available_versions():
        if v != version:
            out[v] = code_registry.load_registry(v)
    return out


def cross_version_collisions(codes: list[str], version: str) -> dict[str, list[str]]:
    """同号异义的编码 → 说明。

    :param codes: 基码。
    :param version: 本版。
    :returns: 基码 → 说明列表。
    """
    reg = code_registry.load_registry(version)
    notes: dict[str, list[str]] = {}
    for v, other in other_registries(version).items():
        for code in codes:
            hit = other.get(code)
            if hit is not None and hit.get("name") != reg[code]["name"]:
                notes.setdefault(code, []).append(
                    f"同号异义：{code} 在 {v} 版为「{hit.get('name')}」，本表按 {version} 版为「{reg[code]['name']}」")
    return notes


# ============================================================ 编排：①–④b（prepare 与 finalize 共用）

@dataclass
class _Warn:
    code: str
    level: str
    message: str


def _warn(bucket: list[_Warn], code: str, level: str, message: str) -> None:
    assert code in rules.WARNING_CODES, code  # C2：code 必须先登记
    bucket.append(_Warn(code, level, message))


def _warn_items(warns: list[_Warn]) -> list[dict]:
    return [{"code": w.code, "level": w.level, "message": w.message} for w in warns]


def _dup_messages(dups: list[dict]) -> list[str]:
    """被合并的副本按保留的那份分组，一组一句告警。"""
    by_kept: dict[int, list[dict]] = {}
    for d in dups:
        by_kept.setdefault(d["kept_index"], []).append(d)
    return [same_content.message(g[0]["kept_label"], [d["label"] for d in g], "生成") for g in by_kept.values()]


@dataclass
class _State:
    files: list[tuple[bytes, str, str]]
    refs: dict[int, dict]
    texts: list[dict]
    skipped: list[str]
    dups: list[dict]
    verdicts: dict[int, rules.ScopeVerdict]
    fsegs: list[segmod.FileSegments]
    all_segs: list[Segment]
    practice: list[Segment]
    ledger: dict[str, LedgerRow]
    related: list[dict]
    provisional: list[Segment]
    to_classify: list[Segment]
    ctx: _RunContext
    warns: list[_Warn]
    prepare_fingerprint: str

    def coverage(self) -> dict:
        return _coverage_detail(self.texts, self.fsegs, self.practice, self.ledger, self.verdicts, self.ctx,
                                self.refs, self.related, len(self.provisional), dups=self.dups)


def _fingerprint(version: str, project_lot: Optional[int], to_classify: list[Segment],
                 exclusions: list[rules.Exclusion], cfg: QuantityConfig) -> str:
    """待分类片段、排除句、码表与提示词版本的指纹：finalize 用它确认 agent 回答的是同一批片段。"""
    body = {
        "code_version": version,
        "registry": qp.registry_fingerprint(version),
        "prompt_version": QUANTITY_PROMPT_VERSION,
        "project_lot": project_lot,
        "segments": [[s.id, s.file_name, s.location, s.text] for s in to_classify],
        "exclusions": [[e.id, e.sentence] for e in exclusions],
        "batch": [cfg.batch_max_segments, cfg.batch_max_chars],
    }
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _build_state(
    files: list[tuple[bytes, str, str]],
    version: str,
    pdf_loader: "PdfLoader | None",
    *,
    project_name: Optional[str],
    eng_category_name: Optional[str],
    file_refs: Optional[list[dict]],
    config: Optional[QuantityConfig],
) -> _State:
    cfg = config or QuantityConfig()
    warns: list[_Warn] = []
    refs = {i: (file_refs[i] if file_refs and i < len(file_refs) else {}) for i in range(len(files))}

    # ① extract（同内容只读一份，WS29-p）
    texts, skipped, dups = read_inputs(files, pdf_loader,
                                       [refs[i].get("display_path") or f[1] for i, f in enumerate(files)])
    for w in skipped:
        _warn(warns, "quantity_file_skipped_no_text", "warn", w)
    if not texts:
        raise ParseFailed("所有输入文件都未能抽取出可用文本，无法生成清单")
    for msg in _dup_messages(dups):
        _warn(warns, "quantity_duplicate_file", "info", msg)
    for t in texts:
        for code, msg in t["notes"]:
            _warn(warns, code, "warn", msg)
        if t.get("text_source") == "ocr_sidecar":
            _warn(warns, "quantity_ocr_source", "warn",
                  f"「{t['file_name']}」为扫描件，正文来自旁车识别——清单条目与原文摘录可能带识别误差，请人工核对原件")

    # ② scope（文件级）
    verdicts: dict[int, rules.ScopeVerdict] = {t["file_index"]: rules.file_scope(t["text"]) for t in texts}

    # ③ segment
    fsegs = [segmod.segment_file(t["content"], t["file_name"], t["ext"], t["text"], t["file_index"])
             for t in texts]
    for fs in fsegs:
        for code, msg in fs.warnings:
            _warn(warns, code, "info" if code == "quantity_hidden_sheets" else "warn", msg)
    all_segs = segmod.assign_ids(fsegs)
    practice = [s for s in all_segs if s.kind == PRACTICE]

    ctx = _RunContext(version, cfg, _Stats(), [], rules.parse_project_lot(project_name), eng_category_name,
                      qp.registry_fingerprint(version))
    for s in all_segs:
        if s.kind == EXCLUSION:
            for kind, objs, lot in s.exclusions:
                ctx.exclusions.append(rules.Exclusion(
                    f"e{len(ctx.exclusions) + 1}", kind, s.text, objs, lot, s.id, s.location, s.file_name))

    out_files = [t for t in texts if verdicts[t["file_index"]].out_of_scope]
    for t in out_files:
        v = verdicts[t["file_index"]]
        _warn(warns, "quantity_file_out_of_scope", "warn",
              f"「{t['file_name']}」判为{rules.domain_name(v.domain)}专业（房建词 {v.counts.get('building', 0)} 次、"
              f"非房建词 {v.foreign_hits} 次），不在清单框架生成的适用范围，已跳过")

    ledger: dict[str, LedgerRow] = {}
    for s in practice:
        v = verdicts[s.file_index]
        if v.out_of_scope:
            ledger[s.id] = LedgerRow(s, DEST_OUT, "file_out_of_scope",
                                     f"整份文件判为{rules.domain_name(v.domain)}专业，不在房建清单范围")
        elif s.section_domain:
            ledger[s.id] = LedgerRow(s, DEST_OUT, "section_out_of_scope",
                                     f"所在章节「{s.heading}」属{rules.domain_name(s.section_domain)}，不在房建清单范围")
    section_out = sum(1 for r in ledger.values() if r.reason_code == "section_out_of_scope")
    if section_out:
        _warn(warns, "quantity_section_out_of_scope", "warn",
              f"{section_out} 个做法片段位于非房建章节（如桥梁、道路、安装），未列项，见「覆盖核算」页")

    # ④b 层内标记（WS29-f）：自理、本层为二次装修的层在分类之前就定了去向
    for s in practice:
        if s.id not in ledger:
            row = inline_row(s)
            if row is not None:
                ledger[s.id] = row
    related = scope_related(all_segs)
    provisional = [s for s in practice if is_provisional(s) and s.id not in ledger]
    blocks = block_lines_unrecognized(fsegs, practice)
    if blocks:
        empty_n = len({x["practice"] for x in blocks if not x["practice_has_layers"]})
        _warn(warns, "quantity_block_lines_unrecognized", "info",
              f"做法块里有 {len(blocks)} 行没有认成构造层（不是做法片段，不进覆盖核算）"
              + (f"，其中 {empty_n} 个做法一层都没有认出" if empty_n else "")
              + "，逐行列在「说明」页「块内未识别行」，请人工确认有没有漏项")

    to_classify = [s for s in practice if s.id not in ledger]
    state = _State(files, refs, texts, skipped, dups, verdicts, fsegs, all_segs, practice, ledger, related,
                   provisional, to_classify, ctx, warns,
                   _fingerprint(version, ctx.project_lot, to_classify, ctx.exclusions, cfg))

    if len(out_files) == len(texts):
        raise QuantityRejected(
            "out_of_scope",
            "所选文件都不属于房屋建筑与装饰工程专业：" + "；".join(
                f"「{t['file_name']}」判为{rules.domain_name(verdicts[t['file_index']].domain)}"
                f"（房建词 {verdicts[t['file_index']].counts.get('building', 0)} 次、非房建词 "
                f"{verdicts[t['file_index']].foreign_hits} 次）" for t in texts)
            + "。" + SCOPE_NOTE, coverage=state.coverage(), warnings=[w.message for w in warns],
            warning_items=_warn_items(warns))

    # ④ gate-in
    per_file: dict[str, int] = {}
    for s in to_classify:
        per_file[s.file_name] = per_file.get(s.file_name, 0) + 1
    if len(to_classify) > cfg.max_segments:
        raise InputTooLarge(
            "too_many_segments",
            f"识别出 {len(to_classify)} 个做法片段，超过单次生成上限 {cfg.max_segments}："
            + "、".join(f"「{k}」{v} 个" for k, v in per_file.items())
            + "。请按单体/专业拆分，分多次生成", coverage=state.coverage(), warning_items=_warn_items(warns))
    # 认出了做法层、但都按层内标记划出范围或待核：不是「没有识别到做法」（R4F-d fix15 决定 4 / fix17 裁定 8）
    if not to_classify and not any(r.dest in (DEST_EXCLUDED, DEST_PENDING) for r in ledger.values()):
        raise QuantityRejected(
            "no_practice",
            "所选文件里没有识别到任何工程做法（带厚度、配合比或材料名的构造层）。" + SCOPE_NOTE
            + "请选择建筑设计说明或工程做法表", coverage=state.coverage(), warnings=[w.message for w in warns],
            warning_items=_warn_items(warns))
    if not to_classify and not _has_reviewable(ledger):
        raise _no_items(state.coverage(), ledger, fsegs, verdicts, warns)
    return state


# ============================================================ prepare

def prepare(
    files: list[tuple[bytes, str, str]],
    version: str = "zj2025",
    pdf_loader: "PdfLoader | None" = None,
    *,
    project_name: Optional[str] = None,
    eng_category_name: Optional[str] = None,
    file_refs: Optional[list[dict]] = None,
    config: Optional[QuantityConfig] = None,
) -> dict:
    """①–④b：读入、判专业、切片、层内标记，输出交给 agent 的待分类片段批次。

    :param files: ``[(字节, 文件名, 扩展名)]``。
    :param version: 码表版本。
    :param pdf_loader: PDF 读取回调。
    :param project_name: 项目名称（解析标段）。
    :param eng_category_name: 项目工程类别（仅供参考）。
    :param file_refs: 与 files 等长的 ``{file_id, rel_path, display_path}``。
    :param config: 可调参数。
    :returns: prepare 结果（见 :mod:`zt.quantity.cli`）。
    :raises ParseFailed: 全部文件抽不出正文。
    :raises QuantityRejected: out_of_scope / no_practice / too_many_segments / no_items。
    """
    st = _build_state(files, version, pdf_loader, project_name=project_name,
                      eng_category_name=eng_category_name, file_refs=file_refs, config=config)
    ctx = st.ctx
    batches = []
    for n, b in enumerate(make_batches(st.to_classify, ctx.cfg), start=1):
        rel = batch_exclusions(b, ctx.exclusions)
        batches.append({
            "batch": n, "file_name": b[0].file_name,
            "exclusions": [{"id": e.id, "sentence": e.sentence} for e in rel],
            "segments": [qp.segment_row(s) for s in b],
        })
    cov = st.coverage()
    return {
        "status": "ok",
        "prompt_version": QUANTITY_PROMPT_VERSION,
        "code_version": version,
        "registry_fingerprint": ctx.fingerprint,
        "registry_count": len(code_registry.load_registry(version)),
        "prepare_fingerprint": st.prepare_fingerprint,
        "project_name": project_name,
        "project_lot": ctx.project_lot,
        "eng_category_name": eng_category_name,
        "segments_to_classify": len(st.to_classify),
        "batches": batches,
        "exclusions": [{"id": e.id, "kind": e.kind, "sentence": e.sentence, "objects": e.objects,
                        "target_lot": e.target_lot, "file_name": e.file_name, "location": e.location}
                       for e in ctx.exclusions],
        "preset": {k: v for k, v in cov["by_destination"].items() if v},
        "coverage_detail": cov,
        "coverage": _envelope_coverage(st.texts, files, st.verdicts, st.practice, st.ledger, st.skipped, st.dups),
        "warnings": [w.message for w in st.warns] or None,
        "warning_items": _warn_items(st.warns),
    }


def instructions_text(prep: dict) -> str:
    """``清单分类说明.md``：分类说明（码表、易混淆对照、条件候选）。

    :param prep: :func:`prepare` 的结果。
    :returns: Markdown 文本。
    """
    return (f"<!-- prompt_version: {prep['prompt_version']} · 码表 {prep['code_version']} "
            f"sha256:{prep['registry_fingerprint'][:12]} -->\n\n"
            + qp.system_prompt(prep["code_version"]) + "\n")


def batches_text(prep: dict) -> str:
    """``清单分类批次.md``：逐批的用户说明（标段、相关排除句、片段 JSON 行）。

    :param prep: :func:`prepare` 的结果。
    :returns: Markdown 文本。
    """
    lot = prep.get("project_lot")
    eng = prep.get("eng_category_name")
    parts = [f"<!-- prompt_version: {prep['prompt_version']} · prepare_fingerprint: {prep['prepare_fingerprint']} -->"]
    for b in prep["batches"]:
        lot_text = f"{lot} 标" if lot is not None else "未识别"
        ex_text = "\n".join(f"{e['id']} {e['sentence']}" for e in b["exclusions"]) or "（无）"
        body = (qp.USER_TEMPLATE.replace("__LOT__", lot_text).replace("__ENG__", eng or "未提供")
                .replace("__EXCLUSIONS__", ex_text).replace("__FILE__", b["file_name"])
                .replace("__SEGMENTS__", "\n".join(json.dumps(s, ensure_ascii=False) for s in b["segments"])))
        parts.append(f"## 批次 {b['batch']}\n\n{body}")
    return "\n\n".join(parts) + "\n"


# ============================================================ finalize

def finalize(
    files: list[tuple[bytes, str, str]],
    answers: Any,
    version: str = "zj2025",
    pdf_loader: "PdfLoader | None" = None,
    *,
    project_name: Optional[str] = None,
    eng_category_name: Optional[str] = None,
    file_refs: Optional[list[dict]] = None,
    config: Optional[QuantityConfig] = None,
    prepare_fingerprint: Optional[str] = None,
) -> dict:
    """⑥–⑨：闸、聚合、特征、覆盖不变式。

    :param files: 与 prepare 相同的输入。
    :param answers: agent 的回答 ``{"r": [...], "f": [...]}``。
    :param version: 码表版本。
    :param pdf_loader: PDF 读取回调。
    :param project_name: 项目名称。
    :param eng_category_name: 项目工程类别。
    :param file_refs: 文件引用。
    :param config: 可调参数（须与 prepare 一致）。
    :param prepare_fingerprint: prepare 给出的指纹；给了就必须一致。
    :returns: 清单结果（render 的输入）。
    :raises PrepareMismatch: 指纹不一致。
    :raises AnswersMissing: 一个回答都没有且没有正式项。
    :raises CoverageInvariantError: 去向核算不成立。
    """
    st = _build_state(files, version, pdf_loader, project_name=project_name,
                      eng_category_name=eng_category_name, file_refs=file_refs, config=config)
    if prepare_fingerprint and prepare_fingerprint != st.prepare_fingerprint:
        raise PrepareMismatch(
            "finalize 重算出的待分类片段与 prepare 不一致（输入文件、项目名称、码表或提示词版本变了）："
            f"prepare {prepare_fingerprint[:12]} ≠ 现在 {st.prepare_fingerprint[:12]}")
    ctx, ledger, warns = st.ctx, st.ledger, st.warns
    to_classify = st.to_classify

    # ⑤ 回答（agent 给出）
    got = parse_answers(answers, to_classify, allowed_exclusions(to_classify, ctx.exclusions, ctx.cfg), ctx.stats)

    # ⑥ gates
    roles: dict[str, str] = {}
    for s in to_classify:
        row, role = decide(s, got[s.id], ctx)
        ledger[s.id] = row
        if role in ("main", "aux"):
            roles[s.id] = role

    # ⑦ aggregate + sort
    items = aggregate(ledger, roles, to_classify)

    # ⑨ coverage 不变式（先于渲染：错了就不出文件）
    check_invariant(st.practice, ledger)
    failed_n = sum(1 for r in ledger.values() if r.dest == DEST_LLM_FAILED)
    if ctx.stats.unknown_ids:
        _warn(warns, "quantity_llm_unknown_ids", "info",
              f"回答里有 {len(ctx.stats.unknown_ids)} 个不存在的片段编号，已丢弃：{sorted(set(ctx.stats.unknown_ids))[:10]}")
    if ctx.stats.duplicate_ids:
        _warn(warns, "quantity_answer_duplicate", "warn",
              f"回答里有 {len(ctx.stats.duplicate_ids)} 个片段编号重复作答，只取第一条："
              f"{sorted(set(ctx.stats.duplicate_ids))[:10]}")
    if ctx.stats.unknown_ex:
        _warn(warns, "quantity_llm_unknown_exclusion", "info",
              f"回答引用了不存在的排除句编号 {sorted(set(ctx.stats.unknown_ex))}，已忽略")

    if not items:
        if failed_n and failed_n == len(to_classify):
            raise AnswersMissing(
                f"全部 {failed_n} 个待分类片段都没有回答，无法生成清单；请按 prepare 的批次逐片段作答后再 finalize",
                coverage=st.coverage())
        # R4F-d fix15（决定 4）：没有任何正式项、但有可展示的待核行时照常出结果；fix17（裁定 8）：没有可展示的
        # 待核 / 未匹配行仍按 no_items 拒绝，不把失败伪装成成功（铁律 8）
        if not _has_reviewable(ledger):
            raise _no_items(st.coverage(), ledger, st.fsegs, st.verdicts, warns)
        by: dict[str, int] = {}
        for r in ledger.values():
            by[r.dest] = by.get(r.dest, 0) + 1
        _warn(warns, "quantity_no_formal_items", "warn",
              "没有形成任何正式清单项：" + "，".join(f"{DEST_CN[k]} {by[k]}" for k in DESTINATIONS if by.get(k))
              + "。清单页为空，明细见「待核与未匹配」页与「覆盖核算」页")

    # ⑧ features
    feature_answers = feat.parse_feature_answer(answers.get("f") if isinstance(answers, dict) else None)
    features, feature_tasks = build_features(items, ctx, feature_answers)
    if feature_tasks:
        _warn(warns, "quantity_features_skipped", "warn",
              f"{len(feature_tasks)} 个清单项的项目特征槽位还没有摘录，相关槽位写「待补」；"
              "按 data.feature_tasks 逐字摘录后把 f 加进 answers 重跑 finalize")
    if ctx.stats.unknown_feature_keys:
        _warn(warns, "quantity_features_unknown_items", "info",
              f"特征摘录里有 {len(ctx.stats.unknown_feature_keys)} 个清单项编码不在本次清单里，已忽略："
              f"{sorted(set(ctx.stats.unknown_feature_keys))[:10]}")
    collisions = cross_version_collisions(sorted({it.base_code for it in items}), version)
    for it in items:
        marked = [s for s in it.main + it.aux if is_provisional(s)]
        if marked:
            it.notes.append(f"做法暂定：{rules.PROVISIONAL_NOTE}（本条 {len(marked)} 层），"
                            "规格材质以装修设计为准，是否属于本次范围请人工确认")
        it.notes.extend(collisions.get(it.base_code, []))
    if collisions:
        _warn(warns, "quantity_cross_version", "info",
              f"{len(collisions)} 个编码在其他版本码表里同号异名，已在来源列标注")

    counts = {d: 0 for d in DESTINATIONS}
    for r in ledger.values():
        counts[r.dest] += 1
    if counts[DEST_PENDING]:
        _warn(warns, "quantity_pending_review", "warn",
              f"{counts[DEST_PENDING]} 个片段降为待核（语义不一致 / 角色冲突 / 排除未确认），未进正式清单，见「待核与未匹配」页")
    if counts[DEST_UNMATCHED]:
        _warn(warns, "quantity_unmatched", "warn", f"{counts[DEST_UNMATCHED]} 个片段没有得到码表里的编码，需人工补")
    if counts[DEST_EXCLUDED]:
        _warn(warns, "quantity_excluded_scope", "info",
              f"{counts[DEST_EXCLUDED]} 个片段按原文排除句划出本次范围，见「待核与未匹配」页")
    if st.provisional:
        basis = next((x["sentence"] for x in st.related if "暂定" in x["sentence"]), "")
        _warn(warns, "quantity_fitout_provisional", "info",
              f"{len(st.provisional)} 个做法层原文注明详精装修设计（或详二次装修），已按暂定做法列项。"
              "是否属于本次范围请人工确认。" + (f"依据（原文）：{basis}" if basis else ""))
    generic_n = sum(1 for x in st.related if x["reason"] == "too_generic")
    if generic_n:
        _warn(warns, "quantity_exclusion_object_too_generic", "warn",
              f"{generic_n} 句原文读着像范围排除句，但对象只有「面层」这类泛指词，没有据此排除任何做法，"
              "见「说明」页「范围相关原文」")
    if any(r.reason_code == "lot_unknown" for r in ledger.values()):
        _warn(warns, "quantity_lot_unknown", "warn",
              "项目名称里解析不到标段（如「III标」），命中标段排除句的做法已降为待核")
    status = "ok"
    if failed_n:
        status = "partial"
        _warn(warns, "quantity_llm_failed", "warn",
              f"{failed_n} 个做法片段没有回答（answers 里缺这些 id），结果为部分完成，见「覆盖核算」页")

    cov = st.coverage()
    reg = code_registry.load_registry(version)
    item_rows = [_item_out(it, reg, features[it.code], st.refs) for it in items]
    unmatched = unmatched_rows(ledger, st.fsegs, st.verdicts)
    ocr_files = [t["file_name"] for t in st.texts if t.get("text_source") == "ocr_sidecar"]
    meta = {
        "code_version": version, "registry_fingerprint": ctx.fingerprint,
        "registry_count": len(reg), "prompt_version": QUANTITY_PROMPT_VERSION,
        "prepare_fingerprint": st.prepare_fingerprint, "status": status, "project_name": project_name,
        "project_lot": ctx.project_lot, "eng_category_name": eng_category_name, "ocr_files": ocr_files,
        "answered": sum(1 for v in got.values() if isinstance(v, Answer)),
        "to_classify": len(to_classify),
    }
    return {
        "status": status,
        "items": item_rows,
        "unmatched": unmatched,
        "ledger": ledger_rows(st.practice, ledger),
        "feature_tasks": feature_tasks,
        "warnings": [w.message for w in warns] or None,
        "warning_items": _warn_items(warns),
        "coverage_detail": cov,
        "coverage": _envelope_coverage(st.texts, files, st.verdicts, st.practice, ledger, st.skipped, st.dups),
        "meta": meta,
        "code_version": version,
        "registry_fingerprint": ctx.fingerprint,
        "prompt_version": QUANTITY_PROMPT_VERSION,
        "prepare_fingerprint": st.prepare_fingerprint,
    }


def _has_reviewable(ledger: dict[str, LedgerRow]) -> bool:
    """至少一行待核 / 未匹配行可以展示（协调者 2026-10-13 裁定 8）。

    算的：带具体原因的待核（aux_without_main 除外）、模型给了编码但编码不在码表里的未匹配。不算的：模型没给编码、
    范围排除、基层、缺回答——只有这些时是真正的空结果，仍 no_items。
    """
    return any((r.dest == DEST_PENDING and r.reason_code != "aux_without_main")
               or (r.dest == DEST_UNMATCHED and r.reason_code == "code_not_in_registry") for r in ledger.values())


def _no_items(cov: dict, ledger: dict[str, LedgerRow], fsegs, verdicts, warns: list) -> QuantityRejected:
    """no_items：认出了做法层、却没有正式项也没有可展示的待核行；明细（unmatched）与逐片段核算照样交出。"""
    return QuantityRejected(
        "no_items",
        "没有形成任何正式清单项：" + "，".join(f"{DEST_CN[k]} {v}" for k, v in cov["by_destination"].items() if v)
        + "。明细见返回的 unmatched（待核 / 未匹配 / 范围排除）", coverage=cov,
        unmatched=unmatched_rows(ledger, fsegs, verdicts), warnings=[w.message for w in warns],
        warning_items=_warn_items(warns))


def check_invariant(practice: list[Segment], ledger: dict[str, LedgerRow]) -> None:
    """覆盖不变式：每个 practice 片段恰好一个合法去向。

    :param practice: 全部做法片段。
    :param ledger: 台账。
    :raises CoverageInvariantError: 不成立。
    """
    ids = [s.id for s in practice]
    missing = [i for i in ids if i not in ledger]
    extra = [i for i in ledger if i not in set(ids)]
    bad = [i for i, r in ledger.items() if r.dest not in DESTINATIONS]
    if missing or extra or bad or len(set(ids)) != len(ids):
        raise CoverageInvariantError(
            f"片段去向核算不成立：缺去向 {missing[:10]}、多余 {extra[:10]}、非法去向 {bad[:10]}")


def _exclusion_list(practice, ledger, ctx) -> list[dict]:
    """范围排除的依据。scope=global：全局排除句，hits 是它排掉的片段数，0 也列；scope=inline：层内标记排掉的层。"""
    hits: dict[str, int] = {}
    for r in ledger.values():
        if r.dest == DEST_EXCLUDED and r.exclusion_id:
            hits[r.exclusion_id] = hits.get(r.exclusion_id, 0) + 1
    out = [{"id": e.id, "scope": "global", "kind": e.kind, "sentence": e.sentence, "objects": e.objects,
            "target_lot": e.target_lot, "file_name": e.file_name, "location": e.location,
            "hits": hits.get(e.id, 0)} for e in ctx.exclusions]
    n = 0
    for s in practice:
        r = ledger.get(s.id)
        if r is None or r.dest != DEST_EXCLUDED or r.reason_code not in (rules.OWNER_INLINE,
                                                                         rules.SECONDARY_INLINE):
            continue
        n += 1
        out.append({"id": f"i{n}", "scope": "inline",
                    "kind": "owner" if r.reason_code == rules.OWNER_INLINE else "secondary",
                    "reason_code": r.reason_code, "sentence": s.text, "objects": [], "target_lot": None,
                    "file_name": s.file_name, "location": s.location, "segment_id": s.id, "hits": 1})
    return out


def _coverage_detail(texts, fsegs, practice, ledger, verdicts, ctx, refs, related=None,
                     provisional: int = 0, *, dups=()) -> dict:
    by_dest = {d: 0 for d in DESTINATIONS}
    for s in practice:
        r = ledger.get(s.id)
        if r is not None:
            by_dest[r.dest] += 1
    by_file = []
    for t, fs in zip(texts, fsegs):
        v = verdicts[t["file_index"]]
        fd = {d: 0 for d in DESTINATIONS}
        n_pr = 0
        for s in fs.segments:
            if s.kind == PRACTICE:
                n_pr += 1
                r = ledger.get(s.id)
                if r is not None:
                    fd[r.dest] += 1
        ref = refs.get(t["file_index"]) or {}
        by_file.append({
            "file_index": t["file_index"],
            "file_id": ref.get("file_id"), "file_name": t["file_name"], "text_source": t["text_source"],
            "mode": fs.mode, "scope": v.domain or "building", "domain_counts": v.counts,
            "building_share": v.building_share, "segments_total": len(fs.segments),
            "practice_segments": n_pr, "by_destination": {k: x for k, x in fd.items() if x},
            "hidden_sheets": fs.hidden_sheets, "notes": [m for _c, m in t["notes"]],
        })
    by_file.extend(_duplicate_entries(dups, texts, verdicts, refs))
    by_file.sort(key=lambda f: f.pop("file_index"))
    return {
        "practice_segments": len(practice),
        # 识别出的做法个数（按做法分组键去重），对得上原表的做法个数（WS29-k1）
        "practices": len({s.practice_key or f"solo:{s.id}" for s in practice}),
        "by_destination": by_dest,
        "by_file": by_file,
        "project_lot": ctx.project_lot,
        "exclusions": _exclusion_list(practice, ledger, ctx),
        "scope_related": list(related or []),
        "provisional_segments": provisional,
        "block_lines_unrecognized": block_lines_unrecognized(fsegs, practice),
    }


def _duplicate_entries(dups, texts, verdicts, refs) -> list[dict]:
    """被合并的副本在 by_file 里也占一行（WS29-p）：没有单独读，片段 0 个，duplicate_of 指向保留的那份。"""
    kept_text = {t["file_index"]: t for t in texts}
    out = []
    for d in dups:
        ref = refs.get(d["file_index"]) or {}
        kept = refs.get(d["kept_index"]) or {}
        v = verdicts[d["kept_index"]]
        out.append({
            "file_index": d["file_index"], "file_id": ref.get("file_id"), "file_name": d["file_name"],
            "text_source": "none", "mode": "duplicate", "scope": v.domain or "building",
            "domain_counts": v.counts, "building_share": v.building_share, "segments_total": 0,
            "practice_segments": 0, "by_destination": {}, "hidden_sheets": [],
            "duplicate_of": {"file_id": kept.get("file_id"), "file_name": kept_text[d["kept_index"]]["file_name"],
                             "display_path": kept.get("display_path")},
            "notes": [f"与「{d['kept_label']}」内容相同，没有单独读取，只按那一份生成"],
        })
    return out


def block_lines_unrecognized(fsegs, practice: list[Segment]) -> list[dict]:
    """做法块里没认成构造层的行（WS29-k2，E31）：原句、位置、所在做法，以及这个做法有没有切出任何一层。

    :param fsegs: 各文件切片结果。
    :param practice: 做法片段。
    :returns: 行列表。
    """
    with_layers = {s.practice_key for s in practice if s.practice_key}
    return [{"text": s.text, "file_name": s.file_name, "location": s.location, "practice": s.block_practice,
             "practice_has_layers": bool(s.practice_key) and s.practice_key in with_layers}
            for fs in fsegs for s in fs.segments if s.kind == OTHER and s.block_practice is not None]


def _envelope_coverage(texts, files, verdicts, practice, ledger, skipped, dups=()) -> dict:
    """信封 coverage（files_total / files_used / rows_parsed / unmatched / skipped）。prepare 时尚未定去向的片段算用到。"""
    used = {s.file_index for s in practice if s.id not in ledger or ledger[s.id].dest != DEST_OUT}
    sk = [{"file_name": t["file_name"], "stage": "scope",
           "reason": f"判为{rules.domain_name(verdicts[t['file_index']].domain)}专业"}
          for t in texts if verdicts[t["file_index"]].out_of_scope]
    sk += [{"stage": "extract", "reason": w} for w in skipped]
    sk += [{"file_name": d["file_name"], "stage": "dedupe",
            "reason": same_content.message(d["kept_label"], [d["label"]], "生成")} for d in dups]
    return {"files_total": len(files), "files_used": len(used), "rows_parsed": len(practice),
            "unmatched": sum(1 for r in ledger.values() if r.dest in (DEST_UNMATCHED, DEST_PENDING, DEST_LLM_FAILED)),
            "skipped": sk}


def _source_str(s: Segment) -> str:
    return f"{s.file_name} | {s.location} | 原文：{s.text}"


def _item_out(it: _Item, reg: dict, features: str, refs: dict) -> dict:
    hit = reg[it.base_code]
    main_ids = {s.id for s in it.main}
    srcs = []
    for s in sorted(it.main + it.aux, key=lambda x: x.order):
        ref = refs.get(s.file_index) or {}
        srcs.append({"file_id": ref.get("file_id"), "file_name": s.file_name, "location": s.location,
                     "quote": s.text[:200], "role": "main" if s.id in main_ids else "aux",
                     "evidence": s.evidence(ref.get("rel_path"), ref.get("file_id"))})
    source = "\n".join(_source_str(s) for s in sorted(it.main, key=lambda x: x.order))
    if it.notes:
        source += "\n" + "\n".join(it.notes)
    return {
        "code": it.code, "base_code": it.base_code,
        "name": hit["name"],              # 查表真相，不用模型的措辞
        "unit": hit["unit"], "features": features, "section": hit["chapter_name"], "source": source,
        "practice": "、".join(it.practices), "part": "、".join(it.parts), "category": "、".join(it.categories),
        "sources": srcs, "notes": list(it.notes),
        # zt 改动：清单项不出工程量，但仍是数量类对象，按铁律 2 标注
        "needs_manual": True,
    }


def with_mark(r: LedgerRow) -> str:
    """台账说明：带精装修引用的层在原因后面注一句「做法暂定」（它是标记，不是去向）。

    :param r: 台账行。
    :returns: 说明文字。
    """
    if not is_provisional(r.seg):
        return r.reason
    return f"{r.reason}【{rules.PROVISIONAL_NOTE}】" if r.reason else f"【{rules.PROVISIONAL_NOTE}】"


def ledger_rows(practice: list[Segment], ledger: dict[str, LedgerRow]) -> list[dict]:
    """逐片段去向（「覆盖核算」页的数据）。

    zt 改动：旧版渲染时直接读 Segment；现在 render 是独立子命令，台账按行序列化进 finalize 结果。

    :param practice: 做法片段。
    :param ledger: 台账。
    :returns: 每个片段一行。
    """
    out = []
    for s in practice:
        r = ledger.get(s.id)
        out.append({
            "id": s.id, "file_name": s.file_name, "location": s.location, "category": s.category,
            "part": s.part, "practice": s.practice, "layer_no": s.layer_no, "text": s.text,
            "dest": r.dest if r else None, "reason_code": r.reason_code if r else None,
            "code": (r.item_code or r.llm_code or "") if r else "",
            "reason": with_mark(r) if r else "",
        })
    return out


def unmatched_rows(ledger: dict[str, LedgerRow], fsegs, verdicts) -> list[dict]:
    """待核 / 未匹配 / 范围排除 / 越界 / 缺回答的明细（QTY-08）。整份越界的文件只出一行汇总。

    :param ledger: 台账。
    :param fsegs: 各文件切片结果（未用，保留调用形态）。
    :param verdicts: 文件专业判定（未用，保留调用形态）。
    :returns: 明细行。
    """
    rows: list[dict] = []
    file_out: dict[str, int] = {}
    for r in sorted(ledger.values(), key=lambda x: x.seg.order):
        if r.dest in (DEST_ITEM, DEST_AUX, DEST_BASE):
            continue
        if r.reason_code == "file_out_of_scope":
            file_out[r.seg.file_name] = file_out.get(r.seg.file_name, 0) + 1
            continue
        rows.append({
            "kind": r.dest, "segment_id": r.seg.id, "text": r.seg.text, "description": r.seg.text,
            "file_name": r.seg.file_name, "location": r.seg.location, "reason_code": r.reason_code,
            "reason": with_mark(r), "llm_guessed_code": r.llm_code, "suggested": r.suggested,
        })
    for name, n in file_out.items():
        rows.append({"kind": DEST_OUT, "segment_id": None, "text": f"（整份文件 {n} 个做法片段）",
                     "description": f"「{name}」整份越界", "file_name": name, "location": "整份文件",
                     "reason_code": "file_out_of_scope",
                     "reason": f"整份文件不属于房屋建筑与装饰工程专业，{n} 个做法片段未列项", "llm_guessed_code": None,
                     "suggested": None})
    return rows
