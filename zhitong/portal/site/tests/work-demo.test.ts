import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { describe, expect, it } from 'vitest';
import WorkDemo from '../src/components/WorkDemo.vue';

describe('工作示例组件', () => {
  it('查看金额来源显示原表位置、公式并保留人工确认标记', async () => {
    const wrapper = mount(WorkDemo, { attachTo: document.body });
    await wrapper.get('.amount-button').trigger('click');
    await nextTick();
    const source = wrapper.get('#source-dialog');
    expect((source.element as HTMLDialogElement).open).toBe(true);
    expect(source.text()).toContain('送审计价表.xlsx');
    expect(source.text()).toContain('土建工程 / F20');
    expect(source.text()).toContain('57,000.00');
    expect(source.text()).toContain('3.48%');
    expect(source.text()).toContain('需人工确认');
  });

  it('场景切换清空上一次演示决定，CAD位置与文字对应', async () => {
    const wrapper = mount(WorkDemo, { attachTo: document.body });
    await wrapper.get('#tab-review').trigger('click');
    const review = wrapper.get('#scene-review');
    const buttons = review.findAll('.review-actions button');
    await buttons[1]!.trigger('click');
    expect(review.text()).toContain('已标记误报');
    await review.get('.decision-result button').trigger('click');
    await review.get('.review-actions button').trigger('click');
    expect(review.text()).toContain('已确认异常');
    await wrapper.get('#tab-cad').trigger('click');
    await wrapper.get('[data-room="office"]').trigger('click');
    expect(wrapper.get('[data-room-shape="office"]').classes()).toContain('selected');
    expect(wrapper.get('#room-status').text()).toBe('已定位：办公室');
    await wrapper.get('#tab-review').trigger('click');
    expect(review.find('.decision-result').exists()).toBe(false);
    expect(review.get('.review-actions').isVisible()).toBe(true);
  });
});
