# 来源：engine-service/app/engine/costsheet_warnings.py（zhitong-cost-ai@991ff5cd，W2 搬入 zt；改动见本文件内「zt 改动」注释）
"""计价表解析链路（costsheet / reconcile / indicator / tk）告警码的**单一真源**（WS08，issue #724）。

仿 warning_codes.py（概算链路）：发出去的码必须在这里登记，
`tests/costsheet/test_costsheet_warning_codes.py` 扫源码，漏登记即红；
`zhitong/skills/_shared/costsheet/告警码.md` 是给 agent 看的同一张表（`tests/costsheet/test_skill_docs.py` 校验一致）。

级别按总纲 C2：info / warn / error。WS08 spec 原文的三档对应关系是
信息→info、降级→warn、漏检→error：
  error  有东西**没算进去**或**算不准**（跳了一张有清单的表、合计对不上、列口径有歧义）——
         造价员必须知道结果缺了哪块；
  warn   按降级方式处理了（样式表被忽略、审定侧找不到审核列只能取无当事方列）；
  info   说明性（旧 .xls 已转换、按标题跳过封面/费用表、跨表去重条数）。
告警不拦截；要拦截走 4xx（全无价 / 全歧义 / 全失败 → 422）。zt 里旧 422 改为 status=insufficient（见 zt.costsheet.service）。
"""
from __future__ import annotations

from typing import Optional

from pydantic import ConfigDict

from zt.common.envelope import WarningItem

INFO, WARN, ERROR = "info", "warn", "error"


def _c(label: str, level: str, hint: str) -> dict:
    return {"label": label, "level": level, "hint": hint}


