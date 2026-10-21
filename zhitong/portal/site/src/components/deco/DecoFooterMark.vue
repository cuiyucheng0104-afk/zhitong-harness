<script setup lang="ts">
/**
 * D3 页脚楼群（按用户意见替代 07 章 §7 的单栋透视楼与轴号、标高）。`aria-hidden`、`pointer-events: none`。
 * - 页脚说明行之后单独一行，宽度铺满内容容器，楼房正立面线框从左到右排满。
 * - 预渲染即终态；动效就绪且未减少动效时，挂载后先压低，进入视口（25%）由左到右依次升起，只播一次。
 */
import { onMounted, ref } from 'vue';
import { useInView } from '../../composables/useInView';
import { prefersReducedMotion } from '../../lib/motion';
import { SKYLINE, skyline, towerGrid } from './skyline';

const TOWERS = skyline();
const root = ref<HTMLElement | null>(null);
const state = ref<'still' | 'armed' | 'in'>('still');

useInView(root, {
  threshold: 0.25,
  once: true,
  play: () => {
    if (state.value === 'armed') state.value = 'in';
  },
});

onMounted(() => {
  if (!prefersReducedMotion()) state.value = 'armed';
});
</script>

<template>
  <div ref="root" class="deco-footer" :data-state="state" aria-hidden="true">
    <svg
      class="deco-skyline"
      :viewBox="`0 0 ${SKYLINE.width} ${SKYLINE.height}`"
      preserveAspectRatio="xMidYMax meet"
      focusable="false"
    >
      <g v-for="t in TOWERS" :key="t.order" class="sk-tower" :style="{ '--i': t.order }">
        <path class="sk-grid" :d="towerGrid(t)" />
        <rect class="sk-body" :x="t.x" :y="SKYLINE.height - t.h" :width="t.w" :height="t.h" />
        <rect
          v-if="t.roofW"
          class="sk-body"
          :x="t.x + (t.w - t.roofW) / 2"
          :y="SKYLINE.height - t.h - t.roofH"
          :width="t.roofW"
          :height="t.roofH"
        />
      </g>
      <path class="sk-ground" :d="`M0 ${SKYLINE.height - 0.5}H${SKYLINE.width}`" />
    </svg>
  </div>
</template>
