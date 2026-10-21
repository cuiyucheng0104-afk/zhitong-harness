<script setup lang="ts">
/**
 * 它解决什么（03 章 §2）。
 *
 * - 钉住模式（与岗位区相同条件）：`.problem-scene` 钉在 `top top+=88`，钉住 200vh，`scrub: SCRUB.damp`，
 *   五个吸附点 0 / 0.25 / 0.5 / 0.75 / 1；时间线总长 1，关键帧与明细见 §2.5.1。
 * - 非钉住模式：网格、标记、线程一次性入场，计数器 `useCountUp`（§2.5.2）；不画扇形线、顺序线与删除线。
 * - 减少动效、动效未加载、无 JS：静态终态（预渲染 HTML 即此状态），本区块不注册任何 ScrollTrigger。
 * - 场景容器 `role="img"` + `aria-describedby="problem-scene-desc"`，内部 `aria-hidden`；钉住区内没有可聚焦元素。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue';
import LegacyGrid from './problem/LegacyGrid.vue';
import ConversationThread from './problem/ConversationThread.vue';
import ProblemCounter from './problem/ProblemCounter.vue';
import { attachLenisSnap, PIN_QUERY, snapOption } from '../composables/usePinnedSteps';
import { CLICK_MARKERS, LEGACY_PANELS, PROBLEM_COPY, THREAD_ROWS, type LegacyId } from '../data/problem';
import { loadMotion, type Motion } from '../lib/motion';
import { DUR, EASE, SCRUB, STAGGER } from '../lib/motion-tokens';

const C = PROBLEM_COPY;
const SNAPS = [0, 0.25, 0.5, 0.75, 1] as const;
/** 线程第 i 行出现的位置（时间线单位）。 */
const rowStart = (i: number) => 0.78 + i * 0.022;

const scene = ref<HTMLElement | null>(null);
const grid = ref<InstanceType<typeof LegacyGrid> | null>(null);
const thread = ref<HTMLElement | null>(null);
const pinnedOn = ref(false);
/** 钉住时间线驱动的已完成行数；undefined = 全部完成。 */
const threadDone = ref<number | undefined>(undefined);

let mm: gsap.MatchMedia | undefined;
let alive = false;

function q<T extends Element = HTMLElement>(sel: string, root: ParentNode | null | undefined = scene.value) {
  return root ? [...root.querySelectorAll<T>(sel)] : [];
}

const lazyPath = (fn: () => MotionPath.Vars) => fn as unknown as MotionPath.Vars;

