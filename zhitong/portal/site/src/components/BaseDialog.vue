<script setup lang="ts">
/**
 * 通用模态对话框（01 章 §7.5、§11）。
 * - 原生 `<dialog>` + `showModal()`：背景惰性、焦点只在对话框内循环；Esc 与点遮罩关闭，关闭后焦点回到 trigger。
 * - 动画用 Web Animations API（不依赖 GSAP，文档页可用）；减少动效时直接显示与关闭。
 * - `variant`：`center`（默认）、`auto`（≥ 768px 居中、≤ 767px 底部弹层）、`sheet`、`custom`（调用方经 enter/leave 自己动画）。
 * - 底部弹层带拖拽把手：下拉 > 80px 松手关闭，否则 280ms 回弹。
 * - 打开时 `lockSmoothScroll()`、登记模态（useAutoplay 以 `dialog` 暂停），`body.modal-open`。
 * - 内含朗读区 `[data-dialog-status]`（useToast 写入）。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { registerModal } from '../lib/modal-state';
import { prefersReducedMotion } from '../lib/motion';
import { CSS_EASE, MS } from '../lib/motion-tokens';
import { lockSmoothScroll, unlockSmoothScroll } from '../lib/smooth-scroll';

export type DialogVariant = 'auto' | 'center' | 'sheet' | 'custom';

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    labelledby: string;
    trigger?: HTMLElement | null;
    variant?: DialogVariant;
    /** variant=custom 时的打开动画；返回动画结束的 Promise。 */
    enter?: (dialog: HTMLDialogElement) => Promise<unknown> | void;
    /** variant=custom 时的关闭动画；结束后才真正 close()。 */
    leave?: (dialog: HTMLDialogElement) => Promise<unknown> | void;
  }>(),
  { trigger: null, variant: 'center', enter: undefined, leave: undefined },
);
const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  opened: [element: HTMLDialogElement];
  closed: [];
}>();

const element = ref<HTMLDialogElement | null>(null);
const sheet = ref(props.variant === 'sheet');
const dragY = ref(0);
let mounted = false;
let returnFocus: HTMLElement | null = null;
let unregister: (() => void) | null = null;
let closing = false;
let dragStart: number | null = null;
let skipFocusReturn = false;

const classes = computed(() => ({
  'zt-dialog': true,
  'is-sheet': sheet.value,
  'is-center': !sheet.value && props.variant !== 'custom',
}));

function animate(el: Element, keyframes: Keyframe[], options: KeyframeAnimationOptions) {
  if (typeof (el as HTMLElement).animate !== 'function') return null;
  try {
    return (el as HTMLElement).animate(keyframes, options);
  } catch {
    // 不支持的伪元素动画等情况，按无动画处理。
    return null;
  }
}

function finished(animations: (Animation | null)[]) {
  return Promise.all(animations.map((a) => a?.finished.catch(() => undefined)));
}

function playEnter(dialog: HTMLDialogElement) {
  if (prefersReducedMotion()) return;
  if (props.variant === 'custom') {
    void props.enter?.(dialog);
    return;
  }
  const easeOut = CSS_EASE.out;
  if (sheet.value) {
    animate(dialog, [{ transform: 'translateY(100%)' }, { transform: 'none' }], {
      duration: MS.base,
      easing: easeOut,
    });
  } else {
    animate(dialog, [{ opacity: 0 }, { opacity: 1 }], {
      duration: MS.short,
      easing: easeOut,
      pseudoElement: '::backdrop',
    });
    animate(
      dialog,
      [
        { opacity: 0, transform: 'translateY(16px) scale(.98)' },
        { opacity: 1, transform: 'none' },
      ],
      { duration: MS.short, easing: easeOut },
    );
  }
  dialog.querySelectorAll('[data-stagger]').forEach((node, i) => {
    animate(
      node,
      [
        { opacity: 0, transform: 'translateY(8px)' },
        { opacity: 1, transform: 'none' },
      ],
      { duration: MS.short, easing: easeOut, delay: 60 + i * 40, fill: 'backwards' },
    );
  });
}

function playLeave(dialog: HTMLDialogElement): Promise<unknown> | null {
  if (prefersReducedMotion()) return null;
  if (props.variant === 'custom') return props.leave?.(dialog) ?? null;
  const opts = { duration: MS.micro, easing: CSS_EASE.out, fill: 'forwards' as const };
  const list = [
    animate(dialog, [{ opacity: 1 }, { opacity: 0 }], opts),
    animate(dialog, [{ opacity: 1 }, { opacity: 0 }], { ...opts, pseudoElement: '::backdrop' }),
  ];
  return list.some(Boolean) ? finished(list) : null;
}

