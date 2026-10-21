/**
 * 顶栏状态（01 章 §2）：首页 `top`（scrollY ≤ 4）/ `scrolled`（scrollY > 8），4–8px 之间保持原状态；
 * 文档页与 404 页恒为 `docs`。水合时立即按 `window.scrollY` 算一次；首页 GSAP 就绪后改由 ScrollTrigger 驱动，
 * 之前与文档页用被动 scroll + rAF。
 */
import { onBeforeUnmount, onMounted, ref, toValue, watch, type MaybeRefOrGetter } from 'vue';
import { getMotion, loadMotion } from '../lib/motion';

export type PageLayout = 'home' | 'docs' | 'notfound';
export type HeaderState = 'top' | 'scrolled' | 'docs';

/**
 * 纯函数：由滚动位置与上一状态得出新状态（滞回 4/8px）。
 * @param y - scrollY。
 * @param prev - 上一状态。
 * @param layout - 页面类型。
 * @returns 新状态。
 */
export function nextHeaderState(y: number, prev: HeaderState, layout: PageLayout): HeaderState {
  if (layout !== 'home') return 'docs';
  if (y > 8) return 'scrolled';
  if (y <= 4) return 'top';
  return prev === 'docs' ? 'top' : prev;
}

/**
 * 使用顶栏状态。
 * @param layout - 页面类型（取自 route.meta.layout）。
 * @returns `state`。
 */
export function useHeaderState(layout: MaybeRefOrGetter<PageLayout>) {
  const initial = toValue(layout) === 'home' ? 'top' : 'docs';
  const state = ref<HeaderState>(initial);
  let frame = 0;
  let trigger: { kill(): void } | undefined;
  let alive = false;

  const compute = (y = window.scrollY) => {
    state.value = nextHeaderState(y, state.value, toValue(layout));
  };
  const onScroll = () => {
    if (trigger) return;
    frame ||= requestAnimationFrame(() => {
      frame = 0;
      compute();
    });
  };

  async function attachTrigger() {
    trigger?.kill();
    trigger = undefined;
    if (toValue(layout) !== 'home') return;
    const motion = getMotion() ?? (await loadMotion());
    if (!alive || !motion || toValue(layout) !== 'home') return;
    trigger = motion.ScrollTrigger.create({
      start: 0,
      end: 'max',
      onUpdate: (self) => compute(self.scroll()),
    });
  }

  onMounted(() => {
    alive = true;
    compute();
    window.addEventListener('scroll', onScroll, { passive: true });
    void attachTrigger();
  });
  watch(
    () => toValue(layout),
    () => {
      compute();
      void attachTrigger();
    },
  );
  onBeforeUnmount(() => {
    alive = false;
    cancelAnimationFrame(frame);
    trigger?.kill();
    window.removeEventListener('scroll', onScroll);
  });

  return { state };
}
