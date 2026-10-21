<script setup lang="ts">
/**
 * 顶栏（01 章 §1–§6）：品牌、导航（滑块吸附 + 当前章节）、文档、主按钮、菜单按钮、比例尺进度。
 * `position: fixed`，盒子恒为 72px（≤ 767px 64px）；紧凑只用 transform（背景层 scaleY、内容行上移 4px）。
 * 状态写在根元素 `data-state="top|scrolled|docs"`；预渲染输出 top（首页）或 docs。
 * 首页链接 `#id` 由 goToSection 接管；文档页与 404 页为 `RouterLink to="/#id"`。
 */
import { computed, onMounted, ref, toRef } from 'vue';
import { useRoute } from 'vue-router';
import AppIcon from './AppIcon.vue';
import HeaderRuler from './header/HeaderRuler.vue';
import MobileMenu from './header/MobileMenu.vue';
import brandMark from '../../assets/brand-mark.svg';
import { DOCS_LINK, NAV_LINKS, type NavSectionId } from '../data/nav';
import { goToSection, navSpy } from '../lib/home-state';
import { useHeaderState, type PageLayout } from '../composables/useHeaderState';
import { useHoverIndicator } from '../composables/useHoverIndicator';

const props = defineProps<{ layout: PageLayout }>();
const emit = defineEmits<{ acquire: [trigger: HTMLElement] }>();

const route = useRoute();
const { state } = useHeaderState(toRef(props, 'layout'));
const nav = ref<HTMLElement | null>(null);
const indicator = ref<HTMLElement | null>(null);
const menuButton = ref<HTMLButtonElement | null>(null);
const menuOpen = ref(false);
const mounted = ref(false);

const isHome = computed(() => props.layout === 'home');
const isDocs = computed(() => props.layout === 'docs' && route.path.startsWith('/docs/'));
const current = computed<NavSectionId | ''>(() => (isHome.value ? navSpy.active.value : ''));

useHoverIndicator({
  container: nav,
  indicator,
  driver: 'css',
  active: () => {
    const root = nav.value;
    if (!root) return null;
    if (isDocs.value) return root.querySelector<HTMLElement>('[data-nav="docs"]');
    return current.value ? root.querySelector<HTMLElement>(`[data-nav="${current.value}"]`) : null;
  },
});

function onNav(event: MouseEvent, id: NavSectionId) {
  if (!isHome.value) return;
  event.preventDefault();
  void goToSection(id);
}
function onBrand(event: MouseEvent) {
  if (!isHome.value) return;
  event.preventDefault();
  void goToSection('main');
}
function acquire(event: MouseEvent) {
  emit('acquire', event.currentTarget as HTMLElement);
}
function menuNavigate(id: NavSectionId) {
  void goToSection(id);
}
function menuAcquire() {
  if (menuButton.value) emit('acquire', menuButton.value);
}

onMounted(() => (mounted.value = true));
</script>

<template>
  <header id="top" class="site-header" :data-state="state" :data-layout="layout">
    <div class="site-header__bg" aria-hidden="true"></div>
    <HeaderRuler v-if="mounted" :layout="layout" :active-id="current" />
    <div class="container header-inner">
      <RouterLink class="brand" to="/" aria-label="智通数工AI 首页" @click="onBrand"
        ><img class="brand-mark" :src="brandMark" alt="" width="36" height="36" /><span
          >智通数工<span class="brand-ai">AI</span></span
        ></RouterLink
      >
      <nav ref="nav" class="desktop-nav" aria-label="主导航">
        <span ref="indicator" class="nav-indicator" aria-hidden="true"></span>
        <template v-for="link in NAV_LINKS" :key="link.id">
          <a
            v-if="isHome"
            v-magnetic="'link'"
            :href="`#${link.id}`"
            class="nav-link"
            :class="{ active: current === link.id }"
            :data-nav="link.id"
            data-indicator-item
            :aria-current="current === link.id ? 'location' : undefined"
            @click="onNav($event, link.id)"
            ><span data-magnetic-label>{{ link.label }}</span></a
          >
          <RouterLink
            v-else
            :to="`/#${link.id}`"
            class="nav-link"
            :data-nav="link.id"
            data-indicator-item
            ><span>{{ link.label }}</span></RouterLink
          >
        </template>
        <span class="nav-divider" aria-hidden="true"></span>
        <RouterLink
          v-magnetic="isHome ? 'link' : false"
          :to="DOCS_LINK.to"
          class="nav-link nav-docs"
          :class="{ active: isDocs }"
          data-nav="docs"
          data-indicator-item
          :aria-current="isDocs ? 'page' : undefined"
          ><span data-magnetic-label><AppIcon name="book" />{{ DOCS_LINK.label }}</span></RouterLink
        >
      </nav>
      <button
        v-magnetic="isHome ? 'button' : false"
        type="button"
        class="button button-primary header-cta"
        aria-haspopup="dialog"
        aria-controls="acquire-dialog"
        @click="acquire"
      >
        <span data-magnetic-label>获取安装包<AppIcon name="arrow" /></span>
      </button>
      <button
        ref="menuButton"
        type="button"
        class="menu-toggle icon-button"
        :class="{ 'is-open': menuOpen }"
        aria-label="打开导航菜单"
        :aria-expanded="menuOpen"
        aria-controls="mobile-menu"
        @click="menuOpen = true"
      >
        <span></span><span></span>
      </button>
    </div>
    <MobileMenu
      v-model="menuOpen"
      :layout="layout"
      :active-id="current"
      :trigger="menuButton"
      @navigate="menuNavigate"
      @acquire="menuAcquire"
    />
  </header>
</template>
