<script setup lang="ts">
/**
 * 标题锚点（06 章 §7.15）：H2/H3 悬停或获焦时在标题左侧外 24px 显示「#」；触屏不显示（样式表）。
 * 点击按 §9.3 平滑跳转、写入 `#id`、焦点移到标题；无 JS 时是普通页内锚点。
 */
import { scrollToHeading } from '../../docs/docs-ui';

const props = defineProps<{ id: string; text: string }>();

function go(event: MouseEvent) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  void scrollToHeading(props.id);
}
</script>

<template>
  <a class="heading-anchor" :href="`#${id}`" :aria-label="`链接到本节：${text}`" @click="go">#</a>
</template>
