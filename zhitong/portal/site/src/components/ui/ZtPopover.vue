<script setup lang="ts">
/**
 * 说明卡（00 章 §6.4）。
 *
 * 桌面：原生 `popover="auto"` 进入顶层，首次打开时懒加载 `@floating-ui/dom` 定位
 * （`bottom-start`、`offset(10)`、`flip()`、`shift({ padding: 16 })`、`size()`、`arrow()`）。
 * 上下都放不下时保留首选方向（`fallbackStrategy: 'initialPlacement'`），由 `size()` 把正文限高为可用高度、内部滚动。
 * 打开 `y 6 → 0`、`scale .98 → 1`、透明度，280ms；内容行（`[data-popover-row]`）错开 40ms；关闭 160ms 淡出。
 * 手机（≤ 767px）：改为底部弹层（复用 BaseDialog，带拖拽把手，下拉 80px 关闭）。
 *
 * 两种触发方式：
 * 1. 调用 `show(trigger)` / `toggle(trigger)`（03 章共用一个实例，换锚点打开）；
 * 2. 触发按钮写原生 `popovertarget="<id>"`（05 章，水合前也能打开）；水合后由本组件接管定位与动画。
 * 触发元素的 `aria-expanded`、`aria-controls` 由本组件维护；Esc、点外部关闭，焦点回到触发元素；同一时间只开一个。
 */
import { computed, onBeforeUnmount, onMounted, ref, nextTick } from 'vue';
import BaseDialog from '../BaseDialog.vue';
import { prefersReducedMotion } from '../../lib/motion';
import { CSS_EASE, MS } from '../../lib/motion-tokens';
import type { PopoverRow } from './types';

const props = withDefaults(
  defineProps<{
    id: string;
    title?: string;
    /** 一句话说明。 */
    lead?: string;
    /** “需要什么 / 得到什么”等两行。 */
    rows?: PopoverRow[];
    placement?: 'bottom-start' | 'bottom' | 'bottom-end' | 'top-start' | 'top' | 'top-end';
  }>(),
  { title: '', lead: '', rows: undefined, placement: 'bottom-start' },
);
const emit = defineEmits<{ open: [trigger: HTMLElement | null]; close: [] }>();

const el = ref<HTMLElement | null>(null);
const arrowEl = ref<HTMLElement | null>(null);
const mobile = ref(false);
const sheetOpen = ref(false);
const isOpen = ref(false);
const titleId = computed(() => `${props.id}-title`);

let anchor: HTMLElement | null = null;
let lastInvoker: HTMLElement | null = null;
let stopAutoUpdate: (() => void) | null = null;
let media: MediaQueryList | undefined;
let closingAnim: Animation | null = null;
let restoreFocus = true;
/** show() 正在打开：原生 toggle 事件不重复定位，beforetoggle 不改锚点。 */
let managed = false;

const nativePopover = () => typeof HTMLElement !== 'undefined' && 'showPopover' in HTMLElement.prototype;

/** 所有实例共享：同一时间只开一个（无原生 popover 的环境下也成立）。 */
const openInstances = (globalThis as { __ztPopovers?: Set<() => void> }).__ztPopovers ??= new Set();

function setTriggerState(open: boolean) {
  if (!anchor) return;
  anchor.setAttribute('aria-expanded', String(open));
  anchor.setAttribute('aria-controls', props.id);
}

async function position() {
  const floating = el.value;
  if (!floating || !anchor) return;
  const { computePosition, autoUpdate, offset, flip, shift, size, arrow } = await import('@floating-ui/dom');
  const reference = anchor;
  const update = async () => {
    if (!el.value || !reference.isConnected) return;
    const { x, y, placement, middlewareData } = await computePosition(reference, floating, {
      placement: props.placement,
      strategy: 'fixed',
      middleware: [
        offset(10),
        flip({ fallbackStrategy: 'initialPlacement', padding: 16 }),
        shift({ padding: 16 }),
        size({
          padding: 16,
          apply({ availableHeight, elements }) {
            // 正文（.zt-popover-body）按可用高度限高，超出部分在卡内滚动（03 章 AC-03-11）。
            elements.floating.style.setProperty('--zt-pop-avail', `${Math.max(120, Math.floor(availableHeight) - 2)}px`);
          },
        }),
        ...(arrowEl.value ? [arrow({ element: arrowEl.value })] : []),
      ],
    });
    Object.assign(floating.style, { left: `${x}px`, top: `${y}px` });
    floating.dataset.placement = placement;
    const a = middlewareData.arrow;
    if (arrowEl.value && a)
      Object.assign(arrowEl.value.style, {
        left: a.x != null ? `${a.x}px` : '',
        top: a.y != null ? `${a.y}px` : '',
      });
  };
  stopAutoUpdate?.();
  stopAutoUpdate = autoUpdate(reference, floating, update);
}

