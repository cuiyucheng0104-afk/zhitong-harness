# zt-report 数据

| 文件 | 内容 | 来源 | 签核状态 |
|---|---|---|---|
| `report_templates.yaml` | 24 套 AI 初稿模板 / 172 章：每章 `code/title/seq/rag_query/gen_prompt/excludes/claims/facts_allowed/attachment_hints` | 旧仓 `engine-service/app/engine/data/report_templates.yaml`（zhitong-cost-ai@991ff5c），**逐字节原样**迁入：sha256 `3fefa8cacdf406cadd2da2869c43ffcd269faa6f7276c4dce6fb9e90ca2df717`，161035 字节 | 【待签核】旧仓没有签核记录；章节骨架按造价咨询惯例自审，不能替代持证造价工程师签核 |
| `docx-templates/*.docx` | 19 份正式报告模板：扩充包 16 份 + 起步包 3 份，`{名称}` 占位符 | 旧仓 `docs/报告模板扩充包/`、`docs/报告模板起步包/`，原样迁入（sha256 见 `manifest.json`，扩充包 16 份与旧登记清单逐份相同） | 【待签核】同上；起步包是「客户正式模板到位前」的替代品 |
| `docx-templates/source-manifest-扩充包.json` | 旧仓扩充包登记清单（分类、来源、章节标题、金额格数） | 旧仓 `docs/报告模板扩充包/templates_manifest.json`，原样迁入 | 随模板 |
| `docx-templates/mapping.yaml` | 正式模板 ↔ AI 初稿模板码对照 | W3 新写 | 【待签核】 |
| `docx-templates/manifest.json` | 19 份模板的 sha256、占位符集合、【待补】处数、对照模板码 | `zt.report.docx_template.build_manifest` 重算写出，不手工登记 | 随模板 |

`report_templates.yaml` 不加文件头：它要与旧仓逐字节相同（tests/report 按上面的 sha256 核对），签核状态记在本表。

每章的 `prompt_version` 不写在 YAML 里，由 `zt.report.compose.prompt_version`（系统提示词 + 章节进提示词的字段，sha256 前 16 位）现算；172 章逐章与旧引擎相同（金标 `zhitong/python/tests/report/fixtures/prompt_versions.json`）。改了任何一章进提示词的字段，那一章的版本号就变；改了系统提示词或分块格式，要升 `PROMPT_TEMPLATE_VERSION`（当前 `ws24-6`）并重做金标。

`section code` 是单章重写的定位键，月报以外不要改（tests/report 钉着全部章节码）。

重写 docx 登记清单：

```sh
cd zhitong/python
uv run python -c "import json; from pathlib import Path; from zt.report.docx_template import build_manifest; d=Path('../skills/zt-report/data/docx-templates'); (d/'manifest.json').write_text(json.dumps(build_manifest(d), ensure_ascii=False, indent=1)+'\n', encoding='utf-8')"
```
