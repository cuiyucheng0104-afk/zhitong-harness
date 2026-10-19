"""zt.code_registry：GB50854 清单编码受控码表（zj2025）与唯一的归章函数。

实现见 :mod:`zt.code_registry.registry`（旧 ``code_registry.py``）；码表与 2013 章名表在 ``data/``。
"""
from zt.code_registry.registry import (
    DEFAULT_VERSION,
    GB,
    available_versions,
    chapter_name,
    classify_chapter,
    load_registry,
    lookup,
    normalize_code,
)

__all__ = [
    "DEFAULT_VERSION",
    "GB",
    "available_versions",
    "chapter_name",
    "classify_chapter",
    "load_registry",
    "lookup",
    "normalize_code",
]
