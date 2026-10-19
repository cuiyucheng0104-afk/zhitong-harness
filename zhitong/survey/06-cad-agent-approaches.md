# 让 agent 读 CAD 施工图：PNG 切片之外的开源路线调研

本报告是只读调研，除本文件外没有改动任何文件，也没有安装任何包。前置材料是 `05-cad-viewer.md` 的 §0、§4、§8。

**来源与日期**
- 所有 URL 的访问日期都是 **2026-10-19**，下文不再逐条重复。
- GitHub 的 star 数、许可证、语言、最近推送时间，来自当天通过 GitHub 搜索 API（GitHub MCP `search_repositories`）取得的数值。
- npm 与 PyPI 的版本号，来自当天直接请求 `registry.npmjs.org` 与 `pypi.org`。
- 本环境的 WebFetch 解析不了多数非 GitHub 域名（ezdxf 文档站、arxiv.org、huggingface.co、opendesign.com、formulae.brew.sh、floorplancad.github.io 都报 `ENOTFOUND`）。处理方式：
  - ezdxf 文档改读 GitHub 上的 `.rst` 源文件和源码。
  - 论文改用 Hugging Face MCP 读 `hf://papers/<id>`。
  - Homebrew 改读 `homebrew-core` 的 formula 源文件。
  - 其余事实只拿到搜索引擎摘要，文中标注为 **〔搜索摘要〕**，表示原页面没有打开核对。
- 搜不到的写“搜不到”或“未核实”，没有补猜。

---

## 0. 结论

1. **推荐路线是“结构化优先，图像按需”。** 继续以 05 里已经移植的 TS 解析链（`dxf-parser` → `BuiltScene`）作为主数据源，在它上面做语义工具：图框和标题栏、文字检索与聚类、表格、块和门窗编号计数、轴网、房间。工具返回带句柄和坐标的紧凑表格。PNG 只用于两件事：每个图框一张总览图，用来定位；按需放大的局部图，用来核对。
2. **“PNG 信息量太大”这个担心，按 token 计并不成立。** harness 的 `packages/llm/llm-deepseek/src/image-tokens.ts` 移植了 DeepSeek 官方的 v41 计算器：每张图最多 1024 token，方形图约 1302×1302 px 就到上限，更大的图会被缩小。
3. **PNG 真正的问题是分辨率不够。** 一整张 A1 图（约 1600×1090 px）上，3.5 mm 字高只有约 5–7 px，读不出来。要可靠读字，每张图大约要切 9–16 张（每张约 1k token），而且是有损 OCR。从 DXF 直接取文字，内容是精确的。
4. **文字也不是免费的。** 05 里的样图单文件就有 15,782 条文字，按每条 10–20 token 估算是 15–30 万 token。所以文字工具必须做到按图框、图层、正则、范围过滤，并做聚合，不能整表倾倒。
5. **SVG 不适合直接喂给模型。** 一个平面图框有数万条线段，SVG 文本会到几十万 token。SVG 只适合作为光栅化的中间格式和给人看的产物。
6. **业界做法一致：查询加渲染两条腿。** U-C4N/Autocad-MCP、dwg-mcp-server、rhinomcp 都是“结构化查询（带分页和字段投影）加按需截图”。AECV-Bench 也给出了证据：VLM 读图上文字可达 0.95，但数门窗只有 0.40–0.55。所以计数类问题应该交给确定性代码。
7. **DWG 转换维持 LibreDWG `dwg2dxf` 子进程（GPLv3，进程隔离）。** macOS 可用 Homebrew 的 arm64 bottle 或自行静态构建。ODA File Converter 对非会员只许非商用〔搜索摘要〕，不适合产品。MIT 的 ACadSharp 和 Apache-2.0 的 go-cad 是许可更友好的备选，但都没有在天正图上验证过。

---

## 1. CAD → 结构化文本/JSON 的 CLI 与库

