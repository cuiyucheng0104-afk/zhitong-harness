/**
 * 使用流程示例会话的节拍排期（05 章 §1.2.1）：起点 = 上一拍结束 + gap；各类型的固有时长见下表。
 * 纯函数，供时间线构建与测试共用。
 */
import { streamUnits } from '../../ui/ZtStream.vue';
import { DUR } from '../../../lib/motion-tokens';
import type { SceneBeat } from '../../../data/workflow';

/** 流式文字速度（字/秒）与标点停顿（秒），05 章 §1.2.1。 */
export const WF_STREAM_CPS = 34;
export const WF_STREAM_PAUSE = 0.12;

/** 各结果卡参与 `stagger` 的行数（标题行计入）。 */
export const CARD_ROWS: Record<Extract<SceneBeat, { kind: 'card' }>['card'], number> = {
  projects: 10,
  inventory: 7,
  reconcile: 3,
  files: 3,
};

/**
 * 一拍的固有时长（秒）。
 * @param beat - 节拍。
 * @returns 时长。
 */
export function beatDuration(beat: SceneBeat): number {
  switch (beat.kind) {
    case 'drop':
      return 0.8 + DUR.short;
    case 'user':
    case 'status':
    case 'outcome':
      return DUR.short;
    case 'tool':
      return DUR.short + beat.run;
    case 'stream':
      return streamUnits([beat.text], WF_STREAM_CPS, WF_STREAM_PAUSE).duration;
    case 'card':
      return DUR.base + CARD_ROWS[beat.card] * 0.07;
    case 'ask':
      return DUR.base + 0.72;
    case 'push':
      return beat.rows.length * 0.14 + 0.18;
    case 'diff':
      return DUR.base + 0.3;
    case 'note':
      return DUR.base;
  }
}

export interface BeatSlot {
  start: number;
  duration: number;
}

/**
 * 排出一个场景每拍的起点与时长。
 * @param beats - 场景节拍。
 * @returns 每拍的排期与场景总时长。
 */
export function planScene(beats: readonly SceneBeat[]): { slots: BeatSlot[]; total: number } {
  let end = 0;
  const slots = beats.map((beat) => {
    const start = end + beat.gap;
    const duration = beatDuration(beat);
    end = start + duration;
    return { start, duration };
  });
  return { slots, total: end };
}

/**
 * 耗时文字（等宽，千分位）。
 * @param ms - 毫秒。
 * @returns 如 `3,840 ms`。
 */
export function formatMs(ms: number): string {
  return `${Math.round(ms).toLocaleString('en-US')} ms`;
}
