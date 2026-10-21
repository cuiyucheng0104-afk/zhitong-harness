<script setup lang="ts">
/**
 * 使用流程 `#workflow`（05 章 §1）。
 * 默认（预渲染、无 JS、减少动效、动效未加载、平板与手机、矮视口）为纵向时间线、场景终态；
 * 钉住条件满足时 `useWorkflowPin` 给 `#workflow` 加 `.wf--pinned`，切到横向轨道并随滚动推进。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import WfPanel from './sections05/workflow/WfPanel.vue';
import WfScene from './sections05/workflow/WfScene.vue';
import AppIcon from './AppIcon.vue';
import { useWorkflowPin } from './sections05/workflow/useWorkflowPin';
import { useInView } from '../composables/useInView';
import { loadMotion, prefersReducedMotion } from '../lib/motion';
import { WORKFLOW_COPY, WORKFLOW_STEPS } from '../data/workflow';

const section = ref<HTMLElement | null>(null);
const pin = ref<HTMLElement | null>(null);
const track = ref<HTMLElement | null>(null);
const rail = ref<HTMLElement | null>(null);
const stepper = ref<HTMLElement | null>(null);
const progress = ref<SVGPathElement | null>(null);
const baseline = ref<SVGPathElement | null>(null);

const mode = ref<'pinned' | 'stacked'>('stacked');
const animate = ref(false);
const active = ref(0);
const passed = ref(0);
const pinView = useInView(pin, { threshold: 0.35 });
const sectionActive = computed(() => pinView.active.value);
let pinApi: ReturnType<typeof useWorkflowPin> | null = null;
let alive = false;

const markerState = (i: number) =>
  i < active.value ? 'passed' : i === active.value ? 'current' : 'upcoming';
const nodeState = (i: number) => (i < passed.value ? 'passed' : 'upcoming');

function goStep(i: number) {
  pinApi?.scrollToStep(i);
}
function onPanelFocus(i: number) {
  if (mode.value === 'pinned' && i !== active.value) pinApi?.scrollToStep(i, 0.6);
}

onMounted(async () => {
  alive = true;
  const motion = await loadMotion();
  if (!alive || !motion || prefersReducedMotion() || !section.value || !pin.value || !track.value)
    return;
  animate.value = true;
  pinApi = useWorkflowPin(
    motion,
    {
      section: section.value,
      pin: pin.value,
      track: track.value,
      panels: [...track.value.querySelectorAll<HTMLElement>(':scope > .wf-panel')],
      progress: progress.value,
      baseline: baseline.value,
      stepper: stepper.value,
      list: track.value,
      rail: rail.value,
      nodes: [...track.value.querySelectorAll<HTMLElement>('.wf-node')],
    },
    {
      setMode: (m) => (mode.value = m),
      setActive: (i) => (active.value = i),
      setPassed: (c) => (passed.value = c),
    },
  );
});

onBeforeUnmount(() => {
  alive = false;
  pinApi?.destroy();
  pinApi = null;
});
</script>

<template>
  <section
    id="workflow"
    ref="section"
    class="workflow-section section-space"
    aria-labelledby="workflow-title"
  >
    <div class="container">
      <div class="section-heading wf-heading">
        <p class="eyebrow">{{ WORKFLOW_COPY.eyebrow }}</p>
        <h2 id="workflow-title" tabindex="-1" data-reveal="heading">{{ WORKFLOW_COPY.title }}</h2>
        <p data-reveal="block">{{ WORKFLOW_COPY.lead }}</p>
      </div>
    </div>
    <div ref="pin" class="wf-pin">
      <div class="container wf-pin-inner">
        <div ref="stepper" class="wf-stepper">
          <svg
            class="wf-dimline"
            viewBox="0 0 1000 16"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <path ref="baseline" class="wf-dimline-base" d="M125 8 H875" />
            <path
              v-for="x in [125, 375, 625, 875]"
              :key="x"
              class="wf-dimline-tick"
              :d="`M${x} 4 V12`"
            />
            <path ref="progress" class="wf-dimline-progress" d="M125 8 H875" />
          </svg>
          <ol class="wf-markers" :aria-label="WORKFLOW_COPY.stepsLabel">
            <li v-for="(step, i) in WORKFLOW_STEPS" :key="step.id" :data-state="markerState(i)">
              <button
                v-magnetic
                type="button"
                class="wf-marker"
                :aria-label="WORKFLOW_COPY.markerLabel(i + 1, step.title)"
                :aria-current="i === active ? 'step' : undefined"
                @click="goStep(i)"
              >
                <span class="wf-marker-dot mono" data-magnetic-label
                  ><span class="wf-marker-num">{{ i + 1 }}</span
                  ><AppIcon name="check" class="wf-marker-check"
                /></span>
                <span class="wf-marker-title">{{ step.title }}</span>
              </button>
            </li>
          </ol>
        </div>
        <div class="wf-viewport">
          <span class="wf-rail" aria-hidden="true"
            ><span ref="rail" class="wf-rail-progress"></span
          ></span>
          <ol ref="track" class="wf-steps">
            <li
              v-for="(step, i) in WORKFLOW_STEPS"
              :key="step.id"
              class="wf-panel"
              :data-step="step.id"
              @focusin="onPanelFocus(i)"
            >
              <span class="wf-node mono" :data-state="nodeState(i)" aria-hidden="true"
                ><span class="wf-node-num">{{ i + 1 }}</span
                ><AppIcon name="check" class="wf-node-check"
              /></span>
              <WfPanel :step="step" />
              <WfScene
                :step="step"
                :index="i"
                :mode="mode"
                :animate="animate"
                :current="i === active"
                :section-active="sectionActive"
              />
            </li>
          </ol>
        </div>
      </div>
    </div>
  </section>
</template>