| 项目 | 链接 | Star / 活跃度 | 许可 | 语言 | 无头 | DWG | 中文/GBK |
|---|---|---|---|---|---|---|---|
| ezdxf | https://github.com/mozman/ezdxf | 1482★，最近推送 2026-10-18；PyPI 1.4.5（2026-10-16 上传） | MIT | Python ≥3.10（PyPI `requires_python`），有 macOS arm64/x86_64/universal2、manylinux、win_amd64 的 wheel | 是 | 经 `odafc` 调用 ODA File Converter | `tools/codepage.py` 把 `ansi_936` 映射到 GBK；R2007+ 的 DXF 是 UTF-8 |
| LibreDWG | https://github.com/LibreDWG/libredwg | 1631★，最近推送 2026-10-13；2026-10 连续发布 0.14.86xx 预发布版 | GPL-3.0 | C | 是 | 原生读取所有版本 | 旧 DWG 的约 30 种代码页经 iconv 转成 UTF-8（README） |
| dxf-parser（tiangong 现用） | https://github.com/gdsestimating/dxf-parser | 559★，最近推送 2024-06-20；npm 最新 1.1.2，发布于 2021-11-12 | MIT | TS/JS | 是 | 否 | 自己不处理代码页，tiangong 在外层做 UTF-8/GBK 嗅探（05 §2.3） |
| dxf-json | https://github.com/dotoritos-kim/dxf-json | 131★，最近更新 2026-10-06 | 未核实 | TS | 是 | 否 | 未核实 |
| ACadSharp | https://github.com/DomCR/ACadSharp | 891★，最近推送 2026-10-19 | MIT | C# | 是 | **原生读取 AC1014 及以上**（README 兼容表），写入 AC1014–AC1032（AC1021 除外） | `CadUtils.cs` 把 `ansi_936` 映射到 `CodePage.Gb2312`。注意 GB2312 比 GBK 窄，生僻字有风险，未验证 |
| netDxf | https://github.com/haplokuon/netDxf | 1148★，**已归档**，最后推送 2023-10-11 | MIT | C# | 是 | 否 | 未核实 |
| dxfgrabber | https://github.com/mozman/dxfgrabber | 70★，**已归档**，最后推送 2020-01-01，描述原文为 “Outdated DXF reader, please switch to ezdxf (UNMAINTAINED)” | GitHub 显示 NOASSERTION | Python | 是 | 否 | 不建议使用 |
| libdxfrw | https://github.com/LibreCAD/libdxfrw | 294★，最近推送 2026-10-13 | GPL-2.0 | C++ | 是（库） | topic 标为 dwg-reader，能力范围未核实 | 未核实 |
| kabeja | https://github.com/fuzziness/kabeja | 127★，描述原文为 “NO LONGER MANTAINED!” | 未核实 | Java | 有 CLI | 否 | 未核实 |
| LibreCAD | https://github.com/LibreCAD/LibreCAD | 6511★ | 未核实 | C++ | `librecad dxf2pdf` 文档写明不需要启动 GUI；README 还列出 `dxf2png`、`dxf2svg` 〔搜索摘要，见 https://docs.librecad.org/en/latest/guides/console-tool.html 〕 | 经 libdxfrw | 未核实 |
| go-cad | https://github.com/unitedrhino/go-cad | 54★，创建于 2026-09-29，18 个提交 | Apache-2.0 | Go（零 cgo） | 是 | **自研纯 Go 读取 R9–R2018** | README 称 TEXT/MTEXT/ATTRIB/ATTDEF 支持 GBK 和 UTF-16 解码，内置 CJK 字形渲染 |
| @mlightcad/libredwg-web | https://github.com/mlightcad/libredwg-web | 82★，npm 0.8.1（2026-10-17） | GPL-3.0 | C→WASM | 浏览器和 Node | 是（基于 LibreDWG） | 未提及 |
| mlightcad/cad-viewer | https://github.com/mlightcad/cad-viewer | 1176★；npm `@mlightcad/cad-simple-viewer` 1.7.6 | MIT（npm 元数据） | TS | 浏览器（three.js），无头未核实 | 经 libredwg-web 转换器 | 未核实 |

**ezdxf 要点**

- **CLI 子命令**：读的是 `docs/source/launcher.rst` 和 `src/ezdxf/commands.py`。
  - 有 `audit`、`draw`、`view`、`browse`、`browse-acis`、`strip`、`config`、`info`、`hpgl`。
  - `info` 只有 `-v`、`-s`（统计）两个选项，输出纯文本摘要。
  - `draw` 支持 `--backend {matplotlib,qt,mupdf,custom_svg}`、`--dpi`、`--all-layers-visible`、`-l` 选布局，可以输出 svg/png/pdf 等格式，但没有按图层名过滤的选项。
  - `pp` 只出现在文档的 usage 行；当前 `commands.py` 里没有对应的 `Command` 类，可视为已不存在。
  - `view` 是 PyQt 交互界面，不能无头运行。
- **drawing add-on 的后端**：读的是 `docs/source/addons/drawing.rst`。
  - 可以无头输出的有 `SVGBackend`（不需要 GUI）、`PyMuPdfBackend`（PDF 字节或位图）、`MatplotlibBackend`（`qsave()` 输出 PNG/PDF）、`PlotterBackend`（HPGL/2）、`DXFBackend`、`GeoJSONBackend`、`CustomJSONBackend`、`Recorder`/`Player`。
  - `CustomJSONBackend` 输出的是**几何图元**（`point|lines|path|filled-paths|filled-polygon`，带颜色、线宽、图层），文字被转成填充路径（见 `src/ezdxf/addons/drawing/json.py` 的 `CUSTOM_JSON_SPECS`）。它不是语义 JSON，不适合给模型读文字。
- **渲染配置**（`src/ezdxf/addons/drawing/config.py`）：
  - `TextPolicy` 可选 `FILLING|OUTLINE|REPLACE_RECT|REPLACE_FILL|IGNORE`。其中“用矩形替代文字”正好可以实现 §4 的“文字单独抽出，图里只画线”。
  - `ProxyGraphicPolicy` 可选 `IGNORE|SHOW|PREFER`，可以画出代理实体自带的 proxy graphic。这与天正图有关，见 §7。
  - 另有 `HatchPolicy`、`ColorPolicy`（含 `MONOCHROME`）、`BackgroundPolicy`、`min_lineweight`、`max_flattening_distance`。
- **字体**：〔搜索摘要，见 https://ezdxf.readthedocs.io/en/stable/tools/fonts.html 〕
  - v1.1 起用 fontTools 渲染文字，并支持 `.shx/.shp/.lff` 笔画字体，前提是把字体目录加到 config 的 `support_dirs`。
  - ezdxf 本身不带任何字体文件。
  - BigFont（中文大字体）是否支持，没有在官方文档里查到，**未核实**。
- **odafc**（`docs/source/addons/odafc.rst`）：
  - 需要用户自行安装 ODA File Converter。
  - Windows 自动隐藏 GUI；Linux 可能需要 `xvfb`；**文档原话称 macOS 没有已知的隐藏 GUI 方法**。
  - 文档还警告“执行外部程序是安全风险”。

**LibreDWG 要点**（读的是仓库 `README`）

- 程序及其能力：
  - `dwgread`：输出 JSON、DXF、DXFB、GeoJSON。
  - `dwg2dxf`：README 称约 90% 覆盖。
  - `dwg2SVG`：原文是只处理部分实体、不处理 3D。
  - `dwgbmp`：只能提取 DWG 自带的缩略图，不是渲染。
  - `dwglayers`、`dwggrep`（正则搜文字）。
  - `dwgfilter`：用 jq 过滤 JSON。
