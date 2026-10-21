<script setup lang="ts">
/**
 * 目录与文件位置（06 章 §7.11）。嵌套列表在构建期由 `text` 代码块解析生成（build/docs-markdown.ts），
 * 这里只提供 `<figure>` 与可选标题；目录项读作「{名称}，文件夹」。
 */
defineProps<{ title?: string }>();
</script>

<template>
  <figure class="filetree">
    <figcaption v-if="title">{{ title }}</figcaption>
    <slot />
  </figure>
</template>
