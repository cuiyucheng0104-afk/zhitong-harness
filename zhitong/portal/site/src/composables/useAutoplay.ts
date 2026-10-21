/**
 * 自动轮播状态机（00 章 §6.3；02 章 §2.5 接线参数）。
 *
 * - 自带时钟：播放时每帧推进 `elapsed`，并把绑定的时间线 `time()` 定位到 `min(elapsed, duration)`；
 *   暂停 = 时钟停住（时间线也停住），恢复从原位置继续，不重播。
 * - 场景时长 = 时间线时长 `duration` + 停留 `hold`（默认 3.2 s；`Infinity` 表示播完停在终态）。
 * - `createAutoplay` 只含状态（可在组件外、测试里用 `tick(dt)` 驱动）；
 *   `useAutoplay` 在其上接好 rAF、悬停、焦点、可见性、页面隐藏、减少动效与弹层。
 */
import {
  computed,
  onBeforeUnmount,
  onMounted,
  readonly,
  ref,
  shallowRef,
  toValue,
  watch,
  type ComputedRef,
  type MaybeRefOrGetter,
  type Ref,
} from 'vue';
import { anyModalOpen } from '../lib/modal-state';
import { hasFinePointer, prefersReducedMotion } from '../lib/motion';
import { useInView } from './useInView';

/** 焦点是否来自键盘（`:focus-visible`）；不支持该选择器的环境按键盘处理。 */
export function isKeyboardFocus(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  try {
    return target.matches(':focus-visible');
  } catch {
    // 旧引擎不认识 :focus-visible：保守地按键盘焦点暂停。
    return true;
  }
}

export type PauseReason = 'hover' | 'focus' | 'offscreen' | 'hidden' | 'user' | 'reduced' | 'dialog';
export type AutoplayState = 'playing' | 'paused' | 'manual' | 'sticky' | 'reduced' | 'done';

export interface AutoplayScene {
  /** 时间线时长（秒）。 */
  duration: number;
  /** 结果停留（秒），默认 3.2；`Infinity` 表示停在终态不前进。 */
  hold?: number;
}

/** 与 `gsap.core.Timeline` 兼容的最小接口。 */
export interface TimelineLike {
  time(value: number, suppressEvents?: boolean): unknown;
}

export interface AutoplayOptions {
  scenes: MaybeRefOrGetter<readonly AutoplayScene[]>;
  /** 最多完整播放几轮，默认 Infinity；播完停在场景 1 终态（`done`）。 */
  loopLimit?: number;
  /** 场景切换回调（自动推进时 `user` 为 false）。 */
  onScene?: (index: number, info: { user: boolean }) => void;
}

export interface UseAutoplayOptions extends AutoplayOptions {
  /** 示例根元素：焦点、可见比例、手动模式的活动检测都以它为范围。 */
  target?: Ref<HTMLElement | null | undefined>;
  /** 悬停暂停的范围，默认同 `target`。 */
  hoverTarget?: Ref<HTMLElement | null | undefined>;
  /** 指针离开后恢复的延迟（秒），默认 0.6。 */
  hoverResumeDelay?: number;
  /** 手动模式：指针离开且无操作多少秒后恢复（从下一个场景开始），默认 8。 */
  manualIdle?: number;
  /** 可见比例低于此值暂停，默认 0.35。 */
  visibleRatio?: number;
  /** 首次挂载时是否立即开始计时，默认 true。 */
  autostart?: boolean;
}

export interface Autoplay {
  /** 当前场景。 */
  index: Readonly<Ref<number>>;
  /** 0..1，当前场景已播放比例，驱动页签进度条。 */
  progress: ComputedRef<number>;
  /** 当前场景内已经过的秒数（含停留）。 */
  elapsed: Readonly<Ref<number>>;
  /** 暂停原因为空且未播完。 */
  playing: ComputedRef<boolean>;
  /** 供 `data-state` 使用的综合状态。 */
  state: ComputedRef<AutoplayState>;
  /** 当前暂停原因。 */
  reasons: ComputedRef<readonly PauseReason[]>;
  /** 已完成的轮数。 */
  loops: Readonly<Ref<number>>;
  pause(reason: PauseReason, opts?: { sticky?: boolean }): void;
  resume(reason: PauseReason): void;
  goTo(i: number, opts?: { user?: boolean }): void;
  /** 底栏“暂停 / 播放”按钮；`done` 时等同 `restart()`。 */
  toggle(): void;
  /** 清除 user（含置顶）与 done，从场景 1 的 0 s 开始。 */
  restart(): void;
  /** 绑定当前场景的时间线；切换场景后由调用方重新绑定。 */
  setTimeline(timeline: TimelineLike | null): void;
  /** 推进时钟（秒）；`useAutoplay` 每帧调用，测试可直接调用。 */
  tick(dt: number): void;
}

