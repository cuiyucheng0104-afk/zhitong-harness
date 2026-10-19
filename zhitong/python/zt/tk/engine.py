# 来源：engine-service/app/engine/tk_engine.py（zhitong-cost-ai@991ff5cd，W2 搬入 zt；改动见本文件内「zt 改动」注释）
"""投控异常检测引擎 —— tk/detect 端点的引擎层。

检测规则(v1 基础族 + v2 基准对齐族)移植自素材仓 `scripts/detect/engine.py`
（纯函数，不依赖 DB/Session）。规则阈值配置移植自素材仓 `config-seeds/tk_detect.yaml`
（打包为 `zt/tk/data/tk_detect.yaml`（旧仓 `app/engine/data/`），版本 `v1-20260711`，客户侧标注仍为 draft——
阈值是内部 train 集上调出的起点值，不是已与客户核对确认的最终值）。

DISPATCH 红线(素材仓原文档已声明,原样保留):
  - 引擎只产"疑似"+置信度,绝不落终态(review_status 恒为 pending,终判归造价师 HITL)。
  - 阈值全部来自配置,禁止硬编码。

v1 规则族(同项目内可判,不依赖外部基准):
  duplicate   重复计取(同项目+同期次+同单位工程内同编码，且组内至少 2 行金额非零)
  code_repeat 编码重复(数据质量)：同组里金额非零的不足 2 行，不判重复计取、severity 为 0
  zangu       暂估/暂定/暂列 且金额过线（WS26-n 分四档：只在项目特征里出现裸词的降为低置信，见 rule_zangu）
  self_check  |量×价 − 送审金额| 偏差超容差(行内自洽，只在量与金额同一期次组时判)
  big_amount  金额异常大(无基准档时粗筛,置信度最低)

v2 基准对齐规则族(用户勾选合同/中标清单文件后才跑；WS08-07 / D44):
  price_over_baseline  单价疑似超合同：送审单价 > 合同单价×(1+P%)
  qty_over_baseline    工程量疑似超合同：送审量 > 合同量×(1+Q%)
  missing_submit       送审量价金额全空 + 合同清单有该项且过线
  new_item             合同外新增：严格对齐不上 + 送审金额过线 + 基准覆盖率达标
  只有严格对齐（tk_align.EXACT）的行能出金额（铁律 3）；同码不同名/单位（CONFLICT）与合同清单里
  有多行可对、收窄后仍不唯一（AMBIGUOUS，WS26-m）的行进 alignment_issues，名称单位相同、特征或
  编码不同的候选进 align_suggestions，都不带金额。

异常身份（WS08-08）：(project_id, file_key, sheet, row)，file_key 取 file_id、没有时取文件名。
旧版只有 project|major|sheet|item_code：两份不同合同的清单行共用同一个 uid，复核结论会串到别的
期次；三份进度款合并检测只剩 44 条（分别检测 84 条）。
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import yaml

from zt.code_registry.registry import GB, normalize_code
from zt.costsheet.parser import basis_rejection, parse_costsheet, scope_label
from zt.costsheet.warning_codes import warn
from zt.tk.align import AMBIGUOUS, CONFLICT, EXACT, NEW_ITEM, SUGGEST, align_row, build_index

RULES_PATH = Path(__file__).resolve().parent / "data" / "tk_detect.yaml"
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
# 身份键版本前缀：换了身份口径就换前缀，新旧 uid 不可能碰巧相等（旧口径的已复核行在前端标「旧版口径」）
_UID_PREFIX = "tk2|"
_WS = re.compile(r"\s+")


def load_rules(path: Path | str = RULES_PATH) -> dict:
    # zt 改动：with 关文件（旧仓 open() 不关，Windows 上留句柄）
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _num(x) -> Optional[float]:
    """取不到就是 None（缺失的量/价/金额不写成 0）。"""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _norm(s) -> str:
    return _WS.sub("", str(s or "")).lower()


def _file_key(r: dict) -> str:
    return str(r.get("file_id") or r.get("source_file") or "").strip()


def _key(r: dict) -> tuple:
    """异常身份 = 折叠键：哪份文件、哪张表、第几行（WS08-08）。

    行号缺失（老调用方直接喂内存行、不带 row）时退到编码，保证同表不同编码的行不被折成一条。"""
    row = r.get("row")
    row_token = str(row) if row not in (None, "") else "code:" + str(r.get("item_code", "")).strip()
    return (str(r.get("project_id", "")).strip(), _file_key(r), str(r.get("sheet", "")).strip(), row_token)


def legacy_anomaly_id_v1(project_id: str, major: str, sheet: str, item_code: str) -> str:
    """D-H6c 第一版身份口径 uuid5(project|major|sheet|item_code) —— **只给历史迁移的回放对账用**。

    后端/sql/tk-anomaly-uid-20260830.sql 用 SQL 给存量行按这个口径重算 uid；
    后端/sql/tests/tk-anomaly-uid-replay.sh 调本函数把 SQL 与引擎锁在一起。
    新异常一律走 _key（WS08-08 的文件 + 表 + 行口径），不许再用它出 uid。"""
    return str(uuid.uuid5(_NS, "|".join(str(x or "").strip() for x in (project_id, major, sheet, item_code))))


# 主台只放"虚增核减";漏报/合同外新增/数据质量分流到低压力核对清单(severity 语义各异,混一张台不可信)
_LANE = {"missing_submit": "漏报核对", "new_item": "合同外新增", "code_repeat": "数据质量"}


def _lane_of(rule: str) -> str:
    return _LANE.get(rule, "虚增核减")


def _tier_of(rule: str, method) -> str:
    """置信分层:高=与合同清单严格对齐;中=确定性(重复/暂估/自洽);低=无基准硬猜。"""
    if method == EXACT:
        return "高"
    if rule in ("duplicate", "zangu", "self_check"):
        return "中"
    return "低"   # new_item / big_amount / code_repeat


def _mk(r: dict, rule: str, atype: str, *, reported, conf, line_amount=None, excess_amount=None,
        baseline=None, baseline_source=None, deviation_pct=None, severity=None, method=None,
        tier: Optional[str] = None, extra: Optional[dict] = None) -> dict:
    """一条异常。

    ⚠ anomaly_id 的指纹**只用 _key(r)，绝不含 rule** —— 它必须与 detect() 末尾的折叠键同粒度。
    指纹里任何跨轮次会变的字段（规则名、置信度、金额、期次…）都会让 Java 按 anomaly_uid 做的
    upsert 认不出同一条清单行：插一条新 pending，旧 confirmed 留在原地（D-H6c）。
    身份 = 哪条清单行；证据 = 这轮它为什么可疑。两者必须分开。

    金额口径（WS08-11）：line_amount = 送审行金额；excess_amount = 疑似超出部分（只有基准规则族有）。
    severity（Java 按它排序，列含义不变）取 excess_amount，没有时取 line_amount。
    """
    k = _key(r)
    if severity is None:
        severity = excess_amount if excess_amount is not None else line_amount
    a = {
        "anomaly_id": str(uuid.uuid5(_NS, _UID_PREFIX + "|".join(k))),
        "anomaly_type": atype,
        "subtype": rule,
        "workflow_lane": _lane_of(rule),
        "confidence_tier": tier or _tier_of(rule, method),
        "project_id": k[0],
        "file_id": r.get("file_id"),
        "source_file": r.get("source_file") or "",
        "sheet": k[2],
        "row": r.get("row"),
        "unit_project": r.get("unit_project") or k[2],
        "major": r.get("major", ""),
        "item_code": r.get("item_code", ""),
        "item_name": r.get("item_name", ""),
        "unit": r.get("unit", ""),
        "locator": {"project_id": k[0], "file_id": r.get("file_id"), "source_file": r.get("source_file") or "",
                    "sheet": k[2], "row": r.get("row"), "unit_project": r.get("unit_project") or k[2],
                    "item_code": r.get("item_code", "")},
        "reported_value": reported,
        "line_amount": line_amount,
        "excess_amount": excess_amount,
        "baseline_value": baseline,
        "baseline_source": baseline_source,
        "deviation_pct": deviation_pct,
        "confidence": conf,
        # WS26-c（P07）：取整到分。missing_submit 传进来的是没取整的基准金额，1234567.8900000001 这种
        # 18 个字符的值写不进 audit_tk_anomaly.severity（varchar(16)），整批落库会回滚
        "severity": round(abs(_f(severity)), 2),
        "review_status": "pending",
    }
    if extra:
        a.update(extra)
    a["detail"] = render_detail(a)
    return a


# ---------- 证据文案（WS08-11：每条规则一个模板，None 不进文案） ----------

def _money(v) -> Optional[str]:
    n = _num(v)
    return None if n is None else f"{n:,.2f}"


def _qty(v) -> Optional[str]:
    n = _num(v)
    return None if n is None else f"{n:,.4f}".rstrip("0").rstrip(".")


def _join(*parts) -> str:
    return "，".join(p for p in parts if p)


def _clause(fmt: str, *vals) -> Optional[str]:
    """只要有一个值是 None，这一句就整句不出 —— 旧版 f-string 直接插值，详情里出现「基准 None」。"""
    return None if any(v is None for v in vals) else fmt.format(*vals)


# 暂估命中在哪里（WS26-n，D-R164）。只有 feature_text 是弱命中（低置信、前端归「数据质量」）
ZANGU_PROVISIONAL = "provisional_amount"    # 清单表「其中：暂估价」列本行非零
ZANGU_NAME = "name"                          # 名称里有裸词
ZANGU_FEATURE_PRICE = "feature_price_word"   # 项目特征里有价款词
ZANGU_FEATURE_TEXT = "feature_text"          # 只在项目特征里出现裸词


def _zangu_clause(a: dict) -> Optional[str]:
    scope = a.get("marker_scope")
    if scope == ZANGU_PROVISIONAL:
        return _clause("清单表「暂估价」列本行 {}", _money(a.get("provisional_amount")))
    if scope == ZANGU_NAME:
        return _clause("名称命中「{}」", a.get("marker"))
    if scope == ZANGU_FEATURE_PRICE:
        return _clause("项目特征命中「{}」", a.get("marker"))
    if scope == ZANGU_FEATURE_TEXT:
        return _clause("项目特征里出现「{}」，不一定是暂估价", a.get("marker"))
    return _clause("文本命中「{}」", a.get("marker"))     # 改前的异常（没有 marker_scope）


def render_detail(a: dict) -> str:
    rule = a.get("subtype")
    head = f"{a.get('anomaly_type')}｜{a.get('item_name') or '（无名称）'}"
    code = _clause("编码 {}", a.get("item_code") or None)
    where = _clause("来源 {}·{}·第{}行", a.get("source_file") or None, a.get("sheet") or None, a.get("row"))
    line = _clause("送审金额 {}", _money(a.get("line_amount")))
    if rule == "duplicate":
        body = _join(_clause("{}内同编码 {} 行（金额非零的至少 2 行）", a.get("period_label") or "同文件同单位工程",
                             a.get("members_total") or len(a.get("members") or []) or None), line)
    elif rule == "code_repeat":
        body = _join(_clause("同编码 {} 行，其中金额非零的不足 2 行，按数据质量问题列出、不判重复计取",
                             a.get("members_total") or len(a.get("members") or []) or None))
    elif rule == "zangu":
        body = _join(_zangu_clause(a), line)
    elif rule == "self_check":
        body = _join(_clause("量 {} × 单价 {} = {}", _qty(a.get("qty")), _money(a.get("price")),
                             _money(a.get("calc_value"))),
                     _clause("与送审金额 {} 偏差 {}%", _money(a.get("line_amount")), a.get("deviation_pct")))
    elif rule == "big_amount":
        amt = _num(a.get("line_amount"))
        if amt is not None and amt < 0:
            # WS26-n（P24，TK-C04）：判定用的是绝对值；带负号的原值写在「≥」左边字面不成立。原值照写，对得上原表
            body = _join(_clause("送审金额 {}", _money(amt)),
                         _clause("绝对值 {} ≥ 大额线 {}", _money(abs(amt)), _money(a.get("threshold"))),
                         "金额为负，请核对是否冲减项")
        else:
            body = _join(_clause("送审金额 {} ≥ 大额线 {}", _money(a.get("line_amount")), _money(a.get("threshold"))))
    elif rule == "price_over_baseline":
        body = _join(_clause("送审单价 {} > 合同单价 {}", _money(a.get("reported_value")), _money(a.get("baseline_value"))),
                     _clause("超 {}%", a.get("deviation_pct")),
                     _clause("疑似超出额 {}", _money(a.get("excess_amount"))),
                     _clause("依据 {}", a.get("baseline_source")))
    elif rule == "qty_over_baseline":
        body = _join(_clause("送审量 {} > 合同量 {}", _qty(a.get("reported_value")), _qty(a.get("baseline_value"))),
                     _clause("超 {}%", a.get("deviation_pct")),
                     _clause("疑似超出额 {}", _money(a.get("excess_amount"))),
                     _clause("依据 {}", a.get("baseline_source")))
    elif rule == "missing_submit":
        body = _join("送审量、价、金额全空", _clause("合同清单该项金额 {}", _money(a.get("baseline_value"))),
                     _clause("依据 {}", a.get("baseline_source")))
    elif rule == "new_item":
        body = _join("合同/中标清单里没有对应项（按编码+名称+单位严格对齐）", line)
    else:
        body = line or ""
    tail = _join(code, where, _clause("置信度 {}", a.get("confidence")))
    return f"{head}（{_join(body, tail)}）"


# ---------- 期次识别(#22 D-12) ----------
#
# 期次来源实地调研结论(nas-data/project 真实语料,2026-08-29):
#   1. 文件名 —— 唯一实测可靠的来源,优先级最高:
#      · 30003:「审核-…进度款2024年4月-土建.xlsx」(年月式,4/5/7 月三份齐全)
#      · 30002:「1、进度款027号.rtf」「进度款01号.rtf」(期次号式;
#        同项目「3、审核汇总表(1).xlsx」表内「编号:032」佐证同一编号序列)
#   2. 表内标题 —— 实测**不可靠,刻意不采用**:30003「2024年5月」文件里,
#      土石方/基坑支护/桩基 sheet 标题分别写着 2023年12月/2023年8月/2024年3月
#      (上月模板复制未改;7月文件里 8#楼还写着 2024年6月)。若按表内标题分组,
#      三份文件的「土石方工程」表(标题同为 2023年12月)会被并进同一期次,
#      该表全部同项立刻互判重复——把 issue #22 的误报原样请回来。
#   3. 目录名 —— 实测全是「未命名文件夹」「未命名文件夹_<雪花ID>」,无期次信息。
#      抽取函数兼容带路径的 source_file(逐级扫描,文件名优先),但不专门接线。
#   4. 上游元数据 —— FileRef 仍然只有 file_id/rel_path/file_name。
#      ⚠ 2026-09-03(#170)订正:audit_tk_submission 已经**不再是**零实体零代码,
#        Java 侧能建批次、能把 submission_id 绑到异常行上了。但**判重键还没换**,
#        也换不了 —— 换键要三件事同时到位,一件都还没做:
#          a) 契约:FileRef 要带上这份文件属于哪个批次(现在只有文件名);
#          b) 归属:Java 侧「哪些文件属于哪个批次」尚无归属关系,
#             tk/detect 送检的仍是**项目全部** Excel(见 TkDetectServiceImpl 注释);
#          c) 数据:存量 2993 条异常的 submission_id 全是 NULL,换键后旧数据无键可用。
#        在这三件到位之前,判重键继续走 period_of(source_file)。
#        方向不变:真有 submission_id 之后,判重键应最优先用它。

# 年月式:2024年4月 / 2024-04 / 2024.4 / 2024_07。要求显式分隔符或「年」,
# 且前后无粘连数字——防「2092051860741865472.xlsx」这类雪花ID文件名误配。
_PERIOD_YM = re.compile(r"(?<!\d)(19\d{2}|20\d{2})\s*[年.\-_/]\s*(0?[1-9]|1[0-2])(?:\s*月)?(?!\d)")
# 期次号式:进度款027号 / 进度款第5期 / 计量第3次(数字紧跟业务词,防「1、」序号误配);
# 或独立的「第N期/第N次/第N批」(带「第」;不含「号」——防「第3号楼」误配)。
_PERIOD_SEQ = re.compile(
    r"(?:进度款|工程款|计量|申报|结算)[^\d第]{0,4}第?\s*(\d{1,4})\s*[期次号批]"
    r"|第\s*(\d{1,4})\s*[期次批]"
)
# 裸月式:「4月进度款.xlsx」(无年份)。同一送检批内可区分,跨年会撞——两害相权,
# 有标识仍好过退化成按文件;年月式/期次号式优先于它。
_PERIOD_MONTH = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])\s*月(?!\d)")


def _period_of_component(comp: str) -> tuple[str, str] | None:
    m = _PERIOD_YM.search(comp)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        return f"ym:{y}-{mo:02d}", f"{y}年{mo}月"
    m = _PERIOD_SEQ.search(comp)
    if m:
        n = int(m.group(1) or m.group(2))
        return f"no:{n}", f"第{n}期"
    m = _PERIOD_MONTH.search(comp)
    if m:
        mo = int(m.group(1))
        return f"m:{mo}", f"{mo}月"
    return None


def period_of(source_file: str) -> tuple[str, str | None]:
    """从 source_file(文件名,可含路径)识别期次 → (期次分组键, 人读期次标签)。

    识别顺序:年月式 > 期次号式 > 裸月式;文件名优先,识别不到再逐级扫父目录名。
    兜底(识别不到任何期次):返回 ("file:" + source_file, None) ——
    **每份文件视为独立期次**。选这边而不是"无期次归同一组"的理由:
      · 归同一组会把任意两份无期次标识的文件互相判重。真实语料里就有实物:
        30003 的「2092051860741865472.xlsx」「2092059268151164928.xlsx」
        (平台雪花ID命名,无期次)是内容完全相同的两份清单(空白工程量版,
        当前解析为 0 行)——同类文件一旦带上量价,归同一组就会全部同项互判
        重复,原样重现 issue #22 的误报形态。
      · 按文件独立=保持已上线的 source_file 保守口径,无期次文件的行为与
        修复前完全一致,不引入新误报;代价是无期次标识的"同期次拆多文件"
        之间的真重复仍漏判——这是修复前就有的漏报,不是本次新引入的,
        且带期次标识时该漏报已被本次修复(同期次跨文件可判重)。
    """
    if not source_file:
        return "file:", None
    comps = re.split(r"[\\/]+", source_file)
    for comp in reversed(comps):          # 文件名(最深一级)优先
        got = _period_of_component(comp)
        if got:
            return got
    return "file:" + source_file, None


# 同组成员清单每条异常都带一份；组很大时（一张表里同码几十行）只列前 N 个，另给总数，别让 detail 膨胀
_MEMBERS_SHOWN = 20


def _members(rows: list[dict]) -> list[dict]:
    return [{"file": m.get("source_file") or "", "file_id": m.get("file_id"), "sheet": m.get("sheet") or "",
             "row": m.get("row"), "amount": _num(m.get("submit_amount"))} for m in rows[:_MEMBERS_SHOWN]]


def rule_duplicate(rows: list[dict], cfg: dict, conf: float, repeat_conf: float = 0.3) -> list[dict]:
    """同项目 + 同期次 + 同单位工程内，清单键重复（编码；编码空则 名称+特征+单位）。

    分组键（WS08-08）：(project_id, 期次, 单位工程, 编码)。旧版用 major（costsheet 章名/附录名）
    分组 —— 两栋楼的同一条清单在同一份文件里会被互判重复。单位工程取表头上方的「单位工程名称」，
    缺省时是 sheet 名（costsheet 已回填）。
    判定（WS08-11）：组内至少 2 行金额非零才是「重复计取」，只圈金额非零的成员；
    否则降级为 code_repeat「编码重复（数据质量）」、severity 0，列出全部成员 —— 一行 6355.3、
    一行 0 的同码不是重复计取。期次识别见 period_of（识别不到退化为按文件独立判重）。
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    labels: dict[str, tuple[str, str | None]] = {}
    for r in rows:
        code = _norm(r.get("item_code"))
        ident = code if code else ("nf:" + _norm(r.get("item_name")) + "|" + _norm(r.get("item_feature")) + "|" + _norm(r.get("unit")))
        if not ident or ident == "nf:||":
            continue
        src = str(r.get("source_file") or "")
        if src not in labels:
            labels[src] = period_of(src)
        pkey, _ = labels[src]
        unit_project = str(r.get("unit_project") or r.get("sheet") or "")
        groups[(r.get("project_id"), pkey, unit_project, ident)].append(r)
    out = []
    for _gk, members in groups.items():
        if len(members) < 2:
            continue
        label = labels[str(members[0].get("source_file") or "")][1]
        member_list = _members(members)
        nonzero = [m for m in members if _num(m.get("submit_amount"))]
        if len(nonzero) >= 2:
            if max(abs(_f(m.get("submit_amount"))) for m in nonzero) < cfg.get("min_amount", 0):
                continue
            src_note = f"同期次[{label}]" if label else "同文件"
            for m in nonzero:
                amt = _num(m.get("submit_amount"))
                a = _mk(m, "duplicate", "重复计取", reported=amt, conf=conf, line_amount=amt,
                        baseline_source=f"{src_note}重复行×{len(nonzero)}",
                        extra={"period": label, "period_label": f"同期次[{label}]" if label else None,
                               "members": member_list, "members_total": len(members)})
                out.append(a)
        else:
            for m in members:
                amt = _num(m.get("submit_amount"))
                out.append(_mk(m, "code_repeat", "编码重复（数据质量）", reported=amt, conf=repeat_conf,
                               line_amount=amt, severity=0, baseline_source="同编码多行",
                               extra={"period": label, "members": member_list, "members_total": len(members)}))
    return out