function animateIn() {
  const floating = el.value;
  if (!floating || prefersReducedMotion() || typeof floating.animate !== 'function') return;
  const fromTop = (floating.dataset.placement ?? props.placement).startsWith('top');
  floating.animate(
    [
      { opacity: 0, transform: `translateY(${fromTop ? -6 : 6}px) scale(.98)` },
      { opacity: 1, transform: 'none' },
    ],
    { duration: MS.short, easing: CSS_EASE.out },
  );
  floating.querySelectorAll('[data-popover-row]').forEach((row, i) =>
    (row as HTMLElement).animate(
      [
        { opacity: 0, transform: 'translateY(4px)' },
        { opacity: 1, transform: 'none' },
      ],
      { duration: MS.short, easing: CSS_EASE.out, delay: i * 40, fill: 'backwards' },
    ),
  );
}

function onOpened() {
  isOpen.value = true;
  setTriggerState(true);
  for (const close of openInstances) if (close !== hideNow) close();
  openInstances.add(hideNow);
  emit('open', anchor);
}

function onClosed() {
  stopAutoUpdate?.();
  stopAutoUpdate = null;
  isOpen.value = false;
  openInstances.delete(hideNow);
  setTriggerState(false);
  const active = document.activeElement;
  const focusInside = !active || active === document.body || el.value?.contains(active);
  if (restoreFocus && focusInside && anchor?.isConnected) anchor.focus({ preventScroll: true });
  restoreFocus = true;
  emit('close');
}

/** 打开说明卡。 */
async function show(trigger?: HTMLElement | null) {
  if (isOpen.value && trigger && trigger !== anchor) hideNow();
  anchor = trigger ?? anchor;
  if (mobile.value) {
    sheetOpen.value = true;
    onOpened();
    return;
  }
  const floating = el.value;
  if (!floating) return;
  closingAnim?.cancel();
  managed = true;
  try {
    if (nativePopover()) {
      if (!floating.matches(':popover-open')) floating.showPopover();
    } else {
      floating.hidden = false;
      floating.dataset.open = 'true';
      onOpened();
    }
    await position();
    await nextTick();
    floating.focus({ preventScroll: true });
    animateIn();
  } finally {
    managed = false;
  }
}

function hideNow() {
  const floating = el.value;
  if (mobile.value) {
    sheetOpen.value = false;
    return;
  }
  if (!floating) return;
  if (nativePopover()) {
    if (floating.matches(':popover-open')) floating.hidePopover();
  } else if (floating.dataset.open) {
    floating.hidden = true;
    delete floating.dataset.open;
    onClosed();
  }
}

/** 关闭说明卡（160ms 淡出）；`returnFocus: false` 时不把焦点还给触发元素（如“看示例”）。 */
function hide(opts: { returnFocus?: boolean } = {}) {
  if (!isOpen.value) return;
  if (opts.returnFocus === false) restoreFocus = false;
  const floating = el.value;
  if (mobile.value || !floating || prefersReducedMotion() || typeof floating.animate !== 'function')
    return hideNow();
  closingAnim = floating.animate([{ opacity: 1 }, { opacity: 0 }], {
    duration: MS.micro,
    easing: CSS_EASE.out,
    fill: 'forwards',
  });
  closingAnim.finished
    .then(() => {
      hideNow();
      closingAnim?.cancel();
      closingAnim = null;
    })
    .catch(() => undefined);
}

function toggle(trigger?: HTMLElement | null) {
  if (isOpen.value && (!trigger || trigger === anchor)) hide();
  else void show(trigger);
}

/** 原生 popovertarget：手机上改开底部弹层；桌面记下触发元素。 */
function onBeforeToggle(event: Event) {
  const e = event as ToggleEvent & { source?: Element | null };
  if (e.newState !== 'open' || managed) return;
  const invoker = (e.source as HTMLElement | null | undefined) ?? lastInvoker;
  if (invoker) anchor = invoker;
  if (mobile.value) {
    event.preventDefault();
    sheetOpen.value = true;
    onOpened();
  }
}

function onToggle(event: Event) {
  const e = event as ToggleEvent;
  if (e.newState === 'open') {
    onOpened();
    if (!managed)
      void position().then(() => {
        el.value?.focus({ preventScroll: true });
        animateIn();
      });
  } else onClosed();
}

