<script setup lang="ts">
/**
 * 常见问题 `#faq`（05 章 §4）：八问、按主题筛选、可同时展开多问、深链 `#faq-{id}`、复制问题链接。
 * - 展开：Flip 记录其后各问 → 打开 → Flip.from（`DUR.base`、`EASE.out`）；答案 `clip-path` 自上而下展开，内容延后 0.08 s 淡入；加号转 45°。
 * - 收起：答案收起、内容淡出（`DUR.short`）→ 关闭 → Flip.from（0.32 s、`EASE.inOut`）。动画中再点同一问：从当前值反向。
 * - 每次展开或收起结束后 200 ms 防抖刷新一次 ScrollTrigger。减少动效或动效未加载时立即完成。
 * - 筛选只改 `hidden`；被隐藏项保留展开状态；焦点所在项被隐藏时焦点移到筛选按钮。筛选组与复制按钮水合后才渲染（预留 36px 高度）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';
import AppIcon from './AppIcon.vue';
import FaqItemView from './sections05/faq/FaqItem.vue';
import { FAQ_COPY, FAQ_GROUPS, FAQS, GROUP_LABEL, type FaqGroup, type FaqItem } from '../data/faq';
import { useHoverIndicator } from '../composables/useHoverIndicator';
import { useCopy } from '../composables/useCopy';
import { getMotion, prefersReducedMotion, refreshMotionLayout } from '../lib/motion';
import { DUR, EASE, STAGGER } from '../lib/motion-tokens';
import { scrollToSection } from '../lib/smooth-scroll';

type Filter = FaqGroup | 'all';
type Id = FaqItem['id'];

const filter = ref<Filter>('all');
const openIds = ref<Set<Id>>(new Set(['calc']));
const hydrated = ref(false);
const statusText = ref('');
const copiedId = ref<Id | null>(null);
const list = ref<HTMLElement | null>(null);
const filters = ref<HTMLElement | null>(null);
const indicator = ref<HTMLElement | null>(null);
const { copy } = useCopy();

const counts = computed(
  () =>
    Object.fromEntries(
      FAQ_GROUPS.map((g) => [
        g.id,
        g.id === 'all' ? FAQS.length : FAQS.filter((f) => f.group === g.id).length,
      ]),
    ) as Record<Filter, number>,
);
const visible = (item: FaqItem) => filter.value === 'all' || item.group === filter.value;
const activeButton = () =>
  filters.value?.querySelector<HTMLElement>('[aria-pressed="true"]') ?? null;

useHoverIndicator({
  container: filters,
  indicator,
  active: () => {
    void filter.value;
    return activeButton();
  },
});

/** 每问的动画序号：新动作开始时递增，旧动作的异步收尾据此作废。 */
const tokens = new Map<Id, number>();
const animating = new Map<Id, 'open' | 'close'>();
let refreshTimer: ReturnType<typeof setTimeout> | undefined;
let copyTimer: ReturnType<typeof setTimeout> | undefined;

function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refreshMotionLayout, 200);
}

function setOpen(id: Id, open: boolean) {
  const next = new Set(openIds.value);
  if (open) next.add(id);
  else next.delete(id);
  openIds.value = next;
}

const el = (id: Id) => document.getElementById(`faq-${id}`) as HTMLDetailsElement | null;
function followers(id: Id): HTMLElement[] {
  const items = [...(list.value?.querySelectorAll<HTMLElement>('.faq-item:not([hidden])') ?? [])];
  const i = items.findIndex((n) => n.id === `faq-${id}`);
  return i < 0 ? [] : items.slice(i + 1);
}
const motionOn = () => {
  const m = getMotion();
  return m && !prefersReducedMotion() ? m : null;
};

