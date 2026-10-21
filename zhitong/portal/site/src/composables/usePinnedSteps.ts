/**
 * 钉住分步（03 章 §3）：把一个钉住区块分成 N 个离散步骤，滚动进度、吸附与页签点击三者同步。
 *
 * - 钉住条件 `PIN_QUERY` 且 `html.motion-ready`（03 章 §0 末段）；在 `gsap.matchMedia()` 条件块内创建，
 *   条件不满足或组件卸载时 revert，条件变化时保留当前 index。
 * - 吸附点 `k / (N − 1)`；步骤 = `Math.round(progress × (N − 1))`（阈值在相邻吸附点中点）。
 * - 吸附与 Lenis（AC-03-04）：Lenis 存在时 ScrollTrigger 自带吸附返回原值（不动），改由 `scrollEnd`
 *   事件算最近吸附点并调用 `lenis.scrollTo`，时长 `clamp(|Δ| / 1000, 0.2, 0.6)`、power2.inOut；
 *   Lenis 不存在时用 ScrollTrigger 自带吸附。两种方式参数等价，调用方不变。
 * - `goTo` 期间忽略 `onUpdate` 产生的中间步骤，滚动完成后恢复。
 *
 * 文件位置：按 03 章 §0 放在 `composables/usePinnedSteps.ts`（集成时由 components/roles/ 迁入）。
 */
import { onBeforeUnmount, onMounted, readonly, ref, shallowRef, type Ref } from 'vue';
import { loadMotion, type Motion } from '../lib/motion';
import { getLenis } from '../lib/smooth-scroll';

/** 钉住条件（岗位区与它解决什么共用）。 */
export const PIN_QUERY =
  '(min-width: 1024px) and (min-height: 640px) and (prefers-reduced-motion: no-preference)';

type ST = InstanceType<Motion['ScrollTrigger']>;

/** power2.inOut 的等价函数（Lenis 用）。 */
export const power2InOut = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

/**
 * 最近的吸附点。
 * @param progress - 0..1。
 * @param points - 吸附点（升序）。
 * @returns 最近的吸附点。
 */
export function nearestPoint(progress: number, points: readonly number[]): number {
  let best = points[0] ?? 0;
  for (const p of points) if (Math.abs(p - progress) < Math.abs(best - progress)) best = p;
  return best;
}

/**
 * 吸附时长（秒）：`clamp(|Δ| / 1000, 0.2, 0.6)`。
 * @param delta - 滚动距离（px）。
 * @returns 秒数。
 */
export function snapDuration(delta: number): number {
  return Math.min(0.6, Math.max(0.2, Math.abs(delta) / 1000));
}

/**
 * 步骤序号。
 * @param progress - 0..1。
 * @param steps - 步数 N。
 * @returns 0..N−1。
 */
export function stepOf(progress: number, steps: number): number {
  return Math.min(steps - 1, Math.max(0, Math.round(progress * (steps - 1))));
}

/** ScrollTrigger 的 snap 选项：Lenis 存在时原样返回（交给 `attachLenisSnap`）。 */
export function snapOption(points: readonly number[], ease = 'power2.inOut') {
  return {
    snapTo: (value: number) => (getLenis() ? value : nearestPoint(value, points)),
    duration: { min: 0.2, max: 0.6 },
    ease,
  };
}

/**
 * Lenis 下的吸附：滚动停止后滚到最近吸附点。
 * @param motion - 动效句柄。
 * @param st - 钉住触发器。
 * @param points - 吸附点。
 * @param busy - 返回 true 时跳过（如页签触发的滚动中）。
 * @returns 解除函数。
 */
export function attachLenisSnap(
  motion: Motion,
  st: ST,
  points: readonly number[],
  busy: () => boolean = () => false,
): () => void {
  const onEnd = () => {
    const lenis = getLenis();
    if (!lenis || busy() || !st.isActive) return;
    const p = nearestPoint(st.progress, points);
    const target = st.start + (st.end - st.start) * p;
    const delta = target - window.scrollY;
    if (Math.abs(delta) < 1) return;
    lenis.scrollTo(target, { duration: snapDuration(delta), easing: power2InOut, force: true });
  };
  motion.ScrollTrigger.addEventListener('scrollEnd', onEnd);
  return () => motion.ScrollTrigger.removeEventListener('scrollEnd', onEnd);
}

export type StepSource = 'scroll' | 'user' | 'refresh';

