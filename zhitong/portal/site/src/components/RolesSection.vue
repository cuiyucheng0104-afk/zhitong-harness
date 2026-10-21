<script setup lang="ts">
/**
 * 适用岗位（03 章 §1）。
 *
 * - 钉住模式（≥ 1024px、高 ≥ 640px、未减少动效且 `html.motion-ready`）：`.roles-stage` 钉住 100vh，
 *   三个吸附点对应三个岗位（`usePinnedSteps`）；进入阶段右栏拖后、岗位图随滚动画出；比例尺连续推进。
 * - 非钉住模式：页签切换不滚动；入场与视差；触屏横扫切换（只在 `(hover: none)` 下注册）。
 * - 岗位切换时间线 §1.5.3（面板文字 0.64s 内就位），岗位图切换 §1.5.4 由 RoleArt 播放。
 * - 任务入口点击打开全区共用的说明卡 `#role-task-popover`；打开 0.2s 后播放该任务的小动画（按需加载）。
 * - 预渲染：选中工程师，其余面板带 `hidden`；水合后改为 `visibility: hidden` + `inert`，容器高度恒为最高面板。
 */
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, type Component } from 'vue';
import AppIcon from './AppIcon.vue';
import ZtPopover from './ui/ZtPopover.vue';
import TaskChip from './roles/TaskChip.vue';
import TaskPopoverBody from './roles/TaskPopoverBody.vue';
import RoleArt from './roles/RoleArt.vue';
import { PIN_QUERY, usePinnedSteps, type StepSource } from '../composables/usePinnedSteps';
import { loadMicro } from './roles/micro';
import type { MicroBuild } from './roles/micro/types';
import { ROLES, ROLE_TASKS, type CapabilityId, type RoleTask } from '../data/roles';
import { onTabKeydown } from '../lib/navigation';
import { getMotion, loadMotion, prefersReducedMotion, type Motion } from '../lib/motion';
import { DUR, EASE, MS, SCRUB, STAGGER } from '../lib/motion-tokens';
import { useHoverIndicator } from '../composables/useHoverIndicator';
import { REVEAL_START } from '../composables/useReveal';
import type { PortalAction } from '../types/portal';

const emit = defineEmits<{ action: [action: PortalAction] }>();

const stage = ref<HTMLElement | null>(null);
const tablist = ref<HTMLElement | null>(null);
const indicator = ref<HTMLElement | null>(null);
const panelsEl = ref<HTMLElement | null>(null);
const mainEl = ref<HTMLElement | null>(null);
const headingEl = ref<HTMLElement | null>(null);
const artWrap = ref<HTMLElement | null>(null);
const rulerEl = ref<HTMLElement | null>(null);
const art = ref<InstanceType<typeof RoleArt> | null>(null);
const pop = ref<InstanceType<typeof ZtPopover> | null>(null);
const microHost = ref<HTMLElement | null>(null);

const activeIndex = ref(0);
const active = computed(() => ROLES[activeIndex.value]!);
const hydrated = ref(false);
const shownPanels = ref<number[]>([0]);
const hovered = ref<CapabilityId | null>(null);
const activeTask = shallowRef<RoleTask>(ROLE_TASKS[0]!);
const popOpen = ref(false);
const microComp = shallowRef<Component | null>(null);
const highlight = computed(() => hovered.value ?? (popOpen.value ? activeTask.value.capability : null));
const RULER_TICKS = Array.from({ length: 11 }, (_, i) => i);

let switchTl: gsap.core.Timeline | null = null;
let entryArt: gsap.core.Timeline | null = null;
let mm: gsap.MatchMedia | undefined;
let alive = false;

const motionReady = () =>
  typeof document !== 'undefined' && document.documentElement.classList.contains('motion-ready');

const pinned = usePinnedSteps({
  stage,
  steps: 3,
  onStep: (i, source) => setRole(i, source),
  setup: setupPinned,
});

useHoverIndicator({
  container: tablist,
  indicator,
  items: '[role="tab"]',
  driver: 'css',
  active: () => tablist.value?.querySelectorAll<HTMLElement>('[role="tab"]')[activeIndex.value] ?? null,
});

function partsOf(index: number) {
  const panel = panelsEl.value?.querySelector<HTMLElement>(`#role-panel-${ROLES[index]!.id}`);
  if (!panel) return null;
  return {
    title: panel.querySelector('.role-panel__title'),
    body: panel.querySelector('.role-panel__body'),
    chipsRow: panel.querySelector('.task-chips'),
    chips: [...panel.querySelectorAll('.task-chip')],
  };
}

