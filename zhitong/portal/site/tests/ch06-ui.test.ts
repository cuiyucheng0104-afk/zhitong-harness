/** 06 章页面与组件（§4、§7、§8.1、AC-06-11、AC-06-15、AC-06-16、AC-06-24）。 */
import { flushPromises, mount } from '@vue/test-utils';
import { defineComponent, h, nextTick } from 'vue';
import { createMemoryHistory, createRouter, RouterView } from 'vue-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DOC_ROUTES, docsRoutes } from '../src/docs/routes';
import { verifyRenderedPage } from '../src/docs/verify';
import { docsUi } from '../src/docs/docs-ui';
import { toastState } from '../src/composables/useToast';
import CodeBlock from '../src/components/docs/CodeBlock.vue';
import ExampleUtterance from '../src/components/docs/ExampleUtterance.vue';
import Kbd from '../src/components/docs/Kbd.vue';
import Callout from '../src/components/docs/Callout.vue';
import { vSpotlight } from '../src/composables/useSpotlight';
import { contactChannels, hasContact, siteConfig } from '../src/site.config';

const Home = defineComponent({ render: () => h('main', { id: 'main' }, 'home') });

async function mountDocs(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    strict: true,
    routes: [{ path: '/', component: Home, meta: { layout: 'home' } }, ...docsRoutes],
  });
  await router.push(path);
  await router.isReady();
  const wrapper = mount(defineComponent({ render: () => h(RouterView) }), {
    attachTo: document.body,
    global: { plugins: [router], directives: { spotlight: vSpotlight } },
  });
  await flushPromises();
  return { wrapper, router };
}

beforeEach(() => {
  docsUi.searchOpen = false;
  docsUi.drawerOpen = false;
});
afterEach(() => vi.unstubAllGlobals());

describe('06 §1.1 路由', () => {
  it('23 页，路径带尾斜杠，head 元信息按 §3.5', () => {
    expect(DOC_ROUTES).toHaveLength(23);
    expect(DOC_ROUTES.every((d) => d.path.startsWith('/docs/') && d.path.endsWith('/'))).toBe(true);
    const children = docsRoutes[0].children!;
    const home = children.find((c) => c.path === '')!;
    expect(home.meta).toMatchObject({ title: '文档 · 智通数工AI', canonical: 'https://ztsgai.com/docs/' });
    const check = children.find((c) => c.path === 'features/check/')!;
    expect(check.meta).toMatchObject({
      title: '送审审定核对 · 文档 · 智通数工AI',
      canonical: 'https://ztsgai.com/docs/features/check/',
    });
    expect(String(check.meta!.description)).toMatch(/^比对送审与审定计价表/);
  });
});

describe('06 §7 文档页', () => {
  it('安装页：H1、面包屑、侧栏当前项、本页目录、上一页/下一页，联系行随配置、无投票控件', async () => {
    const { wrapper } = await mountDocs('/docs/install/');
    expect(wrapper.find('h1').text()).toBe('安装');
    expect(wrapper.find('nav[aria-label="面包屑"]').text().replace(/\s+/g, '')).toBe('文档开始使用安装');
    const sidebar = wrapper.find('aside.docs-sidebar[aria-label="文档目录"] nav[aria-label="文档"]');
    expect(sidebar.findAll('a')).toHaveLength(23);
    expect(sidebar.find('a[aria-current="page"]').text()).toBe('安装');
    expect(wrapper.findAll('.sidebar-group').map((g) => g.text())).toEqual(['开始使用', '项目与资料', '核对与测算', '成果与归档', '知识与协作', '参考']);
    expect(wrapper.find('nav.docs-toc[aria-label="本页目录"]').exists()).toBe(true);
    expect(wrapper.find('#校验安装包').exists()).toBe(true);
    const pager = wrapper.find('nav[aria-label="上一页与下一页"]');
    expect(pager.findAll('a').map((a) => a.attributes('aria-label'))).toEqual(['上一页：快速开始', '下一页：导入配置包']);
    expect(wrapper.find('.docs-updated').text()).toBe('更新于 2026-10-20');
    // 联系行随 site.config 的取值出现与否（AC-06-24）；固定取值的两种情况另见 ch06-config.test.ts。
    expect(wrapper.find('.docs-feedback').exists()).toBe(hasContact);
    if (hasContact) expect(wrapper.find('.docs-feedback').text()).toContain(contactChannels(siteConfig.contact)[0].value);
    expect(wrapper.html()).not.toContain('有帮助');
    expect(verifyRenderedPage('/docs/install/', wrapper.html())).toEqual([]);
  });
  it('文档首页：深色区 H1「文档」、6 张组卡片，没有侧栏、本页目录与面包屑', async () => {
    const { wrapper } = await mountDocs('/docs/');
    expect(wrapper.find('h1').text()).toBe('文档');
    expect(wrapper.find('.docs-sidebar').exists()).toBe(false);
    expect(wrapper.find('.docs-toc').exists()).toBe(false);
    expect(wrapper.find('nav[aria-label="面包屑"]').exists()).toBe(false);
    const cards = wrapper.findAll('.doc-card');
    expect(cards).toHaveLength(6);
    expect(cards[0].find('.doc-card-desc').text()).toBe('安装、导入配置包、第一次对话，以及多步任务怎么跑。');
    expect(cards[0].attributes('aria-labelledby')).toBe('dc-1');
  });
  it('verifyRenderedPage 发现缺失的 H1 与标题 id', () => {
    expect(verifyRenderedPage('/docs/install/', '<h1>别的</h1>')).toEqual(
      expect.arrayContaining(['缺少 H1「安装」', '缺少标题 id「校验安装包」']),
    );
  });
});

