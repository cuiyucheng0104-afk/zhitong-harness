<script setup lang="ts">
/**
 * 文档页外框（06 章 §4.2、§4.3、§7.4–§7.6）：面包屑、H1（tabindex=-1）、导语（summary）、更新于、
 * 平板与手机上的本页目录折叠块，正文（默认插槽，即 `.md` 编译出的组件），上一页/下一页，联系服务方一行。
 * 不做「这页有帮助吗」投票；`hasContact === false` 时不渲染联系行。
 */
import { computed, ref } from 'vue';
import type { DocEntry } from 'virtual:docs-manifest';
import DocsBreadcrumb from '../../components/docs/DocsBreadcrumb.vue';
import DocsPager from '../../components/docs/DocsPager.vue';
import { scrollToHeading } from '../../docs/docs-ui';
import { SUPPORT_CONTACT } from '../../data/site';

const props = defineProps<{ doc: DocEntry }>();
const details = ref<HTMLDetailsElement | null>(null);
const h2Count = computed(() => props.doc.headings.filter((h) => h.level === 2).length);
const contact = SUPPORT_CONTACT;

function go(id: string) {
  if (details.value) details.value.open = false;
  void scrollToHeading(id);
}
</script>

<template>
  <article class="docs-article" :data-slug="doc.slug">
    <DocsBreadcrumb :group="doc.group" :title="doc.title" />
    <h1 class="docs-title" tabindex="-1">{{ doc.title }}</h1>
    <p class="docs-lead">{{ doc.summary }}</p>
    <p class="docs-updated">更新于 <time :datetime="doc.updated">{{ doc.updated }}</time></p>
    <details v-if="h2Count >= 2" ref="details" class="docs-toc-inline">
      <summary>本页目录</summary>
      <ul>
        <li v-for="h in doc.headings" :key="h.id" :class="`toc-l${h.level}`">
          <a :href="`#${h.id}`" @click.prevent="go(h.id)">{{ h.text }}</a>
        </li>
      </ul>
    </details>
    <slot />
    <DocsPager :slug="doc.slug" />
    <p v-if="contact" class="docs-feedback">
      内容有误或不清楚？请联系服务方：<a v-if="'href' in contact" :href="contact.href">{{ contact.value }}</a
      ><span v-else>微信 {{ contact.value }}</span>
    </p>
  </article>
</template>
