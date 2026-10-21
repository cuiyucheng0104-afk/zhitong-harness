/**
 * 首页下半部分的延迟水合（00 章 §9 首页首包 JS 预算）。
 * - 数据与复核、安装与交付、常见问题三个区块不参与跨区调用（无 ref 调用、不钉住），
 *   预渲染 HTML 照常完整输出；客户端在浏览器空闲时（最迟 2 s）才加载各自的代码块并水合。
 * - 钉住类区块（岗位、它解决什么、使用流程）与被跨区调用的区块（示例、能力）保持同步加载，
 *   以免钉住距离在其它 ScrollTrigger 之后才插入。
 * - 非首次水合（从文档页切回首页）时，路由先 `preloadHomeSections()`，保证锚点目标在定位前已渲染。
 */
import { defineAsyncComponent, hydrateOnIdle } from 'vue';

const loaders = {
  trust: () => import('../components/TrustSection.vue'),
  install: () => import('../components/InstallSection.vue'),
  faq: () => import('../components/FaqSection.vue'),
} as const;

/** 是否处于首次水合（create-app 按 hydrate 参数设置；main.ts 在 `app.mount` 后置为 false）。 */
export const hydration = { initial: false };

export const LazyTrustSection = defineAsyncComponent({ loader: loaders.trust, hydrate: hydrateOnIdle(2000) });
export const LazyInstallSection = defineAsyncComponent({ loader: loaders.install, hydrate: hydrateOnIdle(2000) });
export const LazyFaqSection = defineAsyncComponent({ loader: loaders.faq, hydrate: hydrateOnIdle(2000) });

/** 预先加载三个区块的代码块。 */
export function preloadHomeSections(): Promise<unknown> {
  return Promise.all(Object.values(loaders).map((load) => load()));
}
