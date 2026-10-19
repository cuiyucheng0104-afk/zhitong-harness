"""``python -m zt.sidecar.cli``：解析 / 查找旁车。

- ``parse --file X.pdf.ocr.txt``：解析一份旁车，输出逐页判定与清洗后的正文；
- ``locate --root 项目目录 --file 资料/X.pdf``：查原件的并列旁车，输出命中的文件名与可用页。

没有可用页时 ``status=insufficient``，``status_reason=sidecar_unusable``；原件没有旁车时
``status=empty``，``status_reason=no_sidecar``，此时扫描件只能用 ``read_image`` 看图。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from zt.common import Call, Cli, Envelope, WarningItem, WarningLevel, ZtError, empty, insufficient, ok
from zt.sidecar.format import SidecarDoc, parse_ocr_sidecar
from zt.sidecar.locate import read_sidecar_doc
from zt.textextract.decode import decode_text
from zt.textextract.files import resolve_project_file

cli = Cli("zt.sidecar", "OCR 旁车解析与查找（只读，不调用 OCR）")


def _summary(doc: SidecarDoc, name: str | None) -> dict[str, Any]:
    return {
        "sidecar": name,
        "fmt": doc.fmt,
        "usable": doc.usable,
        "declared_pages": doc.declared_pages,
        "usable_pages": doc.usable_pages,
        "quality_suspect": doc.quality_suspect,
        "pages": [{"no": p.no, "verdict": p.verdict, "usable": p.usable, "chars": p.chars,
                   "flags": list(p.flags)} for p in doc.pages],
    }


def _result(doc: SidecarDoc, name: str | None, *, with_text: bool) -> Envelope:
    data = _summary(doc, name)
    if not doc.usable:
        warn = WarningItem(code="sidecar_unusable", level=WarningLevel.WARN,
                           message=f"旁车一页可用的都没有（页判定：{doc.verdict_counts()}）",
                           hint="该文件仍是扫描件：用 read_image 看图")
        return insufficient("sidecar_unusable", warnings=[warn], data=data)
    if with_text:
        data["text"] = doc.render_text()
    warns: list[WarningItem] = []
    if doc.quality_suspect:
        warns.append(WarningItem(code="sidecar_quality_suspect", level=WarningLevel.WARN,
                                 message="旁车 OCR 质量存疑，内容不可全信", hint="关键数字回原件核对"))
    return ok(data, warnings=warns)


@cli.command("parse", help="解析一份旁车文件", arguments=lambda p: p.add_argument("--file", required=True))
def parse(call: Call) -> Envelope:
    """解析一份旁车文件。

    :param call: 调用上下文，``--file`` 为旁车路径。
    :returns: 结果信封。
    :raises ZtError: 文件不存在或无法解码。
    """
    path = Path(call.args.file)
    if not path.is_file():
        raise ZtError("file_not_found", f"文件不存在：{path}")
    text = decode_text(path.read_bytes())
    if text is None:
        raise ZtError("undecodable", f"旁车无法按 UTF-8/UTF-16/GB18030 解码：{path.name}")
    return _result(parse_ocr_sidecar(text), path.name, with_text=True)


def _locate_args(p: Any) -> None:
    p.add_argument("--root", required=True, help="项目目录")
    p.add_argument("--file", required=True, help="原件的项目内相对路径")
    p.add_argument("--with-text", action="store_true", help="同时输出清洗后的正文")


@cli.command("locate", help="查原件的并列旁车", arguments=_locate_args)
def locate(call: Call) -> Envelope:
    """查原件的并列旁车。

    :param call: 调用上下文。
    :returns: 结果信封；无旁车为 ``empty``。
    :raises ZtError: 路径非法或原件不存在。
    """
    root = Path(call.args.root)
    original = resolve_project_file(root, call.args.file)
    hit = read_sidecar_doc(original, root)
    if hit is None:
        return empty("no_sidecar", data={"rel_path": call.args.file})
    doc, name = hit
    return _result(doc, name, with_text=call.args.with_text)


if __name__ == "__main__":
    raise SystemExit(cli.main())
