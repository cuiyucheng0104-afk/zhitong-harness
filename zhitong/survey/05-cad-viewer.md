# tiangong-cad-viewer 调研报告：改造为 DeepSeek Harness CAD 插件

调研对象是 `/home/user/cuiyucheng0104-afk/tiangong-cad-viewer`，全程只读，没有运行 npm 或任何联网命令。仓库只有 1 个提交（`da98e56`），没有 `node_modules`，也没有 `vendor/libredwg`。

没有验证的部分：
- 没有运行测试和构建。
- 没有查证第三方包（`@napi-rs/canvas`、`@resvg/resvg-js` 等）的当前版本和预编译平台。
- 没有看到 Python 脚本 03/06。它们在另一个仓库（`算量层研发/脚本`），所以“判据与 Python 严格对齐”只是代码注释的说法。

---

## 0. 结论

1. **解析和算量逻辑几乎全是纯函数，可以直接在 Node 里跑。**
   - 链路是：`dxf-parser` → `parseHatches` → `buildScene` → `BuiltScene`。
   - 下游 `detectFrames`、`checkRooms`、`countBlocks`、`blocksToSchema`、`extractTable`、`diffScenes`、`ReviewStore` 都只吃 `BuiltScene`。
   - 浏览器相关代码只有渲染器、交互、标注、缓存、PDF、`main.ts`（共 7 个文件，见 §1）。
2. **仓库里没有 PNG、SVG 导出，也没有 headless 渲染。**
   - 唯一的导出是 `jsPDF` 加光栅叠加层（`src/pdfExport.ts`），而且依赖 DOM canvas。
   - 但 `BuiltScene.layers[].positions` 已经是“按图层、按颜色的世界坐标线段数组”。
   - 所以做 headless 光栅化很简单：画线加画文字，不需要 three.js。
3. **dwg2dxf 的定位和打包已有可复用的参考**，但有三个缺口：
   - 没有 macOS 的官方二进制，也没有 macOS 的 CI。
   - `tools/convert.mjs` 缺少 Windows 中文路径、超时、临时文件唯一性的保护（Electron 版已处理）。
   - 现有 `resolveDwg2dxf` 的 mac 支持依赖作者本机的仓库外路径。
4. **有几个“看起来能用、实际要补”的点**：
   - 图框只有 `图框N` 这种标签。楼层标签（3F、标准层×N）只在 UI 里人工添加，存在 IndexedDB 里。
   - `checkRooms` 把房间名锚点硬编码为图层 `TXTROOM`。
   - 没有测试覆盖 `buildScene` 的 DXF 解析路径。

---

## 1. 模块地图

### 1.1 `src/engine/`（解析和场景构建）

| 文件 | 作用 | 输入 → 输出 | 环境 |
|---|---|---|---|
| `engine/sceneBuilder.ts`（400 行） | 核心。DXF 实体 → 按图层批合的线段，同时收集文字、块引用、闭合多边形、捕捉点 | `buildScene(dxf, parseMs, hatches)` → `BuiltScene`（l.19-52 接口，l.77 函数） | 纯逻辑，用 `performance.now()`（Node 全局有）。**headless 可用** |
| `engine/hatchParser.ts`（188 行） | HATCH 解析。`dxf-parser` 不解析 HATCH，所以对 ENTITIES 段做独立组码扫描，用 earcut 三角化 | `parseHatches(text, layerRgb)` → `{layers, count, skippedPaths}`（l.60） | 纯逻辑。**headless 可用**。注意它对全文 `split(/\r?\n/)`，大图内存翻倍 |
| `engine/aci.ts` | ACI 颜色索引 → RGB（1-9 与 250-255 精确，10-249 为近似） | `aciToRgb(i)` | 纯逻辑 |
| `engine/parseWorker.ts`（48 行） | Worker 外壳：fetch 或接收 text → `DxfParser.parseSync` → `parseHatches` → `buildScene` | `{url}` 或 `{text}` → `{ok, scene}` | 依赖 Worker 全局。**核心只有 l.20-33 十几行，headless 里直接复刻** |

**`BuiltScene` 字段**（`sceneBuilder.ts` l.37-52）：
- `layers`：`{name, positions: Float32Array[x,y,z,x,y,z…], colors, segCount}`。每个线段 6 个 float，z 恒为 0。
- `hatches`：三角形。
- `texts`：`{x,y,h,rot,str,layer,rgb}`。
- `inserts`：`{name,x,y,layer}`。
- `polys`：`{pts: 扁平 xy, layer}`（闭合多段线）。
- `header`：`{insunits, measurement}`。
- `bbox`。
- `stats`：`{entityCount, segCount, skipped, ...}`。
- `snapXY` / `snapType`：捕捉点，agent 不需要。

**`buildScene` 的行为和限制**（会影响 agent 能得到什么）：
- 递归展开 INSERT，深度上限 8（l.227）。块内图层 `0` 继承宿主图层（l.231）。
- 颜色按 ByBlock / ByLayer / ACI 解析（l.126-131）。
- LWPOLYLINE/POLYLINE 的 bulge 展开为圆弧，ARC/CIRCLE/ELLIPSE/SPLINE 离散化，SOLID/3DFACE 画外框。
- DIMENSION 通过其匿名块 `*D…` 渲染（l.339-345）。
- **paperspace 实体全部跳过**（l.229），所以不支持布局和视口。
- `polys` 上限 30,000，只收**闭合的 LWPOLYLINE/POLYLINE**（l.254）。
- 文字：TEXT/MTEXT/ATTRIB 取 `startPoint ?? position`，**不处理对齐方式（halign/valign）和 MTEXT 宽度折行**。
- `cleanDxfText`（l.55）只剥离基本控制符：`%%c`、`%%d`、`%%p`、`\P`、`\f…;`。
- **HATCH 只扫顶层，块内 HATCH 不扫。图层的冻结/关闭状态也不处理。** 线型和线宽都不处理。
- `SCENE_VERSION='s7.2'`（l.14）是缓存键的一部分。

