/**
 * 数字滚动（00 章 §6.7）：进入视口时从 from（默认 0）滚到终值，`DUR.long`、`EASE.expo`，按 format 实时格式化。
 *
 * 元素文本在预渲染时就是终值。动画期间元素文字透明（读屏仍读终值），
 * 元素内叠一个绝对定位、`aria-hidden` 的副本显示滚动值；尺寸不变，没有布局位移。
 * 减少动效时不动画，直接显示终值。
 */
import { onBeforeUnmount, type Ref } from 'vue';
import { getMotion, prefersReducedMotion } from '../lib/motion';
import { DUR } from '../lib/motion-tokens';
import { formatMoney } from '../lib/format';
import { useInView } from './useInView';

export interface CountUpOptions {
  /** 终值。 */
  to: number;
  /** 起点，默认 0。 */
  from?: number;
  /** 格式化，默认 `formatMoney`（两位小数千分位）。 */
  format?: (value: number) => string;
  /** 时长（秒），默认 `DUR.long`。 */
  duration?: number;
  /** 'inview'（默认，进入视口一次）或 'manual'（调用 play）。 */
  trigger?: 'inview' | 'manual';
  /** 进入视口阈值，默认 0.35。 */
  threshold?: number;
}

/** expo.out 的等价函数（GSAP 未加载时使用）。 */
export const expoOut = (t: number) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));

/**
 * 使用数字滚动。
 * @param target - 显示数字的元素。
 * @param options - 见 `CountUpOptions`。
 * @returns `play()` 开始（返回结束时 resolve 的 Promise）、`finish()` 立即到终值。
 */
export function useCountUp(target: Ref<HTMLElement | null | undefined>, options: CountUpOptions) {
  const format = options.format ?? ((v: number) => formatMoney(v));
  const duration = (options.duration ?? DUR.long) * 1000;
  let shadow: HTMLSpanElement | null = null;
  let frame = 0;
  let resolveRun: (() => void) | null = null;
  let played = false;

  function cleanup() {
    cancelAnimationFrame(frame);
    frame = 0;
    const el = target.value;
    shadow?.remove();
    shadow = null;
    el?.classList.remove('is-counting');
    resolveRun?.();
    resolveRun = null;
  }

  function play(): Promise<void> {
    const el = target.value;
    if (!el || prefersReducedMotion() || typeof requestAnimationFrame !== 'function') return Promise.resolve();
    cleanup();
    played = true;
    shadow = document.createElement('span');
    shadow.className = 'count-up-shadow';
    shadow.setAttribute('aria-hidden', 'true');
    shadow.style.color = getComputedStyle(el).color;
    const from = options.from ?? 0;
    shadow.textContent = format(from);
    el.classList.add('is-counting');
    el.append(shadow);
    const ease = getMotion()?.gsap.parseEase('expo.out') ?? expoOut;
    const start = performance.now();
    return new Promise<void>((resolve) => {
      resolveRun = resolve;
      const step = (now: number) => {
        const t = Math.min(1, (now - start) / duration);
        if (shadow) shadow.textContent = format(from + (options.to - from) * ease(t));
        if (t < 1) frame = requestAnimationFrame(step);
        else cleanup();
      };
      frame = requestAnimationFrame(step);
    });
  }

  if (options.trigger !== 'manual') {
    useInView(target, {
      threshold: options.threshold ?? 0.35,
      once: true,
      play: () => {
        if (!played) void play();
      },
    });
  }

  onBeforeUnmount(cleanup);
  return { play, finish: cleanup };
}
