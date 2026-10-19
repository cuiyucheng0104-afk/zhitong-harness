"""zt.quantity：设计说明 → GB50854 清单框架（zt-quantity skill 的脚本）。

两半式（spec §4.1）：``prepare`` 切片并给出待分类片段 → agent 逐片段给 ``{role, 基码, 排除句编号, why}`` →
``finalize`` 过闸、聚合、覆盖核算 → ``render`` 出四页 xlsx。入口 :mod:`zt.quantity.cli`。

模块：:mod:`~zt.quantity.rules`（确定性规则与告警码）、:mod:`~zt.quantity.segment`（切片器）、
:mod:`~zt.quantity.features`（项目特征槽位）、:mod:`~zt.quantity.prompt`（分类说明与版本）、
:mod:`~zt.quantity.pipeline`（prepare / finalize）、:mod:`~zt.quantity.render`（xlsx）。
"""
