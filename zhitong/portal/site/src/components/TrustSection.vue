<script setup lang="ts">
/**
 * 数据与复核 `#trust`（05 章 §2）：标题、数据流图（宽窄两套，CSS 按断点显示其一）、图例、模型说明、四条原则、六个节点说明卡。
 * 持有聚焦键 `focus`：原则卡与图例的悬停 / 聚焦 / 触屏点按，以及说明卡打开时设置。
 * 动效：图可见 ≥ 35% 时首次入场，0.4 s 后开始循环；离开视口或页面隐藏时暂停（useInView）；只为当前显示的几何建时间线。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';
import AppIcon from './AppIcon.vue';
import ZtPopover from './ui/ZtPopover.vue';
import TrustFlow from './sections05/trust/TrustFlow.vue';
import {
  NARROW,
  NODE_FOCUS,
  WIDE,
  type FocusKey,
  type TrustNodeId,
} from './sections05/trust/trust-geometry';
import { buildTrustTimelines, type TrustTimelines } from './sections05/trust/trust-timeline';
import {
  splitTicks,
  TRUST_COPY,
  TRUST_FLOWS,
  TRUST_NODES,
  TRUST_PRINCIPLES,
} from '../data/trust';
import { useInView } from '../composables/useInView';
import { loadMotion, prefersReducedMotion, type Motion } from '../lib/motion';

const figure = ref<HTMLElement | null>(null);
const wide = ref<InstanceType<typeof TrustFlow> | null>(null);
const narrow = ref<InstanceType<typeof TrustFlow> | null>(null);
const focus = ref<FocusKey | null>(null);
/** 由触屏点按（或键盘按下）设置、需要再次点按或点别处清空的键。 */
const pinnedKey = ref<FocusKey | null>(null);
const fine = ref(false);
const descId = 'trust-wide-desc';
let lastPointer = '';
let motion: Motion | null = null;
let ctx: gsap.Context | null = null;
let timelines: TrustTimelines | null = null;
let entered = false;
let startTimer: ReturnType<typeof setTimeout> | undefined;
let media: MediaQueryList | undefined;
let alive = false;

const view = useInView(figure, {
  threshold: 0.35,
  play: () => play(),
  pause: () => pause(),
});

const anyFocus = computed(() => focus.value);

function play() {
  if (!timelines) return;
  if (!entered) {
    entered = true;
    timelines.entrance.play(0);
    clearTimeout(startTimer);
    startTimer = setTimeout(
      () => {
        if (view.active.value) timelines?.flow.play();
      },
      (timelines.entrance.duration() + 0.4) * 1000,
    );
  } else timelines.flow.play();
}
function pause() {
  clearTimeout(startTimer);
  timelines?.flow.pause();
}

function build() {
  ctx?.revert();
  ctx = null;
  timelines = null;
  if (!motion || prefersReducedMotion()) return;
  const isWide = media?.matches ?? true;
  const svg = (isWide ? wide.value : narrow.value)?.svg;
  if (!svg) return;
  const m = motion;
  ctx = m.gsap.context(() => {
    timelines = buildTrustTimelines(m, svg);
  });
  if (entered) {
    timelines!.entrance.progress(1);
    if (view.active.value) timelines!.flow.play();
  } else if (view.active.value) play();
}

function onPointerDown(e: PointerEvent) {
  lastPointer = e.pointerType;
}
function enter(key: FocusKey, e: PointerEvent) {
  if (e.pointerType !== 'mouse' && e.pointerType !== 'pen') return;
  focus.value = key;
}
function leave(e: PointerEvent) {
  if (e.pointerType !== 'mouse' && e.pointerType !== 'pen') return;
  focus.value = pinnedKey.value;
}
function onFocusIn(key: FocusKey) {
  if (lastPointer === 'touch') return;
  focus.value = key;
}
function onFocusOut() {
  focus.value = pinnedKey.value;
}
/** 触屏：点卡切换；鼠标点击不改变（悬停已高亮）；键盘 Enter / Space 切换。 */
function onClick(key: FocusKey, e: MouseEvent) {
  const viaPointer = e.detail > 0;
  if (viaPointer && (lastPointer === 'mouse' || lastPointer === 'pen')) return;
  pinnedKey.value = pinnedKey.value === key ? null : key;
  focus.value = pinnedKey.value;
  lastPointer = '';
}
function onDocPointer(e: PointerEvent) {
  if (!pinnedKey.value) return;
  const t = e.target as Element | null;
  if (t?.closest('.trust-principle')) return;
  pinnedKey.value = null;
  focus.value = null;
}
const pressed = (key: FocusKey) => focus.value === key;

