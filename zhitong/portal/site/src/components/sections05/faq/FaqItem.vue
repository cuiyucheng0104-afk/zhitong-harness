<script setup lang="ts">
/**
 * 一问（05 章 §4.3–§4.7）：原生 `<details>` / `<summary>`，无 JS 时照常展开收起；水合后由 FaqSection 拦截 `summary` 点击做动画。
 * `summary` 内为 `<h3>`；主题小标签对读屏追加在问题后（“它会替我算造价吗？，结果”）。复制链接按钮水合后才渲染。
 */
import { RouterLink } from 'vue-router';
import AppIcon from '../../AppIcon.vue';
import { FAQ_COPY, GROUP_LABEL, type FaqItem } from '../../../data/faq';

defineProps<{
  item: FaqItem;
  open: boolean;
  hidden: boolean;
  hydrated: boolean;
  copied: boolean;
}>();
const emit = defineEmits<{ toggle: [event: MouseEvent]; native: [event: Event]; copy: [] }>();
</script>

<template>
  <details
    :id="`faq-${item.id}`"
    class="faq-item"
    :open="open"
    :hidden="hidden"
    :data-group="item.group"
    @toggle="emit('native', $event)"
  >
    <summary @click="hydrated && emit('toggle', $event)">
      <h3 class="faq-q">
        {{ item.question }}<span class="sr-only">，{{ GROUP_LABEL[item.group] }}</span>
      </h3>
      <span class="faq-tag" aria-hidden="true">{{ GROUP_LABEL[item.group] }}</span>
      <AppIcon name="plus" class="faq-plus" />
    </summary>
    <div class="faq-answer">
      <div class="faq-answer-inner">
        <p>{{ item.answer }}</p>
        <div v-if="item.doc || hydrated" class="faq-meta">
          <RouterLink v-if="item.doc" class="text-link faq-related" :to="item.doc.href"
            >{{ FAQ_COPY.related }}{{ item.doc.title }}<AppIcon name="arrow" class="icon"
          /></RouterLink>
          <button
            v-if="hydrated"
            type="button"
            class="icon-button faq-copy"
            :class="{ 'is-copied': copied }"
            :aria-label="FAQ_COPY.copyLabel"
            @click="emit('copy')"
          >
            <AppIcon name="copy" class="icon-copy" /><AppIcon name="check" class="icon-check" />
          </button>
        </div>
      </div>
    </div>
  </details>
</template>
