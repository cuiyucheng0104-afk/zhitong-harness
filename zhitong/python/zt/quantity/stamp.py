# 来源：engine-service/app/provenance_sheet.py 的 stamp_ai_draft_xlsx（zhitong-cost-ai@991ff5cd，W4 搬入 zt）
"""产出 xlsx 的「AI 初稿·须人工复核」页眉（WS06-P4）。清单与概算的渲染出口都调用它。"""
from __future__ import annotations

from typing import Any

AI_DRAFT_STAMP = "AI 初稿·须人工复核"


def stamp_ai_draft_xlsx(wb: Any, text: str = AI_DRAFT_STAMP) -> None:
    """每个 sheet 的页眉（奇数页 / 偶数页 / 首页）居中写印记。只动打印页眉，不动单元格。

    :param wb: openpyxl 工作簿。
    :param text: 印记文字。
    """
    for ws in wb.worksheets:
        for header in (ws.oddHeader, ws.evenHeader, ws.firstHeader):
            cur = header.center.text or ""
            if text not in cur:
                header.center.text = f"{text} {cur}".strip()
