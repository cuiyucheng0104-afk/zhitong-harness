/**
 * 使用流程的钉住、推进与吸附（05 章 §1.5）。
 *
 * - 在 `gsap.matchMedia()` 的钉住条件（`(min-width: 1024px) and (min-height: 580px)`，未减少动效）内创建；
 *   条件不满足时自动还原（移除 `.wf--pinned`、回到纵向时间线）。
 * - 钉住区间 = `round(3.2 × innerHeight)`；时间线 3.9 s：每段先停 0.3、再移 0.9，标签 s1–s4 在 0 / 1.2 / 2.4 / 3.6。
 * - 吸附由 Lenis 驱动（不用 ScrollTrigger 的 snap）：滚动停止 160 ms、|velocity| < 0.1、位于钉住区间内时，
 *   按方向与比例阈值（向下 0.12、向上 0.88）吸到相邻标签。
 * - 纵向时间线：竖轨进度线 `scaleY 0 → 1`（`top 65%` → `bottom 65%`，`scrub: SCRUB.soft`），标记在进度线经过时切为“已过”。
 */
import type { Motion } from '../../../lib/motion';
import { getLenis } from '../../../lib/smooth-scroll';
import { DUR, EASE, SCRUB } from '../../../lib/motion-tokens';

/** 标签 s1–s4 的时间线时刻（秒）与总长。 */
export const WF_LABELS = [0, 1.2, 2.4, 3.6] as const;
export const WF_TOTAL = 3.9;
/** 钉住区间与视口高度之比。 */
export const WF_PIN_RATIO = 3.2;
export const PIN_QUERY =
  '(min-width: 1024px) and (min-height: 580px) and (prefers-reduced-motion: no-preference)';
export const STACK_QUERY = '(max-width: 1023px), (max-height: 579px)';

/**
 * 离时间线时刻最近的标签序号（0 起）。
 * @param t - 时间线时刻。
 * @returns 0..3。
 */
export function nearestLabelIndex(t: number): number {
  let best = 0;
  WF_LABELS.forEach((l, i) => {
    if (Math.abs(t - l) < Math.abs(t - WF_LABELS[best]!)) best = i;
  });
  return best;
}

/**
 * 各标签的滚动位置：`start + label / 3.9 × (end − start)`。
 * @param start - 钉住起点。
 * @param end - 钉住终点。
 * @returns 4 个滚动位置。
 */
export function labelPositions(start: number, end: number): number[] {
  return WF_LABELS.map((l) => start + (l / WF_TOTAL) * (end - start));
}

/**
 * 吸附目标（纯函数）：取当前位置所在的两标签位置 a < b，p = (cur − a)/(b − a)；
 * 向下滚动 p ≥ 0.12 吸到 b，否则回 a；向上滚动 p ≤ 0.88 吸到 a，否则回 b。最后一个标签之后以钉住终点为 b。
 * @param cur - 当前滚动位置。
 * @param positions - 标签位置（升序）。
 * @param end - 钉住终点。
 * @param dir - 最近一次滚动方向（1 向下，−1 向上）。
 * @returns 目标位置。
 */
export function snapTarget(
  cur: number,
  positions: readonly number[],
  end: number,
  dir: 1 | -1,
): number {
  const stops = [...positions, end];
  let k = 0;
  while (k < stops.length - 2 && cur >= stops[k + 1]!) k++;
  const a = stops[k]!;
  const b = stops[k + 1]!;
  if (b <= a) return a;
  const p = (cur - a) / (b - a);
  if (dir > 0) return p >= 0.12 ? b : a;
  return p <= 0.88 ? a : b;
}

/** 吸附滚动的时长：`clamp(0.35, |Δ| / innerHeight × 0.9, 0.8)`。 */
export function snapDuration(delta: number, viewport: number): number {
  return Math.min(0.8, Math.max(0.35, (Math.abs(delta) / viewport) * 0.9));
}

const snapEasing = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

export interface PinElements {
  section: HTMLElement;
  pin: HTMLElement;
  track: HTMLElement;
  panels: HTMLElement[];
  progress: SVGPathElement | null;
  baseline: SVGPathElement | null;
  stepper: HTMLElement | null;
  /** 纵向时间线。 */
  list: HTMLElement;
  rail: HTMLElement | null;
  nodes: HTMLElement[];
}

export interface PinHandlers {
  setMode(mode: 'pinned' | 'stacked'): void;
  setActive(index: number): void;
  setPassed(count: number): void;
}

/**
 * 接好钉住与纵向两种模式。
 * @param motion - 动效句柄。
 * @param el - 元素。
 * @param on - 状态回调。
 * @returns `scrollToStep(i)`（点击标记、焦点进入面板）与 `destroy()`。
 */
