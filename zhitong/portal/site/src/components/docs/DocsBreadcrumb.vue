<script setup lang="ts">
/** 面包屑（06 章 §7.4）：文档 › {组名} › {页标题}。文档首页不显示。 */
defineProps<{ group: string; title: string }>();
</script>

<template>
  <nav class="docs-breadcrumb" aria-label="面包屑">
    <ol>
      <li><RouterLink to="/docs/">文档</RouterLink></li>
      <li><span>{{ group }}</span></li>
      <li><span aria-current="page">{{ title }}</span></li>
    </ol>
  </nav>
</template>
