# 来源：engine-service/app/api/estimate.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""概算的接线层：两段式，**抽取不出数、计算才出数**。

    extract_prepare  files                      → 关键词窗口与抽取说明（agent 读）            不出数
    extract_finalize files + agent 的回答        → {candidates, unresolved, buildings, …}       不出数
    suggest          规模 + 基准 + 费率基数        → {suggestions, fee, unresolved, coverage}     全确定性
    compute          inputs + rates             → {sheets, totals, indicators} + xlsx          全确定性
    template                                    → 行树 + 输入位元数据

zt 改动：去掉 FastAPI 路由、鉴权、usage 与透传字段；HTTP 4xx/5xx 改成两类结果：

- 拦截闸（必填 → 面积闸 → 面积对账 → 全零，顺序由测试钉死）抛 :class:`GateRejected`，CLI 输出
  ``insufficient`` 信封（status_reason = 闸的码）；
- 请求不合法（模板不存在、inputs 非数值含 bool、字段越界）、渲染器缺失、回答形状不对抛
  :class:`zt.common.ZtError`，CLI 退出码 2。

suggest 为什么单列（契约裁决 B）：正向推算必须有出口，否则「概算生成」退回成让造价员手拍 150 个成本数。
它出金额，但全确定性（基准×规模，零模型），产物是待确认的 ``suggested``。

为什么必须拆两段（铁律 2）：模型抽的规模参数须经用户确认才进计算。extract 只回候选（全部 needs_manual，
响应体零金额字段），compute 只吃调用方回传的、用户确认过的 inputs。
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zt.common import ZtError
from zt.common.paths import to_rel_posix
from zt.estimate import checks as estimate_checks
from zt.estimate import extract as estimate_extract
from zt.estimate import gates as estimate_gates
from zt.estimate import policy as estimate_policy
from zt.estimate import quality as estimate_quality
from zt.estimate import warning_codes
from zt.estimate.engine import EstimateTemplateError, column_units, load_template
from zt.estimate.engine import run as estimate_run
# WS29-s：标段号的解析与清单同一个函数（D54）
from zt.quantity import same_content
from zt.quantity.rules import parse_project_lot
from zt.textextract.extract import load_document
from zt.textextract.files import resolve_project_file
from zt.textextract.model import DocText

TEMPLATE_CODE = r"^[A-Za-z0-9_-]{1,64}$"


