import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import SiteHeader from '../src/components/SiteHeader.vue';

describe('移动端导航', () => {
  it('点击章节关闭菜单并通知页面导航', async () => {
    const wrapper = mount(SiteHeader, { props: { activeSection: '' } });
    await wrapper.get('.menu-toggle').trigger('click');
    expect(wrapper.get('.menu-toggle').attributes('aria-expanded')).toBe('true');
    await wrapper.get('#mobile-menu a').trigger('click');
    expect(wrapper.get('.menu-toggle').attributes('aria-expanded')).toBe('false');
    expect(wrapper.emitted('navigate')?.[0]).toEqual(['capabilities']);
  });

  it('Esc关闭菜单并恢复菜单按钮焦点', async () => {
    const wrapper = mount(SiteHeader, { props: { activeSection: '' }, attachTo: document.body });
    await wrapper.get('.menu-toggle').trigger('click');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await wrapper.vm.$nextTick();
    expect(wrapper.get('.menu-toggle').attributes('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(wrapper.get('.menu-toggle').element);
  });
});
