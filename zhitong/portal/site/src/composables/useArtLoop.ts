/**
 * 能力小动画循环控制（04 章 §7.1 `useArtLoop`）。
 *
 * - 首次构建：`active` 且可见比例 ≥ 0.35 时 `loadMotion()` 并懒加载 `art/timelines`，建 `repeat: -1` 的暂停时间线，
 *   执行构建函数后追加停留与复位。减少动效时不构建（原因 `reduced` 常在）。
 * - 暂停原因 offscreen / hidden / inactive：原位暂停；hover / focus / user：快进或回退到 `hold` 终帧并停住。
 * - 首次因滚动进入视口时从 `hold` 播放；因选中而激活时 0.3s 后从 0 播放。
 * - 舞台宽 ≥ 488 为并排，否则顺序；布局变化时按进度重建。
 * - 构建报错只影响该项：`console.warn('capability art build failed', id, error)`，保持终帧。
 * 文件位置：按 04 章 §0 放在 `composables/useArtLoop.ts`（集成时由 components/capabilities/ 迁入）。
 */
import {
  computed,
  onBeforeUnmount,
  onMounted,
  ref,
  shallowRef,
  watch,
  type ComputedRef,
  type Ref,
} from 'vue';
import { loadMotion, prefersReducedMotion, type Motion } from '../lib/motion';
import { DUR, EASE } from '../lib/motion-tokens';
import { useInView } from './useInView';
import type { FeatureId } from '../data/capabilities';
import { ART } from '../components/capabilities/art-tokens';
import type { ArtLayout } from '../components/capabilities/art-kit';

export type ArtPause = 'offscreen' | 'hidden' | 'hover' | 'focus' | 'user' | 'reduced' | 'inactive';

type TimelinesModule = typeof import('../components/capabilities/art/timelines');

/** 测试与调试用：`window.__artDebug[id]`（仅开发与测试构建暴露）。 */
export interface ArtDebug {
  readonly time: number;
  readonly running: boolean;
  readonly hold: number;
  readonly duration: number;
  readonly reasons: ArtPause[];
}

const STOP_AT_HOLD: ArtPause[] = ['hover', 'focus', 'user'];

let timelines: Promise<TimelinesModule> | undefined;
/** 预取时间线块（CapabilitiesSection 在区块距视口一屏时调用）。 */
export function prefetchArtTimelines(): Promise<TimelinesModule> {
  timelines ??= import('../components/capabilities/art/timelines');
  return timelines;
}

const debugEnabled = () =>
  typeof window !== 'undefined' &&
  (import.meta.env.DEV ||
    import.meta.env.MODE === 'test' ||
    (window as { __ART_DEBUG__?: boolean }).__ART_DEBUG__ === true);

/**
 * 舞台布局（纯函数）。
 * @param width - `.feature-art` 内容宽。
 * @returns 并排或顺序。
 */
export function artLayoutFor(width: number): ArtLayout {
  return width >= ART.splitMin ? 'split' : 'sequence';
}

/**
 * 使用小动画循环。
 * @param figure - `figure.feature-art`。
 * @param opts - 能力 id、是否为当前项、全区暂停开关。
 * @returns 布局、是否在运行、是否已接管（`.art-stage` 加 `art-live`、显示暂停按钮）。
 */