### 1.2 业务逻辑（纯逻辑，headless 可用）

| 文件 | 作用 | 备注 |
|---|---|---|
| `frames.ts`（70 行） | `detectFrames(scene): Frame[]`、`pointFrame(frames,x,y)` | 见 §4 |
| `roomCheck.ts`（96 行） | `checkRooms(scene, unitScale): RoomCheckItem[]` | 见 §4 |
| `extract.ts`（187 行） | `countBlocks`、`blocksToSchema`、`extractTable`、`tableToCsv`、`textsToCsv`、`UnitMeta` | **只有 `downloadFile`（l.188-195）碰 DOM**，其余全是纯函数。Node 里 import 该文件安全，只要不调用 `downloadFile` |
| `diff.ts`（166 行） | `diffScenes(old, new)`：配准加量化哈希 | 纯逻辑 |
| `reviewStore.ts`（199 行） | `ReviewStore` 类，审核状态机和 JSON 导入导出 | 纯逻辑，状态在内存里 |
| `snap.ts` | 网格哈希捕捉索引 | 纯逻辑，agent 用不上 |
| `shxText.ts`（79 行） | `ShxTextEngine`：SHX 笔画字体 → 线段。`textSegments(t)` 返回线段，或在字形不全时返回 `null` | 纯逻辑，依赖 `@mlightcad/shx-parser`。**headless 渲染可复用，且不依赖系统字体** |

### 1.3 浏览器 DOM/Canvas 依赖（headless 不可用）

`renderer.ts`（three.js WebGL 加 2D overlay）、`tools.ts`（测量，含 pointer 事件）、`markup.ts`（Konva 标注）、`cache.ts`（IndexedDB）、`pdfExport.ts`（需要 `CadRenderer` 和 `HTMLCanvasElement`）、`main.ts`（1114 行 UI 胶水）。

`main.ts` 里有几段逻辑值得照抄成 headless 版：
- **单位判定**：`deriveUnit`（l.249-254）。`$INSUNITS` 映射 `{1:inch,4:mm,5:cm,6:m}`（l.26）。
- **单位比对**：`maybeFinishUnitCheck`（l.300-326）。找线段中点附近的纯数字文字，比值 ≈1 为 mm，≈1000 为 m。
- **房间核对阈值**：`THRESH = 3`（l.610 附近）。

`tools.ts` 里有 `fmtLen`、`fmtArea`、`shoelace`（l.30-46），也是纯函数。

### 1.4 `tools/`

| 文件 | 作用 |
|---|---|
| `convert.mjs` | DWG→DXF→UTF-8 转码的命令行，输出到 `public/drawings/` |
| `dwgSmoke.mjs` | CI 端到端冒烟：夹具 DWG → 转换 → 解析 → 断言 |
| `nodeVerify.mts` | 用真实 F栋数据做 18 项无头验证。**依赖被 `.gitignore` 排除的数据（`F栋1号楼.dxf` 35MB、`F栋_标注.json`），CI 跑不了** |
| `genManifest.mjs`、`predist.mjs`、`electronSmoke.mjs`、`captureManual.mjs` | 分别是图纸清单、打包前校验、Electron 启动冒烟（CDP）、说明书截图（puppeteer-core） |

注意：`nodeVerify.mts` 声称用“Node 原生 TS 类型剥离”运行，但 `sceneBuilder.ts` 的 `import './aci'` 没有扩展名，原生 Node 解析不了。所以实际要走 esbuild 打包，和单测一样。

### 1.5 `electron/`

| 文件 | 作用 |
|---|---|
| `main.cjs`（141 行） | 主进程。`ipcMain.handle('open-cad-file')`（l.194-229）完成魔数嗅探、拷贝成 ASCII 临时名、dwg2dxf、体积上限、编码嗅探 |
| `preload.cjs` | 只暴露 `desktop.openCadFile` |
| `staticServer.cjs` | 起本地静态服务，端口段 17870-17879 |
| `THIRD_PARTY_NOTICES.txt` | 第三方声明 |

---

## 2. DWG→DXF 转换路径

### 2.1 二进制定位

`tools/convert.mjs` l.30-43 的 `resolveDwg2dxf()` 按以下顺序查找：
1. `process.env.DWG2DXF_BIN`
2. `<repo>/vendor/libredwg/<process.platform>/dwg2dxf[.exe]`（注意 Windows 的 `process.platform` 是 `win32`）
3. `<repo>/vendor/libredwg/dwg2dxf[.exe]`
4. `<repo>/../工程造价/cad_parse_demo/vendor/libredwg/dwg2dxf`，即作者 mac arm64 开发机的仓库外路径。**这就是“mac legacy binary”**。

`electron/main.cjs` l.139-151 是同一逻辑，区别是打包后（`app.isPackaged`）只查 `process.resourcesPath/libredwg/dwg2dxf[.exe]`，找不到返回 `null`。

**各平台的现状**：

| 平台 | 来源 | 位置 |
|---|---|---|
| macOS | 没有官方二进制。R3 报告记录的是开发机上的 0.13.4 arm64 加 `libredwg.0.dylib`，在**本仓库之外** | `docs/R3-压测报告-20260709.md` 第 3 行，遗留 TODO 第 5 节 |
| Windows | CI 下载官方 win64 zip，**钉死版本和哈希**：`LIBREDWG_VERSION=0.14`，`LIBREDWG_WIN64_SHA256=1ad7e15344d20b3426c3435b078d82fb84b35062815946b2cca9c5fc9810fea8`（`ci.yml` l.10-11，l.52-59；`release.yml` l.121-122，l.154-163）。URL 是 `github.com/LibreDWG/libredwg/releases/download/0.14/libredwg-0.14-win64.zip`，解压到 `vendor/libredwg/win32/`，并写入 `VERSION.txt` | `vendor/libredwg/win32/` |
| Linux | CI 从官方源码包构建。源码包 sha256 为 `62ebb73b…81275`（`ci.yml` l.12，l.87-98）。构建命令是 `./configure --disable-bindings --disable-shared`，这样产物是静态的，只有一个 `dwg2dxf` 文件 | CI 缓存 `libredwg-bin` |

