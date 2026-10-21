<script setup lang="ts">
/**
 * 提示框（06 章 §7.7）：注意 / 提示 / 需人工确认。类型始终以文字出现在标题里（不只靠颜色）；
 * 有自定义标题时写作「类型：标题」。
 */
import { computed } from 'vue';

const props = defineProps<{ type: 'note' | 'tip' | 'confirm'; title?: string }>();
const LABEL = { note: '注意', tip: '提示', confirm: '需人工确认' } as const;
const label = computed(() => LABEL[props.type]);
const full = computed(() => (props.title ? `${label.value}：${props.title}` : label.value));
</script>

<template>
  <aside :class="['callout', `callout-${type}`]" role="note" :aria-label="full">
    <p class="callout-head">
      <svg class="callout-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <g v-if="type === 'note'"><path d="M12 3.5 21.5 20h-19z" /><path d="M12 10v4.5M12 17v.5" /></g>
        <g v-else-if="type === 'tip'">
          <path d="M9 18h6M10 21h4" />
          <path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3z" />
        </g>
        <g v-else>
          <path d="M8 13.5a4 4 0 1 1 8 0" /><path d="M9 13.5 7.5 18h9L15 13.5" /><path d="M5 21h14" />
          <path d="m9.6 8.6 1.6 1.6 3.2-3.4" />
        </g>
      </svg>
      <span class="callout-kind">{{ label }}</span><span v-if="title" class="callout-title">：{{ title }}</span>
    </p>
    <div class="callout-body"><slot /></div>
  </aside>
</template>
