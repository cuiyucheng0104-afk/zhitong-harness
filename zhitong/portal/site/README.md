# 智通数工AI 门户网站

基于已确认的 v0.1 原型与设计 spec 开发的 Vue 网站，保留蓝白工作底稿视觉、三种交互示例、三类岗位、四组 12 项能力与完整移动端布局。

## 运行

要求 Node.js `^20.19.0` 或 `>=22.12.0`，推荐 Node.js 22 LTS。

```bash
npm ci
npm run dev
```

开发预览：<http://127.0.0.1:5327/>。端口使用严格模式，不会自动切到其他端口。

```bash
npm test
npm run typecheck
npm run build
node scripts/check-links.mjs   # 构建后：每个路由的 index.html 存在、站内链接与锚点可解析
node scripts/check-budget.mjs  # 构建后：首包与懒加载块 gzip 体积对照 00 章 §9 预算（--report 只打印）
npm run preview
```

生产预览：<http://127.0.0.1:5328/>。`npm run build` 依次运行 TypeScript 检查、Vite 客户端构建、Vue 服务端渲染构建与首页预渲染，产出 `dist/`。SSR 临时构建目录在预渲染后自动清理。

`dist/` 可部署到普通静态托管，不需要 Node.js 后端。站点只部署在域名根（`base: '/'`），每个路由预渲染为 `dist/<路径>/index.html`，另有 `dist/404.html`。请通过 HTTP 服务访问；构建后的 ES 模块不支持直接双击 HTML 的 `file://` 访问。

## 工程结构

```text
src/
├── App.vue                    页面组合、跨区导航、统一获取入口
├── main.ts                    开发挂载 / 生产水合
├── entry-server.ts            构建时静态预渲染入口
├── components/
│   ├── SiteHeader.vue         桌面导航、章节高亮、移动菜单
│   ├── HeroSection.vue        首屏文案与布局
│   ├── WorkDemo.vue           三种示例与一次播放动效
│   ├── demo/                  计价表核对 / 投控复核 / CAD 看图
│   ├── BaseDialog.vue         原生 dialog、滚动锁定、焦点恢复
│   ├── SourceDialog.vue       出处与公式
│   ├── AcquireDialog.vue      安装包下载、SHA256、首次打开提示与配置包说明
│   ├── RolesSection.vue       岗位选择与任务入口
│   ├── CapabilitiesSection.vue 四组 12 项能力
│   ├── FeatureArtwork.vue     各能力的成果示意
│   └── …                      流程、数据、安装、FAQ、页脚、图标
├── composables/               演示状态、媒体查询、页面动效
├── data/
│   ├── content.ts             能力、岗位、FAQ、流程与数据说明
│   └── demo.ts                虚构示例数据、金额格式与房间条目
├── lib/                       页签键盘、锚点导航、动效加载
├── styles/                    设计变量 / 基础 / 章节 / 响应式
└── types/portal.ts            场景与动作类型（能力类型转发自 data/capabilities.ts）
scripts/prerender.mjs          构建后输出完整 HTML
scripts/check-links.mjs        构建后死链检查
scripts/check-budget.mjs       构建后 JS 体积预算检查
assets/                       品牌 SVG（来源副本在 zhitong/brand/brand-mark.svg）
public/                       favicon、apple-touch-icon（由 zhitong/scripts/brand-icons 生成）
public/downloads/releases.json 安装包清单：版本、日期、各平台文件名、SHA256、大小
tests/fixtures/prototype-v0.1.html  v0.1 原型首页，内容测试的对照基准
```

原型历史文件（`prototype/`、`versions/`、根目录 `app.js`、`styles.css`、`serve.py`、`资源说明.txt` 与原型动画库）没有进仓库，只保留内容测试用到的 v0.1 首页。

## 设计与内容维护

- 样式变量：`src/styles/tokens.css`。
- 页面正文、岗位、能力、FAQ、流程与数据说明：`src/data/content.ts`。
- 演示金额与房间：`src/data/demo.ts`。合计、核减额和比例由同一组固定示例数据计算，避免分散硬编码。
- 图标：`src/components/AppIcon.vue`，原型 SVG 形状迁移，默认继承 `icon` 类。
- 获取入口：`src/components/AcquireDialog.vue` 与 `InstallSection.vue`，数据来自 `src/data/downloads.ts`。清单 `public/downloads/releases.json` 在构建时读入并校验（`src/data/release-manifest.mjs`）：平台的 `file` 为 `null` 时显示“即将发布”，不出链接；清单写错则构建失败。清单由 `zhitong/portal/deploy/release-manifest.mjs stage` 填写，不要手改哈希与大小。获得有效联系方式后再替换“联系方式待配置”；配置包继续由服务方单独交付。
- 当前设计 spec 与开发计划：Obsidian 知识库 `智通数工AI门户/spec.md`、`plan.md`；v0.2 工程档案首屏为已撤回历史。

## 交互与可访问性

- Tab 键顺序导航；页签支持方向键、Home / End；弹层使用原生 dialog 支持 Esc、遮罩关闭和焦点恢复。
- 手机隐藏示例目录、汇总表转为金额条目、来源改底部弹层、能力改折叠列表、流程改纵向。
- 尊重 `prefers-reduced-motion`。GSAP 由挂载后的动态导入加载，失败时文字和交互仍可使用；组件销毁时回收时间线、ScrollTrigger、媒体订阅和观察器。
- 生产构建预渲染正文，页面无需执行 JavaScript 即可读取静态内容；交互需要 JavaScript。
- 所有图纸、金额、文件与位置为明确标记的示例；投控决定仅当前页面有效，切换场景清除。

## 产品边界与上线前事项

工作台为交互演示，未接真实模型、TOS、DWG 解析、文件上传、报告生成或云运维，没有收集访客资料的表单。安装包从 `/downloads/` 直接下载（nginx 配置与发布流程见 `zhitong/portal/deploy/runbook.md`）。

填写 `src/site.config.ts` 的服务方联系方式（以及法律信息），否则 `ZT_LAUNCH=1 npm run build` 的上线检查失败（结果写在 `dist/.launch-check.json`）。按 01 章 §8.4 / 06 章 §3.7，`deploy.sh` 应改为 `ZT_LAUNCH=1` 构建、上传前读取 `.launch-check.json`、`--skip-build` 时拒绝上传，nginx 加 `error_page 404 /404.html`；这些改动在 `zhitong/portal/deploy/` 下，**尚未落地**，上线前须先完成。

公开上线前仍需补充：品牌方确认的正式品牌 SVG、法律主体、服务联系方式、隐私与备案文案，并复核最终产品能力说明。

## 依赖与资源

Vue 3.5、Vite 7、TypeScript 5.9；GSAP Core / ScrollTrigger 3.13.0 由 npm 锁定。运行时不依赖 CDN、远程字体或图库。

原型品牌图根据用户提供的 Logo 重绘，正式发布需品牌方确认。GSAP 许可见 <https://gsap.com/standard-license/>；原型本地库保留上游版权说明。
