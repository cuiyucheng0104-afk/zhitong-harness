"""资料盘点（zt-project）与项目文件读写（项目说明、案例索引）。

盘点：扫描项目目录，按文件名与祖先目录给文件定类目（内存里，不写标签），再按咨询类型与阶段口径核对资料清单，
只报缺件。模块：

- :mod:`zt.inventory.rules`：分类规则引擎（文件名 + 目录两层）；
- :mod:`zt.inventory.checklist`：清单与阶段累计口径；
- :mod:`zt.inventory.audit`：按证据定级的清单核查；
- :mod:`zt.inventory.scan`：目录扫描与盘点入口 ``inventory``；
- :mod:`zt.inventory.cli`：``python -m zt.inventory.cli scan``；
- :mod:`zt.inventory.projectdoc` / :mod:`zt.inventory.casebook`：``项目说明.md`` 与 ``案例索引.md`` 的读写，
  zt-project、zt-archive 的脚本共用。

数据文件在 ``zhitong/skills/zt-project/data/``（见 :mod:`zt.inventory.data`）。
"""
