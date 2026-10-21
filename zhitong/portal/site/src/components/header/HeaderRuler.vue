<script setup lang="ts">
/**
 * 比例尺滚动进度（01 章 §4）。只在客户端挂载后渲染；`aria-hidden`；打印隐藏。
 * - 进度 `--p`（0–1）与 `--px`（像素）写在根元素上，即时跟随，不做过渡。
 *   首页由 ScrollTrigger（start 0、end 'max'）驱动；文档页与动效未加载时用被动 scroll + rAF。
 * - 首页标记：七个章节起点（`top top+=64` 的测量触发器 ÷ maxScroll，每次 refresh 后重算，计入钉住区块）。
 *   文档页标记：正文每个 H2 的文档坐标 ÷（scrollHeight − innerHeight），ResizeObserver 监听正文高度。
 *   404 页不画标记。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { RULER_SECTIONS, type RulerSectionId } from '../../data/nav';
import { NAV_IDS, homeReady } from '../../lib/home-state';
import { getMotion, type Motion } from '../../lib/motion';
import type { PageLayout } from '../../composables/useHeaderState';

const props = defineProps<{ layout: PageLayout; activeId: string }>();
const route = useRoute();
const root = ref<HTMLElement | null>(null);
const marks = ref<{ id: string; pos: number; nav: boolean }[]>([]);

let frame = 0;
let triggers: { kill(): void }[] = [];
let resize: ResizeObserver | undefined;
let onRefresh: (() => void) | undefined;
let motionRef: Motion | null = null;

const visibleMarks = computed(() => (props.layout === 'notfound' ? [] : marks.value));

function write(p: number) {
  const el = root.value;
  if (!el) return;
  const clamped = Math.max(0, Math.min(1, p));
  el.style.setProperty('--p', clamped.toFixed(4));
  el.style.setProperty('--px', `${(clamped * el.clientWidth).toFixed(1)}px`);
}

function nativeProgress() {
  const max = document.documentElement.scrollHeight - window.innerHeight;
  write(max > 0 ? window.scrollY / max : 0);
}
const onScroll = () => {
  if (triggers.length) return;
  frame ||= requestAnimationFrame(() => {
    frame = 0;
    nativeProgress();
  });
};

function docMarks() {
  const main = document.getElementById('main');
  const max = document.documentElement.scrollHeight - window.innerHeight;
  if (!main || max <= 0) return (marks.value = []);
  marks.value = [...main.querySelectorAll<HTMLElement>('h2')].map((h, i) => ({
    id: h.id || `h2-${i}`,
    pos: Math.min(1, (h.getBoundingClientRect().top + window.scrollY) / max),
    nav: false,
  }));
}

function homeMarksNative() {
  const max = document.documentElement.scrollHeight - window.innerHeight;
  marks.value = RULER_SECTIONS.flatMap((id) => {
    const el = document.getElementById(id);
    if (!el || max <= 0) return [];
    const start = el.getBoundingClientRect().top + window.scrollY - 64;
    return [{ id, pos: Math.max(0, Math.min(1, start / max)), nav: NAV_IDS.includes(id as never) }];
  });
}

function teardown() {
  for (const t of triggers) t.kill();
  triggers = [];
  if (onRefresh && motionRef) motionRef.ScrollTrigger.removeEventListener('refresh', onRefresh);
  onRefresh = undefined;
  resize?.disconnect();
  resize = undefined;
}

function setupHome() {
  teardown();
  const motion = getMotion();
  motionRef = motion;
  if (!motion) {
    homeMarksNative();
    nativeProgress();
    return;
  }
  const { ScrollTrigger, gsap } = motion;
  const measure = new Map<RulerSectionId, ReturnType<Motion["ScrollTrigger"]["create"]>>();
  for (const id of RULER_SECTIONS) {
    if (!document.getElementById(id)) continue;
    measure.set(id, ScrollTrigger.create({ trigger: `#${id}`, start: 'top top+=64', refreshPriority: -1 }));
  }
  const setP = gsap.quickSetter(root.value!, '--p') as (v: number) => void;
  const progress = ScrollTrigger.create({
    start: 0,
    end: 'max',
    onUpdate: (self) => {
      setP(Number(self.progress.toFixed(4)));
      root.value?.style.setProperty('--px', `${(self.progress * (root.value?.clientWidth ?? 0)).toFixed(1)}px`);
    },
  });
  triggers = [...measure.values(), progress];
  onRefresh = () => {
    const max = ScrollTrigger.maxScroll(window);
    marks.value = [...measure].map(([id, st]) => ({
      id,
      pos: max > 0 ? Math.max(0, Math.min(1, st.start / max)) : 0,
      nav: NAV_IDS.includes(id as never),
    }));
    write(max > 0 ? window.scrollY / max : 0);
  };
  ScrollTrigger.addEventListener('refresh', onRefresh);
  onRefresh();
}

function setupDocs() {
  teardown();
  marks.value = [];
  nativeProgress();
  if (props.layout !== 'docs') return;
  docMarks();
  const main = document.getElementById('main');
  if (main && typeof ResizeObserver !== 'undefined') {
    resize = new ResizeObserver(() => {
      docMarks();
      nativeProgress();
    });
    resize.observe(main);
  }
}

function setup() {
  if (props.layout === 'home') {
    if (homeReady.value) setupHome();
    else teardown();
  } else setupDocs();
}

onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  setup();
});
watch(() => [props.layout, homeReady.value, route.path] as const, () => requestAnimationFrame(setup));
onBeforeUnmount(() => {
  cancelAnimationFrame(frame);
  teardown();
  window.removeEventListener('scroll', onScroll);
  window.removeEventListener('resize', onScroll);
});
</script>

<template>
  <div ref="root" class="header-ruler" aria-hidden="true">
    <div class="ruler-ticks"></div>
    <div class="ruler-fill"></div>
    <span
      v-for="mark in visibleMarks"
      :key="mark.id"
      class="ruler-mark"
      :class="{ 'is-nav': mark.nav, 'is-current': mark.id === activeId }"
      :style="{ left: `${(mark.pos * 100).toFixed(3)}%` }"
    ></span>
    <span class="ruler-cursor"></span>
  </div>
</template>
