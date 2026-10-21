/**
 * 页面 head（06 章 §3.5）：预渲染时由路由元信息生成 `<!--app-head-->` 的内容；
 * 前端路由切换后由 `router.afterEach` 更新 `document.title` 与 description（不引入 head 管理库）。
 */
import type { RouteMeta } from 'vue-router';

const escape = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/**
 * 生成 head 片段。
 * @param meta - 路由元信息。
 * @returns HTML 字符串。
 */
export function renderHead(meta: Partial<RouteMeta>): string {
  const lines: string[] = [];
  if (meta.title) lines.push(`<title>${escape(meta.title)}</title>`);
  if (meta.description) lines.push(`<meta name="description" content="${escape(meta.description)}" />`);
  if (meta.canonical) lines.push(`<link rel="canonical" href="${escape(meta.canonical)}" />`);
  if (meta.noindex) lines.push('<meta name="robots" content="noindex" />');
  return lines.join('\n    ');
}

/**
 * 客户端更新 head。
 * @param meta - 目标路由元信息。
 */
export function applyHead(meta: Partial<RouteMeta>) {
  if (meta.title) document.title = meta.title;
  let desc = document.head.querySelector<HTMLMetaElement>('meta[name="description"]');
  if (meta.description) {
    if (!desc) {
      desc = document.createElement('meta');
      desc.name = 'description';
      document.head.append(desc);
    }
    desc.content = meta.description;
  } else desc?.remove();
  let canonical = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (meta.canonical) {
    if (!canonical) {
      canonical = document.createElement('link');
      canonical.rel = 'canonical';
      document.head.append(canonical);
    }
    canonical.href = meta.canonical;
  } else canonical?.remove();
  const robots = document.head.querySelector('meta[name="robots"]');
  if (meta.noindex && !robots) {
    const m = document.createElement('meta');
    m.name = 'robots';
    m.content = 'noindex';
    document.head.append(m);
  } else if (!meta.noindex) robots?.remove();
}
