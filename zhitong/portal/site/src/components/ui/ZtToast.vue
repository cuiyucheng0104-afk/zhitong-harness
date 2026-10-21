<script setup lang="ts">
/**
 * 复制提示（01 章 §11）。全站一个实例，挂在 App.vue 根部。
 * 视觉元素 `popover="manual"`，每次显示 `showPopover()`，模态对话框打开时也在其上；视觉元素 `aria-hidden`，
 * 朗读由 useToast 写入对话框内或页面的朗读区。
 * 进入 280ms（`translate(-50%, 12px) → (-50%, 0)`），停留 1600ms（错误 3200ms），退出 160ms 下移 6px；
 * 新消息替换文字并重置计时，不重播进入动画。减少动效时只做 160ms 透明度变化。
 */
import { onBeforeUnmount, ref, watch } from 'vue';
import AppIcon from '../AppIcon.vue';
import { prefersReducedMotion } from '../../lib/motion';
import { CSS_EASE, MS } from '../../lib/motion-tokens';
import { toastState } from '../../composables/useToast';

const el = ref<HTMLElement | null>(null);
const visible = ref(false);
let timer: ReturnType<typeof setTimeout> | undefined;
let leaving: Animation | null = null;

const supportsPopover = () => typeof HTMLElement !== 'undefined' && 'showPopover' in HTMLElement.prototype;

function open(node: HTMLElement) {
  if (supportsPopover()) {
    // 已显示时先收起再打开，使它重新排到最新打开的模态对话框之上。
    if (node.matches(':popover-open')) node.hidePopover();
    node.showPopover();
  }
  node.hidden = false;
}

function closeNow() {
  const node = el.value;
  visible.value = false;
  if (!node) return;
  if (supportsPopover() && node.matches(':popover-open')) node.hidePopover();
  node.hidden = true;
}

function leave() {
  const node = el.value;
  if (!node || typeof node.animate !== 'function') return closeNow();
  const reduced = prefersReducedMotion();
  leaving = node.animate(
    [
      { opacity: 1, transform: 'translate(-50%, 0)' },
      { opacity: 0, transform: reduced ? 'translate(-50%, 0)' : 'translate(-50%, 6px)' },
    ],
    { duration: MS.micro, easing: CSS_EASE.out, fill: 'forwards' },
  );
  leaving.finished
    .then(() => {
      closeNow();
      leaving?.cancel();
      leaving = null;
    })
    .catch(() => undefined);
}

watch(
  () => toastState.seq,
  () => {
    const node = el.value;
    if (!node) return;
    clearTimeout(timer);
    leaving?.cancel();
    leaving = null;
    const wasVisible = visible.value;
    visible.value = true;
    open(node);
    if (!wasVisible && typeof node.animate === 'function') {
      const reduced = prefersReducedMotion();
      node.animate(
        reduced
          ? [{ opacity: 0 }, { opacity: 1 }]
          : [
              { opacity: 0, transform: 'translate(-50%, 12px)' },
              { opacity: 1, transform: 'translate(-50%, 0)' },
            ],
        { duration: reduced ? MS.micro : MS.short, easing: CSS_EASE.out },
      );
    }
    timer = setTimeout(leave, (wasVisible ? 0 : MS.short) + toastState.duration);
  },
);

onBeforeUnmount(() => clearTimeout(timer));
</script>

<template>
  <div
    ref="el"
    class="zt-toast"
    :class="`is-${toastState.tone}`"
    popover="manual"
    aria-hidden="true"
    hidden
  >
    <AppIcon :name="toastState.tone === 'error' ? 'alert' : 'check'" />
    <span>{{ toastState.message }}</span>
  </div>
</template>
