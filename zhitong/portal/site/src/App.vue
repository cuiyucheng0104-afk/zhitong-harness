<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import SiteHeader from './components/SiteHeader.vue';
import HeroSection from './components/HeroSection.vue';
import WorkDemo from './components/WorkDemo.vue';
import RolesSection from './components/RolesSection.vue';
import CapabilitiesSection from './components/CapabilitiesSection.vue';
import WorkflowSection from './components/WorkflowSection.vue';
import TrustSection from './components/TrustSection.vue';
import InstallSection from './components/InstallSection.vue';
import FaqSection from './components/FaqSection.vue';
import SiteFooter from './components/SiteFooter.vue';
import AcquireDialog from './components/AcquireDialog.vue';
import { scrollToSection } from './lib/navigation';
import { refreshMotionLayout } from './lib/motion';
import { usePageMotion } from './composables/usePageMotion';
import type { PortalAction, SceneId } from './types/portal';

const root = ref<HTMLElement | null>(null);
const demo = ref<InstanceType<typeof WorkDemo> | null>(null);
const capabilities = ref<InstanceType<typeof CapabilitiesSection> | null>(null);
const activeSection = ref('');
const acquireOpen = ref(false);
const acquireTrigger = ref<HTMLElement | null>(null);
const status = ref('');
let observer: IntersectionObserver | undefined;
usePageMotion(root);

function acquire(event: MouseEvent) {
  acquireTrigger.value = event.currentTarget as HTMLElement;
  acquireOpen.value = true;
}

function navigate(id: string) {
  if (id === 'demo') demo.value?.settle();
  const node = document.getElementById(id);
  const title = id === 'main' || id === 'demo' ? null : node?.querySelector<HTMLElement>('h2');
  scrollToSection(title?.id || id);
  if (['capabilities', 'workflow', 'trust', 'faq'].includes(id)) activeSection.value = id;
}

async function showScene(id: SceneId, source = false) {
  const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  await demo.value?.showScene(id);
  scrollToSection('demo', true, source);
  if (source) await demo.value?.showScene(id, true, trigger);
}

async function act(action: PortalAction) {
  if (action.type === 'feature') {
    await capabilities.value?.selectFeature(action.id);
    await nextTick();
    const target = window.matchMedia('(max-width: 767px)').matches
      ? `feature-${action.id}-title`
      : 'capabilities-title';
    scrollToSection(target, false);
    document.getElementById(`feature-${action.id}-title`)?.focus({ preventScroll: true });
    status.value = `已打开：${document.querySelector(`[data-feature="${action.id}"] summary span`)?.textContent ?? ''}`;
    refreshMotionLayout();
  } else if (action.type === 'scene') await showScene(action.id);
  else if (action.type === 'source') await showScene('check', true);
  else navigate(action.id);
}

onMounted(() => {
  if ('IntersectionObserver' in window) {
    const visible = new Map<string, number>();
    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.set(entry.target.id, entry.boundingClientRect.top);
          else visible.delete(entry.target.id);
        }
        const first = [...visible].sort((a, b) => a[1] - b[1])[0];
        activeSection.value = first?.[0] ?? '';
      },
      { rootMargin: '-15% 0px -58% 0px', threshold: 0 },
    );
    for (const id of ['capabilities', 'workflow', 'trust', 'faq']) {
      const section = document.getElementById(id);
      if (section) observer.observe(section);
    }
  }
  const hash = decodeURIComponent(window.location.hash.slice(1));
  if (hash && document.getElementById(hash)) void nextTick(() => navigate(hash));
});
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <div ref="root">
    <a class="skip-link" href="#main" @click.prevent="navigate('main')">跳到正文</a>
    <SiteHeader :active-section="activeSection" @acquire="acquire" @navigate="navigate" />
    <main id="main" tabindex="-1">
      <HeroSection @acquire="acquire" @navigate="navigate"><WorkDemo ref="demo" /></HeroSection>
      <RolesSection @action="act" />
      <CapabilitiesSection ref="capabilities" @scene="showScene" />
      <WorkflowSection />
      <TrustSection />
      <InstallSection @acquire="acquire" />
      <FaqSection />
    </main>
    <SiteFooter @acquire="acquire" @navigate="navigate" />
    <AcquireDialog v-model="acquireOpen" :trigger="acquireTrigger" />
    <div id="page-status" class="sr-only" role="status" aria-live="polite">{{ status }}</div>
  </div>
</template>