/** 钉住时间线（§2.5.1）。 */
function buildPinned(motion: Motion) {
  const { gsap, ScrollTrigger } = motion;
  const sceneEl = scene.value;
  const g = grid.value;
  const gridEl = g?.root;
  const threadEl = thread.value;
  if (!sceneEl || !g || !gridEl || !threadEl) return;
  pinnedOn.value = true;
  threadDone.value = 0;
  let centers = g.layout();
  const relayout = () => {
    centers = g.layout();
  };
  ScrollTrigger.addEventListener('refreshInit', relayout);

  const panelIndex = new Map(LEGACY_PANELS.map((p, i) => [p.id, i]));
  const dots = q<HTMLElement>('.click-dot', gridEl);
  const order = [...dots].sort((a, b) => {
    const ka = Number(a.dataset.k);
    const kb = Number(b.dataset.k);
    if (ka !== kb) return ka - kb;
    const pa = panelIndex.get(a.closest<HTMLElement>('.legacy-panel')!.dataset.panel as LegacyId) ?? 0;
    const pb = panelIndex.get(b.closest<HTMLElement>('.legacy-panel')!.dataset.panel as LegacyId) ?? 0;
    return pa - pb;
  });
  const ripples = order.map((d) => d.querySelector('.click-ripple')).filter(Boolean) as Element[];
  const head = sceneEl.querySelector<HTMLElement>('.counter-head');
  const caps = q('.scene-captions > li');
  const overlay = g.overlay;
  const rows = q('.conv-row', threadEl);

  const tl = gsap.timeline({
    defaults: { ease: 'none' },
    scrollTrigger: {
      trigger: sceneEl,
      start: 'top top+=88',
      end: () => `+=${Math.round(window.innerHeight * 2)}`,
      pin: true,
      pinSpacing: true,
      scrub: SCRUB.damp,
      anticipatePin: 1,
      invalidateOnRefresh: true,
      snap: snapOption(SNAPS),
    },
    onUpdate: () => {
      const p = tl.progress();
      let n = 0;
      for (let i = 0; i < rows.length; i += 1) if (p >= rowStart(i) + 0.02) n = i + 1;
      if (threadDone.value !== n) threadDone.value = n;
    },
  });

  // 0.02–0.25：点击标记与计数器
  tl.fromTo(order, { scale: 0, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.02, stagger: { each: 0.0018 } }, 0.02);
  tl.fromTo(ripples, { scale: 1 / 3, opacity: 0.6 }, { scale: 1, opacity: 0, duration: 0.02, stagger: { each: 0.0018 } }, 0.02);
  if (head) head.textContent = '0';
  const proxy = { v: 0 };
  tl.fromTo(
    proxy,
    { v: 0 },
    {
      v: 60,
      duration: 0.2,
      onUpdate: () => {
        if (head) head.textContent = String(Math.round(proxy.v));
      },
    },
    0.02,
  );
  tl.fromTo(q('.counter-old .counter-tail, .counter-old .counter-unit, .counter-old .counter-note'), { opacity: 0 }, { opacity: 1, duration: 0.03 }, 0.22);
  const cross = (i: number, at: number) => {
    if (!caps[i] || !caps[i + 1]) return;
    tl.to(caps[i], { opacity: 0, y: -6, duration: 0.02 }, at);
    tl.fromTo(caps[i + 1], { opacity: 0, y: 6 }, { opacity: 1, y: 0, duration: 0.02 }, at);
  };
  // 明细表的交叉淡变（0.24 / 0.49 / 0.74 起）跨在吸附点上，停下时两条图注各半透明；
  // 按关键帧表（0.25 → ①、0.5 → ②、0.75 → ③、1 → ④）整体后移 0.02，吸附点上只有一条图注。
  cross(0, 0.26);
  // 0.25–0.5：文件签、扇形线、待确认、“上次结果”
  tl.fromTo(q('[data-o="tag"]', overlay), { opacity: 0, y: -8 }, { opacity: 1, y: 0, duration: 0.06 }, 0.27);
  tl.fromTo(q('[data-o="fan"]', overlay), { drawSVG: '0% 0%' }, { drawSVG: '0% 100%', duration: 0.06, stagger: 0.03 }, 0.3);
  tl.fromTo(q('.pending-mark', gridEl), { scale: 0 }, { scale: 1, duration: 0.02, stagger: 0.01 }, 0.36);
  tl.fromTo(q('.lp-last', gridEl), { opacity: 0, x: 6 }, { opacity: 1, x: 0, duration: 0.05, stagger: 0.03 }, 0.4);
  cross(1, 0.51);
  // 0.5–0.75：顺序虚线与 ①–⑨、删除线
  tl.fromTo(q('[data-o="seq"]', overlay), { drawSVG: '0% 0%' }, { drawSVG: '0% 100%', duration: 0.16 }, 0.52);
  const seg = centers.map((c, i) => (i ? Math.hypot(c.x - centers[i - 1]!.x, c.y - centers[i - 1]!.y) : 0));
  const total = seg.reduce((a, b) => a + b, 0) || 1;
  let run = 0;
  q('[data-o="no"]', overlay).forEach((no, i) => {
    run += seg[i] ?? 0;
    tl.fromTo(no, { scale: 0.6, opacity: 0, transformOrigin: '50% 50%' }, { scale: 1, opacity: 1, duration: 0.02 }, Math.min(0.66, 0.52 + (run / total) * 0.16 - 0.01));
  });
  tl.fromTo(q('[data-o="strike"]', overlay), { drawSVG: '0% 0%' }, { drawSVG: '0% 100%', duration: 0.06 }, 0.66);
  tl.fromTo(q('.lp-retired', gridEl), { opacity: 0 }, { opacity: 1, duration: 0.06 }, 0.66);
  cross(2, 0.76);
  // 0.75–1：收拢到对话线程
  tl.to(overlay, { opacity: 0, duration: 0.06 }, 0.76);
  tl.to(q('.pending-mark, .lp-retired', gridEl), { opacity: 0, duration: 0.06 }, 0.76);
  tl.fromTo(
    [threadEl, ...q('.conv__title, .conv__bubble', threadEl)],
    { opacity: 0, x: 24 },
    { opacity: 1, x: 0, duration: 0.04 },
    0.76,
  );
  const retired = order.filter((d) => d.closest<HTMLElement>('.legacy-panel')!.dataset.fate === 'retired');
  tl.to(retired, { scale: 0, opacity: 0, duration: 0.08 }, 0.76);
  tl.fromTo(
    rows,
    { opacity: 0, x: 12 },
    {
      // idle 行终态保持 0.45（§2.3）。
      opacity: (_i: number, el: Element) => (el.classList.contains('is-idle') ? 0.45 : 1),
      x: 0,
      duration: 0.03,
      stagger: 0.022,
    },
    0.78,
  );

  const rowFor = new Map(LEGACY_PANELS.map((p) => [p.id, p.target]));
  const flyFrom = LEGACY_PANELS.filter((p) => p.fate !== 'retired');
  const target = (dot: HTMLElement) => {
    const panel = dot.closest<HTMLElement>('.legacy-panel')!;
    const rowId = rowFor.get(panel.dataset.panel as LegacyId);
    const row = threadEl.querySelector<HTMLElement>(`[data-row="${rowId}"]`);
    const body = sceneEl.querySelector<HTMLElement>('.scene-body');
    if (!row || !body) return { dx: 0, dy: 0 };
    const offset = (el: HTMLElement) => {
      let x = 0;
      let y = 0;
      let n: HTMLElement | null = el;
      while (n && n !== body) {
        x += n.offsetLeft;
        y += n.offsetTop;
        n = n.offsetParent as HTMLElement | null;
      }
      return { x, y };
    };
    const base = g.dotBase(dot);
    const gridOff = offset(gridEl);
    const rowOff = offset(row);
    return {
      dx: rowOff.x - (gridOff.x + base.x),
      dy: rowOff.y + row.offsetHeight / 2 - (gridOff.y + base.y),
    };
  };
  flyFrom.forEach((p, pi) => {
    const own = dots.filter((d) => d.closest<HTMLElement>('.legacy-panel')!.dataset.panel === p.id);
    own.forEach((dot, k) => {
      const at = 0.78 + pi * 0.012 + k * 0.0015;
      tl.to(
        dot,
        {
          // 函数值在每次 invalidate（refresh）后重新求值；GSAP 类型声明未覆盖插件属性的函数值。
          motionPath: lazyPath(() => {
            const { dx, dy } = target(dot);
            return {
              path: [
                { x: 0, y: 0 },
                { x: dx / 2, y: dy / 2 - 40 },
                { x: dx, y: dy },
              ],
              curviness: 1.2,
            };
          }),
          duration: 0.06,
        },
        at,
      );
      tl.to(dot, { scale: 0.4, opacity: 0, duration: 0.02 }, at + 0.04);
    });
  });
  tl.to(q('.legacy-panel', gridEl), { opacity: 0.28, scale: 0.96, duration: 0.15 }, 0.8);
  tl.to(q('.counter-old'), { opacity: 0, y: -8, duration: 0.06 }, 0.84);
  tl.fromTo(q('.counter-new'), { opacity: 0, y: 8 }, { opacity: 1, y: 0, duration: 0.06 }, 0.84);
  tl.call(() => undefined, undefined, 1);

  const st = tl.scrollTrigger;
  const detach = st ? attachLenisSnap(motion, st, SNAPS) : () => undefined;
  return () => {
    detach();
    ScrollTrigger.removeEventListener('refreshInit', relayout);
    if (head) head.textContent = C.counterOld.head;
    pinnedOn.value = false;
    threadDone.value = undefined;
  };
}

