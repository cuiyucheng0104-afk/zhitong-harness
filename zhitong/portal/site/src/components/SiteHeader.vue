<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
import brandMark from '../../assets/brand-mark.svg';
import { useMediaQuery } from '../composables/useMediaQuery';

defineProps<{ activeSection: string }>();
const emit = defineEmits<{ acquire: [event: MouseEvent]; navigate: [id: string] }>();
const menuOpen = ref(false);
const header = ref<HTMLElement | null>(null);
const menuButton = ref<HTMLButtonElement | null>(null);
const compact = useMediaQuery('(max-width: 1023px)');
const links = [
  { id: 'capabilities', label: '产品能力' },
  { id: 'workflow', label: '使用流程' },
  { id: 'trust', label: '数据与复核' },
  { id: 'faq', label: '常见问题' },
];
function navigate(id: string) {
  menuOpen.value = false;
  emit('navigate', id);
}
function acquire(event: MouseEvent) {
  menuOpen.value = false;
  emit('acquire', event);
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && menuOpen.value) {
    menuOpen.value = false;
    menuButton.value?.focus();
  }
}
function outside(event: MouseEvent) {
  if (!header.value?.contains(event.target as Node)) menuOpen.value = false;
}
watch(compact, () => {
  menuOpen.value = false;
});
onMounted(() => {
  document.addEventListener('keydown', keydown);
  document.addEventListener('click', outside);
});
onBeforeUnmount(() => {
  document.removeEventListener('keydown', keydown);
  document.removeEventListener('click', outside);
});
</script>

<template>
  <header id="top" ref="header" class="site-header">
    <div class="container header-inner">
      <a
        class="brand"
        href="#main"
        aria-label="智通数工AI，返回首页"
        @click.prevent="navigate('main')"
        ><img class="brand-mark" :src="brandMark" alt="" width="36" height="36" /><span
          >智通数工<span class="brand-ai">AI</span></span
        ></a
      >
      <nav class="desktop-nav" aria-label="主导航">
        <a
          v-for="link in links"
          :key="link.id"
          :href="`#${link.id}`"
          :class="{ active: activeSection === link.id }"
          :aria-current="activeSection === link.id ? 'location' : undefined"
          @click.prevent="navigate(link.id)"
          >{{ link.label }}</a
        >
      </nav>
      <button class="button button-primary header-cta" @click="acquire">
        获取安装与配置包<AppIcon name="arrow" />
      </button>
      <button
        ref="menuButton"
        class="menu-toggle icon-button"
        :aria-label="menuOpen ? '关闭导航菜单' : '打开导航菜单'"
        :aria-expanded="menuOpen"
        aria-controls="mobile-menu"
        @click="menuOpen = !menuOpen"
      >
        <span></span><span></span>
      </button>
    </div>
    <nav id="mobile-menu" class="mobile-menu" aria-label="移动端导航" :hidden="!menuOpen">
      <a
        v-for="link in links"
        :key="link.id"
        :href="`#${link.id}`"
        @click.prevent="navigate(link.id)"
        >{{ link.label }}<AppIcon name="arrow" /></a
      ><button class="button button-primary" @click="acquire">
        获取安装与配置包<AppIcon name="arrow" />
      </button>
    </nav>
  </header>
</template>
