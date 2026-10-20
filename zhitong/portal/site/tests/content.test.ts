import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { mount, type VueWrapper } from '@vue/test-utils';
import { describe, expect, it, vi } from 'vitest';
import CapabilitiesSection from '../src/components/CapabilitiesSection.vue';
import FaqSection from '../src/components/FaqSection.vue';
import RolesSection from '../src/components/RolesSection.vue';
import { faqs, featureGroups, roles } from '../src/data/content';
import * as motion from '../src/lib/motion';

const prototype = new DOMParser().parseFromString(
  readFileSync(resolve('tests/fixtures/prototype-v0.1.html'), 'utf8'),
  'text/html',
);
const normalize = (text: string) => text.replace(/\s+/g, '');

function mobileMedia(initial: boolean) {
  let listener: ((event: MediaQueryListEvent) => void) | undefined;
  const media = {
    matches: initial,
    media: '(max-width: 767px)',
    addEventListener: vi.fn((_: string, callback: (event: MediaQueryListEvent) => void) => {
      listener = callback;
    }),
    removeEventListener: vi.fn(),
  };
  vi.spyOn(window, 'matchMedia').mockReturnValue(media as unknown as MediaQueryList);
  return {
    media,
    change(matches: boolean) {
      media.matches = matches;
      listener?.({ matches } as MediaQueryListEvent);
    },
  };
}

async function checkTabKeyboard(wrapper: VueWrapper, selector: string, initial: number) {
  const tabs = wrapper.findAll(`${selector} [role="tab"]`);
  (tabs[initial]!.element as HTMLElement).focus();
  const next = (initial + 1) % tabs.length;
  await tabs[initial]!.trigger('keydown', { key: 'ArrowRight' });
  expect(document.activeElement).toBe(tabs[next]!.element);
  expect(tabs[next]!.attributes('aria-selected')).toBe('true');
  expect(tabs[next]!.attributes('tabindex')).toBe('0');
  expect(tabs.filter((tab) => tab.attributes('tabindex') === '0')).toHaveLength(1);

  await tabs[next]!.trigger('keydown', { key: 'End' });
  expect(document.activeElement).toBe(tabs.at(-1)!.element);
  await tabs.at(-1)!.trigger('keydown', { key: 'ArrowDown' });
  expect(document.activeElement).toBe(tabs[0]!.element);
  await tabs[0]!.trigger('keydown', { key: 'ArrowLeft' });
  expect(document.activeElement).toBe(tabs.at(-1)!.element);
  await tabs.at(-1)!.trigger('keydown', { key: 'Home' });
  expect(document.activeElement).toBe(tabs[0]!.element);
  expect(tabs[0]!.attributes('aria-selected')).toBe('true');
}

describe('内容数据', () => {
  it('保留四组十二项能力、三种角色和四项常见问题', () => {
    expect(featureGroups.map((group) => [group.id, group.features.length])).toEqual([
      ['project', 3],
      ['calculate', 4],
      ['output', 3],
      ['knowledge', 2],
    ]);
    const features = featureGroups.flatMap((group) => group.features);
    expect(new Set(features.map((feature) => feature.id)).size).toBe(12);
    expect(features.every((feature) => feature.caution.length > 0)).toBe(true);
    expect(roles.map((role) => role.id)).toEqual(['engineer', 'reviewer', 'manager']);
    expect(faqs).toHaveLength(4);
  });
});

