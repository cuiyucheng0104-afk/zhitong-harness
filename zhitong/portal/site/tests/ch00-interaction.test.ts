import { mount } from '@vue/test-utils';
import { defineComponent, h, nextTick, ref } from 'vue';
import { describe, expect, it } from 'vitest';
import { magneticOffset, resolveMagnetic } from '../src/composables/useMagnetic';
import { indicatorBox, useHoverIndicator } from '../src/composables/useHoverIndicator';
import { useScrollSpy } from '../src/composables/useScrollSpy';
import { expoOut } from '../src/composables/useCountUp';

describe('00 §6.1 磁吸', () => {
  const rect = { left: 100, top: 100, width: 100, height: 40 };
  it('默认参数与文字链接档', () => {
    expect(resolveMagnetic(undefined)).toEqual({ radius: 24, strength: 0.32, labelStrength: 0.16, max: 10 });
    expect(resolveMagnetic('link')!.max).toBe(6);
    expect(resolveMagnetic(false)).toBeNull();
  });
  it('感应区外扩 24px，偏移 = (dx, dy) × strength，封顶 max', () => {
    const opts = resolveMagnetic('button')!;
    expect(magneticOffset(rect, 150 + 10, 120, opts)).toMatchObject({ x: 3.2, y: 0 });
    expect(magneticOffset(rect, 223, 120, opts)!.x).toBe(10);
    expect(magneticOffset(rect, 225, 120, opts)).toBeNull();
    expect(magneticOffset(rect, 150, 120 + 30, resolveMagnetic('link')!)!.y).toBe(6);
    expect(magneticOffset(rect, 160, 120, opts)!.lx).toBeCloseTo(1.6);
  });
});

describe('00 §6.2 滑块吸附', () => {
  it('indicatorBox 返回相对组容器的位置，没有当前项时淡出', () => {
    const c = { left: 50, top: 10 } as DOMRect;
    expect(indicatorBox({ left: 80, top: 14, width: 60, height: 36 } as DOMRect, c)).toEqual({
      x: 30,
      y: 4,
      w: 60,
      h: 36,
      o: 1,
    });
    expect(indicatorBox(null, c).o).toBe(0);
  });

  it('CSS 驱动：悬停写 --ind-x/--ind-w/--ind-o，离开回到当前项', async () => {
    const Comp = defineComponent({
      setup() {
        const container = ref<HTMLElement | null>(null);
        const indicator = ref<HTMLElement | null>(null);
        const active = ref<HTMLElement | null>(null);
        useHoverIndicator({ container, indicator, driver: 'css', active });
        return () =>
          h('nav', { ref: container }, [
            h('span', { ref: indicator, class: 'ind' }),
            h('a', { 'data-indicator-item': '', id: 'a' }, 'A'),
            h('a', { 'data-indicator-item': '', id: 'b' }, 'B'),
          ]);
      },
    });
    const wrapper = mount(Comp, { attachTo: document.body });
    const nav = wrapper.get('nav').element as HTMLElement;
    const b = wrapper.get('#b').element as HTMLElement;
    nav.getBoundingClientRect = () => ({ left: 0, top: 0, width: 300, height: 44 }) as DOMRect;
    b.getBoundingClientRect = () => ({ left: 120, top: 4, width: 80, height: 36 }) as DOMRect;
    b.dispatchEvent(new Event('pointerover', { bubbles: true }));
    const ind = wrapper.get('.ind').element as HTMLElement;
    expect(ind.style.getPropertyValue('--ind-x')).toBe('120px');
    expect(ind.style.getPropertyValue('--ind-w')).toBe('80px');
    expect(ind.style.getPropertyValue('--ind-o')).toBe('1');
    nav.dispatchEvent(new Event('pointerleave'));
    await nextTick();
    expect(ind.style.getPropertyValue('--ind-o')).toBe('0');
    b.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
    expect(ind.style.getPropertyValue('--ind-o')).toBe('1');
  });
});

describe('01 §14.1 useScrollSpy', () => {
  it('toggle(id, false) 只在当前为 id 时清空；锁定期间不变，解锁后取实际章节', () => {
    const spy = useScrollSpy(['capabilities', 'workflow', 'trust', 'faq'] as const);
    spy.toggle('capabilities', true);
    expect(spy.active.value).toBe('capabilities');
    spy.toggle('workflow', false);
    expect(spy.active.value).toBe('capabilities');
    spy.lock('faq');
    spy.toggle('workflow', true);
    spy.toggle('capabilities', false);
    expect(spy.active.value).toBe('faq');
    spy.toggle('workflow', false);
    spy.toggle('faq', true);
    spy.unlock();
    expect(spy.active.value).toBe('faq');
    spy.toggle('faq', false);
    expect(spy.active.value).toBe('');
  });
});

describe('00 §6.7 数字滚动缓动', () => {
  it('expo.out 等价函数单调到 1', () => {
    expect(expoOut(0)).toBe(0);
    expect(expoOut(1)).toBe(1);
    expect(expoOut(0.5)).toBeGreaterThan(0.9);
  });
});
