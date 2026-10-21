<script setup lang="ts">
/**
 * D1 首屏底稿网格（07 章 §5）。位于 `section.hero` 最底层（`position: absolute; inset: 0; z-index: 0`），
 * `aria-hidden`、`pointer-events: none`，不改光标。
 * 只保留 `.bp-paper`（CSS 24px 细网格，不依赖 JS）。跟随指针的十字、坐标读数与轴号画布层已按用户意见去掉：
 * 粗糙且与首屏文案、示例窗口互相遮挡。
 */
</script>

<template>
  <div class="deco-hero" aria-hidden="true">
    <div class="bp-paper"></div>
  </div>
</template>
