<script setup lang="ts">
/**
 * D2 清单编码字符场（07 章 §6；05 章 §3.3 插槽）。`.install-panel` 的第一个子元素：
 * `position: absolute; inset: 0; z-index: 0; pointer-events: none; aria-hidden="true"`；内容层由 05 章设为 `z-index: 1`。
 * 预渲染与无 JS 时为空（面板底由 D6 `.deco-navy-grid` 承担）；画布层是懒加载块，首屏可交互后才挂载。
 */
import { defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue';
import { whenDecoReady } from './decoStart';

const InstallFieldCanvas = defineAsyncComponent(() => import('./live/InstallFieldCanvas.vue'));

const root = ref<HTMLElement | null>(null);
const live = ref(false);
let alive = true;

onMounted(() => {
  void whenDecoReady().then(() => {
    if (alive) live.value = true;
  });
});
onBeforeUnmount(() => (alive = false));
</script>

<template>
  <div ref="root" class="deco-install" aria-hidden="true">
    <InstallFieldCanvas v-if="live" :host="root" />
  </div>
</template>
