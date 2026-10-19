"""zt.costsheet：广联达等导出的计价表（xlsx/xlsm）解析取数层，核对、指标、投控共用。

模块：

- :mod:`zt.costsheet.parser`：``parse_costsheet`` 表头块、列角色、行分类、费用表分层勾稽（旧 ``costsheet.py``）。
- :mod:`zt.costsheet.warning_codes`：告警码单一真源与 ``warn()``（旧 ``costsheet_warnings.py``）。
- :mod:`zt.costsheet.xlsx_tolerant`：样式表损坏时的容错读取。
- :mod:`zt.costsheet.probe` / :mod:`zt.costsheet.probe_files` / :mod:`zt.costsheet.cli`：预检（不读金额）。
- :mod:`zt.costsheet.service`：三件套共用的读文件、送检上限、结果信封与 ``needs_manual`` 标注。
- :mod:`zt.costsheet.xlsx_out`：工作底稿 xlsx 写出。

``.xls`` 本机不转换：解析返回 ``xls_unsupported``，三件套整次 ``status=insufficient`` 并提示另存为 xlsx。
"""
