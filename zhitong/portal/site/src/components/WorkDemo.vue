<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
import CheckScene from './demo/CheckScene.vue';
import ReviewScene from './demo/ReviewScene.vue';
import CadScene from './demo/CadScene.vue';
import SourceDialog from './SourceDialog.vue';
import { useDemoState } from '../composables/useDemoState';
import { useMediaQuery } from '../composables/useMediaQuery';
import { sceneTabs } from '../data/demo';
import { loadMotion, type Motion } from '../lib/motion';
import { onTabKeydown } from '../lib/navigation';
import type { SceneId } from '../types/portal';

const { scene, decision, room, roomLabel, totals, selectScene, decide, resetReview, selectRoom } =
  useDemoState();
const root = ref<HTMLElement | null>(null);
const bench = ref<HTMLElement | null>(null);
const connector = ref<SVGSVGElement | null>(null);
const sourceOpen = ref(false);
const sourceTrigger = ref<HTMLElement | null>(null);
const connectorPath = ref('');
const points = ref({ x1: 0, y1: 0, x2: 0, y2: 0 });
const connectorBox = ref('0 0 720 480');
const mobile = useMediaQuery('(max-width: 767px)');
const reduced = useMediaQuery('(prefers-reduced-motion: reduce)');
const status = ref('');
const filename = computed(() => sceneTabs.find((item) => item.id === scene.value)!.filename);
const footerState = computed(() =>
  scene.value === 'review' ? (decision.value ? '已记录' : '待复核') : '示例结果',
);
let motion: Motion | null = null;
let context: gsap.Context | undefined;
let timeline: gsap.core.Timeline | undefined;
let observer: IntersectionObserver | undefined;
let sourceElement: HTMLDialogElement | undefined;
let handled = false;
let mounted = false;
let frame = 0;

function settle() {
  timeline?.progress(1).kill();
  timeline = undefined;
  if (motion && root.value) {
    const nodes = root.value.querySelectorAll('.scene, .demo-part, .scene > *');
    motion.gsap.killTweensOf(nodes);
    motion.gsap.set(nodes, { clearProps: 'opacity,visibility,transform' });
  }
}

function interact() {
  handled = true;
  settle();
}

function animateScene() {
  if (!motion || reduced.value || !root.value) return;
  const panel = root.value.querySelector(`#scene-${scene.value}`);
  context?.add(() => {
    motion!.gsap.fromTo(
      panel,
      { autoAlpha: 0, y: 8 },
      {
        autoAlpha: 1,
        y: 0,
        duration: 0.2,
        ease: 'power2.out',
        clearProps: 'opacity,visibility,transform',
      },
    );
  });
}

async function chooseScene(id: SceneId) {
  interact();
  sourceOpen.value = false;
  selectScene(id);
  await nextTick();
  animateScene();
}

function openSource(trigger?: HTMLElement | null) {
  interact();
  sourceTrigger.value =
    trigger ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
  sourceOpen.value = true;
}

function sourceOpened(dialog: HTMLDialogElement) {
  sourceElement = dialog;
  placeSource();
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(() => {
    placeSource();
    if (mobile.value || reduced.value || !motion || !sourceOpen.value) return;
    const path = connector.value?.querySelector('path');
    if (!path) return;
    const length = path.getTotalLength();
    context?.add(() => {
      motion!.gsap.fromTo(
        path,
        { strokeDasharray: length, strokeDashoffset: length },
        {
          strokeDashoffset: 0,
          duration: 0.36,
          ease: 'power2.out',
          clearProps: 'strokeDasharray,strokeDashoffset',
        },
      );
    });
  });
}

function placeSource() {
  if (!sourceOpen.value || !sourceElement || !bench.value) return;
  if (mobile.value) {
    sourceElement.style.removeProperty('top');
    sourceElement.style.removeProperty('right');
    return;
  }
  const box = bench.value.getBoundingClientRect();
  const panelHeight = sourceElement.offsetHeight;
  sourceElement.style.top = `${Math.min(Math.max(90, box.top + 90), Math.max(16, window.innerHeight - panelHeight - 16))}px`;
  sourceElement.style.right = `${Math.max(16, window.innerWidth - box.right + 13)}px`;
  const panel = sourceElement.getBoundingClientRect();
  const amount = root.value!.querySelector('.amount-button')!.getBoundingClientRect();
  const x1 = amount.right - box.left + 4;
  const y1 = amount.top + amount.height / 2 - box.top;
  const x2 = panel.left - box.left;
  const y2 = panel.top + 45 - box.top;
  const middle = (x1 + x2) / 2;
  points.value = { x1, y1, x2, y2 };
  connectorBox.value = `0 0 ${box.width} ${box.height}`;
  connectorPath.value = `M${x1} ${y1} C${middle} ${y1} ${middle} ${y2} ${x2} ${y2}`;
}

function play() {
  settle();
  if (!motion || reduced.value || mobile.value || !root.value) {
    status.value = '已显示当前示例的完整结果。';
    return;
  }
  const panel = root.value.querySelector(`#scene-${scene.value}`)!;
  const parts = scene.value === 'check' ? panel.querySelectorAll('.demo-part') : panel.children;
  context?.add(() => {
    timeline = motion!.gsap.timeline({ defaults: { ease: 'power2.out' } });
    timeline.fromTo(
      parts,
      { autoAlpha: 0, y: 6 },
      {
        autoAlpha: 1,
        y: 0,
        duration: 0.36,
        stagger: { amount: 1.65 },
        clearProps: 'opacity,visibility,transform',
      },
    );
  });
}