export function useArtLoop(
  figure: Ref<HTMLElement | null>,
  opts: { id: FeatureId; active: Ref<boolean>; paused: Ref<boolean> },
): {
  layout: Ref<ArtLayout>;
  running: ComputedRef<boolean>;
  live: Ref<boolean>;
  reasons: Ref<ReadonlySet<ArtPause>>;
} {
  const layout = ref<ArtLayout>('split');
  const live = ref(false);
  const reasons = shallowRef<ReadonlySet<ArtPause>>(new Set<ArtPause>(['offscreen']));
  const tl = shallowRef<gsap.core.Timeline | null>(null);
  const running = computed(() => !!tl.value && reasons.value.size === 0);

  let motion: Motion | null = null;
  let mod: TimelinesModule | null = null;
  let dispose: (() => void) | null = null;
  let building = false;
  let failed = false;
  let disposed = false;
  let startFrom: 'hold' | 'zero' | null = null;
  let hoverTimer: ReturnType<typeof setTimeout> | undefined;
  let delayed: gsap.core.Tween | null = null;
  let resize: ResizeObserver | undefined;
  let detail: HTMLElement | null = null;

  const stage = () => figure.value?.querySelector<HTMLElement>('.art-stage') ?? null;

  function setReason(reason: ArtPause, on: boolean) {
    const has = reasons.value.has(reason);
    if (has === on) return;
    const next = new Set(reasons.value);
    if (on) next.add(reason);
    else next.delete(reason);
    reasons.value = next;
    apply();
  }

  function holdTime() {
    return tl.value?.labels.hold ?? 0;
  }

  function apply() {
    const t = tl.value;
    if (!t) {
      if (
        !reasons.value.has('offscreen') &&
        !reasons.value.has('inactive') &&
        !reasons.value.has('reduced')
      )
        void build();
      return;
    }
    if (!motion) return;
    motion.gsap.killTweensOf(t);
    if (delayed) return;
    if (STOP_AT_HOLD.some((r) => reasons.value.has(r))) {
      t.pause();
      motion.gsap.to(t, { time: holdTime(), duration: DUR.short, ease: EASE.out });
      return;
    }
    if (reasons.value.size) t.pause();
    else t.play();
  }

  function revert() {
    const s = stage();
    if (!s || !motion) return;
    dispose?.();
    dispose = null;
    motion.gsap.set([...s.querySelectorAll('[data-transient], [data-a], .art-in, .art-out')], {
      clearProps: 'all',
    });
    s.querySelectorAll<SVGRectElement>('[data-clip]').forEach((r) =>
      r.setAttribute('width', '300'),
    );
    figure.value?.style.removeProperty('--art-p');
  }

  function create(progress?: number) {
    const s = stage();
    if (!s || !motion || !mod || disposed) return;
    const { gsap } = motion;
    const t = gsap.timeline({
      paused: true,
      repeat: -1,
      onUpdate: () => figure.value?.style.setProperty('--art-p', String(t.progress())),
    });
    const handle = mod.createArtKit(gsap, t, s, layout.value);
    try {
      mod.builders[opts.id](handle.kit);
      mod.finishArtLoop(gsap, t, s, handle.hold());
    } catch (error) {
      console.warn('capability art build failed', opts.id, error);
      t.kill();
      handle.dispose();
      failed = true;
      live.value = false;
      revert();
      return;
    }
    dispose = handle.dispose;
    tl.value = t;
    live.value = true;
    if (progress !== undefined) t.progress(progress);
    else if (startFrom === 'zero') t.time(0);
    else t.time(holdTime());
    startFrom = null;
    apply();
  }

  async function build() {
    if (building || failed || disposed || tl.value || prefersReducedMotion()) return;
    building = true;
    startFrom ??= 'hold';
    try {
      motion = await loadMotion();
      if (!motion) return;
      mod = await prefetchArtTimelines();
    } catch (error) {
      console.warn('capability art build failed', opts.id, error);
      failed = true;
      return;
    } finally {
      building = false;
    }
    if (disposed || tl.value) return;
    measure();
    create();
  }

  function measure() {
    const el = figure.value;
    if (!el) return;
    const style = getComputedStyle(el);
    const width =
      el.clientWidth - parseFloat(style.paddingLeft || '0') - parseFloat(style.paddingRight || '0');
    if (width > 0) layout.value = artLayoutFor(width);
  }

  function rebuild() {
    const t = tl.value;
    if (!t) return;
    const p = t.progress();
    motion?.gsap.killTweensOf(t);
    t.kill();
    tl.value = null;
    revert();
    create(p);
  }

  function activate() {
    setReasonSilently('inactive', false);
    const t = tl.value;
    if (!t || !motion) {
      // 尚未进入视口就被激活（例如挂载后增强）：仍按“首次滚入从 hold 播放”处理。
      if (!reasons.value.has('offscreen')) startFrom = 'zero';
      apply();
      return;
    }
    motion.gsap.killTweensOf(t);
    t.pause(0);
    delayed?.kill();
    delayed = motion.gsap.delayedCall(0.3, () => {
      delayed = null;
      apply();
    });
  }

  function setReasonSilently(reason: ArtPause, on: boolean) {
    const next = new Set(reasons.value);
    if (on) next.add(reason);
    else next.delete(reason);
    reasons.value = next;
  }

  const inView = useInView(figure, {
    threshold: ART.inViewThreshold,
    play: () => setReason('offscreen', false),
    pause: () => setReason('offscreen', true),
  });
  void inView;

  const onVisibility = () => setReason('hidden', document.hidden);
  const onEnter = () => {
    clearTimeout(hoverTimer);
    setReason('hover', true);
  };
  const onLeave = () => {
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => setReason('hover', false), ART.hoverResume * 1000);
  };
  const onFocusIn = () => setReason('focus', true);
  const onFocusOut = (e: FocusEvent) => {
    if (detail && e.relatedTarget instanceof Node && detail.contains(e.relatedTarget)) return;
    setReason('focus', false);
  };

  watch(opts.active, (on, was) => {
    if (on && !was) activate();
    else if (!on) {
      delayed?.kill();
      delayed = null;
      setReason('inactive', true);
    }
  });
  watch(opts.paused, (on) => setReason('user', on), { immediate: false });

  onMounted(() => {
    const init = new Set<ArtPause>(['offscreen']);
    if (!opts.active.value) init.add('inactive');
    if (opts.paused.value) init.add('user');
    if (prefersReducedMotion()) init.add('reduced');
    if (document.hidden) init.add('hidden');
    reasons.value = init;
    const el = figure.value;
    if (!el) return;
    el.addEventListener('pointerenter', onEnter);
    el.addEventListener('pointerleave', onLeave);
    detail = el.closest<HTMLElement>('.feature-detail') ?? el;
    detail.addEventListener('focusin', onFocusIn);
    detail.addEventListener('focusout', onFocusOut);
    document.addEventListener('visibilitychange', onVisibility);
    if (typeof ResizeObserver !== 'undefined') {
      resize = new ResizeObserver(() => {
        const before = layout.value;
        measure();
        if (layout.value !== before) rebuild();
      });
      resize.observe(el);
    }
    measure();
    if (debugEnabled()) {
      const w = window as { __artDebug?: Record<string, ArtDebug> };
      w.__artDebug ??= {};
      w.__artDebug[opts.id] = {
        get time() {
          return tl.value?.time() ?? 0;
        },
        get running() {
          return running.value;
        },
        get hold() {
          return holdTime();
        },
        get duration() {
          return tl.value?.duration() ?? 0;
        },
        get reasons() {
          return [...reasons.value];
        },
      };
    }
  });

  onBeforeUnmount(() => {
    disposed = true;
    clearTimeout(hoverTimer);
    delayed?.kill();
    resize?.disconnect();
    const el = figure.value;
    el?.removeEventListener('pointerenter', onEnter);
    el?.removeEventListener('pointerleave', onLeave);
    detail?.removeEventListener('focusin', onFocusIn);
    detail?.removeEventListener('focusout', onFocusOut);
    document.removeEventListener('visibilitychange', onVisibility);
    if (tl.value) {
      motion?.gsap.killTweensOf(tl.value);
      tl.value.kill();
      tl.value = null;
      revert();
    }
    const w =
      typeof window !== 'undefined' ? (window as { __artDebug?: Record<string, ArtDebug> }) : null;
    if (w?.__artDebug) delete w.__artDebug[opts.id];
  });

  return { layout, running, live, reasons };
}
