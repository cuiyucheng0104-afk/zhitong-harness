/**
 * 应用工厂：客户端（main.ts）与预渲染（entry-server.ts）共用。
 */
import { createApp as createClientApp, createSSRApp } from 'vue';
import type { Router, RouterHistory } from 'vue-router';
import App from './App.vue';
import { createAppRouter } from './router';
import { vMagnetic } from './composables/useMagnetic';
import { vSpotlight } from './composables/useSpotlight';
import { hydration } from './pages/home-sections';

/**
 * 创建应用与路由。
 * @param history - 路由 history。
 * @param hydrate - 是否走水合（预渲染页面与 SSR 为 true）；也可传函数，拿到路由后再决定
 *   （客户端用它判断服务器回的预渲染 HTML 是否就是当前地址的页面）。
 * @returns app 与 router。
 */
export function createPortalApp(history: RouterHistory, hydrate: boolean | ((router: Router) => boolean)) {
  const router = createAppRouter(history);
  const ssr = typeof hydrate === 'function' ? hydrate(router) : hydrate;
  // 只有水合预渲染页时才延迟水合首页下半部分；纯客户端渲染时路由先预载这些区块（pages/home-sections.ts）。
  hydration.initial = ssr;
  const app = ssr ? createSSRApp(App) : createClientApp(App);
  app.use(router);
  app.directive('magnetic', vMagnetic);
  app.directive('spotlight', vSpotlight);
  return { app, router };
}
