/**
 * 文档正文的 markdown-it 配置（06 章 §3.3、§5）：容器、锚点、代码高亮、行内徽标与按键、站内/外部链接、表格、FileTree。
 *
 * 同一个 `setupDocsMarkdown` 同时用于：
 * - unplugin-vue-markdown 把 `.md` 编译成 SFC（输出组件标签：Callout、Steps、FileTree、ExampleUtterances、CodeBlock…）；
 * - docs-plugin 的构建期检查、清单与搜索索引（解析 token，不渲染）。
 * 两边共用一套解析规则与锚点函数，清单里的标题 id 与正文渲染一致。
 *
 * 插值转义：正文与行内代码的 `{` `}` 输出为 `&#123;` `&#125;`，代码块外包 `v-pre`，正文里的 `{{字段}}` 原样显示。
 */
import type MarkdownIt from 'markdown-it';
import type { MarkdownItAsync } from 'markdown-it-async';
import type Token from 'markdown-it/lib/token.mjs';
import container from 'markdown-it-container';
import anchor from 'markdown-it-anchor';
import { fromHighlighter } from '@shikijs/markdown-it/core';
import { createHighlighter, type HighlighterGeneric } from 'shiki';
import { slugify } from './docs-slug';

/** §5 允许的容器。 */
export const CONTAINERS = [
  'note',
  'tip',
  'confirm',
  'steps',
  'filetree',
  'utterances',
  'doc-cards',
  'release-current',
] as const;
export type ContainerName = (typeof CONTAINERS)[number];

/** §5 行内徽标的取值。 */
export const STATUS_VALUES = ['ok', 'partial', 'empty', 'insufficient', 'manual'] as const;
export const LEVEL_VALUES = ['error', 'warn', 'info'] as const;
/** 读屏与搜索用的中文名（与 components/ui/types.ts 的 STATUS_LABEL 一致）。 */
export const BADGE_LABEL: Record<string, string> = {
  ok: '完成',
  partial: '部分完成',
  empty: '无结果',
  insufficient: '资料不足',
  manual: '需人工确认',
  error: '错误',
  warn: '警告',
  info: '提示',
};

/** 构建期高亮加载的五种语言（§3.3）；其它语言（如 markdown）按 text 输出。 */
export const CODE_LANGS = ['bash', 'powershell', 'json', 'yaml', 'text'] as const;
/** 深色主题；前景色由样式表覆盖为 `--canvas`，底色为 `--code-bg`。各语法色在 #0f1e33 上对比度 ≥ 4.5:1。 */
export const CODE_THEME = 'github-dark-default';

const CALLOUT_LABEL: Record<string, string> = { note: '注意', tip: '提示', confirm: '需人工确认' };

let highlighterPromise: Promise<HighlighterGeneric<any, any>> | undefined;
/** 只创建一次 shiki 高亮器（构建期）。 */
export function getHighlighter() {
  highlighterPromise ??= createHighlighter({ themes: [CODE_THEME], langs: ['bash', 'powershell', 'json', 'yaml'] });
  return highlighterPromise;
}

const escapeHtml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
/** 模板文本：HTML 转义 + 花括号转义（避免被 Vue 当作插值）。 */
export const vueText = (s: string) => escapeHtml(s).replace(/\{/g, '&#123;').replace(/\}/g, '&#125;');
const attr = (s: string) => vueText(s);

/**
 * 行内 token 的纯文本（标题文字、链接文字、搜索索引共用）。徽标取中文名，按键取原文。
 * @param children - inline token 的 children。
 * @returns 纯文本。
 */
export function inlineText(children: readonly Token[] | null | undefined): string {
  let out = '';
  for (const t of children ?? []) {
    if (t.type === 'text') out += t.content;
    else if (t.type === 'code_inline') {
      const badge = /^(status|level):(.+)$/.exec(t.content);
      const kbd = /^kbd:(.+)$/.exec(t.content);
      out += badge ? (BADGE_LABEL[badge[2]] ?? badge[2]) : kbd ? kbd[1] : t.content;
    } else if (t.type === 'softbreak' || t.type === 'hardbreak') out += ' ';
    else if (t.type === 'image') out += t.content;
  }
  return out;
}

