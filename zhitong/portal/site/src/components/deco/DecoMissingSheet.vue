<script setup lang="ts">
/**
 * D5 404 图纸缺页（07 章 §9；00 章 §14 裁定 3：取代 01 章 §12 的 320×160 图框）。
 * - SVG 由 `missingSheetParts()`（固定种子）生成，SSR 时输出进 `dist/404.html`，水合结果一致。
 * - 动画全用 CSS（`styles/deco.css`）：基础样式即终态，`@keyframes` 只描述“从哪里来”；减少动效、打印、无 JS 时直接是终帧。
 * - 唯一的运行时脚本：页面隐藏或 SVG 离开视口时给根元素加 `.paused`（`animation-play-state: paused`）。
 * - 404 页不加载 GSAP，也不加载画布组件。根元素 `aria-hidden="true"`、`focusable="false"`。
 */
import { h, onMounted, ref, type FunctionalComponent, type VNode } from 'vue';
import { useInView } from '../../composables/useInView';
import { missingSheetParts, type SheetPart } from './missingSheet';

const parts = missingSheetParts();
const root = ref<SVGSVGElement | null>(null);
const view = useInView(root, { threshold: 0.01 });
// 预渲染与水合前不加 .paused（否则无 JS 时动画停在起点）
const mounted = ref(false);
onMounted(() => (mounted.value = true));

function render(p: SheetPart): VNode {
  const style = p.t !== undefined ? `--t:${p.t}s;--d:${p.d ?? 0}s` : undefined;
  const props: Record<string, string> = { ...p.attrs };
  if (p.cls) props.class = p.cls;
  if (style) props.style = style;
  if (p.children) return h(p.tag, props, p.children.map(render));
  return h(p.tag, props, p.text);
}

const SheetParts: FunctionalComponent = () => parts.map(render);
</script>

<template>
  <svg
    ref="root"
    class="deco-missing"
    :class="{ paused: mounted && !view.active.value }"
    viewBox="-2 -2 424 301"
    aria-hidden="true"
    focusable="false"
  >
    <SheetParts />
  </svg>
</template>
