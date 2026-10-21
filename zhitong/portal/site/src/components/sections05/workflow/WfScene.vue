<script setup lang="ts">
/**
 * 使用流程的场景窗口（05 章 §1.3–§1.5）：标题栏、示例会话、不可输入的输入条。
 *
 * - 每个场景一条暂停的 GSAP 时间线，由一个 `useAutoplay` 实例按帧定位；`hold: Infinity`，播完停在终态。
 * - 暂停原因：`offscreen`（钉住模式下不是当前步骤或钉住框不在视口；纵向模式下窗口可见 < 35%）、
 *   `hover`（离开 600 ms 后继续）、`focus`（焦点在窗口按钮上）、`hidden`、`dialog`、`user`（暂停/播放按钮，置顶）。
 * - 只有时间线建好后才渲染“暂停示例 / 播放示例”与“重播”按钮；减少动效与动效未加载时显示终态、不渲染按钮。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AppIcon from '../../AppIcon.vue';
import WfSceneBody from './WfSceneBody.vue';
import { isKeyboardFocus, useAutoplay } from '../../../composables/useAutoplay';
import { useInView } from '../../../composables/useInView';
import { getMotion, prefersReducedMotion } from '../../../lib/motion';
import { WORKFLOW_COPY, type WorkflowStep } from '../../../data/workflow';
import { buildSceneTimeline } from './scene-timeline';
import { planScene } from './scene-plan';
import brandMark from '../../../../assets/brand-mark.svg';

const props = withDefaults(
  defineProps<{
    step: WorkflowStep;
    index: number;
    mode: 'pinned' | 'stacked';
    /** 动效块已加载且未减少动效（由 WorkflowSection 判定）。 */
    animate: boolean;
    /** 钉住模式：本步是当前步骤。 */
    current?: boolean;
    /** 钉住模式：钉住框在视口内。 */
    sectionActive?: boolean;
  }>(),
  { current: false, sectionActive: false },
);

const root = ref<HTMLElement | null>(null);
const stage = ref<HTMLElement | null>(null);
const duration = ref(planScene(props.step.scene).total);
const ready = ref(false);
let ctx: gsap.Context | null = null;

const autoplay = useAutoplay({
  scenes: computed(() => [{ duration: duration.value, hold: Infinity }]),
  hoverTarget: root,
  autostart: true,
});
// 第一次成为当前步骤（或进入视口）之前不推进（AC-05-06）。
autoplay.pause('offscreen');

const windowInView = useInView(root, { threshold: 0.35 });
const allowed = computed(() =>
  props.mode === 'pinned' ? props.current && props.sectionActive : windowInView.active.value,
);
watch(allowed, (ok) => (ok ? autoplay.resume('offscreen') : autoplay.pause('offscreen')), {
  immediate: false,
});

const finished = computed(() => autoplay.progress.value >= 1);
const userPaused = computed(() => autoplay.state.value === 'sticky');
const toggleText = computed(() => (userPaused.value ? WORKFLOW_COPY.play : WORKFLOW_COPY.pause));
const elapsed = computed(() => (ready.value ? autoplay.elapsed.value : null));
const n = computed(() => props.index + 1);

function teardown() {
  ctx?.revert();
  ctx = null;
  autoplay.setTimeline(null);
}

function build() {
  teardown();
  const motion = getMotion();
  if (!props.animate || !motion || !stage.value || prefersReducedMotion()) {
    ready.value = false;
    return;
  }
  ctx = motion.gsap.context(() => {
    const tl = buildSceneTimeline(motion, stage.value!, props.step.scene, {
      pinned: props.mode === 'pinned',
    });
    duration.value = tl.duration();
    autoplay.setTimeline(tl);
  });
  ready.value = true;
  if (allowed.value) autoplay.resume('offscreen');
}

function onToggle() {
  if (finished.value) return;
  autoplay.toggle();
}
function onReplay() {
  autoplay.restart();
}
function onFocusIn(e: FocusEvent) {
  // 只有键盘聚焦才暂停；鼠标点“播放 / 重播”不应因按钮获得焦点而停住（与首屏示例同规则）。
  if (isKeyboardFocus(e.target)) autoplay.pause('focus');
  else autoplay.resume('focus');
}
function onFocusOut(e: FocusEvent) {
  const next = e.relatedTarget as Node | null;
  if (!next || !root.value?.contains(next)) autoplay.resume('focus');
}

let resizeTimer: ReturnType<typeof setTimeout> | undefined;
const onResize = () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (ready.value && props.mode === 'pinned') build();
  }, 200);
};

watch(
  () => [props.mode, props.animate] as const,
  () => build(),
  { flush: 'post' },
);

onMounted(() => {
  window.addEventListener('resize', onResize, { passive: true });
  if (props.animate) build();
});
onBeforeUnmount(() => {
  clearTimeout(resizeTimer);
  window.removeEventListener('resize', onResize);
  teardown();
});

defineExpose({ autoplay, ready });
</script>

<template>
  <div
    ref="root"
    class="wf-window"
    role="group"
    aria-roledescription="示例"
    :aria-label="WORKFLOW_COPY.sceneLabel(n, step.title)"
    :data-state="ready ? autoplay.state.value : 'static'"
    @focusin="onFocusIn"
    @focusout="onFocusOut"
  >
    <div class="wf-titlebar">
      <span class="wf-titlebar-brand"
        ><img :src="brandMark" alt="" width="16" height="16" /><span>{{
          WORKFLOW_COPY.windowTitle
        }}</span></span
      >
      <span class="wf-badge">{{ WORKFLOW_COPY.badge }}</span>
      <span class="wf-controls">
        <template v-if="ready">
          <button
            type="button"
            class="icon-button wf-control"
            :aria-label="toggleText"
            :disabled="finished"
            @click="onToggle"
          >
            <AppIcon :name="userPaused ? 'play' : 'pause'" /><span class="wf-control-text">{{
              toggleText
            }}</span>
          </button>
          <button
            type="button"
            class="icon-button wf-control"
            :aria-label="WORKFLOW_COPY.replay(n)"
            @click="onReplay"
          >
            <AppIcon name="replay" />
          </button>
        </template>
      </span>
    </div>
    <div ref="stage" class="wf-stage-wrap">
      <WfSceneBody :step="step" :elapsed="elapsed" />
    </div>
    <div class="wf-input" aria-hidden="true">
      <span>{{ step.placeholder }}</span>
    </div>
  </div>
</template>
