"""docx / pptx 抽取与 LibreOffice 老格式转换。

来源：/home/user/zhitong-cost-ai/engine-service/app/engine/textextract.py（docx / pptx / soffice 部分）。
改动：docx 解析器改引用 :mod:`zt.textextract.docx_reader`；soffice 超时由环境变量
``SOFFICE_TIMEOUT_SEC`` 改为函数参数（默认 60 秒），可执行文件仍可用环境变量 ``SOFFICE_BIN`` 指定
（安装位置，不是调参）。
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from zt.textextract.docx_reader import read_docx
from zt.textextract.model import DocText, exc_detail as _exc_detail, failed_doc
from zt.textextract.xlsx import safe_xml as _safe_xml

log = logging.getLogger("zt.textextract.office")

SOFFICE_TIMEOUT_SEC = 60.0
_DETAIL_MAX = 200


# =============================================================================
# docx
# =============================================================================


def docx_text(content: bytes) -> str:
    """docx 正文：按「接受全部修订」视图、跳过域指令、还原实体；解析失败返回空串。

    :param content: docx 字节。
    :returns: 正文。
    """
    try:
        return read_docx(content).text()
    except Exception as e:  # noqa: BLE001 —— 非法 docx 不炸管线
        log.warning("docx 抽取失败:%s", e)
        return ""


_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _ole_failure(content: bytes, ext: str) -> Optional[DocText]:
    if not content.startswith(_OLE_MAGIC):
        return None
    if "EncryptedPackage".encode("utf-16-le") in content[:1 << 20]:
        return failed_doc("encrypted", f".{ext} 是加密的 Office 文件（需要打开口令）")
    return failed_doc("parse_failed", f".{ext} 内容是老二进制 Office 格式（OLE），与扩展名不符")


def _docx_doc(content: bytes, ext: str = "docx") -> DocText:
    ole = _ole_failure(content, ext)
    if ole is not None:
        return ole
    try:
        doc = read_docx(content)
    except Exception as e:  # noqa: BLE001
        return failed_doc("parse_failed", f"docx 解析失败：{_exc_detail(e)}")
    flags = list(doc.flags)
    if doc.has_revisions:
        flags.append("has_revisions")
    if doc.has_fields:
        flags.append("has_fields")
    text = doc.text()
    if not text:
        return failed_doc("no_text", "docx 解析成功但没有任何文字", quality_flags=flags)
    return DocText(text=text, text_source="text_layer", quality_flags=flags)


# =============================================================================
# pptx
# =============================================================================

_SLIDE_RE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def pptx_text(content: bytes) -> str:
    """读 `ppt/slides/slideN.xml` 里的 `a:t`，每页前加 `## 幻灯片 N`。失败抛异常。"""
    out: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        slides = sorted(
            (int(m.group(1)), n) for n in z.namelist() if (m := _SLIDE_RE.match(n))
        )
        for no, name in slides:
            root = _safe_xml(z, name)
            if root is None:
                continue
            paras = []
            for p in root.iter(f"{{{_A}}}p"):
                t = "".join(x.text or "" for x in p.iter(f"{{{_A}}}t")).strip()
                if t:
                    paras.append(t)
            if paras:
                out.append(f"## 幻灯片 {no}")
                out.extend(paras)
    return "\n".join(out).strip()


def _pptx_doc(content: bytes) -> DocText:
    try:
        text = pptx_text(content)
    except Exception as e:  # noqa: BLE001
        return failed_doc("parse_failed", f"pptx 解析失败：{_exc_detail(e)}")
    if not text:
        return failed_doc("no_text", "pptx 解析成功但幻灯片里没有文字")
    return DocText(text=text, text_source="text_layer")


# =============================================================================
# LibreOffice 转换
# =============================================================================


def _soffice_bin() -> str | None:
    """LibreOffice 可执行路径:env SOFFICE_BIN 优先(部署显式指定),否则 PATH 查找。"""
    env = os.getenv("SOFFICE_BIN")
    if env:
        return env if os.path.exists(env) else None
    return shutil.which("soffice") or shutil.which("libreoffice")


def libreoffice_convert_ex(content: bytes, src_ext: str, target_ext: str, *,
                           timeout: float | None = None) -> tuple[bytes | None, str]:
    """老格式 → 新格式的 headless 转换。

    每次用独立 UserInstallation profile（临时目录内），避免并发转换抢单实例 profile 锁。

    :param content: 源文件字节。
    :param src_ext: 源扩展名（不带点），如 ``doc``。
    :param target_ext: 目标扩展名，如 ``docx``。
    :param timeout: 本次转换的秒数上限；None 取 :data:`SOFFICE_TIMEOUT_SEC`。
    :returns: ``(产物字节 | None, 失败原因)``；失败原因覆盖未安装 / 超时 / 返回码 / 产物缺失 / 异常。
    """
    limit = SOFFICE_TIMEOUT_SEC if timeout is None else max(1.0, float(timeout))
    soffice = _soffice_bin()
    if not soffice:
        log.warning(
            "soffice 未装(部署项:macOS `brew install --cask libreoffice` / "
            "Linux `apt install libreoffice-calc libreoffice-writer`),.%s 无法转换抽取",
            src_ext,
        )
        return None, "soffice 未安装"
    try:
        with tempfile.TemporaryDirectory(prefix="ztconv_") as tmp:
            src = os.path.join(tmp, f"in.{src_ext}")
            with open(src, "wb") as f:
                f.write(content)
            profile = os.path.join(tmp, "luser")
            # as_uri() 跨平台生成合法 file URI(旧写法 f"file://{profile}" 在 Windows 上畸形)
            proc = subprocess.run(
                [
                    soffice,
                    f"-env:UserInstallation={Path(profile).as_uri()}",
                    "--headless",
                    "--convert-to",
                    target_ext,
                    "--outdir",
                    tmp,
                    src,
                ],
                capture_output=True,
                timeout=limit,
            )
            out = os.path.join(tmp, f"in.{target_ext}")
            if proc.returncode != 0 or not os.path.exists(out):
                err = proc.stderr.decode("utf-8", "ignore")[:_DETAIL_MAX]
                log.warning(".%s→.%s 转换失败 rc=%s err=%s", src_ext, target_ext, proc.returncode, err)
                if proc.returncode != 0:
                    return None, f"返回码 {proc.returncode}：{err}".rstrip("：")
                return None, "soffice 未产出目标文件"
            with open(out, "rb") as f:
                return f.read(), ""
    except subprocess.TimeoutExpired:
        log.warning(".%s 转换超时(>%gs),放弃转换", src_ext, limit)
        return None, f"转换超时（>{limit:g}s）"
    except Exception as e:  # noqa: BLE001 —— 转换异常绝不炸回流管线
        log.warning(".%s 转换异常:%s", src_ext, e)
        return None, f"转换异常：{_exc_detail(e)}"


def libreoffice_convert(content: bytes, src_ext: str, target_ext: str) -> bytes | None:
    """:func:`libreoffice_convert_ex` 的简化包装。

    :param content: 源文件字节。
    :param src_ext: 源扩展名。
    :param target_ext: 目标扩展名。
    :returns: 产物字节；失败返回 None。
    """
    return libreoffice_convert_ex(content, src_ext, target_ext)[0]
