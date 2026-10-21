/** 05 章 §4 常见问题：八问数据、筛选、默认展开、深链、复制链接、页内查找同步、降级。 */
import { flushPromises } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render } from '../src/entry-server';
import { FAQ_GROUPS, FAQS } from '../src/data/faq';
import { DOC_ROUTES } from '../src/docs/routes';
import { toastState } from '../src/composables/useToast';
import FaqSection from '../src/components/FaqSection.vue';
import { mountAt } from './helpers';

afterEach(() => {
  history.replaceState(null, '', '/');
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
});

const mountFaq = async () => (await mountAt('/', FaqSection)).wrapper;
const openIds = (w: Awaited<ReturnType<typeof mountFaq>>) =>
  w
    .findAll('details.faq-item')
    .filter((d) => (d.element as HTMLDetailsElement).open)
    .map((d) => d.attributes('id'));
const visibleIds = (w: Awaited<ReturnType<typeof mountFaq>>) =>
  w
    .findAll('details.faq-item')
    .filter((d) => d.attributes('hidden') === undefined)
    .map((d) => d.attributes('id'));

describe('05 §4 常见问题', () => {
  it('AC-05-59：8 问的 id、主题、问、答、相关文档与 §4.2 一致（快照）', () => {
    expect(FAQS.map((f) => [f.id, f.group, f.question, f.doc?.href ?? null])).toEqual([
      ['calc', 'result', '它会替我算造价吗？', '/docs/security/'],
      ['use-directly', 'result', 'AI 给出的结果能直接用吗？', '/docs/results/'],
      ['data-location', 'data', '我们的资料会放到哪里？', '/docs/security/'],
      ['concurrent', 'collab', '几个人同时用同一个项目会冲突吗？', '/docs/projects/'],
      ['scans-drawings', 'data', '扫描件和图纸能看吗？', '/docs/features/cad/'],
      ['vector-index', 'install', '需要建知识库的向量索引吗？', '/docs/features/qa/'],
      ['migrate', 'install', '原来的资料怎么搬进来？', null],
      ['other-documents', 'collab', '能写报告以外的文书吗？', '/docs/features/report/'],
    ]);
    expect(FAQS.map((f) => f.answer)).toMatchSnapshot();
    expect(FAQS[0]!.answer).toBe(
      '不会由模型算。金额与数量由脚本计算，规则和数据是普通文件，可以查看，也可以修改；脚本算出的金额与数量同样标注“需人工确认”。模型负责阅读资料、判断、分类、摘录和写作。',
    );
    for (const f of FAQS)
      if (f.doc) expect(DOC_ROUTES.find((d) => d.path === f.doc!.href)?.title).toBe(f.doc.title);
  });

  it('AC-05-60 / AC-05-61：筛选计数 8 / 2 / 2 / 2 / 2；点“安装”只显示 vector-index、migrate，播报“显示 2 个问题：安装”', async () => {
    const w = await mountFaq();
    const group = w.get('.faq-filters');
    expect(group.attributes('role')).toBe('group');
    expect(group.attributes('aria-label')).toBe('按主题筛选');
    const buttons = w.findAll('.faq-filter');
    expect(buttons.map((b) => b.text().replace(/\s+/g, ' '))).toEqual([
      '全部 8',
      '安装 2',
      '数据 2',
      '结果 2',
      '协作 2',
    ]);
    expect(FAQ_GROUPS.map((g) => g.label)).toEqual(['全部', '安装', '数据', '结果', '协作']);
    await buttons[1]!.trigger('click');
    await flushPromises();
    expect(visibleIds(w)).toEqual(['faq-vector-index', 'faq-migrate']);
    expect(w.findAll('.faq-filter').map((b) => b.attributes('aria-pressed'))).toEqual([
      'false',
      'true',
      'false',
      'false',
      'false',
    ]);
    expect(w.get('#faq-status').text()).toBe('显示 2 个问题：安装');
    expect(w.get('#faq-status').attributes('role')).toBe('status');
    await buttons[0]!.trigger('click');
    await flushPromises();
    expect(w.get('#faq-status').text()).toBe('显示全部 8 个问题');
  });

  it('AC-05-62 / AC-05-72：默认 calc 展开；可同时展开多问；减少动效下立即完成', async () => {
    const w = await mountFaq();
    expect(openIds(w)).toEqual(['faq-calc']);
    await w.get('#faq-migrate summary').trigger('click');
    await flushPromises();
    expect(openIds(w)).toEqual(['faq-calc', 'faq-migrate']);
    await w.get('#faq-calc summary').trigger('click');
    await flushPromises();
    expect(openIds(w)).toEqual(['faq-migrate']);
  });

  it('AC-05-73：筛选到“数据”再回“全部”：之前展开的 calc 仍展开', async () => {
    const w = await mountFaq();
    await w.findAll('.faq-filter')[2]!.trigger('click');
    await flushPromises();
    expect(visibleIds(w)).toEqual(['faq-data-location', 'faq-scans-drawings']);
    await w.findAll('.faq-filter')[0]!.trigger('click');
    await flushPromises();
    expect(openIds(w)).toContain('faq-calc');
  });

  it('AC-05-65 / §4.6：无 JS 时为原生 details，全部 8 问可见；筛选组与复制按钮不渲染，预留高度', async () => {
    const { html } = await render('/');
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const faq = doc.getElementById('faq')!;
    const items = [...faq.querySelectorAll('details.faq-item')];
    expect(items).toHaveLength(8);
    expect(items.every((d) => !d.hasAttribute('hidden'))).toBe(true);
    expect(items[0]!.hasAttribute('open')).toBe(true);
    expect(items[0]!.querySelector('summary > h3')?.textContent).toBe('它会替我算造价吗？，结果');
    expect(faq.querySelector('.faq-filters')).toBeNull();
    expect(faq.querySelector('.faq-filter-slot')).not.toBeNull();
    expect(faq.querySelector('.faq-copy')).toBeNull();
    expect(items.map((d) => d.id)).toEqual(FAQS.map((f) => `faq-${f.id}`));
    expect(faq.querySelector('summary')?.hasAttribute('aria-expanded')).toBe(false);
  });

  it('AC-05-66 / AC-05-67：#faq-concurrent 深链：筛选为全部、该问展开、summary 获得焦点；hashchange 同样处理', async () => {
    history.replaceState(null, '', '/#faq-concurrent');
    const w = await mountFaq();
    await flushPromises();
    await new Promise((r) => setTimeout(r, 20));
    expect(openIds(w)).toContain('faq-concurrent');
    expect(document.activeElement).toBe(w.get('#faq-concurrent summary').element);
    await w.findAll('.faq-filter')[1]!.trigger('click');
    await flushPromises();
    history.replaceState(null, '', '/#faq-migrate');
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    await flushPromises();
    await new Promise((r) => setTimeout(r, 20));
    expect(w.get('.faq-filter[aria-pressed="true"]').text()).toContain('全部');
    expect(openIds(w)).toContain('faq-migrate');
    expect(document.activeElement).toBe(w.get('#faq-migrate summary').element);
  });

  it('AC-05-68：复制链接得到 https://ztsgai.com/#faq-{id}，提示“已复制问题链接”，地址栏写入 #faq-{id}', async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const w = await mountFaq();
    const btn = w.get('#faq-calc .faq-copy');
    expect(btn.attributes('aria-label')).toBe('复制本问题的链接');
    await btn.trigger('click');
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith('https://ztsgai.com/#faq-calc');
    expect(toastState.message).toBe('已复制问题链接');
    expect(location.hash).toBe('#faq-calc');
    expect(btn.classes()).toContain('is-copied');
  });

  it('AC-05-69：浏览器因页内查找展开收起的问题时同步展开状态', async () => {
    const w = await mountFaq();
    const det = w.get('#faq-migrate').element as HTMLDetailsElement;
    det.open = true;
    det.dispatchEvent(new Event('toggle'));
    await flushPromises();
    expect(openIds(w)).toContain('faq-migrate');
    expect(det.open).toBe(true);
  });

  it('AC-05-71：“在文档中查看更多 →”指向 /docs/troubleshooting/；各问相关文档在路由表内', async () => {
    const w = await mountFaq();
    const more = w.get('.faq-doc-link');
    expect(more.attributes('href')).toBe('/docs/troubleshooting/');
    expect(more.text()).toBe('在文档中查看更多');
    const paths = DOC_ROUTES.map((d) => d.path);
    for (const a of w.findAll('.faq-related')) {
      expect(paths).toContain(a.attributes('href'));
      expect(a.text()).toMatch(/^相关文档：/);
    }
    expect(w.findAll('.faq-related')).toHaveLength(7);
  });

  it('文案：眉标、h2、副标题；主题小标签', async () => {
    const w = await mountFaq();
    expect(w.get('.eyebrow').text()).toBe('常见问题');
    expect(w.get('h2#faq-title').text()).toBe('常见问题');
    expect(w.get('.section-heading p:not(.eyebrow)').text()).toBe('安装、数据、结果与协作');
    expect(w.get('#faq-calc .faq-tag').text()).toBe('结果');
    expect(w.get('#faq-calc .faq-tag').attributes('aria-hidden')).toBe('true');
  });
});
