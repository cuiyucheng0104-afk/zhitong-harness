/**
 * 能力小动画的常量与共享状态键（04 章 §7.1）。
 */
import type { InjectionKey, Ref } from 'vue';

export const ART = {
  /** 终帧停留（秒），个别动画由 kit.end 的第二个参数另行指定。 */
  hold: 2.4,
  /** 循环末尾的淡出复位。 */
  reset: 0.4,
  /** 舞台宽 ≥ 此值并排。 */
  splitMin: 488,
  /** 顺序模式舞台最大宽。 */
  sequenceMax: 330,
  /** 并排模式舞台最大宽。 */
  splitMax: 560,
  /** 指针离开后多久恢复。 */
  hoverResume: 0.6,
  /** 模拟流式文字速度（字/秒）。 */
  cps: 36,
  inViewThreshold: 0.35,
} as const;

/** 全区暂停开关（CapabilitiesSection provide，CapabilityArt inject）。 */
export const ART_PAUSED: InjectionKey<Ref<boolean>> = Symbol('art-paused');

/** 文字基准字号（SVG 单位）。 */
export const ART_FS = { text: 14, big: 22 } as const;

const WIDE = /[⺀-鿿豈-﫿＀-￯　-〿〔〕【】（），：；、。…—–＝㎡²]/u;

/**
 * 估算一段 SVG 文字的宽度（SVG 单位）。预渲染没有布局，徽标底与工具条长度按此计算；
 * 中文与全角符号按 1em，等宽字体西文 0.6em，正文西文 0.56em。
 * @param text - 文字。
 * @param mono - 是否等宽字体。
 * @param size - 字号，默认 14。
 * @returns 宽度。
 */
export function textWidth(text: string, mono = false, size: number = ART_FS.text): number {
  let w = 0;
  for (const ch of text) {
    if (WIDE.test(ch)) w += 1;
    else if (ch === ' ') w += mono ? 0.6 : 0.3;
    else w += mono ? 0.6 : 0.56;
  }
  return Math.round(w * size * 10) / 10;
}
