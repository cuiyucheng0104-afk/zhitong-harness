"""旁车文件的命名、查找与读取。

来源：/home/user/zhitong-cost-ai/engine-service/app/files.py（D-01 OCR 旁车部分）。
改动：去掉租户子树授权与 HTTP 异常；根目录由调用方传入（项目缓存目录）；越界的候选降级为未命中并写
stderr 日志，不抛错（旁车缺席对调用方等同于没有 OCR 文本，不该让整次读取失败）。

命名约定（两种都认，顺序固定，命中哪一种随结果返回）：

1. 追加式 ``合同.pdf.ocr.txt``：保留原扩展名，不会与同名不同类型的文件撞车，优先；
2. 替换式 ``合同.ocr.txt``。

软链逃逸防护：候选是 ``with_name()`` 拼出来的新路径，原件在根目录内不代表它也在。
``合同.pdf.ocr.txt -> /etc/passwd`` 会让任意文件被当正文读出；候选 ``resolve()`` 之后必须仍在根目录内，
指向根目录之内的软链仍合法。
"""
from __future__ import annotations

import logging
from pathlib import Path, PurePath
from typing import Iterator, Optional

from zt.sidecar.format import SidecarDoc, parse_ocr_sidecar
from zt.textextract.decode import decode_text

log = logging.getLogger("zt.sidecar")

OCR_SIDECAR_SUFFIX = ".ocr.txt"


def is_sidecar_name(name: str) -> bool:
    """文件名是否是旁车（忽略大小写，以 ``.ocr.txt`` 结尾）。

    :param name: 文件名。
    :returns: 是旁车时为 True。
    """
    return name.strip().lower().endswith(OCR_SIDECAR_SUFFIX)


def sidecar_names(name: str) -> list[str]:
    """原件文件名 → 按优先级排列的旁车文件名候选；只看名字，不碰磁盘。

    ``合同.pdf`` → ``[合同.pdf.ocr.txt, 合同.ocr.txt]``。

    :param name: 原件文件名（不含目录）。
    :returns: 旁车文件名候选。
    """
    appended = name + OCR_SIDECAR_SUFFIX
    replaced = PurePath(name).stem + OCR_SIDECAR_SUFFIX
    return [appended] if appended == replaced else [appended, replaced]


def iter_sidecars(path: Path, root: Path) -> Iterator[tuple[Path, Path]]:
    """按优先级产出存在、且 ``resolve()`` 后仍在 ``root`` 内的旁车 ``(候选路径, 相对 root 的路径)``。

    :param path: 原件路径。
    :param root: 授权根目录（项目缓存目录）。
    :returns: 迭代器。
    """
    base = root.resolve()
    for name in sidecar_names(path.name):
        cand = path.with_name(name)
        if not cand.is_file():
            continue
        try:
            rel = cand.resolve().relative_to(base)
        except ValueError:
            log.warning("旁车 resolve 后越出根目录，拒认（软链逃逸防护）：%s", cand.name)
            continue
        yield cand, rel


def find_sidecar(path: Path, root: Path) -> Optional[Path]:
    """原件的旁车路径（查找顺序同 :func:`sidecar_names`）。

    :param path: 原件路径。
    :param root: 授权根目录。
    :returns: 第一个存在且未越界的旁车；没有则 None。
    """
    for cand, _rel in iter_sidecars(path, root):
        return cand
    return None


def read_sidecar_doc(path: Path, root: Path) -> Optional[tuple[SidecarDoc, str]]:
    """查原件的旁车并按格式解析。

    旁车存在就返回，哪怕一页都不可用：页级降级要知道「有旁车但第 N 页失败」。追加式候选不可用时
    继续看替换式候选；全部候选都解不出时返回第一个解得出的（不可用的）旁车，没有则 None。

    :param path: 原件路径。
    :param root: 授权根目录。
    :returns: ``(SidecarDoc, 命中的旁车文件名)``；无旁车、越界或全部无法解码时为 None。
    """
    undecodable: list[str] = []
    fallback: Optional[tuple[SidecarDoc, str]] = None
    for cand, _rel in iter_sidecars(path, root):
        try:
            raw = cand.read_bytes()
        except OSError as e:
            log.warning("旁车读取失败：%s（%s）", cand.name, e)
            continue
        text = decode_text(raw)
        if text is None:
            undecodable.append(cand.name)
            continue
        doc = parse_ocr_sidecar(text)
        if doc.usable:
            return doc, cand.name
        fallback = fallback or (doc, cand.name)
    if undecodable:
        log.warning("旁车存在但解码失败，按未命中处理：%s", "、".join(undecodable))
    return fallback


def read_sidecar_text(path: Path, root: Path) -> Optional[tuple[str, str]]:
    """原件旁车的清洗后正文。

    卷头元数据、逐页判定行、占位句、OTSL 标记剥掉，复读折叠，每页 ``## pN`` 锚点；旧式纯文本旁车原样返回。
    「一页可用的都没有」判为未命中：旁车整份是「本页 OCR 连续失败」占位句时，不能当正文。

    :param path: 原件路径。
    :param root: 授权根目录。
    :returns: ``(清洗后的正文, 命中的旁车文件名)``；无旁车 / 无可用页 / 越界时为 None。
    """
    hit = read_sidecar_doc(path, root)
    if hit is None:
        return None
    doc, name = hit
    if not doc.usable:
        if doc.fmt == "paged":
            log.warning("旁车一页可用的都没有，按未命中处理：%s 页判定=%s", name, doc.verdict_counts())
        else:
            log.warning("旁车无有效文本，按未命中处理：%s", name)
        return None
    return doc.render_text(), name