function finishEntry() {
  if (!entryArt) return;
  entryArt.scrollTrigger?.kill();
  entryArt.progress(1).kill();
  entryArt = null;
}

/** 岗位切换（§1.5.3）。`refresh` 与无动效时直接替换。 */
function setRole(i: number, source: StepSource) {
  const prev = activeIndex.value;
  if (i === prev) return;
  if (popOpen.value) pop.value?.hide({ returnFocus: false });
  switchTl?.progress(1).kill();
  switchTl = null;
  const motion = getMotion();
  const animate = source !== 'refresh' && !!motion && motionReady() && hydrated.value;
  if (!animate) {
    activeIndex.value = i;
    shownPanels.value = [i];
    return;
  }
  finishEntry();
  art.value?.animateNext();
  activeIndex.value = i;
  shownPanels.value = [prev, i];
  const dir = i > prev ? 1 : -1;
  void nextTick(() => {
    const { gsap } = motion;
    const from = partsOf(prev);
    const to = partsOf(i);
    if (!from || !to) return;
    const old = [from.title, from.body, from.chipsRow].filter(Boolean) as Element[];
    const fresh = [to.title, to.body, ...to.chips].filter(Boolean) as Element[];
    const tl = gsap.timeline({
      onComplete: () => {
        gsap.set(fresh, { clearProps: 'transform,opacity' });
      },
    });
    tl.to(old, { x: -16 * dir, opacity: 0, duration: DUR.micro, ease: EASE.out, stagger: 0.02 }, 0);
    tl.call(() => {
      shownPanels.value = [activeIndex.value];
    }, undefined, 0.16);
    tl.set(old, { clearProps: 'transform,opacity' }, 0.22);
    if (to.title)
      tl.fromTo(to.title, { x: 24 * dir, opacity: 0 }, { x: 0, opacity: 1, duration: DUR.base, ease: EASE.out }, 0.12);
    if (to.body)
      tl.fromTo(to.body, { x: 24 * dir, opacity: 0 }, { x: 0, opacity: 1, duration: DUR.base, ease: EASE.out }, 0.18);
    tl.fromTo(
      to.chips,
      { y: 8, opacity: 0 },
      { y: 0, opacity: 1, duration: DUR.short, ease: EASE.out, stagger: STAGGER.tight },
      0.24,
    );
    switchTl = tl;
  });
}

function selectRole(i: number) {
  void pinned.goTo(i);
}

function step(delta: number) {
  const next = activeIndex.value + delta;
  if (next < 0 || next >= ROLES.length) return;
  void pinned.goTo(next);
}

function drawTargets(svg: SVGSVGElement) {
  const group = svg.querySelector(`[data-art="${active.value.id}"]`);
  return {
    draws: [...svg.querySelectorAll('[data-frame]'), ...(group?.querySelectorAll('[data-draw]') ?? [])],
    fades: [...(group?.querySelectorAll('[data-fade]') ?? [])],
  };
}

/** 钉住模式的进入与跟随动画（与钉住同一条件块，§1.5.1）。 */
function setupPinned(st: InstanceType<Motion['ScrollTrigger']>, motion: Motion) {
  const { gsap } = motion;
  const section = stage.value?.closest('section');
  const svg = art.value?.svg;
  if (!section || !svg) return;
  const enter = { trigger: section, start: 'top bottom', end: 'top top+=64' };
  if (mainEl.value)
    gsap.fromTo(mainEl.value, { y: 48 }, { y: 0, ease: 'none', scrollTrigger: { ...enter, scrub: SCRUB.damp } });
  const { draws, fades } = drawTargets(svg);
  const t = gsap.timeline({ scrollTrigger: { ...enter, scrub: SCRUB.heavy } });
  t.fromTo(draws, { drawSVG: '0% 0%' }, { drawSVG: '0% 100%', ease: 'none', duration: 0.7, stagger: { amount: 0.3 } }, 0);
  t.fromTo(fades, { opacity: 0 }, { opacity: 1, ease: 'none', duration: 0.4 }, 0.6);
  entryArt = t;
  const during = { start: () => st.start, end: () => st.end };
  if (headingEl.value)
    gsap.fromTo(headingEl.value, { y: 0 }, { y: -16, ease: 'none', scrollTrigger: { ...during, scrub: SCRUB.damp } });
  if (artWrap.value)
    gsap.fromTo(artWrap.value, { y: 8 }, { y: -8, ease: 'none', scrollTrigger: { ...during, scrub: SCRUB.heavy } });
  if (rulerEl.value)
    gsap.fromTo(
      rulerEl.value,
      { '--rp': 0 },
      { '--rp': 1, ease: 'none', scrollTrigger: { ...during, scrub: SCRUB.soft } },
    );
}