/** 容器的标题参数（`::: note 标题` → `标题`）。 */
export function containerTitle(info: string, name: string): string {
  return info.trim().slice(name.length).trim();
}

/** FileTree 的一行。 */
export interface TreeNode {
  name: string;
  note: string;
  dir: boolean;
  children: TreeNode[];
}

/**
 * 解析 filetree 代码块：两个空格一级；行尾为 `/` 的是目录；空白后的 `#` 之后是注释。
 * @param text - 代码块内容。
 * @returns 顶层节点。
 */
export function parseFileTree(text: string): TreeNode[] {
  const roots: TreeNode[] = [];
  const stack: { depth: number; node: TreeNode }[] = [];
  for (const raw of text.split('\n')) {
    if (!raw.trim()) continue;
    const depth = Math.floor((raw.length - raw.trimStart().length) / 2);
    let body = raw.trim();
    let note = '';
    const m = /\s+#\s*(.*)$/.exec(body);
    if (m) {
      note = m[1].trim();
      body = body.slice(0, m.index).trim();
    }
    const node: TreeNode = { name: body, note, dir: body.endsWith('/'), children: [] };
    while (stack.length && stack[stack.length - 1].depth >= depth) stack.pop();
    if (stack.length) stack[stack.length - 1].node.children.push(node);
    else roots.push(node);
    stack.push({ depth, node });
  }
  return roots;
}

function renderTree(nodes: TreeNode[]): string {
  const items = nodes
    .map((n) => {
      const icon = `<AppIcon name="${n.dir ? 'folder' : 'file'}" class="ft-icon" />`;
      const kind = n.dir ? '<span class="sr-only">，文件夹</span>' : '';
      const note = n.note ? `<span class="ft-note">${vueText(n.note)}</span>` : '';
      const sub = n.children.length ? renderTree(n.children) : '';
      return `<li class="${n.dir ? 'ft-dir' : 'ft-file'}"><span class="ft-row">${icon}<span class="ft-name">${vueText(n.name)}</span>${kind}${note}</span>${sub}</li>`;
    })
    .join('');
  return `<ul>${items}</ul>`;
}

/** 数字列判定：金额、面积、百分比、计数等。 */
const NUM_CELL =
  /^[−\-+≈~]?¥?\d[\d,]*(\.\d+)?\s*(%|元|万元|m²|㎡|行|条|份|张|个|项|章|页|次|天|秒|MB|KB|GB|ms)?$/;

interface DocsEnv {
  lastHeading?: string;
  linkStack?: ('router' | 'external' | 'plain')[];
  tableCount?: Record<string, number>;
  [k: string]: unknown;
}

/** core 规则：FileTree、说法列表、表格数字列。 */
function transformTokens(tokens: Token[]) {
  const containerStack: string[] = [];
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    const open = /^container_(.+)_open$/.exec(t.type);
    const close = /^container_(.+)_close$/.exec(t.type);
    if (open) containerStack.push(open[1]);
    else if (close) containerStack.pop();
    const inside = containerStack.at(-1);

    if (inside === 'filetree' && t.type === 'fence') t.type = 'zt_filetree';
    if (inside === 'utterances') {
      if (t.type === 'bullet_list_open' || t.type === 'bullet_list_close') t.type = 'zt_skip';
      else if (t.type === 'list_item_open') {
        t.type = 'zt_utter_open';
        // list_item_open → paragraph_open → inline
        const inline = tokens.slice(i, i + 4).find((x) => x.type === 'inline');
        t.meta = { text: inlineText(inline?.children).trim() };
      } else if (t.type === 'list_item_close') t.type = 'zt_utter_close';
    }
    if (t.type === 'table_open') markNumericColumns(tokens, i);
  }
}

