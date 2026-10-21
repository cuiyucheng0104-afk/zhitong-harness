/**
 * 文档子站 Vite 插件（06 章 §3）：
 * - 用 unplugin-vue-markdown 把 `src/docs/content/*.md` 编译成 Vue SFC（markdown-it 配置见 docs-markdown.ts）；
 * - 生成虚拟模块 `virtual:docs-routes`（路由用：标题、摘要、日期，不含目录）与 `virtual:docs-manifest`（§3.4，含 H2/H3）；
 * - 构建期检查（§3.8），任一失败即中止并打印「文件:行号 原因」；
 * - 生成搜索索引 `assets/search-index-<hash>.json`（§8.3），URL 经 `virtual:docs-search-index` 注入搜索模块；
 *   检查搜索逻辑块与索引的体积预算（§8.6）。
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, extname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
import MarkdownIt from 'markdown-it';
import type Token from 'markdown-it/lib/token.mjs';
import Markdown from 'unplugin-vue-markdown/vite';
import type { Plugin, ResolvedConfig } from 'vite';
import { DOC_GROUPS, DOC_TABLE, FEATURE_H2, HOME_GROUP, docFile, docPath } from '../src/docs/groups';
import { RULER_SECTIONS } from '../src/data/nav';
import { CONTAINERS, containerTitle, getHighlighter, inlineText, setupDocsMarkdown } from './docs-markdown';
import { createSlugger, slugify } from './docs-slug';

const SITE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
/** 仓库根（frontmatter `sources` 相对它）。 */
const REPO_ROOT = resolve(SITE_ROOT, '../../..');
const CONTENT_DIR = resolve(SITE_ROOT, 'src/docs/content');

const FIELDS = ['title', 'slug', 'group', 'order', 'summary', 'updated', 'sources', 'layout'] as const;
const REQUIRED = ['title', 'slug', 'group', 'order', 'summary', 'updated', 'sources'];
/** 首页章节锚点（正文可写 `/#faq` 等）。 */
const HOME_ANCHORS = new Set<string>(['main', 'top', ...RULER_SECTIONS, 'capabilities', 'workflow', 'trust', 'faq']);

/** §8.6 体积预算（字节）。 */
export const BUDGET = { searchChunkGzip: 6 * 1024, indexGzip: 120 * 1024, indexRaw: 480 * 1024 };

export interface DocHeading {
  level: 2 | 3;
  text: string;
  id: string;
}
export interface DocEntry {
  slug: string;
  path: string;
  title: string;
  group: string;
  order: number;
  summary: string;
  updated: string;
  file: string;
  headings: DocHeading[];
}
export interface SearchIndex {
  v: 1;
  pages: { p: string; t: string; g: string }[];
  sections: { d: number; h: string; a: string; x: string }[];
}

interface ParsedDoc {
  file: string;
  rel: string;
  fm: Record<string, string | string[]>;
  /** 正文第一行在文件中的行号（1 起）。 */
  bodyLine: number;
  tokens: Token[];
}

/** 文档检查失败：消息为「文件:行号 原因」逐行。 */
export class DocsCheckError extends Error {
  constructor(public readonly problems: string[]) {
    super(`文档构建检查未通过（${problems.length} 项）：\n${problems.join('\n')}`);
  }
}

/**
 * 严格解析 frontmatter（固定字段；`sources` 为列表）。
 * @param text - 文件全文。
 * @returns 字段、正文与正文起始行；没有 frontmatter 时 fm 为 null。
 */
export function parseFrontmatter(text: string): {
  fm: Record<string, string | string[]> | null;
  body: string;
  bodyLine: number;
  problems: { line: number; message: string }[];
} {
  const lines = text.split('\n');
  const problems: { line: number; message: string }[] = [];
  if (lines[0] !== '---') return { fm: null, body: text, bodyLine: 1, problems: [{ line: 1, message: '缺少 frontmatter' }] };
  const end = lines.indexOf('---', 1);
  if (end < 0) return { fm: null, body: text, bodyLine: 1, problems: [{ line: 1, message: 'frontmatter 没有结束标记 ---' }] };
  const fm: Record<string, string | string[]> = {};
  let list: string | null = null;
  for (let i = 1; i < end; i++) {
    const line = lines[i];
    const item = /^ {2}- (.+)$/.exec(line);
    if (item && list) {
      (fm[list] as string[]).push(item[1].trim());
      continue;
    }
    const kv = /^([A-Za-z]+):(?: (.*))?$/.exec(line);
    if (!kv) {
      problems.push({ line: i + 1, message: `无法解析的 frontmatter 行：${line}` });
      continue;
    }
    const [, key, value = ''] = kv;
    if (key in fm) problems.push({ line: i + 1, message: `字段 ${key} 重复` });
    if (value.trim() === '') {
      fm[key] = [];
      list = key;
    } else {
      fm[key] = value.trim();
      list = null;
    }
  }
  return { fm, body: lines.slice(end + 1).join('\n'), bodyLine: end + 2, problems };
}