async function expand(id: Id) {
  const m = motionOn();
  const token = (tokens.get(id) ?? 0) + 1;
  tokens.set(id, token);
  const det = el(id);
  if (!m || !det) {
    setOpen(id, true);
    scheduleRefresh();
    return;
  }
  const { gsap, Flip } = m;
  const answer = det.querySelector<HTMLElement>('.faq-answer');
  const inner = det.querySelector<HTMLElement>('.faq-answer-inner');
  const plus = det.querySelector<HTMLElement>('.faq-plus');
  const interrupted = animating.get(id) === 'close';
  gsap.killTweensOf([answer, inner, plus]);
  animating.set(id, 'open');
  const state = Flip.getState(followers(id));
  setOpen(id, true);
  await nextTick();
  if (tokens.get(id) !== token) return;
  if (!interrupted) {
    gsap.set(answer, { clipPath: 'inset(0 0 100% 0)' });
    gsap.set(inner, { opacity: 0, y: 8 });
    gsap.set(plus, { rotate: 0 });
  }
  Flip.from(state, { duration: DUR.base, ease: EASE.out });
  gsap.to(plus, { rotate: 45, duration: DUR.short, ease: EASE.out });
  gsap.to(inner, {
    opacity: 1,
    y: 0,
    duration: DUR.short,
    ease: EASE.out,
    delay: interrupted ? 0 : 0.08,
  });
  await gsap.to(answer, { clipPath: 'inset(0 0 0% 0)', duration: DUR.base, ease: EASE.out });
  if (tokens.get(id) !== token) return;
  gsap.set([answer, inner, plus], { clearProps: 'all' });
  animating.delete(id);
  scheduleRefresh();
}

async function collapse(id: Id) {
  const m = motionOn();
  const token = (tokens.get(id) ?? 0) + 1;
  tokens.set(id, token);
  const det = el(id);
  if (!m || !det) {
    setOpen(id, false);
    scheduleRefresh();
    return;
  }
  const { gsap, Flip } = m;
  const answer = det.querySelector<HTMLElement>('.faq-answer');
  const inner = det.querySelector<HTMLElement>('.faq-answer-inner');
  const plus = det.querySelector<HTMLElement>('.faq-plus');
  gsap.killTweensOf([answer, inner, plus]);
  animating.set(id, 'close');
  gsap.to(plus, { rotate: 0, duration: DUR.short, ease: EASE.out });
  gsap.to(inner, { opacity: 0, duration: DUR.short, ease: EASE.out });
  await gsap.to(answer, { clipPath: 'inset(0 0 100% 0)', duration: DUR.short, ease: EASE.out });
  if (tokens.get(id) !== token) return;
  const state = Flip.getState(followers(id));
  setOpen(id, false);
  await nextTick();
  if (tokens.get(id) !== token) return;
  gsap.set([answer, inner, plus], { clearProps: 'all' });
  await Flip.from(state, { duration: 0.32, ease: EASE.inOut });
  if (tokens.get(id) !== token) return;
  animating.delete(id);
  scheduleRefresh();
}

function onToggle(item: FaqItem, e: MouseEvent) {
  e.preventDefault();
  const dir = animating.get(item.id);
  const isOpen = dir ? dir === 'open' : openIds.value.has(item.id);
  void (isOpen ? collapse(item.id) : expand(item.id));
}

/** 页内查找等由浏览器触发的展开：同步状态（无动画）。 */
function onNative(item: FaqItem, e: Event) {
  const det = e.target as HTMLDetailsElement;
  if (animating.has(item.id)) return;
  if (det.open !== openIds.value.has(item.id)) setOpen(item.id, det.open);
}

async function setFilter(f: Filter) {
  if (f === filter.value) return;
  const m = motionOn();
  const items = [...(list.value?.querySelectorAll<HTMLElement>('.faq-item') ?? [])];
  const state = m ? m.Flip.getState(items) : null;
  filter.value = f;
  const n = FAQS.filter(visible).length;
  statusText.value = FAQ_COPY.status(n, f === 'all' ? null : GROUP_LABEL[f]);
  await nextTick();
  const active = document.activeElement;
  if (active instanceof HTMLElement && active.closest('.faq-item[hidden]')) activeButton()?.focus();
  if (m && state) {
    const { gsap, Flip } = m;
    Flip.from(state, {
      duration: DUR.base,
      ease: EASE.inOut,
      absolute: true,
      stagger: STAGGER.tight,
      onEnter: (els) =>
        gsap.fromTo(els, { opacity: 0, y: 12 }, { opacity: 1, y: 0, duration: DUR.short }),
      onLeave: (els) => gsap.to(els, { opacity: 0, duration: DUR.micro }),
      onComplete: scheduleRefresh,
    });
  } else scheduleRefresh();
}

