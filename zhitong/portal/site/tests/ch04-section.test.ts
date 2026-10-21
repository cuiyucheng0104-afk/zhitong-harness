/** 04 章能力区组件（AC-04-06 – 08、09、14 部分、19、20、21 部分、22 部分、23、24 部分、28 部分）。 */
import { describe, expect, it, vi, afterEach } from 'vitest';
import { flushPromises } from '@vue/test-utils';
import { createSSRApp, h } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { createMemoryHistory, createRouter } from 'vue-router';
import { mount } from '@vue/test-utils';
import Section from '../src/components/CapabilitiesSection.vue';
import { featureGroups, allFeatures } from '../src/data/capabilities';
import { vMagnetic } from '../src/composables/useMagnetic';
import { vSpotlight } from '../src/composables/useSpotlight';

const wait = (ms = 30) => new Promise((r) => setTimeout(r, ms));

/** 只含首页与通配的内存路由（不加载整站，避免依赖其它章节的组件）。 */
async function testRouter() {
  const router = createRouter({
    history: createMemoryHistory(),
    strict: true,
    routes: [
      { path: '/', component: { render: () => null } },
      { path: '/:p(.*)*', component: { render: () => null } },
    ],
  });
  await router.push('/');
  await router.isReady();
  return router;
}

async function mountSection(props: Record<string, unknown> = {}) {
  const router = await testRouter();
  const wrapper = mount(Section, {
    props,
    attachTo: document.body,
    global: { plugins: [router], directives: { magnetic: vMagnetic, spotlight: vSpotlight } },
  });
  await flushPromises();
  return wrapper;
}

function mockLayout(width: number) {
  const impl = (query: string) => {
    const max = /max-width:\s*(\d+)px/.exec(query);
    const matches =
      query.includes('prefers-reduced-motion') || (max ? width <= Number(max[1]) : false);
    return {
      matches,
      media: query,
      onchange: null,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent: () => false,
    };
  };
  return vi
    .spyOn(window, 'matchMedia')
    .mockImplementation(impl as unknown as typeof window.matchMedia);
}

afterEach(() => {
  history.replaceState(null, '', '/');
});

describe('AC-04-07 初始状态', () => {
  it('选中“核对与测算”与“送审审定核对”；cloud 显示“管理员”；已增强', async () => {
    const w = await mountSection();
    expect(w.get('#capabilities').classes()).toContain('cap-enhanced');
    expect(w.get('#group-calculate').attributes('aria-selected')).toBe('true');
    expect(w.get('#group-calculate').attributes('aria-label')).toBe('核对与测算，4 项');
    expect(w.get('#feature-group-calculate .feature-item[open]').attributes('data-feature')).toBe(
      'check',
    );
    expect(w.get('#feature-group-project').attributes('hidden')).toBeDefined();
    expect(w.get('#feature-cloud summary').text()).toContain('管理员');
    expect(w.findAll('.feature-active-bar')).toHaveLength(4);
    expect(w.get('.cap-count').text()).toBe('12');
    expect(w.get('.cap-dimline .dd-label').text()).toBe('12 = 3 + 4 + 3 + 2');
    expect(w.findAll('.feature-item')).toHaveLength(12);
  });
  it('章节头文案逐字', async () => {
    const w = await mountSection();
    expect(w.get('.eyebrow').text()).toBe('产品能力');
    expect(w.get('#capabilities-title').text()).toBe('从项目资料，到交付成果。');
    expect(w.get('.cap-lede').text().replace(/\s+/g, '')).toBe(
      '12项具体工作，按任务选择。每项都写明需要什么、得到什么、结果放在哪里。',
    );
    expect(w.get('.capability-footnote').text()).toBe('资料有位置，计算有依据，成果有去处。');
    expect(w.findAll('.feature-group-intro').map((p) => p.text())).toEqual(
      featureGroups.map((g) => g.intro),
    );
    expect(
      w
        .get('#feature-check dl')
        .findAll('dt')
        .map((d) => d.text()),
    ).toEqual(['需要什么', '得到什么', '您可以这样说', '产出位置']);
  });
});

describe('AC-04-06 计数由 home 派生', () => {
  it('cloud.home = false：显示 11 与“11 = 3 + 4 + 3 + 1”，#feature-cloud 不渲染', async () => {
    const groups = featureGroups.map((g) => ({
      ...g,
      features: g.features.map((f) => (f.id === 'cloud' ? { ...f, home: false } : f)),
    }));
    const w = await mountSection({ groups });
    expect(w.get('.cap-count').text()).toBe('11');
    expect(w.get('.cap-dimline .dd-label').text()).toBe('11 = 3 + 4 + 3 + 1');
    expect(w.find('#feature-cloud').exists()).toBe(false);
    expect(w.get('#group-knowledge').attributes('aria-label')).toBe('知识与协作，1 项');
  });
});

