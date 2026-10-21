<script setup lang="ts">
/**
 * 徽标：圆角矩形 h 20、rx 4 + 文字（14 单位、500、左右各 6），文字基线 = 矩形顶 + 15（04 章 §7.1）。
 * `anchor="end"` 时 x 为右端。宽度按 `textWidth` 估算（预渲染没有布局）。
 */
import { computed } from 'vue';
import { A } from '../anim';
import { textWidth } from '../../art-tokens';

const props = withDefaults(
  defineProps<{
    x?: number;
    top: number;
    text: string;
    variant?: 'ok' | 'warn' | 'danger' | 'info' | 'muted';
    anchor?: 'start' | 'end';
    a?: string;
    transient?: boolean;
  }>(),
  { x: 0, variant: 'info', anchor: 'start', a: '', transient: false },
);
const width = computed(() => Math.ceil(textWidth(props.text) + 12));
const left = computed(() => (props.anchor === 'end' ? props.x - width.value : props.x));
const attrs = computed(() => (props.a ? A(props.a, props.transient) : {}));
</script>

<template>
  <g class="art-chip" :class="`art-chip-${variant}`" v-bind="attrs">
    <rect :x="left" :y="top" :width="width" height="20" rx="4" />
    <text :x="left + 6" :y="top + 15">{{ text }}</text>
  </g>
</template>