def _zangu_hit(r: dict, markers: list, price_words: list) -> Optional[tuple[str, Optional[str]]]:
    """(命中在哪, 命中的词)；按强弱取第一档。没命中返回 None。"""
    if _num(r.get("provisional_amount")):
        return ZANGU_PROVISIONAL, None
    name, feature = str(r.get("item_name") or ""), str(r.get("item_feature") or "")
    for scope, text, words in ((ZANGU_NAME, name, markers), (ZANGU_FEATURE_PRICE, feature, price_words),
                               (ZANGU_FEATURE_TEXT, feature, markers)):
        hit = next((w for w in words if w in text), None)
        if hit:
            return scope, hit
    return None


def rule_zangu(rows: list[dict], cfg: dict, conf: float) -> list[dict]:
    """暂估价存疑，分四档（WS26-n，D-R164；四档都照出，不少出一条）：

      清单表「其中：暂估价」列本行非零 / 名称里有 markers / 项目特征里有 price_words → conf（中）
      只在项目特征里出现裸的 markers                                         → feature_text_confidence（低）

    改前在「名称 + 特征」拼成的整段里找 markers：TK-C06 原件 10 行「PC楼梯」的特征「钢筋含量：暂定按100kg/m3」
    10 / 10 判成暂估价、排进「重点」，那是含钢量的取值说明。price_words 每个都含一个 markers 里的字，
    所以命中集合与改前相同（只差跨名称与特征拼接处的字，实际不会出现），变的只是置信与页签。
    """
    markers = cfg.get("markers", [])
    price_words = cfg.get("price_words", [])
    weak_conf = cfg.get("feature_text_confidence", conf)
    out = []
    for r in rows:
        amt = _num(r.get("submit_amount"))
        if amt is None or abs(amt) < cfg.get("min_amount", 0):
            continue
        hit = _zangu_hit(r, markers, price_words)
        if hit is None:
            continue
        scope, word = hit
        weak = scope == ZANGU_FEATURE_TEXT
        extra = {"marker": word, "marker_scope": scope}
        if scope == ZANGU_PROVISIONAL:
            extra["provisional_amount"] = _num(r.get("provisional_amount"))
        a = _mk(r, "zangu", "整项存疑-暂估价", reported=amt, conf=weak_conf if weak else conf, line_amount=amt,
                tier="低" if weak else None, extra=extra)
        a["baseline_source"] = _zangu_clause(a)
        out.append(a)
    return out


