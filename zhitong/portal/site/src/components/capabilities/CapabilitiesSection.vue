<script setup lang="ts">
/**
 * 产品能力 `#capabilities`（04 章）：章节头与尺寸线、四个分组页签、能力列表与详情面板、12 段小动画。
 *
 * 状态机见 04 章 §6.7；预渲染没有 `cap-enhanced`（四组依次排列的手风琴，每组首项展开，§4.4），
 * `onMounted` 第一步加上。动效块未就绪或减少动效时切换立即生效，不做 Flip。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue';
import AppIcon from '../AppIcon.vue';
import ZtPopover from '../ui/ZtPopover.vue';
import DecoDimension from '../deco/DecoDimension.vue';
import FeaturePanel from './FeaturePanel.vue';
import { vMagnetic } from '../../composables/useMagnetic';
import { useHoverIndicator } from '../../composables/useHoverIndicator';
import { useCountUp } from '../../composables/useCountUp';
import {
  loadMotion,
  getMotion,
  prefersReducedMotion,
  refreshMotionLayout,
  type Motion,
} from '../../lib/motion';
import { DUR, EASE, SCRUB, STAGGER } from '../../lib/motion-tokens';
import { formatInt } from '../../lib/format';
import { onTabKeydown } from '../../lib/navigation';
import { headerVisualHeight, scrollToSection } from '../../lib/smooth-scroll';
import {
  DEFAULT_GROUP,
  DEFAULT_SELECTION,
  FEATURE_HASH_RE,
  dimLabel,
  featureGroups,
  glossary,
  groupOf,
  homeGroups,
  type FeatureGroup,
  type FeatureId,
  type GlossaryKey,
  type GroupId,
} from '../../data/capabilities';
import type { SceneId } from '../../types/portal';
import { ART_PAUSED } from './art-tokens';
import { prefetchArtTimelines } from '../../composables/useArtLoop';

type Layout = 'desktop' | 'tablet' | 'mobile';

const props = withDefaults(defineProps<{ groups?: readonly FeatureGroup[] }>(), {
  groups: () => featureGroups,
});
const emit = defineEmits<{ scene: [scene: SceneId] }>();

const shown = computed(() => homeGroups(props.groups));
const total = computed(() => shown.value.reduce((n, g) => n + g.features.length, 0));
const label = computed(() => dimLabel(shown.value));

const firstOf = (gid: GroupId): FeatureId | null =>
  (shown.value.find((g) => g.id === gid)?.features[0]?.id as FeatureId) ?? null;
const inGroup = (gid: GroupId, fid: FeatureId | null) =>
  !!fid && !!shown.value.find((g) => g.id === gid)?.features.some((f) => f.id === fid);
const pick = (gid: GroupId, fid: FeatureId | null): FeatureId | null =>
  inGroup(gid, fid) ? fid : firstOf(gid);

const section = ref<HTMLElement | null>(null);
const browser = ref<HTMLElement | null>(null);
const tabsEl = ref<HTMLElement | null>(null);
const indicator = ref<HTMLElement | null>(null);
const countEl = ref<HTMLElement | null>(null);
const termPop = ref<InstanceType<typeof ZtPopover> | null>(null);

const enhanced = ref(false);
const layout = ref<Layout>('desktop');
const group = ref<GroupId>(DEFAULT_GROUP);
const selected = reactive<Record<GroupId, FeatureId | null>>({
  project: pick('project', DEFAULT_SELECTION.project),
  calculate: pick('calculate', DEFAULT_SELECTION.calculate),
  output: pick('output', DEFAULT_SELECTION.output),
  knowledge: pick('knowledge', DEFAULT_SELECTION.knowledge),
});
const mobileOpen = reactive<Record<GroupId, FeatureId | null>>({ ...selected });
const leaving = ref<FeatureId | null>(null);
const artPaused = ref(false);
const termKey = ref<GlossaryKey | ''>('');
provide(ART_PAUSED, artPaused);

const mobile = computed(() => enhanced.value && layout.value === 'mobile');

function isOpen(gid: GroupId, fid: FeatureId) {
  if (!enhanced.value) return selected[gid] === fid;
  if (mobile.value) return mobileOpen[gid] === fid;
  return selected[gid] === fid || leaving.value === fid;
}
function isActive(gid: GroupId, fid: FeatureId) {
  if (!enhanced.value || group.value !== gid) return false;
  return mobile.value ? mobileOpen[gid] === fid : selected[gid] === fid;
}
const showBar = (gid: GroupId, fid: FeatureId) =>
  enhanced.value && !mobile.value && selected[gid] === fid;

useCountUp(countEl, { to: total.value, format: formatInt });
useHoverIndicator({
  container: tabsEl,
  indicator,
  items: '[role="tab"]',
  driver: 'css',
  active: () =>
    mobile.value
      ? null
      : (tabsEl.value?.querySelector<HTMLElement>('[aria-selected="true"]') ?? null),
});

/* ---------- 动画工具 ---------- */
let motion: Motion | null = null;
let ctx: gsap.Context | undefined;
let running: gsap.core.Timeline | null = null;
const canAnimate = () => !!motion && !prefersReducedMotion();
const byId = (id: string) => section.value?.querySelector<HTMLElement>(`#${id}`) ?? null;
const panelOf = (fid: FeatureId) =>
  byId(`feature-${fid}`)?.querySelector<HTMLElement>('.feature-detail') ?? null;