- 读取：README 称能读所有版本，个别 R2010+ 高级对象会失败并跳过。
- `dwgread -O JSON` 可以作为第二条结构化通道，但输出是低层对象 dump，体量远大于 DXF，不适合直接给模型。

**ACadSharp 和 go-cad 的意义**：两者都是“不经 GPL 也能读 DWG”的候选，详见 §5。

- go-cad 自带三样东西，正好对应本项目的需求：
  - `dwg2png -sheets`：智能拆图，自动识别图框、提取图号和图名、逐幅出图。
  - `caddocling`：输出 manifest.json，内容是图框、文本、图片清单。
  - SVG 输出带“AI 友好元数据”：图层分组、实体类型、句柄、图纸摘要。
- 但 go-cad 是一个月前才建的项目，README 里质量数字自相矛盾（“34 个 strict 硬门禁”和“62 行 strict 门禁”）。它称“按 LibreDWG 规格逐位对齐修正”，是否属于独立实现，我无法判断。

---

## 2. 面向 LLM/agent 的 CAD 工具与研究

### 2.1 CAD MCP server 和 agent 插件

| 项目 | 链接 | Star | 许可 | 语言 | 无头 | DWG | 喂给模型的方式 |
|---|---|---|---|---|---|---|---|
| U-C4N/Autocad-MCP | https://github.com/U-C4N/Autocad-MCP | 160 | MIT | Python | 是：除连接 AutoCAD 的 COM 后端外，另有基于 ezdxf 的无头后端 | 无头模式下 DWG 读取方式未说明；ODA 只用于写 DWG | 见下方“值得借鉴的设计” |
| dimitrovakulenko/dwg-mcp-server | https://github.com/dimitrovakulenko/dwg-mcp-server | 20 | GPL-3.0 | Rust（worker）+ Python（MCP） | 是 | LibreDWG 子模块 | 见下方“值得借鉴的设计” |
| dongsheng123132/dsh-cad-review | https://github.com/dongsheng123132/dsh-cad-review | 4 | MIT | JS | 是 | **只收 ASCII DXF**，拒绝 DWG 和二进制 DXF | **它就是 DeepSeek Harness 插件**。工具是 `dsh_cad_inspect_dxf` 和 `dsh_cad_review_dxf`。输出是证据：sha256、单位、边界、图层、实体计数、句柄、源文件行号范围。TEXT/MTEXT 只给 sha256 和长度，**不输出文字内容**（与我们的需求相反）。用 `dsh plugin --profile <name> add` 安装 |
| bimwright/dwg-mcp | https://github.com/bimwright/dwg-mcp | 14 | Apache-2.0 | C# | 否，需要运行中的 AutoCAD | 是（AutoCAD） | `dwg_get_selected_texts` 把碎片文字**按空间聚类成句子**（按块、行、列、段落）后返回 |
| daobataotie/CAD-MCP | https://github.com/daobataotie/CAD-MCP | 618 | MIT | Python | 否，Windows COM | AutoCAD、GstarCAD、ZWCAD | 列图层和模型空间实体（带句柄），返回坐标、半径、文字等属性；可截取 CAD 窗口截图 |
| paulio/cadq | https://github.com/paulio/cadq | 0（4 个提交） | 页面未写明 | Python | 是 | 经 ODA FC 转换后用 ezdxf 解析 | 规则本体把图层映射成语义类，结果存进 DuckDB；回答带 `evidence`，指回实体句柄；`cadq plan` 只给出工具调用顺序建议，不执行 |
| mihaicristianfarcas/dwg-takeoff | https://github.com/mihaicristianfarcas/dwg-takeoff | 0 | MIT | Python | 是 | ODA FC | 先由确定性代码生成“可测量项目录”；模型只输出经 schema 校验的 JSON 计划，选择测什么、怎么测；几何引擎负责测量。原文：“The AI never produces a number.” |
| hwdemtv/tianzheng-dwg-parse | https://github.com/hwdemtv/tianzheng-dwg-parse | 2（1 个提交） | MIT | Python | 需要 Windows 和 AutoCAD 的 `accoreconsole` | 天正 T20 原图先导出 T3，再用 accoreconsole `_.DXFOUT` 转出，最后用 ezdxf 解析 | 输出纯文本证据文件。用 y 值聚类拆楼层。作者实测“explode 代理实体对 10MB 级天正图 >5 分钟无产出”，因此放弃了这条路；代理对象按图层计数 |
| neka-nat/freecad-mcp | https://github.com/neka-nat/freecad-mcp | 2948 | MIT | Python | 需要 FreeCAD | 不涉及（3D） | README 提到截图和“text feedback”配置，细节在 docs 里，未展开读 |
| jingcheng-chen/rhinomcp | https://github.com/jingcheng-chen/rhinomcp | 1155 | MIT | Python | 需要 Rhino | 不涉及 | `get_document_summary`、`get_object_info`，加上 `capture_viewport` 截图 |
| Fusion 360 MCP | https://github.com/AuraFriday/Fusion-360-MCP-Server（127★）、https://github.com/Joe-Spencer/fusion-mcp-server（49★） | — | 未核实 | Python | 需要 Fusion | 不涉及 | 未展开 |
| frontsail-ai/aspicio | https://github.com/frontsail-ai/aspicio | 6 | 未核实 | TS | 有 HTTP API 和 MCP | DXF 和矢量 PDF | 未展开 |

**值得借鉴的设计**

- **U-C4N/Autocad-MCP 的读图工具与 token 控制**
  - 读图工具：`drawing_understand`（一次调用给出单位、范围、图层专业分类、标签、房间）、`arch_rooms_detect`（房间面积按围合墙面计算）、门窗表和房间表导出、`drawing_diff`。
  - 渲染：`view_screenshot` 输出 PNG，无头渲染需要额外安装 `[pdf]` extra。
  - token 控制：
    - `TOOL_PROFILE=lean` 把工具目录缩到 65 个，约 22,661 token。
    - `DISCOVERY_MODE=search` 只暴露 2 个工具，约 356 token。
    - `fields=` 做字段投影；`MAX_LIST_LIMIT` 默认 5000。
