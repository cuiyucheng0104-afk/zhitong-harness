<script setup lang="ts">
/**
 * 应用外壳（01 章 §13）：跳到正文、顶栏、AcquireDialog、ZtToast、朗读区在 RouterView 之外常驻；
 * RouterView 外包页面切换过渡（key = route.meta.layout；文档页之间不触发，由 06 章在 .docs-main 内处理）。
 */
import { computed, nextTick } from 'vue';
import { useRoute } from 'vue-router';
import SiteHeader from './components/SiteHeader.vue';
import AcquireDialog from './components/AcquireDialog.vue';
import ZtToast from './components/ui/ZtToast.vue';
import SiteFooter from './components/SiteFooter.vue';
import { acquireState, openAcquire, setAcquireOpen } from './composables/useAcquire';
import { announce } from './composables/useToast';
import { goToSection } from './lib/home-state';
import { refreshMotionLayout } from './lib/motion';
import type { PageLayout } from './composables/useHeaderState';

const route = useRoute();
const layout = computed<PageLayout>(() => route.meta.layout ?? 'home');

function skip(event: MouseEvent) {
  event.preventDefault();
  const main = document.getElementById('main');
  if (!main) return;
  if (layout.value === 'home') void goToSection('main', true);
  else {
    main.focus({ preventScroll: true });
    main.scrollIntoView({ block: 'start', behavior: 'instant' });
  }
}

function onAfterLeave() {
  const saved = (history.state as { scroll?: { left: number; top: number } } | null)?.scroll;
  window.scrollTo({ top: saved?.top ?? 0, left: saved?.left ?? 0, behavior: 'instant' });
}

async function onAfterEnter() {
  await nextTick();
  const hash = decodeURIComponent(route.hash.slice(1));
  if (layout.value === 'home') {
    refreshMotionLayout();
    await new Promise((r) => requestAnimationFrame(r));
    if (hash && document.getElementById(hash)) await goToSection(hash, true);
    else document.getElementById('main')?.focus({ preventScroll: true });
  } else {
    const target = hash ? document.getElementById(hash) : null;
    if (target) target.scrollIntoView({ block: 'start', behavior: 'instant' });
    document.getElementById('main')?.focus({ preventScroll: true });
  }
  announce(`已打开：${document.title}`);
}
</script>

<template>
  <a class="skip-link" href="#main" @click="skip">跳到正文</a>
  <SiteHeader :layout="layout" @acquire="openAcquire" />
  <RouterView v-slot="{ Component, route: current }">
    <Transition name="page" mode="out-in" :appear="false" @after-leave="onAfterLeave" @after-enter="onAfterEnter">
      <component :is="Component" :key="current.meta.layout" />
    </Transition>
  </RouterView>
  <!-- /privacy/ 的页面根元素是 <main id="main">，页脚由外壳补上（05 章反馈）。 -->
  <SiteFooter v-if="route.name === 'privacy'" context="docs" @acquire="openAcquire" />
  <AcquireDialog
    :model-value="acquireState.open"
    :trigger="acquireState.trigger"
    @update:model-value="setAcquireOpen"
  />
  <ZtToast />
  <div id="page-status" class="sr-only" role="status" aria-live="polite"></div>
</template>
