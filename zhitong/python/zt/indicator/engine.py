# 来源：engine-service/app/engine/indicator_engine.py（zhitong-cost-ai@991ff5cd，W2 搬入 zt；改动见本文件内「zt 改动」注释）
"""指标计算引擎 —— indicator/calc 端点的引擎层。

核心算法 `compute_indicators()` / `match_similar()` 移植自素材仓
`app/engine/indicator.py`（本身无 DB 耦合,纯函数,原样搬运,未改动一行算法逻辑)。
`run()` 是本服务新写的接线层。

指标(工程造价惯例):
- 单方造价(元/㎡) = 总造价 / 建筑面积。
- 专业/分部占比 = 各章合价 / 总造价。
- 造价驱动项 = 合价 Top-N。
- 类似项目对标:同建筑类型 + 结构相近 + 面积相近 → 相似度打分,给单方造价对标。
纯 Python,确定可复算。

能力边界(如实标注,详见 README):
- `price_files` 用 costsheet 解析后**合并**成一份清单明细,不识别 WBS(单体/楼栋)归属
  ——素材仓的计价表本身不带 WBS 字段,无法把某一行清单明细"拆"给某个 wbs_unit。
- 因此严格意义的"分单体指标"未实现。旧版按 wbs_units 面积占比对整体单方造价做「分摊」
  (unit_cost_area_share)——每个单体都是同一个值，没有信息量，D41 已删；面积只用项目总建筑面积
  (Java 传用户填写值或各 WBS 单元面积之和)。
- `baseline` 支持两种对标输入:
  1. `indicator_baselines: {indicator_code: value}` —— 直接给某个指标的对标基准,
     用来算 deviation(如 `{"unit_cost": 3200}` 对比"单方造价"实际值)。
  2. `peer_library: [...]`（同 `match_similar()` 的 library 参数,需含
     building_type/structure/gross_area/unit_cost 等字段)+ baseline 自身的
     building_type/structure/gross_area —— 用来算同类项目对标偏差
     (indicator_code=`peer_avg_unit_cost`)。
  两者都缺省时,只输出不带 baseline_value/deviation 的原始指标值。
"""
from __future__ import annotations

from zt.code_registry import registry as code_registry
from zt.costsheet.parser import (FEE_BREAKDOWN_ITEMS, FEE_BREAKDOWN_SUBITEMS, FEE_TOTAL_TOL_CENTS,
                                  basis_columns_text, parse_costsheet, to_cents)
from zt.costsheet.warning_codes import warn


def _f(x) -> float:
    return float(x) if isinstance(x, (int, float)) else 0.0


def compute_indicators(items: list[dict], meta: dict | None = None) -> dict:
    """items = costsheet.parse 的明细;meta 可含 gross_area/total_amount/building_type/structure。"""
    meta = meta or {}
    total = round(sum(_f(i.get("amount")) for i in items), 2)
    # 甲方口径总造价优先用外部录入(含措施/规费/税金),否则用清单明细合计
    total_cost = _f(meta.get("total_amount")) or total
    area = _f(meta.get("gross_area"))

    # 章节(专业/分部)占比 —— 一律用 code_registry.classify_chapter 现算（WS08-06）：
    # 与 costsheet 给 item 打章、对账、投控是**同一个函数**，所以同一条清单在三个端点章名相同。
    # 不采信 item 自带的 chapter_name 字段本身（外部调用方可能塞别的口径），但用 item 的
    # section：无编码行、补充码只能靠所在分部标题归章。
    ch: dict[str, dict] = {}
    for it in items:
        ref = code_registry.classify_chapter(it.get("code", ""), it.get("section"))
        d = ch.setdefault(
            ref.key,
            {
                "chapter": ref.key,
                "chapter_name": ref.name,
                "amount": 0.0,
                "count": 0,
            },
        )
        d["amount"] += _f(it.get("amount")); d["count"] += 1
    for d in ch.values():
        d["amount"] = round(d["amount"], 2)
        # 总额为 0 时占比给 null 不给 0（WS08-04）：0% 读起来像「这一章没花钱」
        d["pct"] = round(d["amount"] / total, 4) if total else None
        d["unit_cost"] = round(d["amount"] / area, 2) if (area and total) else None
    chapters = sorted(ch.values(), key=lambda x: -x["amount"])
    # 章名重名（市政 0401 与房建 0101 都叫「土石方工程」）时 label 带章码（WS08-06）
    code_registry.unique_chapter_labels(chapters)

    top = sorted(items, key=lambda i: -_f(i.get("amount")))[:15]
    top_items = [{"code": i.get("code", ""), "name": i.get("name", ""),
                  "unit": i.get("unit", ""), "amount": round(_f(i.get("amount")), 2),
                  "pct": round(_f(i.get("amount")) / total, 4) if total else None} for i in top]

    return {
        "total_amount": total_cost,
        "parsed_total": total,
        "item_count": len(items),
        "gross_area": area or None,
        # 总额为 0 时单方造价给 null（WS08-04）：旧版无价清单算出「单方造价 0.0」还返回 200
        "unit_cost": round(total_cost / area, 2) if (area and total_cost) else None,
        "unit_cost_itemized": round(total / area, 2) if (area and total) else None,
        "cost_basis": "full" if _f(meta.get("total_amount")) else "itemized",
        "chapters": chapters,
        "chapter_coverage": code_registry.chapter_coverage(items),
        "top_items": top_items,
    }