/** 非钉住模式：入场、视差、触屏横扫（§1.5.2）。 */
function setupLoose(motion: Motion) {
  const { gsap, Observer } = motion;
  mm = gsap.matchMedia();
  mm.add(
    { pin: PIN_QUERY, wide: '(min-width: 768px)', touch: '(hover: none)', reduce: '(prefers-reduced-motion: reduce)' },
    (ctx) => {
      const c = ctx.conditions ?? {};
      const isPinned = !!c.pin && motionReady();
      if (isPinned) return;
      const svg = art.value?.svg;
      if (!c.reduce && motionReady()) {
        if (mainEl.value)
          gsap.from(mainEl.value, {
            y: 24,
            opacity: 0,
            duration: DUR.base,
            ease: EASE.out,
            clearProps: 'opacity,transform',
            scrollTrigger: { trigger: mainEl.value, start: REVEAL_START, once: true },
          });
        if (svg) {
          const { draws, fades } = drawTargets(svg);
          const t = gsap.timeline({ scrollTrigger: { trigger: svg, start: 'top 75%', once: true } });
          t.fromTo(
            draws,
            { drawSVG: '0% 0%' },
            { drawSVG: '0% 100%', duration: DUR.long, ease: EASE.inOut, stagger: { amount: 0.3 } },
          );
          t.fromTo(fades, { opacity: 0 }, { opacity: 1, duration: DUR.short, ease: EASE.out });
          entryArt = t;
        }
        if (c.wide && artWrap.value)
          gsap.fromTo(
            artWrap.value,
            { y: 16 },
            {
              y: -16,
              ease: 'none',
              scrollTrigger: { trigger: '#roles', start: 'top bottom', end: 'bottom top', scrub: SCRUB.soft },
            },
          );
      }
      if (c.touch && panelsEl.value) {
        const obs = Observer.create({
          target: panelsEl.value,
          type: 'touch',
          tolerance: 48,
          lockAxis: true,
          onLeft: () => step(1),
          onRight: () => step(-1),
        });
        return () => obs.kill();
      }
    },
  );
}

/* ---------- 说明卡与小动画 ---------- */
let openToken = 0;
let openedAt = 0;
let microBuild: MicroBuild | null = null;
let microTl: gsap.core.Timeline | null = null;
let microTimer = 0;
let microPending = false;

const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

async function openTask(task: RoleTask, anchor: HTMLElement) {
  const p = pop.value;
  if (!p) return;
  if (popOpen.value && activeTask.value.id === task.id) {
    p.hide();
    return;
  }
  if (popOpen.value) {
    p.hide({ returnFocus: false });
    await wait(MS.micro);
  }
  if (activeTask.value.id !== task.id) microComp.value = null;
  activeTask.value = task;
  await nextTick();
  await p.show(anchor);
}

function stopMicro() {
  clearTimeout(microTimer);
  microPending = false;
  microTl?.revert();
  microTl = null;
}

function startMicro(token: number) {
  const motion = getMotion();
  const svg = microHost.value?.querySelector('svg');
  if (!motion || !svg || !microBuild || prefersReducedMotion() || !motionReady()) return;
  stopMicro();
  microTl = microBuild(svg, motion.gsap);
  const delay = Math.max(0, 200 - (performance.now() - openedAt));
  microTimer = window.setTimeout(() => {
    if (token !== openToken || !microTl) return;
    if (document.hidden) microPending = true;
    else microTl.play();
  }, delay);
}

function onPopOpen() {
  popOpen.value = true;
  openedAt = performance.now();
  const token = ++openToken;
  const task = activeTask.value;
  loadMicro(task.micro)
    .then(async (mod) => {
      if (token !== openToken || !popOpen.value) return;
      microBuild = mod.build;
      microComp.value = markRaw(mod.default);
      await nextTick();
      startMicro(token);
    })
    .catch(() => undefined);
}

function onPopClose() {
  popOpen.value = false;
  openToken += 1;
  stopMicro();
}

function onVisibility() {
  if (!microTl) return;
  if (document.hidden) {
    if (microTl.isActive()) {
      microTl.pause();
      microPending = true;
    }
  } else if (microPending && popOpen.value) {
    microPending = false;
    microTl.play();
  }
}

