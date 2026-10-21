/**
 * 入场（00 章 §6.5）：`data-reveal="heading | block | stagger"`。
 *
 * - heading：SplitText 按行拆（`mask: 'lines'`，`autoSplit: true`），每行 `yPercent 100 → 0`，`DUR.long`、`EASE.expo`、`STAGGER.base`。
 * - block：`y 24 → 0`、`opacity 0 → 1`，`DUR.base`、`EASE.out`。
 * - stagger：直接子元素依次做 block，`STAGGER.base`。
 * - 触发 `start: 'top 85%'`，`once: true`。
 * - 预渲染即终态；只在 `html.motion-ready`（GSAP 加载成功且未减少动效）后才设初始态。
 *   加载时已在视口上方的元素直接保持终态（00 章 §5.5）。
 * - 旧类名 `.reveal` 视同 `block`，供未改写的区块过渡使用。
 */
import { onBeforeUnmount, onMounted, type Ref } from 'vue';
import { loadMotion, prefersReducedMotion, type Motion } from '../lib/motion';
import { DUR, EASE, STAGGER } from '../lib/motion-tokens';

export type RevealKind = 'heading' | 'block' | 'stagger';

export const REVEAL_START = 'top 85%';

export interface RevealOptions {
  /** 额外的选择器（视同 block），默认 `.reveal`。 */
  legacy?: string;
  /** 加载完成后调用（例如做 ScrollTrigger.refresh）。 */
  onReady?: (motion: Motion) => void;
}

/**
 * 为 root 内的 `[data-reveal]` 建立入场动画。
 * @param root - 范围元素。
 * @param options - 见 `RevealOptions`。
 * @returns `refresh()`：动态插入新元素后重新扫描。
 */
export function useReveal(root: Ref<HTMLElement | null | undefined>, options: RevealOptions = {}) {
  let ctx: gsap.Context | undefined;
  let motion: Motion | null = null;
  let mounted = false;
  const done = new WeakSet<Element>();

  function setup(el: HTMLElement, kind: RevealKind, m: Motion) {
    const { gsap, SplitText } = m;
    if (done.has(el)) return;
    done.add(el);
    if (el.getBoundingClientRect().bottom < 0) return;
    const scrollTrigger = { trigger: el, start: REVEAL_START, once: true };
    if (kind === 'heading') {
      SplitText.create(el, {
        type: 'lines',
        mask: 'lines',
        autoSplit: true,
        onSplit: (self) =>
          gsap.from(self.lines, {
            yPercent: 100,
            duration: DUR.long,
            ease: EASE.expo,
            stagger: STAGGER.base,
            scrollTrigger,
          }),
      });
    } else {
      const targets = kind === 'stagger' ? [...el.children] : el;
      gsap.from(targets, {
        y: 24,
        opacity: 0,
        duration: DUR.base,
        ease: EASE.out,
        stagger: kind === 'stagger' ? STAGGER.base : 0,
        clearProps: 'opacity,transform',
        scrollTrigger,
      });
    }
  }

  function scan() {
    const el = root.value;
    if (!el || !motion || prefersReducedMotion()) return;
    ctx ??= motion.gsap.context(() => {}, el);
    ctx.add(() => {
      for (const node of el.querySelectorAll<HTMLElement>('[data-reveal]')) {
        const kind = node.dataset.reveal as RevealKind;
        if (kind === 'heading' || kind === 'block' || kind === 'stagger') setup(node, kind, motion!);
      }
      for (const node of el.querySelectorAll<HTMLElement>(options.legacy ?? '.reveal'))
        if (!node.hasAttribute('data-reveal')) setup(node, 'block', motion!);
    });
  }

  onMounted(async () => {
    mounted = true;
    const m = await loadMotion();
    if (!mounted || !m) return;
    motion = m;
    scan();
    options.onReady?.(m);
  });
  onBeforeUnmount(() => {
    mounted = false;
    ctx?.revert();
    ctx = undefined;
  });

  return { refresh: scan };
}
