/**
 * AC-03-19：首次打开任一说明卡前不请求小动画块；打开“资料盘点”后只请求 inventory 一个块。
 * AC-03-11 / AC-03-18 的静态部分：小动画组件的静态 SVG 即末帧。
 */
import { describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import RolesSection from '../src/components/RolesSection.vue';
import { MICROS } from '../src/components/roles/micro';
import MicroReview from '../src/components/roles/micro/MicroReview.vue';
import MicroReconcile from '../src/components/roles/micro/MicroReconcile.vue';
import MicroDraft from '../src/components/roles/micro/MicroDraft.vue';
import MicroBenchmark from '../src/components/roles/micro/MicroBenchmark.vue';
import MicroExtract from '../src/components/roles/micro/MicroExtract.vue';
import MicroCodes from '../src/components/roles/micro/MicroCodes.vue';
import type { MicroKind } from '../src/data/roles';
import { mountAt } from './helpers';

describe('AC-03-19 小动画按需加载', () => {
  it('打开前没有请求；打开资料盘点只请求 inventory；加载后显示静态末帧', async () => {
    const spies = Object.fromEntries(
      (Object.keys(MICROS) as MicroKind[]).map((k) => [k, vi.spyOn(MICROS, k)]),
    ) as Record<MicroKind, ReturnType<typeof vi.spyOn>>;
    const { wrapper } = await mountAt('/', RolesSection);
    await flushPromises();
    for (const s of Object.values(spies)) expect(s).not.toHaveBeenCalled();
    expect(wrapper.find('.task-micro svg').exists()).toBe(false);
    await wrapper.get('[data-task="engineer-project"]').trigger('click');
    await flushPromises();
    await new Promise((r) => setTimeout(r, 50));
    await flushPromises();
    const called = (Object.keys(spies) as MicroKind[]).filter((k) => spies[k].mock.calls.length > 0);
    expect(called).toEqual(['inventory']);
    const svg = wrapper.get('.task-micro svg');
    expect(svg.attributes('viewBox')).toBe('0 0 160 96');
    expect(svg.attributes('aria-hidden')).toBe('true');
    expect(wrapper.get('#role-task-popover .zt-popover-art').attributes('aria-hidden')).toBe('true');
  });
});

describe('§1.5.7 小动画静态末帧', () => {
  it('review 末帧有印章“已确认”与“复核.jsonl +1”', () => {
    const w = mount(MicroReview);
    expect(w.text()).toContain('已确认');
    expect(w.text()).toContain('复核.jsonl +1');
  });
  it('AC-03-18：金额与比例', () => {
    expect(mount(MicroReconcile).text()).toContain('906,692.96');
    expect(mount(MicroReconcile).text()).toContain('2.97%');
    expect(mount(MicroDraft).text()).toContain('30,530,406.80');
    expect(mount(MicroBenchmark).text()).toContain('1,592.67');
    expect(mount(MicroExtract).text()).toContain('15,200.00');
  });
  it('codes 行 2 的编码保持 Z011201001（不自动改码）', () => {
    expect(mount(MicroCodes).text()).toContain('Z011201001');
  });
});
