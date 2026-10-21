<script setup lang="ts">
/**
 * 对话线程（03 章 §2.2、§2.3）：线程标题、用户气泡、8 行 `ZtToolCall`（紧凑，不显示耗时）。
 * `done` 为已完成的行数（钉住时间线驱动，未完成的行显示进行中图标）；省略时全部完成。
 * `idle` 行整行半透明，状态图标为短横线（state 用 done 以显示结果行，图标由样式换成短横线）；结果里的“需人工确认”用人工确认徽标。
 */
import ZtToolCall from '../ui/ZtToolCall.vue';
import ZtStatus from '../ui/ZtStatus.vue';
import { MANUAL_SUFFIX, PROBLEM_COPY, type ThreadRow } from '../../data/problem';

defineProps<{ rows: readonly ThreadRow[]; done?: number }>();

const detail = (row: ThreadRow) =>
  row.manual && row.result.endsWith(MANUAL_SUFFIX) ? row.result.slice(0, -MANUAL_SUFFIX.length) : row.result;
</script>

<template>
  <div class="conv">
    <p class="conv__title">{{ PROBLEM_COPY.threadTitle }}</p>
    <p class="conv__bubble">{{ PROBLEM_COPY.userBubble }}</p>
    <ol class="conv__rows">
      <li
        v-for="(row, i) in rows"
        :key="row.id"
        :class="['conv-row', { 'is-idle': row.muted }]"
        :data-row="row.id"
      >
        <ZtToolCall
          compact
          :tool="{ label: row.label, name: row.command ?? '', detail: detail(row) }"
          :state="row.muted || done === undefined || i < done ? 'done' : 'running'"
        />
        <ZtStatus v-if="row.manual" class="conv-row__manual" value="manual" size="sm" />
      </li>
    </ol>
  </div>
</template>
