"""W8 第一个客户的资料整理与上传（spec §6）：旧库导出、NAS → 桶目录规范的镜像、对账。

- :mod:`zt.migration.dump`：mysqldump 解析；
- :mod:`zt.migration.rows`：``project`` / ``project_file`` / ``knowledge_file`` 行规范化，``projects.json`` 与 ``files.json``；
- :mod:`zt.migration.numbering`：项目编号分配；
- :mod:`zt.migration.relayout`：整理计划与执行（显示名还原、清理、图纸分离、项目说明、案例索引、知识库）；
- :mod:`zt.migration.verify`：镜像对账；
- :mod:`zt.migration.cli`：``zhitong/migration/`` 下三个脚本的入口。
"""