const DEFAULT_HOLD = 3.2;

/**
 * 创建与 DOM 无关的轮播状态。
 * @param options - 场景、轮数与回调。
 * @returns 轮播控制对象。
 */
export function createAutoplay(options: AutoplayOptions): Autoplay & { sticky: Readonly<Ref<boolean>> } {
  const index = ref(0);
  const elapsed = ref(0);
  const loops = ref(0);
  const done = ref(false);
  const sticky = ref(false);
  const reasonSet = ref(new Set<PauseReason>());
  const timeline = shallowRef<TimelineLike | null>(null);
  const loopLimit = options.loopLimit ?? Infinity;

  const scenes = () => toValue(options.scenes);
  const scene = (i: number) => scenes()[i] ?? { duration: 0 };
  const total = (i: number) => scene(i).duration + (scene(i).hold ?? DEFAULT_HOLD);
  const sync = () => timeline.value?.time(Math.min(elapsed.value, scene(index.value).duration));

  const playing = computed(() => reasonSet.value.size === 0 && !done.value);
  const progress = computed(() => {
    const t = total(index.value);
    if (!Number.isFinite(t)) {
      const d = scene(index.value).duration;
      return d > 0 ? Math.min(1, elapsed.value / d) : 1;
    }
    return t > 0 ? Math.min(1, elapsed.value / t) : 1;
  });
  const reasons = computed(() => [...reasonSet.value]);
  const state = computed<AutoplayState>(() => {
    const r = reasonSet.value;
    if (r.has('reduced')) return 'reduced';
    if (done.value) return 'done';
    if (r.has('user')) return sticky.value ? 'sticky' : 'manual';
    return r.size ? 'paused' : 'playing';
  });

  function setReasons(mut: (s: Set<PauseReason>) => void) {
    const next = new Set(reasonSet.value);
    mut(next);
    reasonSet.value = next;
  }

  function pause(reason: PauseReason, opts: { sticky?: boolean } = {}) {
    setReasons((s) => s.add(reason));
    if (reason === 'user' && opts.sticky) sticky.value = true;
  }

  function resume(reason: PauseReason) {
    setReasons((s) => s.delete(reason));
    if (reason === 'user') sticky.value = false;
  }

  function goTo(i: number, opts: { user?: boolean } = {}) {
    const n = scenes().length;
    if (!n) return;
    index.value = ((i % n) + n) % n;
    elapsed.value = 0;
    done.value = false;
    if (opts.user) pause('user');
    options.onScene?.(index.value, { user: Boolean(opts.user) });
    sync();
  }

  function restart() {
    resume('user');
    loops.value = 0;
    goTo(0);
  }

  function toggle() {
    if (done.value) return restart();
    if (reasonSet.value.has('user') && sticky.value) resume('user');
    else pause('user', { sticky: true });
  }

  function tick(dt: number) {
    if (!playing.value || dt <= 0) return;
    elapsed.value += dt;
    const t = total(index.value);
    if (elapsed.value < t) return sync();
    const n = scenes().length;
    const next = index.value + 1;
    if (next >= n) {
      loops.value += 1;
      if (loops.value >= loopLimit) {
        done.value = true;
        index.value = 0;
        elapsed.value = scene(0).duration;
        options.onScene?.(0, { user: false });
        return sync();
      }
    }
    goTo(next);
  }

  return {
    index: readonly(index),
    elapsed: readonly(elapsed),
    loops: readonly(loops),
    sticky: readonly(sticky),
    progress,
    playing,
    state,
    reasons,
    pause,
    resume,
    goTo,
    toggle,
    restart,
    setTimeline(tl) {
      timeline.value = tl;
      sync();
    },
    tick,
  };
}

/**
 * 在组件内使用轮播：接好 rAF 时钟与全部暂停原因。
 * @param options - 见 `UseAutoplayOptions`。
 * @returns 轮播控制对象。
 */
