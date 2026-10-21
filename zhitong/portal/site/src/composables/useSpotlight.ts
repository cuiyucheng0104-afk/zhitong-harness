/**
 * 卡片光斑（00 章 §6.6）：精确指针下，pointermove 在 rAF 内写 `--mx`、`--my`，并切换 `.is-spotlit`；
 * 视觉由 styles/ui.css 的 `.zt-spotlight` 提供（240px 径向高光 + 1px 边框高光）。
 */
import { onBeforeUnmount, onMounted, watch, type Directive, type Ref } from 'vue';
import { hasFinePointer, prefersReducedMotion } from '../lib/motion';

/**
 * 给元素挂光斑。
 * @param el - 卡片元素（会加上 `.zt-spotlight` 类）。
 * @returns 解除函数。
 */
export function attachSpotlight(el: HTMLElement): () => void {
  if (typeof window === 'undefined' || !hasFinePointer() || prefersReducedMotion()) return () => {};
  el.classList.add('zt-spotlight');
  let frame = 0;
  let pending: PointerEvent | null = null;
  const flush = () => {
    frame = 0;
    if (!pending) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${pending.clientX - rect.left}px`);
    el.style.setProperty('--my', `${pending.clientY - rect.top}px`);
  };
  const move = (e: PointerEvent) => {
    pending = e;
    frame ||= requestAnimationFrame(flush);
  };
  const enter = (e: PointerEvent) => {
    el.classList.add('is-spotlit');
    move(e);
  };
  const leave = () => el.classList.remove('is-spotlit');
  el.addEventListener('pointerenter', enter, { passive: true });
  el.addEventListener('pointermove', move, { passive: true });
  el.addEventListener('pointerleave', leave, { passive: true });
  return () => {
    cancelAnimationFrame(frame);
    el.removeEventListener('pointerenter', enter);
    el.removeEventListener('pointermove', move);
    el.removeEventListener('pointerleave', leave);
    el.classList.remove('zt-spotlight', 'is-spotlit');
  };
}

/**
 * 组合式用法。
 * @param target - 卡片 ref。
 */
export function useSpotlight(target: Ref<HTMLElement | null | undefined>) {
  let off: (() => void) | undefined;
  const bind = (el: HTMLElement | null | undefined) => {
    off?.();
    off = el ? attachSpotlight(el) : undefined;
  };
  onMounted(() => bind(target.value));
  watch(target, bind);
  onBeforeUnmount(() => off?.());
}

const registry = new WeakMap<HTMLElement, () => void>();

/** 指令：`v-spotlight`。 */
export const vSpotlight: Directive<HTMLElement> = {
  mounted(el) {
    registry.set(el, attachSpotlight(el));
  },
  beforeUnmount(el) {
    registry.get(el)?.();
    registry.delete(el);
  },
  getSSRProps() {
    return {};
  },
};
