# inventory 夹具

- `sample-project/`：合成样例项目（全部虚构，不含真实客户文件）。结算审核项目、阶段「审定」，资料基本齐全，
  故意留出缺件（投标报价文件、造价指标分析）、待确认（`变更资料/签证单汇总.xlsx` 只命中裸词「签证」）和干扰项
  （施工日志、`INDEX.md`、`.ocr.txt` 旁车、`工作/` 下的中间产物）。DWG 是占位字节，不是真实图纸；PDF 正文用英文。
  由 `make_sample_project.py` 生成，改场景改脚本后重新生成：`uv run python tests/inventory/fixtures/make_sample_project.py`。
- `classify_golden.json`、`audit_gt_cases.json`：迁自旧仓 `engine-service/tests/fixtures/ws13_classify_golden.json`、
  `ws13_audit_gt/cases.json`，逐字拷贝（已脱敏，来源写在文件内 `_about` / `_readme`）。