function createParser() {
  const md = new MarkdownIt({ html: false, linkify: false, typographer: false });
  setupDocsMarkdown(md);
  return md;
}

function headingsOf(tokens: Token[]): DocHeading[] {
  const out: DocHeading[] = [];
  tokens.forEach((t, i) => {
    if (t.type !== 'heading_open' || (t.tag !== 'h2' && t.tag !== 'h3')) return;
    out.push({ level: t.tag === 'h2' ? 2 : 3, text: inlineText(tokens[i + 1].children).trim(), id: t.attrGet('id') ?? '' });
  });
  return out;
}

/** 读取并解析全部正文（不检查）。 */
function readDocs(md: MarkdownIt, dir: string): { docs: ParsedDoc[]; problems: string[] } {
  const problems: string[] = [];
  const docs: ParsedDoc[] = [];
  for (const name of readdirSync(dir).filter((n) => n.endsWith('.md')).sort()) {
    const file = resolve(dir, name);
    const rel = relative(SITE_ROOT, file);
    const text = readFileSync(file, 'utf8');
    const { fm, body, bodyLine, problems: fmProblems } = parseFrontmatter(text);
    for (const p of fmProblems) problems.push(`${rel}:${p.line} ${p.message}`);
    let tokens: Token[] = [];
    try {
      tokens = md.parse(body, {});
    } catch (e) {
      problems.push(`${rel}:1 ${(e as Error).message}`);
    }
    docs.push({ file, rel, fm: fm ?? {}, bodyLine, tokens });
  }
  return { docs, problems };
}

const lineOf = (doc: ParsedDoc, token: Token | undefined) => doc.bodyLine + (token?.map?.[0] ?? 0);

/**
 * 构建期检查（§3.8 第 1–7 条）并生成清单。
 * @param dir - 正文目录，默认 `src/docs/content/`（测试可传临时目录）。
 * @returns 清单（按组顺序、组内 order 排好）与问题清单。
 */
