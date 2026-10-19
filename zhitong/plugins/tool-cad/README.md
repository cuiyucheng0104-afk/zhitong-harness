# @zhitong/tool-cad

智通数工AI 的看图插件：结构化读取为主，按需出图。DWG 经 LibreDWG `dwg2dxf` 子进程转成 DXF，解析成无头场景后由工具按图框、图层、文字、块、表格、房间查询；`cad_render` 每次只出一张 PNG（图框总览或局部放大），交给 `read_image` 看。计数与面积一律由代码算，不从图片读；单位未确认时量纲类工具拒绝执行。看图流程见 skill [`zt-cad`](../../skills/zt-cad/SKILL.md)。

## 工具

| 工具 | 作用 |
|---|---|
| `cad_open` | 打开 DWG/DXF（绝对路径，按文件头判断格式），返回 `doc`、sha256、转换器版本、编码、范围、计数、跳过的实体、图框 id、单位与单位证据、警告 |
| `cad_layers` | 按图层统计线段/文字/块/填充，颜色、冻结/关闭状态、样例文字；可限定图框 |
| `cad_frames` | 图框列表：`S*` 按 A0–A4 图幅识别的图框线，`F*` 图形簇（含簇边图名文字），都没有时 `W1` 整张范围；每个图框的标题栏启发式（图名、图号、比例、楼层，带文字 id 与句柄） |
| `cad_text_search` | 按图框、图层、子串、正则、矩形、最小字高过滤文字；`group=line` 拼行；超出 `limit` 的结果写 TSV |
| `cad_blocks` | 块引用计数（含嵌套，排除匿名块内部）与门窗编号文字计数（排除门窗表里列出的编号），按图框分组；全部坐标写 TSV；可另存统一算量 schema |
| `cad_render` | 一张 PNG：只给 `frame` 出总览（带 A…/1… 网格、文字画空框）；`frame+cell`、`rect`、`around`、`text_id`、`handle` 出局部（文字照画，比例按字高）；`text=ids` 给编号对照表；返回 `world_rect`、`px_per_unit`、`image_size` |
| `cad_set_unit` | 确认单位：`unit + basis`（人工确认）或 `verify=true`（尺寸标注显示值÷实测长度比对，样本 ≥5、一致率 ≥80%） |
| `cad_rooms` | 房间面积双路核对（锚点图层房间名 → 最小闭合多段线几何面积 vs 面积文字）；需已确认单位 |
| `cad_table` | 给 `rect` 直接按表格线重建；否则按表头关键词自动找门窗表/材料表；返回前若干行与 CSV 路径 |
| `cad_diff` | 两张图的线段增删（自动平移配准）、文字增删、块数量变化；可出差异图 |

所有结果是带 `doc`、坐标与句柄（文字另有 `T<序号>` id）的 JSON；模型看到的是紧凑表格。长列表只返回前 `limit` 行，全部写进文件并返回路径。坐标是图纸单位（图纸 Y 轴向上）；图片像素 `(px, py)` 换算为世界坐标 `(world_rect.x1 + px / s, world_rect.y2 − py / s)`，`s = px_per_unit`。

## 文件落在哪里

`<图纸目录>/.cache/`（或配置的 `cacheDir`）：

- `<sha256>-<SCENE_VERSION>.scene`：解析缓存（二进制）。文件内容或场景构建器版本变化时自动失效；`cad_open force=true` 重建。
- `<sha256>.unit.json`：单位确认记录，再次打开同一文件仍有效。
- `out/`：TSV、CSV、schema JSON；`render/`：PNG。

## 配置

| 字段 | 默认 | 说明 |
|---|---|---|
| `dwg2dxfPath` | 空 | dwg2dxf 绝对路径；空则依次查 `DWG2DXF_BIN`、包内 `bin/<platform>-<arch>/`、`PATH`。配置了但不存在时打开 DWG 报错 |
| `dwg2dxfTimeoutMs` | 180000 | 单次转换时限；超时终止子进程托管的整个进程范围 |
| `maxDwgBytes` / `maxDxfBytes` | 200 MiB / 400 MiB | 输入与转换结果的体积上限 |
| `cacheDir` | 空 | 空为 `<图纸目录>/.cache` |
| `shxFonts` | 包内 KST32B | SHX 笔画字体，按顺序取字形；一条文字缺任一字形就整条用回退字体 |
| `fallbackFont` | 包内 Noto Sans SC（GB2312 子集） | 回退字体文件；加载时检查存在 |
| `frameGapMm` / `frameMinAreaM2` / `frameMinPts` | 30000 / 50 / 30 | 图形簇判据（与算量脚本 03/06 一致），按单位换算 |
| `frameLayerPattern` / `framePointCap` | `WALL\|墙\|轴\|AXIS\|DOTE\|COLUMN\|柱` / 300000 | 聚类取点图层与取点上限 |
| `titleMarginRatio` | 0.15 | 图形簇向外找图名文字的边距（相对长边） |
| `titleFieldLabels` | 工程名称、项目名称、比例、日期等 | 标题栏标签，取右侧或下方最近文字为值 |
| `drawingNumberPattern` | `建施-03`、`JS-01` 类 | 没有「图号」标签时识别图号的正则 |
| `openingLabelPattern` | `M1021`、`C1518`、`FM甲1022` 类 | 门窗编号正则 |
| `roomAnchorLayers` | `["TXTROOM"]` | 房间名锚点图层 |
| `roomMinAreaM2` / `roomMaxAreaM2` / `roomMaxLabelLength` | 1 / 2000 / 12 | 房间面积范围与房间名长度 |
| `diffEpsMm` | 1 | 比较图纸时的端点量化容差 |
| `listLimit` / `listMaxLimit` | 100 / 1000 | 列表默认行数与上限 |
| `tableKinds` / `tableMinHeaderHits` | 门窗表、材料表 / 3 | 自动找表的表名与表头词；表头行至少命中的词数 |
| `renderMaxPx` / `renderHardMaxPx` | 1600 / 2400 | 图片长边默认值与上限 |
| `renderMinTextPx` / `renderDropTextPx` | 14 / 3 | 局部图的目标字高；小于此像素的文字不画 |
| `gridLongSide` | 8 | 总览网格长边格数 |
| `renderMaxZoomFraction` | 0.25 | 局部范围占所在图框面积的上限，超过即拒绝 |
| `renderMaxLabels` | 120 | `text=ids` 每张图最多编号数 |

