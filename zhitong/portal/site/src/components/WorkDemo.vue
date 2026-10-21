<script setup lang="ts">
/**
 * 首屏工作示例 `#demo`（02 章 §2）：窗口外壳、场景页签与进度条、底栏、`useAutoplay` 接线、热区层、模拟指针、出处弹层、文字版。
 *
 * 时钟：每个场景只有一个时刻（`times[i]`，秒）。自动播放时由 useAutoplay 的时钟经 `setTimeline` 写入；
 * 用户主动请求的内容（点页签、提交提问卡、重播、“播放演示”）作为“响应片段”由本组件自己的 rAF 推进到 `end` 后停住，
 * 只受 hidden / offscreen / dialog（与置顶暂停）阻挡（§2.5.2）。场景面板上的 `--t` 驱动全部补间（见 demo/engine.ts）。
 * 预渲染与无 JS：三个场景都是终态，只显示场景 1；减少动效与动效块加载失败：不自动播放，页签切换直接显示终态。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
import SourceDialog from './SourceDialog.vue';
import DemoChat from './demo/DemoChat.vue';
import CheckPreview from './demo/CheckPreview.vue';
import ReviewPreview from './demo/ReviewPreview.vue';
import CadPreview from './demo/CadPreview.vue';
import DemoHotspot from './demo/DemoHotspot.vue';
import DemoCursor from './demo/DemoCursor.vue';
import { SCENES, type HitlState, type Principle } from '../data/demo';
import { useAutoplay } from '../composables/useAutoplay';
import { useHoverIndicator } from '../composables/useHoverIndicator';
import { useMediaQuery } from '../composables/useMediaQuery';
import { announce } from '../composables/useToast';
import { loadMotion } from '../lib/motion';
import { onTabKeydown } from '../lib/navigation';
import { scrollToSection } from '../lib/smooth-scroll';
import { CSS_EASE, MS } from '../lib/motion-tokens';
import type { SceneId } from '../types/portal';
import { compileScene, easeInOut, principleAt, visibleHotspots } from './demo/engine';
import { DEMO_CONTEXT, createDemoStore, utcSeconds } from './demo/store';
import { currentPrinciple, demoHandle, type DemoHandle } from './demo/bus';

const store = createDemoStore();
const mobile = useMediaQuery('(max-width: 767px)');
const split = useMediaQuery('(min-width: 1280px)');
const reducedMq = useMediaQuery('(prefers-reduced-motion: reduce)');
const motionReady = ref(false);
const motionFailed = ref(false);
/** 可以按时间线播放（动效块就绪且未减少动效）。 */
const canAnimate = computed(() => motionReady.value && !reducedMq.value);
const still = computed(() => !canAnimate.value);

const stage = ref<HTMLElement | null>(null);
const bench = ref<HTMLElement | null>(null);
const tabsEl = ref<HTMLElement | null>(null);
const indicator = ref<HTMLElement | null>(null);
const panels = ref<HTMLElement[]>([]);

const compiled = computed(() => SCENES.map((s) => compileScene(s, s.id === 'review' ? store.decision.value : 'confirmed')));
/** 每个场景的时刻（秒）；预渲染为终态。 */
const times = reactive(SCENES.map((s) => s.end));

/* ---------- 轮播 ---------- */
const bound = ref(false);
let gateOpen = false;
const started = ref(false);
const autoplay = useAutoplay({
  scenes: SCENES.map((s) => ({ duration: s.end, hold: s.hold })),
  target: stage,
  hoverTarget: bench,
  hoverResumeDelay: 0.6,
  manualIdle: 8,
  visibleRatio: 0.35,
  loopLimit: 3,
  onScene: (i, info) => onScene(i, info.user),
});
const index = computed(() => autoplay.index.value);
const current = computed(() => SCENES[index.value]!);
autoplay.setTimeline({
  time(v: number) {
    if (bound.value) times[autoplay.index.value] = v;
  },
});