**没有 macOS 的 CI 作业。**

### 2.2 调用方式（进程边界）

- 命令行是 `dwg2dxf -y -o <tmp.dxf> <input.dwg>`（`convert.mjs` l.61）。
- `stdio: ['ignore','ignore','pipe']`，`cwd = binDir`（让 Windows 从 exe 同目录找 DLL）。
- macOS 设 `DYLD_LIBRARY_PATH=binDir`，Linux 设 `LD_LIBRARY_PATH`（l.59-60）。
- 成功条件是退出码为 0 且临时文件存在；失败时返回 stderr 的最后 800 字符。

**`convert.mjs` 与 `main.cjs` 的差异，plugin 要采用较完善的一版**：
- `main.cjs` l.209-212 会先把输入拷贝成纯 ASCII 临时名。注释说官方 win64 是 ANSI `fopen`，非本机代码页的中文路径打不开。**`convert.mjs` 没有这一步，中文路径在 Windows 上会失败。**
- 临时文件名用 `Date.now()`（`convert.mjs` l.57、`main.cjs` l.159），并发会撞名。应改用 `mkdtemp`。
- 没有超时，也没有杀进程树。
- `main.cjs` 有体积上限 `MAX_DXF_BYTES = 400MB`（l.137，l.214-220）。`convert.mjs` 没有。

### 2.3 格式和编码嗅探

- **魔数嗅探**（`convert.mjs` l.94-98，`main.cjs` l.180-183）：文件头以 `AC10` 开头且第 6 字节不是换行，就当 DWG。原因是扩展名会撒谎。已有实例：`F栋.dxf` 实际是 AC1021 的 DWG。
- **编码嗅探**（`convert.mjs` l.81-91，`main.cjs` l.186-192）：先用 `new TextDecoder('utf-8',{fatal:true})`，失败再退回 `new TextDecoder('gbk')`。
- 背景：老图是 GBK（`$DWGCODEPAGE=ANSI_936`），AC1021 及以上经 dwg2dxf 输出已是 UTF-8。一律按 GBK 解会把 UTF-8 中文解成乱码（README 称为“第 7 坑”）。
- 局限：不读 `$DWGCODEPAGE`，只靠严格解码是否抛错判断。

### 2.4 许可约束

- `electron/THIRD_PARTY_NOTICES.txt`：
  - LibreDWG 是 GPLv3，只以独立子进程方式调用，通信是命令行参数加临时文件，没有链接。
  - 可以单独替换或删除，删除后只失去 DWG 转换能力。
  - 依 GPLv3 第 6 条，可从官方发布页获取对应源码（版本见 `resources/libredwg/VERSION.txt`）。
  - KST32B 字体是 FREEWARE，允许再分发，原许可文本在 `public/fonts/LICENSE_KST32B_v2.txt`。
  - 其余依赖是 MIT/BSD 类。
  - 安装包内没有 Autodesk 或天正的专有字体。
- `docs/08-授权合规与出货清单.md`：
  - **进程边界守则**（§3.2）：独立可执行；只用 `spawn`；零链接，禁用 WASM 版 `@mlightcad/libredwg-web`（GPL，会让整个 app 变 GPLv3）和 N-API 封装；wrapper 要保持通用，不依赖 LibreDWG 内部结构；随包附 GPLv3 文本和源码（或三年 offer）。
  - **文档自己标明**：这不是法律意见，进程边界论点仍有争议，发布前要请软件 IP 律师签字。
  - 免费的 ODA File Converter 商用不行。
  - `DwgConverter` 接口要做得通用，方便换成商业 SDK。
  - 建议 CI 加 license 扫描：除隔离的 LibreDWG 二进制外，出现任何 GPL/AGPL/LGPL 就让构建失败。
  - 字体：Autodesk 和天正的 SHX 不可分发，用 OFL 字体（Noto/思源）替换，客户自带字体只在本地读取。
- 天正 proxy 实体：LibreDWG 读不出 TArch 的 `ACAD_PROXY_ENTITY`。R3 实测 8 张样图全部是零 proxy（全是已转 T3 的图或非天正图）。**原生 T20 天正图没有验证过，仍是已知风险。**

---

## 3. headless 光栅化可行性

### 3.1 现状

- **没有 PNG/SVG 导出。** 全仓库 grep 不到 SVG 输出。
- `docs/05` 把 SVG 路线写在规划里（`svg2pdf.js`、服务端 ezdxf），但没有实现。
- PDF 导出（`pdfExport.ts`）：
  - 矢量部分是 `jsPDF.line`，按颜色分桶，上限 `SEG_CAP=300_000`。
  - 文字和标注是从 DOM canvas 取的光栅图，依赖 `CadRenderer`、`HTMLCanvasElement`、`Blob`。
  - 所以不能直接 headless 复用，但“遍历 `scene.layers` 的线段，并做世界坐标到页面坐标的映射”这段逻辑（l.43-64）可以照搬。

### 3.2 渲染所需数据

`BuiltScene` 已经有 headless 渲染所需的全部数据：
- 线段：`layers[].positions` / `colors`。
- 填充三角形：`hatches[]`（实心半透明，不透明度 0.45，见 `renderer.ts` l.91-94）。
- 文字：`texts[]`，包含位置、字高、旋转、颜色。
- 暗底和白底：白底时把 `0xffffff` 的颜色改成 `0x202020`（`renderer.ts` l.262-264），PDF 里把近白色改成 `0x303030`（`pdfExport.ts` l.57）。

