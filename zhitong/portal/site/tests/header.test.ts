import { describe, expect, it } from 'vitest';
import { flushPromises } from '@vue/test-utils';
import { mountAt } from './helpers';

describe('移动端导航（01 章 §5）', () => {
  it('点菜单按钮打开对话框；点章节先关闭菜单再导航', async () => {
    const { wrapper } = await mountAt('/');
    const toggle = wrapper.get('.site-header > .header-inner .menu-toggle');
    await toggle.trigger('click');
    const dialog = document.getElementById('mobile-menu') as HTMLDialogElement;
    expect(dialog.open).toBe(true);
    expect(toggle.attributes('aria-expanded')).toBe('true');
    expect(document.body.classList.contains('modal-open')).toBe(true);
    const links = dialog.querySelectorAll<HTMLAnchorElement>('.mobile-sheet-row');
    expect([...links].map((a) => a.textContent?.replace(/\s+/g, ''))).toEqual([
      '01产品能力',
      '02使用流程',
      '03数据与复核',
      '04常见问题',
      '文档安装、配置包、12项能力与排错',
    ]);
    links[1]!.click();
    await flushPromises();
    expect(dialog.open).toBe(false);
    expect(window.location.hash).toBe('#workflow-title');
    expect(document.activeElement?.id).toBe('workflow-title');
  });

  it('Esc 关闭菜单并把焦点还给菜单按钮', async () => {
    const { wrapper } = await mountAt('/');
    const toggle = wrapper.get('.site-header > .header-inner .menu-toggle');
    (toggle.element as HTMLElement).focus();
    await toggle.trigger('click');
    const dialog = document.getElementById('mobile-menu') as HTMLDialogElement;
    dialog.dispatchEvent(new Event('cancel', { cancelable: true }));
    await flushPromises();
    expect(dialog.open).toBe(false);
    expect(toggle.attributes('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(toggle.element);
  });

  it('底部说明列出版本与平台，未发布平台标注即将发布', async () => {
    await mountAt('/');
    const foot = document.querySelector('.mobile-sheet-foot')?.textContent ?? '';
    expect(foot).toMatch(/^v\d+\.\d+\.\d+ · Mac（Apple 芯片）(（即将发布）)?与 Windows（x64）(（即将发布）)?$/);
  });
});