## dwg2dxf 分发与 GPL 合规

- LibreDWG 是 GPLv3，只作为独立可执行文件经 `ctx.subprocess` 启动（argv + 临时文件 + 退出码），不链接、不嵌入；禁止引入 `@mlightcad/libredwg-web` 等链接式封装。删掉二进制只失去 DWG 能力。
- 每次转换：`mkdtemp` 临时目录，输入拷成 ASCII 名 `in.dwg`（官方 win64 版用 ANSI `fopen`，中文路径打不开），`dwg2dxf -y -o out.dxf in.dwg`，工作目录与库路径设为可执行文件所在目录，超时终止，体积超限拒收，结束后删除临时目录。
- 二进制按 [`bin/README.md`](bin/README.md) 放进 `bin/<platform>-<arch>/`，同目录随附 `COPYING`（GPLv3）、`VERSION.txt`、`SOURCE-OFFER.txt`；仓库只提交说明，不提交二进制。Linux/macOS 用 `sh scripts/build-dwg2dxf.sh` 从钉死 sha256 的 0.14 源码包静态构建；Windows 用官方 0.14 win64 zip（sha256 见 `bin/README.md`）。
- 其余第三方声明见 [`THIRD_PARTY_NOTICES.txt`](THIRD_PARTY_NOTICES.txt)。进程边界是否足以隔离 GPL 仍需 IP 律师在发布前确认。

## 已知盲区

- **图纸空间**：布局与视口里的实体全部跳过（`cad_open` 报跳过数），只读模型空间。
- **块内 HATCH** 不解析，只读顶层填充；填充一律按实心半透明画，不画图案。
- **冻结/关闭图层**：结构化工具照常统计（`cad_layers` 标出状态）；`cad_render` 默认不画。
- **线型与线宽**不处理，虚线画成实线。
- **文字对齐**与 MTEXT 折行不处理：文字取插入点，宽度按字符数估算（中文 1 倍字高、其他 0.6 倍），图上文字框与原图可能有偏差。
- **天正代理实体**（T20 原生图的 `ACAD_PROXY_ENTITY`/`TCH_*`）LibreDWG 读不出，`cad_open` 给警告；需要先在天正导出 T3。天正房间面积文字经转换常丢失，`cad_rooms` 退化为只有几何面积。
- **启发式**：图框图幅匹配、标题栏、门窗编号、表头关键词、房间锚点都依赖制图习惯；判据都在配置里可调。结果带来源文字 id/句柄，引用前要核对。
- **解析在插件进程内同步进行**：几百 MB 的 DXF 会占用数秒并占内存；超过 `maxDxfBytes` 直接拒绝。
- **SHX 字体**：KST32B 缺不少简体专用字（如「图门开电标卫详」），含这些字的文字整条用回退字体；天正/Autodesk 的 bigfont（gbcbig、hztxt）需要 Unicode→GB2312 映射，尚未实现。
- `cad_diff` 只处理平移；线段级比较对百万级线段的大图内存开销未实测。

## Model Experience

十个工具的定义进入系统提示的工具段。工具结果是紧凑表格，单次结果按 `limit` 截断，长结果写文件；`cad_render` 只返回 PNG 路径与元数据，图片经 `read_image` 才进入上下文（每张约 1k token）。

#### KV Cache effect

加载插件只增加固定的工具定义，不随会话变化；不改写已有消息。

## 测试

```sh
pnpm vitest run                    # 合成 DXF 夹具、迁移的合成场景用例、工具级测试、PNG 尺寸与非空白像素比例
pnpm exec tsc --noEmit -p tsconfig.json
DWG2DXF_BIN=/path/to/dwg2dxf pnpm vitest run tests/dwg.spec.ts   # 真实 DWG 夹具；找不到 dwg2dxf 时该用例跳过
```

`tests/fixtures/fixture_t3.dwg` 来自 tiangong-cad-viewer（天正 T3 节点详图，AC1018）。转换相关的超时、非零退出与 ASCII 临时名用 POSIX 脚本冒充 dwg2dxf 测试，Windows 上跳过。
