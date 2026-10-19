"""文本抽取：PDF 文字层 / 文本类 / xlsx / docx / pptx / 老 Office 格式，扫描页回落到旁车。

只有两种正文来源：``text_layer``（文件自带文字）与 ``ocr_sidecar``（并列的 ``.ocr.txt`` 旁车）。
两者都没有时 ``text_source="none"``，失败码 ``needs_vision``，由 agent 用 ``read_image`` 看图；
本仓不调用 OCR 服务。

模块（本文件不做导入，避免与 :mod:`zt.sidecar` 循环引用，请从子模块导入）：

- :mod:`zt.textextract.extract`：统一出口 ``extract_document`` 与按项目目录读取的 ``load_document``；
- :mod:`zt.textextract.model`：``DocText`` 等数据类；
- :mod:`zt.textextract.pdf` / ``xlsx`` / ``office`` / ``docx_reader``：各格式抽取器；
- :mod:`zt.textextract.files`：项目目录内的安全路径解析；
- :mod:`zt.textextract.cli`：``python -m zt.textextract.cli extract``。
"""
