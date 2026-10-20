import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { describe, expect, it } from 'vitest';
import BaseDialog from '../src/components/BaseDialog.vue';

describe('通用说明弹层', () => {
  it('只在打开时进入模态，并在关闭后恢复触发按钮焦点', async () => {
    const trigger = document.createElement('button');
    document.body.append(trigger);
    trigger.focus();
    const wrapper = mount(BaseDialog, {
      props: { modelValue: false, labelledby: 'dialog-title' },
      attachTo: document.body,
      slots: { default: '<h2 id="dialog-title">说明</h2><button>关闭</button>' },
    });
    const dialog = wrapper.get('dialog').element as HTMLDialogElement;
    expect(dialog.open).toBe(false);
    await wrapper.setProps({ modelValue: true });
    expect(dialog.open).toBe(true);
    expect(document.body.classList.contains('modal-open')).toBe(true);
    await wrapper.setProps({ modelValue: false });
    await nextTick();
    expect(dialog.open).toBe(false);
    expect(document.activeElement).toBe(trigger);
    expect(document.body.classList.contains('modal-open')).toBe(false);
    trigger.remove();
  });

  it('Esc 取消通知父组件关闭', async () => {
    const wrapper = mount(BaseDialog, {
      props: { modelValue: true, labelledby: 'dialog-title' },
      attachTo: document.body,
    });
    await wrapper.get('dialog').trigger('cancel');
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false]);
  });

  it('卸载已打开的弹层会解除页面滚动锁定', () => {
    const wrapper = mount(BaseDialog, {
      props: { modelValue: true, labelledby: 'title' },
      attachTo: document.body,
    });
    expect(document.body.classList.contains('modal-open')).toBe(true);
    wrapper.unmount();
    expect(document.body.classList.contains('modal-open')).toBe(false);
  });
});
