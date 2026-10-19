"""文本字节解码。

来源：/home/user/zhitong-cost-ai/engine-service/app/engine/textextract.py ``decode_text``（逻辑未改）。
"""
from __future__ import annotations

from typing import Optional


def decode_text(content: bytes) -> Optional[str]:
    """严格解码：BOM 优先，候选编码全 strict 失败 → None（与「空文件」区分开）。

    旧 filetree 用 ``errors='ignore'`` 把 GBK 文本读成乱码还判可读；``gb18030`` 几乎不抛错，
    但会把无 BOM 的 UTF-16LE 解成含 NUL 的乱码，所以含 NUL 判废。

    :param content: 文件字节。
    :returns: 文本；空字节返回 ``""``；解不出返回 None。
    """
    if not content:
        return ""
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return content.decode("utf-16")
        except UnicodeDecodeError:
            return None
    if content[:3] == b"\xef\xbb\xbf":
        try:
            return content[3:].decode("utf-8")
        except UnicodeDecodeError:
            return None
    for enc in ("utf-8", "gb18030"):
        try:
            text = content.decode(enc)
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            return None
        return text
    return None