### 3.3 选型

| 方案 | 优点 | 缺点 |
|---|---|---|
| A. `@napi-rs/canvas`（Skia 的 Node 绑定，预编译，含 darwin-arm64/x64、win32-x64） | 提供 Canvas2D API。`renderer.ts` 的 overlay 绘制代码（`fillText`、`strokeRect`、`setLineDash`、`rotate`）和 `main.ts` 的图框、审核叠加钩子基本可原样移植。有 `GlobalFonts.registerFromPath` 可注册字体 | 原生依赖，需要核实各平台预编译包的可用性（我没联网验证） |
| B. 自己生成 SVG，用 `@resvg/resvg-js`（Rust，预编译）转 PNG | 可以顺便输出 SVG 供人查看。`fontFiles` 选项可指定字体 | 数十万条线段的 SVG 很大，性能没有实测。许可是 MPL-2.0（文件级） |
| C. 纯 JS 线段光栅化（Wu/Bresenham）加 `pngjs`/`fast-png` | 零原生依赖，跨平台最稳 | 要自己写抗锯齿；中文文字只能靠 SHX 笔画 |

**建议**：主选 A；C 作为无原生依赖时的降级；B 只在需要 SVG 输出时使用。

### 3.4 按图框出 PNG 切片

**参数**。需要的输入是世界坐标矩形（图框）、目标分辨率、是否白底、是否叠加标注。

**坐标映射**。`sx = (x - rect.x1) * s`，`sy = (rect.y2 - y) * s`（Y 轴翻转，世界坐标 Y 向上）。`s` 是 px/图纸单位。

**DPI 的含义**。CAD 里没有“DPI”，要定义成“出图比例加 DPI”。设比例 1:N、图纸单位是 mm，则：
- `s = (dpi / 25.4) / N`（px 每图纸 mm）。
- 例子：150 dpi、1:100 时 `s≈0.059`，60m×40m 的图框是 3543×2362 px。
- 实际建议改用“最长边像素数”作为主参数（例如 ≤2000 px），再反推 DPI，因为模型会对大图降采样。

**大图框要分块**。一张大图框切成 N×M 个切片，带约 5-10% 的重叠，并返回每个切片的世界坐标矩形。

**必须随 PNG 返回的元数据**，这样模型才能把像素坐标换回世界坐标：
- `world_rect`
- `px_per_unit`
- `image_size`
- 单位信息

**文字渲染的字体风险**。
- 优先使用 `ShxTextEngine`：不依赖系统字体。实测 `楼梯详图1211_t3` 里 15,782 条文字有 13,729 条（87%）可走笔画，其余字形不全。KST32B 缺简体专用字，例如“图门开电标卫详”（README l.138 附近），所以含这些字的文字整条回退。
- 回退文字用内置 OFL 字体（建议 Noto Sans SC 子集）。桌面端的 overlay 回退用 `"PingFang SC", "Microsoft YaHei"`（`renderer.ts` l.265），headless 机器不一定有这些字体。
- 文字预算：浏览器端有 `BUDGET=4000` 和 `hPx < 3.2` 的剔除规则（`renderer.ts` l.249，l.257）。headless 可以放宽预算，但要保留“字高小于 3 px 不画”的规则，避免噪声。
- `@mlightcad/shx-parser` 在 Node ESM 下是否可用需要实测：README 记录 1.4.5 的 CJS 构建导出为空，只有 `module` 字段能用，所以单测用 esbuild 的 `--main-fields=module,main`。**plugin 构建要走会读 `module` 字段的打包器，或者实测直接 `import` 是否可用。**

---

## 4. 确定性提取逻辑（数据结构和工具化）

### 4.1 `frames.ts`

- **判据**（l.16-19）：`GAP=30000`（30m 空白）、`MIN_AREA_M2=50`、`MIN_PTS=30`，点源来自图层名匹配 `/WALL|墙|轴|AXIS|DOTE|COLUMN|柱/i` 的线段端点。如果没有图层命中，退回全部图层（l.36-38）。
- **算法**（l.34-62）：X 向排序后按 GAP 聚类成列，列内 Y 向同样聚类成行，过滤面积和点数。
- **输出**：
  ```ts
  interface Frame { id:number; label:string; x1:number; y1:number; x2:number; y2:number }
  ```
- **注意**：
  - `label` 只会是 `图框N`。注释和文档里的楼层标签（`3F`、`标准层×N`）是 UI 手工添加的，存在 IndexedDB 的 `${file}::frames`（`main.ts` l.401），headless 里没有。
  - 点数上限 `CAP=300_000`（l.39）：超出后后面的图层被静默丢弃，没有任何提示。
  - 名字叫“图框”，实际是“建筑平面簇”，不是识别图纸标题栏。
  - 要给 agent 提供楼层标签，需要另写启发式。例如在框内或框边找形如“X层平面图”、“标准层”的文字；这个函数目前不存在。

### 4.2 `roomCheck.ts`

- **输出**：
  ```ts
  RoomCheckItem { label; textM2:number|null; geomM2; diffPct:number|null; x; y; layer }
  ```
  按 `diffPct` 降序，null 排在后面。
- **规则**：
  - 房间名锚点必须在图层 `TXTROOM`（l.116-117，硬编码），排除以数字或括号开头的文字，长度 ≤12。
  - 面积文字的正则是 `^(\d{1,4}\.\d{1,2})\s*(㎡|m²|M2)?$`，范围 1-2000。
  - 几何面积 = 包含该锚点的最小闭合多边形，面积在 1-2000 m² 之间。
  - 用 `unitScale`（图纸单位→mm）换算面积。
