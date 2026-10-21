import { describe, expect, it, vi } from 'vitest';
import { createAutoplay } from '../src/composables/useAutoplay';

const scenes = [
  { duration: 14.6, hold: 3.2 },
  { duration: 18.15, hold: 3.2 },
  { duration: 17.85, hold: 3.2 },
];

describe('00 §6.3 useAutoplay 状态机', () => {
  it('progress = (时间线进度 × 时长 + 已停留) / 总时长，停留结束进入下一场景', () => {
    const onScene = vi.fn();
    const a = createAutoplay({ scenes, onScene });
    a.tick(8.9);
    expect(a.progress.value).toBeCloseTo(8.9 / 17.8, 5);
    a.tick(14.6 - 8.9 + 3.2 - 0.01);
    expect(a.index.value).toBe(0);
    a.tick(0.02);
    expect(a.index.value).toBe(1);
    expect(onScene).toHaveBeenLastCalledWith(1, { user: false });
  });

  it('暂停 = 时钟停住；恢复从原位置继续，不重播', () => {
    const a = createAutoplay({ scenes });
    a.tick(3);
    a.pause('hover');
    expect(a.playing.value).toBe(false);
    a.tick(5);
    expect(a.elapsed.value).toBe(3);
    a.resume('hover');
    a.tick(1);
    expect(a.elapsed.value).toBe(4);
  });

  it('多个暂停原因同时存在时，全部解除才继续', () => {
    const a = createAutoplay({ scenes });
    a.pause('hover');
    a.pause('offscreen');
    a.resume('hover');
    expect(a.playing.value).toBe(false);
    expect(a.state.value).toBe('paused');
    a.resume('offscreen');
    expect(a.playing.value).toBe(true);
  });

  it('绑定的时间线定位到 min(elapsed, duration)', () => {
    const a = createAutoplay({ scenes });
    const time = vi.fn();
    a.setTimeline({ time });
    a.tick(2);
    expect(time).toHaveBeenLastCalledWith(2);
    a.tick(14);
    expect(time).toHaveBeenLastCalledWith(14.6);
  });

  it('goTo(i, { user }) 进入手动模式；toggle 置顶暂停与恢复', () => {
    const a = createAutoplay({ scenes });
    a.goTo(2, { user: true });
    expect(a.index.value).toBe(2);
    expect(a.state.value).toBe('manual');
    a.toggle();
    expect(a.state.value).toBe('sticky');
    a.toggle();
    expect(a.state.value).toBe('playing');
  });

  it('loopLimit 轮播完停在场景 1 终态（done），toggle 从头开始', () => {
    const a = createAutoplay({ scenes, loopLimit: 1 });
    for (let i = 0; i < 70; i++) a.tick(1);
    expect(a.state.value).toBe('done');
    expect(a.index.value).toBe(0);
    expect(a.elapsed.value).toBe(14.6);
    a.toggle();
    expect(a.state.value).toBe('playing');
    expect(a.elapsed.value).toBe(0);
  });

  it('hold: Infinity 时播完停在终态，不前进', () => {
    const a = createAutoplay({ scenes: [{ duration: 5, hold: Infinity }, { duration: 5 }] });
    a.tick(100);
    expect(a.index.value).toBe(0);
    expect(a.progress.value).toBe(1);
  });

  it('reduced 原因优先显示为 reduced 状态', () => {
    const a = createAutoplay({ scenes });
    a.pause('reduced');
    a.pause('user');
    expect(a.state.value).toBe('reduced');
  });
});
