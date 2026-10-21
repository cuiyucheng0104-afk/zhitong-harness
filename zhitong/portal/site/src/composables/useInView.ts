/**
 * 可见性与暂停（00 章 §6.8）：可见比例 ≥ threshold 且页面可见时 `play()`，否则 `pause()`。
 * 所有循环动画（能力小动画、装饰动效）都挂在它上面。
 */
import { onBeforeUnmount, onMounted, readonly, ref, watch, type Ref } from 'vue';

export interface InViewOptions {
  /** 可见比例阈值，默认 0.35。 */
  threshold?: number;
  /** 进入（且页面可见）时调用。 */
  play?: () => void;
  /** 离开或页面隐藏时调用。 */
  pause?: () => void;
  /** 只触发一次 play，之后停止观察。 */
  once?: boolean;
}

export interface InView {
  /** 可见比例 ≥ threshold 且页面可见。 */
  active: Readonly<Ref<boolean>>;
  /** 最近一次观测到的有效可见比例 0..1（高于视口的元素按占视口比例计）。 */
  ratio: Readonly<Ref<number>>;
  /** 停止观察并移除监听。 */
  stop: () => void;
}

// 1% 步长：高于视口的元素按“占视口比例”判定时，元素自身比例变化很小，步长粗了会推迟触发。
const THRESHOLDS = Array.from({ length: 101 }, (_, i) => i / 100);

/**
 * 有效可见比例：可见高度 ÷ min(元素高度, 视口高度)。
 * 元素不高于视口时等于 intersectionRatio；高于视口时（如手机纵向时间线里展开后 2000+ px 的场景窗口），
 * 按“占满视口的比例”计算，否则元素永远到不了 0.35（05 章 AC-05-17）。
 */
function effectiveRatio(entry: IntersectionObserverEntry): number {
  if (!entry.isIntersecting) return 0;
  const h = entry.boundingClientRect.height;
  const vh = entry.rootBounds?.height ?? (typeof window !== 'undefined' ? window.innerHeight : 0);
  if (!h || !vh || h <= vh) return entry.intersectionRatio;
  return Math.min(1, entry.intersectionRect.height / vh);
}

/**
 * 观察元素可见性。
 * @param target - 被观察元素（ref）。
 * @param options - 阈值与回调。
 * @returns 可见状态与停止函数。
 */
export function useInView(target: Ref<Element | null | undefined>, options: InViewOptions = {}): InView {
  const threshold = options.threshold ?? 0.35;
  const active = ref(false);
  const ratio = ref(0);
  let observer: IntersectionObserver | undefined;
  let stopped = false;
  let fired = false;

  const compute = () => {
    const next = !stopped && ratio.value >= threshold && !document.hidden;
    if (next === active.value) return;
    active.value = next;
    if (next) {
      options.play?.();
      if (options.once) {
        fired = true;
        stop();
      }
    } else if (!fired) options.pause?.();
  };
  const onVisibility = () => compute();

  function observe(el: Element | null | undefined) {
    observer?.disconnect();
    if (!el || stopped || typeof IntersectionObserver === 'undefined') return;
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) ratio.value = effectiveRatio(entry);
        compute();
      },
      { threshold: [...new Set([...THRESHOLDS, threshold])].sort((a, b) => a - b) },
    );
    observer.observe(el);
  }

  function stop() {
    stopped = true;
    observer?.disconnect();
    observer = undefined;
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onVisibility);
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', onVisibility);
    observe(target.value);
  });
  watch(target, (el) => observe(el));
  onBeforeUnmount(stop);

  return { active: readonly(active), ratio: readonly(ratio), stop };
}
