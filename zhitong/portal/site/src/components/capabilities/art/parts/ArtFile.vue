<script setup lang="ts">
/** 文件图标 12×15（右上 4px 折角）+ 名称（x + 18），04 章 §7.1。y 为名称基线，图标顶在 y − 12。 */
import { computed } from 'vue';
import { A } from '../anim';

const props = withDefaults(
  defineProps<{
    x?: number;
    y: number;
    name: string;
    kind?: 'xlsx' | 'docx' | 'pdf' | 'dwg' | 'md' | 'json' | 'txt';
    cls?: string;
    a?: string;
    transient?: boolean;
  }>(),
  { x: 0, kind: 'txt', cls: 'at', a: '', transient: false },
);
const COLORS = {
  xlsx: '#1e865f',
  docx: '#2b5fd9',
  pdf: '#c2412d',
  dwg: '#5c6d82',
  md: '#5c6d82',
  json: '#5c6d82',
  txt: '#5c6d82',
} as const;
const color = computed(() => COLORS[props.kind]);
const top = computed(() => props.y - 12);
const attrs = computed(() => (props.a ? A(props.a, props.transient) : {}));
</script>

<template>
  <g class="art-file" v-bind="attrs">
    <path
      :d="`M${x} ${top} h8 l4 4 v11 h-12 z`"
      :fill="color"
      fill-opacity="0.14"
      :stroke="color"
      stroke-width="1.2"
      stroke-linejoin="round"
    />
    <path
      :d="`M${x + 8} ${top} v4 h4`"
      fill="none"
      :stroke="color"
      stroke-width="1.2"
      stroke-linejoin="round"
    />
    <text :class="cls" :x="x + 18" :y="y">{{ name }}</text>
  </g>
</template>
