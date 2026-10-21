/**
 * 站内死链检查（00 章 §12“路由”）。用法：`node scripts/check-links.mjs`（先 `npm run build`）。
 * - 扫描 dist 下全部 .html 的 a[href]、link[href]、script[src]、img[src]、source[srcset]；
 * - 站内路径按 nginx 规则解析：`/x/` → `dist/x/index.html`，其余按文件；无尾斜杠的目录地址记为错误（线上会 301，站内不应这样写）；
 * - 带 `#片段` 的链接还要求目标页存在该 id（`#` 与 `#main` 之外）；
 * - 每个预渲染路由（sitemap.xml 的 loc）都必须有 `dist/<路径>/index.html`。
 * - 安装包与 .sha256（releases.json 列出的文件）由发布流程直接上传到服务器 /downloads/，不在 dist 里：只核对文件名与清单一致，单列提示。
 * 发现问题时逐条打印并以退出码 1 结束。
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const dist = new URL('../dist/', import.meta.url).pathname;
const ORIGIN = 'https://ztsgai.com';

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}
const pages = walk(dist).filter((f) => f.endsWith('.html'));
const idCache = new Map();
function idsOf(file) {
  if (!idCache.has(file)) {
    const html = readFileSync(file, 'utf8');
    idCache.set(file, new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => decodeEntities(m[1]))));
  }
  return idCache.get(file);
}
function decodeEntities(s) {
  return s.replace(/&amp;/g, '&').replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n))).replace(/&quot;/g, '"');
}
/** 页面文件 → 其 URL 路径。 */
function urlOf(file) {
  const rel = relative(dist, file).split('\\').join('/');
  if (rel === 'index.html') return '/';
  if (rel.endsWith('/index.html')) return `/${rel.slice(0, -'index.html'.length)}`;
  return `/${rel}`;
}
/** URL 路径 → dist 文件（不存在时 null；目录无尾斜杠时返回 'NO_SLASH'）。 */
function fileOf(pathname) {
  const p = decodeURIComponent(pathname);
  if (p.endsWith('/')) {
    const f = join(dist, p, 'index.html');
    return existsSync(f) ? f : null;
  }
  const f = join(dist, p);
  if (existsSync(f) && statSync(f).isFile()) return f;
  if (existsSync(join(f, 'index.html'))) return 'NO_SLASH';
  return null;
}

const manifest = JSON.parse(readFileSync(join(dist, 'downloads', 'releases.json'), 'utf8'));
const released = new Set(
  Object.values(manifest.platforms)
    .filter((p) => p.file)
    .flatMap((p) => [`/downloads/${p.file}`, `/downloads/${p.file}.sha256`]),
);
const externalSeen = new Set();

const problems = [];
let checked = 0;
const ATTR = /<(a|link|script|img|source|use)\b[^>]*?\s(href|src|srcset|xlink:href)="([^"]*)"/g;
for (const page of pages) {
  const html = readFileSync(page, 'utf8');
  const here = urlOf(page);
  for (const m of html.matchAll(ATTR)) {
    const [, tag, attr, rawValue] = m;
    const values = attr === 'srcset' ? rawValue.split(',').map((s) => s.trim().split(/\s+/)[0]) : [rawValue];
    for (const raw0 of values) {
      const raw = decodeEntities(raw0);
      if (!raw || /^(mailto:|tel:|data:|javascript:)/.test(raw)) continue;
      if (/^https?:\/\//.test(raw) && !raw.startsWith(ORIGIN)) continue; // 外链不检查
      if (tag === 'link' && /rel="(preconnect|dns-prefetch)"/.test(m[0])) continue;
      let url;
      try {
        url = new URL(raw, `${ORIGIN}${here}`);
      } catch {
        problems.push(`${here}：无法解析 ${tag}[${attr}]="${raw}"`);
        continue;
      }
      checked++;
      if (released.has(url.pathname)) {
        externalSeen.add(url.pathname);
        continue;
      }
      const target = fileOf(url.pathname);
      if (target === 'NO_SLASH') {
        problems.push(`${here}：${raw} 指向目录但缺少尾斜杠`);
        continue;
      }
      if (!target) {
        problems.push(`${here}：${raw} → 不存在（${url.pathname}）`);
        continue;
      }
      const frag = decodeURIComponent(url.hash.slice(1));
      if (frag && frag !== 'main' && target.endsWith('.html') && !idsOf(target).has(frag))
        problems.push(`${here}：${raw} → 目标页没有 id="${frag}"`);
    }
  }
}

// 每个路由都有 dist/<路径>/index.html
const sitemap = readFileSync(join(dist, 'sitemap.xml'), 'utf8');
const locs = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1].replace(ORIGIN, ''));
for (const loc of locs) if (!existsSync(join(dist, loc, 'index.html'))) problems.push(`路由 ${loc} 缺少 index.html`);
if (!existsSync(join(dist, '404.html'))) problems.push('缺少 dist/404.html');

console.log(`页面 ${pages.length} 个，路由 ${locs.length} 个，检查链接 ${checked} 条。`);
for (const f of externalSeen) console.log(`提示：${f} 由发布流程上传（releases.json 已列出），dist 中没有该文件`);
if (problems.length) {
  for (const p of [...new Set(problems)]) console.error(`死链：${p}`);
  process.exit(1);
}
console.log('站内链接全部可解析。');
