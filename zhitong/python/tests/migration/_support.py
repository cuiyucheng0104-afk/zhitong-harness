"""migration 测试共用：合成的旧 NAS 目录与旧库行（全部虚构，不含真实客户文件）。

``build_world(tmp)`` 在 ``tmp/nas/project/<project.id>/`` 下按 ``disk_path`` 写文件，同时生成与之对应的
``project`` / ``project_file`` JSON Lines，再用 export 走一遍得到 ``tmp/export/``。每个文件的用意写在 ``FILES`` 的注释里。
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from zt.migration.cli import export_main, relayout_main, verify_main  # noqa: F401  测试经由这里取入口

PAGED_OK = """# 审定单.pdf
> 原始路径: 某项目/扫描/审定单.pdf
> 类型: pdf(OCR) ｜ 引擎: paddleocr-vl-1.6 ｜ 页数: 2 ｜ OCR页: 2 ｜ 时间: 2026-09-29

## p1
> 字符 120 ｜ 异常字符 0.0% ｜ 判定 ok
审定金额合计见下表，审定单位盖章。

## p2
> 字符 3 ｜ 异常字符 0.0% ｜ 判定 failed
（本页 OCR 连续失败未取得任何结果，请查看原件）
"""

PAGED_ALL_FAILED = """# 报告.pdf
> 原始路径: 某项目/扫描/报告.pdf
> 类型: pdf(OCR) ｜ 引擎: paddleocr-vl-1.6 ｜ 页数: 2 ｜ OCR页: 2 ｜ 时间: 2026-09-29

## p1
> 字符 0 ｜ 异常字符 0.0% ｜ 判定 failed
（本页 OCR 连续失败未取得任何结果，请查看原件）