- **已知数据现实**（README 和 `nodeVerify.mts` 注释）：
  - 天正房间面积文字经 dwg2dxf 转换后丢失，于是退化为只有几何面积，`textM2=null`。
  - 室内房间闭合边界多数不存在，因为墙是双线段。
  - 所以在 F栋 上只匹配到很少的房间。工具返回结果要明确标注“未匹配 ≠ 没有房间”。
- 参数里有一个隐含约束：`unitScale` 必须由调用方给出，函数本身不判断单位。

### 4.3 `extract.ts`

- `countBlocks(scene, frames?)` → `BlockCount[] {name; count; layers[]; perFrame: Record<label, n>}`，按 count 降序。匿名块（以 `*` 开头）不计，框外归入 `'框外'`。
- `blocksToSchema(counts, file, unit)` → 信封：
  ```
  {meta:{file,...UnitMeta,generatedBy,schemaBody}, items: RecognitionItem[]}
  ```
  `RecognitionItem` 是：
  ```
  {sourcePath:'cad', sourceRef:{file,location,rawExcerpt},
   componentCategory, detection:{detector:'vector_rule',confidence:1,layer,bbox:null,polyline:null},
   rawMeasures:{lengthMm,areaMm2,heightMm,count}, params:{frameId?}, gbCodeHint}
  ```
- **受控词表映射**（l.233-236）：是子串匹配，不是精确匹配，顺序决定优先级。
  ```
  门→门, 窗→窗, 柱→柱, 梁→梁, 墙→墙, 板→板, 桩→基础, 楼梯→楼梯, 砌体→砌体, 钢筋→钢筋
  ```
  - 只有这 10 个关键字，而 `ReviewStore` 里的 `REVIEW_VOCAB` 有 19 项。
  - 词表以外的块不导出（留给人工）。
  - 隐患：“防火门”会命中“门”，但“门窗”这种块名会先命中“门”，“窗”类被误归；且包含“板”的块名（如“楼板”）会被归为“板”。
  - 词表外专业（给排水、电气）不导出，是代码审查 R1 的修复结果。
- `extractTable(scene, rect)` → `TableResult|null {rows:string[][]; nRows; nCols; hLines; vLines}`。
  - 在矩形内收集水平和垂直线，按坐标聚类，用主跨度投票排除无关长线，再把文字落入单元格。
  - 同一单元格的多段文字用空格连接。
  - 没找到网格返回 null。
  - 只处理 `scene.layers` 里的线段，对 SOLID/HATCH 画的表格线无效。
- `textsToCsv(texts, unit, frames)`：第一行是 `# unit=… insunits=… confirmed=… method=…`，之后是 `文字,X,Y,字高,图层,图框`。

### 4.4 `reviewStore.ts`

- **状态机**：`pending → confirmed / modified / deleted`。
- **`ReviewItem`**：`{id, category, detector, confidence, bbox, point, layer, blockName, handle, params, state, original?, source:'import'|'manual', raw}`。
- **API**：
  - `importJson(json)`：自动识别 `{annotations}` 弱标签格式和 `{items}` 或裸数组（`schema_v1`）。
  - `addManual`、`setState`、`reclassify`（记录原值）、`batchReclassify(blockName, cat)`、`setParams`。
  - `stats()` → `{total, pending, confirmed, modified, deleted, manual, lowConf, patchRate}`。
  - `exportJson(unitMeta)`：按原格式回写；label 格式合并回 `annotations`，schema 格式带 `meta.review` 信封。
- **已知小瑕疵**：`exportJson` 里 `+(x).toFixed(2) + '%'` 写法会吞掉尾零（`"50.00"` 变成 `"50%"`）。单测 l.292-294 按这个真实行为断言，并注明了这是既有问题。
- **用途判断**：这是给人用的审核界面的数据核心。**agent 场景下可以把它做成“导入识别结果 → 查看统计 → 批量改类 → 导出”的工具，但要明确写磁盘，因为类本身是内存态。**

### 4.5 `diff.ts`

- **算法**：
  1. `estimateOffset` 用“线段长度加方向”签名投票估计平移偏移，票数 <100 或偏移为 0 时视为不需要配准。
  2. 把新图平移到旧图坐标系。
  3. 线段端点量化到 `EPS=1.0`（图纸单位），端点排序后作为键，做集合差。
- **输出**：`{scene, counts:{added,removed,unchanged}, offset?:{dx,dy,votes}}`。
- **着色约定**：新增红 `0xff4d4d`、删除绿 `0x2ecc71`、共有灰 `0x4a4a52`。
- **局限**：
  - 只到线段粒度，不比较文字、块、图层。
  - 对大图，`Map<string,…>` 键是字符串，百万级线段内存开销大（没有实测）。
  - 只处理平移，不处理旋转和缩放。
  - `EPS=1.0` 默认假设单位是 mm。

### 4.6 建议的工具化映射

| 工具 | 底层函数 | 输出要点 |
|---|---|---|
| `cad_open(path)` | convert → decode → `DxfParser.parseSync` → `parseHatches` → `buildScene` | 摘要：`{doc_id, sha256, bbox, layers[{name,segCount,texts,inserts}], entityCount, texts, inserts, skipped, header, unit_guess}` |
| `cad_frames(doc_id, opts?)` | `detectFrames` | `Frame[]`，带面积 m² |
| `cad_rooms(doc_id, unit)` | `checkRooms` | 要求先确认单位 |
| `cad_text_search(doc_id, query, frame_id?, layer?, limit)` | `scene.texts.filter(includes)` | `{str,x,y,h,layer,frame_id}`（原版 UI 最多 30 条，`main.ts` l.826） |
| `cad_blocks(doc_id, frame_id?)` | `countBlocks` | 可选 schema 输出 |
| `cad_table(doc_id, rect)` | `extractTable` | rows、csv |
| `cad_render(doc_id, rect\|frame_id, max_px, ...)` | 新写 | PNG 路径加元数据 |
| `cad_diff(old, new)` | `diffScenes` | counts 加 offset，可选渲染 PNG |

