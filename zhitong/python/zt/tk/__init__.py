"""zt.tk：投控异常检测（只产疑似）与人工复核记录。

:mod:`zt.tk.engine` / :mod:`zt.tk.align` 是旧 ``tk_engine.py`` / ``tk_align.py``；阈值在 ``data/tk_detect.yaml``
（版本 v1-20260711，客户侧仍为 draft）。:mod:`zt.tk.service` 是请求与结果信封，:mod:`zt.tk.review` 是只追加的
``复核.jsonl``，:mod:`zt.tk.cli` 是 ``python -m zt.tk.cli detect|review|progress``。
"""
