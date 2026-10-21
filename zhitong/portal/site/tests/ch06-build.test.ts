/** 06 章构建期：清单、frontmatter 与链接检查、能力页模板、插值转义、FileTree（§3.2–§3.8、§5、§7.11）。 */
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import MarkdownIt from 'markdown-it';
import { compileTemplate } from '@vue/compiler-sfc';
import { afterEach, describe, expect, it } from 'vitest';
import { analyzeDocs, parseFrontmatter } from '../build/docs-plugin';
import { parseFileTree, setupDocsMarkdown } from '../build/docs-markdown';
import { createSlugger, slugify } from '../build/docs-slug';
import { DOC_TABLE, FEATURE_H2 } from '../src/docs/groups';

const CONTENT = resolve(__dirname, '../src/docs/content');
const temps: string[] = [];
afterEach(() => temps.splice(0).forEach((d) => rmSync(d, { recursive: true, force: true })));

/** 复制正文到临时目录并改一个文件。 */
function mutate(file: string, edit: (text: string) => string) {
  const dir = mkdtempSync(join(tmpdir(), 'zt-docs-'));
  temps.push(dir);
  cpSync(CONTENT, dir, { recursive: true });
  const p = join(dir, file);
  writeFileSync(p, edit(readFileSync(p, 'utf8')));
  return analyzeDocs(dir).problems;
}

describe('06 §2.4 锚点 id', () => {
  it('按规则生成，同页重名加 -2、-3', () => {
    expect(slugify('校验安装包')).toBe('校验安装包');
    expect(slugify('Windows：SmartScreen 拦截')).toBe('windowssmartscreen-拦截');
    const s = createSlugger();
    expect([s('常见问题'), s('常见问题'), s('常见问题')]).toEqual(['常见问题', '常见问题-2', '常见问题-3']);
  });
});

describe('06 §3.4 清单 / §3.8 检查（真实正文）', () => {
  it('23 页全部通过检查，顺序 = 路由表顺序', () => {
    const { entries, problems } = analyzeDocs();
    expect(problems).toEqual([]);
    expect(entries.map((e) => e.slug)).toEqual(DOC_TABLE.map((r) => r.slug));
    expect(entries[0].path).toBe('/docs/');
    expect(entries.find((e) => e.slug === 'install')!.headings.map((h) => h.id)).toContain('校验安装包');
  });
  it('12 个能力页的 H2 恰为 §6.2', () => {
    const { entries } = analyzeDocs();
    const features = entries.filter((e) => e.slug.startsWith('features/'));
    expect(features).toHaveLength(12);
    for (const f of features) expect(f.headings.filter((h) => h.level === 2).map((h) => h.text)).toEqual([...FEATURE_H2]);
  });
  it('frontmatter 解析：固定字段与 sources 列表', () => {
    const { fm, bodyLine } = parseFrontmatter(readFileSync(join(CONTENT, 'install.md'), 'utf8'));
    expect(fm).toMatchObject({ title: '安装', slug: 'install', group: '开始使用', order: '2', updated: '2026-10-20' });
    expect(Array.isArray(fm!.sources)).toBe(true);
    expect(bodyLine).toBeGreaterThan(9);
  });
});

describe('06 AC-06-04 frontmatter 不合规时失败并指出文件', () => {
  it('缺字段', () => {
    const p = mutate('install.md', (t) => t.replace(/^summary: .*\n/m, ''));
    expect(p.some((x) => x.includes('install.md') && x.includes('缺少字段 summary'))).toBe(true);
  });
  it('多字段', () => {
    const p = mutate('install.md', (t) => t.replace('updated:', 'author: x\nupdated:'));
    expect(p.some((x) => /install\.md:\d+ frontmatter 多余字段 author/.test(x))).toBe(true);
  });
  it('与路由表不一致', () => {
    const p = mutate('install.md', (t) => t.replace('title: 安装', 'title: 安装说明'));
    expect(p.some((x) => x.includes('install.md:2') && x.includes('与路由表「安装」不一致'))).toBe(true);
  });
  it('sources 路径不存在', () => {
    const p = mutate('install.md', (t) => t.replace('sources:\n', 'sources:\n  - zhitong/不存在.md\n'));
    expect(p.some((x) => x.includes('install.md') && x.includes('sources 路径不存在：zhitong/不存在.md'))).toBe(true);
  });
  it('summary 超过 60 字', () => {
    const p = mutate('install.md', (t) => t.replace(/^summary: .*$/m, `summary: ${'字'.repeat(61)}`));
    expect(p.some((x) => x.includes('summary 超过 60 字'))).toBe(true);
  });
});

