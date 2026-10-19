"""结构化失败：脚本以退出码 2 结束，stdout 为 ``{"error": {"code", "message", "hint"?}}``。"""
from __future__ import annotations

import re
from typing import Any, Optional

# 机器码口径：error code、warning code、status_reason 共用（小写 snake_case）。
MACHINE_CODE = r"^[a-z][a-z0-9_]*$"
_MACHINE_CODE_RE = re.compile(MACHINE_CODE)

EXIT_ERROR = 2


class ZtError(Exception):
    """可预期的失败：输入不满足前置、文件缺失、规则数据损坏等。

    :param code: 机器码（小写 snake_case）。
    :param message: 给人看的说明。
    :param hint: 可选的下一步建议。
    """

    def __init__(self, code: str, message: str, hint: Optional[str] = None) -> None:
        if not _MACHINE_CODE_RE.match(code):
            raise ValueError(f"error code 必须是小写 snake_case：{code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def to_json(self) -> dict[str, Any]:
        """序列化为错误 JSON。

        :returns: ``{"error": {...}}``。
        """
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.hint is not None:
            body["hint"] = self.hint
        return {"error": body}