function replay() {
  handled = true;
  sourceOpen.value = false;
  if (scene.value === 'review') resetReview();
  void nextTick(play);
}

async function showScene(id: SceneId, source = false, trigger?: HTMLElement | null) {
  await chooseScene(id);
  if (source) openSource(trigger);
}

function visibilityChanged() {
  if (document.hidden) settle();
}
watch([mobile, reduced], () => {
  settle();
  void nextTick(placeSource);
});
onMounted(async () => {
  mounted = true;
  window.addEventListener('resize', placeSource);
  document.addEventListener('visibilitychange', visibilityChanged);
  motion = await loadMotion();
  if (!mounted || !root.value) return;
  if (motion) context = motion.gsap.context(() => {}, root.value);
  if ('IntersectionObserver' in window) {
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && !handled) {
            handled = true;
            play();
          } else if (!entry.isIntersecting) settle();
        }
      },
      { threshold: 0.35 },
    );
    if (bench.value) observer.observe(bench.value);
  }
});
onBeforeUnmount(() => {
  mounted = false;
  settle();
  context?.revert();
  observer?.disconnect();
  cancelAnimationFrame(frame);
  window.removeEventListener('resize', placeSource);
  document.removeEventListener('visibilitychange', visibilityChanged);
});
defineExpose({ showScene, settle: interact });
</script>

<template>
  <div id="demo" ref="root" class="demo-stage" tabindex="-1" aria-label="可交互工作示例">
    <div class="stage-capsule capsule-one" aria-hidden="true"></div>
    <div class="stage-capsule capsule-two" aria-hidden="true"></div>
    <div class="stage-caption">
      <span><span class="status-dot"></span>从一句话，到一份有出处的结果</span
      ><span class="sample-label">交互示意 · 示例数据</span>
    </div>
    <div ref="bench" class="workbench" @pointerdown.capture="interact" @keydown.capture="interact">
      <div class="workbench-titlebar">
        <span class="project-title"><AppIcon name="cube" />示例项目 · 综合办公楼</span
        ><span class="window-dots" aria-hidden="true"><i></i><i></i><i></i></span>
      </div>
      <div class="scenario-tabs" role="tablist" aria-label="工作示例" @keydown="onTabKeydown">
        <button
          v-for="tab in sceneTabs"
          :id="`tab-${tab.id}`"
          :key="tab.id"
          class="scenario-tab"
          role="tab"
          :aria-controls="`scene-${tab.id}`"
          :aria-selected="scene === tab.id"
          :tabindex="scene === tab.id ? 0 : -1"
          :data-scene="tab.id"
          @click="chooseScene(tab.id)"
        >
          <AppIcon :name="tab.icon" />{{ tab.label }}
        </button>
      </div>
      <div class="workbench-body">
        <aside class="project-tree" aria-label="示例项目目录">
          <span class="tree-heading">项目文件</span>
          <div class="tree-folder is-active"><AppIcon name="folder" />资料</div>
          <div class="tree-file"><span class="file-dot"></span>送审计价表</div>
          <div class="tree-file"><span class="file-dot"></span>审定计价表</div>
          <div class="tree-file"><span class="file-dot"></span>设计图纸</div>
          <div class="tree-folder"><AppIcon name="folder" />工作</div>
          <div class="tree-folder"><AppIcon name="folder" />成果</div>
          <div class="tree-bottom"><AppIcon name="cloud" />公司 TOS</div>
        </aside>
        <div class="scene-stack">
          <CheckScene
            :hidden="scene !== 'check'"
            :totals="totals"
            @source="openSource($event.currentTarget as HTMLElement)"
          />
          <ReviewScene
            :hidden="scene !== 'review'"
            :decision="decision"
            @decide="decide"
            @reset="resetReview"
          />
          <CadScene
            :hidden="scene !== 'cad'"
            :room="room"
            :room-label="roomLabel"
            @select="selectRoom"
          />
        </div>
      </div>
      <div class="workbench-footer">
        <span class="generated-file"
          ><AppIcon name="check" /><span id="generated-filename">{{ filename }}</span
          ><span class="footer-state">{{ footerState }}</span></span
        ><button class="plain-button replay-button" @click="replay">
          <AppIcon name="replay" />重新播放
        </button>
      </div>
      <svg
        v-show="sourceOpen && !mobile"
        ref="connector"
        class="source-connector"
        :viewBox="connectorBox"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path :d="connectorPath" />
        <circle :cx="points.x1" :cy="points.y1" r="4" />
        <circle :cx="points.x2" :cy="points.y2" r="4" />
      </svg>
    </div>
    <div class="demo-footnote">
      <AppIcon name="link" /><span>点结果，见出处。</span
      ><span class="demo-footnote-secondary">每一次判断，都有回查的起点。</span>
    </div>
    <SourceDialog
      v-model="sourceOpen"
      :totals="totals"
      :trigger="sourceTrigger"
      @opened="sourceOpened"
      @closed="sourceElement = undefined"
    />
    <div class="sr-only" role="status" aria-live="polite">{{ status }}</div>
  </div>
</template>
