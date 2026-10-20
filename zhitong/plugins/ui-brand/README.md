# @zhitong/ui-brand

Web 客户端（浏览器与桌面版共用）的品牌占位插件：在任何构建里填三个品牌位，并标出推荐模型。

| 位置 | 上游 slot | 本插件显示 |
|---|---|---|
| 侧栏左上角图标（含收起后的窄栏） | `sidebar.brand.mark` | 品牌图形（`zhitong/brand/brand-mark.svg`） |
| 侧栏左上角名称 | `sidebar.brand.name` | 「智通数工AI」文字标 |
| 新会话页标题旁的图标 | `conversation.hero.brand.mark` | 品牌图形（同上） |
| 输入框的模型选择器 | `conversation.input.model.label` | `deepseek-official` / `deepseek-account` 的 `deepseek-flash` 显示为「DeepSeek V4.1 Flash」加「官方推荐」标签，其余模型保持目录名 |

`zhitong/bundle/cordis.patch.yml` 禁用上游 `ui-brand-official`（只在 official 构建里填侧栏品牌位，用的是 DeepSeek 官方 artwork）与 `ui-deepseek-model-label-1017`，本插件是这些位置唯一的占位者。

## 品牌图形与字标

图标是 `zhitong/brand/brand-mark.svg` 的图形（蓝色渐变圆角方块、白十字、绿色短划），在 `src/client/Brand.tsx` 里以内联 SVG 画出：颜色写死，不引用外部文件或 asset URL，打包后的桌面版（`app.asar`）与浏览器显示一致，深浅主题都不变色。每个实例用 `useId` 生成自己的渐变 id：侧栏同时渲染展开与收起两份图标，共用一个 id 时 `url(#…)` 可能解析到隐藏的那一份而画不出渐变。

之前的占位图标是主题色方块上叠一个「智」字，方块用 `--dsw-alias-brand-primary`、字用 `--dsw-alias-brand-primary-invert`；这两个 token 在 `packages/client/ui-theme/src/styles/design-platform.css` 的浅色与深色主题里取值相同，字与底同色，看上去是空白圆角方块。

字标仍是文字（高 24 像素），颜色取 `--dsw-alias-label-primary`。品牌方换稿后：先替换 `zhitong/brand/brand-mark.svg`（见 `zhitong/brand/README.md`），再把 `Brand.tsx` 的路径与颜色同步过来，重跑 `pnpm run build`。`assets/wordmark-{light,dark}.svg` 是字标的浅色 / 深色静态版本，供文档、门户与桌面欢迎窗口（`apps/desktop/renderer/assets/welcome-brand.svg`，472×40）参照。

产品名与推荐标签的文字在 `src/client/locales.ts`（命名空间 `zhitong-brand`），遵守「Client UI copy is locale-owned」。新会话页标题「造价咨询工作台」与输入框占位不归本插件：locale 服务的每个（命名空间, 语言）只允许一个注册者，插件不能覆盖 `conversation` 命名空间里的条目，所以它们直接改在 `packages/client/ui-conversation/src/client/locales.ts`（`zhitong increment`）。

## 构建与测试

浏览器加载的是 `lib/client.js`（client module registry 按 `exports["./client"]` 提供），根目录 `pnpm run build` 不构建 `zhitong/`：

```sh
pnpm run build        # tsdown：lib/index.js（空的 Host 半边）+ lib/client.js
pnpm vitest run
pnpm run typecheck    # 依赖上游客户端包的 lib/types（pnpm run build:artifacts）
```

桌面安装包由 `zhitong/scripts/pack-desktop.mjs` 构建并打包本插件。
