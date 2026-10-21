<script setup lang="ts">
/**
 * 工具调用条（00 章 §8.3）：中文标签在前、等宽原名在后；状态 进行中（旋转）→ 完成（对勾）+ 耗时；
 * 完成后可显示结果行与警告原文。时间线由调用方驱动（改 `state` 即可），本组件只负责终态与 CSS 过渡。
 */
import { computed } from 'vue';
import type { ToolCallSpec, ToolCallState } from './types';

const props = withDefaults(
  defineProps<{
    tool: ToolCallSpec;
    state?: ToolCallState;
    /** 窄屏省略参数摘要。 */
    compact?: boolean;
  }>(),
  { state: 'done', compact: false },
);

const statusText = computed(
  () => ({ pending: '等待', running: '进行中', done: '完成', error: '失败' })[props.state],
);
</script>

<template>
  <div :class="['zt-tool', `is-${state}`]" :data-state="state">
    <span class="zt-tool-icon" aria-hidden="true">
      <svg v-if="state === 'done'" viewBox="0 0 16 16" class="zt-tool-check">
        <path d="m4 8.5 2.5 2.5L12 5" pathLength="1" />
      </svg>
      <svg v-else-if="state === 'error'" viewBox="0 0 16 16" class="zt-tool-error">
        <path d="m5 5 6 6M11 5l-6 6" />
      </svg>
      <svg v-else viewBox="0 0 16 16" class="zt-tool-spinner"><path d="M8 3a5 5 0 1 1-5 5" /></svg>
    </span>
    <span class="sr-only">{{ statusText }}：</span>
    <span class="zt-tool-label">{{ tool.label }}</span>
    <code class="zt-tool-name mono">{{ tool.name }}</code>
    <code v-if="tool.args && !compact" class="zt-tool-args mono">{{ tool.args }}</code>
    <span v-if="tool.times && tool.times > 1" class="zt-tool-times mono">×{{ tool.times }}</span>
    <span v-if="state === 'done' && tool.elapsed" class="zt-tool-elapsed mono">{{ tool.elapsed }}</span>
    <span v-if="state === 'done' && tool.detail" class="zt-tool-detail">{{ tool.detail }}</span>
    <ul v-if="state === 'done' && tool.warnings?.length" class="zt-tool-warnings">
      <li v-for="(w, i) in tool.warnings" :key="i">{{ w }}</li>
    </ul>
  </div>
</template>