def rule_self_check(rows: list[dict], cfg: dict, conf: float) -> list[dict]:
    tol = cfg.get("tol_pct", 2.0)
    out = []
    for r in rows:
        # WS08-01：工程量与金额不是同一期次组时（合同量 vs 本月上报产值）量×价≠金额是常态，
        # 不是「不自洽」—— 旧版在进度款表上因此报了 701 条假阳（QA:tk-01）
        periods = r.get("periods") or {}
        if periods.get("qty") and periods.get("amount") and periods["qty"] != periods["amount"]:
            continue
        q, p, amt = _num(r.get("submit_qty")), _num(r.get("submit_price")), _num(r.get("submit_amount"))
        if not q or not p or amt is None or abs(amt) < cfg.get("min_amount", 0):
            continue
        calc = q * p
        if calc == 0:
            continue
        dev = abs(calc - amt) / max(abs(amt), 1e-9) * 100
        if dev > tol:
            out.append(_mk(r, "self_check", "整项存疑-自洽", reported=amt, conf=conf, line_amount=amt,
                           baseline_source="行内 量×单价", deviation_pct=round(dev, 2),
                           extra={"qty": q, "price": p, "calc_value": round(calc, 2)}))
    return out


def rule_big_amount(rows: list[dict], cfg: dict, conf: float) -> list[dict]:
    line = cfg.get("min_amount", 0)
    out = []
    for r in rows:
        amt = _num(r.get("submit_amount"))
        if amt is not None and abs(amt) >= line:
            # 「基准」曾被填成大额线 —— 大额线不是合同基准，单列 threshold（WS08-11）
            out.append(_mk(r, "big_amount", "整项存疑-大额", reported=amt, conf=conf, line_amount=amt,
                           baseline_source="配置大额线", extra={"threshold": line}))
    return out