function syncScrollLock() {
  document.body.classList.toggle('modal-open', Boolean(document.querySelector('dialog[open]')));
}

/** 请求关闭（父组件经 v-model 收到 false）。 */
function close(opts: { returnFocus?: boolean } = {}) {
  if (opts.returnFocus === false) skipFocusReturn = true;
  emit('update:modelValue', false);
}

function release() {
  if (!unregister) return;
  unregister();
  unregister = null;
  unlockSmoothScroll();
}

function afterClose() {
  closing = false;
  dragY.value = 0;
  for (const a of element.value?.getAnimations?.() ?? []) a.cancel();
  release();
  syncScrollLock();
  emit('update:modelValue', false);
  // 先归还焦点，再通知父组件：父组件在 closed 里做的跳转（如滚到章节并聚焦标题）不会被覆盖。
  if (!skipFocusReturn && returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
  skipFocusReturn = false;
  emit('closed');
}

function finishClose(dialog: HTMLDialogElement) {
  if (dialog.open) dialog.close();
}

function sync() {
  const dialog = element.value;
  if (!mounted || !dialog) return;
  if (props.modelValue && !dialog.open) {
    closing = false;
    returnFocus =
      props.trigger ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    sheet.value =
      props.variant === 'sheet' ||
      (props.variant === 'auto' && (window.matchMedia?.('(max-width: 767px)').matches ?? false));
    dialog.showModal();
    lockSmoothScroll();
    unregister = registerModal();
    syncScrollLock();
    emit('opened', dialog);
    playEnter(dialog);
  } else if (!props.modelValue && dialog.open && !closing) {
    closing = true;
    const leaving = playLeave(dialog);
    if (leaving) void Promise.resolve(leaving).then(() => finishClose(dialog));
    else finishClose(dialog);
  }
}

function onBackdrop(event: MouseEvent) {
  const dialog = element.value;
  if (!dialog || event.target !== dialog) return;
  const rect = dialog.getBoundingClientRect();
  if (
    event.clientX < rect.left ||
    event.clientX > rect.right ||
    event.clientY < rect.top ||
    event.clientY > rect.bottom
  )
    close();
}

function onHandleDown(event: PointerEvent) {
  if (!sheet.value) return;
  dragStart = event.clientY;
  (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
}
function onHandleMove(event: PointerEvent) {
  if (dragStart === null) return;
  dragY.value = Math.max(0, event.clientY - dragStart);
}
/** 轻点把手（没有拖动）也关闭；拖动过的那次 click 不处理。 */
let handleDragged = false;
function onHandleClick() {
  if (handleDragged) {
    handleDragged = false;
    return;
  }
  close();
}
function onHandleUp() {
  if (dragStart === null) return;
  dragStart = null;
  const dialog = element.value;
  const distance = dragY.value;
  handleDragged = distance > 4;
  if (distance > 80) {
    close();
    return;
  }
  if (dialog && distance > 0 && !prefersReducedMotion())
    animate(dialog, [{ transform: `translateY(${distance}px)` }, { transform: 'none' }], {
      duration: MS.short,
      easing: CSS_EASE.out,
    });
  dragY.value = 0;
}

watch(() => props.modelValue, sync, { flush: 'post' });
onMounted(() => {
  mounted = true;
  sync();
});
onBeforeUnmount(() => {
  mounted = false;
  release();
  if (element.value?.open) element.value.close();
  syncScrollLock();
});
defineExpose({ element, close, sheet });
</script>

<template>
  <dialog
    ref="element"
    :class="classes"
    :aria-labelledby="labelledby"
    data-lenis-prevent
    :style="dragY ? { transform: `translateY(${dragY}px)` } : undefined"
    @cancel.prevent="close()"
    @close="afterClose"
    @click="onBackdrop"
  >
    <div
      v-if="sheet"
      class="sheet-handle"
      role="button"
      tabindex="-1"
      aria-label="下拉关闭"
      @click="onHandleClick"
      @pointerdown="onHandleDown"
      @pointermove="onHandleMove"
      @pointerup="onHandleUp"
      @pointercancel="onHandleUp"
    >
      <span></span>
    </div>
    <slot :close="close" :sheet="sheet" />
    <div class="sr-only" role="status" aria-live="polite" data-dialog-status></div>
  </dialog>
</template>
