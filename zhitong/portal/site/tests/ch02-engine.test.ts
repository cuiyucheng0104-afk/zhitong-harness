/** 02 章时间线引擎与轮播接线（AC-02-05、AC-02-12/13 顺序、AC-02-23、§2.6 收起规则、§2.7 热区）。 */
import { describe, expect, it } from 'vitest';
import { SCENES } from '../src/data/demo';
import {
  checkViewAt,
  collapsedCount,
  compileScene,
  composeChars,
  principleAt,
  toolPhase,
  visibleHotspots,
} from '../src/components/demo/engine';
import { createAutoplay } from '../src/composables/useAutoplay';

const [check, review, cad] = SCENES as [typeof SCENES[0], typeof SCENES[0], typeof SCENES[0]];

describe('AC-02-12 / 13 工具原名顺序', () => {
  it('场景一', () => {
    const c = compileScene(check);
    expect(c.tools.map((t) => `${t.spec.name}${t.spec.times ? `×${t.spec.times}` : ''}`)).toEqual([
      'read', 'tos_pull×2', 'probe.py probe', 'reconcile.py run', 'python', 'write', 'tos_push×3',
    ]);
    expect(c.tools.map((t) => t.spec.elapsed)).toEqual(['0.1 s', '1.6 s', '0.8 s', '5.9 s', '0.3 s', '0.1 s', '2.1 s']);
  });
  it('场景二（含 ask_user_question）', () => {
    const c = compileScene(review);
    expect(c.tools.map((t) => t.spec.name)).toEqual(['read', 'tos_pull', 'tk.py detect', 'tk.py review', 'write']);
    expect(c.ask?.spec.tool).toBe('ask_user_question');
    expect(c.ask?.submitted).toBe(15.4);
  });
  it('场景三', () => {
    expect(compileScene(cad).tools.map((t) => t.spec.name)).toEqual([
      'tos_pull', 'cad_open', 'cad_set_unit', 'cad_frames', 'cad_rooms', 'cad_render', 'read_image', 'cad_render', 'read_image', 'write',
    ]);
  });
  it('AC-02-17 分支：判为误报时工具④参数含 --state dismissed，段落 5 逐字', () => {
    const c = compileScene(review, 'dismissed');
    expect(c.tools[3]!.spec.args).toContain('--state dismissed');
    expect(c.tools[3]!.spec.detail).toBe('已追加 1 条 · 判为误报 1 · 待复核 289');
    const last = c.says.at(-1)!.segs.map((s) => (typeof s === 'string' ? s : s.t)).join('');
    expect(last).toBe('已记录为误报，写入 复核.jsonl。重点还剩 3 条待复核。');
    expect(compileScene(review, 'pending').tools[4]!.spec.detail).toBe('未复核 290 条（重点 4 条）');
  });
});

describe('§2.6 时间线状态', () => {
  it('工具条 进行中 → 完成', () => {
    const t = compileScene(check).tools[3]!;
    expect(toolPhase(t, 2.6)).toBe('hidden');
    expect(toolPhase(t, 3.0)).toBe('running');
    expect(toolPhase(t, 3.8)).toBe('done');
  });
  it('输入框匀速逐字', () => {
    const c = compileScene(check).compose;
    expect(composeChars(c, 0)).toBe(0);
    expect(composeChars(c, 0.36)).toBe(6);
    expect(composeChars(c, 0.72)).toBe(12);
  });
  it('第 5 个工具条开始时最早的 (n − 3) 条收起；手机只留当前一步', () => {
    expect(collapsedCount(4)).toBe(0);
    expect(collapsedCount(5)).toBe(2);
    expect(collapsedCount(7)).toBe(4);
    expect(collapsedCount(3, true)).toBe(2);
  });
  it('核对预览视图随时间线切换', () => {
    const cues = compileScene(check).cues;
    expect([1, 2.2, 4, 6.5, 9, 12].map((t) => checkViewAt(cues, t))).toEqual(['empty', 'files', 'summary', 'chapters', 'rows', 'summary']);
  });
  it('热区：到达 hotspots 步骤后显示；暂停时只显示已经出现的', () => {
    const c = compileScene(check);
    expect(visibleHotspots(c, 14.6, false)).toEqual(['reduction', 'sheet-tabs']);
    expect(visibleHotspots(c, 3.0, true)).toEqual([]);
    expect(visibleHotspots(c, 5, true)).toEqual(['reduction', 'sheet-tabs']);
    expect(visibleHotspots(c, 5, false)).toEqual([]);
  });
});

describe('AC-02-23 原则条', () => {
  it('场景一 3.0 s 脚本、5.0 s 对话、16.0 s（停留）复核', () => {
    expect(principleAt(check, 3.0)).toBe('script');
    expect(principleAt(check, 5.0)).toBe('dialog');
    expect(principleAt(check, 16.0)).toBe('review');
  });
  it('场景一段落 4（状态与告警）标为 review；场景二提问卡为 review', () => {
    expect(principleAt(check, 11)).toBe('review');
    expect(principleAt(review, 13)).toBe('review');
  });
});

describe('AC-02-05 轮播接线（与 WorkDemo 相同参数）', () => {
  it('1 → 2 → 3 → 1 顺序推进，一轮 60.20 s，3 轮后停在场景 1 终态（done）', () => {
    const ap = createAutoplay({ scenes: SCENES.map((s) => ({ duration: s.end, hold: s.hold })), loopLimit: 3 });
    const order: number[] = [ap.index.value];
    let elapsed = 0;
    const dt = 0.02;
    let firstLoop = 0;
    for (let i = 0; i < 20000 && ap.state.value !== 'done'; i++) {
      ap.tick(dt);
      elapsed += dt;
      if (order.at(-1) !== ap.index.value) order.push(ap.index.value);
      if (!firstLoop && ap.loops.value === 1) firstLoop = elapsed;
    }
    expect(Math.abs(firstLoop - 60.2)).toBeLessThan(0.5);
    expect(order.slice(0, 4)).toEqual([0, 1, 2, 0]);
    expect(ap.state.value).toBe('done');
    expect(ap.index.value).toBe(0);
    expect(elapsed).toBeGreaterThan(3 * 60.2 - 0.5);
    expect(elapsed).toBeLessThan(3 * 60.2 + 0.5);
  });
});