const bars = () => [
  ...(section.value?.querySelectorAll<HTMLElement>('[data-flip-id="feature-active"]') ?? []),
];

function finishRunning() {
  if (running) running.progress(1);
  running = null;
}

/** 浏览器高度 = max(列表高, 当前面板高)（桌面与平板）。 */
function measure() {
  const el = browser.value;
  if (!el) return;
  if (!enhanced.value || mobile.value) {
    el.style.removeProperty('height');
    return;
  }
  const list = el.querySelector<HTMLElement>('.feature-group:not([hidden])');
  const fid = selected[group.value];
  const panel = fid ? panelOf(fid) : null;
  const h = Math.max(list?.offsetHeight ?? 0, panel?.offsetHeight ?? 0);
  if (h > 0) el.style.height = `${h}px`;
}

/** 减少动效：面板只做 0.2s 透明度。 */
function reducedFade(el: HTMLElement | null) {
  if (!el || typeof el.animate !== 'function') return;
  el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200, easing: 'linear' });
}

function panelEnter(
  tl: gsap.core.Timeline,
  panel: HTMLElement | null,
  at: number,
  dy: number,
  childAt: number,
) {
  if (!panel || !motion) return;
  tl.fromTo(
    panel,
    { opacity: 0, y: dy },
    { opacity: 1, y: 0, duration: DUR.base, ease: EASE.out, clearProps: 'transform,opacity' },
    at,
  );
  tl.fromTo(
    panel.querySelectorAll(':scope > [data-panel-child]'),
    { opacity: 0, y: 8 },
    {
      opacity: 1,
      y: 0,
      duration: DUR.short,
      ease: EASE.out,
      stagger: STAGGER.tight,
      clearProps: 'transform,opacity',
    },
    childAt,
  );
}

function heightTween(tl: gsap.core.Timeline, from: number) {
  const el = browser.value;
  if (!el || !motion) return;
  const to = el.offsetHeight;
  if (Math.abs(to - from) < 1) return;
  tl.fromTo(
    el,
    { height: from },
    { height: to, duration: DUR.base, ease: EASE.inOut, clearProps: 'height', onComplete: measure },
    0,
  );
}

