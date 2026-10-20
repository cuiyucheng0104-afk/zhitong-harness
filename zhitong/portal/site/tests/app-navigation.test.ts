import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it } from 'vitest';

beforeEach(() => {
  history.replaceState(null, '', '/');
});
import App from '../src/App.vue';

describe('页面锚点导航', () => {
  it('品牌返回首页和跳过导航聚焦正文入口', async () => {
    const wrapper = mount(App, { attachTo: document.body });
    await wrapper.get('.site-header .brand').trigger('click');
    expect(window.location.hash).toBe('#main');
    expect(document.activeElement?.id).toBe('main');
    await wrapper.get('.skip-link').trigger('click');
    expect(document.activeElement?.id).toBe('main');
  });

  it('导航到 FAQ 将焦点放在可见的章节标题', async () => {
    const wrapper = mount(App, { attachTo: document.body });
    await wrapper.get('.desktop-nav a[href="#faq"]').trigger('click');
    expect(window.location.hash).toBe('#faq-title');
    expect(document.activeElement?.id).toBe('faq-title');
  });
});
