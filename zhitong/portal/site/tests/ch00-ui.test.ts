import { mount, flushPromises } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import ZtStatus from '../src/components/ui/ZtStatus.vue';
import ZtToolCall from '../src/components/ui/ZtToolCall.vue';
import ZtStream, { streamUnits } from '../src/components/ui/ZtStream.vue';
import ZtPopover from '../src/components/ui/ZtPopover.vue';
import { STATUS_LABEL } from '../src/components/ui/types';

describe('00 §8.3 ZtStatus', () => {
  it('中文名完整', () => {
    expect(STATUS_LABEL).toEqual({
      ok: '完成',
      partial: '部分完成',
      empty: '无结果',
      insufficient: '资料不足',
      manual: '需人工确认',
      error: '错误',
      warn: '警告',
      info: '提示',
    });
  });
  it('状态 + 需人工确认 + 告警计数 + 告警原文', () => {
    const w = mount(ZtStatus, {
      props: { value: 'ok', manual: true, counts: { warn: 1, info: 2 }, lines: [{ level: 'warn', text: '第 46 行重复计取' }] },
    });
    expect(w.text()).toContain('完成');
    expect(w.text()).toContain('需人工确认');
    expect(w.text()).toContain('警告 1');
    expect(w.text()).toContain('提示 2');
    expect(w.get('.zt-status-lines').text()).toContain('第 46 行重复计取');
    expect(mount(ZtStatus, { props: { value: 'insufficient', size: 'sm' } }).classes()).toContain('is-sm');
  });
});

describe('00 §8.3 ZtToolCall', () => {
  const tool = { label: '运行核对', name: 'reconcile.py run', args: '--basis auto', elapsed: '5.9 s', detail: '1,284 行', times: 2 };
  it('中文标签在前、等宽原名在后；进行中无耗时，完成后显示耗时与结果', () => {
    const running = mount(ZtToolCall, { props: { tool, state: 'running' } });
    const text = running.text();
    expect(text.indexOf('运行核对')).toBeLessThan(text.indexOf('reconcile.py run'));
    expect(running.find('.zt-tool-spinner').exists()).toBe(true);
    expect(text).not.toContain('5.9 s');
    expect(text).toContain('×2');
    const done = mount(ZtToolCall, { props: { tool } });
    expect(done.text()).toContain('5.9 s');
    expect(done.text()).toContain('1,284 行');
    expect(done.find('.zt-tool-check').exists()).toBe(true);
  });
});

describe('00 §6.9 ZtStream', () => {
  it('逐字计时：中文标点后停 0.12s，mono 片段计 1 字', () => {
    const { units, duration } = streamUnits(['核对，完成', { t: '906,692.96', mono: true }], 36);
    expect(units).toHaveLength(6);
    expect(units[2]!.at).toBeCloseTo(2 / 36);
    expect(units[3]!.at).toBeCloseTo(3 / 36 + 0.12);
    expect(duration).toBeCloseTo(6 / 36 + 0.12);
  });
  it('预渲染为终态；受控 time 显示对应进度，播放中可视文本对读屏隐藏', async () => {
    const w = mount(ZtStream, { props: { segs: ['核减额 ', { t: '906,692.96', mono: true }], cps: 36 } });
    expect(w.text()).toBe('核减额 906,692.96');
    expect(w.attributes('aria-live')).toBe('off');
    await w.setProps({ time: 2 / 36 + 0.001 });
    expect(w.get('.zt-stream-visible').text()).toBe('核减额');
    expect(w.get('.zt-stream-visible').attributes('aria-hidden')).toBe('true');
    expect(w.classes()).toContain('is-typing');
    await w.setProps({ time: 10 });
    expect(w.emitted('done')).toHaveLength(1);
    expect(w.get('.zt-stream-visible').attributes('aria-hidden')).toBeUndefined();
  });
});

describe('00 §6.4 ZtPopover', () => {
  it('打开时维护触发元素 aria-expanded/aria-controls，Esc 关闭并归还焦点', async () => {
    const trigger = document.createElement('button');
    document.body.append(trigger);
    const w = mount(ZtPopover, {
      attachTo: document.body,
      props: { id: 'term-popover', title: '配置包', lead: '服务方交付的压缩文件。', rows: [{ label: '需要什么', text: '向服务方获取。' }] },
    });
    const el = w.get('#term-popover').element as HTMLElement;
    expect(el.getAttribute('role')).toBe('dialog');
    expect(el.getAttribute('aria-labelledby')).toBe('term-popover-title');
    trigger.focus();
    await (w.vm as unknown as { show: (t: HTMLElement) => Promise<void> }).show(trigger);
    await flushPromises();
    expect(trigger.getAttribute('aria-expanded')).toBe('true');
    expect(trigger.getAttribute('aria-controls')).toBe('term-popover');
    expect(el.hidden).toBe(false);
    expect(w.text()).toContain('需要什么');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await flushPromises();
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(trigger);
    w.unmount();
    trigger.remove();
  });
});