/* ---------- 分组与能力项切换 ---------- */
async function selectGroup(gid: GroupId, opts: { instant?: boolean } = {}) {
  if (gid === group.value) return;
  finishRunning();
  if (mobile.value) {
    group.value = gid;
    await nextTick();
    const card = byId(`feature-group-${gid}`);
    if (!opts.instant && canAnimate() && card)
      motion!.gsap.fromTo(
        card,
        { opacity: 0, y: 12 },
        { opacity: 1, y: 0, duration: DUR.base, ease: EASE.out, clearProps: 'transform,opacity' },
      );
    else if (!opts.instant && prefersReducedMotion()) reducedFade(card);
    refreshMotionLayout();
    return;
  }
  const animate = !opts.instant && canAnimate();
  const state = animate ? motion!.Flip.getState(bars()) : null;
  const fromH = browser.value?.offsetHeight ?? 0;
  group.value = gid;
  selected[gid] = pick(gid, selected[gid]);
  await nextTick();
  measure();
  const fid = selected[gid];
  if (animate && state) {
    const { gsap, Flip } = motion!;
    const tl = gsap.timeline({ onComplete: () => (running = null) });
    tl.add(
      Flip.from(state, { duration: DUR.base, ease: EASE.inOut, absolute: true, simple: true }),
      0,
    );
    heightTween(tl, fromH);
    const summaries = byId(`feature-group-${gid}`)?.querySelectorAll('summary');
    if (summaries?.length)
      tl.fromTo(
        summaries,
        { x: -8, opacity: 0 },
        {
          x: 0,
          opacity: 1,
          duration: DUR.short,
          ease: EASE.out,
          stagger: STAGGER.tight,
          clearProps: 'transform,opacity',
        },
        0,
      );
    panelEnter(tl, fid ? panelOf(fid) : null, 0.06, 12, 0.1);
    running = tl;
  } else if (!opts.instant && prefersReducedMotion()) reducedFade(fid ? panelOf(fid) : null);
  refreshMotionLayout();
}

async function selectItem(gid: GroupId, fid: FeatureId, opts: { instant?: boolean } = {}) {
  const prev = selected[gid];
  if (prev === fid) return;
  finishRunning();
  const list = shown.value.find((g) => g.id === gid)?.features ?? [];
  const dir = list.findIndex((f) => f.id === fid) > list.findIndex((f) => f.id === prev) ? 1 : -1;
  const animate = !opts.instant && canAnimate();
  const state = animate ? motion!.Flip.getState(bars()) : null;
  const fromH = browser.value?.offsetHeight ?? 0;
  selected[gid] = fid;
  leaving.value = animate ? prev : null;
  await nextTick();
  measure();
  if (animate && state && prev) {
    const { gsap, Flip } = motion!;
    const old = panelOf(prev);
    const tl = gsap.timeline({ onComplete: () => (running = null) });
    tl.add(
      Flip.from(state, { duration: DUR.base, ease: EASE.inOut, absolute: true, simple: true }),
      0,
    );
    heightTween(tl, fromH);
    if (old)
      tl.fromTo(
        old,
        { opacity: 1, y: 0 },
        {
          opacity: 0,
          y: -8 * dir,
          duration: DUR.micro,
          ease: EASE.inOut,
          clearProps: 'transform,opacity',
          onComplete: () => {
            if (leaving.value === prev) leaving.value = null;
          },
        },
        0,
      );
    panelEnter(tl, panelOf(fid), 0.08, 14 * dir, 0.12);
    tl.eventCallback('onComplete', () => {
      running = null;
      if (leaving.value === prev) leaving.value = null;
    });
    running = tl;
  } else {
    leaving.value = null;
    if (!opts.instant && prefersReducedMotion()) reducedFade(panelOf(fid));
  }
  refreshMotionLayout();
}

async function toggleMobile(gid: GroupId, fid: FeatureId) {
  const card = byId(`feature-group-${gid}`);
  const animate = canAnimate();
  const items = card ? [...card.querySelectorAll<HTMLElement>('.feature-item')] : [];
  const state = animate ? motion!.Flip.getState(items) : null;
  const opening = mobileOpen[gid] !== fid;
  mobileOpen[gid] = opening ? fid : null;
  if (opening) selected[gid] = fid;
  await nextTick();
  if (animate && state) {
    motion!.Flip.from(state, { duration: DUR.base, ease: EASE.inOut, simple: true });
    const panel = panelOf(fid);
    if (opening && panel)
      motion!.gsap.fromTo(
        panel,
        { opacity: 0, y: -8 },
        { opacity: 1, y: 0, duration: DUR.base, ease: EASE.out, clearProps: 'transform,opacity' },
      );
  }
  refreshMotionLayout();
  if (!opening) return;
  const summary = byId(`feature-${fid}`)?.querySelector('summary');
  const top = summary?.getBoundingClientRect().top ?? 0;
  if (summary && (top < headerVisualHeight() + 8 || top > window.innerHeight))
    void scrollToSection(`feature-${fid}`, false);
}

