/**
 * 路由（00 章 §3.1；06 章 §3.5）：history 模式，路由表与预渲染共用。
 * 所有路径带尾斜杠（`strict: true`）；nginx 把无尾斜杠的目录地址 301 到带斜杠的地址。
 * 未知路径渲染 404 页（`dist/404.html` 由预渲染 `/__not_found__/` 生成）。
 */
import { createRouter, type RouteRecordRaw, type RouterHistory, type RouterScrollBehavior } from 'vue-router';
import { hydration, preloadHomeSections } from './pages/home-sections';
import { docsRoutes } from './docs/routes';
import type { PageLayout } from './composables/useHeaderState';

declare module 'vue-router' {
  interface RouteMeta {
    /** 顶栏状态、页面切换过渡的 key（01 章 §13）。 */
    layout: PageLayout;
    /** `<title>`。 */
    title?: string;
    /** `<meta name="description">`；省略时不输出。 */
    description?: string;
    /** `<link rel="canonical">`；省略时不输出。 */
    canonical?: string;
    /** 输出 `<meta name="robots" content="noindex">`。 */
    noindex?: boolean;
  }
}

export const SITE_ORIGIN = 'https://ztsgai.com';
export const HOME_TITLE = '智通数工AI · 造价咨询公司的对话式工作台';
export const HOME_DESCRIPTION =
  '智通数工AI，造价咨询公司的对话式工作台。用对话读资料、做核对、算指标、写报告，让资料、计算和成果有据可查。';
/** 预渲染 404 页时请求的地址。 */
export const NOT_FOUND_PROBE = '/__not_found__/';

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    // 首页按路由懒加载：文档页首包不含首页代码（00 章 §9、06 章 AC-06-22）。
    component: async () => {
      const page = await import('./pages/HomePage.vue');
      if (!hydration.initial) await preloadHomeSections();
      return page;
    },
    meta: { layout: 'home', title: HOME_TITLE, description: HOME_DESCRIPTION, canonical: `${SITE_ORIGIN}/` },
  },
  ...docsRoutes,
  {
    path: '/privacy/',
    name: 'privacy',
    component: () => import('./pages/PrivacyPage.vue'),
    meta: { layout: 'docs', title: '隐私说明 · 智通数工AI', canonical: `${SITE_ORIGIN}/privacy/` },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('./pages/NotFoundPage.vue'),
    meta: { layout: 'notfound', title: '页面不存在 · 智通数工AI', noindex: true },
  },
];

function flatten(records: readonly RouteRecordRaw[], base = ''): string[] {
  return records.flatMap((r) => {
    const path = r.path.startsWith('/') ? r.path : `${base}${r.path}`;
    const own = path.includes(':') || (r.children && !r.component && !('components' in r)) ? [] : [path];
    return [...own, ...(r.children ? flatten(r.children, path) : [])];
  });
}

/** 需要预渲染为 `dist/<路径>/index.html` 的路径（不含 404），去重、保持路由表顺序。 */
export const prerenderPaths: string[] = [...new Set(flatten(routes))];

/**
 * 滚动行为（01 章 §13；06 章 §9.3）：跨页面类型时返回 false（由 App.vue 的过渡钩子定位）；
 * 文档页之间：前进后退恢复 savedPosition，带锚点 instant 定位，其余回到页顶。
 */
export const scrollBehavior: RouterScrollBehavior = (to, from, saved) => {
  if (to.meta.layout !== from.meta.layout) return false;
  if (to.path === from.path && to.hash === from.hash) return false;
  if (saved) return saved;
  if (to.hash) return { el: decodeURIComponent(to.hash), behavior: 'instant', top: 96 };
  if (to.path === from.path) return false;
  return { top: 0, behavior: 'instant' };
};

/**
 * 创建路由实例。
 * @param history - 客户端 `createWebHistory()`，预渲染 `createMemoryHistory()`。
 * @returns router。
 */
export function createAppRouter(history: RouterHistory) {
  return createRouter({ history, routes, strict: true, scrollBehavior });
}