describe('能力浏览器', () => {
  it('默认显示核对与测算中的送审审定核对，所有能力均保留在 DOM', () => {
    const wrapper = mount(CapabilitiesSection);
    expect(wrapper.get('#group-calculate').attributes('aria-selected')).toBe('true');
    expect(wrapper.get('#group-calculate').attributes('tabindex')).toBe('0');
    expect(wrapper.get('#feature-group-calculate').attributes('hidden')).toBeUndefined();
    expect(wrapper.get('#feature-group-project').attributes('hidden')).toBeDefined();
    expect(wrapper.findAll('.feature-group')).toHaveLength(4);
    expect(wrapper.findAll('.feature-item')).toHaveLength(12);
    expect(
      wrapper.get('#feature-group-calculate .feature-item[open]').attributes('data-feature'),
    ).toBe('check');
    expect(wrapper.get('[data-feature="check"] summary').attributes('aria-expanded')).toBe('true');
  });

  it('保留原型全部能力文案、警告与成果示意', () => {
    const wrapper = mount(CapabilitiesSection);
    for (const item of wrapper.findAll('.feature-item')) {
      const original = prototype.querySelector(
        `[data-feature="${item.attributes('data-feature')}"]`,
      )!;
      expect(normalize(item.text())).toBe(normalize(original.textContent!));
    }
    expect(wrapper.findAll('.feature-art')).toHaveLength(12);
    expect(wrapper.find('[data-feature="check"] .feature-caution .icon').exists()).toBe(true);
    expect(wrapper.get('[data-feature="project"] .artifact-list').attributes('aria-label')).toBe(
      '资料盘点示意',
    );
  });

  it('切换分组时选中该组第一项，返回已浏览分组也重新选第一项', async () => {
    const wrapper = mount(CapabilitiesSection);
    await wrapper.get('[data-feature="metrics"] summary').trigger('click');
    await wrapper.get('#group-output').trigger('click');
    expect(wrapper.get('#group-output').attributes('aria-selected')).toBe('true');
    expect(
      wrapper.get('#feature-group-output .feature-item[open]').attributes('data-feature'),
    ).toBe('report');
    expect(wrapper.get('#feature-group-calculate').attributes('hidden')).toBeDefined();
    await wrapper.get('#group-calculate').trigger('click');
    expect(
      wrapper.get('#feature-group-calculate .feature-item[open]').attributes('data-feature'),
    ).toBe('check');
  });

  it('selectFeature 跨分组选中能力并在 DOM 更新后聚焦标题', async () => {
    const wrapper = mount(CapabilitiesSection, { attachTo: document.body });
    await wrapper.vm.selectFeature('archive');
    expect(wrapper.get('#group-output').attributes('aria-selected')).toBe('true');
    expect(wrapper.get('#feature-group-output').attributes('hidden')).toBeUndefined();
    expect(wrapper.findAll('#feature-group-output .feature-item[open]')).toHaveLength(1);
    expect(wrapper.get('[data-feature="archive"]').attributes('open')).toBeDefined();
    expect(wrapper.get('[data-feature="archive"] summary').attributes('aria-expanded')).toBe(
      'true',
    );
    expect(document.activeElement).toBe(wrapper.get('[data-feature="archive"] h3').element);
    await wrapper.vm.selectFeature('unknown-feature');
    expect(wrapper.get('#group-output').attributes('aria-selected')).toBe('true');
  });

  it('桌面端必须保留一个展开项，选择其它能力会关闭前一项', async () => {
    const wrapper = mount(CapabilitiesSection);
    await wrapper.get('[data-feature="check"] summary').trigger('click');
    expect(wrapper.get('[data-feature="check"]').attributes('open')).toBeDefined();
    await wrapper.get('[data-feature="estimate"] summary').trigger('click');
    expect(wrapper.findAll('#feature-group-calculate .feature-item[open]')).toHaveLength(1);
    expect(wrapper.get('[data-feature="check"] summary').attributes('aria-expanded')).toBe('false');
    expect(wrapper.get('[data-feature="estimate"] summary').attributes('aria-expanded')).toBe(
      'true',
    );
  });

  it('移动端可收起当前能力，切回桌面时恢复选项，并清理媒体订阅', async () => {
    const { media, change } = mobileMedia(true);
    const wrapper = mount(CapabilitiesSection);
    await wrapper.get('[data-feature="check"] summary').trigger('click');
    expect(wrapper.findAll('#feature-group-calculate .feature-item[open]')).toHaveLength(0);
    expect(wrapper.get('[data-feature="check"] summary').attributes('aria-expanded')).toBe('false');
    change(false);
    await wrapper.vm.$nextTick();
    expect(wrapper.get('[data-feature="check"]').attributes('open')).toBeDefined();
    expect(media.addEventListener).toHaveBeenCalledWith('change', expect.any(Function));
    const callback = media.addEventListener.mock.calls[0]![1];
    wrapper.unmount();
    expect(media.removeEventListener).toHaveBeenCalledWith('change', callback);
  });

  it.each([
    ['cad', 'cad'],
    ['check', 'check'],
    ['control', 'review'],
  ])('能力 %s 的示例入口发送场景 %s', async (featureId, sceneId) => {
    const wrapper = mount(CapabilitiesSection);
    await wrapper.vm.selectFeature(featureId);
    await wrapper.get(`[data-feature="${featureId}"] .text-link`).trigger('click');
    expect(wrapper.emitted('scene')).toEqual([[sceneId]]);
  });

  it('能力分组支持方向键、Home、End 和循环焦点', async () => {
    await checkTabKeyboard(
      mount(CapabilitiesSection, { attachTo: document.body }),
      '.capability-tabs',
      1,
    );
  });

  it('能力布局改变后刷新滚动动效测量', async () => {
    const wrapper = mount(CapabilitiesSection);
    const refresh = vi.spyOn(motion, 'refreshMotionLayout');
    await wrapper.get('#group-output').trigger('click');
    expect(refresh).toHaveBeenCalled();
    refresh.mockClear();
    await wrapper.get('[data-feature="bills"] summary').trigger('click');
    expect(refresh).toHaveBeenCalled();
    refresh.mockClear();
    await wrapper.vm.selectFeature('cad');
    expect(refresh).toHaveBeenCalled();
  });
});

