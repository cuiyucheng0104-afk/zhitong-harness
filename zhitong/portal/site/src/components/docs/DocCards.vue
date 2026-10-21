<script setup lang="ts">
/**
 * 全部文档（06 章 §4.4、§7.14）：按 §1.2 渲染 6 张组卡片。卡片内为组名（H3）、组说明、该组各页链接（标题 + summary 一行省略）。
 * 卡片使用光斑（00 章 §6.6）。只用于 index.md 的 `::: doc-cards`。
 */
import { groups } from 'virtual:docs-manifest';
</script>

<template>
  <div class="doc-cards">
    <section v-for="(g, n) in groups" :key="g.name" v-spotlight class="doc-card" :aria-labelledby="`dc-${n + 1}`">
      <h3 :id="`dc-${n + 1}`">{{ g.name }}</h3>
      <p class="doc-card-desc">{{ g.description }}</p>
      <ul>
        <li v-for="item in g.items" :key="item.slug">
          <RouterLink :to="item.path">
            <span class="doc-card-title">{{ item.title }}</span>
            <span class="doc-card-summary">{{ item.summary }}</span>
          </RouterLink>
        </li>
      </ul>
    </section>
  </div>
</template>