- **dwg-mcp-server 的工具集**
  - 共 10 个 `dwg.*` 工具。
  - 打开文件时一次建好索引；`query_objects` 支持过滤、投影、分页。
  - `render_view` 以 SVG 为主，PNG 由 SVG 光栅化得到，并在结果里附带“未支持实体的覆盖诊断”。
- 归纳下来，这些项目喂模型的方式分三类：
  - 实体或对象查询，返回 JSON，带句柄、分页、字段投影。
  - 语义摘要，例如房间、门窗表、图层专业。
  - 视口截图，作为辅助。
- **我没有找到任何项目把整张图的 SVG 或实体全集直接塞给模型。**
- 名为 “ezdxf MCP”“dxf-mcp”“cad-agent”“drawing-agent” 的项目：GitHub 搜 `dxf mcp` 有 103 个结果、`dwg mcp` 有 38 个，绝大多数是“让 AI 画图”。
  - 例如 https://github.com/KanJieTeam/kjdraw（74★）、https://github.com/Svetlana-DAO-LLC/cad-agent（51★，build123d 3D 建模）。
  - 都与读施工图无关，不展开。

### 2.2 论文与数据集

| 名称 | 链接 | 要点（摘要原意） | 与本项目的关系 |
|---|---|---|---|
| AECV-Bench（2026-01-08） | https://arxiv.org/abs/2601.04819 （经 `hf://papers/2601.04819` 读取） | 120 张平面图做计数，192 个图纸问答。OCR 和以文字为主的问答最强，最高 0.95；空间推理中等；**符号类理解，尤其门窗计数，仍未解决，常见 0.40–0.55**。作者结论是需要领域表示，以及工具增强、人在环的工作流 | **直接支持“门窗计数不靠看图”** |
| LED-BENCH | https://arxiv.org/html/2610.19571 | 〔搜索摘要〕面向大幅面机械、建筑、交通图纸；最好的模型平均 52.65%；需要整合更大范围证据的问题全部更差 | 支持“先定位再局部看” |
| FloorplanQA（2025-07-10） | https://arxiv.org/abs/2507.07644 ；代码 https://github.com/OldDeLorean/FloorplanQA（4★） | 用 JSON 或 XML 符号化平面布局测试 LLM 的空间推理。浅层问题能答对，但常违反物理约束、空间一致性差 | 结构化输入也不等于能推理。几何计算（面积、距离）应由工具完成，不交给模型 |
| CAD-Assistant（2024-12-18） | https://arxiv.org/abs/2412.13810 | 以 VLLM 作规划器，在 FreeCAD Python API 解释器里迭代执行，工具包含渲染函数 | “代码查询 + 渲染”的 agent 模式；对应 §6 的可选 `cad_query` |
| SVGenius（2025-06-03） | https://arxiv.org/abs/2506.03139 | 2,377 个查询；**所有模型都随 SVG 复杂度系统性退化** | 反对把大 SVG 当文本喂 |
| ZoomEye（2024-11-25） | https://arxiv.org/abs/2411.16044 ；代码 https://github.com/om-ai-lab/ZoomEye（97★） | 把图像当树，子节点是放大的子区域；免训练；InternVL2.5-8B 在 HR-Bench 上提升 15.71% 和 17.69% | “先缩略、再放大”的渐进方案有实证 |
| Set-of-Mark（2023-10-17） | https://arxiv.org/abs/2310.11441 | 在图上打编号标记，可以显著提升细粒度定位 | 渲染时给文字框或块打编号，并与结构化行对应 |
| CAD-Recode / Text2CAD / CADTalk | https://arxiv.org/abs/2412.14042 、https://arxiv.org/abs/2409.17106 、https://arxiv.org/abs/2311.16703 | 分别是点云到 CAD 代码、文本到 3D CAD 序列、CAD 程序语义注释 | 都是 3D 参数化建模，**与读 2D 施工图基本无关** |
| DrawingQA | — | **搜不到同名论文或数据集** | — |

---

## 3. 建筑平面图专用解析

| 项目 | 链接 | Star | 许可 | 输入 | 可直接用于我们的 DXF 吗 |
|---|---|---|---|---|---|
| CubiCasa5k | https://github.com/CubiCasa/CubiCasa5k | 612 | **CC BY-NC 4.0**（仓库 LICENSE 原文），**不可商用** | 栅格图加 SVG 标注，5000 张，80 多类 | 否：栅格户型图，与施工图差异大 |
| FloorPlanCAD 数据集 | https://arxiv.org/abs/2105.07147 ；站点 https://floorplancad.github.io/（未能打开） | — | 未核实 | 1 万多张矢量 CAD 平面图，30 类，标注到线 | 训练数据参考 |
| CADTransformer | https://github.com/VITA-Group/CADTransformer | 137 | MIT | FloorPlanCAD 的 SVG，流程是 SVG → PNG → NPY | 需要转换和训练；没有现成的 DXF 推理 |
| SymPoint（ICLR 2024） | https://github.com/nicehuster/SymPoint | 61 | 未核实 | 矢量图元转成点 | 同上 |
| VecFormer（NeurIPS 2025） | https://github.com/WesKwong/VecFormer | 49 | Apache-2.0 | 线段表示；FloorPlanCAD 上 91.1 PQ | README 没有提预训练权重，只覆盖 FloorPlanCAD 上的训练和评估 |
| ArchCAD-400K | https://arxiv.org/abs/2503.22346 ；模型 `mohansshf/dpss-archcad`（HF） | — | 未核实 | 5538 张图切成 413,062 块 | 大规模建筑图数据集，加上 DPSS 基线模型；数据来源和语种未核实，可作为长期参考 |
| DeepFloorplan / TF2DeepFloorplan | https://github.com/zlzeng/DeepFloorplan（418★）、https://github.com/zcemycl/TF2DeepFloorplan（267★） | — | 未核实 | 栅格 | 否 |
| FloorplanTransformation | https://github.com/art-programmer/FloorplanTransformation | 682 | 未核实 | 栅格转矢量（Lua/Torch） | 否 |
| VecFloorSeg | https://github.com/DrZiji/VecFloorSeg | 67 | 未核实 | 矢量毛坯平面图分割（图注意力） | 思路可参考 |
| U-C4N/Autocad-MCP `arch_rooms_detect` | 见 §2.1 | 160 | MIT | DXF（ezdxf） | **规则法房间检测的可读实现**，可以拿来借鉴算法 |
| shapely | https://github.com/shapely/shapely | 4528 | 未核实 | 几何运算（含 polygonize） | Python 侧做墙线闭合和多边形化的常用工具 |
| go-cad 图框和标题栏 | 见 §1 | 54 | Apache-2.0 | DWG/DXF | README 称能识别非标加长图框，并从标题栏提取图号和图名；算法没有公开说明 |
| tianzheng-dwg-parse | 见 §2.1 | 2 | MIT | 天正 T3 转出的 DXF | 用 y 值聚类拆楼层、按图例映射块名、按图层统计代理实体 |

