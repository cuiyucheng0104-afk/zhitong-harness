<script setup lang="ts">
/**
 * 搜索入口（06 章 §8.1）：
 * - `variant="sidebar"`：外观像输入框，左放大镜、「搜索文档」、右侧按键提示（Apple 设备 ⌘ K，其它 Ctrl K）；
 * - `variant="hero"`：文档首页深色区的大号触发器；
 * - `variant="icon"`：平板与手机文档子栏的图标按钮。
 * 预渲染与无 JS 时不渲染按钮（占位保留尺寸，避免位移）；按键提示同样只在水合后出现、区域预留宽度。
 * 指针移到或聚焦时预取搜索块与索引。
 */
import { computed } from 'vue';
import { isApple, openSearch, prefetchSearch } from '../../docs/docs-ui';
import { useHydrated } from './useHydrated';

const props = withDefaults(defineProps<{ variant?: 'sidebar' | 'hero' | 'icon' }>(), { variant: 'sidebar' });
const hydrated = useHydrated();
const hint = computed(() => (hydrated.value ? (isApple() ? '⌘ K' : 'Ctrl K') : ''));
const text = computed(() => (props.variant === 'hero' ? '搜索安装、配置包、核对、需人工确认…' : '搜索文档'));

function open(event: MouseEvent) {
  openSearch(event.currentTarget as HTMLElement);
}
const prefetch = () => void prefetchSearch().catch(() => undefined);
</script>

<template>
  <button
    v-if="hydrated"
    type="button"
    :class="['docs-search-trigger', `is-${variant}`]"
    :aria-label="variant === 'icon' ? '搜索文档' : undefined"
    aria-haspopup="dialog"
    @click="open"
    @pointerenter="prefetch"
    @focus="prefetch"
  >
    <svg class="search-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.5 4.5" />
    </svg>
    <span v-if="variant !== 'icon'" class="search-text">{{ text }}</span>
    <span v-if="variant !== 'icon'" class="search-hint" aria-hidden="true">{{ hint }}</span>
  </button>
  <span v-else :class="['docs-search-trigger', 'is-placeholder', `is-${variant}`]" aria-hidden="true"></span>
</template>
