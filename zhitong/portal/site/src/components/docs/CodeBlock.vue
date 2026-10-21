<script setup lang="ts">
/**
 * 代码块（06 章 §7.9）：构建期 shiki 高亮的 `<pre>` 放在默认插槽里（外包 v-pre）。
 * 顶部 32px 标题条：语言名（text 不显示）+「复制」。复制代码原文（`<pre>` 的文本，不含标题条），
 * 成功后图标 copy → check 交叉淡入，1.6 秒复原，并提示「已复制代码」；失败提示并选中代码文本。无 JS 时没有复制按钮。
 */
import { computed, onBeforeUnmount, ref } from 'vue';
import AppIcon from '../AppIcon.vue';
import { useCopy } from '../../composables/useCopy';
import { useHydrated } from './useHydrated';

const props = defineProps<{ lang: string }>();
const LANG_LABEL: Record<string, string> = {
  bash: 'macOS 终端',
  powershell: 'Windows PowerShell',
  json: 'JSON',
  yaml: 'YAML',
};
const label = computed(() => LANG_LABEL[props.lang] ?? '');
const root = ref<HTMLElement | null>(null);
const copied = ref(false);
const hydrated = useHydrated();
const { copy } = useCopy();
let timer: ReturnType<typeof setTimeout> | undefined;

async function onCopy() {
  const code = root.value?.querySelector('pre code') ?? root.value?.querySelector('pre');
  if (!code) return;
  const ok = await copy(code.textContent ?? '', { success: '已复制代码', fallbackSelect: code as HTMLElement });
  if (!ok) return;
  copied.value = true;
  clearTimeout(timer);
  timer = setTimeout(() => (copied.value = false), 1600);
}
onBeforeUnmount(() => clearTimeout(timer));
</script>

<template>
  <div ref="root" class="code-block" :data-lang="lang">
    <div class="code-head">
      <span class="code-lang">{{ label }}</span>
      <button v-if="hydrated" type="button" class="code-copy" :class="{ 'is-copied': copied }" aria-label="复制代码" @click="onCopy">
        <span class="copy-icons" aria-hidden="true"><AppIcon name="copy" class="i-copy" /><AppIcon name="check" class="i-check" /></span>
        <span class="code-copy-text" aria-hidden="true">复制</span>
      </button>
    </div>
    <slot />
  </div>
</template>
