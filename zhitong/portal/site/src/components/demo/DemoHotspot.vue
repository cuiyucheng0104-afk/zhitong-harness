<script setup lang="ts">
/**
 * 引导热区（02 章 §10.1）：8px 实心圆点 + 同心脉冲环，不带文字；挂在目标元素右上角向内 4px。
 * 位置随窗口尺寸与预览滚动重算（ResizeObserver + 滚动，rAF 节流）；目标被滚出可视区时隐藏。
 * `aria-hidden`、`pointer-events: none`，不拦截点击。减少动效：无脉冲，环静态 scale 1.6、opacity .35。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { HotspotId } from '../../data/demo';

const props = defineProps<{
  id: HotspotId;
  /** CSS 选择器，相对场景面板。 */
  target: string;
  /** 是否显示。 */
  visible: boolean;
  /** 示例在视口内且未减少动效：脉冲。 */
  pulse: boolean;
}>();

const el = ref<HTMLElement | null>(null);
const pos = ref<{ x: number; y: number } | null>(null);
let frame = 0;
let resize: ResizeObserver | undefined;
let panel: HTMLElement | null = null;

function scrollParent(node: HTMLElement | null): HTMLElement | null {
  let cur = node?.parentElement ?? null;
  while (cur && cur !== panel) {
    const style = getComputedStyle(cur);
    if (/(auto|scroll)/.test(style.overflowY + style.overflowX)) return cur;
    cur = cur.parentElement;
  }
  return null;
}

function measure() {
  frame = 0;
  if (!panel) return;
  const target = panel.querySelector<HTMLElement>(props.target);
  if (!target) {
    pos.value = null;
    return;
  }
  const r = target.getBoundingClientRect();
  const p = panel.getBoundingClientRect();
  if (!r.width && !r.height) {
    pos.value = null;
    return;
  }
  const x = r.right - 4;
  const y = r.top + 4;
  const sp = scrollParent(target);
  if (sp) {
    const s = sp.getBoundingClientRect();
    if (y < s.top || y > s.bottom || x < s.left || x > s.right) {
      pos.value = null;
      return;
    }
  }
  pos.value = { x: x - p.left, y: y - p.top };
}

function schedule() {
  if (frame || typeof requestAnimationFrame !== 'function') return;
  frame = requestAnimationFrame(measure);
}

onMounted(() => {
  panel = el.value?.closest<HTMLElement>('.scene') ?? null;
  if (!panel) return;
  if (typeof ResizeObserver !== 'undefined') {
    resize = new ResizeObserver(schedule);
    resize.observe(panel);
  }
  panel.addEventListener('scroll', schedule, true);
  window.addEventListener('resize', schedule);
  if (props.visible) void nextTick(measure);
});
watch(
  () => props.visible,
  (v) => {
    if (v) void nextTick(measure);
  },
);
onBeforeUnmount(() => {
  cancelAnimationFrame(frame);
  resize?.disconnect();
  panel?.removeEventListener('scroll', schedule, true);
  window.removeEventListener('resize', schedule);
});
defineExpose({ measure });
</script>

<template>
  <span
    ref="el"
    class="demo-hotspot"
    :class="{ 'is-on': visible && pos, 'is-pulsing': pulse }"
    :data-hotspot="id"
    :style="pos ? { transform: `translate(${pos.x}px, ${pos.y}px)` } : undefined"
    aria-hidden="true"
    ><i class="demo-hotspot-ring"></i><i class="demo-hotspot-dot"></i
  ></span>
</template>
