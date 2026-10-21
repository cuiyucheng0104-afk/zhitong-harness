/**
 * 文档子站路由（06 章 §1.1、§3.4）：由 frontmatter 清单（`virtual:docs-routes`）生成，构建期已与 §1.1 路由表比对。
 * 父路由 `/docs/` → DocsLayout；子路由的组件就是正文 `.md` 编译出的 SFC，按页懒加载（首页不为文档付出体积）；
 * 页面外框（DocsHome / DocsPage）由 DocsLayout 按路由包在正文外面。
 * router.ts 只导入这里的 `docsRoutes`；预渲染遍历 router 的全部静态路由，sitemap 的 lastmod 取 `updated`。
 */
import type { RouteComponent, RouteRecordRaw } from 'vue-router';
import { docs } from 'virtual:docs-routes';

export interface DocRoute {
  /** 'install'、'features/check'；首页 'index'。 */
  slug: string;
  /** '/docs/install/'；首页 '/docs/'。 */
  path: string;
  title: string;
  group: string;
  order: number;
  /** `src/docs/content/` 下的正文文件名。 */
  file: string;
  /** frontmatter `summary`（≤ 60 字），写入 `<meta name="description">`。 */
  summary: string;
  /** frontmatter `updated`（YYYY-MM-DD），写入 sitemap 的 lastmod。 */
  updated?: string;
}

declare module 'vue-router' {
  interface RouteMeta {
    /** 文档页的 slug（DocsLayout 据此找清单条目）。 */
    docSlug?: string;
  }
}

const SITE = 'https://ztsgai.com';
export const DOCS_HOME_TITLE = '文档 · 智通数工AI';

/** 全部 23 页，按清单顺序（首页在最前）。 */
export const DOC_ROUTES: readonly DocRoute[] = docs;

const pages = import.meta.glob<RouteComponent>('./content/*.md');

/**
 * 页面 `<title>`（§3.5）。
 * @param doc - 文档条目。
 * @returns 标题文字。
 */
export const docTitle = (doc: DocRoute) => (doc.slug === 'index' ? DOCS_HOME_TITLE : `${doc.title} · 文档 · 智通数工AI`);

/** 交给 router.ts 的文档路由记录：DocsLayout 为父路由，文档页之间切换不触发顶层页面过渡。 */
export const docsRoutes: RouteRecordRaw[] = [
  {
    path: '/docs/',
    component: () => import('../pages/docs/DocsLayout.vue'),
    meta: { layout: 'docs' },
    children: DOC_ROUTES.map(
      (doc): RouteRecordRaw => ({
        path: doc.slug === 'index' ? '' : `${doc.slug}/`,
        name: doc.slug === 'index' ? 'docs-home' : `docs:${doc.slug}`,
        component: pages[`./content/${doc.file}`],
        meta: {
          layout: 'docs',
          title: docTitle(doc),
          description: doc.summary,
          canonical: `${SITE}${doc.path}`,
          docSlug: doc.slug,
        },
      }),
    ),
  },
];
