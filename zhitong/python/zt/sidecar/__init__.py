"""旁车（``.ocr.txt``）：格式解析与查找。

- :mod:`zt.sidecar.format`：分页旁车 / 旧式纯文本旁车解析，``parse_ocr_sidecar``；
- :mod:`zt.sidecar.locate`：命名约定、软链逃逸防护、读取，``read_sidecar_doc``；
- :mod:`zt.sidecar.cli`：``python -m zt.sidecar.cli parse|locate``。

本仓不调用 OCR：旁车是历史 OCR 产物，只读。
"""
from zt.sidecar.format import (
    PAGE_FLAG_NOTES,
    PLACEHOLDER_BY_VERDICT,
    USABLE_VERDICTS,
    SidecarDoc,
    SidecarPage,
    looks_like_paged_sidecar,
    parse_ocr_sidecar,
)
from zt.sidecar.locate import (
    OCR_SIDECAR_SUFFIX,
    find_sidecar,
    is_sidecar_name,
    iter_sidecars,
    read_sidecar_doc,
    read_sidecar_text,
    sidecar_names,
)

__all__ = [
    "OCR_SIDECAR_SUFFIX",
    "PAGE_FLAG_NOTES",
    "PLACEHOLDER_BY_VERDICT",
    "SidecarDoc",
    "SidecarPage",
    "USABLE_VERDICTS",
    "find_sidecar",
    "is_sidecar_name",
    "iter_sidecars",
    "looks_like_paged_sidecar",
    "parse_ocr_sidecar",
    "read_sidecar_doc",
    "read_sidecar_text",
    "sidecar_names",
]
