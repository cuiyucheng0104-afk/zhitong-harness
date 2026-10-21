/**
 * 平滑滚动（00 章 §5.3）：Lenis 实例只由 HomePage 创建、离开首页时销毁（06 章 §9.1）。
 * `scrollToSection` 是全站唯一的锚点定位入口（01 章 §14.5 返回 Promise）。
 */
import type Lenis from 'lenis';
import type { Motion } from './motion';
import { prefersReducedMotion } from './motion';

let lenis: Lenis | null = null;
let detach: (() => void) | null = null;
let locks = 0;

/** Lenis 参数（00 章 §5.3），导出供测试断言。 */
export const LENIS_OPTIONS = {
  lerp: 0.085,
  wheelMultiplier: 0.9,
  smoothWheel: true,
  syncTouch: false,
  anchors: false,
  autoRaf: false,
} as const;

/** 锚点滚动的时长与缓动（00 章 §5.3）。 */
export const SCROLL_DURATION = 1.1;
export const scrollEasing = (t: number) => 1 - Math.pow(1 - t, 4);

/**
 * 创建 Lenis 并与 ScrollTrigger 同步；减少动效时不创建。
 * @param motion - `loadMotion()` 的结果。
 * @returns Lenis 实例；未创建时为 null。重复调用返回同一实例。
 */
export function createSmoothScroll(motion: Motion): Lenis | null {
  if (lenis) return lenis;
  if (prefersReducedMotion()) return null;
  const { gsap, ScrollTrigger, Lenis: LenisCtor } = motion;
  const instance = new LenisCtor({ ...LENIS_OPTIONS });
  const update = () => ScrollTrigger.update();
  const raf = (time: number) => instance.raf(time * 1000);
  instance.on('scroll', update);
  gsap.ticker.add(raf);
  gsap.ticker.lagSmoothing(0);
  lenis = instance;
  if (locks > 0) instance.stop();
  detach = () => {
    gsap.ticker.remove(raf);
    gsap.ticker.lagSmoothing(500, 33);
    instance.destroy();
  };
  return instance;
}

/** 当前 Lenis 实例（文档页、减少动效、未加载时为 null）。 */
export function getLenis(): Lenis | null {
  return lenis;
}

/** 销毁 Lenis（HomePage 卸载时调用，01 章 §13）。 */
export function destroySmoothScroll() {
  detach?.();
  detach = null;
  lenis = null;
}

/** 弹层、说明卡打开时暂停平滑滚动；可嵌套，与 `unlockSmoothScroll` 成对调用。 */
export function lockSmoothScroll() {
  locks += 1;
  lenis?.stop();
}

/** 解除一次 `lockSmoothScroll`；全部解除后恢复 Lenis。 */
export function unlockSmoothScroll() {
  locks = Math.max(0, locks - 1);
  if (locks === 0) lenis?.start();
}

/**
 * 顶栏视觉高度（01 章 §2）：首页导航目标都在紧凑态，取 64；文档页 72（≤ 767px 为 64）。
 * @returns 像素值。
 */
export function headerVisualHeight(): number {
  if (typeof document === 'undefined') return 64;
  const header = document.querySelector<HTMLElement>('.site-header');
  const mobile = window.matchMedia?.('(max-width: 767px)').matches ?? false;
  if (header?.dataset.state === 'docs') return mobile ? 64 : 72;
  return 64;
}

const nextFrame = () =>
  new Promise<void>((resolve) => {
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => resolve());
    else setTimeout(resolve, 0);
  });

/**
 * 滚到某个元素（偏移 = 顶栏视觉高度 + 24px），可选聚焦，并把 `#id` 写进地址栏。
 * @param id - 目标元素 id。
 * @param focus - 是否聚焦目标（`preventScroll`）。
 * @param instant - 直接定位，不做长滚动（跨页进入、跳到正文时用）。
 * @returns 滚动完成时 resolve；目标不存在时立即 resolve。
 */
export function scrollToSection(id: string, focus = true, instant = false): Promise<void> {
  const node = document.getElementById(id);
  if (!node) return Promise.resolve();
  const offset = headerVisualHeight() + 24;
  const top = Math.max(0, node.getBoundingClientRect().top + window.scrollY - offset);
  history.replaceState(history.state, '', `#${id}`);
  const finish = () => {
    if (focus) node.focus({ preventScroll: true });
  };
  if (lenis && !instant && !prefersReducedMotion()) {
    const instance = lenis;
    return new Promise<void>((resolve) => {
      instance.scrollTo(top, {
        duration: SCROLL_DURATION,
        easing: scrollEasing,
        force: true,
        onComplete: () => {
          finish();
          resolve();
        },
      });
    });
  }
  if (lenis) lenis.scrollTo(top, { immediate: true, force: true });
  else window.scrollTo({ top, behavior: 'instant' });
  finish();
  return nextFrame();
}

/**
 * 回到页顶（页脚“回到顶部”，05 章 §5.5）：Lenis 1.2s；否则直接定位；完成后聚焦 #main。
 * @returns 完成时 resolve。
 */
export function scrollToTop(): Promise<void> {
  const main = () => document.getElementById('main')?.focus({ preventScroll: true });
  if (lenis && !prefersReducedMotion()) {
    const instance = lenis;
    return new Promise<void>((resolve) => {
      instance.scrollTo(0, {
        duration: 1.2,
        easing: scrollEasing,
        force: true,
        onComplete: () => {
          main();
          resolve();
        },
      });
    });
  }
  window.scrollTo({ top: 0, behavior: 'instant' });
  main();
  return nextFrame();
}