export interface PinnedStepsOptions {
  /** 被钉住的元素。 */
  stage: Ref<HTMLElement | null>;
  /** 步数 N（≥ 2）。 */
  steps: number;
  /** 默认 'top top+=64'。 */
  start?: string;
  /** 钉住长度（px），默认 () => (N − 1) × 0.5 × innerHeight。 */
  length?: () => number;
  /** 默认 { duration: { min: 0.2, max: 0.6 }, ease: 'power2.inOut' }。 */
  snap?: { duration: { min: number; max: number }; ease: string };
  /** 步骤变化；`refresh` 为窗口尺寸变化后按新进度重算（不播放切换动画）。 */
  onStep(index: number, source: StepSource): void;
  /** 每帧回调，供比例尺等连续元素使用。 */
  onProgress?(progress: number): void;
  /** 钉住生效后在同一 matchMedia 条件块内追加的动画（随条件一起 revert）。 */
  setup?(st: ST, motion: Motion): void;
}

export interface PinnedSteps {
  /** 当前是否处于钉住模式。 */
  enabled: Readonly<Ref<boolean>>;
  index: Readonly<Ref<number>>;
  /** 钉住时滚到吸附点 k/(N−1)；未钉住时只调用 onStep(index, 'user')。 */
  goTo(index: number): Promise<void>;
  trigger: Readonly<Ref<ST | null>>;
}

/**
 * 使用钉住分步。
 * @param opts - 见 `PinnedStepsOptions`。
 * @returns 见 `PinnedSteps`。
 */
export function usePinnedSteps(opts: PinnedStepsOptions): PinnedSteps {
  const N = Math.max(2, opts.steps);
  const points = Array.from({ length: N }, (_, k) => k / (N - 1));
  const enabled = ref(false);
  const index = ref(0);
  const trigger = shallowRef<ST | null>(null);
  let busy = false;
  let alive = false;
  let mm: gsap.MatchMedia | undefined;

  const setIndex = (i: number, source: StepSource) => {
    if (i === index.value) return;
    index.value = i;
    opts.onStep(i, source);
  };

  onMounted(async () => {
    alive = true;
    const motion = await loadMotion();
    if (!alive || !motion) return;
    mm = motion.gsap.matchMedia();
    mm.add(PIN_QUERY, () => {
      const stage = opts.stage.value;
      if (!stage || !document.documentElement.classList.contains('motion-ready')) return;
      const length = opts.length ?? (() => (N - 1) * 0.5 * window.innerHeight);
      const snap = snapOption(points, opts.snap?.ease);
      if (opts.snap) snap.duration = opts.snap.duration;
      let refreshing = false;
      const st = motion.ScrollTrigger.create({
        trigger: stage,
        start: opts.start ?? 'top top+=64',
        end: () => `+=${Math.round(length())}`,
        pin: true,
        pinSpacing: true,
        anticipatePin: 1,
        invalidateOnRefresh: true,
        snap,
        onUpdate: (self) => {
          opts.onProgress?.(self.progress);
          if (busy) return;
          setIndex(stepOf(self.progress, N), refreshing ? 'refresh' : 'scroll');
        },
        onRefreshInit: () => {
          refreshing = true;
        },
        onRefresh: (self) => {
          opts.onProgress?.(self.progress);
          if (!busy) setIndex(stepOf(self.progress, N), 'refresh');
          refreshing = false;
        },
      });
      trigger.value = st;
      enabled.value = true;
      const detach = attachLenisSnap(motion, st, points, () => busy);
      opts.setup?.(st, motion);
      return () => {
        detach();
        enabled.value = false;
        trigger.value = null;
      };
    });
  });

  onBeforeUnmount(() => {
    alive = false;
    mm?.revert();
    mm = undefined;
  });

  function goTo(i: number): Promise<void> {
    const k = Math.min(N - 1, Math.max(0, i));
    const st = trigger.value;
    if (!enabled.value || !st) {
      setIndex(k, 'user');
      return Promise.resolve();
    }
    busy = true;
    setIndex(k, 'user');
    const target = st.start + (st.end - st.start) * points[k]!;
    const lenis = getLenis();
    return new Promise<void>((resolve) => {
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        busy = false;
        resolve();
      };
      // 用户中途滚轮打断时 Lenis 不回调 onComplete：兜底解锁。
      setTimeout(done, 1200);
      if (lenis) lenis.scrollTo(target, { duration: 0.6, easing: power2InOut, force: true, onComplete: done });
      else {
        window.scrollTo({ top: target, behavior: 'instant' });
        requestAnimationFrame(() => done());
      }
    });
  }

  return { enabled: readonly(enabled), index: readonly(index), goTo, trigger: readonly(trigger) as Readonly<Ref<ST | null>> };
}
