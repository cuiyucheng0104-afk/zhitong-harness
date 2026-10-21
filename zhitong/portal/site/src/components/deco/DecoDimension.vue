<script setup lang="ts">
/**
 * D4 尺寸线分隔（07 章 §8）。放在同底色章节的接缝（首页 ≤ 3 处），由 HomePage 插入 `<DecoDimension from="3" to="4" />`；
 * 04 章 `.cap-dimline` 用 `<DecoDimension variant="inline" label="…" />`（00 章 §14 裁定 5）。
 * - 随滚动（ScrollTrigger `top 92%` → `top 56%`，`scrub: SCRUB.soft`）尺寸线从中点向两端拉开，数字从 0 数到容器实测宽度。
 * - 预渲染输出 1248 宽的终态 SVG；水合后按实测宽重建。减少动效、动效加载失败、打印：终态。
 * - 滚动帧内只写属性与样式，不读布局（纵坐标由 ScrollTrigger 在 refresh 时缓存）。
 * - `aria-hidden="true"`，数字不读出。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { SCRUB } from '../../lib/motion-tokens';
import { loadMotion, prefersReducedMotion } from '../../lib/motion';
import { columnEdges, columnsFor, dimensionState, formatDimension } from './dimension';

const props = withDefaults(defineProps<{ from?: string; to?: string; variant?: 'divider' | 'inline'; label?: string }>(), {
  from: '',
  to: '',
  variant: 'divider',
  label: '',
});

const root = ref<HTMLElement | null>(null);
const W = ref(1248);
const cols = ref(12);
const small = ref(false);
const wide = ref(true);

const inline = computed(() => props.variant === 'inline');
const H = computed(() => (inline.value ? 24 : small.value ? 44 : 56));
const Y = computed(() => (inline.value ? 12 : small.value ? 28 : 34));
const ticks = computed(() => (inline.value ? [] : columnEdges(W.value, cols.value)));
const showBubbles = computed(() => !inline.value && wide.value && (props.from !== '' || props.to !== ''));
const finalText = computed(() => props.label || formatDimension(W.value));
/** inline 标注底块宽：13px 等宽字约 7.8px/字 + 左右各 10px。 */
const labelW = computed(() => Math.round(props.label.length * 7.8 + 20));

const line = ref<SVGLineElement | null>(null);
const text = ref<SVGTextElement | null>(null);
const ends = ref<SVGGElement | null>(null);
const bubbles = ref<SVGGElement | null>(null);
const tickEls = ref<SVGLineElement[]>([]);

let lastP = -1;
let current = 1;
let tween: gsap.core.Tween | null = null;
let ro: ResizeObserver | null = null;
let alive = true;

/** 把进度写到 SVG（同一 p 不重复写）。 */
function set(p: number, force = false) {
  current = p;
  if (!force && Math.abs(p - lastP) < 1e-4) return;
  lastP = p;
  const s = dimensionState(p, W.value);
  if (line.value) line.value.style.transform = `scaleX(${s.scale})`;
  if (text.value) {
    const t = props.label ? props.label : formatDimension(s.value);
    if (text.value.textContent !== t) text.value.textContent = t;
    text.value.style.opacity = String(s.textOpacity);
  }
  if (ends.value) {
    ends.value.style.opacity = String(s.ext);
    ends.value.style.setProperty('--dd-ext', String(s.ext));
  }
  if (bubbles.value) bubbles.value.style.opacity = String(s.bubble);
  const half = (W.value * s.scale) / 2;
  const mid = W.value / 2;
  tickEls.value.forEach((el, i) => {
    const x = ticks.value[i];
    const on = x !== undefined && Math.abs(x - mid) <= half + 0.01 ? '1' : '0';
    if (el.style.opacity !== on) el.style.opacity = on;
  });
}

function onBeforePrint() {
  set(1, true);
}
function onAfterPrint() {
  set(tween ? tween.progress() : current, true);
}

function measure(width: number) {
  const w = Math.max(1, Math.round(width));
  const vw = window.innerWidth;
  small.value = vw <= 767;
  wide.value = vw >= 1024;
  cols.value = columnsFor(vw);
  if (w === W.value) return;
  W.value = w;
  void nextTick(() => set(current, true));
}

