<script setup lang="ts">
/**
 * 本页目录（06 章 §7.3、§9.2）：H2 与 H3（缩进 12px）；本页 H2 少于 2 个时由布局不渲染。
 * 当前项：IntersectionObserver 观察每个标题（rootMargin 上沿 = 顶栏高 + 16px，下沿 -60%），
 * 当前项 = 最后一个顶部越过上沿的标题，滚到页底时取最后一项；状态由 useScrollSpy 管理。
 * 点击条目时 lock(id)，scrollend（不支持时 800ms）后 unlock()。指示条 = useHoverIndicator 的 css 驱动，只跟随当前项。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import type { DocHeading } from 'virtual:docs-manifest';
import { useScrollSpy } from '../../composables/useScrollSpy';
import { useHoverIndicator } from '../../composables/useHoverIndicator';
import { scrollToHeading } from '../../docs/docs-ui';

const props = defineProps<{ headings: DocHeading[] }>();
const ids = computed(() => props.headings.map((h) => h.id));
let spy = useScrollSpy<string>(ids.value);
const active = ref('');
const list = ref<HTMLElement | null>(null);
const indicator = ref<HTMLElement | null>(null);
const BASE = 20;

const activeEl = () =>
  active.value
    ? ([...(list.value?.querySelectorAll<HTMLElement>('[data-toc-id]') ?? [])].find((a) => a.dataset.tocId === active.value) ??
      null)
    : null;
const { box } = useHoverIndicator({
  container: list,
  indicator,
  items: '[data-indicator-item]',
  active: activeEl,
  driver: 'css',
  followPointer: false,
});
const barStyle = computed(() => ({
  transform: `translateY(${box.value.y}px) scaleY(${box.value.h / BASE || 0})`,
  opacity: String(box.value.o),
}));

let io: IntersectionObserver | undefined;
let frame = 0;
let stopSpyWatch: (() => void) | undefined;

function headerOffset() {
  return (document.querySelector<HTMLElement>('.site-header')?.offsetHeight ?? 72) + 16;
}

/** 重算当前项：最后一个顶部越过上沿的标题；页底取最后一项。 */
function recompute() {
  frame = 0;
  const line = headerOffset() + 1;
  const els = ids.value.map((id) => document.getElementById(id)).filter((e): e is HTMLElement => Boolean(e));
  if (!els.length) return;
  const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
  let current = '';
  if (atBottom) current = els[els.length - 1].id;
  else for (const el of els) if (el.getBoundingClientRect().top <= line) current = el.id;
  for (const id of ids.value) spy.toggle(id, id === current);
}
const schedule = () => {
  frame ||= requestAnimationFrame(recompute);
};

function observe() {
  io?.disconnect();
  stopSpyWatch?.();
  spy = useScrollSpy<string>(ids.value);
  stopSpyWatch = watch(spy.active, (v) => (active.value = v), { immediate: true });
  if (typeof IntersectionObserver === 'undefined') return;
  io = new IntersectionObserver(schedule, { rootMargin: `-${headerOffset()}px 0px -60% 0px`, threshold: [0, 1] });
  for (const id of ids.value) {
    const el = document.getElementById(id);
    if (el) io.observe(el);
  }
  schedule();
}

async function go(id: string) {
  spy.lock(id, 2000);
  await scrollToHeading(id);
  spy.unlock();
}

function toTop() {
  window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  document.querySelector<HTMLElement>('#main h1')?.focus({ preventScroll: true });
}

onMounted(() => {
  observe();
  window.addEventListener('scroll', schedule, { passive: true });
});
watch(ids, () => void nextTick(observe));
onBeforeUnmount(() => {
  io?.disconnect();
  stopSpyWatch?.();
  cancelAnimationFrame(frame);
  window.removeEventListener('scroll', schedule);
});
defineExpose({ refresh: observe });
</script>

<template>
  <div class="toc-inner">
    <p class="toc-title">本页目录</p>
    <div ref="list" class="toc-list-wrap">
      <span ref="indicator" class="toc-indicator" aria-hidden="true" :style="barStyle"></span>
      <ul class="toc-list">
        <li v-for="h in headings" :key="h.id" :class="`toc-l${h.level}`">
          <a
            :href="`#${h.id}`"
            :data-toc-id="h.id"
            data-indicator-item
            :aria-current="active === h.id ? 'location' : undefined"
            @click.prevent="go(h.id)"
            >{{ h.text }}</a
          >
        </li>
      </ul>
    </div>
    <button type="button" class="toc-top text-link" @click="toTop">回到顶部</button>
  </div>
</template>