export function useAutoplay(options: UseAutoplayOptions): Autoplay {
  const core = createAutoplay(options);
  const hoverDelay = (options.hoverResumeDelay ?? 0.6) * 1000;
  const idleDelay = (options.manualIdle ?? 8) * 1000;
  const target = options.target ?? ref(null);
  const hoverTarget = options.hoverTarget ?? target;
  let frame = 0;
  let last = 0;
  let hoverTimer: ReturnType<typeof setTimeout> | undefined;
  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  let pointerInside = false;
  let media: MediaQueryList | undefined;
  const cleanups: (() => void)[] = [];

  const loop = (now: number) => {
    const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
    last = now;
    core.tick(dt);
    frame = requestAnimationFrame(loop);
  };

  function scheduleManual() {
    clearTimeout(idleTimer);
    if (!core.reasons.value.includes('user') || core.state.value === 'sticky' || pointerInside) return;
    if (core.reasons.value.includes('dialog')) return;
    idleTimer = setTimeout(() => {
      if (core.state.value !== 'manual') return;
      // 计时期间打开了弹层、离开视口或页面隐藏：不跳场景，重新计时（02 章反馈）。
      const r = core.reasons.value;
      if (r.includes('dialog') || r.includes('offscreen') || r.includes('hidden') || pointerInside) {
        scheduleManual();
        return;
      }
      core.resume('user');
      core.goTo(core.index.value + 1);
    }, idleDelay);
  }

  const api: Autoplay = {
    ...core,
    goTo(i, opts) {
      core.goTo(i, opts);
      if (opts?.user) scheduleManual();
    },
    pause(reason, opts) {
      core.pause(reason, opts);
      if (reason === 'user') scheduleManual();
    },
  };

  useInView(target, {
    threshold: options.visibleRatio ?? 0.35,
    play: () => core.resume('offscreen'),
    pause: () => core.pause('offscreen'),
  });

  function listen<K extends keyof HTMLElementEventMap>(
    el: HTMLElement,
    type: K,
    fn: (e: HTMLElementEventMap[K]) => void,
  ) {
    el.addEventListener(type, fn as EventListener, { passive: true });
    cleanups.push(() => el.removeEventListener(type, fn as EventListener));
  }

  function wire() {
    const root = target.value;
    const hover = hoverTarget.value;
    if (hover && hasFinePointer()) {
      listen(hover, 'pointerenter', () => {
        pointerInside = true;
        clearTimeout(hoverTimer);
        clearTimeout(idleTimer);
        core.pause('hover');
      });
      listen(hover, 'pointerleave', () => {
        pointerInside = false;
        clearTimeout(hoverTimer);
        hoverTimer = setTimeout(() => core.resume('hover'), hoverDelay);
        scheduleManual();
      });
    }
    if (root) {
      // 只有键盘聚焦（:focus-visible）才按“焦点在示例内”暂停（02 章 AC-02-26）。鼠标点底栏“播放”同样会让按钮获得焦点，
      // 若也暂停，按钮显示“暂停”而进度不动（AC-02-08）；指针在示例内时由 hover 原因负责暂停。
      listen(root, 'focusin', (e) => {
        if (isKeyboardFocus(e.target)) core.pause('focus');
        else core.resume('focus');
      });
      listen(root, 'focusout', (e) => {
        const next = e.relatedTarget as Node | null;
        if (!next || !root.contains(next)) core.resume('focus');
      });
      for (const type of ['pointerdown', 'keydown', 'pointermove'] as const)
        listen(root, type, () => scheduleManual());
    }
  }

  const onVisibility = () => (document.hidden ? core.pause('hidden') : core.resume('hidden'));
  const onReduced = () => (media?.matches ? core.pause('reduced') : core.resume('reduced'));

  watch(anyModalOpen, (open) => {
    if (open) core.pause('dialog');
    else {
      core.resume('dialog');
      scheduleManual();
    }
  });

  onMounted(() => {
    if (prefersReducedMotion()) core.pause('reduced');
    media = window.matchMedia?.('(prefers-reduced-motion: reduce)');
    media?.addEventListener?.('change', onReduced);
    if (document.hidden) core.pause('hidden');
    document.addEventListener('visibilitychange', onVisibility);
    if (anyModalOpen.value) core.pause('dialog');
    // 可见比例由 IntersectionObserver 首次回调确认后才开始计时。
    if (target.value && typeof IntersectionObserver !== 'undefined') core.pause('offscreen');
    wire();
    if (options.autostart !== false && typeof requestAnimationFrame === 'function')
      frame = requestAnimationFrame(loop);
  });

  onBeforeUnmount(() => {
    cancelAnimationFrame(frame);
    clearTimeout(hoverTimer);
    clearTimeout(idleTimer);
    media?.removeEventListener?.('change', onReduced);
    document.removeEventListener('visibilitychange', onVisibility);
    for (const fn of cleanups.splice(0)) fn();
  });

  return api;
}