**要点**

1. **深度学习路线（符号识别）不适合第一期。**
   - 主要数据集是 FloorPlanCAD 和 CubiCasa5k；后者明确禁止商用。
   - 现成仓库都没有给出可直接对 DXF 推理的权重和流程。
   - 天正图是半结构化的：门窗是块，房间名在专门的图层上，可以直接用规则处理。
2. **房间多边形重建**，三种做法按可靠性排序：
   1. 天正自带的房间对象或面积文字。但 05 §4.2 指出，经 dwg2dxf 转换后面积文字会丢失。
   2. 规则几何法：取墙、柱、门、窗所在图层的线段，做端点吸附，在门窗洞口补上封闭线，再 polygonize，最后取包含房间名锚点的最小面。
   3. 栅格泛洪法：把墙、门、窗、柱画进位图，从房间名锚点泛洪填充，再把轮廓矢量化。这种方法对双线墙和小缺口最鲁棒，但面积精度受分辨率限制。
   - 2 和 3 我**没有找到成熟的开源中文施工图实现**。
3. **图框和标题栏识别**：
   - 05 的 `frames.ts` 实际做的是“平面簇聚类”，不是图框识别。
   - 开源可参考的只有 go-cad 和 tianzheng-dwg-parse 的 y 值聚类。
   - 规则思路：
     - 先找图框候选。候选是满足以下任一条件的对象：
       - 闭合矩形，长宽比接近 √2，或者是加长幅面；
       - 块名含“图框/TK/A0–A4”的 INSERT；
       - 内外双框。
     - 再取右下角区域的文字，按“图名、图号、比例、日期”这些键值对匹配。
4. **门窗表和材料表**：
   - 05 的 `extractTable` 已经能识别线网格表格；缺的是“自动找出图上哪里有表格”。
   - 思路：在一块区域里，水平线和垂直线的密度都高，而且区域内有“门窗表”“编号”“洞口尺寸”这类表头文字，就把它当作表格候选。
   - 开源方面只看到 Autocad-MCP 能导出门窗表，另有 https://github.com/jackyjiang76-sketch/cad-text-parser-skill（0★，依赖 AutoCAD 2027 无头转档）。
5. **轴网识别**：**没有搜到开源实现。**
   - 规则思路：
     1. 取轴线图层（05 的正则里有 `AXIS|轴|DOTE`）的长直线，按方向分组。
     2. 把附近“圆加单字符或数字”的轴号气泡挂到轴线上。
     3. 用相邻轴线的间距，或 DIMENSION 实体的实测值（组码 42），算出开间和进深。
   - 天正的具体图层名要用样图核实，本文不臆测。

---

## 4. 渲染方案对比

**前提数字**

- 来源是 harness 的 `packages/llm/llm-deepseek/src/image-tokens.ts` 及其测试 `tests/image-tokens.spec.ts`。文件注释说明它是从 api-docs.deepseek.com 的 image token 计算器（v41 配置）逐字移植的。
- 计费规则：
  - 每个 token 单元覆盖 42×42 px，即 14 px 的 patch 再 3:1 下采样。
  - 每张图上限 1024 token。
  - 测试中的样例：800×800 记 422 token；1920×1080 记 968 token；2048×2048 被缩到 1302×1302，记 994 token；5000×5000 同样记 994 token。
- 第三方博客另有“vision-exp 每图上限 384 token、约 800×800”的说法〔搜索摘要，例如 https://tokencost.app/models/deepseek-v4-flash-vision-exp 〕，与仓库内的 v41 计算器不一致。**以仓库实现和实际 usage 字段为准。**
- 我按上述网格自行推算：A1 横幅（841×594 mm）整张出图，大约是 1600×1090 px、接近 1024 token。此时 3.5 mm 字高约 6–7 px，2.5 mm 字高约 4–5 px。
- “中文要 14 px 以上才能稳定识读”是**未验证的经验假设**。按这个假设，读 3.5 mm 字需要约 3×3 张切片，读 2.5 mm 字需要约 4×4 张切片。