describe('06 AC-06-05 站内链接与锚点', () => {
  it('不存在的页面：报文件与行号', () => {
    const p = mutate('install.md', (t) => `${t}\n见[这里](/docs/nope/)。\n`);
    // 原文以换行结尾：split 的最后一项为空串，追加的空行之后一行即新内容所在行。
    const lines = readFileSync(join(CONTENT, 'install.md'), 'utf8').split('\n').length;
    expect(p).toHaveLength(1);
    expect(p[0]).toMatch(new RegExp(`install\\.md:${lines + 1} 链接指向不存在的页面：/docs/nope/$`));
  });
  it('不存在的锚点', () => {
    const p = mutate('install.md', (t) => `${t}\n见[这里](/docs/install/#没有这一节)。\n`);
    expect(p.some((x) => /install\.md:\d+ 链接指向不存在的锚点：\/docs\/install\/#没有这一节/.test(x))).toBe(true);
  });
});

describe('06 AC-06-06 能力页 H2 与 §6.2 不一致时失败', () => {
  it('缺一节、顺序错', () => {
    expect(mutate('features-check.md', (t) => t.replace('## 适用场景', '## 适用范围')).some((x) => x.includes('能力页的 H2 与 06 章 §6.2 不一致'))).toBe(true);
  });
  it('H4 与正文 H1', () => {
    const p = mutate('features-check.md', (t) => `${t}\n#### 小标题\n\n# 大标题\n`);
    expect(p.some((x) => x.includes('不能写 H4'))).toBe(true);
    expect(p.some((x) => x.includes('正文不能有 H1'))).toBe(true);
  });
});

describe('06 §3.8 第 6、7 条：容器与原始 HTML', () => {
  it('未知容器、嵌套、doc-cards 用在别处、原始 HTML', () => {
    const p = mutate('basics.md', (t) => `${t}\n::: warning\n内容\n:::\n\n::: doc-cards\n:::\n\n这是 <span>原始</span> HTML。\n`);
    expect(p.some((x) => x.includes('未知或写错的容器「::: warning」'))).toBe(true);
    expect(p.some((x) => x.includes('::: doc-cards 只能用于 index.md'))).toBe(true);
    expect(p.some((x) => x.includes('正文不能写原始 HTML'))).toBe(true);
  });
});

function render(src: string) {
  const md = new MarkdownIt();
  setupDocsMarkdown(md);
  return md.render(src, {});
}

describe('06 §5 渲染', () => {
  it('AC-06-07：{{字段}} 原样显示，模板编译无错误', () => {
    const html = render('项目说明模板里写 {{项目名称}}，行内 `{{字段}}`。\n');
    expect(html).not.toContain('{{');
    const { errors, code } = compileTemplate({ source: html, filename: 'x.vue', id: 'x' });
    expect(errors).toEqual([]);
    expect(code).toContain('{{项目名称}}');
    expect(code).toContain('{{字段}}');
  });
  it('容器、徽标、按键、链接、表格', () => {
    const html = render(
      [
        '## 小节',
        '',
        '::: note 不要这样做',
        '内容 `status:partial` 与 `level:warn`，按 `kbd:Ctrl+K`。',
        ':::',
        '',
        '见[安装](/docs/install/#校验安装包)，外链 [官网](https://example.com/)。',
        '',
        '| 项 | 金额 |',
        '|---|---|',
        '| 核减额 | 906,692.96 |',
        '',
      ].join('\n'),
    );
    expect(html).toMatch(/<div class="doc-h doc-h2"><h2 id="小节" tabindex="-1">小节<\/h2>\s*<HeadingAnchor id="小节" text="小节" \/><\/div>/);
    expect(html).toContain('<Callout type="note" title="不要这样做">');
    expect(html).toContain('<ZtStatus value="partial" size="sm" />');
    expect(html).toContain('<ZtStatus value="warn" size="sm" />');
    expect(html).toContain('<Kbd keys="Ctrl+K" />');
    expect(html).toMatch(/<RouterLink to="\/docs\/install\/#%E6%A0%A1[^"]*">安装<\/RouterLink>/);
    expect(html).toContain('target="_blank" rel="noopener noreferrer" aria-label="官网（在新标签页打开）"');
    expect(html).toContain('role="region" tabindex="0" aria-label="表格：小节，可横向滚动"');
    expect(html).toMatch(/<td class="num">906,692\.96<\/td>/);
  });
  it('徽标取值不在 §5 列表内时报错', () => {
    expect(() => render('`status:done`')).toThrow(/不在 06 章 §5 列表内/);
  });
  it('utterances 每条一个 ExampleUtterance', () => {
    const html = render('::: utterances\n- 核对一下送审和审定计价表。\n- 把 2026-007 比一下。\n:::\n');
    expect(html).toContain('<ExampleUtterances>');
    expect(html).toContain('<ExampleUtterance text="核对一下送审和审定计价表。">核对一下送审和审定计价表。</ExampleUtterance>');
    expect(html).not.toContain('<ul>');
  });
  it('FileTree：两空格一级、/ 结尾为目录、# 后为注释、· 同行', () => {
    const tree = parseFileTree('项目/\n  工作/\n    result.json        # 脚本完整结果\n  资料/a.xlsx · b.xlsx\n');
    expect(tree).toEqual([
      {
        name: '项目/',
        note: '',
        dir: true,
        children: [
          { name: '工作/', note: '', dir: true, children: [{ name: 'result.json', note: '脚本完整结果', dir: false, children: [] }] },
          { name: '资料/a.xlsx · b.xlsx', note: '', dir: false, children: [] },
        ],
      },
    ]);
    const html = render('::: filetree 示例\n```text\n项目/\n  a.md  # 说明\n```\n:::\n');
    expect(html).toContain('<FileTree title="示例">');
    expect(html).toContain('<span class="sr-only">，文件夹</span>');
    expect(html).toContain('<span class="ft-note">说明</span>');
  });
});