function onSummaryClick(event: MouseEvent, gid: GroupId, fid: FeatureId) {
  if (!enhanced.value) return;
  event.preventDefault();
  if (mobile.value) void toggleMobile(gid, fid);
  else void selectItem(gid, fid);
}

function onSummaryKeydown(event: KeyboardEvent) {
  const current = event.currentTarget as HTMLElement;
  const card = current.closest('.feature-group');
  if (!card) return;
  const all = [...card.querySelectorAll<HTMLElement>('summary')];
  const i = all.indexOf(current);
  let next = -1;
  if (event.key === 'ArrowDown') next = Math.min(all.length - 1, i + 1);
  else if (event.key === 'ArrowUp') next = Math.max(0, i - 1);
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = all.length - 1;
  else return;
  event.preventDefault();
  all[next]?.focus();
}

/**
 * 选中某项能力（03 章说明卡、深链接、首页内跳转调用）。
 * @param id - 能力 id；不在首页上的 id 忽略。
 * @param opts - `focus` 默认 true：DOM 更新后聚焦 `#feature-<id>-title`；`instant` 不播放切换动画。
 */
async function selectFeature(
  id: FeatureId | string,
  opts: { focus?: boolean; instant?: boolean } = {},
): Promise<void> {
  const g = groupOf(id, shown.value);
  if (!g) return;
  const fid = id as FeatureId;
  const instant = opts.instant || !enhanced.value;
  if (mobile.value) {
    group.value = g.id;
    mobileOpen[g.id] = fid;
    selected[g.id] = fid;
    await nextTick();
  } else if (g.id !== group.value) {
    selected[g.id] = fid;
    await selectGroup(g.id, { instant });
  } else await selectItem(g.id, fid, { instant });
  await nextTick();
  if (opts.focus !== false) byId(`feature-${fid}-title`)?.focus({ preventScroll: true });
}

defineExpose({ selectFeature });

function onScene(scene: SceneId) {
  emit('scene', scene);
}

async function onTerm(key: GlossaryKey, trigger: HTMLElement) {
  if (termKey.value === key && termPop.value?.isOpen) {
    termPop.value.hide();
    return;
  }
  termKey.value = key;
  await nextTick();
  void termPop.value?.show(trigger);
}

/* ---------- 断点 ---------- */
let mqMobile: MediaQueryList | undefined;
let mqTablet: MediaQueryList | undefined;
function readLayout(): Layout {
  if (mqMobile?.matches) return 'mobile';
  if (mqTablet?.matches) return 'tablet';
  return 'desktop';
}
function onLayoutChange() {
  const next = readLayout();
  const prev = layout.value;
  if (next === prev) return;
  if (prev === 'mobile') {
    for (const g of shown.value) if (!mobileOpen[g.id]) mobileOpen[g.id] = selected[g.id];
  } else if (next === 'mobile') mobileOpen[group.value] = selected[group.value];
  layout.value = next;
  finishRunning();
  leaving.value = null;
  void nextTick(() => {
    measure();
    refreshMotionLayout();
  });
}

/* ---------- 深链接 ---------- */
async function onHash() {
  const m = FEATURE_HASH_RE.exec(window.location.hash);
  if (!m) return;
  const id = m[1] as FeatureId;
  if (!groupOf(id, shown.value)) return;
  const done = selectFeature(id, { instant: true, focus: false });
  await done;
  await scrollToSection(`feature-${id}`, false, true);
  byId(`feature-${id}-title`)?.focus({ preventScroll: true });
}

/* ---------- 打印 ---------- */
let printOpen: boolean[] = [];
function beforePrint() {
  const items = [
    ...(section.value?.querySelectorAll<HTMLDetailsElement>('details.feature-item') ?? []),
  ];
  printOpen = items.map((d) => d.open);
  for (const d of items) d.open = true;
  section.value?.classList.remove('cap-enhanced');
}
function afterPrint() {
  const items = [
    ...(section.value?.querySelectorAll<HTMLDetailsElement>('details.feature-item') ?? []),
  ];
  items.forEach((d, i) => (d.open = printOpen[i] ?? d.open));
  if (enhanced.value) section.value?.classList.add('cap-enhanced');
}