/** 响应片段（§2.5.2）：用户请求的内容播到 end 后停住。 */
const resp = ref<{ scene: number; to: number } | null>(null);
/** 手动模式下当前场景的时刻（驱动页签进度），自动推进时清空。 */
const manualTime = ref<number | null>(null);
let respFrame = 0;
let respLast = 0;
const blocked = computed(() => {
  const r = autoplay.reasons.value;
  return r.includes('hidden') || r.includes('offscreen') || r.includes('dialog') || autoplay.state.value === 'sticky';
});
let idleKick = 0;
/** 手动模式的 8 s 空闲计时从响应片段播完才开始：播放中每秒重置一次，播完再重置一次。 */
function holdManual(now: number, force = false) {
  if (!force && now - idleKick < 1000) return;
  idleKick = now;
  if (autoplay.state.value === 'manual') autoplay.pause('user');
}
function respLoop(now: number) {
  const job = resp.value;
  if (!job) return;
  const dt = respLast ? Math.min(0.1, (now - respLast) / 1000) : 0;
  respLast = now;
  holdManual(now);
  if (!blocked.value) {
    const next = Math.min(job.to, times[job.scene]! + dt);
    times[job.scene] = next;
    manualTime.value = next;
    if (next >= job.to) {
      resp.value = null;
      holdManual(now, true);
      return;
    }
  }
  respFrame = requestAnimationFrame(respLoop);
}
function playResponse(scene: number, from: number, to = SCENES[scene]!.end) {
  cancelAnimationFrame(respFrame);
  times[scene] = from;
  manualTime.value = from;
  if (typeof requestAnimationFrame !== 'function') {
    times[scene] = to;
    manualTime.value = to;
    return;
  }
  resp.value = { scene, to };
  respLast = 0;
  respFrame = requestAnimationFrame(respLoop);
}
function stopResponse() {
  cancelAnimationFrame(respFrame);
  resp.value = null;
}

/* 场景切换动效（§2.5.5）：当前面板 x 0 → −16 淡出，下一面板 x 16 → 0 淡入，重叠 0.08 s。 */
const leaving = ref<number | null>(null);
function animateSwitch(from: number, to: number) {
  const out = panels.value[from];
  const inn = panels.value[to];
  if (!canAnimate.value || !out || !inn || typeof inn.animate !== 'function') return;
  leaving.value = from;
  const opts = { duration: MS.short, easing: CSS_EASE.inOut };
  const a = out.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateX(-16px)' }], { ...opts, fill: 'forwards' });
  inn.animate([{ opacity: 0, transform: 'translateX(16px)' }, { opacity: 1, transform: 'none' }], {
    ...opts,
    delay: MS.short - 80,
    fill: 'backwards',
  });
  void a.finished
    .catch(() => undefined)
    .then(() => {
      a.cancel();
      if (leaving.value === from) leaving.value = null;
    });
}

function onScene(i: number, user: boolean) {
  const prev = shownIndex.value;
  stopResponse();
  if (!user) manualTime.value = null;
  store.reset(SCENES[i]!.id);
  if (prev !== i) {
    shownIndex.value = i;
    animateSwitch(prev, i);
  }
}
/** 正在显示的面板（与 autoplay.index 同步，用于切换动画的“上一个”）。 */
const shownIndex = ref(0);

/** 进入手动模式（点了示例内任何按钮）。 */
function interact() {
  autoplay.pause('user');
}

function openGate() {
  if (gateOpen) return;
  gateOpen = true;
  if (!document.hidden) autoplay.resume('hidden');
}

/** 用户选场景（页签、滑动、看示例）：手动模式 + 响应片段从 0 s 播放。 */
function selectScene(i: number, opts: { announce?: boolean } = {}) {
  if (canAnimate.value) {
    bound.value = true;
    started.value = true;
    openGate();
  }
  autoplay.goTo(i, { user: true });
  if (canAnimate.value) playResponse(i, 0);
  else times[i] = SCENES[i]!.end;
  if (opts.announce !== false) announce(`已切换到：${SCENES[i]!.tab}`);
}

function restart() {
  stopResponse();
  if (canAnimate.value) {
    bound.value = true;
    started.value = true;
    openGate();
  }
  manualTime.value = null;
  autoplay.restart();
  autoplay.resume('focus');
  if (!canAnimate.value) times[0] = SCENES[0]!.end;
}

