<script setup lang="ts">
/**
 * 模拟指针（02 章 §10.2）：只在场景二自动播放中出现，表示“这一步由您操作”；旁边 13px 标签“示例：由您判定”。
 * 16×20 箭头，白填充、1px 墨色描边；点击时以箭尖为圆心出现 6px 环 `scale .6 → 1.4`、`opacity .5 → 0`，0.36 s。
 * 位置与点击环进度由 WorkDemo 按场景时刻算好传入（与时间线同步，可暂停、可定位）。
 */
defineProps<{
  visible: boolean;
  x: number;
  y: number;
  /** 点击环进度 0..1；< 0 表示不显示。 */
  ring: number;
}>();
</script>

<template>
  <div
    class="demo-cursor"
    :class="{ 'is-on': visible }"
    :style="{ transform: `translate(${x}px, ${y}px)` }"
    aria-hidden="true"
  >
    <i
      v-if="ring >= 0 && ring <= 1"
      class="demo-cursor-ring"
      :style="{ transform: `scale(${0.6 + 0.8 * ring})`, opacity: 0.5 * (1 - ring) }"
    ></i>
    <svg viewBox="0 0 16 20" width="16" height="20">
      <path d="M1 1v16l4.2-4.1 2.9 6.3 2.6-1.2-2.9-6.2H14z" />
    </svg>
    <span class="demo-cursor-label">示例：由您判定</span>
  </div>
</template>