def _sim(a: dict, b: dict) -> float:
    """两项目相似度 0..1:建筑类型 0.5 + 结构 0.2 + 面积相近 0.3。"""
    s = 0.0
    bt_a, bt_b = (a.get("building_type") or "").strip(), (b.get("building_type") or "").strip()
    if bt_a and bt_a == bt_b:
        s += 0.5
    st_a, st_b = (a.get("structure") or "").strip(), (b.get("structure") or "").strip()
    if st_a and st_a == st_b:
        s += 0.2
    ar_a, ar_b = _f(a.get("gross_area")), _f(b.get("gross_area"))
    if ar_a and ar_b:
        s += 0.3 * (1 - min(1.0, abs(ar_a - ar_b) / max(ar_a, ar_b)))
    return round(s, 4)


def match_similar(target: dict, library: list[dict], top_n: int = 5) -> dict:
    """target 与 library(历史项目指标记录)对标。返回相似项目 + 单方造价对标。"""
    tid = target.get("project_id")
    scored = []
    for p in library:
        if p.get("project_id") == tid:
            continue
        sc = _sim(target, p)
        if sc <= 0:
            continue
        scored.append({
            "project_id": p.get("project_id"), "name": p.get("name", ""),
            "building_type": p.get("building_type", ""), "structure": p.get("structure", ""),
            "gross_area": p.get("gross_area"), "unit_cost": p.get("unit_cost"),
            "total_amount": p.get("total_amount"), "similarity": sc,
        })
    scored.sort(key=lambda x: -x["similarity"])
    peers = scored[:top_n]

    # 对标一律用"明细合计口径"单方造价(同基),避免含税/裸清单口径差被误报为造价偏高低
    def _uc(p):
        return p.get("unit_cost_itemized") if p.get("unit_cost_itemized") is not None else p.get("unit_cost")

    ucs = [_uc(p) for p in peers if _uc(p)]
    peer_avg = round(sum(ucs) / len(ucs), 2) if ucs else None
    t_uc = _uc(target)
    deviation = None
    if t_uc and peer_avg:
        deviation = round((t_uc - peer_avg) / peer_avg, 4)  # 本项目相对同类均值偏差(同口径)
    return {
        "peers": peers,
        "benchmark": {
            "target_unit_cost": t_uc,
            "peer_avg_unit_cost": peer_avg,
            "deviation": deviation,           # >0 偏高,<0 偏低
            "peer_count": len(peers),         # 匹配到的相似项目总数
            "avg_sample_count": len(ucs),     # 真正参与均值的项目数(用于"相对同类均值(N个)")
            "cost_basis": "itemized",
        },
    }