---

## 5. 测试和夹具

### 5.1 `tests/unit.test.mts`（295 行，12 个 `test`）

覆盖：
- `ShxTextEngine`：真实字体 KST32B，从 `process.cwd()/public/fonts/kst32b.shx` 读取（所以必须从仓库根运行）。
- `aciToRgb`、`cleanDxfText`。
- `detectFrames` 与 `pointFrame`（两个用例）。
- `checkRooms`（双路一致、面积文字缺失两种）。
- `countBlocks` 加 `blocksToSchema`。
- `diffScenes`。
- `ReviewStore`（三个用例：schema 导入加置信队列、弱标签批量改判加导出、schema 导出信封）。

**没有覆盖**：`buildScene` 的实体展开（块变换、bulge、DIMENSION 匿名块）、`parseHatches`、`extractTable`、`textsToCsv`、`snap`。夹具是手造的 `BuiltScene`，不经过 DXF 解析。

**运行方式**：`npm test` 的 `pretest` 先用 esbuild 把测试打成 `.test-bundle.mjs`（`--main-fields=module,main`），再用 `node --test`。CI 用 Node 20。

### 5.2 `tests/fixtures/fixture_t3.dwg`

- 156,285 字节，`file` 命令识别为 AutoCAD 2004/2005/2006（AC1018）。
- 注释称本机 0.13.4 下约 580 个实体、561 个中文片段。
- `dwgSmoke.mjs` 的断言：实体 ≥300、图层 ≥3、输出含中文。留了版本裕量，因为 0.14 与 0.13.4 的输出有差异。
- 流程：`execFileSync(node, [convert.mjs, fixture, '_dwg-smoke'])` → 读 `public/drawings/_dwg-smoke.dxf` → `DxfParser`。

### 5.3 CI（`.github/workflows/ci.yml`）

三个作业，均用 Node 20：
- `windows`：typecheck、`vite build`、`npm test`。
- `windows-dwg`：下载钉死的 win64 zip 并校验哈希，然后跑 `dwgSmoke`。
- `linux-dwg`：源码构建 dwg2dxf（带缓存），然后跑 `dwgSmoke`。

`release.yml` 只做 Windows 安装包，tag 是 `v*`，并带版本一致性检查。

### 5.4 可复用方式

1. 直接复用：`fixture_t3.dwg`、`dwgSmoke` 的断言思路、`unit.test.mts` 里的合成场景测试（改成 import 新包路径即可）。
2. 新增：
   - fixture → `buildScene` 的黄金快照，例如实体数、图层列表、中文文字存在性、`texts` 里是否有预期的词，宽容区间以适配 0.13.4 与 0.14。
   - `cad_render` 的 PNG 测试：尺寸、非空白像素占比、文字区域像素存在；不建议逐像素比对，各平台抗锯齿不同。
   - 路径含中文和空格的转换测试。
   - macOS 的 dwg2dxf 作业。
3. `nodeVerify.mts` 依赖私有大数据，只能作为本地手工回归。

---

## 6. `docs/使用说明书.md` 的 14 章

| 章 | 内容 | agent（headless）适用性 |
|---|---|---|
| 1 快速上手 | 启动 dev server，选图 | 不适用（人用界面） |
| 2 界面总览 | 侧边栏、标签、状态栏 | 状态栏的统计数字可作为 `cad_open` 摘要的参考字段 |
| 3 单位确认门禁 | `$INSUNITS` 缺失时锁住导出，三种确认方式 | **适用**，且很重要。天正图常见 `$INSUNITS=0`，搞错差 1000 倍。headless 版建议：单位未确认时，需要量纲的工具（房间、算量导出）拒绝执行，并返回证据（`$INSUNITS`、图幅跨度、尺寸比对结果）。“量尺寸比对”可做成无需鼠标的版本（给两点坐标）。确认状态要持久化（原版存 IndexedDB） |
| 4 看图基础 | 平移、缩放、图层开关、多标签、黑白底 | 图层开关和黑白底 → 渲染工具的参数；平移缩放 → 渲染的 `rect`；其余不适用 |
| 5 测量 | 距离、连续、面积、比例校准，带捕捉 | 部分适用。距离和面积可直接算（`fmtLen`、`shoelace` 是纯函数），但“捕捉”依赖鼠标。可做成 `cad_measure(points[])`，点由模型给，用 `SnapIndex` 吸附 |
| 6 标注批注 | Konva 云线、箭头、矩形、文字，撤销重做 | 不适用（Konva）。但“模型在 PNG 上标出问题区域”可以用渲染叠加层的 rect 和文字实现 |
| 7 SHX 单线体中文 | KST32B 笔画字体 | **渲染层适用**，作为不依赖系统字体的文字渲染手段 |
| 8 图框切分 | `detectFrames`，人工贴楼层标签 | **适用**，核心。要补自动楼层标签启发式 |
| 9 识别与提取 | 块计数（`$DorLib2D$` 等）、提取表格、提取文字 CSV | **适用**，核心 |
| 10 审核工作台 | 导入识别结果、过滤、逐条确认、批量改判、画框补漏、导出 | 部分适用。人工逐条确认的交互不适用；导入、统计、批量改判、导出可做成工具。**需要把状态落盘** |
| 11 双路面积与映射核对 | `checkRooms`；图层和块的统计表加映射 JSON 导出 | 适用。映射核对的“统计表”部分可做（图层×线段/文字/块计数），“隔离显示”对应渲染的图层过滤参数 |
| 12 文字查找 | 全图文字子串搜索，跳转高亮 | **适用**，核心。跳转高亮对应“渲染该位置周围的切片并画十字” |
| 13 导出与图纸对比 | 导出 PDF；新旧版差异，三色 | 差异比对适用；PDF 导出不适用（依赖 DOM），可由 PNG 渲染取代 |
| 14 快捷键与常见问题 | 快捷键、FAQ | 不适用。FAQ 里的编码、单位、大图提示可以放进工具描述 |