export function useWorkflowPin(motion: Motion, el: PinElements, on: PinHandlers) {
  const { gsap, ScrollTrigger } = motion;
  let positions: number[] = [];
  let stEnd = 0;
  let pinned: ScrollTrigger | null = null;

  const mm = gsap.matchMedia(el.section);
  mm.add(
    { pinned: PIN_QUERY, stacked: STACK_QUERY, reduce: '(prefers-reduced-motion: reduce)' },
    (context) => {
      const c = context.conditions as { pinned: boolean; stacked: boolean; reduce: boolean };
      if (c.reduce) {
        on.setMode('stacked');
        return;
      }
      if (c.pinned) return setupPinned();
      return setupStacked();
    },
  );

  function setupPinned() {
    el.section.classList.add('wf--pinned');
    on.setMode('pinned');
    const { panels, track } = el;
    const stepX = (i: number) => i * (panels[0]!.offsetWidth + 48);
    // 当前步骤取平滑后的时间线时刻（与画面一致）：scrub 追赶期间 ScrollTrigger 的 onUpdate 不再触发，所以挂在时间线自身的 onUpdate 上。
    const tl = gsap.timeline({
      defaults: { ease: EASE.inOut },
      onUpdate(this: gsap.core.Timeline) {
        on.setActive(nearestLabelIndex(this.time()));
      },
    });
    tl.addLabel('s1', 0);
    for (let i = 1; i <= 3; i++) {
      const at = 0.3 + (i - 1) * 1.2;
      tl.to(track, { x: () => -stepX(i), duration: 0.9 }, at)
        .to(panels[i - 1]!, { opacity: 0.32, scale: 0.97, duration: 0.9 }, at)
        .fromTo(
          panels[i]!,
          { opacity: 0.32, scale: 0.97 },
          { opacity: 1, scale: 1, duration: 0.9 },
          at,
        );
      if (el.progress)
        tl.fromTo(
          el.progress,
          { drawSVG: `0% ${((i - 1) / 3) * 100}%` },
          { drawSVG: `0% ${(i / 3) * 100}%`, duration: 0.9, ease: EASE.linear },
          at,
        );
      tl.addLabel(`s${i + 1}`, at + 0.9);
    }
    tl.to({}, { duration: 0.3 });
    if (el.progress) gsap.set(el.progress, { drawSVG: '0% 0%' });

    pinned = ScrollTrigger.create({
      trigger: el.pin,
      start: 'top top',
      end: () => `+=${Math.round(innerHeight * WF_PIN_RATIO)}`,
      pin: true,
      scrub: SCRUB.damp,
      anticipatePin: 1,
      invalidateOnRefresh: true,
      animation: tl,
      onRefresh: (self) => {
        positions = labelPositions(self.start, self.end);
        stEnd = self.end;
      },
    });
    positions = labelPositions(pinned.start, pinned.end);
    stEnd = pinned.end;

    // 步骤条入场：整体 block，底线 DrawSVG 0% → 100%。
    if (el.stepper)
      gsap.from(el.stepper, {
        y: 24,
        opacity: 0,
        duration: DUR.base,
        ease: EASE.out,
        scrollTrigger: { trigger: el.pin, start: 'top 85%', once: true },
      });
    if (el.baseline)
      gsap.fromTo(
        el.baseline,
        { drawSVG: '0% 0%' },
        {
          drawSVG: '0% 100%',
          duration: DUR.long,
          ease: EASE.out,
          scrollTrigger: { trigger: el.pin, start: 'top 85%', once: true },
        },
      );

    let lastY = window.scrollY;
    let dir: 1 | -1 = 1;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const snap = () => {
      const lenis = getLenis();
      if (!lenis || !pinned) return;
      if (Math.abs(lenis.velocity) >= 0.1) return;
      const cur = lenis.scroll;
      if (cur < pinned.start || cur > pinned.end) return;
      const target = snapTarget(cur, positions, stEnd, dir);
      if (Math.abs(target - cur) < 1) return;
      lenis.scrollTo(target, {
        duration: snapDuration(target - cur, innerHeight),
        easing: snapEasing,
      });
    };
    const onScroll = () => {
      const y = window.scrollY;
      if (y !== lastY) dir = y > lastY ? 1 : -1;
      lastY = y;
      clearTimeout(timer);
      timer = setTimeout(snap, 160);
    };
    window.addEventListener('scroll', onScroll, { passive: true });

    return () => {
      clearTimeout(timer);
      window.removeEventListener('scroll', onScroll);
      pinned = null;
      el.section.classList.remove('wf--pinned');
      on.setMode('stacked');
      on.setActive(0);
    };
  }

  function setupStacked() {
    on.setMode('stacked');
    if (el.rail) {
      const centers = () => {
        const box = el.list.getBoundingClientRect();
        const h = box.height || 1;
        return el.nodes.map((n) => {
          const r = n.getBoundingClientRect();
          return (r.top + r.height / 2 - box.top) / h;
        });
      };
      gsap.fromTo(
        el.rail,
        { scaleY: 0 },
        {
          scaleY: 1,
          ease: 'none',
          // 用补间自身进度（scrub 平滑后），标记与进度线同步切为“已过”。
          onUpdate(this: gsap.core.Tween) {
            const p = this.progress();
            on.setPassed(centers().filter((c) => c <= p).length);
          },
          scrollTrigger: {
            trigger: el.list,
            start: 'top 65%',
            end: 'bottom 65%',
            scrub: SCRUB.soft,
          },
        },
      );
    }
    for (const panel of el.panels) {
      const text = panel.querySelector('.wf-text');
      const win = panel.querySelector('.wf-window');
      const trigger = { trigger: panel, start: 'top 85%', once: true };
      if (text)
        gsap.from(text, {
          y: 24,
          opacity: 0,
          duration: DUR.base,
          ease: EASE.out,
          scrollTrigger: trigger,
        });
      if (win)
        gsap.from(win, {
          y: 24,
          opacity: 0,
          duration: DUR.base,
          ease: EASE.out,
          delay: 0.08,
          scrollTrigger: trigger,
        });
    }
    return () => on.setPassed(0);
  }

  /** 滚到第 i 步（0 起）的标签位置；不在钉住模式时什么也不做。 */
  function scrollToStep(i: number, duration = 1.0) {
    if (!pinned) return;
    const target = positions[i];
    if (target === undefined) return;
    const lenis = getLenis();
    if (lenis) lenis.scrollTo(target, { duration, force: true });
    else window.scrollTo({ top: target, behavior: 'instant' });
  }

  return {
    scrollToStep,
    isPinned: () => pinned !== null,
    destroy: () => mm.revert(),
  };
}