def _aligns(rows: list[dict], index: dict, aligns: Optional[list]) -> list:
    return aligns if aligns is not None else [align_row(r, index) for r in rows]


def rule_price_over_baseline(rows, cfg, conf, index, align_cfg=None, aligns=None):
    """单价疑似超合同：只认严格对齐（铁律 3）。疑似超出额 =（送审单价 − 合同单价）× 送审量。"""
    over = cfg.get("over_pct", 10.0)
    out = []
    for r, al in zip(rows, _aligns(rows, index, aligns)):
        amt = _num(r.get("submit_amount"))
        if al.method != EXACT or amt is None or abs(amt) < cfg.get("min_amount", 0):
            continue
        bp, sp = _num(al.base.get("base_price")), _num(r.get("submit_price"))
        if not bp or bp <= 0 or sp is None or sp <= bp * (1 + over / 100):
            continue
        sq = _num(r.get("submit_qty"))
        excess = round((sp - bp) * sq, 2) if sq is not None else None
        out.append(_mk(r, "price_over_baseline", "单价疑似超合同", reported=sp, conf=round(conf, 3),
                       line_amount=amt, excess_amount=excess, baseline=bp,
                       baseline_source=_base_src(al.base, "单价"), deviation_pct=round((sp - bp) / bp * 100, 2),
                       method=EXACT, extra={"baseline_ref": _base_ref(al.base)}))
    return out