/** 非钉住模式入场（§2.5.2）。 */
function buildLoose(motion: Motion) {
  const { gsap } = motion;
  const gridEl = grid.value?.root;
  const threadEl = thread.value;
  if (gridEl) {
    const t = gsap.timeline({ scrollTrigger: { trigger: gridEl, start: 'top 80%', once: true } });
    t.from(q('.legacy-panel', gridEl), { y: 12, opacity: 0, duration: DUR.base, ease: EASE.out, stagger: STAGGER.tight, clearProps: 'transform,opacity' }, 0);
    t.from(q('.click-dot', gridEl), { scale: 0, duration: DUR.micro, ease: EASE.out, stagger: 0.006 }, 0.3);
    t.from(q('.pending-mark, .lp-last', gridEl), { opacity: 0, duration: DUR.short, ease: EASE.out }, 0.9);
  }
  if (threadEl)
    gsap.from([...q('.conv__title, .conv__bubble', threadEl), ...q('.conv-row', threadEl)], {
      y: 24,
      opacity: 0,
      duration: DUR.base,
      ease: EASE.out,
      stagger: STAGGER.base,
      clearProps: 'transform,opacity',
      scrollTrigger: { trigger: threadEl, start: 'top 80%', once: true },
    });
}

onMounted(async () => {
  alive = true;
  const motion = await loadMotion();
  if (!alive || !motion) return;
  mm = motion.gsap.matchMedia();
  mm.add({ pin: PIN_QUERY, reduce: '(prefers-reduced-motion: reduce)' }, (ctx) => {
    const c = ctx.conditions ?? {};
    if (c.reduce || !document.documentElement.classList.contains('motion-ready')) return;
    if (c.pin) return buildPinned(motion);
    buildLoose(motion);
  });
});

