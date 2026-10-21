/**
 * 预渲染（06 章 §3.5；01 章 §8.4）：
 * - 对路由表每个静态路径输出 `dist/<路径>/index.html`（`/` → `dist/index.html`），未知路径输出 `dist/404.html`；
 * - 生成 `dist/sitemap.xml`、`dist/robots.txt`；
 * - 上线检查写入 `dist/.launch-check.json`；`ZT_LAUNCH=1` 时有问题即逐条打印并以退出码 1 结束。
 */
import { mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  NOT_FOUND_PROBE,
  lastmod,
  launchIssues,
  render,
  routes,
  verifyRenderedPage,
} from '../.ssr/entry-server.js';

const ORIGIN = 'https://ztsgai.com';
const dist = new URL('../dist/', import.meta.url);
const template = await readFile(new URL('index.html', dist), 'utf8');
for (const mark of ['<!--app-html-->', '<!--app-head-->'])
  if (!template.includes(mark)) throw new Error(`缺少预渲染插入点 ${mark}`);

/** 把渲染结果套进模板。 */
function page({ html, head, layout }) {
  return template
    .replace('<html lang="zh-CN">', `<html lang="zh-CN" data-layout="${layout}">`)
    .replace('<!--app-head-->', head)
    .replace('<!--app-html-->', html);
}

/** `/docs/install/` → `dist/docs/install/index.html`。 */
function outputFor(path) {
  return new URL(`.${path}index.html`, dist);
}

const problems = [];
for (const path of routes) {
  const result = await render(path);
  if (result.status !== 200) problems.push(`${path}：渲染状态 ${result.status}`);
  if (!result.html.includes('id="main"')) problems.push(`${path}：缺少 #main`);
  for (const issue of verifyRenderedPage(path, result.html)) problems.push(`${path}：${issue}`);
  const file = outputFor(path);
  await mkdir(dirname(fileURLToPath(file)), { recursive: true });
  await writeFile(file, page(result));
}
const home = await readFile(outputFor('/'), 'utf8');
if (!home.includes('智通数工')) problems.push('/：首页预渲染内容不完整');

const missing = await render(NOT_FOUND_PROBE);
if (missing.status !== 404) problems.push(`404：渲染状态 ${missing.status}`);
await writeFile(new URL('404.html', dist), page(missing));

if (problems.length) {
  for (const p of problems) console.error(`预渲染检查失败：${p}`);
  process.exit(1);
}

const today = new Date().toISOString().slice(0, 10);
const sitemap = [
  '<?xml version="1.0" encoding="UTF-8"?>',
  '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
  ...routes.map(
    (path) => `  <url><loc>${ORIGIN}${path}</loc><lastmod>${lastmod[path] ?? today}</lastmod></url>`,
  ),
  '</urlset>',
  '',
].join('\n');
await writeFile(new URL('sitemap.xml', dist), sitemap);
await writeFile(new URL('robots.txt', dist), `User-agent: *\nAllow: /\nSitemap: ${ORIGIN}/sitemap.xml\n`);

const issues = launchIssues();
await writeFile(new URL('.launch-check.json', dist), `${JSON.stringify(issues, null, 2)}\n`);
await rm(new URL('../.ssr/', import.meta.url), { recursive: true, force: true });
console.log(`已预渲染 ${routes.length} 个页面与 404.html：${fileURLToPath(dist)}`);
if (process.env.ZT_LAUNCH === '1' && issues.length) {
  console.error('上线检查未通过：');
  for (const issue of issues) console.error(`- ${issue}`);
  process.exit(1);
}