class ParseFailed(RuntimeError):
    """zt：接线层（zt.costsheet.service.parse_failed）把它转成 status=insufficient，detail() 原样放进 data.detail。

    全部 price_files 均解析不出清单行 / 全部无价 / 可计入文件不到所选的一半（D40）。

    WS26-e：422 的 detail 与投控、对账同一个对象形状（detail()）；指标没有口径可选，不带 reason_code。"""

    def __init__(self, message: str, *, reason_code: str | None = None):
        super().__init__(message)
        self.message = message
        self.reason_code = reason_code

    def detail(self) -> dict:
        return {"message": self.message, "reason_code": self.reason_code, "hint": None,
                "basis_requested": "contract", "basis_available": [], "files": []}


# 可计入文件数低于所选文件数的这个比例 → 整次判失败（D40：不再「16 份一份没读进、用一张估算表算出
# 单方 0.04 元/㎡ 还返回 200」）
_MIN_USABLE_RATIO = 0.5
# 两份文件叶子行签名重合超过这个比例 → file_overlap_suspect（只提示，同构楼栋可能真是同一份清单）
_OVERLAP_RATIO = 0.9

# 总造价口径（WS08-16）：标签随口径生成。旧版无论取没取到费用表都标「含税总造价口径」，
# 实际只是分部分项+措施明细合计，比含税控制价系统性偏低 10%–13%。
# WS26-h（实测 07-012）：itemized 的标签不再写死「分部分项+措施」——生产那份控制价的措施表一张没读进，
# 标签却写着「+措施」，数只有控制价的 58.2%。按实际读到的表生成，见 itemized_label。
COST_BASIS_LABELS = {
    "fee_table": "含规费税金，取自费用表",
    "user_input": "用户录入",
}
ITEMIZED_WITH_MEASURE = "分部分项+措施清单合计口径"
ITEMIZED_NO_MEASURE = "分部分项清单合计口径(未含措施项目、规费、税金)"


def itemized_label(has_measure: bool, measure_unread: int = 0) -> str:
    """WS26-p：技术措施表有读进来的、也有和费用表勾稽不过没计入的 → 写出没计入的张数，不说成措施都在里面。"""
    if not has_measure:
        return ITEMIZED_NO_MEASURE
    return ITEMIZED_WITH_MEASURE + (f"(技术措施 {measure_unread} 张表未计入)" if measure_unread else "")


def itemized_missing(has_measure: bool) -> str:
    """清单明细合计没算进去的是哪几块（回落时写在卡片和告警里）。"""
    return ("措施费里没读入的部分" if has_measure else "措施项目费") + "、其他项目费、规费、税金"


# summary.fee_total_checks 里每份文件带出的采用依据（costsheet.resolve_fee_total 的结果，去掉命中行原文）
_FEE_CHECK_KEYS = ("source", "has_fee_sheet", "project_total", "unit_sum", "unit_count",
                   "single_sum", "single_count", "specialty_sum", "specialty_count", "diff", "reason")


def _money(v: float) -> str:
    return f"{v:,.2f}"


def _list_sums(parsed: dict) -> dict:
    """一份文件读入的清单，按费用表的两项拆开（WS26-h2，与费用构成表勾稽用）：措施表（表名或标题带「措施」）
    里的行算技术措施，其余算分部分项。技术措施表有没读进来的（跳过、勾稽不过）就不给技术措施这一项——
    读了一部分的和拿去比，只会报一个假的差额。

    tol：两边允许差多少（分）。清单合价全是整元时，是软件把每行合价取整后导出的，费用表那一格却是按到分的
    数量 × 单价算的，逐行取整最多差 0.5 元（与 WS26-p 措施表勾稽同一个算法：0.5 × 行数 + 0.5 元，再不小于
    1 元）；有一行带角分就不是取整导出，按 1 元。样本库 41 行取整清单与费用表差 2.87 元就是这一类。"""
    details = parsed["meta"].get("sheets_detail") or []
    measure = {d["sheet"] for d in details if d.get("measure_sheet")}
    acc = {"fbfx": [0, 0, True], "measure_tech": [0, 0, True]}     # 分、行数、是否全是整元
    for it in parsed["items"]:
        c = to_cents(it.get("amount"))
        if c is None:
            continue
        a = acc["measure_tech" if it.get("sheet") in measure else "fbfx"]
        a[0] += c
        a[1] += 1
        a[2] = a[2] and c % 100 == 0

    def tol(key: str) -> int:
        _c, n, whole = acc[key]
        return max(FEE_TOTAL_TOL_CENTS, 50 * n + 50) if whole and n else FEE_TOTAL_TOL_CENTS

    cov = parsed["meta"].get("coverage") or {}
    complete = bool(cov.get("measure_used")) and not (cov.get("measure_skipped") or {}).get("sheets")
    return {"fbfx": acc["fbfx"][0], "fbfx_tol": tol("fbfx"),
            "measure_tech": acc["measure_tech"][0] if complete else None, "measure_tech_tol": tol("measure_tech")}