COSTSHEET_WARNING_CODES: dict[str, dict] = {
    # —— 文件级：读不读得进来 ——
    "not_excel": _c("非 Excel 文件", ERROR, "计价表只支持 .xlsx / .xlsm / .xls；请不要选 Word、PDF 等文件"),
    # zt 改动：本机不做 .xls → xlsx 转换（旧仓的 xls_converted / xls_convert_failed 两条码随之删除）
    "xls_unsupported": _c("旧版 .xls 不支持", ERROR, "请用 Excel/WPS 把文件另存为 .xlsx 后再试"),
    "xlsx_unreadable": _c("无法读取 xlsx", ERROR, "请用 Excel/WPS 另存为 .xlsx 后再上传"),
    "stylesheet_patched": _c("样式表已补名", INFO, "单元格样式缺名称，已在内存里补名后读取，数据不受影响"),
    "stylesheet_dropped": _c("样式表已忽略", WARN, "样式表损坏，已忽略样式读取；日期列可能显示为数字"),
    "no_items": _c("没有读出清单行", ERROR,
                   "请确认选的是分部分项清单与计价表（表头有项目编码、名称、合价），或审核汇总表（表头有报审、审核、核减金额）"),
    "file_unpriced": _c("无单价/金额", ERROR, "疑似招标工程量清单（只有工程量），已剔除，不参与金额计算"),
    # —— sheet 级：看懂了哪些表 ——
    "sheet_truncated": _c("工作表超长已截断", WARN, "单表超过 8000 行，只取前 8000 行"),
    "sheet_skipped_has_items": _c("有清单的表被跳过", ERROR,
                                  "该表含清单编码或标题像计价表，但表头没认出来 / 口径有歧义，其金额未计入"),
    # WS26-e（07-004）：一条短句按跳过词计数，表名放进 sheets（改前顿号拼全部表名，242 张时 7448 字）
    "sheets_skipped_by_title": _c("按标题跳过的表", INFO, "封面、说明、费用表、工日/台班/材料一览表等非清单表不计入"),
    # WS26-e（07-003 披露、D-R87）：读不了的施工技术措施表（所选口径读不出 / 版式认不出）单独一条。它们不是
    # 「非清单表」—— 带清单编码行，金额没算进去。warn 不是 error：error 会让这类工作簿每次都是「部分完成」
    # （stubs._status），真正的部分完成反而看不出来（U14）。勾稽不过的那种已有 measure_sheet_unreconciled（error）
    "measure_sheets_skipped": _c("技术措施表没有参与", WARN,
                                 "施工技术措施项目综合单价计算表按所选口径读不出或版式认不出，这些措施项没有参与；"
                                 "措施项目上的问题请人工核对"),
    "sheets_skipped_non_list": _c("非国标清单表已排除", INFO, "国标编码行不到一半的表（如万元估算表）不参与指标计算"),
    "column_ambiguous": _c("金额列口径有歧义", ERROR,
                           "表头有多组金额/工程量列，无法确定取哪一组；请在「对比口径」里选择合同 / 本期 / 累计"),
    # WS26-e（07-009，P10）：表头有金额列、只是没有所选期次 —— 不是「多组列不知道取哪组」，指的方向相反。
    # 改前并在 column_ambiguous 里，用户被叫去「选择对比口径」，而他刚选的那个口径正是不存在的那个
    "basis_not_found": _c("表头没有所选口径的金额列", ERROR,
                          "这张表没有所选口径的金额列。请把对比口径改为『自动』"),
    "party_columns_missing": _c("没有对应当事方的列", WARN,
                                "表头分了送审/审核列，但没有本侧要的那一组，已按不带当事方的列取数"),
    "amount_scaled_wan": _c("万元已换算为元", INFO, "表头标注「万元」，金额与单价已乘以 10000"),
    "audit_summary_format": _c("按审核汇总表解析", INFO, "表头有成对的报审/审核/核减金额列，按审核汇总版式解析"),
    "sheet_total_mismatch": _c("合计对不上", ERROR, "明细行之和与该表合计行偏差超过 0.5%：可能漏行或多算了标题/小计行"),
    # WS26-p（07-003）：施工技术措施项目综合单价计算表只在与费用表勾稽通过时计入。error：这张表的措施项没算进去
    "measure_sheet_unreconciled": _c("技术措施表对不上，未计入", ERROR,
                                     "措施综合单价计算表的清单项（数量 × 综合单价小计）之和与同一单位工程费用表的"
                                     "「施工技术措施项目」相差超过 1 元（没有费用表时与本表合计行比），整张没有计入；"
                                     "这张表上的措施项请人工核对"),
    "summary_detail_mismatch": _c("汇总表与明细表对不上", ERROR, "汇总表只用于勾稽、不计入；两者之和偏差超过 0.5%"),
    "summary_only": _c("只有汇总表", INFO, "工作簿里没有明细表，已按汇总表计入"),
    "cross_sheet_dedup": _c("跨表重复行已去重", INFO, "不同工作表里编码、名称、金额完全相同的行只计一次"),
    "coverage_partial": _c("部分清单表未计入", WARN, "可识别清单表的金额没有全部计入，见各表状态"),
    "coverage_poor": _c("覆盖率不足", ERROR, "可识别清单表的金额计入不到一半，结果不可作为结论"),
    "chapter_coverage_low": _c("章名覆盖率低", INFO, "来自标准章名表的金额不到 80%，其余归入补充项目/无编码项/非国标编号项"),
    # —— 调用方（对账 / 投控 / 指标）——
    "amounts_identical_suspect": _c("两侧金额疑似取成同一列", ERROR,
                                    "匹配行里 95% 以上两侧金额逐分相同，且表头有多组金额列；请确认对比口径"),
    # 对账两侧是同一份文件 / 全部一致（WS26-b，D-R78）。全部表都取到同一列时不出告警，直接 422
    "same_file_two_sides": _c("两侧是同一份文件", INFO,
                              "表头同时有送审、审定两组金额列，已按两组列分别取数；审核对比表这样选是正确用法"),
    "same_file_sheets_excluded": _c("同一列金额的表未参与对账", ERROR,
                                    "这些表没有分送审、审定两组金额列，同一份文件放两侧比出来必然全部一致，已剔除；"
                                    "请为它们分别选择送审文件和审定文件"),
    "all_rows_identical": _c("全部一致", WARN,
                             "两份文件的每一行金额逐分相同、核减额为 0；这可能是合法结果，也可能是审定文件选错了"),
    # 对账（WS08-19）
    "calc_error_rows": _c("行内量×价≠合价", WARN,
                          "已在对应行标记「送审计算错误 / 审定计算错误」；差额可能来自算术错误而不是量价调整"),
    # 投控合同基准（WS08-07 / WS08-10）
    "baseline_rows_invalid": _c("合同基准行不可用", ERROR,
                                "基准行既没有清单编码也没有名称，无法按清单严格对齐；超合同、漏报、合同外新增比对本轮未做"),
    "baseline_file_unparsed": _c("合同/中标清单未解析出清单行", ERROR,
                                 "该文件没有参与超合同、漏报、合同外新增比对；请确认选的是合同或中标清单（分部分项计价表）"),
    "baseline_coverage_low": _c("合同基准覆盖率低", WARN,
                                "送审行里能严格对齐到合同清单的不到一半，本轮不判「合同外新增」（大多是没对上，不是真新增）"),
    # WS26-m：合同清单里有多行可对、收窄后仍不唯一的行（AMBIGUOUS）并进这一条，不新增告警码
    "baseline_conflicts": _c("需要人工指定合同行", WARN,
                             "这些行与合同清单对不准：编码相同但名称或单位不同，或合同清单里有多行可对、"
                             "分不清对哪一行；按铁律 3 不出金额，列为待人工指定"),
    # 指标（WS08-14 / 15 / 16）
    "files_failed": _c("部分文件未计入", ERROR, "这些文件读不出清单或不是清单表，结果只含其余文件"),
    "file_duplicate": _c("重复文件已剔除", WARN, "两份文件内容完全相同（sha256 一致），只计一份"),
    "file_overlap_suspect": _c("疑似重复清单", WARN,
                               "两份文件的清单行 90% 以上完全相同；同构楼栋可能确实同清单，未自动剔除，请确认没有重复选"),
    "area_missing": _c("未提供建筑面积", WARN, "没有总建筑面积，单方造价与各章单方未计算；请在「指标计算」对话框里填写"),
    "fee_total_unavailable": _c("没有费用表合计", INFO,
                                "所选文件里没有费用表，只算出清单明细合计，不是总造价；可在「含税总造价」里手填"),
    # WS26-h（07-012）：文件里有费用表却取不到（或取到了但与各单位工程费用表之和对不上）。
    # warn 不是 info：这时卡片上的数只是清单明细合计，用户必须看得见（info 在前端是灰字）
    "fee_total_unreadable": _c("费用表合计未采用", WARN,
                               "有费用表，但合计没读到或与各单位工程费用表之和对不上（相差超过 1 元）；"
                               "卡片上的数是清单明细合计，不是总造价。可在「含税总造价」里手填"),
    # WS26-h2（07-005 / 07-012）：费用构成表——单位工程费用表的六项相加与该表合计差超过 1 元时整张不显示。
    # info：构成表只是把合计拆开看，总造价的取数不受影响
    "fee_breakdown_unreconciled": _c("费用构成表未显示", INFO,
                                     "有单位工程费用表的六项（分部分项、技术措施、组织措施、其他项目、规费、增值税）"
                                     "相加与该表合计相差超过 1 元，构成表不显示；总造价的取数不受影响"),
    # WS26-h2（WS26-h 评审留给本片）：费用表的分部分项 / 技术措施与读入的清单之和差超过 1 元。warn：总造价取自
    # 费用表、章节占比按清单算，两边说的不是同一份东西（测试件 B「只改清单、费用表没重算」就是这样）
    "fee_itemized_mismatch": _c("费用表与清单对不上", WARN,
                                "费用表里的分部分项工程费（或施工技术措施项目）与读入的清单合计相差超过 1 元："
                                "可能有清单行没读进来，也可能费用表不是按这份清单算的，请核对"),
}