function onPrimary(task: RoleTask) {
  pop.value?.hide({ returnFocus: false });
  if (task.primary.kind === 'scene') emit('action', { type: 'scene', id: task.primary.scene });
  else emit('action', { type: 'feature', id: task.capability });
}

onMounted(async () => {
  alive = true;
  hydrated.value = true;
  document.addEventListener('visibilitychange', onVisibility);
  const motion = await loadMotion();
  if (!alive || !motion) return;
  setupLoose(motion);
});

onBeforeUnmount(() => {
  alive = false;
  document.removeEventListener('visibilitychange', onVisibility);
  stopMicro();
  switchTl?.kill();
  mm?.revert();
});
</script>

<template>
  <section
    id="roles"
    class="roles-section"
    :class="{ 'is-pinned': pinned.enabled.value, 'is-hydrated': hydrated }"
    aria-labelledby="roles-title"
  >
    <div ref="stage" class="roles-stage">
      <div class="container roles-layout">
        <div ref="rulerEl" class="roles-ruler" aria-hidden="true">
          <span class="roles-ruler__base"></span>
          <span
            v-for="t in RULER_TICKS"
            :key="t"
            :class="['roles-ruler__tick', { 'is-major': t % 5 === 0, 'is-current': t === activeIndex * 5 }]"
            :style="{ top: `${t * 24}px` }"
          ></span>
          <span
            v-for="n in 3"
            :key="`n${n}`"
            :class="['roles-ruler__no', 'mono', { 'is-current': n - 1 === activeIndex }]"
            :style="{ top: `${(n - 1) * 120}px` }"
            >0{{ n }}</span
          >
          <span class="roles-ruler__fill"></span>
          <span class="roles-ruler__cursor"></span>
        </div>
        <div class="roles-side">
          <div ref="headingEl" class="section-heading roles-heading">
            <p class="eyebrow">适用岗位</p>
            <h2 id="roles-title" data-reveal="heading">一个项目，<br />多人协同。</h2>
            <p>从经手资料的人，到签发成果的人。</p>
          </div>
          <div ref="artWrap" class="roles-art">
            <RoleArt ref="art" :active="active.id" :highlight="highlight" />
          </div>
        </div>
        <div ref="mainEl" class="roles-main">
          <div ref="tablist" class="role-tabs" role="tablist" aria-label="选择岗位" @keydown="onTabKeydown">
            <button
              v-for="(role, i) in ROLES"
              :id="`role-tab-${role.id}`"
              :key="role.id"
              v-magnetic="'link'"
              type="button"
              role="tab"
              :aria-selected="activeIndex === i ? 'true' : 'false'"
              :aria-controls="`role-panel-${role.id}`"
              :tabindex="activeIndex === i ? 0 : -1"
              :data-role="role.id"
              @click="selectRole(i)"
            >
              <span class="role-tab__inner" data-magnetic-label><AppIcon :name="role.icon" />{{ role.name }}</span>
            </button>
            <span ref="indicator" class="role-tabs__indicator" aria-hidden="true"></span>
          </div>
          <div ref="panelsEl" class="role-panels" :class="{ 'is-hydrated': hydrated }">
            <div
              v-for="(role, i) in ROLES"
              :id="`role-panel-${role.id}`"
              :key="role.id"
              :class="['role-panel', { 'is-shown': shownPanels.includes(i) }]"
              role="tabpanel"
              :aria-labelledby="`role-tab-${role.id}`"
              :hidden="!hydrated && i !== activeIndex"
              :inert="hydrated && !shownPanels.includes(i) ? true : undefined"
            >
              <h3 class="role-panel__title">{{ role.title }}</h3>
              <p class="role-panel__body">{{ role.description }}</p>
              <div class="task-chips">
                <TaskChip
                  v-for="t in role.tasks"
                  :key="t.id"
                  :task="t"
                  :expanded="popOpen && activeTask.id === t.id"
                  @open="openTask"
                  @hover="(c) => (hovered = c)"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <ZtPopover
      id="role-task-popover"
      ref="pop"
      class="task-pop"
      :title="activeTask.label"
      @open="onPopOpen"
      @close="onPopClose"
    >
      <TaskPopoverBody :task="activeTask" @primary="onPrimary" />
      <template #art>
        <div ref="microHost" class="task-micro" :data-micro="activeTask.micro">
          <component :is="microComp" v-if="microComp" />
        </div>
      </template>
    </ZtPopover>
  </section>
</template>