def rule_qty_over_baseline(rows, cfg, conf, index, align_cfg=None, aligns=None):
    """工程量疑似超合同：只认严格对齐。疑似超出额 =（送审量 − 合同量）× 送审单价。"""
    over = cfg.get("over_pct", 15.0)
    out = []
    for r, al in zip(rows, _aligns(rows, index, aligns)):
        amt = _num(r.get("submit_amount"))
        if al.method != EXACT or amt is None or abs(amt) < cfg.get("min_amount", 0):
            continue
        bq, sq = _num(al.base.get("base_qty")), _num(r.get("submit_qty"))
        if not bq or bq <= 0 or sq is None or sq <= bq * (1 + over / 100):
            continue
        sp = _num(r.get("submit_price"))
        excess = round((sq - bq) * sp, 2) if sp is not None else None
        out.append(_mk(r, "qty_over_baseline", "工程量疑似超合同", reported=sq, conf=round(conf, 3),
                       line_amount=amt, excess_amount=excess, baseline=bq,
                       baseline_source=_base_src(al.base, "工程量"), deviation_pct=round((sq - bq) / bq * 100, 2),
                       method=EXACT, extra={"baseline_ref": _base_ref(al.base)}))
    return out


def rule_missing_submit_data(rows, cfg, conf, index, align_cfg=None, aligns=None):
    """送审量价金额全空 + 合同清单（严格对齐）有该项且金额过线 → 送审缺失存疑。"""
    min_base = cfg.get("min_base_amount", 10000)
    out = []
    for r, al in zip(rows, _aligns(rows, index, aligns)):
        if _num(r.get("submit_qty")) or _num(r.get("submit_price")) or _num(r.get("submit_amount")):
            continue
        if al.method != EXACT:
            continue
        b = al.base
        base_amt = _num(b.get("base_amount"))
        if base_amt is None and _num(b.get("base_qty")) is not None and _num(b.get("base_price")) is not None:
            base_amt = _num(b.get("base_qty")) * _num(b.get("base_price"))
        if base_amt is None or base_amt < min_base:
            continue
        out.append(_mk(r, "missing_submit", "整项存疑-送审缺失", reported=None, conf=round(conf, 3),
                       baseline=round(base_amt, 2), baseline_source=_base_src(b, "金额"), severity=base_amt,
                       method=EXACT, extra={"baseline_ref": _base_ref(b)}))
    return out


def rule_new_item(rows, cfg, conf, index, align_cfg=None, aligns=None):
    """对齐=合同外新增 + 送审金额过线 → 合同外新增存疑。

    过线判定用 `abs(amt)`（H6b 止血，2026-08-30）：进度款/结算表里的核减行、红冲行、退场费冲回行
    都是负数，一条 −80 万的合同外新增冲回在旧口径 `amt < min_amount` 下恒被跳过。
    只认 NEW_ITEM：CONFLICT（同码不同名）、SUGGEST（名称单位相同）与 AMBIGUOUS（合同里有多行可对，
    WS26-m）不是「合同里没有」，是「对不准」，进 alignment_issues / align_suggestions 让人看（WS08-07）。
    基准覆盖率护栏在 detect_full 里判（覆盖率低时整条规则不跑）。
    """
    min_amount = cfg.get("min_amount", 5000)
    out = []
    for r, al in zip(rows, _aligns(rows, index, aligns)):
        amt = _num(r.get("submit_amount"))
        if amt is None or abs(amt) < min_amount or al.method != NEW_ITEM:
            continue
        out.append(_mk(r, "new_item", "合同外新增", reported=amt, conf=round(conf, 3), line_amount=amt,
                       baseline_source="合同/中标清单无对应项", method=NEW_ITEM))
    return out


def _base_src(b: dict, what: str) -> str:
    where = "·".join(p for p in (b.get("sheet") or None, _clause("第{}行", b.get("row"))) if p)
    return f"{b.get('source') or '合同清单'}{('·' + where) if where else ''} {what}"


def _base_ref(b: dict) -> dict:
    """每一分建议金额须回链得到基准行（铁律 3）。"""
    return {"file": b.get("source"), "file_id": b.get("file_id"), "sheet": b.get("sheet"), "row": b.get("row"),
            "item_code": b.get("item_code"), "item_name": b.get("item_name"), "unit": b.get("unit")}


_BASELINE_RULES = {
    "price_over_baseline": rule_price_over_baseline,
    "qty_over_baseline": rule_qty_over_baseline,
    "missing_submit": rule_missing_submit_data,
    "new_item": rule_new_item,
}

_RULES = {
    "zangu": rule_zangu,
    "self_check": rule_self_check,
    "big_amount": rule_big_amount,
}

# —— 行级前提（WS26-c，铁律 8）：一条规则「跑了」之后，它判的是哪些行 ——
# Java 落库时只在拿到「这一行被它原来那条规则重新判过」的证据后才删 / 才换掉旧的待复核异常；
# 「本轮没命中」不等于「问题没了」。规则表的真源在这里，Java 只认这三种前提、不抄规则名。
#   all            每一行都判
#   exact_rows     只判严格对齐到合同/中标清单的行（见各规则里的 al.method != EXACT）
#   group_members  判的是一组行（同组成员少了一份文件，这一组就拼不出来）
PREMISE_ALL = "all"
PREMISE_EXACT_ROWS = "exact_rows"
PREMISE_GROUP_MEMBERS = "group_members"
_ROW_PREMISE = {
    "duplicate": PREMISE_GROUP_MEMBERS,
    "code_repeat": PREMISE_GROUP_MEMBERS,      # rule_duplicate 的降级产物，同一条规则开关
    "zangu": PREMISE_ALL,
    "self_check": PREMISE_ALL,
    "big_amount": PREMISE_ALL,
    "price_over_baseline": PREMISE_EXACT_ROWS,
    "qty_over_baseline": PREMISE_EXACT_ROWS,
    "missing_submit": PREMISE_EXACT_ROWS,
    "new_item": PREMISE_ALL,                   # 每一行都判「合同里有没有」；另需覆盖率过线才跑
}
# rule_duplicate 一个开关出两种异常
_DUPLICATE_OUTPUTS = ("duplicate", "code_repeat")


def _is_gb(r: dict) -> bool:
    return normalize_code(r.get("item_code")).kind == GB


# 折叠时这条结果去哪（WS26-n）：0 本身归「重点」；1 弱命中的暂估（前端归「数据质量」）；2 粗筛 / 数据质量提示。
# 与 anomalyTable.ts / TkAnomalyExportFilter 的 tabOfRule 是同一张表（test_tk_zangu_scope 用口径对照夹具钉住）。
_SCREEN_OUTPUTS = frozenset({"big_amount", "code_repeat"})


def _fold_tier(h: dict) -> int:
    if h["subtype"] in _SCREEN_OUTPUTS:
        return 2
    if h["subtype"] == "zangu" and h.get("marker_scope") == ZANGU_FEATURE_TEXT:
        return 1
    return 0


