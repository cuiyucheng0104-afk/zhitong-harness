"""zt.estimate：估算 / 概算（zt-estimate skill 的脚本）。

两段式，抽取不出数、计算才出数：``extract_prepare`` 取关键词窗口 → agent 逐格给 ``{value, quote, scope}`` →
``extract_finalize`` 核引文、解析数值、单体归位；用户确认后 ``suggest`` 正向推算、``compute`` 求值（515 条公式，
四道闸）并写真公式 xlsx。入口 :mod:`zt.estimate.cli`，接线 :mod:`zt.estimate.service`。

模块：:mod:`~zt.estimate.engine`（模板与求值器）、:mod:`~zt.estimate.policy`（模板策略）、
:mod:`~zt.estimate.extract`（抽取后处理）、:mod:`~zt.estimate.suggest`（正向推算）、
:mod:`~zt.estimate.fee_rules`（其他费费率，owner_release）、:mod:`~zt.estimate.checks` / ``gates`` / ``quality``
（闸、告警、质量结论）、:mod:`~zt.estimate.render` / ``xlsx_values``（xlsx）、:mod:`~zt.estimate.warning_codes`。
"""