function rememberInvoker(event: Event) {
  const target = event.target instanceof Element ? event.target.closest('[popovertarget]') : null;
  if (target?.getAttribute('popovertarget') === props.id) lastInvoker = target as HTMLElement;
}

/** 手机上说明卡不是 popover 元素：接管 popovertarget 按钮的点击，改开底部弹层。 */
function onInvokerClick(event: MouseEvent) {
  if (!mobile.value) return;
  const target = event.target instanceof Element ? event.target.closest('[popovertarget]') : null;
  if (target?.getAttribute('popovertarget') !== props.id) return;
  event.preventDefault();
  void show(target as HTMLElement);
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && isOpen.value && !nativePopover() && !mobile.value) hide();
}
function onOutside(event: PointerEvent) {
  if (!isOpen.value || nativePopover() || mobile.value) return;
  const target = event.target as Node;
  if (el.value?.contains(target) || anchor?.contains(target)) return;
  hide();
}
const onMedia = () => {
  if (isOpen.value) hideNow();
  mobile.value = media?.matches ?? false;
};

onMounted(() => {
  media = window.matchMedia?.('(max-width: 767px)');
  mobile.value = media?.matches ?? false;
  media?.addEventListener?.('change', onMedia);
  document.addEventListener('pointerdown', rememberInvoker, true);
  document.addEventListener('keydown', rememberInvoker, true);
  document.addEventListener('keydown', onKeydown);
  document.addEventListener('pointerdown', onOutside);
  document.addEventListener('click', onInvokerClick, true);
  if (el.value && !nativePopover()) el.value.hidden = true;
});
onBeforeUnmount(() => {
  hideNow();
  stopAutoUpdate?.();
  openInstances.delete(hideNow);
  media?.removeEventListener?.('change', onMedia);
  document.removeEventListener('pointerdown', rememberInvoker, true);
  document.removeEventListener('keydown', rememberInvoker, true);
  document.removeEventListener('keydown', onKeydown);
  document.removeEventListener('pointerdown', onOutside);
  document.removeEventListener('click', onInvokerClick, true);
});

defineExpose({ show, hide, toggle, isOpen, element: el });
</script>

<template>
  <div
    v-if="!mobile"
    :id="id"
    ref="el"
    popover="auto"
    role="dialog"
    :aria-labelledby="title ? titleId : undefined"
    tabindex="-1"
    class="zt-popover"
    @beforetoggle="onBeforeToggle"
    @toggle="onToggle"
  >
    <span ref="arrowEl" class="zt-popover-arrow" aria-hidden="true"></span>
    <div class="zt-popover-body" data-lenis-prevent>
      <h3 v-if="title" :id="titleId" class="zt-popover-title" data-popover-row>{{ title }}</h3>
      <slot>
        <p v-if="lead" class="zt-popover-lead" data-popover-row>{{ lead }}</p>
        <dl v-if="rows?.length" class="zt-popover-rows">
          <div v-for="row in rows" :key="row.label" data-popover-row>
            <dt>{{ row.label }}</dt>
            <dd>{{ row.text }}</dd>
          </div>
        </dl>
      </slot>
      <div v-if="$slots.art" class="zt-popover-art" aria-hidden="true" data-popover-row><slot name="art" /></div>
      <div v-if="$slots.actions" class="zt-popover-actions" data-popover-row>
        <slot name="actions" :hide="hide" />
      </div>
    </div>
  </div>
  <BaseDialog
    v-else
    :id="id"
    v-model="sheetOpen"
    variant="sheet"
    class="zt-popover-sheet"
    :labelledby="titleId"
    :trigger="anchor"
    @closed="onClosed"
  >
    <div class="zt-popover-body">
      <h3 :id="titleId" class="zt-popover-title">{{ title }}</h3>
      <slot>
        <p v-if="lead" class="zt-popover-lead">{{ lead }}</p>
        <dl v-if="rows?.length" class="zt-popover-rows">
          <div v-for="row in rows" :key="row.label">
            <dt>{{ row.label }}</dt>
            <dd>{{ row.text }}</dd>
          </div>
        </dl>
      </slot>
      <div v-if="$slots.art" class="zt-popover-art" aria-hidden="true"><slot name="art" /></div>
      <div v-if="$slots.actions" class="zt-popover-actions"><slot name="actions" :hide="hide" /></div>
    </div>
  </BaseDialog>
</template>