function replay() {
  const i = index.value;
  store.reset(SCENES[i]!.id);
  if (canAnimate.value || reducedMq.value) {
    if (canAnimate.value) bound.value = true;
    autoplay.goTo(i, { user: true });
    playResponse(i, 0);
  }
}

function toggle() {
  if (reducedMq.value) {
    // 减少动效：“播放演示”按时间线播放当前场景（只保留透明度与逐字），播完停住。
    store.reset(current.value.id);
    playResponse(index.value, 0);
    return;
  }
  if (autoplay.state.value === 'done') return restart();
  if (canAnimate.value && !bound.value) {
    bound.value = true;
    started.value = true;
    openGate();
  }
  autoplay.toggle();
}

/* ---------- 首次启动（§2.5.3） ---------- */
function firstStart() {
  started.value = true;
  const fresh = performance.now() <= 1200 && window.scrollY < 40;
  if (!fresh) {
    bound.value = true;
    autoplay.tick(SCENES[0]!.end);
    return;
  }
  const panel = panels.value[0];
  const anim = panel?.animate?.([{ opacity: 1 }, { opacity: 0 }], { duration: 200, easing: CSS_EASE.out, fill: 'forwards' });
  const go = () => {
    store.reset('check');
    bound.value = true;
    times[0] = Math.min(autoplay.elapsed.value, SCENES[0]!.end);
    anim?.cancel();
  };
  if (anim) void anim.finished.catch(() => undefined).then(go);
  else go();
}
watch(
  () => autoplay.playing.value,
  (playing) => {
    if (playing && gateOpen && !started.value && canAnimate.value) firstStart();
  },
);
/* 动效块就绪前用 hidden 原因挡住时钟（visibilitychange 也不放行）。 */
watch(
  () => autoplay.reasons.value,
  (r) => {
    if (!gateOpen && !r.includes('hidden')) autoplay.pause('hidden');
  },
);

/* ---------- 页签进度（§2.5.4） ---------- */
const tabProgress = computed(() =>
  SCENES.map((s, i) => {
    if (!bound.value && !resp.value) return 0;
    if (i < index.value) return 1;
    if (i > index.value) return 0;
    if (manualTime.value !== null) return Math.min(1, manualTime.value / (s.end + s.hold));
    return autoplay.progress.value;
  }),
);
const running = computed(() => (resp.value ? !blocked.value : autoplay.playing.value && bound.value));

/* ---------- 热区、原则条、模拟指针 ---------- */
const hoverPaused = computed(() => {
  const r = autoplay.reasons.value;
  return r.includes('hover') || r.includes('focus') || r.includes('user');
});
const hotspots = computed(() => compiled.value.map((c, i) => visibleHotspots(c, times[i]!, hoverPaused.value)));
const hotspotPulse = computed(() => canAnimate.value && !autoplay.reasons.value.includes('offscreen') && !autoplay.reasons.value.includes('hidden'));

const principleNow = computed<Principle | null>(() => {
  const st = autoplay.state.value;
  const r = autoplay.reasons.value;
  if (!canAnimate.value || !started.value || st === 'done' || st === 'reduced') return null;
  if (r.includes('offscreen') || r.includes('hidden')) return null;
  const t = resp.value ? times[resp.value.scene]! : manualTime.value ?? autoplay.elapsed.value;
  return principleAt(current.value, t);
});
watch(
  principleNow,
  (p) => {
    const st = autoplay.state.value;
    const frozen = p !== null && (st === 'paused' || st === 'manual' || st === 'sticky') && !resp.value;
    if (frozen && currentPrinciple.value !== null) return;
    currentPrinciple.value = p;
  },
  { immediate: true },
);