function markNumericColumns(tokens: Token[], start: number) {
  const columns: { cells: Token[]; values: string[] }[] = [];
  let col = 0;
  let inBody = false;
  for (let j = start; j < tokens.length && tokens[j].type !== 'table_close'; j++) {
    const t = tokens[j];
    if (t.type === 'tbody_open') inBody = true;
    if (t.type === 'tr_open') col = 0;
    if (t.type === 'th_open' || t.type === 'td_open') {
      columns[col] ??= { cells: [], values: [] };
      columns[col].cells.push(t);
      if (inBody) columns[col].values.push(inlineText(tokens[j + 1]?.children).trim());
      col++;
    }
  }
  for (const c of columns) {
    const filled = c.values.filter((v) => v && v !== '—' && v !== '-');
    if (filled.length && filled.every((v) => NUM_CELL.test(v))) for (const cell of c.cells) cell.attrJoin('class', 'num');
  }
}

/**
 * 给 markdown-it 实例装上文档扩展。
 * @param target - markdown-it（或 unplugin-vue-markdown 的 markdown-it-async）实例。
 * @param highlighter - shiki 高亮器；省略时代码块不高亮（只供构建期检查使用）。
 */
export function setupDocsMarkdown(target: MarkdownIt | MarkdownItAsync, highlighter?: HighlighterGeneric<any, any>) {
  // markdown-it-async 是 markdown-it 的子类，只是 highlight 可返回 Promise；这里只注册同步规则。
  const md = target as MarkdownIt;
  md.set({ html: false, linkify: false, typographer: false });

  md.use(anchor, {
    level: [2, 3],
    slugify,
    uniqueSlugStartIndex: 2,
    tabIndex: -1,
    getTokensText: (tokens: Token[]) => inlineText(tokens),
  });

  for (const name of CONTAINERS) {
    md.use(container, name, {
      validate: (params: string) => params.trim() === name || params.trim().startsWith(`${name} `),
      render: (tokens: Token[], idx: number) => {
        const t = tokens[idx];
        if (t.nesting === -1) {
          return (
            {
              note: '</Callout>\n',
              tip: '</Callout>\n',
              confirm: '</Callout>\n',
              steps: '</Steps>\n',
              filetree: '</FileTree>\n',
              utterances: '</ExampleUtterances>\n',
              'doc-cards': '</DocCards>\n',
              'release-current': '</ReleaseCurrent>\n',
            } as Record<string, string>
          )[name];
        }
        const title = containerTitle(t.info, name);
        if (name in CALLOUT_LABEL) return `<Callout type="${name}"${title ? ` title="${attr(title)}"` : ''}>\n`;
        if (name === 'steps') return '<Steps>\n';
        if (name === 'filetree') return `<FileTree${title ? ` title="${attr(title)}"` : ''}>\n`;
        if (name === 'utterances') return '<ExampleUtterances>\n';
        if (name === 'doc-cards') return '<DocCards>\n';
        return '<ReleaseCurrent>\n';
      },
    });
  }

  md.core.ruler.push('zt_docs', (state) => {
    transformTokens(state.tokens);
  });

  if (highlighter) {
    md.use(
      fromHighlighter(highlighter, {
        theme: CODE_THEME,
        transformers: [
          {
            name: 'zt:pre-style',
            pre(node) {
              // 底色与前景色由样式表决定（--code-bg / --canvas），去掉主题的内联底色。
              delete node.properties.style;
              node.properties.tabindex = '0';
            },
          },
        ],
      }),
    );
  }

  const rules = md.renderer.rules;
  const defaultFence = rules.fence!.bind(rules);

  rules.text = (tokens, idx) => vueText(tokens[idx].content);

  rules.code_inline = (tokens, idx) => {
    const content = tokens[idx].content;
    const badge = /^(status|level):(.*)$/.exec(content);
    if (badge) {
      const allowed: readonly string[] = badge[1] === 'status' ? STATUS_VALUES : LEVEL_VALUES;
      if (!allowed.includes(badge[2])) throw new Error(`行内徽标 \`${content}\` 的取值不在 06 章 §5 列表内`);
      return `<ZtStatus value="${badge[2]}" size="sm" />`;
    }
    const kbd = /^kbd:(.+)$/.exec(content);
    if (kbd) return `<Kbd keys="${attr(kbd[1])}" />`;
    return `<code>${vueText(content)}</code>`;
  };

  rules.fence = (tokens, idx, options, env, self) => {
    const token = tokens[idx];
    const lang = token.info.trim().split(/\s+/)[0] || 'text';
    // 非五种语言之一时按 text 高亮（不显示语言名）。
    if (!(CODE_LANGS as readonly string[]).includes(lang)) token.info = 'text';
    const html = defaultFence(tokens, idx, options, env, self);
    const shown = (CODE_LANGS as readonly string[]).includes(lang) ? lang : 'text';
    return `<CodeBlock lang="${shown}"><div class="code-scroll" v-pre>${html}</div></CodeBlock>\n`;
  };

  rules.zt_filetree = (tokens, idx) => renderTree(parseFileTree(tokens[idx].content)) + '\n';
  rules.zt_skip = () => '';
  rules.zt_utter_open = (tokens, idx) => `<ExampleUtterance text="${attr(String(tokens[idx].meta?.text ?? ''))}">`;
  rules.zt_utter_close = () => '</ExampleUtterance>\n';

  rules.heading_open = (tokens, idx, options, env: DocsEnv, self) => {
    const t = tokens[idx];
    env.lastHeading = inlineText(tokens[idx + 1]?.children).trim();
    if (t.tag !== 'h2' && t.tag !== 'h3') return self.renderToken(tokens, idx, options);
    return `<div class="doc-h doc-${t.tag}">${self.renderToken(tokens, idx, options)}`;
  };
  rules.heading_close = (tokens, idx, options, _env, self) => {
    const t = tokens[idx];
    if (t.tag !== 'h2' && t.tag !== 'h3') return self.renderToken(tokens, idx, options);
    const open = tokens[idx - 2];
    const id = open.attrGet('id') ?? '';
    const text = inlineText(tokens[idx - 1].children).trim();
    return `${self.renderToken(tokens, idx, options)}<HeadingAnchor id="${attr(id)}" text="${attr(text)}" /></div>\n`;
  };

  rules.table_open = (tokens, idx, options, env: DocsEnv, self) => {
    // 同一标题下有多张表时加序号，区域名称不重复。
    const base = env.lastHeading || '正文';
    env.tableCount ??= {};
    const n = (env.tableCount[base] = (env.tableCount[base] ?? 0) + 1);
    const label = `表格：${base}${n > 1 ? `（${n}）` : ''}，可横向滚动`;
    return `<div class="table-wrap" role="region" tabindex="0" aria-label="${attr(label)}">${self.renderToken(tokens, idx, options)}`;
  };
  rules.table_close = (tokens, idx, options, _env, self) => `${self.renderToken(tokens, idx, options)}</div>\n`;

  rules.link_open = (tokens, idx, options, env: DocsEnv, self) => {
    const t = tokens[idx];
    const href = t.attrGet('href') ?? '';
    env.linkStack ??= [];
    if (href.startsWith('/')) {
      env.linkStack.push('router');
      return `<RouterLink to="${attr(href)}">`;
    }
    if (/^https?:\/\//.test(href)) {
      env.linkStack.push('external');
      // 链接文字：link_open 与 link_close 之间的 token。
      const rest = tokens.slice(idx + 1);
      const end = rest.findIndex((x) => x.type === 'link_close');
      const text = inlineText(rest.slice(0, end < 0 ? undefined : end)).trim();
      return `<a href="${attr(href)}" target="_blank" rel="noopener noreferrer" aria-label="${attr(`${text}（在新标签页打开）`)}">`;
    }
    env.linkStack.push('plain');
    return self.renderToken(tokens, idx, options);
  };
  rules.link_close = (_tokens, _idx, _options, env: DocsEnv) => {
    const kind = env.linkStack?.pop() ?? 'plain';
    if (kind === 'router') return '</RouterLink>';
    if (kind === 'external') return '<AppIcon name="external" class="ext-icon" /></a>';
    return '</a>';
  };

  rules.image = (tokens, idx) => {
    const t = tokens[idx];
    const src = t.attrGet('src') ?? '';
    return `<img src="${attr(src)}" alt="${attr(t.content)}" loading="lazy" decoding="async" />`;
  };

}