describe('06 AC-06-11 快捷键', () => {
  it('文档页 Ctrl+K 与 / 打开搜索；输入框里的 / 不打开；离开文档后不再绑定', async () => {
    const { wrapper, router } = await mountDocs('/docs/install/');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }));
    expect(docsUi.searchOpen).toBe(true);
    docsUi.searchOpen = false;
    await nextTick();
    const input = document.createElement('input');
    document.body.append(input);
    input.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true }));
    expect(docsUi.searchOpen).toBe(false);
    input.remove();
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '/' }));
    expect(docsUi.searchOpen).toBe(true);
    docsUi.searchOpen = false;
    await router.push('/');
    await flushPromises();
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }));
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '/' }));
    expect(docsUi.searchOpen).toBe(false);
    wrapper.unmount();
  });
});

describe('06 §7.9–§7.12 组件', () => {
  it('AC-06-15：代码块复制原文（不含标题条）并提示「已复制代码」', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const w = mount(CodeBlock, {
      props: { lang: 'bash' },
      slots: { default: '<div class="code-scroll"><pre><code><span>cd ~/Downloads</span>\n<span>shasum -a 256 a.dmg</span></code></pre></div>' },
    });
    await nextTick();
    expect(w.find('.code-lang').text()).toBe('macOS 终端');
    await w.find('button[aria-label="复制代码"]').trigger('click');
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith('cd ~/Downloads\nshasum -a 256 a.dmg');
    expect(toastState.message).toBe('已复制代码');
    expect(w.find('.code-copy').classes()).toContain('is-copied');
  });
  it('text 代码块不显示语言名', () => {
    expect(mount(CodeBlock, { props: { lang: 'text' } }).find('.code-lang').text()).toBe('');
  });
  it('AC-06-16：说法整条复制（不含引号），提示「已复制，可粘贴到对话框」', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    const w = mount(ExampleUtterance, { props: { text: '核对一下送审和审定计价表。' }, slots: { default: '核对一下送审和审定计价表。' } });
    await nextTick();
    const btn = w.find('button');
    expect(btn.attributes('aria-label')).toBe('复制这句话：核对一下送审和审定计价表。');
    await btn.trigger('click');
    await flushPromises();
    expect(writeText).toHaveBeenCalledWith('核对一下送审和审定计价表。');
    expect(toastState.message).toBe('已复制，可粘贴到对话框');
  });
  it('Kbd 每键一个 kbd，读屏读原文', () => {
    const w = mount(Kbd, { props: { keys: 'Option+Command+C' } });
    expect(w.findAll('kbd.kbd').map((k) => k.text())).toEqual(['Option', 'Command', 'C']);
    expect(w.find('.sr-only').text()).toBe('Option+Command+C');
  });
  it('Callout 类型以文字出现在标题里', () => {
    const w = mount(Callout, { props: { type: 'confirm', title: '签发前至少确认' } });
    expect(w.find('aside').attributes()).toMatchObject({ role: 'note', 'aria-label': '需人工确认：签发前至少确认' });
    expect(w.find('.callout-head').text()).toBe('需人工确认：签发前至少确认');
    expect(mount(Callout, { props: { type: 'tip' } }).find('.callout-head').text()).toBe('提示');
  });
});
