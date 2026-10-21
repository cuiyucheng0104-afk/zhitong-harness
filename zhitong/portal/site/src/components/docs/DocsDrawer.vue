<script setup lang="ts">
/**
 * 文档目录抽屉（06 章 §4.3、§9.2）：平板与手机上从左滑入，宽 min(85vw, 320px)，内容与桌面侧栏相同（含搜索按钮）。
 * BaseDialog（原生模态 `<dialog>`）：点击遮罩、Esc、点击任一链接都关闭；Esc 与遮罩关闭后焦点回到「文档目录」按钮，
 * 点链接关闭后由页面切换把焦点移到正文。动效：面板 translateX(-100% → 0)、遮罩 0 → 0.4，280ms；关闭 160ms。
 * 内容只在打开时渲染（避免与桌面侧栏的 id、链接重复）。
 */
import { ref } from 'vue';
import BaseDialog from '../BaseDialog.vue';
import DocsSidebar from './DocsSidebar.vue';
import { CSS_EASE, MS } from '../../lib/motion-tokens';
import { docsUi } from '../../docs/docs-ui';

defineProps<{ trigger: HTMLElement | null }>();
const dialog = ref<InstanceType<typeof BaseDialog> | null>(null);
const panel = ref<HTMLElement | null>(null);

function setOpen(v: boolean) {
  docsUi.drawerOpen = v;
}
function close(returnFocus = true) {
  dialog.value?.close({ returnFocus });
}

function enter(el: HTMLDialogElement) {
  const opts = { duration: MS.short, easing: CSS_EASE.out };
  el.animate([{ opacity: 0 }, { opacity: 1 }], { ...opts, pseudoElement: '::backdrop' });
  return el.animate([{ transform: 'translateX(-100%)' }, { transform: 'none' }], opts).finished;
}
function leave(el: HTMLDialogElement) {
  const opts = { duration: MS.micro, easing: CSS_EASE.out, fill: 'forwards' as const };
  el.animate([{ opacity: 1 }, { opacity: 0 }], { ...opts, pseudoElement: '::backdrop' });
  return el.animate([{ transform: 'none' }, { transform: 'translateX(-100%)' }], opts).finished;
}
</script>

<template>
  <BaseDialog
    ref="dialog"
    :model-value="docsUi.drawerOpen"
    labelledby="docs-drawer-title"
    :trigger="trigger"
    variant="custom"
    class="docs-drawer"
    :enter="enter"
    :leave="leave"
    @update:model-value="setOpen"
  >
    <div ref="panel" class="drawer-panel">
      <div class="drawer-head">
        <p id="docs-drawer-title" class="drawer-title">文档目录</p>
        <button type="button" class="icon-button drawer-close" aria-label="关闭目录" @click="close()">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m6 6 12 12M18 6 6 18" /></svg>
        </button>
      </div>
      <DocsSidebar v-if="docsUi.drawerOpen" id-prefix="sgd" :scroller="panel" @navigate="close(false)" />
    </div>
  </BaseDialog>
</template>
