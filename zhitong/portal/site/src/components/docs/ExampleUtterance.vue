<script setup lang="ts">
/**
 * 一条“您可以这样说”（06 章 §7.10）：水合后是整行复制按钮（复制文字不含引号），图标 copy → check 1.6 秒复原，
 * 提示「已复制，可粘贴到对话框」；失败时提示并选中该句。无 JS 时是普通引用样式（无复制图标）。
 */
import { onBeforeUnmount, ref } from 'vue';
import AppIcon from '../AppIcon.vue';
import { useCopy } from '../../composables/useCopy';
import { useHydrated } from './useHydrated';

const props = defineProps<{ text: string }>();
const hydrated = useHydrated();
const copied = ref(false);
const sentence = ref<HTMLElement | null>(null);
const { copy } = useCopy();
let timer: ReturnType<typeof setTimeout> | undefined;

async function onCopy() {
  const ok = await copy(props.text, { success: '已复制，可粘贴到对话框', fallbackSelect: sentence.value });
  if (!ok) return;
  copied.value = true;
  clearTimeout(timer);
  timer = setTimeout(() => (copied.value = false), 1600);
}
onBeforeUnmount(() => clearTimeout(timer));
</script>

<template>
  <li class="utterance">
    <button
      v-if="hydrated"
      type="button"
      class="utterance-button"
      :class="{ 'is-copied': copied }"
      :aria-label="`复制这句话：${text}`"
      @click="onCopy"
    >
      <span class="utterance-text">“<span ref="sentence"><slot /></span>”</span>
      <span class="copy-icons" aria-hidden="true"><AppIcon name="copy" class="i-copy" /><AppIcon name="check" class="i-check" /></span>
    </button>
    <q v-else class="utterance-quote"><slot /></q>
  </li>
</template>
