<script setup lang="ts">
/**
 * 文档首页外框（06 章 §4.4）：深色区（H1「文档」、index.md 的导语、大号搜索触发器），下方为 index.md 正文（单栏 ≤ 1040px）。
 * 文档首页没有侧栏与本页目录，也不显示面包屑。
 */
import type { DocEntry } from 'virtual:docs-manifest';
import DocsSearchTrigger from '../../components/docs/DocsSearchTrigger.vue';

defineProps<{ doc: DocEntry }>();
</script>

<template>
  <div class="docs-home">
    <section class="docs-hero on-dark deco-navy-grid" aria-labelledby="docs-home-title">
      <div class="docs-hero-inner">
        <h1 id="docs-home-title" class="docs-title" tabindex="-1">文档</h1>
        <p class="docs-hero-lead">{{ doc.summary }}</p>
        <DocsSearchTrigger variant="hero" />
      </div>
    </section>
    <div class="docs-home-body"><slot /></div>
  </div>
</template>