const cursor = reactive({ visible: false, x: 0, y: 0, ring: -1 });
function center(sel: string, base: DOMRect) {
  const el = panels.value[1]?.querySelector<HTMLElement>(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: r.left + r.width / 2 - base.left - 6, y: r.top + r.height / 2 - base.top - 4 };
}
function updateCursor() {
  const ask = compiled.value[1]?.ask;
  const t = times[1]!;
  const show =
    !!ask?.option &&
    !!ask.submit &&
    index.value === 1 &&
    canAnimate.value &&
    !mobile.value &&
    autoplay.state.value === 'playing' &&
    store.askChoice.value === null &&
    t >= ask.option.at &&
    t < ask.submitted;
  if (!show || !ask?.option || !ask.submit || !bench.value) {
    cursor.visible = false;
    return;
  }
  const base = bench.value.getBoundingClientRect();
  const p0 = { x: base.width - 24, y: base.height - 24 };
  const p1 = center(ask.option.target, base) ?? p0;
  const p2 = center(ask.submit.target, base) ?? p1;
  const o = ask.option;
  const s = ask.submit;
  const lerp = (a: typeof p0, b: typeof p0, k: number) => ({ x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k });
  let p = p0;
  if (t < o.at + o.dur) p = lerp(p0, p1, easeInOut((t - o.at) / o.dur));
  else if (t < s.at) p = p1;
  else if (t < s.at + s.dur) p = lerp(p1, p2, easeInOut((t - s.at) / s.dur));
  else p = p2;
  const ringOf = (start: number) => (t >= start && t <= start + 0.36 ? (t - start) / 0.36 : -1);
  const r1 = ringOf(o.at + o.dur);
  cursor.ring = r1 >= 0 ? r1 : ringOf(s.at + s.dur);
  cursor.x = p.x;
  cursor.y = p.y;
  cursor.visible = true;
}
watch(() => times[1], updateCursor, { flush: 'post' });
watch(() => autoplay.state.value, updateCursor);

/* ---------- 出处弹层 ---------- */
const sourceOpen = ref(false);
const sourceTrigger = ref<HTMLElement | null>(null);
function openSource(trigger: HTMLElement) {
  // 先登记 dialog 原因再进入手动模式：useAutoplay 的 8 s 空闲计时只在登记时检查 dialog。
  autoplay.pause('dialog');
  interact();
  sourceTrigger.value = trigger;
  sourceOpen.value = true;
}
async function viewRows() {
  const i = SCENES.findIndex((s) => s.id === 'check');
  store.views.check = 'rows';
  store.flashRow.value += 1;
  await nextTick();
  const row = panels.value[i]?.querySelector<HTMLElement>('[data-row="0"]');
  row?.focus({ preventScroll: true });
}

/* ---------- 提问卡提交（手动） ---------- */
function submitAsk(choice: HitlState) {
  interact();
  const i = SCENES.findIndex((s) => s.id === 'review');
  store.decision.value = choice;
  store.askUserTs.value = utcSeconds();
  store.askChoice.value = null;
  const mark = compiled.value[i]!.ask?.submitted ?? 0;
  if (canAnimate.value || reducedMq.value) playResponse(i, mark);
  else times[i] = SCENES[i]!.end;
}

provide(DEMO_CONTEXT, {
  store,
  mobile,
  still,
  interact,
  openSource,
  openRows: () => interact(),
  submitAsk,
});

/* 用户一碰提问卡（选项）就冻结响应片段，等其提交。 */
watch(
  () => store.askChoice.value,
  (v) => {
    if (v !== null && resp.value?.scene === 1) stopResponse();
  },
);

/* ---------- 页签悬停底板（圆角浅蓝底，与顶栏同款，§2.5.4） ---------- */
useHoverIndicator({
  container: tabsEl,
  indicator,
  items: '.scenario-tab',
  active: () => tabsEl.value?.querySelector<HTMLElement>('[aria-selected="true"]') ?? null,
  driver: 'css',
});

/* ---------- 手机：轻点切换置顶暂停、横滑切换场景（§2.5.7） ---------- */
let touch: { x: number; y: number } | null = null;
function onTouchStart(e: TouchEvent) {
  const p = e.touches[0];
  touch = p ? { x: p.clientX, y: p.clientY } : null;
}
function onTouchEnd(e: TouchEvent) {
  if (!mobile.value || !touch) return;
  const p = e.changedTouches[0];
  if (!p) return;
  const dx = p.clientX - touch.x;
  const dy = p.clientY - touch.y;
  touch = null;
  if (Math.abs(dx) >= 48 && Math.abs(dx) > 1.5 * Math.abs(dy)) {
    const next = index.value + (dx < 0 ? 1 : -1);
    if (next >= 0 && next < SCENES.length) selectScene(next);
    return;
  }
  if (Math.abs(dx) < 12 && Math.abs(dy) < 12) {
    const target = e.target as Element | null;
    if (target?.closest('button, a, input, summary, [role="tab"], [tabindex], [data-room]')) interact();
    else toggle();
  }
}

