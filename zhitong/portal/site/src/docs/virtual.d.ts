/** 文档虚拟模块与 `.md` 组件的类型（由 build/docs-plugin.ts 生成，06 章 §3.4）。 */

declare module 'virtual:docs-routes' {
  /** 路由用条目（不含目录，进主包）。 */
  export interface DocRouteEntry {
    slug: string;
    path: string;
    title: string;
    group: string;
    order: number;
    summary: string;
    updated: string;
    file: string;
  }
  export const docs: DocRouteEntry[];
}

declare module 'virtual:docs-manifest' {
  export interface DocHeading {
    level: 2 | 3;
    text: string;
    id: string;
  }
  export interface DocEntry {
    /** 'install'、'features/check'；首页 'index'。 */
    slug: string;
    /** '/docs/install/'；首页 '/docs/'。 */
    path: string;
    title: string;
    group: string;
    order: number;
    summary: string;
    /** 'YYYY-MM-DD' */
    updated: string;
    /** 本页目录用；id 由 build/docs-slug.ts 生成。 */
    headings: DocHeading[];
  }
  /** 按组顺序、组内 order 排好（首页在最前）。 */
  export const docs: DocEntry[];
  export const groups: { name: string; description: string; items: DocEntry[] }[];
}

declare module 'virtual:docs-search-index' {
  /** 搜索索引 JSON 的同源 URL。 */
  const url: string;
  export default url;
}

declare module '*.md' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent;
  export default component;
}