def _fee_breakdown(entries: list, *, many: bool, cost_basis: str, total_cost, warn_fn) -> dict:
    """费用构成表（WS26-h2，spec §3.17 第 5 条）：各文件的单位工程费用表分项之和，各项占构成表合计的比例。

    每份计入的文件都拆得开（costsheet.resolve_fee_breakdown）才显示；任一份拆不开整张不显示，reason 写原因。
    表自己对不上（某张单位工程表各项相加 ≠ 合计）出 fee_breakdown_unreconciled（info）；
    费用表的分部分项 / 技术措施与读入的清单对不上出 fee_itemized_mismatch（warn）——WS26-h 评审留给本片的
    「费用表合计不与清单明细勾稽」：只改了清单、费用表没重算时，总造价仍取自费用表（如实），但要说出来。"""
    fb = {"available": False, "reason": None, "unit_count": 0, "total": None, "rows": [], "notes": [],
          "itemized_check": []}
    prefix = (lambda f: f"「{f}」") if many else (lambda f: "")
    missing = [ft for ft in entries if not (ft["breakdown"] or {}).get("available")]
    if not entries or missing:
        fb["reason"] = "；".join(prefix(ft["file"]) + ((ft["breakdown"] or {}).get("reason") or "没有单位工程费用表")
                                for ft in missing) or "没有计入的文件"
        for ft in missing:
            if (ft["breakdown"] or {}).get("unreconciled"):
                warn_fn("fee_breakdown_unreconciled",
                        f"费用构成表没有显示：{prefix(ft['file'])}{ft['breakdown']['reason']}"
                        "（构成表只是把合计拆开看，总造价的取数不受影响）", file=ft["file"])
        return fb
    bds = [ft["breakdown"] for ft in entries]
    total = sum(to_cents(b["total"]) for b in bds)

    def summed(part: str, key: str):
        vals = [to_cents(b[part][key]) for b in bds if key in b[part]]
        return sum(vals) if vals else None

    def label(key: str, name: str) -> str:
        got = []
        for b in bds:
            for lab in (b.get("labels") or {}).get(key, "").split("/"):
                if lab and lab not in got:
                    got.append(lab)
        return "/".join(got) or name

    rows = []
    for key, name, _labs in FEE_BREAKDOWN_ITEMS:
        c = summed("items", key)
        rows.append({"key": key, "label": label(key, name), "amount": None if c is None else c / 100,
                     "pct": None if c is None or not total else round(c / total, 4), "level": 0})
        if key == "other":
            for sk, sname, _sl in FEE_BREAKDOWN_SUBITEMS:
                c = summed("subs", sk)
                rows.append({"key": sk, "label": f"其中：{label(sk, sname)}", "amount": None if c is None else c / 100,
                             "pct": None if c is None or not total else round(c / total, 4), "level": 1})
    fb.update(available=True, unit_count=sum(b["unit_count"] for b in bds), total=total / 100, rows=rows)
    gap = None if total_cost is None else to_cents(total_cost) - total
    if gap:
        who = "手填的总造价" if cost_basis == "user_input" else "总造价"
        fb["notes"].append(f"构成表合计与{who} {_money(total_cost)} 相差 {_money(abs(gap) / 100)} 元"
                           + ("（总造价取的是项目级合计，见总造价卡片的提示行）" if cost_basis == "fee_table" else ""))

    for ft in entries:
        items, ls = ft["breakdown"]["items"], ft["list_sums"]
        fee_f = to_cents(items.get("fbfx")) or 0
        fee_t = to_cents(items.get("measure_tech")) if "measure_tech" in items else None
        d_f = ls["fbfx"] - fee_f
        d_t = None if ls["measure_tech"] is None or fee_t is None else ls["measure_tech"] - fee_t
        fb["itemized_check"].append({
            "file": ft["file"], "fee_fbfx": fee_f / 100, "list_fbfx": ls["fbfx"] / 100, "fbfx_diff": d_f / 100,
            "fee_measure_tech": None if fee_t is None else fee_t / 100,
            "list_measure_tech": None if ls["measure_tech"] is None else ls["measure_tech"] / 100,
            "measure_tech_diff": None if d_t is None else d_t / 100})
        parts = []
        if abs(d_f) > ls["fbfx_tol"]:
            parts.append(f"费用表里的分部分项工程费 {_money(fee_f / 100)}，读入的分部分项清单合计 "
                         f"{_money(ls['fbfx'] / 100)}，相差 {_money(abs(d_f) / 100)} 元")
        if d_t is not None and abs(d_t) > ls["measure_tech_tol"]:
            parts.append(f"费用表里的施工技术措施项目 {_money(fee_t / 100)}，读入的技术措施清单合计 "
                         f"{_money(ls['measure_tech'] / 100)}，相差 {_money(abs(d_t) / 100)} 元")
        if parts:
            warn_fn("fee_itemized_mismatch",
                    prefix(ft["file"]) + "；".join(parts) + "。两者对不上：可能有清单行没读进来，也可能费用表不是按"
                    "这份清单算的（清单改过、费用表没重算），请核对"
                    + ("；总造价取自费用表，不随清单变化" if cost_basis == "fee_table" else ""), file=ft["file"])
    return fb