| 方案 | 做法 | token 消耗（定性，带估算） | 信息保真 | 评价 |
|---|---|---|---|---|
| A. 整框 PNG 切片（当前设计） | 每个图框切成 N×M 张高分辨率 PNG | 每张约 1k token；一个 A1 图框 9–16 张，约 9–16k token | 线条形状好；文字靠 OCR，有损；模型给出的坐标需要换算 | 能用但贵，而且读数不精确。门窗计数不可靠（AECV-Bench） |
| B. SVG 文本直接给模型 | 把实体转成 `<path>` 文本 | 按每条线段约 10–15 token 估算，一个平面框数万段，就是几十万 token；超出上下文 | 坐标精确，但模型难以从中形成整体理解（SVGenius 显示复杂度一高就退化） | **不推荐作为模型输入。** 适合作为中间格式和人工查看的产物（dwg-mcp-server、go-cad 都是 SVG→PNG） |
| C. 分层或分图层出图 | 预设“结构（墙、柱、轴）”“洞口（门窗）”“标注”等图层组，按组分别出图 | 每张约 1k token；按问题只出 1–2 张 | 去掉噪声后，单张图的可读性明显提升 | 推荐作为 `cad_render` 的 `layers` 预设 |
| D. 渐进放大 | L0 每个图框一张总览（≤1600 px，约 1k token），图上叠加 A–H×1–8 网格标签；模型说出“放大 C3”，或指定 bbox、句柄、文字命中点，再出 L1 局部图。局部图的比例按“最小字高 ≥14 px”反推 | 典型问题 2–4 张，约 2–4k token | 只在需要的地方用高分辨率 | **推荐。** 有 ZoomEye 支撑；与 05 §3.4 已有的 `world_rect`、`px_per_unit` 元数据兼容 |
| E. 文字单独抽成表，图里只画线 | 文字通过 `cad_text` 精确给出；渲染时把文字画成空框，或标上与表格行对应的短编号 | 文字按需检索：一个图框过滤后通常几百行，每行约 10–20 token（估算），合计数千 token；图本身约 1k | 文字 100% 精确（受 dwg2dxf 转换保真度限制）；图只负责空间关系 | **推荐与 D 组合。** ezdxf 的 `TextPolicy.REPLACE_RECT` 即此思路；编号做法见 Set-of-Mark |
| F. 纯结构化，不出图 | 只回答语义查询：图框、房间、门窗编号计数、表格、轴网 | 每次几百到几千 token | 取决于规则覆盖面；规则漏检时模型没有视觉兜底 | 是主力，但需要 D/E 兜底与核对 |

**结论**：采用 F 为主、D+E 兜底。默认不出图；总览图每个图框只出一张；局部图按需出，并带编号标注；完全放弃“整框高分辨率切满”。

---

## 5. DWG 转换与许可

| 途径 | 现状 | 许可 | 平台 | 结论 |
|---|---|---|---|---|
| LibreDWG `dwg2dxf`（子进程） | GitHub 发布页在 2026-10 连续发布 0.14.86xx **预发布版**，说明里写 “libredwg windows nightly”；发布页的附件列表没有加载出来，具体文件名未核实。tiangong CI 用的是官方 `libredwg-0.14-win64.zip`（05 §2.1） | GPL-3.0 | Windows 有官方 zip；Linux 从源码构建；macOS 见下行 | **保留。** 维持 05 §2.4 的进程隔离方案 |
| Homebrew `libredwg` | `homebrew-core/Formula/lib/libredwg.rb`：版本 0.14，`GPL-3.0-or-later`；bottle 有 `arm64_golden_gate`、`arm64_tahoe`、`arm64_sequoia`、`arm64_sonoma`、`arm64_linux`、`x86_64_linux`。**没有 Intel macOS 的 bottle**。搜索引擎摘要里显示的 0.13.3 是旧缓存 | GPL-3.0+ | macOS arm64、Linux | 开发机可用。**产品分发不宜依赖用户安装 brew**：bottle 链接 Homebrew 前缀下的动态库，仍应按 05 §8.4 在 CI 里静态构建 |
| LibreDWG 官方 macOS 二进制 | 发布页没有看到 macOS 附件（附件列表未加载，05 也记录“没有官方 macOS 二进制”） | — | — | 自建 |
| ODA File Converter（含 ezdxf `odafc`） | ODA 官方 FAQ 称免费的 ODA Viewer 和 ODA File Converter **非会员只能用于非商业用途**〔搜索摘要，https://www.opendesign.com/faq/question/what-are-oda-viewer-and-oda-file-converter ，页面约 1.5 年前〕。Repology 把 Linux 包标为 “Unfree / all-rights-reserved”〔搜索摘要，https://repology.org/project/oda-file-converter/information 〕。ezdxf 文档称 macOS 无法隐藏它的 GUI | 专有 | Win/Linux/mac | **产品里不用。** 只允许用户自装后作为可选后端（cadq、dwg-takeoff 都是这样做的），并在文档里写清许可责任 |
| `@mlightcad/libredwg-web`（WASM） | npm 0.8.1（2026-10-17）；README 称浏览器和 Node 都能用 | GPL-3.0 | 全平台 | **不用。** 在进程内加载 WASM，GPL 隔离论点不成立（05 §2.4 已明令禁止） |
| ACadSharp | MIT；DWG 读取支持 AC1014 及以上；`ansi_936` 映射到 GB2312 | MIT | .NET 运行时（是否需要随包或能否 AOT 发布，未核实） | **许可上最好的备选。** 需要用 05 的 `fixture_t3.dwg` 和天正样图验证保真度，以及中文生僻字 |
| go-cad | Apache-2.0；纯 Go 可交叉编译成单个静态二进制；有 `caddocling` 和拆图出图 | Apache-2.0 | 理论上全平台；仓库没有发布预编译包 | **值得跟踪评估。** 风险是项目极新，且“按 LibreDWG 规格逐位对齐”的实现来源没有说明 |
| AutoCAD `accoreconsole` | tianzheng-dwg-parse 的路线：天正 T20 先导出 T3，再 `_.DXFOUT` | 需要 AutoCAD 授权 | 仅 Windows | 只适合用户自有 AutoCAD 的场景，不能作为默认 |
| dwg-mcp-server | Rust 加 LibreDWG，发布 macOS arm64、Win x64、Linux 二进制 | GPL-3.0 | 三平台 | 作为独立进程的 MCP 服务器接入时，许可边界与 dwg2dxf 相同；可以拿来参考 API 设计 |

