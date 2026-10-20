"""知识库：一级目录映射（未映射报错）、显示名还原、占位旁车删除、每个子目录 README、knowledge-seed 合入且不带 _tools/。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from zt.common import ZtError
from zt.migration.knowledge import load_knowledge_map
from zt.migration.relayout import ZHITONG_ROOT

from tests.migration import _support as S


def _knowledge(tmp: Path, world: dict) -> Path:
    root = tmp / "nas" / "knowledge" / "1"
    files = {
        "定额__12/浙江定额(1).pdf": b"%PDF quota",
        "定额__12/浙江定额(1).pdf.ocr.txt": S.PAGED_ALL_FAILED.encode("utf-8"),
        "规范__13/清单/GB50854.pdf": b"%PDF norm",
        "规范__13/清单/GB50854.pdf.ocr.txt": S.PAGED_OK.encode("utf-8"),
        "规范__13/Thumbs.db": b"junk",
        "其他资料__14/公司做法.docx": b"practice",
    }
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    rows = world["rows"].read_text(encoding="utf-8")
    rows += json.dumps({"table": "knowledge_file", "id": "k1", "category_id": "12", "item_type": 0,
                        "relative_parent_folder": "/定额__12", "disk_relative_parent_folder": "/定额__12",
                        "file_name": "浙江定额.pdf", "disk_file_name": "浙江定额(1).pdf", "sys_company_code": "1",
                        "del_flag": 0}, ensure_ascii=False) + "\n"
    world["rows"].write_text(rows, encoding="utf-8")
    return root


def _seed(tmp: Path) -> Path:
    seed = tmp / "seed"
    for rel, text in {"README.md": "# seed 根说明\n", "规范/README.md": "# 规范\n\n种子说明。\n",
                      "规范/清单编码/码表.md": "# 码表\n\n> 来源：合成测试夹具\n> 生成：2026-10-19\n", "_tools/gen.py": "print(1)\n",
                      "定额/_tools/x.py": "x\n"}.items():
        p = seed / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return seed


@pytest.fixture()
def world(tmp_path: Path) -> dict:
    w = S.write_world(tmp_path)
    w["knowledge"] = _knowledge(tmp_path, w)
    w["export"] = S.export(w)
    return w


def test_unmapped_category_fails_loud(world: dict) -> None:
    code, res = S.relayout(world, world["export"], "--knowledge", str(world["knowledge"]))
    assert code == 2 and res["error"]["code"] == "knowledge_unmapped"
    assert "其他资料__14" in res["error"]["message"]
    assert not (world["root"] / "out").exists()


def test_knowledge_layout_readmes_and_seed(world: dict, tmp_path: Path) -> None:
    kmap = tmp_path / "kmap.yaml"
    default = (ZHITONG_ROOT / "migration" / "data" / "knowledge_map.yaml").read_text(encoding="utf-8")
    kmap.write_text(default.replace("exact: {}", "exact: {其他资料: 公司经验}"), encoding="utf-8")
    code, res = S.relayout(world, world["export"], "--knowledge", str(world["knowledge"]), "--knowledge-map", str(kmap),
                           "--knowledge-seed", str(_seed(tmp_path)), "--link", "copy")
    assert code == 0, res
    m = S.manifest(world)
    paths = {f["path"] for f in m["files"]}
    assert "知识库/定额/定额/浙江定额.pdf" in paths                   # 去 __id，磁盘名还原
    assert "知识库/规范/规范/清单/GB50854.pdf.ocr.txt" in paths
    assert "知识库/公司经验/其他资料/公司做法.docx" in paths
    assert "知识库/规范/清单编码/码表.md" in paths
    assert not any("_tools" in p for p in paths)
    generated = {f["path"] for f in m["files"] if f["kind"] == "generated"}
    assert {"知识库/README.md", "知识库/规范/README.md", "知识库/定额/定额/README.md"} <= generated
    reasons = {d["old_rel"]: d["reason"] for d in m["deletions"] if d["group"] == "知识库"}
    assert reasons == {"定额__12/浙江定额(1).pdf.ocr.txt": "ocr_placeholder_sidecar", "规范__13/Thumbs.db": "system_junk"}
    mirror = world["root"] / "out" / "mirror"
    for sub in ("规范", "定额", "费率", "模板", "公司经验"):
        assert (mirror / "知识库" / sub / "README.md").is_file()
    norm = (mirror / "知识库" / "规范" / "README.md").read_text(encoding="utf-8")
    assert norm.startswith("# 规范\n\n种子说明。") and "## 旧系统迁入" in norm and "`规范/` 1 个文件" in norm and "`knowledge/1`" in norm
    quota = (mirror / "知识库" / "定额" / "README.md").read_text(encoding="utf-8")
    assert "`定额/浙江定额.pdf`" in quota                              # 没有可用旁车的 PDF 列出
    code, res = S.verify(world, world["export"])
    assert code == 0, res
    # 镜像的 知识库/ 通过 zt-knowledge 的目录与来源检查（每个目录都有 README.md）
    check = subprocess.run([sys.executable, str(ZHITONG_ROOT / "skills" / "zt-knowledge" / "scripts" / "check_knowledge.py"),
                            "--root", str(mirror / "知识库")], capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout
    assert (mirror / "知识库" / "定额" / "定额" / "README.md").read_text(encoding="utf-8").count("`定额__12/`") == 1


def test_real_knowledge_seed_layout(world: dict) -> None:
    seed = ZHITONG_ROOT / "knowledge-seed"
    code, res = S.relayout(world, world["export"], "--knowledge-seed", str(seed))  # 项目文件硬链接，seed 总是复制
    assert code == 0, res
    paths = {f["path"] for f in S.manifest(world)["files"]}
    expected = {f"知识库/{p.relative_to(seed).as_posix()}" for p in seed.rglob("*")
                if p.is_file() and p.relative_to(seed).parts[0] in ("规范", "定额", "费率", "模板", "公司经验")}
    assert expected and expected <= paths
    assert not any(p.startswith("知识库/_tools") for p in paths)
    mirror = world["root"] / "out" / "mirror" / "知识库"
    check = subprocess.run([sys.executable, str(ZHITONG_ROOT / "skills" / "zt-knowledge" / "scripts" / "check_knowledge.py"),
                            "--root", str(mirror)], capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout


def test_knowledge_map_validation(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("rules:\n  - { contains: 定额, to: 杂项 }\n", encoding="utf-8")
    with pytest.raises(ZtError) as e:
        load_knowledge_map(bad)
    assert e.value.code == "knowledge_map_invalid"
    km = load_knowledge_map(ZHITONG_ROOT / "migration" / "data" / "knowledge_map.yaml")
    assert km.resolve("浙江2018定额__7") == "定额" and km.resolve("取费文件__9") == "费率"
    assert km.resolve("其他__3") is None and km.resolve(None) is None