## p2
> 字符 0 ｜ 异常字符 0.0% ｜ 判定 failed
（本页 OCR 连续失败未取得任何结果，请查看原件）
"""

P1, P2, P3, P4, P5 = "1001", "1002", "1003", "1004", "1005"

PROJECTS: list[dict[str, Any]] = [
    # 2024 年建的三个：按 create_time 排出 2024-001、2024-002；P4 的客户编号不是 YYYY-NNN，进别名
    {"id": P1, "name": "某某医院 住院楼/改造", "report_code": None, "create_time": "2024-03-01 09:00:00",
     "eng_category": 1, "project_node": 2, "scale": "12000.50", "scale_unit_code": "m²", "total_amount": "3560.00"},
    {"id": P2, "name": "某小学操场", "report_code": None, "create_time": "2024-05-01 09:00:00",
     "eng_category": 3, "project_node": 1},
    {"id": P4, "name": "某厂房", "report_code": "HT-2024-18", "create_time": "2024-07-01 09:00:00", "project_node": 1},
    # 2025 年：P3 的客户编号本身是 YYYY-NNN，直接用；P5 没有客户编号，接在当年最大值后面
    {"id": P3, "name": "某道路", "report_code": "2025-010", "create_time": "2025-02-01 09:00:00", "project_node": 1},
    {"id": P5, "name": "某公园", "report_code": None, "create_time": "2025-06-01 09:00:00", "project_node": 1},
    # 已删除的项目：跳过并计数
    {"id": "1999", "name": "已删项目", "report_code": None, "create_time": "2024-01-01 09:00:00", "del_flag": 1},
]


@dataclass
class F:
    """一个文件行（或只在磁盘上的文件）。"""

    project: str
    display: Optional[str]          # 显示路径；None = 库里没有记录
    disk: str                       # 磁盘相对路径
    content: Optional[bytes] = None  # None = 只有记录、磁盘上没有
    row_id: Optional[str] = None
    history: tuple[str, ...] = ()


FILES: list[F] = [
    # 显示名还原：磁盘名带 (1)，显示名不带；以及显示名本身就以 (1) 结尾的（不能按后缀猜）
    F(P1, "合同/施工合同.pdf", "合同(1)/施工合同(1).pdf", b"%PDF contract", "f01"),
    F(P1, "结算/报价(1).xlsx", "结算/报价(1)(1).xlsx", b"xlsx quote", "f02"),
    F(P1, "结算/送审计价表.xlsx", "结算/送审计价表.xlsx", b"xlsx submitted", "f03",
      history=("结算/送审计价表(2).xlsx",)),
    # 同 sha256 重复：保留路径最短的
    F(P1, "照片/现场.jpg", "照片/现场.jpg", b"same-photo", "f04"),
    F(P1, "照片/备份/旧/现场副本.jpg", "照片/备份/旧/现场副本.jpg", b"same-photo", "f05"),
    # 旧格式双份：有 docx 的 doc 删除；没有 docx 的 doc 保留
    F(P1, "说明/方案.doc", "说明/方案.doc", b"old doc", "f06"),
    F(P1, "说明/方案.docx", "说明/方案.docx", b"new docx", "f07"),
    F(P1, "说明/单独.doc", "说明/单独.doc", b"lonely doc", "f08"),
    F(P1, "表/汇总.xls", "表/汇总.xls", b"old xls", "f09"),
    F(P1, "表/汇总.xlsx", "表/汇总.xlsx", b"new xlsx", "f10"),
    # 旁车：分页可用的跟着原件改名保留；整份占位的删除
    F(P1, "扫描/审定单.pdf", "扫描/审定单(1).pdf", b"%PDF approved scan", "f11"),
    F(P1, None, "扫描/审定单(1).pdf.ocr.txt", PAGED_OK.encode("utf-8")),
    F(P1, "扫描/报告.pdf", "扫描/报告.pdf", b"%PDF report scan", "f12"),
    F(P1, None, "扫描/报告.pdf.ocr.txt", PAGED_ALL_FAILED.encode("utf-8")),
    # 图纸：DWG 与图纸 PDF 进 图纸/；施工图预算不是图纸
    F(P1, "图纸/建筑/一层平面.dwg", "图纸/建筑/一层平面.dwg", b"AC1027 dwg", "f13"),
    F(P1, "施工图/一层平面图.pdf", "施工图/一层平面图.pdf", b"%PDF drawing", "f14"),
    F(P1, "预算/施工图预算.pdf", "预算/施工图预算.pdf", b"%PDF budget", "f15"),
    # 系统生成物：有记录的 ~$ 临时文件、没记录的 .DS_Store 与 INDEX.md、@eaDir 缩略图
    F(P1, "合同/~$施工合同.docx", "合同(1)/~$施工合同.docx", b"lock", "f16"),
    F(P1, None, ".DS_Store", b"junk"),
    F(P1, None, "INDEX.md", b"# index"),
    F(P1, None, "照片/@eaDir/现场.jpg/SYNOPHOTO_THUMB_S.jpg", b"thumb"),
    # 未登记文件与历史版本：不迁，进清单
    F(P1, None, "未知/多出来.txt", b"orphan"),
    F(P1, None, "结算/送审计价表(2).xlsx", b"old version"),
    # 项目 2：一个普通文件
    F(P2, "招标文件/招标文件.docx", "招标文件/招标文件.docx", b"tender", "f21"),
    F(P3, "设计/设计说明.pdf", "设计/设计说明.pdf", b"%PDF design notes", "f31"),
    F(P4, "图纸/总平面.dxf", "图纸/总平面.dxf", b"0\nSECTION dxf", "f41"),
    F(P5, "资料/审定单.xlsx", "资料/审定单.xlsx", b"approved", "f51"),
]
FOLDERS = [(P1, "空目录", "空目录", "d01"), (P1, "合同", "合同(1)", "d02")]


def _parent(path: str) -> str:
    head = path.rpartition("/")[0]
    return "/" + head if head else "/"


def write_world(tmp: Path, files: list[F] = FILES, projects: list[dict[str, Any]] = PROJECTS) -> dict[str, Path]:
    """写合成 NAS 与 JSON Lines 行文件。

    :returns: ``{"nas", "rows", "root"}``。
    """
    nas = tmp / "nas" / "project"
    lines: list[str] = []
    for p in projects:
        row = {"table": "project", "sys_company_code": "1", "del_flag": 0, "modify_time": p["create_time"]} | p
        lines.append(json.dumps(row, ensure_ascii=False))
    for f in files:
        if f.content is not None:
            target = nas / f.project / f.disk
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.content)
        if f.display is None:
            continue
        history = [{"diskRelativeParentFolder": _parent(h), "diskFileName": h.rpartition("/")[2], "fileInfo": "1 KB"}
                   for h in f.history]
        lines.append(json.dumps({
            "table": "project_file", "id": f.row_id, "project_id": f.project, "item_type": 0,
            "relative_parent_folder": _parent(f.display), "disk_relative_parent_folder": _parent(f.disk),
            "file_name": f.display.rpartition("/")[2], "disk_file_name": f.disk.rpartition("/")[2],
            "suffix": f.display.rsplit(".", 1)[-1], "source": 1, "sys_company_code": "1", "del_flag": 0,
            "file_info": f"{len(f.content)} B" if f.content is not None else "1 KB",
            "history_list": json.dumps(history, ensure_ascii=False),
        }, ensure_ascii=False))
    for pid, display, disk, rid in FOLDERS:
        lines.append(json.dumps({
            "table": "project_file", "id": rid, "project_id": pid, "item_type": 1,
            "relative_parent_folder": "/", "disk_relative_parent_folder": "/", "file_name": display,
            "disk_file_name": disk, "sys_company_code": "1", "del_flag": 0,
        }, ensure_ascii=False))
    # 已删除的记录
    lines.append(json.dumps({"table": "project_file", "id": "f99", "project_id": P1, "item_type": 0,
                             "relative_parent_folder": "/", "disk_relative_parent_folder": "/", "file_name": "删.pdf",
                             "disk_file_name": "删.pdf", "sys_company_code": "1", "del_flag": 1}, ensure_ascii=False))
    rows = tmp / "rows.jsonl"
    rows.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"nas": nas, "rows": rows, "root": tmp}


def run(main, *argv: str) -> tuple[int, dict[str, Any]]:
    """调用脚本入口，返回 ``(退出码, stdout JSON)``。"""
    buf = io.StringIO()
    code = main(list(argv), stdout=buf)
    return code, json.loads(buf.getvalue())


def export(world: dict[str, Path]) -> Path:
    out = world["root"] / "export"
    code, res = run(export_main, "--json", str(world["rows"]), "--out", str(out))
    assert code == 0, res
    return out


def relayout(world: dict[str, Path], export_dir: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    return run(relayout_main, "--export-dir", str(export_dir), "--nas", str(world["nas"]),
               "--out", str(world["root"] / "out"), *extra)


def verify(world: dict[str, Path], export_dir: Path, *extra: str) -> tuple[int, dict[str, Any]]:
    return run(verify_main, "--export-dir", str(export_dir), "--nas", str(world["nas"]),
               "--out", str(world["root"] / "out"), *extra)


def snapshot(root: Path) -> dict[str, tuple[int, int, bytes]]:
    """源目录快照：相对路径 → (大小, mtime_ns, 内容)。"""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns, p.read_bytes())
    return out


def manifest(world: dict[str, Path]) -> dict[str, Any]:
    return json.loads((world["root"] / "out" / "manifest.json").read_text(encoding="utf-8"))
