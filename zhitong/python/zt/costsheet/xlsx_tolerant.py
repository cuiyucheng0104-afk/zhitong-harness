# 来源：engine-service/app/engine/xlsx_tolerant.py（zhitong-cost-ai@991ff5cd，W2 搬入 zt；改动见本文件内「zt 改动」注释）
"""xlsx 容错读取 —— 样式表损坏时的兜底（WS08-05，issue #724；总纲 K25 / C6）。

广联达等软件导出的一部分 xlsx，`xl/styles.xml` 里的 `<cellStyle>` 缺 `name` 属性。
openpyxl 3.1.5 读样式表时直接抛
`<class '..._NamedCellStyle'>.name should be <class 'str'> but value is <class 'NoneType'>`，
整本读不出来。生产 4372 份 xlsx 里有 93 份是这个样子，端点 422 的提示却是
「请用广联达导出 .xlsx」—— 出问题的恰恰就是广联达导出件。

按顺序尝试（前一步成功就停）：
  1. 正常读；
  2. 失败且错误出在样式表：内存里重建 zip，给缺 name 的 cellStyle 补名再读 → `stylesheet_patched`（info）；
  3. 还失败：去掉 `xl/styles.xml` 再读 → `stylesheet_dropped`（warn：日期列可能显示成数字，
     因为没有数字格式就认不出日期）；
  4. 仍失败：抛 XlsxUnreadable，文案改成可操作的「用 Excel/WPS 另存为」，附原因前 300 字。

不走 soffice 的 xlsx→xlsx 转换：textextract.libreoffice_convert 输入输出都叫 in.xlsx，会撞名。

本模块是**共用件**：costsheet 与 textextract 都应从这里读 xlsx（C6「xlsx 坐标只来自 WS04 的
读取件，样式表损坏时的兜底用 WS08-A 的容错模块」）。它不认识任何业务表头，只负责把字节
变成 openpyxl Workbook，并把自己动过手的地方如实报出来。
"""
from __future__ import annotations

import io
import re
import traceback
import zipfile
from typing import Any

STYLES_PART = "xl/styles.xml"
_REASON_MAX = 300

MSG_STYLESHEET = "文件样式表损坏，请用 Excel/WPS 另存为 .xlsx 后再上传"
MSG_GENERIC = "无法读取该 xlsx（文件损坏或并非 Excel 文件），请用 Excel/WPS 另存为 .xlsx 后再上传"

# 缺 name 属性的 cellStyle 开标签（可能带命名空间前缀，如 <x:cellStyle ...>）
_CELLSTYLE_NO_NAME = re.compile(r"<((?:\w+:)?cellStyle)\b(?![^>]*\sname=)([^>]*)>")


class XlsxUnreadable(Exception):
    """三步都读不出来。`message` 给人看（已含原因前 300 字），`stylesheet` 标明是不是样式表的锅。"""

    def __init__(self, message: str, reason: str, stylesheet: bool):
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.stylesheet = stylesheet


def _load(raw: bytes, read_only: bool, data_only: bool):
    from openpyxl import load_workbook
    return load_workbook(io.BytesIO(raw), read_only=read_only, data_only=data_only)


def _is_style_error(exc: BaseException) -> bool:
    """错误是不是在读样式表时抛的：看调用栈里有没有 openpyxl 的 styles 包。

    不按报错文案匹配 —— 缺 name 与样式表 XML 非法抛的是两种完全不同的异常文本。
    """
    for frame in traceback.extract_tb(exc.__traceback__):
        fn = frame.filename.replace("\\", "/")
        if "/openpyxl/styles/" in fn:
            return True
    return "stylesheet" in str(exc).lower() or "NamedCellStyle" in str(exc)


def _rebuild(raw: bytes, replace: dict[str, bytes | None]) -> bytes:
    """按原 zip 重建一份：replace 里给 bytes 的替换内容，给 None 的删掉该成员。"""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as zin, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            if info.filename in replace:
                data = replace[info.filename]
                if data is None:
                    continue
            else:
                data = zin.read(info.filename)
            zout.writestr(info, data)
    return out.getvalue()


def patch_cellstyle_names(xml: str) -> tuple[str, int]:
    """给缺 name 的 `<cellStyle>` 补一个名字，返回 (新 xml, 补了几个)。"""
    n = 0

    def _sub(m: re.Match) -> str:
        nonlocal n
        n += 1
        return f'<{m.group(1)} name="patched_style_{n}"{m.group(2)}>'

    return _CELLSTYLE_NO_NAME.sub(_sub, xml), n


def _reason(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:_REASON_MAX]


def load_workbook_tolerant(raw: bytes, *, read_only: bool = True,
                           data_only: bool = True) -> tuple[Any, list[dict]]:
    """→ (Workbook, notes)。notes 是本次动过手的告警：[{code, level, message}]。

    读不出来抛 XlsxUnreadable；调用方负责把它变成自己的告警 / 422。
    """
    try:
        return _load(raw, read_only, data_only), []
    except Exception as e0:  # noqa: BLE001 — openpyxl 对坏文件抛的异常类型五花八门
        first = e0

    if not zipfile.is_zipfile(io.BytesIO(raw)):
        raise XlsxUnreadable(f"{MSG_GENERIC}：{_reason(first)}", _reason(first), stylesheet=False)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        has_styles = STYLES_PART in z.namelist()
        styles_xml = z.read(STYLES_PART) if has_styles else b""
    if not has_styles or not _is_style_error(first):
        raise XlsxUnreadable(f"{MSG_GENERIC}：{_reason(first)}", _reason(first), stylesheet=False)

    # ② 补名
    try:
        text = styles_xml.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    patched, n = patch_cellstyle_names(text) if text else ("", 0)
    if n:
        try:
            wb = _load(_rebuild(raw, {STYLES_PART: patched.encode("utf-8")}), read_only, data_only)
            return wb, [{
                "code": "stylesheet_patched", "level": "info",
                "message": f"样式表里有 {n} 个单元格样式缺名称（openpyxl 读不了），已在内存里补名后读取；数据不受影响",
            }]
        except Exception:  # noqa: BLE001 — 补名不够就走第 ③ 步
            pass

    # ③ 去掉样式表
    try:
        wb = _load(_rebuild(raw, {STYLES_PART: None}), read_only, data_only)
        return wb, [{
            "code": "stylesheet_dropped", "level": "warn",
            "message": "样式表损坏，已忽略样式表读取：数值与文字不受影响，但日期列可能显示为数字",
        }]
    except Exception as e3:  # noqa: BLE001
        reason = _reason(e3)
    raise XlsxUnreadable(f"{MSG_STYLESHEET}：{reason}", reason, stylesheet=True)