describe('AC-04-08 页签键盘', () => {
  it('→ 移到下一页签并选中；End / Home；漫游 tabindex 只有一个 0', async () => {
    const w = await mountSection();
    const tabs = () => w.findAll('[role="tab"]');
    await w.get('#group-calculate').trigger('keydown', { key: 'ArrowRight' });
    await flushPromises();
    expect(w.get('#group-output').attributes('aria-selected')).toBe('true');
    expect(document.activeElement).toBe(w.get('#group-output').element);
    await w.get('#group-output').trigger('keydown', { key: 'End' });
    await flushPromises();
    expect(w.get('#group-knowledge').attributes('aria-selected')).toBe('true');
    await w.get('#group-knowledge').trigger('keydown', { key: 'Home' });
    await flushPromises();
    expect(w.get('#group-project').attributes('aria-selected')).toBe('true');
    expect(tabs().filter((t) => t.attributes('tabindex') === '0')).toHaveLength(1);
  });
  it('列表 ↑/↓/Home/End 只移动焦点，不选中', async () => {
    const w = await mountSection();
    const s = w.findAll('#feature-group-calculate summary');
    (s[0]!.element as HTMLElement).focus();
    await s[0]!.trigger('keydown', { key: 'ArrowDown' });
    expect(document.activeElement).toBe(s[1]!.element);
    await s[1]!.trigger('keydown', { key: 'End' });
    expect(document.activeElement).toBe(s[3]!.element);
    await s[3]!.trigger('keydown', { key: 'ArrowDown' });
    expect(document.activeElement).toBe(s[3]!.element);
    await s[3]!.trigger('keydown', { key: 'Home' });
    expect(document.activeElement).toBe(s[0]!.element);
    expect(w.get('#feature-group-calculate .feature-item[open]').attributes('data-feature')).toBe(
      'check',
    );
  });
});

describe('AC-04-09 切组记忆', () => {
  it('切到另一组再切回，恢复该组上次选中的能力项；旧面板关闭', async () => {
    const w = await mountSection();
    await w.get('#feature-control summary').trigger('click');
    await flushPromises();
    expect(w.get('#feature-control').attributes('open')).toBeDefined();
    expect(w.get('#feature-check').attributes('open')).toBeUndefined();
    await w.get('#group-output').trigger('click');
    await flushPromises();
    expect(w.get('#feature-group-output .feature-item[open]').attributes('data-feature')).toBe(
      'report',
    );
    await w.get('#group-calculate').trigger('click');
    await flushPromises();
    expect(w.get('#feature-group-calculate .feature-item[open]').attributes('data-feature')).toBe(
      'control',
    );
  });
});

describe('selectFeature（03 章接口，§5.4）', () => {
  it('跨分组选中并聚焦标题；未知 id 忽略', async () => {
    const w = await mountSection();
    const vm = w.vm as unknown as { selectFeature: (id: string, o?: object) => Promise<void> };
    await vm.selectFeature('archive');
    await flushPromises();
    expect(w.get('#group-output').attributes('aria-selected')).toBe('true');
    expect(w.get('#feature-archive').attributes('open')).toBeDefined();
    expect(document.activeElement?.id).toBe('feature-archive-title');
    await vm.selectFeature('nope');
    expect(w.get('#group-output').attributes('aria-selected')).toBe('true');
  });
});

describe('AC-04-23 深链接', () => {
  it('/#feature-control：选中核对与测算与投控，焦点在 #feature-control-title', async () => {
    history.replaceState(null, '', '/#feature-control');
    const w = await mountSection();
    await wait(40);
    await flushPromises();
    expect(w.get('#group-calculate').attributes('aria-selected')).toBe('true');
    expect(w.get('#feature-control').attributes('open')).toBeDefined();
    expect(document.activeElement?.id).toBe('feature-control-title');
  });
  it('/#feature-unknown 不改变选中项', async () => {
    history.replaceState(null, '', '/#feature-unknown');
    const w = await mountSection();
    await wait(20);
    expect(w.get('#feature-check').attributes('open')).toBeDefined();
  });
  it('hashchange 到 #feature-bills 切换到成果与归档', async () => {
    const w = await mountSection();
    history.replaceState(null, '', '/#feature-bills');
    window.dispatchEvent(new HashChangeEvent('hashchange'));
    await wait(40);
    await flushPromises();
    expect(w.get('#group-output').attributes('aria-selected')).toBe('true');
    expect(w.get('#feature-bills').attributes('open')).toBeDefined();
  });
});

describe('链接（AC-04-21 组件部分、AC-04-22 链接部分）', () => {
  it('“查看工作示例”只在 check / control / cad，href="#demo"，点击发出 scene', async () => {
    const w = await mountSection();
    const links = w.findAll('a[data-scene]');
    expect(links.map((a) => a.attributes('data-scene'))).toEqual(['cad', 'check', 'review']);
    for (const a of links) expect(a.attributes('href')).toBe('#demo');
    const review = w.get('a[data-scene="review"]');
    expect(review.attributes('aria-label')).toBe(
      '查看工作示例：投控异常检测与复核，跳到页面上方的示例窗口',
    );
    await review.trigger('click', { button: 0 });
    expect(w.emitted('scene')).toEqual([['review']]);
  });
  it('12 个“读文档”指向 /docs/features/<id>/', async () => {
    const w = await mountSection();
    const docs = w.findAll('a.text-link:not([data-scene])');
    expect(docs).toHaveLength(12);
    expect(docs.map((a) => a.attributes('href'))).toEqual(
      allFeatures.map((f) => `/docs/features/${f.id}/`),
    );
    expect(docs[0]!.attributes('aria-label')).toBe('读文档：开项目与资料盘点');
  });
});

