# @zhitong/ui-brand

Web 客户端（浏览器与桌面版共用）的品牌占位插件：在任何构建里填三个品牌位，并标出推荐模型。

| 位置 | 上游 slot | 本插件显示 |
|---|---|---|
| 侧栏左上角图标（含收起后的窄栏） | `sidebar.brand.mark` | 圆角方块「智」 |
| 侧栏左上角名称 | `sidebar.brand.name` | 「智通数工AI」文字标 |
| 新会话页标题旁的图标 | `conversation.hero.brand.mark` | 圆角方块「智」 |
| 输入框的模型选择器 | `conversation.input.model.label` | `deepseek-official` / `deepseek-account` 的 `deepseek-flash` 显示为「DeepSeek V4.1 Flash」加「官方推荐」标签，其余模型保持目录名 |

`zhitong/bundle/cordis.patch.yml` 禁用上游 `ui-brand-official`（只在 official 构建里填侧栏品牌位，用的是 DeepSeek 官方 artwork）与 `ui-deepseek-model-label-1017`，本插件是这些位置唯一的占位者。

## 替换成正式 artwork

现在是文字标占位，颜色取主题 token（`--dsw-alias-brand-primary`、`--dsw-alias-brand-primary-invert`、`--dsw-alias-label-primary`），深浅两种主题自动换色。设计师交付后：

- 应用内：改 `src/client/Brand.tsx` 的两个组件（图标保持正方形、按 `size` 缩放；名称高 24 像素），重跑 `pnpm run build`。
- 静态文件：`assets/{mark,wordmark}-{light,dark}.svg` 是同一占位的浅色 / 深色版本，供文档、门户与桌面欢迎窗口（`apps/desktop/renderer/assets/welcome-brand.svg`，472×40）参照替换。

产品名与推荐标签的文字在 `src/client/locales.ts`（命名空间 `zhitong-brand`），遵守「Client UI copy is locale-owned」。

## 构建与测试

浏览器加载的是 `lib/client.js`（client module registry 按 `exports["./client"]` 提供），根目录 `pnpm run build` 不构建 `zhitong/`：

```sh
pnpm run build        # tsdown：lib/index.js（空的 Host 半边）+ lib/client.js
pnpm vitest run
pnpm run typecheck    # 依赖上游客户端包的 lib/types（pnpm run build:artifacts）
```

桌面安装包由 `zhitong/scripts/pack-desktop.mjs` 构建并打包本插件。