onMounted(async () => {
  if (!root.value) return;
  measure(root.value.getBoundingClientRect().width);
  if (typeof ResizeObserver !== 'undefined') {
    ro = new ResizeObserver((entries) => {
      for (const entry of entries) measure(entry.contentRect.width);
    });
    ro.observe(root.value);
  }
  window.addEventListener('beforeprint', onBeforePrint);
  window.addEventListener('afterprint', onAfterPrint);
  await nextTick();
  if (prefersReducedMotion()) return set(1, true);
  const motion = await loadMotion();
  if (!alive || !root.value) return;
  if (!motion || prefersReducedMotion()) return set(1, true);
  const state = { p: 0 };
  tween = motion.gsap.to(state, {
    p: 1,
    ease: 'none',
    scrollTrigger: { trigger: root.value, start: 'top 92%', end: 'top 56%', scrub: SCRUB.soft },
    onUpdate: () => set(state.p),
  });
  // 加载时已滚过或尚未到达的分隔直接定在滚动对应的状态，不做动画
  const st = tween.scrollTrigger;
  if (st) {
    tween.progress(st.progress);
    state.p = st.progress;
    set(state.p, true);
  }
});

onBeforeUnmount(() => {
  alive = false;
  ro?.disconnect();
  tween?.scrollTrigger?.kill();
  tween?.kill();
  tween = null;
  window.removeEventListener('beforeprint', onBeforePrint);
  window.removeEventListener('afterprint', onAfterPrint);
});

defineExpose({ set });
</script>

<template>
  <div ref="root" class="deco-dimension" :data-variant="variant" aria-hidden="true">
    <svg
      class="dd-svg"
      :viewBox="`0 0 ${W} ${H}`"
      :width="W"
      :height="H"
      preserveAspectRatio="none"
      focusable="false"
      aria-hidden="true"
    >
      <g ref="ends" class="dd-ends">
        <line class="dd-ext" :x1="0.5" :y1="Y - 14" :x2="0.5" :y2="Y + 8" />
        <line class="dd-ext" :x1="W - 0.5" :y1="Y - 14" :x2="W - 0.5" :y2="Y + 8" />
        <path class="dd-tick" :d="`M-5 ${Y + 5}L5 ${Y - 5}M${W - 5} ${Y + 5}L${W + 5} ${Y - 5}`" />
      </g>
      <line ref="line" class="dd-line" x1="0" :y1="Y + 0.5" :x2="W" :y2="Y + 0.5" :style="{ transformOrigin: `${W / 2}px ${Y}px` }" />
      <line
        v-for="(x, i) in ticks"
        :key="i"
        :ref="(el) => { if (el) tickEls[i] = el as SVGLineElement; }"
        class="dd-col"
        :x1="Math.round(x) + 0.5"
        :y1="Y - 4"
        :x2="Math.round(x) + 0.5"
        :y2="Y + 4"
      />
      <template v-if="inline">
        <!-- 04 章 .cap-dim-label：等宽 13px、--text-muted、--canvas 底、左右内边距 10px，居中压在线上 -->
        <rect v-if="label" class="dd-label-bg" :x="W / 2 - labelW / 2" :y="Y - 9" :width="labelW" height="18" />
        <text v-if="label" ref="text" class="dd-num dd-label" :x="W / 2" :y="Y + 4.5" text-anchor="middle">{{ label }}</text>
      </template>
      <text v-else ref="text" class="dd-num" :x="W / 2" :y="Y - 8" text-anchor="middle">{{ finalText }}</text>
      <g v-if="showBubbles" ref="bubbles" class="dd-bubbles">
        <g v-if="from">
          <circle :cx="-34" :cy="Y" r="9.5" />
          <text :x="-34" :y="Y + 3.5" text-anchor="middle">{{ from }}</text>
        </g>
        <g v-if="to">
          <circle :cx="W + 34" :cy="Y" r="9.5" />
          <text :x="W + 34" :y="Y + 3.5" text-anchor="middle">{{ to }}</text>
        </g>
      </g>
    </svg>
  </div>
</template>
