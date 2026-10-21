<script setup lang="ts">
/**
 * 侧栏（06 章 §1.2、§7.2）：搜索按钮 +「文档首页」+ 6 个组。组名用 `<p>`（不用标题标签），组标题不可点击、不折叠。
 * 当前页 `aria-current="page"`。进入页面时若当前项不在侧栏可视区内，只滚动侧栏容器使其居中（不滚动页面）。
 * 桌面侧栏与抽屉共用本组件，`idPrefix` 区分组名 id。
 */
import { nextTick, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { docs, groups } from 'virtual:docs-manifest';
import DocsSearchTrigger from './DocsSearchTrigger.vue';

const props = withDefaults(defineProps<{ idPrefix?: string; scroller?: HTMLElement | null }>(), {
  idPrefix: 'sg',
  scroller: null,
});
const emit = defineEmits<{ navigate: [] }>();
const route = useRoute();
const list = ref<HTMLElement | null>(null);
const home = docs.find((d) => d.slug === 'index')!;

/** 当前项不在滚动容器可视区时，把它滚到容器中间。 */
function centerCurrent() {
  const box = props.scroller ?? list.value?.closest<HTMLElement>('.docs-sidebar') ?? null;
  const item = list.value?.querySelector<HTMLElement>('[aria-current="page"]');
  if (!box || !item) return;
  const b = box.getBoundingClientRect();
  const r = item.getBoundingClientRect();
  if (r.top >= b.top && r.bottom <= b.bottom) return;
  box.scrollTop += r.top - b.top - (b.height - r.height) / 2;
}

onMounted(() => void nextTick(centerCurrent));
watch(
  () => route.path,
  () => void nextTick(centerCurrent),
);
defineExpose({ centerCurrent });
</script>

<template>
  <div ref="list" class="sidebar-inner">
    <DocsSearchTrigger variant="sidebar" />
    <nav class="sidebar-nav" aria-label="文档">
      <ul class="sidebar-list sidebar-home">
        <li>
          <RouterLink class="sidebar-link" :to="home.path" @click="emit('navigate')">文档首页</RouterLink>
        </li>
      </ul>
      <template v-for="(g, n) in groups" :key="g.name">
        <p :id="`${idPrefix}-${n + 1}`" class="sidebar-group">{{ g.name }}</p>
        <ul class="sidebar-list" :aria-labelledby="`${idPrefix}-${n + 1}`">
          <li v-for="item in g.items" :key="item.slug">
            <RouterLink class="sidebar-link" :to="item.path" @click="emit('navigate')">{{ item.title }}</RouterLink>
          </li>
        </ul>
      </template>
    </nav>
  </div>
</template>
