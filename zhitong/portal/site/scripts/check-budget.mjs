/**
 * 构建产物 JS 体积对照 00 章 §9 预算（gzip）。用法：`node scripts/check-budget.mjs`（先 `npm run build`）。
 * - 入口首包：dist/index.html 里的 <script type=module> 与 modulepreload，再加它们的静态 import 闭包。
 * - 页面首包：入口首包 + 该页路由组件块（按文件名前缀找到）及其静态 import 闭包；这些块在水合前必须加载。
 * - 懒加载块：动效块（gsap + 插件 + lenis 的动态 import 闭包）、装饰动效块（components/deco/live/*）。
 * 超出预算时打印“超出”并以退出码 1 结束；`--report` 只打印不失败。
 */
import { readFileSync, readdirSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { join } from 'node:path';

const dist = new URL('../dist/', import.meta.url).pathname;
const assets = join(dist, 'assets');
const files = readdirSync(assets).filter((f) => f.endsWith('.js'));
const gz = new Map(files.map((f) => [f, gzipSync(readFileSync(join(assets, f))).length]));
const src = new Map(files.map((f) => [f, readFileSync(join(assets, f), 'utf8')]));
const kb = (n) => (n / 1024).toFixed(1);

/** 静态 import（不含 import()）。 */
function staticDeps(f) {
  const code = src.get(f) ?? '';
  const out = new Set();
  for (const m of code.matchAll(/(?:^|[;\s}])import\s*(?:[\w$*{},\s]+from\s*)?["']\.\/([^"']+\.js)["']/g)) out.add(m[1]);
  for (const m of code.matchAll(/\bfrom\s*["']\.\/([^"']+\.js)["']/g)) out.add(m[1]);
  return out;
}
function dynamicDeps(f) {
  const code = src.get(f) ?? '';
  return new Set([...code.matchAll(/import\(\s*["']\.\/([^"']+\.js)["']\s*\)/g)].map((m) => m[1]));
}
function closure(roots) {
  const seen = new Set();
  const stack = [...roots];
  while (stack.length) {
    const f = stack.pop();
    if (seen.has(f) || !gz.has(f)) continue;
    seen.add(f);
    for (const d of staticDeps(f)) stack.push(d);
  }
  return seen;
}
const sum = (set) => [...set].reduce((n, f) => n + (gz.get(f) ?? 0), 0);
const byPrefix = (p) => files.filter((f) => f.startsWith(p));

const html = readFileSync(join(dist, 'index.html'), 'utf8');
const entryRoots = [...html.matchAll(/<(?:script[^>]+src|link[^>]+rel="modulepreload"[^>]+href)="\/assets\/([^"]+\.js)"/g)].map((m) => m[1]);
const entry = closure(entryRoots);

const rows = [];
let failed = false;
function check(name, bytes, budgetKB, note = '') {
  const over = budgetKB != null && bytes > budgetKB * 1024;
  if (over) failed = true;
  rows.push(`${over ? '超出' : '  ok'}  ${name.padEnd(34)} ${kb(bytes).padStart(6)} KB${budgetKB != null ? ` / ${budgetKB} KB` : ''}${note ? `  ${note}` : ''}`);
}

check('入口首包（全站共用）', sum(entry), null);
const page = (name, prefixes, budget) => {
  const roots = prefixes.flatMap(byPrefix);
  const all = new Set([...entry, ...closure(roots)]);
  check(name, sum(all), budget, `路由块 ${roots.join(', ') || '（未找到）'}`);
  return all;
};
const home = page('首页首包（入口 + 首页路由块）', ['HomePage-'], 90);
page('文档首页首包', ['DocsLayout-', 'index-'].slice(0, 1), 90);
page('/docs/install/ 首包', ['DocsLayout-', 'install-'], 90);
page('/docs/features/check/ 首包', ['DocsLayout-', 'features-check-'], 90);

// 首页延迟水合块（hydrateOnIdle）：不计入首包，单列。
const lazyHome = ['TrustSection-', 'InstallSection-', 'FaqSection-'].flatMap(byPrefix);
const lazyClosure = new Set([...closure(lazyHome)].filter((f) => !home.has(f)));
check('首页延迟水合块（空闲时加载）', sum(lazyClosure), null, lazyHome.join(', '));

// 动效块：GSAP 核心（含 gsap.com 提示串的块）、各插件块与 Lenis。
const motionSet = files.filter(
  (f) => /^(ScrollTrigger|Flip|MotionPathPlugin|Observer|DrawSVGPlugin|lenis)-/.test(f) || src.get(f).includes('gsap.com'),
);
check('动效懒加载块（GSAP + 插件 + Lenis）', sum(new Set(motionSet)), 75, motionSet.join(', '));

for (const f of files.filter((f) => /^(HeroGridCanvas|InstallFieldCanvas|FooterMarkCanvas)-/.test(f))) {
  const own = new Set([...closure([f])].filter((x) => !entry.has(x) && !home.has(x)));
  check(`装饰动效块 ${f.split('-')[0]}`, sum(own), 12);
}

console.log(rows.join('\n'));
if (failed && !process.argv.includes('--report')) process.exit(1);