describe('岗位入口', () => {
  it('默认显示造价工程师，并保留三种角色的原型文案', () => {
    const wrapper = mount(RolesSection);
    expect(wrapper.get('#role-engineer').attributes('aria-selected')).toBe('true');
    expect(wrapper.get('#panel-engineer').attributes('hidden')).toBeUndefined();
    expect(wrapper.get('#panel-reviewer').attributes('hidden')).toBeDefined();
    for (const panel of wrapper.findAll('.role-panel')) {
      expect(normalize(panel.text())).toBe(
        normalize(prototype.getElementById(panel.attributes('id')!)!.textContent!),
      );
    }
  });

  it('角色任务发送判别联合 action，由父组件负责全局跳转', async () => {
    const wrapper = mount(RolesSection);
    await wrapper.get('#panel-engineer [data-go-feature="check"]').trigger('click');
    await wrapper.get('#role-reviewer').trigger('click');
    expect(wrapper.get('#panel-reviewer').attributes('hidden')).toBeUndefined();
    expect(wrapper.get('#panel-engineer').attributes('hidden')).toBeDefined();
    await wrapper.get('#panel-reviewer [data-view-source]').trigger('click');
    await wrapper.get('#panel-reviewer [data-go-scene="review"]').trigger('click');
    await wrapper.get('#role-manager').trigger('click');
    await wrapper.get('#panel-manager a[href="#trust"]').trigger('click');
    expect(wrapper.emitted('action')).toEqual([
      [{ type: 'feature', id: 'check' }],
      [{ type: 'source' }],
      [{ type: 'scene', id: 'review' }],
      [{ type: 'section', id: 'trust' }],
    ]);
  });

  it('岗位选项支持方向键、Home、End 和循环焦点', async () => {
    await checkTabKeyboard(mount(RolesSection, { attachTo: document.body }), '.role-tabs', 0);
  });
});

describe('常见问题', () => {
  it('首项默认展开，四项问题与回答保留原型文案', () => {
    const wrapper = mount(FaqSection);
    const items = wrapper.findAll('.faq-item');
    const original = prototype.querySelectorAll('.faq-item');
    expect(items).toHaveLength(4);
    expect(items[0]!.attributes('open')).toBeDefined();
    expect(items[0]!.get('summary').attributes('aria-expanded')).toBe('true');
    items.forEach((item, index) => {
      expect(normalize(item.text())).toBe(normalize(original[index]!.textContent!));
    });
  });

  it('一次只展开一项，再次点击已展开的问题可全部收起', async () => {
    const wrapper = mount(FaqSection);
    const summaries = wrapper.findAll('.faq-item summary');
    await summaries[1]!.trigger('click');
    expect(wrapper.findAll('.faq-item[open]')).toHaveLength(1);
    expect(summaries[0]!.attributes('aria-expanded')).toBe('false');
    expect(summaries[1]!.attributes('aria-expanded')).toBe('true');
    await summaries[1]!.trigger('click');
    expect(wrapper.findAll('.faq-item[open]')).toHaveLength(0);
    expect(summaries[1]!.attributes('aria-expanded')).toBe('false');
  });

  it('回答展开后刷新滚动动效测量', async () => {
    const wrapper = mount(FaqSection);
    const refresh = vi.spyOn(motion, 'refreshMotionLayout');
    await wrapper.get('.faq-item summary').trigger('click');
    expect(refresh).toHaveBeenCalled();
  });
});