/* ---------- 生命周期 ---------- */
let resize: ResizeObserver | undefined;
let resizeTimer: ReturnType<typeof setTimeout> | undefined;
let prefetch: IntersectionObserver | undefined;
let alive = false;

function setupHeaderMotion(m: Motion) {
  const root = section.value;
  if (!root || prefersReducedMotion()) return;
  const heading = root.querySelector('.capabilities-heading');
  const lede = root.querySelector('.cap-lede');
  const dim = root.querySelector<HTMLElement>('.cap-dimline');
  ctx = m.gsap.context(() => {
    const { gsap } = m;
    if (heading && lede)
      gsap.fromTo(
        lede,
        { y: 32, opacity: 0.35 },
        {
          y: 0,
          opacity: 1,
          ease: EASE.linear,
          scrollTrigger: { trigger: heading, start: 'top 85%', end: 'top 45%', scrub: SCRUB.damp },
        },
      );
    if (heading && dim) {
      const tl = gsap.timeline({
        scrollTrigger: { trigger: heading, start: 'top 85%', end: 'top 45%', scrub: SCRUB.soft },
      });
      tl.fromTo(
        dim,
        { '--cap-dim-p': 0 },
        { '--cap-dim-p': 1, duration: 0.85, ease: EASE.linear },
        0,
      );
      tl.fromTo(
        dim,
        { '--cap-dim-tick': 0 },
        { '--cap-dim-tick': 1, duration: 0.15, ease: EASE.linear },
        0.85,
      );
    }
    const summaries = root.querySelectorAll(`#feature-group-${group.value} summary`);
    if (
      browser.value &&
      summaries.length &&
      browser.value.getBoundingClientRect().top > window.innerHeight
    )
      gsap.from(summaries, {
        y: 24,
        opacity: 0,
        duration: DUR.base,
        ease: EASE.out,
        stagger: STAGGER.base,
        clearProps: 'transform,opacity',
        scrollTrigger: { trigger: browser.value, start: 'top 85%', once: true },
      });
  }, root);
}

onMounted(async () => {
  alive = true;
  enhanced.value = true;
  mqMobile = window.matchMedia('(max-width: 767px)');
  mqTablet = window.matchMedia('(max-width: 1023px)');
  layout.value = readLayout();
  if (layout.value === 'mobile') mobileOpen[group.value] = selected[group.value];
  mqMobile.addEventListener?.('change', onLayoutChange);
  mqTablet.addEventListener?.('change', onLayoutChange);
  void onHash();
  window.addEventListener('hashchange', onHash);
  window.addEventListener('beforeprint', beforePrint);
  window.addEventListener('afterprint', afterPrint);
  await nextTick();
  measure();
  if (typeof ResizeObserver !== 'undefined' && browser.value) {
    let lastW = window.innerWidth;
    resize = new ResizeObserver(() => {
      if (window.innerWidth === lastW) return;
      lastW = window.innerWidth;
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(measure, 150);
    });
    resize.observe(browser.value);
  }
  void document.fonts?.ready.then(() => alive && measure());
  if (typeof IntersectionObserver !== 'undefined' && section.value) {
    prefetch = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          prefetch?.disconnect();
          void prefetchArtTimelines().catch(() => undefined);
        }
      },
      { rootMargin: '100% 0px' },
    );
    prefetch.observe(section.value);
  }
  const m = await loadMotion();
  if (!alive || !m) return;
  motion = m;
  setupHeaderMotion(m);
});

watch(
  () => [group.value, layout.value] as const,
  () => void nextTick(measure),
);

onBeforeUnmount(() => {
  alive = false;
  mqMobile?.removeEventListener?.('change', onLayoutChange);
  mqTablet?.removeEventListener?.('change', onLayoutChange);
  window.removeEventListener('hashchange', onHash);
  window.removeEventListener('beforeprint', beforePrint);
  window.removeEventListener('afterprint', afterPrint);
  resize?.disconnect();
  prefetch?.disconnect();
  clearTimeout(resizeTimer);
  running?.kill();
  ctx?.revert();
  void getMotion;
});
</script>