def _pick_winner(hits: list[dict]) -> dict:
    """同一身份被多条规则命中：去处档升序、置信度降序、severity 降序、规则名升序取第一条 —— 与输入顺序无关。

    去处档（WS26-n）只为暂估的弱命中而设，它的单条置信 0.3 放在哪儿都不对：
      · 按置信与大额粗筛并列 0.3，规则名 big_amount 在前 —— TK-C06 那 10 行「钢筋含量暂定」（都过 2 万）
        会整体改判成大额，暂估 10 → 0（合入条件：暂估命中条数不变）；
      · 按规则档 0.6 排又胜过自洽（0.55）、合同外新增（0.55）—— 那一行的量价不自洽 / 合同外新增跟着它进了
        「数据质量」，证据句还写「不一定是暂估价」。第四档只该自己不进「重点」，不该带走别的规则（spec §3.14）。
    所以弱命中输给每一条本身归「重点」的规则，仍胜大额粗筛与编码重复。其余规则在默认配置下「重点」档的置信
    都高于粗筛的 0.3，次序与改前相同。"""
    return sorted(hits, key=lambda h: (_fold_tier(h), -h["confidence"], -h["severity"], h["subtype"]))[0]


def _row_ref(r: dict) -> dict:
    return {"file": r.get("source_file") or "", "file_id": r.get("file_id"), "sheet": r.get("sheet") or "",
            "row": r.get("row"), "unit_project": r.get("unit_project"), "item_code": r.get("item_code", ""),
            "item_name": r.get("item_name", ""), "item_feature": r.get("item_feature", ""), "unit": r.get("unit", "")}


def _cand_ref(b: dict) -> dict:
    """候选基准行：只给定位与名称，不带任何金额/单价/量（铁律 3：对不准就不出数）。"""
    return {"file": b.get("source"), "file_id": b.get("file_id"), "sheet": b.get("sheet"), "row": b.get("row"),
            "unit_project": b.get("unit_project"), "item_code": b.get("item_code"), "item_name": b.get("item_name"),
            "item_feature": b.get("item_feature"), "unit": b.get("unit")}


def _pct(part: int, whole: int) -> str:
    """覆盖率写进文案的百分数。不到 1% 时保留两位小数：14 / 8626 写成「0%」会被读成一行都没对上
    （WS26-m，缺陷 07-014）；两位小数仍抹成 0.00% 的写「不到 0.01%」—— 0% 只留给真的 0 行。"""
    ratio = part / whole
    if ratio >= 0.01 or part == 0:
        return f"{ratio:.0%}"
    text = f"{ratio:.2%}"
    return "不到 0.01%" if text == "0.00%" else text


def detect_full(rows: list[dict], rules_cfg: dict, baselines: list[dict] | None = None) -> dict:
    """跑全部启用规则 → {anomalies, alignment_issues, align_suggestions, baseline_stats, warning_items,
    rules_run, rules_skipped, exact_rows}。

    rules_run / rules_skipped / exact_rows（WS26-c）是给 Java 落库用的「本轮证据」，都是本次请求里
    现算的（铁律 4），不含金额：
      rules_run     {规则 id: 行级前提}，本轮真的跑了的规则
      rules_skipped {规则 id: 原因码}，本轮没跑的规则与原因
                    （baseline_not_provided / baseline_coverage_low / rule_disabled；
                      run() 在基准给了却读不出时把前者改写成 baseline_invalid）
      exact_rows    {file_id: {表名: [行号…]}}，严格对齐到基准行的送审行；没有基准时是 {}。
                    CONFLICT / AMBIGUOUS 的行不在内：基准规则没判它，它上一轮的待复核不能删
    """
    conf_map = rules_cfg.get("confidence", {})
    rules = rules_cfg.get("rules", {})
    hits: list[dict] = []
    warning_items: list[dict] = []
    rules_run: dict[str, str] = {}
    rules_skipped: dict[str, str] = {}
    dup_cfg = rules.get("duplicate", {})
    if dup_cfg.get("enabled", False):
        hits.extend(rule_duplicate(rows, dup_cfg, conf_map.get("duplicate", 0.7), conf_map.get("code_repeat", 0.3)))
        for name in _DUPLICATE_OUTPUTS:
            rules_run[name] = _ROW_PREMISE[name]
    else:
        for name in _DUPLICATE_OUTPUTS:
            rules_skipped[name] = "rule_disabled"
    for name, fn in _RULES.items():
        rc = rules.get(name, {})
        if rc.get("enabled", False):
            hits.extend(fn(rows, rc, conf_map.get(name, 0.5)))
            rules_run[name] = _ROW_PREMISE[name]
        else:
            rules_skipped[name] = "rule_disabled"

    alignment_issues: list[dict] = []
    suggestions: list[dict] = []
    stats = None
    exact_rows: dict[str, dict[str, list]] = {}
    if not baselines:
        for name in _BASELINE_RULES:
            rules_skipped[name] = ("baseline_not_provided" if rules.get(name, {}).get("enabled", False)
                                   else "rule_disabled")
    if baselines:
        index = build_index(baselines)
        aligns = [align_row(r, index) for r in rows]
        align_cfg = rules_cfg.get("baseline_align", {})
        coded = [i for i, r in enumerate(rows) if _is_gb(r)]
        exact_coded = sum(1 for i in coded if aligns[i].method == EXACT)
        coverage = round(exact_coded / len(coded), 4) if coded else None
        min_cov = float(align_cfg.get("new_item_min_coverage", 0.5))
        new_item_ok = coverage is not None and coverage >= min_cov
        for name, fn in _BASELINE_RULES.items():
            rc = rules.get(name, {})
            if not rc.get("enabled", False):
                rules_skipped[name] = "rule_disabled"
                continue
            if name == "new_item" and not new_item_ok:
                rules_skipped[name] = "baseline_coverage_low"
                continue
            hits.extend(fn(rows, rc, conf_map.get(name, 0.6), index, align_cfg, aligns))
            rules_run[name] = _ROW_PREMISE[name]
        for r, al in zip(rows, aligns):
            # 没有 file_id / 行号的行（老调用方直接喂内存行）进不了证据：Java 拿不到就不删，方向是保守的。
            # 表名与异常身份键同一写法（_key 里 strip 过），Java 拿异常的 sheet 来这里查
            if al.method == EXACT and r.get("file_id") not in (None, "") and r.get("row") is not None:
                exact_rows.setdefault(str(r["file_id"]), {}).setdefault(
                    str(r.get("sheet") or "").strip(), []).append(r["row"])
        if not new_item_ok and rules.get("new_item", {}).get("enabled", False):
            msg = (f"送审行里带标准编码的 {len(coded)} 行，严格对齐到合同/中标清单的只有 {exact_coded} 行"
                   f"（{_pct(exact_coded, len(coded))}，门槛 {min_cov:.0%}），本轮不判「合同外新增」" if coded else
                   "送审行里没有标准清单编码，无法评估合同基准覆盖率，本轮不判「合同外新增」")
            warning_items.append(warn("baseline_coverage_low", msg))
        for r, al in zip(rows, aligns):
            if al.method in (CONFLICT, AMBIGUOUS):
                alignment_issues.append({**_row_ref(r), "method": al.method, "reason": al.reason,
                                         "baseline": [_cand_ref(c) for c in al.candidates]})
            elif al.method == SUGGEST:
                suggestions.append({**_row_ref(r), "reason": al.reason,
                                    "candidates": [_cand_ref(c) for c in al.candidates]})
        counts = {m: sum(1 for a in aligns if a.method == m)
                  for m in (EXACT, CONFLICT, SUGGEST, NEW_ITEM, AMBIGUOUS)}
        if alignment_issues:
            warning_items.append(warn(
                "baseline_conflicts",
                f"{len(alignment_issues)} 行需要人工指定合同行（其中 {counts[CONFLICT]} 行同编码不同名称或单位，"
                f"{counts[AMBIGUOUS]} 行在合同清单里有多行可对），未出金额"))
        stats = {"rows": len(baselines), "coded_rows": len(coded), "exact_coded": exact_coded,
                 "coverage": coverage, "min_coverage": min_cov, "new_item_checked": new_item_ok,
                 "aligned": counts}

    # 折叠键就是身份键：异常自身带着 project_id/file_id/source_file/sheet/row/item_code，
    # 直接对它算 _key —— 指纹字段集 ≡ 折叠键字段集，一轮之内不会出现两条同 uid
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for h in hits:
        by_key[_key(h)].append(h)
    best = [_pick_winner(v) for v in by_key.values()]
    best.sort(key=lambda x: (-x["severity"], x["anomaly_id"]))
    return {"anomalies": best, "alignment_issues": alignment_issues, "align_suggestions": suggestions,
            "baseline_stats": stats, "warning_items": warning_items,
            "rules_run": rules_run, "rules_skipped": rules_skipped, "exact_rows": exact_rows}