---

## 7. 外部依赖（`package.json`）

**运行时依赖**：

| 包 | headless 需要？ |
|---|---|
| `dxf-parser` 1.1.2（MIT） | **需要** |
| `earcut` ^3.2.3 | 需要，仅当渲染 HATCH 填充 |
| `@mlightcad/shx-parser` ^1.4.5（MIT） | 可选，用于笔画文字（见 §3.4 的导入风险） |
| `three` 0.185.1 | 不需要 |
| `konva` ^10.3.0 | 不需要 |
| `immer` ^11.1.11 | 不需要（仅标注撤销重做） |
| `jspdf` ^4.2.1 | 不需要 |

**开发依赖**：`vite`、`electron`、`electron-builder`、`puppeteer-core`、`@types/three`、`typescript ^7.0.2`、`esbuild`。

**注意**：不要引入的包——`@mlightcad/libredwg-web` 与任何封装 LibreDWG 的 npm 包，它们会破坏 GPL 进程边界（`docs/08`）。

---

## 8. 推荐的插件设计

### 8.1 包结构

按 `packages/<group>/<pkg>/` 新建一个插件包，名称可按 `@deepseek-ai/dsh-cad`（我没有读过 harness 的 `docs/architecture.md`，包名、分组位置和 `defineTool` 的具体签名需要你对照确认）。

建议把代码分成三层：
1. **core**（headless 纯逻辑）：从本仓库 `src/engine/*`、`frames.ts`、`roomCheck.ts`、`extract.ts`、`diff.ts`、`shxText.ts` 搬入。删除 `downloadFile`，去掉对 `main.ts` 的依赖。
2. **convert**：`resolveDwg2dxf`、魔数嗅探、编码嗅探、spawn。
3. **render**：新写，输出 PNG。

harness 约定上要注意（来自 `CLAUDE.md` 摘要，细节需核对）：
- 所有注册走 `ctx.effect()`；可调参数走带校验的 `Config`。
- spawn dwg2dxf 应该用 harness 自己的子进程服务（`packages/subprocess`），而不是裸 `child_process`；是否受沙箱约束要核对。
- `GAP=30000`、`MIN_AREA_M2=50`、`MIN_PTS=30`、`EPS`、房间锚点图层名 `TXTROOM`、面积范围 1-2000 都应进入 `Config`，默认值保持与 Python 脚本一致，因为 CLAUDE.md 规定“不要硬编码可调参数”。
- 把可替换的字体、dwg2dxf 路径、缓存目录也放进 `Config`。
- 模型可见的内容要能从会话日志重建：PNG 通过 `read_image` 读取，路径和元数据要在工具结果里出现。

### 8.2 工具清单

所有工具返回结构化 JSON 加路径，不要把大数组塞进上下文。

| 工具 | 参数 | 输出 |
|---|---|---|
| `cad_open` | `path`（DWG 或 DXF）、`force?` | `{doc_id, source_sha256, format_sniffed, dwg2dxf_version, encoding, bbox, layers:[{name,segs,texts,inserts}], counts:{entities,texts,inserts,polys,hatches}, skipped, unit:{insunits, guess, confirmed, evidence}, warnings}`。缓存键用 `sha256 + SCENE_VERSION` 落盘 |
| `cad_set_unit` | `doc_id, unit:'mm'\|'m'`、或 `verify:{p1,p2}` | 更新单位状态，返回证据 |
| `cad_frames` | `doc_id, gap?, min_area_m2?, min_pts?` | 帧列表，含 `id, label, bbox, area_m2, text_hints[]` |
| `cad_label_frame` | `doc_id, frame_id, label` | 人工或模型设置楼层标签，写入伴随的 JSON 文件 |
| `cad_text_search` | `doc_id, query, frame_id?, layer?, regex?, limit` | `[{str,x,y,h,layer,frame_id}]`，加 `truncated` 标志 |
| `cad_blocks` | `doc_id, frame_id?, top?` | `BlockCount[]`；可选 `as_schema:true` 输出 `RecognitionItem` 信封 |
| `cad_rooms` | `doc_id, threshold_pct?` | `RoomCheckItem[]` 加汇总。单位未确认时拒绝，并说明未匹配的可能原因 |
| `cad_table` | `doc_id, rect\|frame_id+rect` | `{rows,nRows,nCols}`，可选 CSV 路径 |
| `cad_layers` | `doc_id` | 图层×线段/文字/块统计，用来人工映射图层 |
| `cad_render` | `doc_id, target:{frame_id}\|{rect}\|{around:{x,y,radius}}, max_px?, scale?, dpi?, background:'white'\|'dark', layers?, hide_layers?, overlay?:{frames,highlights[]}, tile?:{max_px,overlap}` | `{files:[{path,tile:[i,j],world_rect,px_per_unit,size}], text_render:{shx,fallback,dropped}}` |
| `cad_diff` | `old_doc, new_doc, render?:true` | `{counts, offset, png?}` |
| `cad_review_*`（可选，第二期） | 导入、统计、批量改类、导出 | 状态落盘 |

**设计要点**：
- 优先暴露 `cad_open`、`cad_frames`、`cad_text_search`、`cad_render` 四个，已经能覆盖“找一块区域，看它，读它的文字”。
- `cad_render` 需要有明确的“默认不会渲染整张大图”的保护。大图直接渲染整张只会得到一堆线，要提示先用 `cad_frames` 或 `cad_text_search` 缩小范围。
- 文字过密时可以只渲染某图层，或只渲染指定图层的文字。

### 8.3 要新增的 Node 包