LEVELS = {code: meta["level"] for code, meta in COSTSHEET_WARNING_CODES.items()}


class CostsheetWarningItem(WarningItem):
    """C2 告警 + 计价表领域多带的定位键（C2：领域要多带键就写子类显式声明）。

    sheets（WS26-e）：一条告警涉及的表名清单（按标题跳过、读不了的措施表）。message 只写短句和张数，
    表名放这里，前端「查看名单」展开 —— 改前 242 个表名拼进 message。"""

    model_config = ConfigDict(extra="forbid")

    file: Optional[str] = None
    sheet: Optional[str] = None
    sheets: Optional[list[str]] = None


def warn(code: str, message: str, *, file: Optional[str] = None,
         sheet: Optional[str] = None, level: Optional[str] = None,
         hint: Optional[str] = None, sheets: Optional[list[str]] = None) -> dict:
    """造一条告警 dict。级别默认取登记表；未登记的码直接 KeyError —— 宁可炸在测试里。
    hint、sheets 只在给了的时候带上（其余告警的 dict 形状不变）。"""
    w = {"code": code, "level": level or LEVELS[code], "message": message,
         "file": file, "sheet": sheet}
    if hint:
        w["hint"] = hint
    if sheets is not None:
        w["sheets"] = list(sheets)
    return w
