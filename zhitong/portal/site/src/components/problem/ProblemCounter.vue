<script setup lang="ts">
/**
 * 计数器（03 章 §2.2、§2.7）：旧方式“60–150 次点击”+ 注；新方式“一次对话”+ 注（只在钉住模式出现）。
 * - `scrub`：数字由钉住时间线写入（ProblemSection 驱动）。
 * - `count`：进入视口后 `useCountUp` 0 → 60（`DUR.long`、`EASE.expo`），随后“–150”淡入（`DUR.short`）。
 * 可见数字 `aria-hidden`，读屏只读真实文本“约 60 至 150 次点击（估算值，非实测）”。
 */
import { ref } from 'vue';
import { useCountUp } from '../../composables/useCountUp';
import { useInView } from '../../composables/useInView';
import { prefersReducedMotion } from '../../lib/motion';
import { PROBLEM_COPY } from '../../data/problem';

const props = defineProps<{ mode: 'scrub' | 'count' }>();

const root = ref<HTMLElement | null>(null);
const head = ref<HTMLElement | null>(null);
const tailHidden = ref(false);
const C = PROBLEM_COPY;

const counter = useCountUp(head, { to: 60, format: (v) => String(Math.round(v)), trigger: 'manual' });

useInView(root, {
  threshold: 0.35,
  once: true,
  play: () => {
    if (props.mode !== 'count' || prefersReducedMotion()) return;
    if (!document.documentElement.classList.contains('motion-ready')) return;
    tailHidden.value = true;
    void counter.play().then(() => {
      tailHidden.value = false;
    });
  },
});

defineExpose({ root });
</script>

<template>
  <div ref="root" class="problem-counter" :data-mode="mode">
    <p class="sr-only">{{ C.counterSr }}</p>
    <div class="counter-old" aria-hidden="true">
      <p class="counter-main">
        <span class="counter-value mono"
          ><span ref="head" class="counter-head">{{ C.counterOld.head }}</span
          ><span :class="['counter-tail', { 'is-hidden': tailHidden }]">{{ C.counterOld.tail }}</span></span
        >
        <span class="counter-unit">{{ C.counterOld.unit }}</span>
      </p>
      <p class="counter-note">{{ C.counterOld.note }}</p>
    </div>
    <div class="counter-new" aria-hidden="true">
      <p class="counter-main"><span class="counter-value">{{ C.counterNew.value }}</span></p>
      <p class="counter-note">{{ C.counterNew.note }}</p>
    </div>
  </div>
</template>