class GateRejected(Exception):
    """compute 的拦截闸拒算（旧版 422）。

    :param code: 闸的码（:data:`zt.estimate.gates.ORDER` 之一）。
    :param detail: 给人看的原因（闸的原文案）。
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _bad_request(e: Exception) -> ZtError:
    return ZtError("invalid_request", str(e))


# ------------------------------------------------------------------ 请求

class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComputeRequest(_Req):
    """compute 入参。inputs / rates 刻意声明成 ``dict[str, Any]``：声明 float 时 pydantic 会把 JSON ``true``
    静默转成 1.0，严格类型检查交给 ``estimate_engine.run()``（显式拒 bool）。"""

    template_code: str = Field("gsyz_v1", pattern=TEMPLATE_CODE)
    inputs: dict[str, Any]
    rates: Optional[dict[str, Any]] = None
    project_name: Optional[str] = None
    render: bool = True
    area_checks: Optional[dict[str, Any]] = None
    acknowledged_checks: Optional[list[Any]] = None
    slot_labels: Optional[dict[str, Any]] = None
    input_sources: Optional[dict[str, Any]] = None
    fee_bases: Optional[dict[str, Any]] = None
    fee_attrs: Optional[dict[str, Any]] = None
    project_profile: Optional[dict[str, Any]] = None
    # 生成说明与 xlsx 字节由它确定：同一入参两次渲染逐字节一致
    generated_at: Optional[str] = None


class SuggestRequest(_Req):
    """suggest 入参。baselines / items 是概算指标基准（zt 改动：旧版由 Java 查库下发，现在由调用方给出
    基准 JSON 文件，例如知识库里的指标基准）。"""

    template_code: str = Field("gsyz_v1", pattern=TEMPLATE_CODE)
    inputs: dict[str, Any]
    baselines: list[dict] = Field(default_factory=list)
    items: list[dict] = Field(default_factory=list)
    dims: Optional[dict[str, Any]] = None
    fee_bases: Optional[dict[str, Any]] = None
    fee_attrs: Optional[dict[str, Any]] = None


class FileRef(_Req):
    """项目内一份文件。file_id 缺省取规范化后的 rel_path。"""

    rel_path: str
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    display_path: Optional[str] = None


class ExtractRequest(_Req):
    files: list[FileRef]
    template_code: str = Field("gsyz_v1", pattern=TEMPLATE_CODE)
    project_name: Optional[str] = None


def parse(model: type[_Req], body: Any) -> Any:
    """请求字典 → 请求模型；不合法抛 ZtError（invalid_request）。

    :param model: 请求模型类。
    :param body: 请求字典。
    :returns: 模型实例。
    :raises ZtError: 字段不合法。
    """
    try:
        return model.model_validate(body or {})
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", ()))
        raise ZtError("invalid_request", f"请求字段不合法：{loc} {first.get('msg')}") from e


# 旧端点模块里的别名：模板下发与既有用例按旧名取用（函数本体在 estimate_checks）
_optional_input_impact = estimate_checks.optional_input_impact
_input_value_scales = estimate_checks.input_value_scales
_ratio_scale_warnings = estimate_checks.ratio_scale_warnings
_split_cell = estimate_checks.split_cell
_column_units = column_units


def _required_input_cells(template_code: str) -> list[str]:
    """必填输入位 = 模板 `经济技术指标` 表的输入位（实测 11 个），与 extract 的候选池同一个来源函数。"""
    return [s["cell"] for s in estimate_extract.root_input_specs(template_code)]


# ------------------------------------------------------------------ extract

def _no_text_detail(doc: DocText) -> str:
    """降级链走完仍无正文 → 给人看的原因（写明为什么，不一律「可能是扫描件」）。"""
    f = doc.failure
    if f is None:
        return "该文件抽不出可读正文"
    return f"该文件取不到可读正文：{f.detail}（{f.code}）"


def _incomplete_text_warning(name: str, doc: DocText) -> dict | None:
    """有正文但缺页 / 截断（C5：缺页与截断不许吞，转成告警）。"""
    missing = doc.pages_missing
    if not missing and not doc.truncated:
        return None
    parts = []
    if missing:
        head = "、".join(str(n) for n in missing[:10]) + ("…" if len(missing) > 10 else "")
        reasons = sorted({p.missing_reason for p in doc.pages if p.source == "missing" and p.missing_reason})
        parts.append(f"第 {head} 页未取得正文" + (f"（{'；'.join(reasons[:3])}）" if reasons else ""))
    if doc.truncated:
        parts.append("正文被截断（页数上限）")
    return {"code": "source_text_incomplete", "cell": None,
            "message": f"「{name}」" + "，".join(parts)
                       + "：这些页里的指标本次没有检索到，not_found 不代表原文没有。"}


_CN_DIGITS = "零一二三四五六七八九"


def _lot_label(n: int) -> str:
    """标段号 → 「一标段」「十二标段」（提示文案用；1–99 写中文数字，其余写阿拉伯数字）。"""
    if 1 <= n <= 9:
        s = _CN_DIGITS[n]
    elif 10 <= n <= 99:
        tens, ones = divmod(n, 10)
        s = ("" if tens == 1 else _CN_DIGITS[tens]) + "十" + (_CN_DIGITS[ones] if ones else "")
    else:
        s = str(n)
    return f"{s}标段"


def _area_text(v: float) -> str:
    """172389.96 → 「172,389.96」：千分位，不带浮点毛刺。"""
    return format(Decimal(format(float(v), ".12g")), ",f")


def lot_scope(project_name: str | None, check_values: list[dict]) -> tuple[dict, list[dict]]:
    """→ (scope, 告警)。项目名称解析出标段、而总建筑面积这条总量的引文没有注明本标段时，出
    scope_whole_site_suspect（WS29-s：一标段项目抽到全地块面积，概算规模翻倍）。只提示，不改候选。

    :param project_name: 项目名称。
    :param check_values: 合并后的原文总量。
    :returns: ``(scope, warnings)``。
    """
    lot = parse_project_lot(project_name)
    scope = {"project_lot": lot, "lot_source": "project_name" if lot is not None else None}
    if lot is None:
        return scope, []
    loose: list[float] = []
    for c in check_values or []:
        if c.get("key") != "gross_building_area" or c.get("value") is None:
            continue
        # 标段归属只认核验过的引文：抄回一句原文里没有的「一标段总建筑面积…」，不能把提示压掉
        verified = bool((c.get("verification") or {}).get("quote_in_source"))
        if verified and parse_project_lot(c.get("quote")) == lot:
            continue
        v = float(c["value"])
        if v not in loose:
            loose.append(v)
    if not loose:
        return scope, []
    label = _lot_label(lot)
    nums = "、".join(f"{_area_text(v)} ㎡" for v in loose)
    return scope, [{
        "code": "scope_whole_site_suspect", "cell": None,
        "message": f"项目名称含「{label}」，所选文件给的总量没有注明是{label}的（总建筑面积 {nums}）。"
                   "如果这是全地块的数，请按分标段资料填写本标段的面积、用地与车位。",
        "project_lot": lot, "lot_label": label, "values": loose,
    }]


def _file_id(f: FileRef) -> str:
    return f.file_id or to_rel_posix(f.rel_path)


def _file_name(f: FileRef) -> str:
    return f.file_name or to_rel_posix(f.rel_path).rsplit("/", 1)[-1]


def _content_key(root: Path, rel_path: str) -> str | None:
    """原件字节的 sha256（WS29-p 去重用）。读不到就不参与去重，缺文件照旧由 load_document 报错。"""
    try:
        return same_content.file_key(resolve_project_file(root, rel_path))
    except (ZtError, OSError):
        return None


def _read_files(root: Path, req: ExtractRequest) -> tuple[list[tuple[FileRef, DocText]], list[dict], list[dict]]:
    """读入（同内容只读一份）→ (可读文件, no_text 行, 读入告警)。"""
    keys = [_content_key(root, x.rel_path) for x in req.files]
    shown = same_content.labels([x.display_path or _file_name(x) for x in req.files])
    readable: list[tuple[FileRef, DocText]] = []
    no_text: list[dict] = []
    warns: list[dict] = []
    for group in same_content.groups(keys):
        kept = None
        unread: list[tuple[FileRef, DocText]] = []
        for i in group:
            cand = req.files[i]
            got = load_document(root, cand.rel_path, file_name=_file_name(cand))
            if got.failure is None and (got.text or "").strip():
                kept = i
                readable.append((cand, got))
                break
            unread.append((cand, got))
        if kept is None:
            for cand, got in unread:
                no_text.append({"cell": None, "label": _file_name(cand), "reason": "no_text",
                                "detail": _no_text_detail(got), "source_file_id": _file_id(cand)})
            continue
        others = [shown[j] for j in group if j != kept]
        if others:
            warns.append({"code": "source_file_duplicate", "cell": None, "level": "info",
                          "message": same_content.message(shown[kept], others, "抽取")})
        w = _incomplete_text_warning(_file_name(req.files[kept]), readable[-1][1])
        if w is not None:
            warns.append(w)
    return readable, no_text, warns


def _all_no_text(no_text: list[dict]) -> ZtError:
    details = "；".join(u["detail"] for u in no_text)
    return ZtError("no_text", "给定的所有文件都抽不出可读文本：" + details,
                   hint="扫描件请先用 read_image 看图，把识别文字写成并列旁车 <原件名>.ocr.txt 后再跑")


def _fingerprint(template_code: str, prepared: list[dict]) -> str:
    body = {"prompt_version": estimate_extract.ESTIMATE_PROMPT_VERSION, "template_code": template_code,
            "files": [[p["file_id"], p["window_sha256"]] for p in prepared]}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def extract_prepare(body: Any, root: Path) -> dict:
    """读文件、取关键词窗口，给出抽取说明（不出任何数）。

    :param body: :class:`ExtractRequest` 字典。
    :param root: 项目目录。
    :returns: ``{prompt_version, template_code, prepare_fingerprint, instructions, files[{…, window}], unresolved,
        warnings}``；window 是交给 agent 的正文。
    :raises ZtError: 没有文件、模板不存在、全部文件读不出正文。
    """
    req = parse(ExtractRequest, body)
    if not req.files:
        raise ZtError("no_files", "files 不能为空", hint="--files 资料/设计说明.pdf …")
    try:
        estimate_extract.root_input_specs(req.template_code)
        pol = estimate_policy.load_policy(req.template_code)
    except EstimateTemplateError as e:
        raise _bad_request(e) from e
    readable, no_text, warns = _read_files(root, req)
    if not readable:
        raise _all_no_text(no_text)
    prepared = [estimate_extract.prepare_text(_file_id(f), doc.text, doc.text_source, req.template_code,
                                              file_name=_file_name(f)) for f, doc in readable]
    cell_specs = estimate_extract.cell_hint_specs(req.template_code, pol)
    text = estimate_extract.instructions(cell_specs, estimate_policy.extract_checks(pol),
                                         bool(estimate_policy.slot_cells(pol)))
    return {
        "prompt_version": estimate_extract.ESTIMATE_PROMPT_VERSION,
        "template_code": req.template_code,
        "prepare_fingerprint": _fingerprint(req.template_code, prepared),
        "instructions": text,
        "files": [{**p, "rel_path": to_rel_posix(f.rel_path)} for p, (f, _d) in zip(prepared, readable)],
        "unresolved": no_text,
        "warnings": warns,
        "request": req.model_dump(exclude_none=True),
    }


def _answers_by_file(answers: Any) -> dict[str, Any]:
    rows = answers.get("files") if isinstance(answers, dict) else answers
    if not isinstance(rows, list):
        raise ZtError("invalid_answers", "answers 须是 {\"files\": [{\"file_id\", \"buildings\", \"checks\", \"cells\"}]}")
    out: dict[str, Any] = {}
    for r in rows:
        if not isinstance(r, dict) or not isinstance(r.get("file_id"), str):
            raise ZtError("invalid_answers", "answers.files 的每一项须带 file_id")
        fid = r["file_id"]
        if fid in out:
            raise ZtError("invalid_answers", f"answers 里 file_id 重复：{fid}")
        out[fid] = {k: v for k, v in r.items() if k != "file_id"}
    return out


def extract_finalize(body: Any, root: Path, answers: Any, prepare_fingerprint: str | None = None) -> dict:
    """agent 的回答 → 候选、未落定项、单体、原文总量（确定性后处理 + 多文件合并）。

    :param body: :class:`ExtractRequest` 字典（与 prepare 相同）。
    :param root: 项目目录。
    :param answers: ``{"files": [{file_id, buildings, checks, cells}]}``。
    :param prepare_fingerprint: prepare 给出的指纹；给了就必须一致。
    :returns: 与旧 ``EstimateExtractOut`` 同形（去掉 usage）。
    :raises ZtError: 指纹不一致、回答形状不对、一份都没回答。
    """
    req = parse(ExtractRequest, body)
    if not req.files:
        raise ZtError("no_files", "files 不能为空")
    try:
        estimate_extract.root_input_specs(req.template_code)
    except EstimateTemplateError as e:
        raise _bad_request(e) from e
    readable, no_text, warns = _read_files(root, req)
    if not readable:
        raise _all_no_text(no_text)
    prepared = [estimate_extract.prepare_text(_file_id(f), doc.text, doc.text_source, req.template_code,
                                              file_name=_file_name(f)) for f, doc in readable]
    fp = _fingerprint(req.template_code, prepared)
    if prepare_fingerprint and prepare_fingerprint != fp:
        raise ZtError("prepare_mismatch", f"正文窗口与 prepare 不一致（prepare {prepare_fingerprint[:12]} ≠ 现在 {fp[:12]}）",
                      hint="输入文件变了：重新跑 extract_prepare，按新正文作答")
    by_file = _answers_by_file(answers)
    known = {_file_id(f) for f, _d in readable}
    unknown = sorted(set(by_file) - known)
    if unknown:
        raise ZtError("invalid_answers", f"answers 里有不在本次正文里的 file_id：{unknown}")
    per_file: list[dict] = []
    for f, doc in readable:
        fid = _file_id(f)
        if fid not in by_file:
            warns.append({"code": "extract_answer_missing", "cell": None,
                          "message": f"「{_file_name(f)}」没有回答，这份文件的指标本次没有抽取；not_found 不代表原文没有"})
            continue
        try:
            per_file.append(estimate_extract.extract_from_text(
                fid, doc.text, by_file[fid], None, doc.text_source, req.template_code, file_name=_file_name(f)))
        except estimate_extract.AnswerUnparseable as e:
            raise ZtError("invalid_answers", f"「{_file_name(f)}」的回答形状不对：{e}") from e
    if not per_file:
        raise ZtError("answers_missing", "所有可读文件都没有回答", hint="按 概算抽取说明.md 逐份作答，file_id 照抄")
    merged = estimate_extract.merge_extractions(per_file, template_code=req.template_code)
    scope, scope_warnings = lot_scope(req.project_name, merged["check_values"])
    candidates = [dict(c, needs_manual=True) for c in merged["candidates"]]
    return {
        "candidates": candidates,
        "unresolved": no_text + merged["unresolved"],
        "buildings": merged["buildings"],
        "check_values": merged["check_values"],
        "warnings": warns + merged["warnings"] + scope_warnings,
        "text_stats": merged["text_stats"],
        "scope": scope,
        "prompt_version": estimate_extract.ESTIMATE_PROMPT_VERSION,
        "prepare_fingerprint": fp,
    }


# ------------------------------------------------------------------ suggest

DERIVABLE_FEE_BASES = estimate_checks.DERIVABLE_FEE_BASES
_DATA_DIR = Path(__file__).resolve().parent / "data"


def default_baselines(template_code: str = "gsyz_v1") -> list[dict]:
    """随包的样本指标基准（旧版由 Java 从同一份种子 SQL 查库下发）。

    单一来源（gsyz_v1 样本），按 D47 只作单样本参考，不是已签核的企业指标库。

    :param template_code: 模板编码。
    :returns: 基准行；该模板没有随包基准时为空列表。
    """
    path = _DATA_DIR / f"concept_baselines_{template_code}.json"
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return list(doc.get("rows") or [])


def _fee_suggestions(req: SuggestRequest, warnings: list[dict]) -> tuple[list[dict], dict | None, list[str]]:
    """费率规则段。``fee[]`` 为空的两种原因各有各的 warning，绝不静默：没给基数 → ``fee_bases_absent``；
    费率规则引擎缺失 → ``fee_rules_unavailable``。两条都不等于「这个项目没有其他费用」。"""
    bases, derived_keys = estimate_checks.resolve_fee_bases(req.inputs, req.template_code, req.fee_bases, warnings)
    if not bases:
        warnings.append({
            "code": "fee_bases_absent",
            "cell": None,
            "message": (
                "请求未带 fee_bases，且无法从本次求值兜底（估概算总表!C5 工程费用合计"
                "为 0 或不可用，通常是 150 个成本位还一个都没填）；"
                "未调用费率规则引擎，5.工程建设其他费用 表的 13 个费用输入位本次不出"
                "建议值（fee[] 为空）。请先完成成本位，或在请求体带上 fee_bases"
                "（键名与单位见响应体 required_fee_bases）。"
            ),
        })
        return [], None, []
    try:
        # 必须走 importlib（O-02）：测试对 sys.modules 的打桩才生效
        fee_rules = importlib.import_module("zt.estimate.fee_rules")  # noqa: PLC0415
    except ImportError:
        warnings.append({
            "code": "fee_rules_unavailable",
            "cell": None,
            "message": "费率规则引擎尚未接入（zt.estimate.fee_rules 缺失），"
                       "本次不出其他费建议；这不代表该项目没有工程建设其他费用",
        })
        return [], bases, derived_keys
    out = fee_rules.suggest_all(bases, req.fee_attrs)
    warnings.extend(out.get("warnings") or [])
    return list(out.get("items") or []), bases, derived_keys


def _load_engine_module(name: str, what: str):
    """按需装载引擎模块；缺失抛 ZtError（旧版 501），绝不静默降级成空结果。"""
    try:
        return importlib.import_module(name)
    except ImportError as e:
        raise ZtError("engine_unavailable", f"{what}尚未实现（{name} 缺失：{e}）") from e


def _call_suggest(mod, req: SuggestRequest, fee_items: list[dict] | None, fee_bases_used: dict | None,
                  fee_attrs_used: dict | None, fee_bases_derived: list[str] | None) -> dict:
    """按引擎签名调用：不支持的参数不传并如实出 warning，不让 TypeError 打成内部错误。"""
    kwargs: dict = {"inputs": req.inputs, "baselines": req.baselines or [], "fee_items": fee_items,
                    "template_code": req.template_code, "dims": req.dims}
    extra_warnings: list[dict] = []
    params = inspect.signature(mod.suggest).parameters
    if req.items:
        if "items" in params:
            kwargs["items"] = req.items
        else:
            extra_warnings.append({"code": "items_unsupported", "cell": None,
                                   "message": "本版 estimate_suggest 不接受 items 参数，item_code 回链已跳过"})
    if "fee_bases" in params:
        kwargs["fee_bases"] = fee_bases_used
    elif fee_bases_used:
        extra_warnings.append({"code": "fee_bases_unsupported", "cell": None,
                               "message": "本版 estimate_suggest 不接受 fee_bases 参数，"
                                          "required_fee_bases 的 satisfied 标记已跳过"})
    if "fee_bases_derived" in params:
        kwargs["fee_bases_derived"] = list(fee_bases_derived or [])
    if "fee_bases_derivable" in params:
        kwargs["fee_bases_derivable"] = list(DERIVABLE_FEE_BASES)
    if "fee_attrs" in params:
        kwargs["fee_attrs"] = fee_attrs_used
    elif fee_attrs_used:
        extra_warnings.append({"code": "fee_attrs_unsupported", "cell": None,
                               "message": "本版 estimate_suggest 不接受 fee_attrs 参数，"
                                          "required_fee_attrs 的 satisfied 标记已跳过"})
    result = mod.suggest(**kwargs)
    if extra_warnings:
        result.setdefault("warnings", []).extend(extra_warnings)
    return result


def suggest(body: Any) -> dict:
    """正向推算：基准单方指标 × 规模 → 各成本输入位的**建议**金额（全确定性，零模型）。

    纯查询，不套必填闸：根输入没填全的后果是数量推不出来，逐条落 unresolved(no_quantity)。

    :param body: :class:`SuggestRequest` 字典。
    :returns: 与旧 ``EstimateSuggestOut`` 同形（去掉 usage）。
    :raises ZtError: 请求不合法、模板不存在、inputs 非数值。
    """
    req = parse(SuggestRequest, body)
    warnings: list[dict] = []
    suggest_mod = _load_engine_module("zt.estimate.suggest", "概算正向推算引擎")
    try:
        fee_list, fee_bases_used, fee_bases_derived = _fee_suggestions(req, warnings)
        fee_items = fee_list or None
        # WS10-P11：汇总型费率（C6 / C9 小计）与用户已填子项对账；只报数，不给子项分配金额（铁律 3）
        aggregate = estimate_checks.aggregate_checks(fee_list, req.inputs, warnings)
        result = _call_suggest(suggest_mod, req, fee_items, fee_bases_used, req.fee_attrs, fee_bases_derived)
    except EstimateTemplateError as e:
        raise _bad_request(e) from e
    warnings.extend(result.get("warnings") or [])
    return {
        "suggestions": result.get("suggestions") or [],
        "unresolved": result.get("unresolved") or [],
        "fee": result.get("fee") or fee_items or [],
        "coverage": result.get("coverage") or {},
        "totals": result.get("totals") or {},
        "required_fee_bases": result.get("required_fee_bases") or [],
        "required_fee_attrs": result.get("required_fee_attrs") or [],
        "warnings": warnings,
        "aggregate_checks": aggregate,
        # 偏离阈值单点下发（O-22）：每条 suggestion 的 range 按它算
        "tolerance": getattr(suggest_mod, "DEFAULT_TOLERANCE", None),
    }


# ------------------------------------------------------------------ compute

def _indicators_with_slot_labels(template_code: str, indicators: list[dict], slot_labels: dict | None) -> list[dict]:
    """「经济技术指标」行的名称套用归位时起的单体名（WS29-q）：数值、序号、单位一律不动。"""
    if not slot_labels:
        return indicators
    tech = next((s for s in load_template(template_code)["sheets"] if s["name"] == "经济技术指标"), None)
    if tech is None:
        return indicators
    rows = [r["row"] for r in tech["rows"] if r["role"] == "row"]
    if len(rows) != len(indicators):  # 求值器换了生成口径：宁可不改名，也不按错位的行改
        return indicators
    out = []
    for row_no, ind in zip(rows, indicators):
        label = slot_labels.get(f"经济技术指标!D{row_no}")
        out.append(dict(ind, label=label) if label else ind)
    return out


def compute(body: Any) -> tuple[dict, Optional[bytes]]:
    """确定性求值 + xlsx 渲染。零模型 —— 金额一分钱都不经过模型（铁律 2）。

    拦截闸顺序（测试钉死）：必填 → P04 面积闸 → P05 面积对账（可带理由确认放行）→ 全零。面积闸必须在全零闸
    之前：总建筑面积为 0 时室外成本仍让 C47 ≠ 0。

    :param body: :class:`ComputeRequest` 字典。
    :returns: ``(结果, xlsx 字节或 None)``；结果与旧 ``EstimateComputeOut`` 同形（去掉 usage 与 xlsx_base64）。
    :raises GateRejected: 某道闸拒算。
    :raises ZtError: 请求不合法、模板不存在、inputs 非数值、渲染器缺失或渲染失败。
    """
    req = parse(ComputeRequest, body)
    try:
        required = _required_input_cells(req.template_code)
    except EstimateTemplateError as e:
        raise _bad_request(e) from e

    # 必填闸写在接线层、不写在引擎（契约裁决 C）：run() 对缺失输入位按 0 计（Excel 空格语义）
    supplied = {k.replace("$", "") for k in (req.inputs or {})}
    gate = estimate_gates.required(required, supplied)
    if gate is not None:
        raise GateRejected(gate.code, gate.message)

    pol = estimate_policy.load_policy(req.template_code)
    try:
        area_checks, acks, slot_labels = estimate_checks.check_area_context(
            req.area_checks, req.acknowledged_checks, req.slot_labels, pol)
        input_sources, fee_bases, fee_attrs, profile, generated_at = estimate_checks.check_output_context(
            req.input_sources, req.fee_bases, req.fee_attrs, req.project_profile, req.generated_at)
    except ValueError as e:
        raise _bad_request(e) from e

    try:
        result = estimate_run(req.inputs, req.template_code, req.rates)
    except EstimateTemplateError as e:
        raise _bad_request(e) from e

    absent = estimate_gates.area_gate_absent(pol)
    if absent is not None:
        result["warnings"].append(absent)
    gate = estimate_gates.area_gate(pol, result)
    if gate is not None:
        raise GateRejected(gate.code, gate.message)
    gate = estimate_gates.area_reconcile(pol, result, area_checks)
    if gate is not None:
        reason = acks.get(gate.code)
        if reason is None:
            raise GateRejected(gate.code, gate.message)
        result["warnings"].append(estimate_gates.mismatch_acknowledged(gate, reason))

    # 可选输入位未填的静默污染必须披露；比值型输入位的标度哨兵；成本位覆盖率披露
    result["warnings"].extend(estimate_checks.missing_optional_warnings(req.template_code, supplied))
    result["warnings"].extend(estimate_checks.ratio_scale_warnings(req.template_code, req.inputs))
    input_coverage, coverage_warnings = estimate_checks.input_coverage(req.template_code, supplied)
    result["warnings"].extend(coverage_warnings)

    # 全零闸：披露解决「少算了却不说」，闸解决「全没算却报成功」
    gate = estimate_gates.all_zero(result)
    if gate is not None:
        raise GateRejected(gate.code, gate.message)

    result["warnings"].extend(estimate_checks.land_cost_warnings(pol, supplied))
    result["warnings"].extend(estimate_checks.footprint_warnings(pol, result))

    fee_items, fee_derived, fee_signoff = estimate_checks.fee_rerun(req.inputs, req.template_code, fee_bases, fee_attrs)
    result["warnings"].extend(estimate_quality.stale_fee_warnings(
        fee_items, req.inputs, input_sources, estimate_quality.fee_stale_tolerance(pol)))
    aggregate = estimate_checks.aggregate_checks(fee_items, req.inputs, result["warnings"])
    reference = estimate_quality.reference_comparison(
        profile.get(estimate_checks.REFERENCE_COST_KEY),
        (result["totals"].get("static_total") or {}).get("value"), pol)
    quality = estimate_quality.judge_quality(
        coverage=input_coverage, warnings=result["warnings"], input_sources=input_sources,
        supplied=supplied, fee_signoff_kind=fee_signoff, policy=pol, reference=reference)

    xlsx_bytes = None
    if req.render:
        try:
            estimate_render = importlib.import_module("zt.estimate.render")  # noqa: PLC0415
        except ImportError as e:
            # 调用方明确要了文件，拿不到就必须知道拿不到（旧版 501）
            raise ZtError("renderer_unavailable", "xlsx 渲染器尚未实现（zt.estimate.render 缺失）",
                          hint="只要数值可用 render=false 重试") from e
        tpl = load_template(req.template_code)
        order = [i["cell"] for i in tpl["inputs"]] + list(tpl.get("optional_inputs", []))
        notes = {
            "generated_at": generated_at, "quality": quality, "input_coverage": input_coverage,
            "warnings": list(result["warnings"]), "input_sources": input_sources,
            "supplied": [c for c in order if c in supplied], "acks": acks,
            "fee_basis": estimate_quality.fee_basis_texts(fee_items, fee_derived),
            "aggregate_checks": aggregate, "project_profile": profile,
        }
        try:
            full = getattr(estimate_render, "render_estimate", None)
            if full is not None:
                rendered = full(req.inputs, req.rates, req.template_code, req.project_name,
                                slot_labels or None, notes=notes, values=result["sheets"])
                xlsx_bytes = rendered.xlsx
                result["warnings"].extend(rendered.warnings)
            else:  # 老版渲染器：照旧出表，只是没有生成说明与缓存值
                xlsx_bytes = estimate_render.render(req.inputs, req.rates, req.template_code, req.project_name,
                                                    slot_labels or None)
        except EstimateTemplateError as e:
            raise _bad_request(e) from e
        except Exception as e:  # noqa: BLE001 —— 渲染失败转错误 JSON，不出半份文件
            raise ZtError("render_failed", f"概算 xlsx 渲染失败：{e}") from e

    out = {
        "sheets": result["sheets"],
        "totals": result["totals"],
        "indicators": _indicators_with_slot_labels(req.template_code, result["indicators"], slot_labels),
        "input_coverage": input_coverage,
        "rates_used": result.get("rates_used", {}),
        "warnings": result["warnings"],
        "quality": quality,
        "aggregate_checks": aggregate,
    }
    return out, xlsx_bytes


# ------------------------------------------------------------------ template

@lru_cache(maxsize=4)
def _template_payload(template_code: str) -> dict:
    """裁剪后的模板元数据：去掉 515 条 formulas 与 sheet 级渲染元数据（那是渲染器的输入）。"""
    tpl = load_template(template_code)
    meta = {i["cell"]: i for i in tpl["inputs"]}
    for spec in copy.deepcopy(list(estimate_checks.optional_input_specs(template_code))):
        meta.setdefault(spec["cell"], spec)
    opt_cells = set(tpl.get("optional_inputs", []))
    by_row: dict[tuple[str, int], list[dict]] = {}
    for cell, m in meta.items():
        sheet, coord = cell.split("!", 1)
        col = "".join(ch for ch in coord if ch.isalpha())
        row_no = int("".join(ch for ch in coord if ch.isdigit()))
        by_row.setdefault((sheet, row_no), []).append(
            {"col": col, "cell": cell, "kind": m.get("kind"), "label": m.get("label"), "unit": m.get("unit"),
             "column_label": m.get("column_label"), "optional": cell in opt_cells})
    for v in by_row.values():
        v.sort(key=lambda x: x["col"])
    sheets = []
    for s in tpl["sheets"]:
        rows = []
        for r in s["rows"]:
            cells = by_row.get((s["name"], r["row"]), [])
            rows.append({"row": r["row"], "role": r["role"], "seq": r["seq"], "level": r["level"],
                         "label": r["label"], "static": r.get("static") or {}, "editable": bool(cells),
                         "input_kind": cells[0]["kind"] if cells else None, "input_cells": cells})
        sheets.append({"name": s["name"], "rows": rows})
    return {
        "template_code": tpl["template_code"],
        "template_version": tpl["template_version"],
        "row_tree_levels": tpl["row_tree_levels"],
        "sheets": sheets,
        "inputs": tpl["inputs"],
        "optional_inputs": tpl.get("optional_inputs", []),
        "optional_input_specs": copy.deepcopy(list(estimate_checks.optional_input_specs(template_code))),
        "rate_params": tpl.get("rate_params", {}),
        "required_inputs": _required_input_cells(template_code),
        "fixes": tpl.get("fixes", []),
        "code_dictionary": warning_codes.payload(),
        "policy": estimate_policy.public_payload(template_code),
    }


def template(template_code: str = "gsyz_v1") -> dict:
    """模板元数据（行树 + 输入位 + 告警码字典 + 策略）。出口 deepcopy，调用方原地改不污染缓存。

    :param template_code: 模板编码。
    :returns: 元数据。
    :raises ZtError: 模板不存在。
    """
    try:
        return copy.deepcopy(_template_payload(template_code))
    except EstimateTemplateError as e:
        raise _bad_request(e) from e
