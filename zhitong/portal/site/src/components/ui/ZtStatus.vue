<script setup lang="ts">
/**
 * 结果状态与告警徽标（00 章 §8.3；06 章 §7.12 行内徽标）。
 * - `value`：单个徽标（完成 / 部分完成 / 无结果 / 资料不足 / 需人工确认 / 错误 / 警告 / 提示），始终带文字。
 * - `counts`：在徽标后显示告警计数（如“警告 1 · 提示 2”）。
 * - `lines`：逐条列出告警原文。
 * - `manual`：额外显示“需人工确认”徽标。
 */
import { computed } from 'vue';
import { STATUS_LABEL, type AlertLevel, type StatusLine, type StatusValue } from './types';

const props = withDefaults(
  defineProps<{
    value: StatusValue;
    size?: 'sm' | 'md';
    counts?: Partial<Record<AlertLevel, number>>;
    lines?: StatusLine[];
    manual?: boolean;
  }>(),
  { size: 'md', counts: undefined, lines: undefined, manual: false },
);

const LEVELS: AlertLevel[] = ['error', 'warn', 'info'];
const countList = computed(() =>
  LEVELS.filter((l) => (props.counts?.[l] ?? 0) > 0).map((l) => ({
    level: l,
    text: `${STATUS_LABEL[l]} ${props.counts![l]}`,
  })),
);
const tone = (v: StatusValue) =>
  ({
    ok: 'ok',
    partial: 'warn',
    empty: 'muted',
    insufficient: 'warn',
    manual: 'manual',
    error: 'error',
    warn: 'warn',
    info: 'info',
  })[v];
</script>

<template>
  <span v-if="!lines?.length && !countList.length && !manual" :class="['zt-status', `is-${size}`, `tone-${tone(value)}`]">{{
    STATUS_LABEL[value]
  }}</span>
  <span v-else class="zt-status-group" :class="`is-${size}`">
    <span :class="['zt-status', `is-${size}`, `tone-${tone(value)}`]">{{ STATUS_LABEL[value] }}</span>
    <span v-if="manual" :class="['zt-status', `is-${size}`, 'tone-manual']">{{ STATUS_LABEL.manual }}</span>
    <span v-if="countList.length" class="zt-status-counts">
      <span v-for="item in countList" :key="item.level" :class="['zt-status-count', `tone-${item.level}`]">{{
        item.text
      }}</span>
    </span>
    <ul v-if="lines?.length" class="zt-status-lines">
      <li v-for="(line, i) in lines" :key="i" :class="`tone-${line.level}`">
        <span class="zt-status-level">{{ STATUS_LABEL[line.level] }}</span>{{ line.text }}
      </li>
    </ul>
  </span>
</template>
