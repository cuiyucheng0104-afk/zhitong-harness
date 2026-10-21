import { beforeEach, describe, expect, it } from 'vitest';
import { flushPromises } from '@vue/test-utils';
import { mountAt } from './helpers';

beforeEach(() => {
  history.replaceState(null, '', '/');
});

describe('页面锚点导航', () => {
  it('品牌返回首页和跳过导航聚焦正文入口', async () => {
    const { wrapper } = await mountAt('/');
    await wrapper.get('.site-header .brand').trigger('click');
    await flushPromises();
    expect(window.location.hash).toBe('#main');
    expect(document.activeElement?.id).toBe('main');
    await wrapper.get('.skip-link').trigger('click');
    await flushPromises();
    expect(document.activeElement?.id).toBe('main');
  });

  it('导航到 FAQ 将焦点放在可见的章节标题，并乐观设为当前项', async () => {
    const { wrapper } = await mountAt('/');
    await wrapper.get('.desktop-nav a[href="#faq"]').trigger('click');
    // 点击后立即乐观设为当前项（滚动完成前锁住跟踪器）
    expect(wrapper.get('.desktop-nav a[href="#faq"]').attributes('aria-current')).toBe('location');
    await flushPromises();
    expect(window.location.hash).toBe('#faq-title');
    expect(document.activeElement?.id).toBe('faq-title');
  });
});