<template>
  <section
    id="capabilities"
    ref="section"
    class="capabilities-section section-space"
    :class="{ 'cap-enhanced': enhanced }"
    :data-layout="enhanced ? layout : undefined"
    aria-labelledby="capabilities-title"
  >
    <div class="container">
      <div class="capabilities-heading">
        <div>
          <p class="eyebrow">产品能力</p>
          <h2 id="capabilities-title" tabindex="-1" data-reveal="heading">
            从项目资料，到交付成果。
          </h2>
        </div>
        <p class="cap-lede">
          <span ref="countEl" class="cap-count num">{{ total }}</span>
          项具体工作，按任务选择。每项都写明需要什么、得到什么、结果放在哪里。
        </p>
      </div>
      <div class="cap-dimline" aria-hidden="true">
        <!-- 00 §14 裁定 5：标注由 D4 的 label 渲染并压在线上（07 章），不另叠 .cap-dim-label。 -->
        <DecoDimension variant="inline" :label="label" />
      </div>
      <div
        ref="tabsEl"
        class="capability-tabs"
        role="tablist"
        aria-label="能力分组"
        data-reveal="block"
        @keydown="onTabKeydown"
      >
        <button
          v-for="g in shown"
          :id="`group-${g.id}`"
          :key="g.id"
          v-magnetic
          type="button"
          role="tab"
          :aria-label="`${g.label}，${g.features.length} 项`"
          :aria-selected="group === g.id ? 'true' : 'false'"
          :aria-controls="`feature-group-${g.id}`"
          :tabindex="group === g.id ? 0 : -1"
          :data-group="g.id"
          @click="selectGroup(g.id)"
        >
          <span class="cap-tab-inner" data-magnetic-label
            ><AppIcon :name="g.icon" /><span class="cap-tab-label">{{ g.label }}</span
            ><span class="cap-tab-count num" aria-hidden="true">{{ g.features.length }}</span></span
          >
        </button>
        <span ref="indicator" class="capability-tab-indicator" aria-hidden="true"></span>
      </div>
      <div ref="browser" class="feature-browser" data-reveal="block">
        <div
          v-for="g in shown"
          :id="`feature-group-${g.id}`"
          :key="g.id"
          class="feature-group"
          role="tabpanel"
          :aria-labelledby="`group-${g.id}`"
          :hidden="group !== g.id"
        >
          <p class="feature-group-label">{{ g.label }}</p>
          <p class="feature-group-intro">{{ g.intro }}</p>
          <details
            v-for="f in g.features"
            :id="`feature-${f.id}`"
            :key="f.id"
            class="feature-item"
            :class="{
              'is-selected': enhanced && !mobile && selected[g.id] === f.id,
              'is-leaving': leaving === f.id,
            }"
            :data-feature="f.id"
            :open="isOpen(g.id, f.id)"
            :inert="leaving === f.id ? true : undefined"
          >
            <summary @click="onSummaryClick($event, g.id, f.id)" @keydown="onSummaryKeydown">
              <AppIcon :name="f.icon" /><span class="feature-name">{{ f.name }}</span
              ><span v-if="f.badge" class="feature-badge">{{ f.badge }}</span
              ><AppIcon name="arrow" class="feature-chevron" /><span
                v-if="showBar(g.id, f.id)"
                class="feature-active-bar"
                data-flip-id="feature-active"
                aria-hidden="true"
              ></span>
            </summary>
            <FeaturePanel
              :feature="f"
              :active="isActive(g.id, f.id)"
              @scene="onScene"
              @term="onTerm"
            />
          </details>
        </div>
      </div>
      <p class="capability-footnote" data-reveal="block">
        <AppIcon name="link" />资料有位置，计算有依据，成果有去处。
      </p>
    </div>
    <ZtPopover
      ref="termPop"
      id="cap-term-popover"
      :title="termKey"
      :lead="termKey ? glossary[termKey] : ''"
    />
  </section>
</template>
