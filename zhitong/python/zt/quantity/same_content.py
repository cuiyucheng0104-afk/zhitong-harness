# 来源：engine-service/app/engine/same_content.py（zhitong-cost-ai@991ff5cd，W4 搬入 zt；改动见本文件内「zt 改动」注释）
"""同内容的文件只读一份（实跑整改 WS29-p，issue #970；总纲 K-R43）。

清单框架生成（:mod:`zt.quantity.pipeline`）与概算指标抽取（:mod:`zt.estimate.extract`）共用这一套判定：

- 按**原件字节的 sha256** 分组，不按文件名（同名不同内容不并，不同名同内容要并）；
- 组内按输入顺序，先出现的那份读得出正文就只读它；读不出才轮到下一份。字节相同、结果却可能不同的只有
  两种情形：扩展名不同，或旁车只放在其中一份旁边（旁车按落盘路径找）；
- 告警点名保留的是哪一份，提示词统一叫「内容相同」。
"""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

_CHUNK = 1 << 20


def content_key(content: bytes) -> Optional[str]:
    """内容键：原件字节的 sha256。

    空文件不参与：0 字节的 sha256 全都一样（Windows 右键新建的空文档），并成「同一份」是假的。

    :param content: 文件字节。
    :returns: 十六进制摘要；空文件为 None。
    """
    # zt 改动：旧实现用 app.text_cache.sha256_hex，这里直接用 hashlib。
    return hashlib.sha256(content).hexdigest() if content else None


def file_key(path: Path) -> Optional[str]:
    """同 :func:`content_key`，但按块流式读文件，不把原件整份读进来。

    :param path: 文件路径。
    :returns: 十六进制摘要；空文件为 None。
    """
    if not path.stat().st_size:
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def groups(keys: Sequence[Optional[str]]) -> list[list[int]]:
    """按内容键分组 → 下标组。组按首次出现排序，组内下标升序；键为 None 的各自成组。

    没有重复时结果是 ``[[0], [1], …]``，调用方逐组处理就和逐份处理一模一样。

    :param keys: 每份文件的内容键。
    :returns: 下标组。
    """
    out: list[list[int]] = []
    by_key: dict[str, list[int]] = {}
    for i, k in enumerate(keys):
        if k is None:
            out.append([i])
            continue
        g = by_key.get(k)
        if g is None:
            g = by_key[k] = []
            out.append(g)
        g.append(i)
    return out


def labels(names: Sequence[str]) -> list[str]:
    """告警里给人看的名字。同名的加「第 N 份」：副本常是同名放在两个目录。

    :param names: 文件名或显示路径。
    :returns: 与输入等长的显示名。
    """
    n = Counter(names)
    return [f"{x}（第 {i + 1} 份）" if n[x] > 1 else x for i, x in enumerate(names)]


def message(kept: str, dropped: Sequence[str], verb: str) -> str:
    """「『A』与『B』内容相同，只按『A』生成」。dropped 可以不止一份。

    :param kept: 保留的那份。
    :param dropped: 被合并的副本。
    :param verb: 动词（生成 / 抽取）。
    :returns: 告警文字。
    """
    others = "、".join(f"「{d}」" for d in dropped)
    return f"「{kept}」与{others}内容相同，只按「{kept}」{verb}"
