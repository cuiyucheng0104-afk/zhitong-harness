/**
 * 预渲染入口（06 章 §3.5；01 章 §8.4）。
 */
import { renderToString } from '@vue/server-renderer';
import { createMemoryHistory } from 'vue-router';
import { createPortalApp } from './create-app';
import { renderHead } from './lib/head';
import { NOT_FOUND_PROBE, prerenderPaths } from './router';
import { DOC_ROUTES } from './docs/routes';
import { verifyRenderedPage } from './docs/verify';
import { launchIssues as contactIssues, legalLaunchIssues, siteConfig } from './site.config';

/** 需要预渲染的全部路径（`/`、`/docs/`、每个文档页、`/privacy/`）。 */
export const routes: string[] = prerenderPaths;
export { NOT_FOUND_PROBE, verifyRenderedPage };

/** sitemap 的 lastmod：文档页取 frontmatter `updated`，其余由预渲染脚本填构建日期。 */
export const lastmod: Record<string, string> = Object.fromEntries(
  DOC_ROUTES.filter((d) => d.updated).map((d) => [d.path, d.updated!]),
);

/**
 * 渲染一个地址。
 * @param url - 站内路径。
 * @returns 正文 HTML、head 片段、状态码与页面类型（写入 `<html data-layout>`）。
 */
export async function render(
  url: string,
): Promise<{ html: string; head: string; status: 200 | 404; layout: string }> {
  const { app, router } = createPortalApp(createMemoryHistory(), true);
  await router.push(url);
  await router.isReady();
  const route = router.currentRoute.value;
  const html = await renderToString(app);
  return {
    html,
    head: renderHead(route.meta),
    status: route.name === 'not-found' ? 404 : 200,
    layout: route.meta.layout,
  };
}

/**
 * 上线检查：联系方式 + 法律信息。
 * @returns 问题清单，空数组表示可以上线。
 */
export function launchIssues(): string[] {
  return [...contactIssues(siteConfig.contact), ...legalLaunchIssues(siteConfig.legal, routes)];
}