def detect(rows: list[dict], rules_cfg: dict, baselines: list[dict] | None = None) -> list[dict]:
    """只要异常清单（老调用方与单测用）。"""
    return detect_full(rows, rules_cfg, baselines)["anomalies"]


# ---------- 接线层:costsheet 明细 → detect() 行 schema ----------

def costsheet_items_to_rows(items: list[dict], project_id: str, source_file: str = "") -> list[dict]:
    """costsheet.parse_costsheet 的 items → detect() 期望的送审行 schema。

    `source_file` 是该批 items 所属的送审文件名,由 run() 逐份传入 —— rule_duplicate 用它识别期次。
    major 取附录名（WS08-06，只作展示，不再参与判重分组）。
    row / file_id / sheet 进异常身份键（WS08-08）；unit_project 进重复计取分组；
    periods 供 self_check 的期次判断（WS08-01）。"""
    rows = []
    for it in items:
        rows.append({
            "project_id": project_id or "",
            "major": it.get("appendix_name") or it.get("chapter_name") or "",
            "sheet": it.get("sheet") or "",
            "item_code": it.get("code") or "",
            "item_name": it.get("name") or "",
            "item_feature": it.get("feature") or "",
            "unit": it.get("unit") or "",
            "submit_qty": it.get("qty"),
            "submit_price": it.get("price"),
            "submit_amount": it.get("amount"),
            "source_file": source_file or it.get("file") or "",
            "row": it.get("row"),
            "file_id": it.get("file_id"),
            "unit_project": it.get("unit_project") or it.get("sheet") or "",
            "section": it.get("section") or "",
            "values": it.get("values") or {},
            "basis_used": it.get("basis_used"),
            "periods": it.get("periods") or {},
            "audit_amount": it.get("audit_amount"),
            # WS26-n：清单表「其中：暂估价」列本行的值（表里没有这一列 / 格是空的就没有这个键）
            "provisional_amount": it.get("provisional_amount"),
        })
    return rows


def _extract_baseline_rows(baseline: Any) -> list[dict] | None:
    """旧 `baseline` 入参：list[dict]，或 dict 里挂 items/rows/baseline_items/lines。识别不到回 None。

    基准行字段口径:item_code, item_name, item_feature, unit, base_qty, base_price, base_amount, source
    """
    if baseline is None:
        return None
    if isinstance(baseline, list):
        return [b for b in baseline if isinstance(b, dict)]
    if isinstance(baseline, dict):
        for key in ("items", "rows", "baseline_items", "lines"):
            v = baseline.get(key)
            if isinstance(v, list):
                return [b for b in v if isinstance(b, dict)]
    return None


def _validate_baseline(raw_rows: list[dict], project_id: str) -> tuple[list[dict], int]:
    """旧 baseline 参数兼容但校验（WS08-07）：缺 project_id 用请求里的；既没编码也没名称的行拒收。

    Java 曾把 WBS 级 {wbs_unit_id, baseline_type, amount} 当清单级基准发来 —— 索引为空，
    100% 送审行被判成「合同外新增」。"""
    ok, bad = [], 0
    for b in raw_rows:
        if not str(b.get("item_code") or "").strip() and not str(b.get("item_name") or "").strip():
            bad += 1
            continue
        row = dict(b)
        if not str(row.get("project_id") or "").strip():
            row["project_id"] = project_id
        ok.append(row)
    return ok, bad


def baseline_rows_from_items(items: list[dict], project_id: str, source: str, file_id=None) -> list[dict]:
    """合同/中标清单（basis=contract 解析）→ 基准行。带 file_id/sheet/row，超合同条目能回链到基准行；
    带 unit_project，同一个键在合同清单里有多行时 tk_align 用它收窄（WS26-m）。"""
    return [{"project_id": project_id, "item_code": it.get("code") or "", "item_name": it.get("name") or "",
             "item_feature": it.get("feature") or "", "unit": it.get("unit") or "",
             "base_qty": it.get("qty"), "base_price": it.get("price"), "base_amount": it.get("amount"),
             "source": source, "file_id": file_id if file_id is not None else it.get("file_id"),
             "sheet": it.get("sheet"), "row": it.get("row"),
             "unit_project": it.get("unit_project") or it.get("sheet") or ""} for it in items]


class ParseFailed(RuntimeError):
    """zt：接线层（zt.costsheet.service.parse_failed）把它转成 status=insufficient，detail() 原样放进 data.detail。

    全部送审文件均解析不出清单行 / 全部无金额 / 全部口径不存在或有歧义 —— API 层转 422。

    WS26-e：422 的 detail 是对象（detail()），Java TaskOutcomeJudge 取 message 作 summary、reason_code 作
    outcome_reason、hint 进告警；口径问题另带所选口径与各文件实际有的期次（basis_available），前端据此指路。"""

    def __init__(self, message: str, *, reason_code: str | None = None, hint: str | None = None,
                 basis_requested: str | None = None, basis_available: list | None = None,
                 files: list | None = None):
        super().__init__(message)
        self.message = message
        self.reason_code = reason_code
        self.hint = hint
        self.basis_requested = basis_requested
        self.basis_available = basis_available
        self.files = files

    def detail(self) -> dict:
        return {"message": self.message, "reason_code": self.reason_code, "hint": self.hint,
                "basis_requested": self.basis_requested, "basis_available": self.basis_available or [],
                "files": self.files or []}