---

## 6. 推荐的插件设计

### 6.1 原则

1. **默认只回文本，不回图。** 每个工具都返回紧凑的 TSV 风格表格，第一行是列名，每行带 `handle` 或 `id` 和世界坐标，可以追溯到原实体。工具都带 `limit` 和 `truncated` 标志；超出部分写到 spill 文件，只返回路径。
2. **能数的不看。** 计数、面积、长度、表格一律由确定性代码给出，模型只负责规划和解释。dwg-takeoff 的原则是“AI 不产生数字”，AECV-Bench 的门窗计数结论也支持这一点。
3. **看图用来定位和核对，不用来读数。** 出图走 §4 的 D+E 方案。
4. **单位门禁**：沿用 05 §6 第 3 章的约定，单位未确认时，带量纲的工具拒绝执行。

### 6.2 工具清单

| 工具 | 输入 | 输出 | 底层 |
|---|---|---|---|
| `cad_open` | `path`，`force?` | 文档摘要：`doc_id`、sha256、格式嗅探结果、dwg2dxf 版本、编码、单位证据、图层数、文字数、块数、跳过的实体、警告 | 05 已有设计 |
| `cad_sheets` | `doc_id` | 每个图框一行：`frame_id`、bbox、面积、**图名**、**图号**、**比例**、楼层标签猜测及置信度、文字数、块数 | 新做：图框规则（§3 要点 3）加标题栏键值匹配加“X 层平面图”正则。`frames.ts` 的聚类结果作为兜底 |
| `cad_layers` | `doc_id`，`frame_id?` | 每个图层一行：线段数、文字数、块数，外加 3 条样例文字 | 05 已有设计，加样例文字 |
| `cad_text` | `doc_id`，`frame_id?`，`layer?`，`query?/regex?`，`bbox?`，`group:'none'\|'line'\|'paragraph'`，`limit` | 每条一行：`id`、文字、x、y、字高、图层、`frame_id`。`group` 不是 `none` 时，先按空间聚类把碎片合成行或段 | `scene.texts` 加聚类（借鉴 bimwright/dwg-mcp 的按行、列、段落分组） |
| `cad_count` | `doc_id`，`frame_id?`，`by:'block'\|'label'`，`pattern?` | 按块名计数，带属性值和每个图框的分布；或按**门窗编号文字**计数，如 `/^(F?M\|C\|MLC\|TLM)[\w-]*\d{3,4}/`，带每个编号的坐标列表 | `countBlocks` 加文字正则计数（新做）。两种计数互相印证 |
| `cad_tables` | `doc_id`，`frame_id?` | 先列出表格候选：bbox、表头文字、行列数 | 新做：线密度检测加表头关键字 |
| `cad_table` | `doc_id`，`table_id\|rect` | 表格内容的 Markdown 或 CSV，外加 CSV 文件路径 | `extractTable` |
| `cad_axes` | `doc_id`，`frame_id` | 轴号序列，每个轴号的坐标，开间和进深尺寸，DIMENSION 实测值 | 新做（§3 要点 5） |
| `cad_rooms` | `doc_id`，`frame_id`，`method:'text'\|'geom'\|'raster'` | 每个房间一行：房间名、文字面积、几何面积、差异、多边形文件路径、`matched` 状态 | `checkRooms`，再补上 §3 要点 2 的第二、三种方法 |
| `cad_render` | `doc_id`，`target:{frame_id}\|{rect}\|{around:{x,y,r}}\|{cell:'C3'}`，`preset:'all'\|'structure'\|'openings'\|'annotation'`，`text:'draw'\|'boxes'\|'ids'\|'none'`，`grid?:true`，`min_text_px?:14` | 一张 PNG 的路径，外加 `world_rect`、`px_per_unit`、网格对照表、图中编号与 `cad_text` 行 `id` 的对应表 | 05 §3 选型（`@napi-rs/canvas`）。**单次调用只出一张图**；出图比例按 `min_text_px` 反推；区域过大时拒绝执行，并建议使用 `cell` 参数 |
| `cad_diff` | `old_doc`，`new_doc`，`frame_id?` | 文字新增和删除列表、块计数差、表格差、线段增删计数；可选输出差异图 | `diffScenes`，加上新做的文字、块、表格级差异 |
| `cad_query`（可选） | 一段 TS 程序，运行在 harness 的 `ptc-runtime-node` 里，绑定只读的 scene API | 程序打印的结果 | 模型自己写过滤和聚合，避免逐个增加工具（CAD-Assistant 的模式）。依赖 PTC 沙箱，第二期再考虑 |

### 6.3 结构化读取用哪个库

- **主路径用现有的 TS 链**（`dxf-parser` 加 tiangong 的 `buildScene`）。
  - 理由：已经针对 GBK、天正图层、`$DorLib2D$` 块调过；harness 插件也是 TS。
  - harness 的 Python 后端仍是 experimental（`packages/ptc-runtime/README.md`），把 Python 运行时塞进桌面安装包代价大。
- **ezdxf 作为可选的旁路校验和增强**：本机有 Python 时，用 bash 调脚本。适合做这几件事：
  1. 按 `$DWGCODEPAGE` 正确解码，以及 `recover` 模式读取损坏文件。
  2. 读取 MTEXT 纯文本和块属性 ATTRIB。
  3. 用 `ProxyGraphicPolicy` 读出代理实体的 proxy graphic（天正图）。
  4. 用 `SVGBackend` 加 `TextPolicy.REPLACE_RECT` 快速做出图原型。
  - 用 ezdxf 对同一张样图的文字数、块数做对拍，可以暴露 `dxf-parser` 的漏读。