def _sig(it: dict) -> tuple:
    return (it.get("code_norm") or it.get("name") or "", it.get("unit") or "", it.get("qty"),
            it.get("price"), it.get("amount"))


def run(price_files: list[tuple], baseline: dict | None, wbs_units: list[dict] | None = None, *,
        gross_area: float | None = None, total_amount: float | None = None,
        area_source: str | None = None) -> dict:
    """接线层:price_files (bytes, filename[, file_id]) 列表 → 契约形状的指标结果。

    WS08-01：指标按合同价口径解析（side=None、basis=contract、require_gb_code=True）——
    国标编码行不到一半的表（万元设备估算表、审核汇总表）不参与。
    WS08-04：无价文件剔除并出 file_unpriced；全部被剔除 → ParseFailed（422）。
    WS08-14：面积由调用方给（用户填写 / WBS 各单元之和），没有面积单方给 null 并出 area_missing；
             删掉了按面积占比分摊的近似行（D41）。wbs_units 参数保留兼容，不再参与计算。
    WS08-15：逐文件归类 parsed/unparsed/unpriced/non_list；同 sha256 的文件只计一份；
             可计入文件数 < 所选的 50% → ParseFailed（D40）。
    WS08-16：总造价口径 user_input > fee_table（每份文件都取到费用表合计）> itemized。
    WS26-h：费用表合计按层勾稽后才采用（costsheet.resolve_fee_total）；回落到清单明细合计时
             不叫「总造价」，口径标签按实际读到的表生成；有费用表却取不到 → fee_total_unreadable（warn）。
    """
    import hashlib

    baseline = baseline or {}
    items: list[dict] = []
    warnings: list[str] = []
    warning_items: list[dict] = []
    file_coverage: list[dict] = []
    files_used: list[str] = []
    files_failed: list[dict] = []
    unpriced: list[str] = []
    fee_totals: list[dict] = []
    seen_sha: dict[str, str] = {}
    sigs: dict[str, set] = {}
    selected = 0
    has_measure = False
    measure_unread = 0      # 勾稽不过、没计入的技术措施表张数（WS26-p）

    def _warn(code: str, msg: str, **kw) -> None:
        w = warn(code, msg, **kw)
        warning_items.append(w)
        warnings.append(w["message"])

    for f in price_files:
        raw, name = f[0], f[1]
        fid = f[2] if len(f) > 2 else None
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen_sha:
            _warn("file_duplicate", f"「{name}」与「{seen_sha[digest]}」内容完全相同，只计一份", file=name)
            continue
        seen_sha[digest] = name
        selected += 1
        parsed = parse_costsheet(raw, name, side=None, basis="contract", require_gb_code=True, file_id=fid)
        warnings.extend(f"{name}: {w}" for w in parsed["warnings"])
        warning_items.extend(parsed["warning_items"])
        cov = parsed["meta"]["coverage"]
        file_coverage.append(cov)
        if parsed["meta"].get("unpriced"):
            unpriced.append(name)
            _warn("file_unpriced", f"「{name}」疑似招标工程量清单（只有工程量、没有单价和金额），已剔除", file=name)
            continue
        if not parsed["items"]:
            status = cov.get("status") or "unparsed"
            statuses = {d.get("status") for d in parsed["meta"].get("sheets_detail") or []}
            if status == "non_list":
                reason = "不是国标清单表（估算表/汇总表/费用表等）"
            elif "basis_missing" in statuses:
                # WS26-e：指标按合同价口径取数，进度款表只有本期 / 累计列时说清楚，不笼统写「未识别」
                have = basis_columns_text(parsed["meta"].get("basis_available")) or "别的期次的金额列"
                reason = f"表头只有{have}，没有合同价或不分期的合价列（指标按合同价口径计算）"
            else:
                reason = "未识别到清单明细行"
            files_failed.append({"file": name, "file_id": fid, "status": status, "reason": reason})
            continue
        files_used.append(name)
        items.extend(parsed["items"])
        sigs[name] = {_sig(i) for i in parsed["items"]}
        details = parsed["meta"].get("sheets_detail") or []
        has_measure = has_measure or any(d.get("measure_sheet") and d.get("status") == "used" for d in details)
        measure_unread += sum(1 for d in details if d.get("status") == "measure_unreconciled")
        fee_totals.append({"file": name, "file_id": fid, "fee_total": parsed["meta"].get("fee_total"),
                           "hits": parsed["meta"].get("fee_totals") or [],
                           "check": parsed["meta"].get("fee_total_check") or {},
                           "breakdown": parsed["meta"].get("fee_breakdown"), "list_sums": _list_sums(parsed)})

    if files_failed:
        _warn("files_failed", "以下文件未计入：" + "；".join(f"{x['file']}（{x['reason']}）" for x in files_failed))
    if not files_used:
        if unpriced and not files_failed:
            raise ParseFailed("清单无单价/金额，无法计算单方造价等指标：" + "、".join(unpriced))
        failed = [x["file"] for x in files_failed] + unpriced
        raise ParseFailed("所选文件都没有可计入的清单（不是清单表或读不出清单行）：" + "、".join(failed))
    if len(files_used) < _MIN_USABLE_RATIO * selected:
        failed = [f"{x['file']}（{x['reason']}）" for x in files_failed] + [f"{n}（无单价/金额）" for n in unpriced]
        raise ParseFailed(f"所选 {selected} 份文件只有 {len(files_used)} 份可计入（不到一半），"
                          f"结果不能代表项目，未计算。未计入：" + "；".join(failed))

    names = list(sigs)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = sigs[names[i]], sigs[names[j]]
            if a and b and len(a & b) / min(len(a), len(b)) >= _OVERLAP_RATIO:
                _warn("file_overlap_suspect",
                      f"「{names[i]}」与「{names[j]}」的清单行 {len(a & b) / min(len(a), len(b)):.0%} 完全相同，"
                      "请确认没有把同一份清单选了两次（同构楼栋可能确实同清单，未自动剔除）")

    # —— 总造价口径（WS08-16 / WS26-h）——
    item_label = itemized_label(has_measure, measure_unread)
    cost_basis_notes: list[str] = []
    cost_basis_missing = None
    many = len(fee_totals) > 1
    user_total = total_amount if total_amount is not None else baseline.get("total_amount")
    if _f(user_total) > 0:
        cost_basis, total_cost_input = "user_input", _f(user_total)
        basis_label = COST_BASIS_LABELS[cost_basis]
    elif fee_totals and all(ft["fee_total"] is not None for ft in fee_totals):
        cost_basis = "fee_table"
        total_cost_input = round(sum(ft["fee_total"] for ft in fee_totals), 2)
        if all(ft["check"].get("source") == "unit_sum" for ft in fee_totals):
            # 没有项目级合计、用各单位工程表相加得到的：标签说清楚是相加出来的，不说成「取自费用表」的某一格
            basis_label = f"各单位工程费用表合计之和({sum(ft['check'].get('unit_count') or 0 for ft in fee_totals)} 张)"
        else:
            basis_label = COST_BASIS_LABELS[cost_basis]
        for ft in fee_totals:
            cost_basis_notes.extend((f"「{ft['file']}」" if many else "") + n for n in ft["check"].get("notes") or [])
    else:
        # 回落：这个数是清单明细合计，不是总造价（铁律 3：取不到就说取不到，不拿别的数顶上「总造价」的名字）
        cost_basis, total_cost_input, basis_label = "itemized", None, item_label
        cost_basis_missing = itemized_missing(has_measure)
        tail = f"本次只算出清单明细合计，不是总造价，没有算进{cost_basis_missing}"
        unreadable = [ft for ft in fee_totals if ft["fee_total"] is None and ft["check"].get("has_fee_sheet")]
        absent = [ft["file"] for ft in fee_totals if ft["fee_total"] is None and not ft["check"].get("has_fee_sheet")]
        for ft in unreadable:
            _warn("fee_total_unreadable",
                  f"「{ft['file']}」里有费用表，但没有取到可以采用的合计：{ft['check'].get('reason') or '原因不明'}。"
                  f"{tail}；可在「含税总造价」里手填", file=ft["file"])
        if absent:
            _warn("fee_total_unavailable", "、".join(f"「{n}」" for n in absent)
                  + f"里没有费用表（或费用表里没有招标控制价/投标报价合计行）。{tail}")
    area = gross_area if gross_area is not None else baseline.get("gross_area")
    area = _f(area) if _f(area) > 0 else None
    if area is None:
        _warn("area_missing", "没有总建筑面积，单方造价与各章单方未计算；请在「指标计算」对话框里填写总建筑面积")

    meta = {"gross_area": area, "total_amount": total_cost_input,
            "building_type": baseline.get("building_type"), "structure": baseline.get("structure")}
    ind = compute_indicators(items, meta)

    indicator_baselines: dict = baseline.get("indicator_baselines") or {}

    def _bl(code: str, value: float | None) -> tuple[float | None, float | None]:
        bv = indicator_baselines.get(code)
        bv = _f(bv) if bv is not None else None
        dev = round((value - bv) / bv, 4) if (value is not None and bv) else None
        return bv, dev

    rows: list[dict] = []

    def _add(code: str, value, wbs_unit_id: str | None = None, label: str | None = None, **extra):
        bv, dev = _bl(code, value) if value is not None else (None, None)
        row = {"indicator_code": code, "value": value, "baseline_value": bv, "deviation": dev,
               "wbs_unit_id": wbs_unit_id}
        if label:
            row["label"] = label
        row.update(extra)
        rows.append(row)

    # 指标编码不变（Java 按编码落 cost_indicator_result）；回落时改的是名字：total_amount / unit_cost 两行
    # 此时装的是清单明细合计与按它算的单方，行名不许再叫「总造价」「单方造价」（WS26-h，07-012）
    itemized = cost_basis == "itemized"
    _add("total_amount", ind["total_amount"], kind="amount",
         label=f"清单明细合计(元,不是总造价;{basis_label})" if itemized else f"总造价(元,{basis_label})")
    _add("parsed_total", ind["parsed_total"], label="清单明细合计(元)", kind="amount")
    # 没有面积时单方造价行照出、值为 null，reason 说明为什么（WS08-14）：只是不出行，界面上看不出是没算
    _add("unit_cost", ind["unit_cost"], kind="unit_cost",
         label=(f"按清单明细合计算的单方(元/㎡,不是单方造价指标;{basis_label})" if itemized
                else f"单方造价(元/㎡,{basis_label})"),
         reason=None if ind["unit_cost"] is not None else "未提供总建筑面积")
    if not itemized:
        _add("unit_cost_itemized", ind["unit_cost_itemized"], label=f"按清单明细合计算的单方(元/㎡,{item_label})",
             kind="unit_cost", reason=None if ind["unit_cost_itemized"] is not None else "未提供总建筑面积")
    for c in ind["chapters"]:
        # chapter_name 额外落一份到指标行(而非只塞进 label 文案里),供下游按字段取用、不必解析 label。
        _add(f"chapter_pct:{c['chapter']}", c["pct"], label=f"{c['label']}占比",
             chapter_name=c["chapter_name"], kind="ratio")
        if c["unit_cost"] is not None:
            _add(f"chapter_unit_cost:{c['chapter']}", c["unit_cost"],
                 label=f"{c['label']}单方造价(元/㎡)", chapter_name=c["chapter_name"], kind="unit_cost")

    # peer 对标(仅当 baseline 提供 peer_library 且带自身画像字段时)
    peer_library = baseline.get("peer_library")
    if peer_library:
        target = {
            "project_id": baseline.get("project_id"),
            "building_type": baseline.get("building_type"),
            "structure": baseline.get("structure"),
            "gross_area": area,
            "unit_cost_itemized": ind["unit_cost_itemized"],
            "unit_cost": ind["unit_cost"],
        }
        sim = match_similar(target, peer_library)
        bm = sim["benchmark"]
        rows.append({
            "indicator_code": "peer_avg_unit_cost", "value": bm["target_unit_cost"],
            "baseline_value": bm["peer_avg_unit_cost"], "deviation": bm["deviation"],
            "wbs_unit_id": None, "label": "同类项目单方造价对标", "kind": "unit_cost",
            "peer_count": bm["peer_count"], "avg_sample_count": bm["avg_sample_count"],
        })

    fee_breakdown = _fee_breakdown(fee_totals, many=many, cost_basis=cost_basis,
                                   total_cost=ind["total_amount"] if cost_basis != "itemized" else None,
                                   warn_fn=_warn)

    cov = ind["chapter_coverage"]
    if cov is not None and cov < 0.8:
        _warn("chapter_coverage_low", f"来自标准章名表的金额占比 {cov:.2%}，其余归入补充项目/无编码项/非国标编号项")
    return {"indicators": rows, "chapters": ind["chapters"], "top_items": ind["top_items"],
            "fee_breakdown": fee_breakdown,
            "warnings": warnings, "warning_items": warning_items, "file_coverage": file_coverage,
            "files_used": files_used, "files_failed": files_failed, "files_selected": selected,
            "chapter_coverage": cov,
            "rows_parsed": sum(1 for i in items if i.get("amount")),
            "summary": {
                "total_amount": ind["total_amount"], "parsed_total": ind["parsed_total"],
                "cost_basis": cost_basis, "cost_basis_label": basis_label,
                # 只增字段（WS26-h）：卡片提示行（项目级合计 / 单位工程之和 / 差额）、清单明细合计的口径、
                # 回落时没算进去的是哪几块、每份文件的采用依据
                "cost_basis_notes": cost_basis_notes, "cost_basis_missing": cost_basis_missing,
                "itemized_basis_label": item_label,
                "fee_totals": [{"file": ft["file"], "file_id": ft["file_id"], "fee_total": ft["fee_total"]}
                               for ft in fee_totals],
                "fee_total_checks": [{"file": ft["file"], "file_id": ft["file_id"],
                                      **{k: ft["check"].get(k) for k in _FEE_CHECK_KEYS}} for ft in fee_totals],
                "gross_area": area, "area_source": (area_source or "request") if area else None,
                "unit_cost": ind["unit_cost"],
                "unit_cost_reason": None if ind["unit_cost"] is not None else "未提供总建筑面积",
                "files_selected": selected, "files_used": len(files_used), "files_failed": len(files_failed) + len(unpriced),
            }}