| 用途 | 包 | 说明 |
|---|---|---|
| 解析 | `dxf-parser`（已有） | 固定 1.1.2 |
| HATCH | `earcut` | 如果不渲染填充，可省 |
| 栅格 | `@napi-rs/canvas`（首选） | 预编译、Skia。**需要在三个目标平台上实测安装** |
| 降级 | `pngjs` 或 `fast-png` | 纯 JS 输出 PNG |
| 笔画文字 | `@mlightcad/shx-parser` | 可选 |
| 字体 | 打包 Noto Sans SC 子集（OFL） | 路径可配置；可选使用系统字体 |

### 8.4 dwg2dxf 在桌面安装包里的分发

1. **按平台和架构分目录**，如 `bin/darwin-arm64/`、`bin/darwin-x64/`、`bin/win32-x64/`。理想情况是做成每平台一个可选依赖包（类似 esbuild 和 sharp 的做法），让 GPL 组件在物理上和插件主体分开。
2. **查找顺序**：`Config.dwg2dxfPath` → `DWG2DXF_BIN` → 随包目录 → PATH。找不到时要在加载或首次使用时给出清晰报错，不要静默跳过。
3. **Windows**：沿用 CI 的做法（官方 zip 加 sha256 校验，包含同目录 DLL）。
4. **macOS**：官方没有二进制。建议在 CI（`macos-14` 与 `macos-13` 或 universal）用同样的 `./configure --disable-bindings --disable-shared` 从源码静态构建，产物是单个文件，不依赖 `libredwg.0.dylib`。这样可以避免 `DYLD_LIBRARY_PATH` 问题：如果以后给 dwg2dxf 签 hardened runtime，`DYLD_*` 环境变量会被忽略。
5. **Linux**：沿用静态构建。
6. **签名和公证**：mac 的 dwg2dxf 要和宿主应用一起签名和公证；Windows 未签名的 exe 会被 SmartScreen 提示。
7. **GPL 合规物**随二进制放在同一目录或旁边：GPLv3 全文、`VERSION.txt`、对应版本源码压缩包或书面 offer、`THIRD_PARTY_NOTICES`。按 `docs/08` 的清单，发布前还要做 license 扫描门禁，并请 IP 律师确认进程边界。
8. **版本钉死**：CI 用 0.14，本地遗留是 0.13.4，行为有差异，plugin 应记录实际版本（`dwg2dxf --version`），写进 `cad_open` 的输出。

### 8.5 已知风险

1. **中文字体**
   - headless 机器可能没有 PingFang 或微软雅黑。
   - SHX 路线（KST32B）覆盖率约 87%，缺简体专用字，整条回退。
   - 需要随包带一个 OFL 的中文字体子集，并在输出里报告 `shx` 与 `fallback` 的数量。
   - bigfont（hztxt、gbcbig）的 Unicode→GB2312 转换还没实现（README 记为 TODO），客户自带天正字体时只有 unifont 类生效。
   - 天正和 Autodesk 的 SHX 不能随包分发。
2. **大图**
   - 25MB DWG 转出 199MB DXF，409,913 个实体（R3 报告）。
   - JS 一次读入整个字符串有 V8 上限（约 5.36 亿字符），文档称 R7 风险“实锤加重”，流式解析至今没有做。
   - `main.cjs` 的 400MB 上限是人为的保护，`parseHatches` 的 `split` 又会让内存翻倍。
   - 建议：解析放在 worker 或子进程里并设置内存上限；按 `sha256 + SCENE_VERSION` 缓存解析后的二进制场景；超过上限直接报错，提示用户拆图。
   - 渲染在大图上遍历所有线段，需要按矩形做空间剔除（目前每次线性扫描）。
   - `diffScenes` 的字符串键 Map 在大图上很吃内存，没有实测。
3. **GBK**
   - 编码判断只靠“UTF-8 严格解码是否抛错”，不读 `$DWGCODEPAGE`。混合编码或纯 ASCII 的文件不会有问题，但该方法没有对 GBK 字节恰好是合法 UTF-8 的情况做保护（概率很低）。
   - `TextDecoder('gbk')` 需要 Node 带完整 ICU（官方构建默认带）。
   - 文件名是中文时，要处理 Windows 的 ANSI 路径问题（见 §2.2）。
4. **转换保真度**
   - LibreDWG 可能丢对象，例如“废水立管”块在 DXF 里没有定义，README 记为“转换器保真度缺口”。
   - 天正面积文字丢失。
   - 原生 T20 天正图（proxy 实体）没有验证过。
   - 工具输出应该带 `skipped` 统计和警告，让 agent 知道结果不完整。
5. **覆盖盲区**：paperspace/布局视口、块内 HATCH、冻结图层、线型线宽、文字对齐、MTEXT 折行都没处理。这些会导致渲染和真实 CAD 画面有差异，agent 看图时需要知道。
6. **判据假设**：`frames.ts` 的 30m 空白聚类和图层名正则是针对作者手头图纸调出来的，其他图纸上可能误检或漏检。需要在工具描述里写清，并允许参数覆盖。
7. **词表映射**：`blocksToSchema` 的子串匹配有歧义（见 §4.3）。
8. **并发和临时文件**：`Date.now()` 命名会撞；需要 `mkdtemp`、超时、杀进程树、stderr 截断，并保证清理。
9. **许可**：见 §2.4。GPL 进程边界是否足够，文档自己说需要律师确认。

### 8.6 建议的实施顺序

1. 搬运 core 加 convert，补一个“夹具 → `buildScene` → 摘要”的测试，实现 `cad_open`、`cad_text_search`、`cad_frames`、`cad_blocks`。
2. 实现 `cad_render`（先走 `@napi-rs/canvas`，白底、图层过滤、SHX 加字体回退、元数据），用 PNG 测试验证。
3. 补 macOS 的 dwg2dxf 构建、签名、打包，并加三平台冒烟。
4. 再做 `cad_rooms`、`cad_table`、`cad_diff`，以及单位门禁。
5. 最后做 `cad_review_*` 和楼层标签启发式。