/* ---------- “看它怎么工作”（§1.5） ---------- */
function visibleRatio(el: HTMLElement) {
  const r = el.getBoundingClientRect();
  const h = Math.max(0, Math.min(r.bottom, window.innerHeight) - Math.max(r.top, 0));
  const w = Math.max(0, Math.min(r.right, window.innerWidth) - Math.max(r.left, 0));
  return r.width && r.height ? (h * w) / (r.width * r.height) : 0;
}
function hint() {
  const el = bench.value;
  if (!el || typeof el.animate !== 'function' || reducedMq.value) return;
  el.animate(
    [{ boxShadow: '0 0 0 0 rgba(6,102,245,.35), var(--shadow-workbench)' }, { boxShadow: '0 0 0 6px rgba(6,102,245,0), var(--shadow-workbench)' }],
    { duration: 600, easing: CSS_EASE.out },
  );
}
async function watchDemo() {
  const root = stage.value;
  if (!root || !bench.value) return;
  if (still.value) {
    if (visibleRatio(bench.value) < 0.9) await scrollToSection('demo');
    else root.focus({ preventScroll: true });
    stopResponse();
    autoplay.goTo(0);
    times[0] = SCENES[0]!.end;
    return;
  }
  if (split.value && visibleRatio(bench.value) >= 0.9) {
    restart();
    hint();
    root.focus({ preventScroll: true });
    autoplay.resume('focus');
  } else {
    // 滚动结束前不推进：先进入手动模式，滚完再从场景 1 的 0 s 播放。
    autoplay.pause('user');
    await scrollToSection('demo');
    restart();
  }
  announce('正在播放：计价表核对');
}

/* ---------- 对外接口（§2.5.6） ---------- */
async function showScene(id: SceneId, opts?: { source?: boolean } | boolean, _trigger?: HTMLElement | null) {
  const i = SCENES.findIndex((s) => s.id === id);
  if (i < 0) return;
  const source = typeof opts === 'boolean' ? opts : Boolean(opts?.source);
  if (source) {
    stopResponse();
    if (canAnimate.value) bound.value = true;
    autoplay.goTo(i, { user: true });
    times[i] = SCENES[i]!.end;
    manualTime.value = SCENES[i]!.end;
    store.views.check = null;
    await nextTick();
    const amount = panels.value[i]?.querySelector<HTMLElement>('[data-source-amount]');
    if (amount) openSource(amount);
    return;
  }
  selectScene(i, { announce: false });
  await nextTick();
}

const handle: DemoHandle = { restart, showScene, watch: watchDemo };

onMounted(async () => {
  shownIndex.value = autoplay.index.value;
  if (!gateOpen) autoplay.pause('hidden');
  demoHandle.value = handle;
  const motion = await loadMotion();
  if (!motion) {
    // 动效块加载失败：与减少动效相同（不自动播放），但页签切换可用、不显示“播放演示”（§2.8）。
    motionFailed.value = true;
    autoplay.pause('reduced');
    return;
  }
  motionReady.value = true;
  if (!reducedMq.value) openGate();
});
onBeforeUnmount(() => {
  stopResponse();
  if (demoHandle.value === handle) demoHandle.value = null;
  currentPrinciple.value = null;
});

defineExpose({ restart, showScene, currentPrinciple });

/* ---------- 文案 ---------- */
const toggleText = computed(() => {
  const st = autoplay.state.value;
  if (reducedMq.value) return { label: '播放演示', aria: '播放演示', icon: 'play' };
  if (st === 'done') return { label: '再看一遍', aria: '再看一遍', icon: 'replay' };
  if (st === 'sticky') return { label: '播放', aria: '播放演示', icon: 'play' };
  return { label: '暂停', aria: '暂停演示', icon: 'pause' };
});
const footerShown = computed(() => times[index.value]! >= (compiled.value[index.value]!.files?.at ?? 0));
</script>

