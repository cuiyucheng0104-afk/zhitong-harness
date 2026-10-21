<script setup lang="ts">
/** 按键组（06 章 §7.12）：`kbd:Ctrl+K` → 每键一个 `<kbd>`，不写「+」；读屏读出原文。 */
import { computed } from 'vue';

const props = defineProps<{ keys: string }>();
const list = computed(() => props.keys.split('+').map((k) => k.trim()).filter(Boolean));
</script>

<template>
  <kbd class="kbd-group"><span class="sr-only">{{ keys }}</span><kbd v-for="k in list" :key="k" class="kbd" aria-hidden="true">{{ k }}</kbd></kbd>
</template>
