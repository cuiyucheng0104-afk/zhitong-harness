"""mysqldump 解析：extended insert 多行、转义引号、带列名的 INSERT、跨行语句、gzip、相似表名不误读。"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from zt.common import ZtError
from zt.migration.cli import export_main
from zt.migration.dump import iter_dump_rows, open_dump

from tests.migration._support import run

DUMP = r"""-- MySQL dump 10.13  Distrib 8.0.20
/*!40101 SET NAMES utf8mb4 */;
CREATE DATABASE /*!32312 IF NOT EXISTS*/ `tian_gong_intelligence`;
USE `tian_gong_intelligence`;
DROP TABLE IF EXISTS `project`;
CREATE TABLE `project` (
  `id` varchar(20) NOT NULL DEFAULT '' COMMENT '主键id',
  `sys_company_code` varchar(20) NOT NULL COMMENT '系统所属公司编号',
  `name` varchar(200) NOT NULL DEFAULT '' COMMENT '项目名',
  `report_code` varchar(20) DEFAULT NULL COMMENT '报告书编号',
  `total_amount` decimal(15,2) DEFAULT NULL COMMENT '工程造价（万元）',
  `del_flag` tinyint(1) DEFAULT '0',
  `create_time` timestamp NOT NULL COMMENT '创建时间',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_sys_company_code` (`sys_company_code`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='项目信息表';
LOCK TABLES `project` WRITE;
INSERT INTO `project` VALUES ('1','1','O\'Neil 的\\工程','2025-010',1234.50,0,'2025-02-01 09:00:00'),('2','1','含''单引号''与,逗号(括号)',NULL,NULL,0,'2024-03-01 10:00:00'),('3','1','已删',NULL,NULL,1,'2024-01-01 00:00:00');
UNLOCK TABLES;
CREATE TABLE `project_file_edit_lock` (
  `id` varchar(19) NOT NULL,
  `file_id` varchar(20) NOT NULL
) ENGINE=InnoDB;
INSERT INTO `project_file_edit_lock` VALUES ('x','y');
CREATE TABLE `project_file` (
  `id` varchar(20) NOT NULL,
  `project_id` varchar(20) NOT NULL,
  `relative_parent_folder` text NOT NULL,
  `disk_relative_parent_folder` text NOT NULL,
  `file_name` varchar(255) NOT NULL,
  `disk_file_name` varchar(255) NOT NULL,
  `item_type` tinyint(1) NOT NULL DEFAULT '0',
  `file_info` varchar(64) DEFAULT NULL,
  `history_list` json DEFAULT NULL,
  `sys_company_code` varchar(20) NOT NULL,
  `del_flag` tinyint(1) NOT NULL DEFAULT '0'
) ENGINE=InnoDB;
INSERT INTO `project_file` VALUES ('f1','1','/合同','/合同(1)','施工合同.pdf','施工合同(1).pdf',0,'66.81 KB','[{\"diskRelativeParentFolder\": \"/合同(1)\", \"diskFileName\": \"施工合同(2).pdf\"}]','1',0),
('f2','2','/','/','说明\n第二行.docx','说明\n第二行.docx',0,NULL,NULL,'1',0);
INSERT INTO `project_file` (`id`,`project_id`,`relative_parent_folder`,`disk_relative_parent_folder`,`file_name`,`disk_file_name`,`item_type`,`file_info`,`history_list`,`sys_company_code`,`del_flag`) VALUES ('f3','1','/','/','删.pdf','删.pdf',0,'1 KB',NULL,'1',1);
"""


def _dump(tmp_path: Path, text: str = DUMP, gz: bool = False) -> Path:
    path = tmp_path / ("db.sql.gz" if gz else "db.sql")
    if gz:
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def test_extended_insert_with_escapes(tmp_path: Path) -> None:
    rows = list(iter_dump_rows(open_dump(_dump(tmp_path)), {"project", "project_file"}))
    projects = [r for _db, t, r in rows if t == "project"]
    assert [p["id"] for p in projects] == ["1", "2", "3"]
    assert projects[0]["name"] == "O'Neil 的\\工程"
    assert projects[1]["name"] == "含'单引号'与,逗号(括号)"
    assert projects[1]["report_code"] is None
    assert projects[0]["total_amount"] == "1234.50"
    files = [r for _db, t, r in rows if t == "project_file"]
    assert [f["id"] for f in files] == ["f1", "f2", "f3"]
    assert files[1]["file_name"] == "说明\n第二行.docx"
    assert json.loads(files[0]["history_list"])[0]["diskFileName"] == "施工合同(2).pdf"
    assert {db for db, _t, _r in rows} == {"tian_gong_intelligence"}


def test_similar_table_names_are_not_read(tmp_path: Path) -> None:
    rows = list(iter_dump_rows(open_dump(_dump(tmp_path)), {"project_file"}))
    assert {t for _db, t, _r in rows} == {"project_file"}
    assert all("file_id" not in r for _db, _t, r in rows)


def test_gzip_and_export_counts(tmp_path: Path) -> None:
    out = tmp_path / "export"
    code, res = run(export_main, "--mysql-dump", str(_dump(tmp_path, gz=True)), "--out", str(out))
    assert code == 0, res
    counts = res["data"]["counts"]
    assert counts["project_rows"] == 2 and counts["project_deleted"] == 1
    assert counts["file_rows"] == 2 and counts["file_deleted"] == 1
    files = json.loads((out / "files.json").read_text(encoding="utf-8"))
    f1 = next(f for f in files["files"] if f["id"] == "f1")
    assert f1["display_path"] == "合同/施工合同.pdf" and f1["disk_path"] == "合同(1)/施工合同(1).pdf"
    assert f1["history"][0]["disk_path"] == "合同(1)/施工合同(2).pdf"
    assert f1["size_approx"] == int(66.81 * 1024) and f1["size_tolerance"] > 0
    assert files["deleted_files"][0]["id"] == "f3"
    projects = json.loads((out / "projects.json").read_text(encoding="utf-8"))["projects"]
    assert [p["id"] for p in projects] == ["2", "1"]  # 按 create_time 排序
    assert projects[1]["alias"] == "2025-010" and projects[1]["needs_manual"] is True


def test_insert_without_create_table_fails_loud(tmp_path: Path) -> None:
    text = "INSERT INTO `project` VALUES ('1','1','x');\n"
    with pytest.raises(ZtError) as e:
        list(iter_dump_rows(open_dump(_dump(tmp_path, text)), {"project"}))
    assert e.value.code == "dump_columns_unknown"


def test_truncated_dump_fails_loud(tmp_path: Path) -> None:
    text = DUMP.split("('2','1'")[0] + "('2','1','未结束\n"
    with pytest.raises(ZtError) as e:
        list(iter_dump_rows(open_dump(_dump(tmp_path, text)), {"project"}))
    assert e.value.code == "dump_parse_error"


def test_two_databases_need_explicit_choice(tmp_path: Path) -> None:
    second = DUMP.replace("tian_gong_intelligence", "tenant_3")
    path = _dump(tmp_path, DUMP + second)
    code, res = run(export_main, "--mysql-dump", str(path), "--out", str(tmp_path / "e"))
    assert code == 2 and res["error"]["code"] == "ambiguous_database"
    code, res = run(export_main, "--mysql-dump", str(path), "--database", "tenant_3", "--out", str(tmp_path / "e"))
    assert code == 0 and res["data"]["counts"]["project_rows"] == 2


def test_no_projects_is_an_error_not_empty_success(tmp_path: Path) -> None:
    text = DUMP.split("LOCK TABLES `project` WRITE;")[0]
    code, res = run(export_main, "--mysql-dump", str(_dump(tmp_path, text)), "--out", str(tmp_path / "e"))
    assert code == 2 and res["error"]["code"] == "no_projects"


def test_export_sql_selects_every_column_the_normalizer_reads() -> None:
    import re

    from zt.migration.relayout import ZHITONG_ROOT

    def keys(name: str) -> dict[str, set[str]]:
        text = (ZHITONG_ROOT / "migration" / name).read_text(encoding="utf-8")
        out: dict[str, set[str]] = {}
        for stmt in text.split(";"):
            m = re.search(r"'table', '(\w+)'", stmt)
            if m:
                out[m.group(1)] = set(re.findall(r"'(\w+)', \w+", stmt)) - {"table"}
        return out

    rows = keys("export-rows.sql") | keys("export-knowledge-rows.sql")
    assert {"id", "name", "create_time", "report_code", "del_flag", "sys_company_code", "eng_category",
            "project_node", "scale", "scale_unit_code", "total_amount"} <= rows["project"]
    needed_file = {"id", "relative_parent_folder", "disk_relative_parent_folder", "file_name", "disk_file_name",
                   "item_type", "file_info", "sha256", "history_list", "del_flag", "sys_company_code", "source"}
    assert needed_file | {"project_id"} <= rows["project_file"]
    assert (needed_file - {"source"}) | {"category_id"} <= rows["knowledge_file"]


def test_json_lines_values_typed_like_mysql_json_object(tmp_path: Path) -> None:
    """JSON_OBJECT 的输出：数字是数字、json 列是嵌套数组、日期带微秒；规范化结果与 dump 一致。"""
    lines = [
        {"table": "project", "id": "7", "sys_company_code": "1", "name": "甲", "report_code": None,
         "total_amount": 12.5, "scale": 100, "del_flag": 0, "create_time": "2024-03-01 09:00:00.000000",
         "eng_category": 1, "project_node": 1},
        {"table": "project_file", "id": "a", "project_id": "7", "item_type": 0, "relative_parent_folder": "/x",
         "disk_relative_parent_folder": "/x(1)", "file_name": "a.pdf", "disk_file_name": "a(1).pdf",
         "file_info": "1.5 MB", "sha256": "ABC", "del_flag": 0, "sys_company_code": "1", "source": 1,
         "history_list": [{"diskRelativeParentFolder": "/x(1)", "diskFileName": "a(2).pdf"}]},
    ]
    path = tmp_path / "rows.jsonl"
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")
    code, res = run(export_main, "--json", str(path), "--out", str(tmp_path / "e"))
    assert code == 0, res
    p = json.loads((tmp_path / "e" / "projects.json").read_text(encoding="utf-8"))["projects"][0]
    assert p["create_time"] == "2024-03-01T09:00:00" and p["total_amount_wan"] == "12.5" and p["eng_category_label"] == "房屋建筑工程"
    f = json.loads((tmp_path / "e" / "files.json").read_text(encoding="utf-8"))["files"][0]
    assert f["display_path"] == "x/a.pdf" and f["disk_path"] == "x(1)/a(1).pdf" and f["sha256"] == "abc"
    assert f["history"] == [{"disk_path": "x(1)/a(2).pdf", "sha256": None, "size_text": None}]
    assert f["size_approx"] == int(1.5 * 1024 * 1024)