onBeforeUnmount(() => {
  alive = false;
  mm?.revert();
});
</script>

<template>
  <section id="problem" class="problem-section section-space" :class="{ 'is-pinned': pinnedOn }" aria-labelledby="problem-title">
    <div class="container">
      <div class="section-heading problem-heading">
        <h2 id="problem-title" data-reveal="heading">{{ C.title }}</h2>
        <p>{{ C.subtitle }}</p>
      </div>
      <div ref="scene" class="problem-scene">
        <div class="scene-bar">
          <ol class="scene-captions" aria-hidden="true">
            <li v-for="(cap, i) in C.captions" :key="i" :data-caption="i + 1">
              <span class="scene-captions__no mono">{{ i + 1 }}</span>{{ cap }}
            </li>
          </ol>
          <ProblemCounter :mode="pinnedOn ? 'scrub' : 'count'" />
        </div>
        <div class="scene-body" role="img" aria-describedby="problem-scene-desc">
          <div class="scene-legacy" aria-hidden="true">
            <LegacyGrid ref="grid" :panels="LEGACY_PANELS" :markers="CLICK_MARKERS" />
            <p class="scene-caption">{{ C.gridCaption }}</p>
          </div>
          <div class="scene-thread" aria-hidden="true">
            <div ref="thread" class="scene-thread__box">
              <ConversationThread :rows="THREAD_ROWS" :done="threadDone" />
            </div>
            <p class="scene-caption">{{ C.threadCaption }}</p>
          </div>
        </div>
      </div>
      <p id="problem-scene-desc" class="sr-only">{{ C.sceneDesc }}</p>
    </div>
  </section>
</template>