def run(submission_files: list[tuple], baseline: Any, project_id: str = "", basis: str = "auto",
        baseline_files: list[tuple] | None = None, rules_path: Path | str = RULES_PATH) -> dict:
    """接线层:送审文件 (bytes, filename[, file_id]) 列表 + 合同/中标清单文件 → 异常清单。

    WS08-01：送审文件按 side=submit 解析，期次口径 basis 默认 auto。
    WS08-04：无价文件剔除并告警；全部无价 → ParseFailed（422）。
    WS08-07：合同基准来自用户勾选的清单文件（basis=contract 解析）；旧 baseline 参数兼容但校验。
    WS08-10：没给基准不出告警，用 baseline.status=not_provided 表达。
    zt 改动：rules_path 可指向另一份阈值配置（默认随包的 data/tk_detect.yaml）。"""
    rows: list[dict] = []
    warnings: list[str] = []
    warning_items: list[dict] = []
    file_coverage: list[dict] = []
    files_used = 0
    unpriced_files: list[str] = []
    # WS26-e：一行都没读出的文件里，口径不存在（basis_missing）与多组列分不清（ambiguous）分开记 —— 改前
    # 只看 ambiguous，把「表里只有不分期合价、你选了本期」也说成「多组金额列，请选择对比口径」
    missing_files: list[dict] = []
    ambiguous_files: list[dict] = []
    for f in submission_files:
        raw, name = f[0], f[1]
        fid = f[2] if len(f) > 2 else None
        parsed = parse_costsheet(raw, name, side="submit", basis=basis, file_id=fid)
        warnings.extend(f"{name}: {w}" for w in parsed["warnings"])
        warning_items.extend(parsed["warning_items"])
        file_coverage.append(parsed["meta"]["coverage"])
        if parsed["meta"].get("unpriced"):
            unpriced_files.append(name)
            w = warn("file_unpriced", f"「{name}」清单只有工程量、没有单价和金额（疑似招标工程量清单），已剔除",
                     file=name)
            warning_items.append(w)
            warnings.append(w["message"])
            continue
        if parsed["items"]:
            files_used += 1
            rows.extend(costsheet_items_to_rows(parsed["items"], project_id, source_file=name))
        else:
            statuses = {d["status"] for d in parsed["meta"].get("sheets_detail", [])}
            info = {"file": name, "file_id": fid, "basis_available": parsed["meta"].get("basis_available") or []}
            if "basis_missing" in statuses:
                missing_files.append(info)
            if "ambiguous" in statuses:
                ambiguous_files.append(info)
    if not files_used:
        if unpriced_files and not (missing_files or ambiguous_files):
            raise ParseFailed("送审文件均无金额（疑似招标工程量清单）：" + "、".join(unpriced_files))
        rej = basis_rejection(basis, missing_files, ambiguous_files, lead="送审文件全部没有读出清单",
                              ambiguous_tail="：" + "、".join(f["file"] for f in ambiguous_files))
        if rej:
            raise ParseFailed(rej.pop("message"), **rej)
        # 面向用户的话里不出现 submission_files 这类字段名（07-009 第 2 项）
        raise ParseFailed("送审文件全部没有读出清单：" + ("; ".join(warnings) or "未知原因"))

    # —— 合同基准 ——
    base_rows: list[dict] = []
    base_files_used: list[str] = []
    provided = False
    for f in baseline_files or []:
        provided = True
        raw, name = f[0], f[1]
        fid = f[2] if len(f) > 2 else None
        parsed = parse_costsheet(raw, name, side=None, basis="contract", file_id=fid)
        if parsed["items"]:
            base_files_used.append(name)
            base_rows.extend(baseline_rows_from_items(parsed["items"], project_id, name, fid))
            # WS26-e（WS26-p 评审留下）：合同清单里技术措施表勾稽不过 / 读不出时，那个单位工程的措施项不在基准里，
            # 送审侧对应的措施项会被判成「合同外新增」。改前合同清单的解析告警一条都不回传（只有一行都没读出时
            # 才有 baseline_file_unparsed），任务照样是绿的。这两条回传出去，并写明是哪份合同清单
            for w in parsed["warning_items"]:
                if w["code"] in ("measure_sheet_unreconciled", "measure_sheets_skipped"):
                    w = dict(w, message=f"合同/中标清单「{name}」：{w['message']}，该部分措施项没有参与合同比对")
                    warning_items.append(w)
                    warnings.append(w["message"])
        else:
            w = warn("baseline_file_unparsed", f"合同/中标清单「{name}」没有解析出清单行，未参与超合同、漏报、合同外新增比对",
                     file=name)
            warning_items.append(w)
            warnings.append(w["message"])
    legacy = _extract_baseline_rows(baseline)
    invalid = 0
    if legacy:
        provided = True
        ok, invalid = _validate_baseline(legacy, project_id)
        base_rows.extend(ok)
        if invalid:
            w = warn("baseline_rows_invalid",
                     f"合同基准里有 {invalid} 行既没有清单编码也没有名称（疑似 WBS 级汇总额，不是清单），已拒收"
                     + ("；没有可用的基准行，超合同、漏报、合同外新增比对本轮未做" if not ok else ""))
            warning_items.append(w)
            warnings.append(w["message"])
    elif baseline is not None and legacy is None:
        w = warn("baseline_rows_invalid", "baseline 参数形状无法识别（需 list[dict] 或 dict 内 items/rows 字段），"
                                          "超合同、漏报、合同外新增比对本轮未做")
        warning_items.append(w)
        warnings.append(w["message"])
        provided = True

    rules_cfg = load_rules(rules_path)
    out = detect_full(rows, rules_cfg, baselines=base_rows or None)
    for w in out["warning_items"]:
        warning_items.append(w)
        warnings.append(w["message"])
    if not provided:
        baseline_status = "not_provided"
    elif base_rows:
        baseline_status = "provided"
    else:
        baseline_status = "invalid"
    checked = sum(1 for r in rows if r.get("submit_amount"))
    rules_skipped = dict(out["rules_skipped"])
    if baseline_status == "invalid":
        # 给了合同/中标清单却一行都没读出来：与「没给」分开说（Java 的 sweep.keptRules 与页面文案据此区分）
        rules_skipped = {k: ("baseline_invalid" if v == "baseline_not_provided" else v)
                         for k, v in rules_skipped.items()}
    return {"anomalies": out["anomalies"], "warnings": warnings, "warning_items": warning_items,
            "rules_version": rules_cfg.get("version", ""), "file_coverage": file_coverage,
            # WS26-e：送检范围标签（投控页横幅下方那一行），只按计入了的送审文件算
            "scope_label": scope_label([c for c in file_coverage if c.get("status") == "parsed"]),
            "checked_rows": checked, "rows_total": len(rows),
            "files_total": len(submission_files), "files_used": files_used,
            "alignment_issues": out["alignment_issues"], "align_suggestions": out["align_suggestions"],
            "rules_run": out["rules_run"], "rules_skipped": rules_skipped,
            "baseline": {"status": baseline_status, "files": base_files_used, "rows": len(base_rows),
                         "rows_rejected": invalid, "stats": out["baseline_stats"],
                         "exact_rows": out["exact_rows"]}}
