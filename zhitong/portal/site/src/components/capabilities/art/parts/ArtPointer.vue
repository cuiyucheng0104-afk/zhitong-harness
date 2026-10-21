<script setup lang="ts">
/** 指针（04 章 §7.1）：光标路径 + 按下时扩散的环；起点写在 data-x / data-y，由 `kit.click` 移动。 */
defineProps<{ x: number; y: number }>();
</script>

<template>
  <g
    class="art-pointer"
    data-a="ptr"
    data-transient
    :data-x="x"
    :data-y="y"
    :transform="`translate(${x} ${y})`"
  >
    <circle data-a="ptr-ring" data-transient r="4" class="art-ptr-ring" />
    <path d="M0 0 L0 15 L4 11 L7 17 L9.5 16 L6.5 10 L12 10 Z" class="art-ptr" />
  </g>
</template>
