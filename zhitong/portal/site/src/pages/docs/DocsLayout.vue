<script setup lang="ts">
/**
 * 文档布局（06 章 §4、§7.1、§8.1、§9）：
 * - `<div class="docs">` 内 `aside.docs-sidebar`（文档目录）、`main#main.docs-main`、`nav.docs-toc`（本页目录）；
 *   ≥ 1200px 三栏，1024–1199px 两栏，≤ 1023px 单栏 + 文档子栏 + 抽屉。文档首页没有侧栏与本页目录。
 * - 正文列内的页面切换只淡入（160ms，离开 0ms）；侧栏与本页目录不动。
 * - 快捷键：⌘K（macOS）/ Ctrl+K（其它）打开搜索；焦点不在输入框、文本域、可编辑元素中时按 `/` 也打开。
 *   只在文档路由挂载期间绑定（首页不绑定）。
 * - 文档路由不加载 GSAP 与 Lenis；滚动与锚点全部用原生 API。
 * - 无 JS：平板与手机在正文末尾输出完整文档目录列表（水合后移除）。
 */
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter, type RouteLocationNormalizedLoaded } from 'vue-router';
import { docs, groups } from 'virtual:docs-manifest';
import SiteFooter from '../../components/SiteFooter.vue';
import DocsSidebar from '../../components/docs/DocsSidebar.vue';
import DocsToc from '../../components/docs/DocsToc.vue';
import DocsSearchTrigger from '../../components/docs/DocsSearchTrigger.vue';
import DocsHome from './DocsHome.vue';
import DocsPage from './DocsPage.vue';
import { docsUi, isApple, openSearch } from '../../docs/docs-ui';
import { openAcquire } from '../../composables/useAcquire';
import { announce } from '../../composables/useToast';

// 抽屉与搜索对话框按需加载（首次打开时），不计入文档页首包。
const DocsDrawer = defineAsyncComponent(() => import('../../components/docs/DocsDrawer.vue'));
const DocsSearch = defineAsyncComponent(() => import('../../components/docs/DocsSearch.vue'));
const route = useRoute();
const router = useRouter();
const hydrated = ref(false);
const toc = ref<InstanceType<typeof DocsToc> | null>(null);
const drawerButton = ref<HTMLElement | null>(null);
const drawerUsed = ref(false);
const searchUsed = ref(false);
watch(
  () => docsUi.drawerOpen,
  (v) => v && (drawerUsed.value = true),
);
watch(
  () => docsUi.searchOpen,
  (v) => v && (searchUsed.value = true),
);

const docFor = (r: RouteLocationNormalizedLoaded) => docs.find((d) => d.slug === r.meta.docSlug) ?? docs[0];
const doc = computed(() => docFor(route));
const isHome = computed(() => doc.value.slug === 'index');
const showToc = computed(() => !isHome.value && doc.value.headings.filter((h) => h.level === 2).length >= 2);
const frameFor = (r: RouteLocationNormalizedLoaded) => (r.meta.docSlug === 'index' ? DocsHome : DocsPage);

function openDrawer() {
  docsUi.drawerOpen = true;
}

function isEditable(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
}

function onKeydown(e: KeyboardEvent) {
  if (e.defaultPrevented || e.isComposing || document.querySelector('dialog[open]')) return;
  const mod = isApple() ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
  if (mod && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    openSearch();
  } else if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey && !isEditable(e.target)) {
    e.preventDefault();
    openSearch();
  }
}

/** 文档页之间切换完成：刷新本页目录，带锚点时定位到标题，否则焦点到正文；朗读页面标题。 */
async function onPageEnter() {
  await nextTick();
  toc.value?.refresh();
  const hash = safeDecode(route.hash.slice(1));
  const target = hash ? document.getElementById(hash) : null;
  if (target) {
    target.scrollIntoView({ block: 'start', behavior: 'instant' });
    target.focus({ preventScroll: true });
  } else document.getElementById('main')?.focus({ preventScroll: true });
  announce(`已打开：${document.title}`);
}

function safeDecode(s: string) {
  try {
    return decodeURIComponent(s);
  } catch {
    // 非法编码的锚点按原文查找。
    return s;
  }
}

function onFooterNavigate(id: string) {
  void router.push(id === 'main' ? '/' : `/#${id}`);
}

onMounted(() => {
  hydrated.value = true;
  window.addEventListener('keydown', onKeydown);
});
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown);
  docsUi.searchOpen = false;
  docsUi.drawerOpen = false;
});
</script>

<template>
  <div class="docs-root">
    <div class="docs" :class="{ 'is-home': isHome, 'has-toc': showToc, 'is-hydrated': hydrated }">
      <nav v-if="!isHome" class="docs-subbar" aria-label="文档子栏">
        <button
          v-if="hydrated"
          ref="drawerButton"
          type="button"
          class="subbar-menu"
          aria-haspopup="dialog"
          @click="openDrawer"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 6h16M4 12h16M4 18h10" /></svg>
          <span>文档目录</span>
        </button>
        <span v-else class="subbar-menu is-placeholder" aria-hidden="true"></span>
        <p class="subbar-title">{{ doc.title }}</p>
        <DocsSearchTrigger variant="icon" />
      </nav>

      <aside v-if="!isHome" class="docs-sidebar" aria-label="文档目录">
        <DocsSidebar />
      </aside>

      <main id="main" class="docs-main" tabindex="-1">
        <RouterView v-slot="{ Component, route: r }">
          <Transition name="docs-page" mode="out-in" @after-enter="onPageEnter">
            <component :is="frameFor(r)" :key="r.path" :doc="docFor(r)">
              <component :is="Component" />
            </component>
          </Transition>
        </RouterView>

        <nav v-if="!isHome && !hydrated" class="docs-fallback-nav" aria-label="全部文档">
          <p class="sidebar-group">全部文档</p>
          <ul>
            <li><RouterLink to="/docs/">文档首页</RouterLink></li>
          </ul>
          <template v-for="g in groups" :key="g.name">
            <p class="sidebar-group">{{ g.name }}</p>
            <ul>
              <li v-for="item in g.items" :key="item.slug">
                <RouterLink :to="item.path">{{ item.title }}</RouterLink>
              </li>
            </ul>
          </template>
        </nav>
      </main>

      <nav v-if="showToc" class="docs-toc" aria-label="本页目录">
        <DocsToc ref="toc" :headings="doc.headings" />
      </nav>
    </div>

    <SiteFooter context="docs" @acquire="openAcquire" @navigate="onFooterNavigate" />
    <DocsDrawer v-if="drawerUsed" :trigger="drawerButton" />
    <DocsSearch v-if="searchUsed" />
  </div>
</template>