async function onCopy(item: FaqItem) {
  const ok = await copy(FAQ_COPY.link(item.id), { success: FAQ_COPY.copied });
  history.replaceState(history.state, '', `#faq-${item.id}`);
  if (!ok) return;
  copiedId.value = item.id;
  clearTimeout(copyTimer);
  copyTimer = setTimeout(() => (copiedId.value = null), 1600);
}

/** 深链：筛选设为“全部”、展开该问（都无动画）→ 滚到该问（顶栏 + 24px）→ 焦点到其 summary。 */
async function openFromHash() {
  const hash = decodeURIComponent(location.hash.slice(1));
  if (!hash.startsWith('faq-')) return;
  const item = FAQS.find((f) => `faq-${f.id}` === hash);
  if (!item) return;
  filter.value = 'all';
  setOpen(item.id, true);
  await nextTick();
  await scrollToSection(hash, false);
  el(item.id)?.querySelector('summary')?.focus({ preventScroll: true });
}

let printOpened: Id[] = [];
const beforePrint = () => {
  printOpened = FAQS.map((f) => f.id).filter((id) => !openIds.value.has(id));
  openIds.value = new Set(FAQS.map((f) => f.id));
};
const afterPrint = () => {
  const next = new Set(openIds.value);
  for (const id of printOpened) next.delete(id);
  openIds.value = next;
  printOpened = [];
};
const onHash = () => void openFromHash();

onMounted(() => {
  hydrated.value = true;
  window.addEventListener('hashchange', onHash);
  window.addEventListener('beforeprint', beforePrint);
  window.addEventListener('afterprint', afterPrint);
  void nextTick(openFromHash);
});
onBeforeUnmount(() => {
  clearTimeout(refreshTimer);
  clearTimeout(copyTimer);
  window.removeEventListener('hashchange', onHash);
  window.removeEventListener('beforeprint', beforePrint);
  window.removeEventListener('afterprint', afterPrint);
});

defineExpose({ setFilter, expand, collapse, openFromHash });
</script>

<template>
  <section id="faq" class="faq-section section-space" aria-labelledby="faq-title">
    <div class="container faq-grid">
      <div class="faq-aside">
        <div class="section-heading">
          <p class="eyebrow">{{ FAQ_COPY.eyebrow }}</p>
          <h2 id="faq-title" tabindex="-1" data-reveal="heading">{{ FAQ_COPY.title }}</h2>
          <p data-reveal="block">{{ FAQ_COPY.lead }}</p>
        </div>
        <div class="faq-filter-slot">
          <div
            v-if="hydrated"
            ref="filters"
            class="faq-filters"
            role="group"
            :aria-label="FAQ_COPY.filterLabel"
          >
            <span ref="indicator" class="faq-filter-ind" aria-hidden="true"></span>
            <button
              v-for="g in FAQ_GROUPS"
              :key="g.id"
              v-magnetic
              type="button"
              class="faq-filter"
              data-indicator-item
              :aria-pressed="filter === g.id"
              @click="setFilter(g.id)"
            >
              <span data-magnetic-label
                >{{ g.label }} <span class="mono">{{ counts[g.id] }}</span></span
              >
            </button>
          </div>
        </div>
        <p id="faq-status" class="sr-only" role="status" aria-live="polite">{{ statusText }}</p>
        <RouterLink class="text-link faq-doc-link" :to="FAQ_COPY.docLink.href"
          >{{ FAQ_COPY.docLink.text }}<AppIcon name="arrow" class="icon"
        /></RouterLink>
      </div>
      <div ref="list" class="faq-list" data-reveal="stagger">
        <FaqItemView
          v-for="item in FAQS"
          :key="item.id"
          :item="item"
          :open="openIds.has(item.id)"
          :hidden="!visible(item)"
          :hydrated="hydrated"
          :copied="copiedId === item.id"
          @toggle="onToggle(item, $event)"
          @native="onNative(item, $event)"
          @copy="onCopy(item)"
        />
      </div>
    </div>
  </section>
</template>
