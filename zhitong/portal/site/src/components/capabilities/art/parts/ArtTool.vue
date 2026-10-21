<script setup lang="ts">
/**
 * 工具调用条（模仿 00 章 §8.3 `ZtToolCall`）：圆角矩形 h 24、rx 12、白底、1px 线；
 * 左 12 处状态图标（转圈 `<a>-spin` 为过程元素，对勾 `<a>-ok`）；中文标签 x + 24，等宽原名其后 6，可选结果 `<a>-res` 再后 6。
 */
import { computed } from 'vue';
import { A } from '../anim';
import { textWidth } from '../../art-tokens';

const props = withDefaults(
  defineProps<{
    x?: number;
    top: number;
    label: string;
    name: string;
    result?: string;
    a: string;
    transient?: boolean;
  }>(),
  { x: 0, result: '', transient: false },
);
const labelX = computed(() => props.x + 24);
const nameX = computed(() => labelX.value + textWidth(props.label) + 6);
const resX = computed(() => nameX.value + textWidth(props.name, true) + 6);
const width = computed(() =>
  Math.ceil((props.result ? resX.value + textWidth(props.result) : resX.value - 6) - props.x + 12),
);
const cx = computed(() => props.x + 12);
const cy = computed(() => props.top + 12);
</script>

<template>
  <g class="art-tool" v-bind="A(a, transient)">
    <rect :x="x" :y="top" :width="width" height="24" rx="12" class="art-tool-bg" />
    <path
      v-bind="A(`${a}-spin`, true)"
      class="art-spin"
      :d="`M${cx + 5} ${cy} A5 5 0 1 1 ${cx} ${cy - 5}`"
      fill="none"
    />
    <path
      v-bind="A(`${a}-ok`)"
      class="art-ok"
      :d="`M${cx - 4} ${cy} l2.8 2.8 l5.2 -5.6`"
      fill="none"
    />
    <text class="at" :x="labelX" :y="top + 17">{{ label }}</text>
    <text class="am" :x="nameX" :y="top + 17">{{ name }}</text>
    <text v-if="result" class="as" v-bind="A(`${a}-res`)" :x="resX" :y="top + 17">{{
      result
    }}</text>
  </g>
</template>