- **不引入 netDxf、dxfgrabber、kabeja**：三者都已归档或停止维护。

### 6.4 什么时候出图，怎么出

- **出图的触发条件**，只有三种：
  1. 模型需要理解空间关系，例如“这个房间在哪”“门的开向”。
  2. 结构化结果与预期不符，需要人工核对。
  3. 用户明确要求看图。
- **出图顺序**：
  1. 先出 L0：一个图框一张，预设 `structure`，`text:'boxes'`，带网格。
  2. 再按需出 L1：用 `cell`、`around` 或句柄定位，`text:'ids'`，按 `min_text_px` 定比例。
  3. 每张图约 1k token，一次问答控制在 2–4 张。
- **不输出 SVG 给模型。** 如果确实需要 SVG（给人看，或者走 resvg 渲染），只作为文件产物。

### 6.5 DWG 转换路径与许可处理

- 查找顺序沿用 05 §8.4：`Config.dwg2dxfPath` → 环境变量 → 随包附带的二进制 → PATH。
- 产品只随包附带 LibreDWG（GPLv3，独立子进程）。合规材料和 IP 律师确认的要求不变（05 §2.4）。
- macOS：
  - CI 用 `--disable-shared` 静态构建 arm64 和 x64 两个版本。
  - Homebrew 只是开发便利：只有 arm64 bottle，没有 Intel bottle。
- `DwgConverter` 接口保持通用，预留三种实现：
  - ACadSharp：MIT，需要 .NET。
  - go-cad：Apache-2.0。
  - 用户自装的 ODA FC：非商用限制由用户承担。
- 先用样图评估这些实现的保真度，再决定是否替换 LibreDWG。

### 6.6 工作量估计（1 名熟悉 TS 的工程师，含单测和快照）

| 项目 | 人日 |
|---|---|
| 搬运 core 和 convert，实现 `cad_open`、`cad_layers`、`cad_text`（含聚类） | 5–7 |
| `cad_sheets`：图框、标题栏、楼层标签启发式 | 4–6 |
| `cad_count`：块计数加门窗编号计数 | 2–3 |
| `cad_tables` 和 `cad_table`：自动找表 | 3–5 |
| `cad_axes` | 3–5 |
| `cad_rooms`：补几何法和栅格法 | 6–10 |
| `cad_render`：L0/L1、预设、编号、网格 | 5–7 |
| `cad_diff`：文字、块、表格级差异 | 3–5 |
| macOS 和 Windows 的 dwg2dxf 构建与冒烟测试，以及许可材料 | 5–8 |
| ACadSharp 和 go-cad 的保真度评估（可选） | 3–5 |
| **合计** | **约 39–61 人日（8–12 周）**；第一期只做前 3 行加 `cad_render`，约 3–4 周 |

---

## 7. 风险与未验证事项

1. **天正原生 T20 图的代理实体。**
   - LibreDWG 能否保留 `ACAD_PROXY_ENTITY` 的 proxy graphic 数据，**没有查到资料**。
   - ezdxf 能在 DXF 里画出 proxy graphic，但前提是转换器把这些数据写进了 DXF。
   - tianzheng-dwg-parse 作者的实测是“explode 代理实体 >5 分钟无产出”，因此选择先导出 T3。
   - **建议**：找一张原生 T20 样图，对比 dwg2dxf、ACadSharp、go-cad 三者的实体数和文字数。
2. **DeepSeek 图片 token 规则。**
   - 本文的数字来自 harness 移植的 v41 计算器。第三方页面有“每图 384 token”的不同说法。
   - V4.1 Flash 的实际计费、降采样方式、小字识读阈值（14 px 是假设）都**没有实测**。
   - 应该用 05 的样图做一次“字高 × 像素 × 识读率”的小实验来定 `min_text_px`。
3. **文字 token 估算**（每行 10–20 token）是按经验估的，没有用 DeepSeek 分词器实测。
4. **规则启发式的泛化。** 标题栏、门窗编号正则、轴网、表格检测都依赖制图习惯。需要在多家设计院的图上回归测试，并允许通过参数覆盖默认判据。
5. **dxf-parser 的维护状态。** npm 上的最后一个版本发布于 2021-11；GitHub 最后推送于 2024-06。MTEXT 格式码、ATTRIB 等能力的边界需要用 ezdxf 对拍确认。
6. **ACadSharp 的中文。** ACadSharp 把 `ansi_936` 映射到 GB2312，不是 GBK，扩展汉字可能乱码。另外 .NET 的打包方式没有核实。
7. **go-cad 的来源与成熟度。** 实现是否属于独立实现无法判断；项目创建不到一个月；README 的质量数字前后不一致。
8. **ODA File Converter 的许可。** 只拿到搜索摘要，没有读到 EULA 原文。只要涉及商用，就要以安装时的许可文本为准。
9. **LibreDWG 发布页的附件** 没有加载出来；Windows nightly 是否包含 `dwg2dxf.exe`，以及 0.14.86xx 与 0.14 的行为差异，都未核实。
10. **没有读完的来源**：
    - LED-BENCH 正文（arxiv 打不开）。
    - FloorPlanCAD、SymPoint、DeepFloorplan、dxf-json 的许可证。
    - LibreCAD `dxf2svg` 的实际可用性。
    - freecad-mcp 的 docs。
    - 这些在文中都已标为“未核实”。
11. **dsh-cad-review** 是现成的 DeepSeek Harness CAD 插件，可以参考它的 Cordis 接入方式（`inject = ['tools']`、`dsh plugin add`）。但它刻意不输出文字内容，与本项目的目标相反，不能直接复用。
