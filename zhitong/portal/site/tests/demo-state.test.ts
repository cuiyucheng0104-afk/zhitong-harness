import { describe, expect, it } from 'vitest';
import { useDemoState } from '../src/composables/useDemoState';

describe('工作示例的临时状态', () => {
  it('核对合计、核减额与核减率使用同一组数据', () => {
    const state = useDemoState();
    expect(state.totals.value).toEqual({
      submitted: 1640000,
      approved: 1583000,
      reduction: 57000,
      rate: '3.48',
    });
  });

  it('确认异常后可重新选择，切换场景清除临时决定', () => {
    const state = useDemoState();
    state.selectScene('review');
    state.decide('confirmed');
    expect(state.decision.value).toBe('confirmed');
    state.resetReview();
    expect(state.decision.value).toBeNull();
    state.decide('false-positive');
    expect(state.decision.value).toBe('false-positive');
    state.selectScene('cad');
    expect(state.decision.value).toBeNull();
    expect(state.scene.value).toBe('cad');
  });

  it('房间选择更新对应的文字位置', () => {
    const state = useDemoState();
    state.selectRoom('office');
    expect(state.room.value).toBe('office');
    expect(state.roomLabel.value).toBe('办公室');
  });

  it('不同组件实例之间不共享复核决定', () => {
    const first = useDemoState();
    const second = useDemoState();
    first.decide('confirmed');
    expect(first.decision.value).toBe('confirmed');
    expect(second.decision.value).toBeNull();
  });
});