describe('术语说明卡', () => {
  it('术语只在面板中第一次出现处渲染为按钮，点击打开同一张说明卡', async () => {
    const w = await mountSection();
    const project = w.get('#feature-project');
    expect(project.findAll('.term-link').map((b) => b.text())).toEqual([
      '项目说明',
      '案例索引',
      '公司存储桶',
    ]);
    expect(
      project
        .get('.feature-io')
        .findAll('.term-link')
        .map((b) => b.text()),
    ).toEqual(['公司存储桶']);
    expect(
      w
        .get('#feature-cloud')
        .findAll('.term-link')
        .map((b) => b.text()),
    ).toEqual(['配置包']);
    await w.get('#feature-check .term-link').trigger('click');
    await flushPromises();
    const pop = document.getElementById('cap-term-popover')!;
    expect(pop.textContent).toContain('待确认清单');
    expect(pop.textContent).toContain('每个工作目录里的 待确认清单.md');
  });
});

describe('AC-04-19 减少动效（测试环境即减少动效）', () => {
  it('不构建小动画：舞台没有 art-live，暂停按钮隐藏', async () => {
    const w = await mountSection();
    await wait(30);
    expect(w.findAll('.art-stage.art-live')).toHaveLength(0);
    for (const b of w.findAll('.art-toggle')) expect(b.attributes('hidden')).toBeDefined();
    expect(w.get('.art-toggle').attributes('aria-label')).toBe('暂停示意动画');
    expect(w.get('.art-toggle').attributes('aria-pressed')).toBe('false');
  });
});

describe('AC-04-24 手机手风琴（390 宽）', () => {
  it('同组最多一项展开；再点收起；切组后显示新组', async () => {
    const spy = mockLayout(390);
    const w = await mountSection();
    expect(w.get('#capabilities').attributes('data-layout')).toBe('mobile');
    expect(w.findAll('.feature-active-bar')).toHaveLength(0);
    await w.get('#feature-metrics summary').trigger('click');
    await flushPromises();
    expect(
      w
        .findAll('#feature-group-calculate .feature-item[open]')
        .map((d) => d.attributes('data-feature')),
    ).toEqual(['metrics']);
    await w.get('#feature-metrics summary').trigger('click');
    await flushPromises();
    expect(w.findAll('#feature-group-calculate .feature-item[open]')).toHaveLength(0);
    await w.get('#group-project').trigger('click');
    await flushPromises();
    expect(w.get('#feature-group-project').attributes('hidden')).toBeUndefined();
    spy.mockRestore();
  });
});

describe('AC-04-20 预渲染（无 JS）', () => {
  async function ssr() {
    const router = await testRouter();
    const app = createSSRApp({ render: () => h(Section) });
    app.use(router);
    app.directive('magnetic', vMagnetic);
    app.directive('spotlight', vSpotlight);
    return renderToString(app);
  }
  it('没有 cap-enhanced；四组各首项展开；12 项全部在 HTML 中；暂停按钮 hidden；看示例为 #demo 锚点', async () => {
    const html = await ssr();
    const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');
    const section = doc.getElementById('capabilities')!;
    expect(section.classList.contains('cap-enhanced')).toBe(false);
    expect(section.querySelectorAll('details.feature-item')).toHaveLength(12);
    expect(
      [...section.querySelectorAll('details[open]')].map((d) => d.getAttribute('data-feature')),
    ).toEqual(['project', 'check', 'report', 'knowledge']);
    expect(section.querySelectorAll('.art-toggle[hidden]')).toHaveLength(12);
    expect(section.querySelectorAll('.art-stage.art-live')).toHaveLength(0);
    expect(
      [...section.querySelectorAll('a[data-scene]')].map((a) => a.getAttribute('href')),
    ).toEqual(['#demo', '#demo', '#demo']);
    expect(section.querySelectorAll('.feature-group-label')).toHaveLength(4);
    expect(section.querySelectorAll('figcaption')).toHaveLength(12);
    for (const f of allFeatures)
      expect(section.querySelector(`[data-art="${f.id}"] figcaption`)!.textContent).toBe(
        f.art.caption,
      );
    for (const svg of section.querySelectorAll('.art-stage svg')) {
      expect(svg.getAttribute('aria-hidden')).toBe('true');
      expect(svg.getAttribute('focusable')).toBe('false');
    }
  });
  it('AC-04-28（HTML 部分）：12 段 SVG 未压缩合计 ≤ 60 KB', async () => {
    const html = await ssr();
    const svgs = html.match(/<svg class="art-(?:in|link|out)"[\s\S]*?<\/svg>/g) ?? [];
    expect(svgs.length).toBe(36);
    const bytes = svgs.reduce((n, s) => n + Buffer.byteLength(s, 'utf8'), 0);
    expect(bytes).toBeLessThanOrEqual(60 * 1024);
  });
});
