# 来源：engine-service/app/engine/estimate_xlsx_values.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""给存好的概算 xlsx 的公式格补 `<v>` 缓存值（WS10-P06，issue #761）。

为什么：openpyxl 只写公式串、`<v>` 留空。Excel / LibreOffice 打开时会重算（workbook.xml 里
`fullCalcOnLoad="1"`），但**不重算的读取方**—— 平台自己用 openpyxl `data_only=True` 读、
各类预览 / 索引 —— 读到的是 None：`估概算总表!C47` = None，一份概算在它们眼里没有金额。

怎么做：存盘后直接改 sheet XML，把引擎求值器同一次 run 算出的值写进公式格的 `<v>`。
**不引入 LibreOffice 运行时依赖**（spec 要求）：值来自引擎自己的求值器（与 compute 响应的
totals 同源），不是再算一遍。取不到值（#DIV/0! 传播 = None）的格保持空 —— 不编一个数（铁律 3）。

另外：传入 `fixed_time` 时 zip 条目时间戳与 docProps 的创建 / 修改时间一律用它，
同一入参两次渲染逐字节相同（spec「传入 generated_at 时结果确定」）。

只动 `<c>…<f>…</f><v></v></c>` 这一种形状（openpyxl 3.1.5 的写法，生产同版本）；
公式本身、样式、合并、其余部件一个字节都不改。
"""
from __future__ import annotations

import html
import io
import re
import zipfile
from datetime import datetime
from typing import Any, Optional
from xml.sax.saxutils import escape

_SHEET_RE = re.compile(r'<sheet\b[^>]*?\bname="([^"]*)"[^>]*?\br:id="([^"]+)"')
_REL_RE = re.compile(r'<Relationship\b[^>]*?\bTarget="([^"]+)"[^>]*?\bId="([^"]+)"')
_REL_RE2 = re.compile(r'<Relationship\b[^>]*?\bId="([^"]+)"[^>]*?\bTarget="([^"]+)"')
# 公式格：<c r="C5" s="3"><f>SUM(C6:C9)</f><v></v></c>（也认 <v/>）
_FORMULA_CELL = re.compile(
    r'<c r="(?P<ref>[A-Z]{1,3}\d+)"(?P<attrs>[^>]*)>(?P<f><f>(?P<ftext>[^<]*)</f>)(?:<v\s*/>|<v>\s*</v>)</c>')
_T_ATTR = re.compile(r'\s+t="[^"]*"')
_SINGLE_REF = re.compile(r"^(?:(?:'(?P<q>[^']+)'|(?P<s>[^'!]+))!)?\$?(?P<col>[A-Z]{1,3})\$?(?P<row>\d+)$")
_CORE_TIME = re.compile(r"(<dcterms:(?:created|modified)\b[^>]*>)[^<]*(</dcterms:(?:created|modified)>)")


def _unescape(s: str) -> str:
    # openpyxl 把非 ASCII 写成数字字符引用（&#32463;…），跨表引用里的中文表名必须还原才对得上
    return html.unescape(s)


def _sheet_paths(z: zipfile.ZipFile) -> dict[str, str]:
    """zip 内 sheet XML 路径 → 工作表名。"""
    wb = z.read("xl/workbook.xml").decode("utf-8")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    targets = {rid: tgt for tgt, rid in _REL_RE.findall(rels)}
    targets.update({rid: tgt for rid, tgt in _REL_RE2.findall(rels)})
    out: dict[str, str] = {}
    for name, rid in _SHEET_RE.findall(wb):
        tgt = targets.get(rid)
        if not tgt:
            continue
        path = tgt.lstrip("/") if tgt.startswith("/") else f"xl/{tgt}"
        out[path] = _unescape(name)
    return out


def _lookup(values: dict[str, dict[str, Any]], sheet: str, ref: str, formula: str) -> Any:
    v = (values.get(sheet) or {}).get(ref)
    if v is not None:
        return v
    # 渲染器自己加的单格引用（如清单表 K2 = 经济技术指标!$D$5）不在求值器的结果里：按引用取值
    m = _SINGLE_REF.match(_unescape(formula).strip())
    if m:
        target_sheet = m.group("q") or m.group("s") or sheet
        return (values.get(target_sheet) or {}).get(f"{m.group('col')}{m.group('row')}")
    return None


def _cell_xml(ref: str, attrs: str, fxml: str, value: Any) -> Optional[str]:
    if isinstance(value, bool) or value is None:
        return None
    base = _T_ATTR.sub("", attrs)
    if isinstance(value, (int, float)):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return f'<c r="{ref}"{base}>{fxml}<v>{format(float(value), ".17g")}</v></c>'
    if isinstance(value, str):
        return f'<c r="{ref}"{base} t="str">{fxml}<v>{escape(value)}</v></c>'
    return None


def inject_cached_values(xlsx: bytes, values: dict[str, dict[str, Any]], *,
                         fixed_time: Optional[datetime] = None) -> tuple[bytes, int]:
    """→ (新字节, 补上缓存值的公式格数)。values = 求值器 run() 的 `sheets`。"""
    src = zipfile.ZipFile(io.BytesIO(xlsx))
    paths = _sheet_paths(src)
    filled = 0
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            sheet = paths.get(info.filename)
            if sheet is not None:
                text = data.decode("utf-8")

                def _sub(m: re.Match) -> str:
                    nonlocal filled
                    ref = m.group("ref")
                    new = _cell_xml(ref, m.group("attrs"), m.group("f"),
                                    _lookup(values, sheet, ref, m.group("ftext")))
                    if new is None:
                        return m.group(0)
                    filled += 1
                    return new

                data = _FORMULA_CELL.sub(_sub, text).encode("utf-8")
            elif fixed_time is not None and info.filename == "docProps/core.xml":
                stamp = fixed_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                data = _CORE_TIME.sub(lambda m: f"{m.group(1)}{stamp}{m.group(2)}",
                                      data.decode("utf-8")).encode("utf-8")
            zi = zipfile.ZipInfo(info.filename,
                                 date_time=(fixed_time.timetuple()[:6] if fixed_time else info.date_time))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr
            dst.writestr(zi, data)
    return out_buf.getvalue(), filled
