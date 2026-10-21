/**
 * 滑块吸附（00 章 §6.2；CSS 驱动方式见 01 章 §14.4）。
 *
 * 一组链接共用一个底板：指针进入或键盘聚焦某项时，底板移到该项位置与宽度；离开整组回到当前项，
 * 没有当前项则淡出；当前项变化时同样跟随。
 * - `driver: 'css'`：只在底板元素上写 `--ind-x`、`--ind-w`、`--ind-y`、`--ind-h`（相对组容器的像素）
 *   与 `--ind-o`（0/1），移动由样式表 `transition` 完成。顶栏与文档目录用它（文档页不加载 GSAP）。
 * - `driver: 'gsap'`（默认）：底板 `x`/`y` 平移 + `scaleX`/`scaleY` 伸缩（底板自身宽高为 100px 基准），
 *   `DUR.short`、`EASE.out`；GSAP 未加载时退回 CSS 变量。
 */
import { onBeforeUnmount, onMounted, readonly, ref, toValue, watch, type MaybeRefOrGetter, type Ref } from 'vue';
import { getMotion } from '../lib/motion';
import { DUR, EASE } from '../lib/motion-tokens';

export interface HoverIndicatorOptions {
  /** 组容器（底板的定位参照）。 */
  container: Ref<HTMLElement | null | undefined>;
  /** 底板元素。 */
  indicator: Ref<HTMLElement | null | undefined>;
  /** 组成员选择器，默认 `[data-indicator-item]`。 */
  items?: string;
  /** 当前选中项（元素或返回元素的 getter）；null 表示没有当前项。 */
  active?: MaybeRefOrGetter<HTMLElement | null | undefined>;
  /** 驱动方式，默认 'gsap'。 */
  driver?: 'gsap' | 'css';
  /** 指针悬停是否预览，默认 true；文档本页目录传 false。 */
  followPointer?: boolean;
  /** GSAP 驱动时底板的基准尺寸（px），默认 100。 */
  baseSize?: number;
}

export interface IndicatorBox {
  x: number;
  y: number;
  w: number;
  h: number;
  o: 0 | 1;
}

/**
 * 计算某项相对组容器的位置（纯函数，供测试）。
 * @param item - 组成员包围盒。
 * @param container - 组容器包围盒。
 * @returns 底板目标。
 */
export function indicatorBox(item: DOMRect | null, container: DOMRect): IndicatorBox {
  if (!item) return { x: 0, y: 0, w: 0, h: 0, o: 0 };
  return {
    x: item.left - container.left,
    y: item.top - container.top,
    w: item.width,
    h: item.height,
    o: 1,
  };
}

/**
 * 使用滑块吸附。
 * @param options - 见 `HoverIndicatorOptions`。
 * @returns 当前底板目标（只读）、手动刷新与移动函数。
 */
export function useHoverIndicator(options: HoverIndicatorOptions) {
  const selector = options.items ?? '[data-indicator-item]';
  const box = ref<IndicatorBox>({ x: 0, y: 0, w: 0, h: 0, o: 0 });
  let hovered: HTMLElement | null = null;
  let last: IndicatorBox | null = null;
  let resize: ResizeObserver | undefined;

  const itemFrom = (target: EventTarget | null) => {
    const root = options.container.value;
    if (!root || !(target instanceof Element)) return null;
    const item = target.closest<HTMLElement>(selector);
    return item && root.contains(item) ? item : null;
  };

  function apply(next: IndicatorBox) {
    const el = options.indicator.value;
    box.value = next;
    if (!el) return;
    const motion = options.driver === 'css' ? null : getMotion();
    if (motion) {
      const base = options.baseSize ?? 100;
      const first = last === null || last.o === 0;
      motion.gsap.to(el, {
        x: next.x,
        y: next.y,
        scaleX: next.w / base || 0.0001,
        scaleY: next.h / base || 0.0001,
        opacity: next.o,
        duration: first ? 0 : DUR.short,
        ease: EASE.out,
        overwrite: 'auto',
      });
      if (first && next.o)
        motion.gsap.fromTo(el, { opacity: 0 }, { opacity: 1, duration: DUR.micro, ease: EASE.out });
    } else {
      el.style.setProperty('--ind-x', `${next.x}px`);
      el.style.setProperty('--ind-y', `${next.y}px`);
      el.style.setProperty('--ind-w', `${next.w}px`);
      el.style.setProperty('--ind-h', `${next.h}px`);
      el.style.setProperty('--ind-o', String(next.o));
    }
    last = next;
  }

  /** 把底板移到某项（null 表示淡出）。 */
  function moveTo(item: HTMLElement | null | undefined) {
    const root = options.container.value;
    if (!root) return;
    if (!item) {
      apply({ ...(last ?? box.value), o: 0 });
      return;
    }
    apply(indicatorBox(item.getBoundingClientRect(), root.getBoundingClientRect()));
  }

  /** 回到当前项（或悬停项）。 */
  function update() {
    moveTo(hovered ?? toValue(options.active) ?? null);
  }

  const onOver = (e: Event) => {
    const item = itemFrom(e.target);
    if (!item || item === hovered) return;
    hovered = item;
    moveTo(item);
  };
  const onLeave = () => {
    hovered = null;
    update();
  };
  const onFocusOut = (e: FocusEvent) => {
    const root = options.container.value;
    if (root && e.relatedTarget instanceof Node && root.contains(e.relatedTarget)) return;
    onLeave();
  };

  function bind(root: HTMLElement | null | undefined, prev?: HTMLElement | null) {
    if (prev) {
      prev.removeEventListener('pointerover', onOver);
      prev.removeEventListener('pointerleave', onLeave);
      prev.removeEventListener('focusin', onOver);
      prev.removeEventListener('focusout', onFocusOut);
      resize?.disconnect();
    }
    if (!root) return;
    if (options.followPointer !== false) {
      root.addEventListener('pointerover', onOver);
      root.addEventListener('pointerleave', onLeave);
    }
    root.addEventListener('focusin', onOver);
    root.addEventListener('focusout', onFocusOut);
    if (typeof ResizeObserver !== 'undefined') {
      resize = new ResizeObserver(() => update());
      resize.observe(root);
    }
    update();
  }

  onMounted(() => bind(options.container.value));
  watch(options.container, (root, prev) => bind(root, prev));
  watch(() => toValue(options.active), () => update(), { flush: 'post' });
  onBeforeUnmount(() => bind(null, options.container.value));

  return { box: readonly(box), update, moveTo };
}