export function analyzeDocs(dir = CONTENT_DIR): { entries: DocEntry[]; problems: string[]; parsed: ParsedDoc[] } {
  const md = createParser();
  const { docs, problems } = readDocs(md, dir);
  const base = (d: ParsedDoc) => d.file.slice(dir.length + 1);
  const byFile = new Map(docs.map((d) => [base(d), d]));

  // 1. 路由表每行都有文件；每个文件都在路由表中。
  for (const row of DOC_TABLE)
    if (!byFile.has(docFile(row.slug))) problems.push(`${relative(SITE_ROOT, resolve(dir, docFile(row.slug)))}:1 路由表（06 章 §1.1）中的「${row.title}」缺少正文文件`);
  const tableFiles = new Set(DOC_TABLE.map((r) => docFile(r.slug)));
  for (const d of docs)
    if (!tableFiles.has(base(d))) problems.push(`${d.rel}:1 文件不在路由表（06 章 §1.1）中`);

  const groupNames = new Set([HOME_GROUP, ...DOC_GROUPS.map((g) => g.name)]);
  const entries: DocEntry[] = [];
  for (const d of docs) {
    const name = base(d);
    const row = DOC_TABLE.find((r) => docFile(r.slug) === name);
    const fm = d.fm;
    const at = (key: string) => {
      const idx = readFileSync(d.file, 'utf8').split('\n').findIndex((l) => l.startsWith(`${key}:`));
      return `${d.rel}:${idx < 0 ? 1 : idx + 1}`;
    };
    // 2. 字段齐全、无多余字段、与路由表一致。
    for (const key of Object.keys(fm))
      if (!(FIELDS as readonly string[]).includes(key)) problems.push(`${at(key)} frontmatter 多余字段 ${key}`);
    for (const key of REQUIRED) if (!(key in fm)) problems.push(`${d.rel}:1 frontmatter 缺少字段 ${key}`);
    const str = (key: string) => (typeof fm[key] === 'string' ? (fm[key] as string) : '');
    const slug = str('slug');
    if (row) {
      if (str('title') !== row.title) problems.push(`${at('title')} title「${str('title')}」与路由表「${row.title}」不一致`);
      if (slug !== row.slug) problems.push(`${at('slug')} slug「${slug}」与路由表「${row.slug}」不一致`);
      if (str('group') !== row.group) problems.push(`${at('group')} group「${str('group')}」与路由表「${row.group}」不一致`);
      if (str('order') !== String(row.order)) problems.push(`${at('order')} order「${str('order')}」与路由表「${row.order}」不一致`);
    }
    if ('group' in fm && !groupNames.has(str('group'))) problems.push(`${at('group')} group「${str('group')}」不在组列表（§1.2）中`);
    if ('summary' in fm && [...str('summary')].length > 60) problems.push(`${at('summary')} summary 超过 60 字`);
    const updated = str('updated');
    if ('updated' in fm && (!/^\d{4}-\d{2}-\d{2}$/.test(updated) || Number.isNaN(Date.parse(`${updated}T00:00:00Z`))))
      problems.push(`${at('updated')} updated「${updated}」不是 YYYY-MM-DD`);
    if ('layout' in fm && !(slug === 'index' && fm.layout === 'home')) problems.push(`${at('layout')} 只有首页写 layout: home`);
    if (slug === 'index' && fm.layout !== 'home') problems.push(`${d.rel}:1 首页须写 layout: home`);
    // 3. sources 至少一条且路径存在。
    const sources = Array.isArray(fm.sources) ? fm.sources : [];
    if ('sources' in fm && !sources.length) problems.push(`${at('sources')} sources 至少一条`);
    for (const s of sources) if (!existsSync(resolve(REPO_ROOT, s))) problems.push(`${at('sources')} sources 路径不存在：${s}`);

    // 5. 标题层级：无 H1、无 H4+；能力页 H2 恰为 §6.2；其它页 H2 不少于 3。
    const h2: { text: string; token: Token }[] = [];
    d.tokens.forEach((t, i) => {
      if (t.type !== 'heading_open') return;
      const level = Number(t.tag.slice(1));
      if (level === 1) problems.push(`${d.rel}:${lineOf(d, t)} 正文不能有 H1（H1 由布局输出）`);
      if (level >= 4) problems.push(`${d.rel}:${lineOf(d, t)} 不能写 H4 及更深的标题`);
      if (level === 2) h2.push({ text: inlineText(d.tokens[i + 1].children).trim(), token: t });
    });
    if (name.startsWith('features-')) {
      const got = h2.map((h) => h.text);
      if (got.join('|') !== FEATURE_H2.join('|')) {
        const firstBad = got.findIndex((g, i) => g !== FEATURE_H2[i]);
        const where = firstBad >= 0 ? lineOf(d, h2[firstBad].token) : d.bodyLine;
        problems.push(
          `${d.rel}:${where} 能力页的 H2 与 06 章 §6.2 不一致：应为「${FEATURE_H2.join('、')}」，实为「${got.join('、')}」`,
        );
      }
    } else if (h2.length < 3) problems.push(`${d.rel}:${d.bodyLine} 非能力页 H2 不少于 3 个（现有 ${h2.length} 个）`);

    // 6. 容器：只用 §5 列出的；不嵌套；doc-cards 只在 index.md。7. 不含原始 HTML。
    let depth = 0;
    d.tokens.forEach((t, ti) => {
      const open = /^container_(.+)_open$/.exec(t.type);
      if (open) {
        if (depth > 0) problems.push(`${d.rel}:${lineOf(d, t)} 容器不能嵌套（::: ${open[1]}）`);
        depth++;
        if (open[1] === 'doc-cards' && name !== 'index.md') problems.push(`${d.rel}:${lineOf(d, t)} ::: doc-cards 只能用于 index.md`);
      } else if (/^container_.+_close$/.test(t.type)) depth--;
      if (t.type === 'paragraph_open') {
        // 未注册的 ::: 写法会被当作普通段落。
        const next = d.tokens[ti + 1];
        const m = /^:::\s*(\S*)/.exec(next?.content ?? '');
        if (m) problems.push(`${d.rel}:${lineOf(d, t)} 未知或写错的容器「::: ${m[1]}」（只能用 ${CONTAINERS.join(' / ')}）`);
      }
      if (t.type === 'html_block' || t.type === 'html_inline') problems.push(`${d.rel}:${lineOf(d, t)} 正文不能写原始 HTML`);
      if (t.type === 'inline')
        for (const c of t.children ?? []) {
          if (c.type === 'text' && /<\/?[A-Za-z][A-Za-z0-9-]*(\s[^<>]*)?\/?>/.test(c.content))
            problems.push(`${d.rel}:${lineOf(d, t)} 正文不能写原始 HTML：${c.content.trim().slice(0, 40)}`);
          if (c.type === 'image') {
            const src = c.attrGet('src') ?? '';
            const img = resolve(dirname(d.file), src);
            if (!/^\.\/images\//.test(src) || !existsSync(img)) problems.push(`${d.rel}:${lineOf(d, t)} 图片不存在或不在 ./images/ 下：${src}`);
            else if (!['.png', '.webp'].includes(extname(img).toLowerCase())) problems.push(`${d.rel}:${lineOf(d, t)} 图片须为 PNG 或 WebP：${src}`);
            else if (statSync(img).size > 200 * 1024) problems.push(`${d.rel}:${lineOf(d, t)} 图片超过 200 KB：${src}`);
          }
        }
    });

    // 锚点 id 只由 docs-slug 生成：清单 id 与独立重算一致。
    const headings = headingsOf(d.tokens);
    const seen = new Map<string, number>();
    for (const h of headings) {
      const base = slugify(h.text);
      const n = (seen.get(base) ?? 0) + 1;
      seen.set(base, n);
      const expect = n === 1 ? base : `${base}-${n}`;
      if (h.id !== expect) problems.push(`${d.rel}:${d.bodyLine} 标题「${h.text}」的锚点 ${h.id} 与 docs-slug 结果 ${expect} 不一致`);
    }

    if (row)
      entries.push({
        slug: row.slug,
        path: docPath(row.slug),
        title: row.title,
        group: row.group,
        order: row.order,
        summary: str('summary'),
        updated,
        file: name,
        headings,
      });
  }

  // 4. 站内链接与锚点（§2.5）。
  const anchors = new Map(entries.map((e) => [e.path, new Set(e.headings.map((h) => h.id))]));
  for (const d of docs)
    d.tokens.forEach((t) => {
      if (t.type !== 'inline') return;
      for (const c of t.children ?? []) {
        if (c.type !== 'link_open') continue;
        const href = c.attrGet('href') ?? '';
        if (/^https?:\/\//.test(href)) continue;
        const [path, rawHash = ''] = href.split('#');
        const hash = safeDecode(rawHash);
        const where = `${d.rel}:${lineOf(d, t)}`;
        if (path === '/') {
          if (!hash || !HOME_ANCHORS.has(hash)) problems.push(`${where} 首页锚点不存在：${href}`);
          continue;
        }
        if (!path.startsWith('/docs/') || !path.endsWith('/')) {
          problems.push(`${where} 站内链接须以 /docs/ 开头、以 / 结尾：${safeDecode(href)}`);
          continue;
        }
        const target = anchors.get(path);
        if (!target) problems.push(`${where} 链接指向不存在的页面：${safeDecode(href)}`);
        else if (hash && !target.has(hash)) problems.push(`${where} 链接指向不存在的锚点：${safeDecode(href)}`);
      }
    });

  const order = (e: DocEntry) => (e.group === HOME_GROUP ? -1 : DOC_GROUPS.findIndex((g) => g.name === e.group));
  entries.sort((a, b) => order(a) - order(b) || a.order - b.order);
  // 组内序不重复。
  for (let i = 1; i < entries.length; i++)
    if (entries[i].group === entries[i - 1].group && entries[i].order === entries[i - 1].order)
      problems.push(`${relative(SITE_ROOT, resolve(dir, entries[i].file))}:1 组「${entries[i].group}」内 order ${entries[i].order} 重复`);
  return { entries, problems, parsed: docs };
}

function safeDecode(s: string) {
  try {
    return decodeURIComponent(s);
  } catch {
    // 非法百分号编码：按原文比对，交给锚点检查报错。
    return s;
  }
}

/**
 * 搜索索引（§8.3）：每页按 H2/H3 切小节，H2 之前的导语归入「概述」；纯文本保留表格、说法与代码块内容。
 * @param entries - 清单。
 * @param parsed - 解析结果。
 * @returns 索引对象。
 */
export function buildSearchIndex(entries: DocEntry[], parsed: ParsedDoc[]): SearchIndex {
  const index: SearchIndex = { v: 1, pages: [], sections: [] };
  entries.forEach((e, d) => {
    index.pages.push({ p: e.path, t: e.title, g: e.group });
    const doc = parsed.find((p) => p.file.endsWith(`/${e.file}`));
    if (!doc) return;
    let current = { d, h: '概述', a: '', x: [] as string[] };
    const flush = () => {
      const x = current.x.join(' ').replace(/\s+/g, ' ').trim();
      if (x || current.a) index.sections.push({ d: current.d, h: current.h, a: current.a, x });
    };
    const tokens = doc.tokens;
    for (let i = 0; i < tokens.length; i++) {
      const t = tokens[i];
      if (t.type === 'heading_open' && (t.tag === 'h2' || t.tag === 'h3')) {
        flush();
        current = { d, h: inlineText(tokens[i + 1].children).trim(), a: t.attrGet('id') ?? '', x: [] };
        i += 2;
        continue;
      }
      const open = /^container_(.+)_open$/.exec(t.type);
      if (open) {
        const title = containerTitle(t.info, open[1]);
        if (title) current.x.push(title);
      } else if (t.type === 'inline') current.x.push(inlineText(t.children));
      else if (t.type === 'fence' || t.type === 'zt_filetree') current.x.push(t.content);
    }
    flush();
  });
  return index;
}

const VIRTUAL = {
  routes: 'virtual:docs-routes',
  manifest: 'virtual:docs-manifest',
  searchIndex: 'virtual:docs-search-index',
} as const;

const components = ['Callout', 'Steps', 'FileTree', 'ExampleUtterances', 'ExampleUtterance', 'Kbd', 'CodeBlock', 'HeadingAnchor', 'DocCards', 'ReleaseCurrent'];

/**
 * 文档插件组。
 * @returns Vite 插件数组：Markdown 编译与文档清单/检查/索引。
 */
export function docsPlugin(): Plugin[] {
  let config: ResolvedConfig | undefined;
  let state: ReturnType<typeof analyzeDocs> | undefined;
  let indexRef: string | undefined;
  let indexSource = '';

  const analyze = () => {
    state ??= analyzeDocs();
    if (state.problems.length) throw new DocsCheckError(state.problems);
    return state;
  };

  const markdown = Markdown({
    include: [/src[\\/]docs[\\/]content[\\/][^\\/]+\.md$/],
    wrapperClasses: 'doc-body',
    headEnabled: false,
    frontmatter: true,
    exposeFrontmatter: false,
    exportFrontmatter: false,
    // frontmatter 不进客户端代码（sources 等只供维护与构建期检查）。
    frontmatterPreprocess: () => ({ head: {}, frontmatter: {} }),
    markdownItOptions: { html: false, linkify: false, typographer: false },
    async markdownItSetup(md) {
      setupDocsMarkdown(md, await getHighlighter());
    },
    transforms: {
      extraScripts: () => [
        ...components.map((c) => `import ${c} from ${JSON.stringify(resolve(SITE_ROOT, `src/components/docs/${c}.vue`))};`),
        `import ZtStatus from ${JSON.stringify(resolve(SITE_ROOT, 'src/components/ui/ZtStatus.vue'))};`,
        `import AppIcon from ${JSON.stringify(resolve(SITE_ROOT, 'src/components/AppIcon.vue'))};`,
      ],
      after(html, id) {
        // 代码块外（v-pre 之外）不得出现未转义的 {{（§3.3）。
        const outside = html.replace(/<div class="code-scroll" v-pre>[\s\S]*?<\/CodeBlock>/g, '');
        if (outside.includes('{{')) throw new Error(`${relative(SITE_ROOT, id)}：生成的模板含未转义的 {{`);
        return html;
      },
    },
  });

  const core: Plugin = {
    name: 'zt-docs',
    configResolved(c) {
      config = c;
    },
    buildStart() {
      state = undefined;
      try {
        const { entries, parsed } = analyze();
        const index = buildSearchIndex(entries, parsed);
        indexSource = JSON.stringify(index);
        if (config?.command === 'build')
          indexRef = this.emitFile({ type: 'asset', name: 'search-index.json', source: indexSource });
        for (const f of parsed) this.addWatchFile(f.file);
      } catch (e) {
        if (e instanceof DocsCheckError) for (const p of e.problems) console.error(`文档检查失败：${p}`);
        this.error(e instanceof Error ? e.message : String(e));
      }
    },
    resolveId(id) {
      if ((Object.values(VIRTUAL) as string[]).includes(id)) return `\0${id}`;
      return null;
    },
    load(id) {
      if (!id.startsWith('\0virtual:docs-')) return null;
      const { entries } = analyze();
      const name = id.slice(1);
      if (name === VIRTUAL.routes) {
        const docs = entries.map(({ headings: _h, ...rest }) => rest);
        return `export const docs = ${JSON.stringify(docs)};`;
      }
      if (name === VIRTUAL.manifest) {
        // 体积：条目字段复用 virtual:docs-routes（已在主包）；标题写成 [级别, 文字]，id 与 docs-slug 结果不同时才写第三项。
        const compactHeadings = entries.map((e) => {
          const slugger = createSlugger();
          return e.headings.map((h) => (slugger(h.text) === h.id ? [h.level, h.text] : [h.level, h.text, h.id]));
        });
        const groups = DOC_GROUPS.map((g) => ({
          name: g.name,
          description: g.description,
          items: entries.filter((d) => d.group === g.name).map((d) => d.slug),
        }));
        return [
          `import { docs as base } from ${JSON.stringify(VIRTUAL.routes)};`,
          `import { createSlugger } from ${JSON.stringify(resolve(SITE_ROOT, 'build/docs-slug.ts'))};`,
          `const H = ${JSON.stringify(compactHeadings)};`,
          'export const docs = base.map(({ file, ...d }, i) => {',
          '  const slug = createSlugger();',
          '  return { ...d, headings: H[i].map(([level, text, id]) => { const auto = slug(text); return { level, text, id: id ?? auto }; }) };',
          '});',
          'const bySlug = new Map(docs.map((d) => [d.slug, d]));',
          `export const groups = ${JSON.stringify(groups)}.map((g) => ({ ...g, items: g.items.map((s) => bySlug.get(s)) }));`,
        ].join('\n');
      }
      if (name === VIRTUAL.searchIndex) {
        if (config?.command === 'build' && indexRef) return `export default import.meta.ROLLUP_FILE_URL_${indexRef};`;
        return `export default '/@docs/search-index.json';`;
      }
      return null;
    },
    configureServer(server) {
      server.middlewares.use('/@docs/search-index.json', (_req, res) => {
        const { entries, parsed } = analyze();
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify(buildSearchIndex(entries, parsed)));
      });
      server.watcher.on('change', (file) => {
        if (!file.startsWith(CONTENT_DIR)) return;
        state = undefined;
        for (const v of Object.values(VIRTUAL)) {
          const mod = server.moduleGraph.getModuleById(`\0${v}`);
          if (mod) server.moduleGraph.invalidateModule(mod);
        }
      });
    },
    generateBundle(_options, bundle) {
      if (config?.build.ssr) return;
      const problems: string[] = [];
      const raw = Buffer.byteLength(indexSource);
      const gz = gzipSync(indexSource).length;
      if (raw > BUDGET.indexRaw) problems.push(`搜索索引未压缩 ${raw} 字节，超过预算 ${BUDGET.indexRaw}`);
      if (gz > BUDGET.indexGzip) problems.push(`搜索索引 gzip ${gz} 字节，超过预算 ${BUDGET.indexGzip}`);
      const searchChunk = Object.values(bundle).find(
        (c) => c.type === 'chunk' && Object.keys(c.modules).some((m) => /src[\\/]docs[\\/]search\.ts$/.test(m)),
      );
      if (!searchChunk || searchChunk.type !== 'chunk') problems.push('找不到搜索逻辑块（src/docs/search.ts 应为独立懒加载块）');
      else {
        const size = gzipSync(searchChunk.code).length;
        if (size > BUDGET.searchChunkGzip) problems.push(`搜索逻辑块 gzip ${size} 字节，超过预算 ${BUDGET.searchChunkGzip}`);
        this.info(`搜索逻辑块 ${searchChunk.fileName} gzip ${size} 字节；索引 ${raw} 字节（gzip ${gz}）`);
      }
      if (problems.length) {
        for (const p of problems) console.error(`文档体积检查失败：${p}`);
        this.error(problems.join('；'));
      }
    },
  };

  return [...[markdown].flat(), core];
}
