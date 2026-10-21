<script setup lang="ts">
/** 上一页 / 下一页（06 章 §7.5）：顺序 = 清单 `docs` 的顺序（首页在最前）；没有对应页时该侧留空。 */
import { computed } from 'vue';
import { docs } from 'virtual:docs-manifest';

const props = defineProps<{ slug: string }>();
const at = computed(() => docs.findIndex((d) => d.slug === props.slug));
const prev = computed(() => (at.value > 0 ? docs[at.value - 1] : null));
const next = computed(() => (at.value >= 0 && at.value < docs.length - 1 ? docs[at.value + 1] : null));
const label = (d: (typeof docs)[number]) => (d.slug === 'index' ? '文档首页' : d.title);
</script>

<template>
  <nav class="docs-pager" aria-label="上一页与下一页">
    <RouterLink v-if="prev" class="pager-card pager-prev" :to="prev.path" :aria-label="`上一页：${label(prev)}`">
      <span class="pager-dir" aria-hidden="true">上一页</span>
      <span class="pager-title" aria-hidden="true">{{ label(prev) }}</span>
    </RouterLink>
    <span v-else class="pager-empty"></span>
    <RouterLink v-if="next" class="pager-card pager-next" :to="next.path" :aria-label="`下一页：${label(next)}`">
      <span class="pager-dir" aria-hidden="true">下一页</span>
      <span class="pager-title" aria-hidden="true">{{ label(next) }}</span>
    </RouterLink>
  </nav>
</template>