function onPopoverOpen(n: TrustNodeId) {
  focus.value = NODE_FOCUS[n];
}
function onPopoverClose() {
  focus.value = pinnedKey.value;
}

const onMedia = () => build();

onMounted(async () => {
  alive = true;
  fine.value = window.matchMedia?.('(hover: hover) and (pointer: fine)').matches ?? false;
  document.addEventListener('pointerdown', onDocPointer);
  media = window.matchMedia?.('(min-width: 1024px)');
  media?.addEventListener?.('change', onMedia);
  const m = await loadMotion();
  if (!alive || !m) return;
  motion = m;
  build();
});
onBeforeUnmount(() => {
  alive = false;
  clearTimeout(startTimer);
  document.removeEventListener('pointerdown', onDocPointer);
  media?.removeEventListener?.('change', onMedia);
  ctx?.revert();
});
</script>

<template>
  <section id="trust" class="trust-section section-space" aria-labelledby="trust-title">
    <div class="container">
      <div class="section-heading trust-heading">
        <p class="eyebrow">{{ TRUST_COPY.eyebrow }}</p>
        <h2 id="trust-title" tabindex="-1" data-reveal="heading">{{ TRUST_COPY.title }}</h2>
        <p data-reveal="block">{{ TRUST_COPY.lead }}</p>
      </div>

      <figure ref="figure" class="trust-figure" :data-focus="anyFocus ?? undefined">
        <div class="trust-diagram">
          <TrustFlow ref="wide" :geometry="WIDE" :focus="focus" />
          <TrustFlow ref="narrow" :geometry="NARROW" :focus="focus" />
        </div>
        <ol class="sr-only">
          <li v-for="flow in TRUST_FLOWS" :key="flow">{{ flow }}</li>
        </ol>
      </figure>

      <ul class="trust-principles" data-reveal="stagger">
        <li v-for="p in TRUST_PRINCIPLES" :key="p.key">
          <button
            v-spotlight
            type="button"
            class="trust-principle zt-card"
            :aria-pressed="pressed(p.key)"
            :aria-describedby="descId"
            @pointerdown="onPointerDown"
            @pointerenter="enter(p.key, $event)"
            @pointerleave="leave"
            @focusin="onFocusIn(p.key)"
            @focusout="onFocusOut"
            @click="onClick(p.key, $event)"
          >
            <span class="trust-principle-no mono">{{ p.no }}</span>
            <span class="trust-principle-title">{{ p.title }}</span>
            <span class="trust-principle-body">{{ p.body }}</span>
            <span v-if="fine" class="trust-principle-hint">{{ TRUST_COPY.hoverHint }}</span>
          </button>
        </li>
      </ul>
    </div>

    <ZtPopover
      v-for="card in TRUST_NODES"
      :id="`trust-pop-${card.node}`"
      :key="card.node"
      :title="card.title"
      @open="onPopoverOpen(card.node)"
      @close="onPopoverClose"
    >
      <p class="zt-popover-lead" data-popover-row>{{ card.lead }}</p>
      <dl class="zt-popover-rows">
        <div v-for="row in card.rows" :key="row.label" data-popover-row>
          <dt>{{ row.label }}</dt>
          <dd>
            <template v-for="(part, k) in splitTicks(row.text)" :key="k"
              ><code v-if="part.mono" class="mono">{{ part.t }}</code
              ><template v-else>{{ part.t }}</template></template
            >
          </dd>
        </div>
      </dl>
      <template #actions="{ hide }">
        <RouterLink class="text-link" :to="TRUST_COPY.docHref" @click="hide({ returnFocus: false })"
          >{{ TRUST_COPY.readDoc }}<AppIcon name="arrow" class="icon"
        /></RouterLink>
      </template>
    </ZtPopover>
  </section>
</template>
