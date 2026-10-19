"""zt.report：报告初稿（zt-report skill 的脚本层，零模型）。

旧仓 engine-service 的「AI 报告初稿」一条线拆成 prepare / agent 写作 / finalize 两半（spec §4.1）。模块：

- :mod:`zt.report.templates`：``report_templates.yaml``（24 套 / 172 章）的读取、章节解析、确认事项；
- :mod:`zt.report.compose`：选材 v2（切块 → 保底 → 块竞争）、系统提示词九条、用户消息分块、``prompt_version``；
- :mod:`zt.report.facts`：金额事实（审定单网格 + 项目级费用表）与〔Fn〕替换；
- :mod:`zt.report.approval_grid` / :mod:`zt.report.sections` / :mod:`zt.report.fields`：审定单与审核报告的确定性读数；
- :mod:`zt.report.guard`：确定性护栏（数字回链、模板话术、程序性陈述、全称否定、转写…）；
  :mod:`zt.report.codes` / :mod:`zt.report.filename_exempt` 是它用到的编码回链与文件名豁免；
- :mod:`zt.report.export`：零依赖手写 OOXML 的初稿 docx（页眉免责声明 + 附录）。选它而不是上游 skill-office 的
  docx 技能：每个 run 显式设 eastAsia 字体、XML 控制字符剔除、附录的待补 / 待核清单从正文数，这些口径旧仓有测试钉着，
  脚本一步出件也不需要 agent 再排版；
- :mod:`zt.report.docx_template`：正式 docx 模板的占位符扫描、替换与登记清单；
- :mod:`zt.report.service` / :mod:`zt.report.cli`：编排与子命令
  ``templates / context / facts / section_prepare / section_finalize / export / fill_template``。
"""
