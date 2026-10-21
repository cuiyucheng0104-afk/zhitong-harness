<script setup lang="ts">
/**
 * 首页（00 章 §3.2 章节顺序与锚点）。由原 App.vue 的页面部分迁入。
 * - 挂载后懒加载动效块：创建 Lenis（00 章 §5.3）、入场（useReveal）、导航四章的 ScrollTrigger 章节跟踪（01 章 §3）；
 *   动效加载失败时章节跟踪退回 IntersectionObserver（`rootMargin: '-40% 0px -60% 0px'`）。
 * - 卸载时 revert 自己的 gsap.context 并销毁 Lenis（01 章 §13）。
 * - 各章的跨区动作（看示例、打开能力、跳章节）在这里汇总。
 */
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import HeroSection from '../components/HeroSection.vue';
import WorkDemo from '../components/WorkDemo.vue';
import PrinciplesStrip from '../components/PrinciplesStrip.vue';
import RolesSection from '../components/RolesSection.vue';
import ProblemSection from '../components/ProblemSection.vue';
import CapabilitiesSection from '../components/CapabilitiesSection.vue';
import WorkflowSection from '../components/WorkflowSection.vue';
import { LazyFaqSection as FaqSection, LazyInstallSection as InstallSection, LazyTrustSection as TrustSection } from './home-sections';
import SiteFooter from '../components/SiteFooter.vue';
import DecoDimension from '../components/deco/DecoDimension.vue';
import { openAcquire } from '../composables/useAcquire';
import { announce } from '../composables/useToast';
import { useReveal } from '../composables/useReveal';
import { goToSection, homeReady, NAV_IDS, navSpy } from '../lib/home-state';
import { loadMotion, refreshMotionLayout } from '../lib/motion';
import { createSmoothScroll, destroySmoothScroll, scrollToSection } from '../lib/smooth-scroll';
import type { PortalAction, SceneId } from '../types/portal';

const root = ref<HTMLElement | null>(null);
const demo = ref<InstanceType<typeof WorkDemo> | null>(null);
const capabilities = ref<InstanceType<typeof CapabilitiesSection> | null>(null);
let ctx: gsap.Context | undefined;
let observer: IntersectionObserver | undefined;
let alive = false;

useReveal(root);

function acquire(event: MouseEvent) {
  openAcquire(event);
}

/** 跳到首页内的章节或元素。 */
function navigate(id: string) {
  void goToSection(id);
}

/**
 * 看某个场景的示例（04 章 AC-04-21；02 章 showScene）：切到该场景（轮播暂停原因含 user），
 * 滚到 #demo，焦点移到该场景页签（不再滚动）。`source` 为真时同时打开该场景的出处弹层。
 */
async function showScene(id: SceneId, source = false) {
  await demo.value?.showScene(id);
  await scrollToSection('demo', false, source);
  document.getElementById(`tab-${id}`)?.focus({ preventScroll: true });
  if (source) await demo.value?.showScene(id, { source: true });
}

async function act(action: PortalAction) {
  if (action.type === 'feature') {
    await capabilities.value?.selectFeature(action.id, { focus: false });
    await nextTick();
    const target = window.matchMedia('(max-width: 767px)').matches
      ? `feature-${action.id}-title`
      : 'capabilities-title';
    void scrollToSection(target, false);
    document.getElementById(`feature-${action.id}-title`)?.focus({ preventScroll: true });
    const name = document.querySelector(`[data-feature="${action.id}"] summary span`)?.textContent ?? '';
    announce(`已打开：${name}`);
    refreshMotionLayout();
  } else if (action.type === 'scene') await showScene(action.id);
  else if (action.type === 'source') await showScene('check', true);
  else navigate(action.id);
}

function fallbackSpy() {
  if (typeof IntersectionObserver === 'undefined') return;
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) navSpy.toggle(entry.target.id as (typeof NAV_IDS)[number], entry.isIntersecting);
    },
    { rootMargin: '-40% 0px -60% 0px', threshold: 0 },
  );
  for (const id of NAV_IDS) {
    const section = document.getElementById(id);
    if (section) observer.observe(section);
  }
}

onMounted(async () => {
  alive = true;
  const hash = decodeURIComponent(window.location.hash.slice(1));
  // #feature-* 由能力区自行处理（选中 → 定位 → 聚焦标题，04 章），这里跳过以免二次滚动。
  if (hash && !hash.startsWith('feature-') && document.getElementById(hash)) void nextTick(() => navigate(hash));
  const motion = await loadMotion();
  if (!alive) return;
  if (!motion) {
    fallbackSpy();
    homeReady.value = true;
    return;
  }
  createSmoothScroll(motion);
  ctx = motion.gsap.context(() => {
    for (const id of NAV_IDS) {
      if (!document.getElementById(id)) continue;
      motion.ScrollTrigger.create({
        trigger: `#${id}`,
        start: 'top 40%',
        end: 'bottom 40%',
        refreshPriority: -1,
        onToggle: (self) => navSpy.toggle(id, self.isActive),
        onRefresh: (self) => {
          if (self.isActive) navSpy.toggle(id, true);
        },
      });
    }
  }, root.value ?? undefined);
  homeReady.value = true;
  void document.fonts?.ready.then(() => {
    if (alive) refreshMotionLayout();
  });
});

onBeforeUnmount(() => {
  alive = false;
  homeReady.value = false;
  for (const id of NAV_IDS) navSpy.toggle(id, false);
  observer?.disconnect();
  ctx?.revert();
  destroySmoothScroll();
});
</script>

<template>
  <div ref="root" class="page-home">
    <main id="main" tabindex="-1">
      <HeroSection @acquire="acquire"><WorkDemo ref="demo" /></HeroSection>
      <PrinciplesStrip />
      <RolesSection @action="act" />
      <!-- 07 章 D4：只放在同底色接缝（#roles→#problem、#install→#faq；#workflow→#trust 底色不同，不放）。 -->
      <DecoDimension from="3" to="4" />
      <ProblemSection />
      <CapabilitiesSection ref="capabilities" @scene="showScene" />
      <WorkflowSection />
      <TrustSection />
      <InstallSection @acquire="acquire" />
      <DecoDimension from="8" to="9" />
      <FaqSection />
    </main>
    <SiteFooter @acquire="acquire" @navigate="navigate" />
  </div>
</template>
