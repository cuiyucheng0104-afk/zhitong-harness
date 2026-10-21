/**
 * 预渲染后对文档页的校验（06 章 §3.5 第 4 条）：HTML 里有该页标题作为 H1（文档首页为「文档」），
 * 清单里该页每个 H2/H3 的 id 都出现在 HTML 中。scripts/prerender.mjs 对每个预渲染路径调用；返回非空即构建失败。
 */
import { docs } from 'virtual:docs-manifest';

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/**
 * @param path - 预渲染路径，如 `/docs/install/`。
 * @param html - 该路径渲染出的正文 HTML。
 * @returns 问题清单。
 */
export function verifyRenderedPage(path: string, html: string): string[] {
  const doc = docs.find((d) => d.path === path);
  if (!doc) return [];
  const problems: string[] = [];
  const h1 = doc.slug === 'index' ? '文档' : doc.title;
  const h1s = [...html.matchAll(/<h1\b[^>]*>([\s\S]*?)<\/h1>/g)].map((m) => m[1].replace(/<[^>]+>/g, '').trim());
  if (h1s.length !== 1) problems.push(`应有 1 个 H1，实有 ${h1s.length} 个`);
  if (!h1s.includes(escapeHtml(h1))) problems.push(`缺少 H1「${h1}」`);
  for (const h of doc.headings) if (!html.includes(`id="${escapeHtml(h.id)}"`)) problems.push(`缺少标题 id「${h.id}」`);
  return problems;
}
