/** 06 章站内搜索（§8.3–§8.6，AC-06-12、AC-06-14 的索引预算部分）。 */
import { gzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { analyzeDocs, buildSearchIndex, BUDGET } from '../build/docs-plugin';
import { compact, createSearcher, tokenize } from '../src/docs/search';

const { entries, parsed } = analyzeDocs();
const index = buildSearchIndex(entries, parsed);
const searcher = createSearcher(index);
const titles = (q: string) => searcher.search(q).map((r) => `${r.pageTitle} › ${r.heading}`);

describe('06 §8.3 索引', () => {
  it('每页按 H2/H3 切小节，H2 之前归入「概述」；保留代码块与说法', () => {
    expect(index.pages).toHaveLength(23);
    const install = index.pages.findIndex((p) => p.p === '/docs/install/');
    const sections = index.sections.filter((s) => s.d === install);
    expect(sections[0]).toMatchObject({ h: '概述', a: '' });
    expect(sections.find((s) => s.a === '校验安装包')!.x).toContain('shasum -a 256');
    expect(index.sections.some((s) => s.x.includes('zt_not_importable'))).toBe(true);
  });
  it('AC-06-14：索引 gzip ≤ 120 KB、未压缩 ≤ 480 KB', () => {
    const raw = JSON.stringify(index);
    expect(Buffer.byteLength(raw)).toBeLessThanOrEqual(BUDGET.indexRaw);
    expect(gzipSync(raw).length).toBeLessThanOrEqual(BUDGET.indexGzip);
  });
});

describe('06 §8.4 分词', () => {
  it('汉字二字组、字母数字词、单字查询', () => {
    expect(tokenize('校验安装包')).toEqual(['h:校验', 'h:验安', 'h:安装', 'h:装包']);
    expect(tokenize('跑 zt_not 吧')).toEqual(['w:zt_not']);
    expect(tokenize('桶', true)).toEqual(['u:桶']);
    expect(tokenize('ＡＢＣ')).toEqual(['w:abc']);
    expect(compact('需人工 确认！')).toBe('需人工确认');
  });
});

describe('06 AC-06-12 检索', () => {
  it('「校验安装包」第一条为「安装 › 校验安装包」', () => {
    expect(titles('校验安装包')[0]).toBe('安装 › 校验安装包');
  });
  it('「审减」经同义词命中含「核减」的小节', () => {
    const res = searcher.search('审减');
    expect(res.length).toBeGreaterThan(0);
    expect(res.some((r) => r.excerpt.some((p) => p.mark && p.text.includes('核减')))).toBe(true);
  });
  it('「zt_not」前缀命中 zt_not_importable', () => {
    const res = searcher.search('zt_not');
    expect(res.length).toBeGreaterThan(0);
    expect(res[0].excerpt.filter((p) => p.mark).map((p) => p.text)).toContain('zt_not_importable');
  });
  it('「xyzxyz」无结果', () => {
    expect(searcher.search('xyzxyz')).toEqual([]);
  });
  it('每页最多 3 个小节，总数最多 20 条；摘录首尾加省略号', () => {
    const res = searcher.search('确认');
    expect(res.length).toBeLessThanOrEqual(20);
    const perPage = new Map<string, number>();
    for (const r of res) perPage.set(r.path, (perPage.get(r.path) ?? 0) + 1);
    expect(Math.max(...perPage.values())).toBeLessThanOrEqual(3);
    const long = res.find((r) => r.excerpt[0].text === '…');
    expect(long).toBeTruthy();
  });
  it('「配置包」与 zhitong.config.json 互为同义词；英文同义词按整词匹配', () => {
    expect(searcher.search('zhitong.config.json').length).toBeGreaterThan(0);
    expect(titles('配置包')[0]).toContain('配置包');
  });
});