<template>
  <div
    id="demo"
    ref="stage"
    class="demo-stage"
    role="region"
    aria-roledescription="轮播"
    aria-label="工作示例"
    tabindex="-1"
    data-deco-avoid
  >
    <p class="stage-caption">
      <span class="stage-caption-main"><i class="status-dot" aria-hidden="true"></i>从一句话，到一份有出处的结果</span>
    </p>
    <div
      ref="bench"
      class="workbench"
      :data-state="autoplay.state.value"
      :data-layout="split ? 'split' : 'stack'"
      :data-running="running ? 'true' : 'false'"
      :data-motion="still ? 'reduced' : 'full'"
      @touchstart.passive="onTouchStart"
      @touchend="onTouchEnd"
    >
      <header class="workbench-titlebar">
        <span class="titlebar-dots" aria-hidden="true"><i></i><i></i><i></i></span>
        <span class="titlebar-project">2026-007-某综合办公楼</span>
        <span class="titlebar-tag">示例项目</span>
      </header>
      <div ref="tabsEl" class="scenario-tabs" role="tablist" aria-label="工作示例场景" @keydown="onTabKeydown">
        <span ref="indicator" class="scenario-indicator" aria-hidden="true"></span>
        <button
          v-for="(s, i) in SCENES"
          :id="`tab-${s.id}`"
          :key="s.id"
          v-magnetic="'link'"
          type="button"
          role="tab"
          class="scenario-tab"
          :aria-selected="index === i"
          :aria-controls="`scene-${s.id}`"
          :tabindex="index === i ? 0 : -1"
          @click="selectScene(i)"
        >
          <span data-magnetic-label class="scenario-tab-label"><AppIcon :name="s.icon" />{{ s.tab }}</span>
          <span class="tab-progress" aria-hidden="true"><i :style="{ transform: `scaleX(${tabProgress[i]})` }"></i></span>
        </button>
      </div>
      <button
        v-if="!motionFailed"
        type="button"
        class="demo-toggle"
        :aria-label="toggleText.aria"
        :data-icon="toggleText.icon"
        @click="toggle"
      >
        <AppIcon :name="toggleText.icon" /><span>{{ toggleText.label }}</span>
      </button>
      <div class="workbench-body">
        <section
          v-for="(s, i) in SCENES"
          :id="`scene-${s.id}`"
          :key="s.id"
          ref="panels"
          class="scene"
          :class="`scene-${s.id}`"
          role="tabpanel"
          :aria-labelledby="`tab-${s.id}`"
          :hidden="i !== index && i !== leaving"
          :style="{ '--t': times[i] }"
          :data-scene="s.id"
        >
          <DemoChat :compiled="compiled[i]!" :t="times[i]!" :follow="running && i === index" />
          <div class="scene-divider" aria-hidden="true"></div>
          <CheckPreview v-if="s.id === 'check'" :compiled="compiled[i]!" :t="times[i]!" />
          <ReviewPreview v-else-if="s.id === 'review'" :compiled="compiled[i]!" :t="times[i]!" />
          <CadPreview v-else :compiled="compiled[i]!" :t="times[i]!" />
          <DemoHotspot
            v-for="id in compiled[i]!.hotspots?.ids ?? []"
            :id="id"
            :key="id"
            :target="`[data-hotspot-target='${id}']`"
            :visible="hotspots[i]!.includes(id)"
            :pulse="hotspotPulse"
          />
        </section>
      </div>
      <footer class="workbench-footer">
        <span class="generated-file" :class="{ 'is-on': footerShown }" :title="current.footerFile.dir + current.footerFile.name">
          <AppIcon name="check" /><span class="generated-name">{{ current.footerFile.name }}</span
          ><span class="generated-state">{{ current.footerFile.state }}</span>
        </span>
        <button type="button" class="plain-button replay-button" aria-label="从头重播当前场景" @click="replay">
          <AppIcon name="replay" />重播
        </button>
      </footer>
      <DemoCursor :visible="cursor.visible" :x="cursor.x" :y="cursor.y" :ring="cursor.ring" />
    </div>
    <SourceDialog v-model="sourceOpen" :trigger="sourceTrigger" @rows="viewRows" />
  </div>
</template>
