<script setup lang="ts">
/**
 * 移动菜单（01 章 §5）：`<dialog id="mobile-menu">` 经 BaseDialog（variant custom）以 showModal 打开，铺满视口。
 * 动画用 Web Animations API（首页与文档页一致，不依赖 GSAP）：
 * 打开 clip-path 450ms inOut；5 行 opacity/translateY 450ms out，第 i 行延迟 120 + i×70ms；主按钮区 280ms 延迟 470ms；
 * 关闭 clip-path 280ms inOut 后 close()。减少动效时直接显示与关闭。
 * 点链接：先关闭（等 close 事件），再滚动或路由跳转；视口 ≥ 1024px 时立即关闭（无动画）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import BaseDialog from '../BaseDialog.vue';
import AppIcon from '../AppIcon.vue';
import brandMark from '../../../assets/brand-mark.svg';
import { NAV_LINKS, type NavSectionId } from '../../data/nav';
import { release } from '../../data/downloads';
import { CSS_EASE, MS } from '../../lib/motion-tokens';
import type { PageLayout } from '../../composables/useHeaderState';

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    layout: PageLayout;
    activeId?: string;
    trigger?: HTMLElement | null;
  }>(),
  { activeId: '', trigger: null },
);
const emit = defineEmits<{
  'update:modelValue': [value: boolean];
  navigate: [id: NavSectionId];
  acquire: [];
}>();

const router = useRouter();
const dialog = ref<InstanceType<typeof BaseDialog> | null>(null);
let pending: (() => void) | null = null;
let media: MediaQueryList | undefined;

const footnote = `v${release.version} · ${release.platforms
  .map((p) => `${p.name}（${p.arch}）${p.available ? '' : '（即将发布）'}`)
  .join('与 ')}`;

function enter(el: HTMLDialogElement) {
  if (typeof el.animate !== 'function') return;
  el.animate([{ clipPath: 'inset(0 0 100% 0)' }, { clipPath: 'inset(0 0 0 0)' }], {
    duration: MS.base,
    easing: CSS_EASE.inOut,
  });
  el.querySelectorAll('[data-menu-row]').forEach((row, i) =>
    (row as HTMLElement).animate(
      [
        { opacity: 0, transform: 'translateY(16px)' },
        { opacity: 1, transform: 'none' },
      ],
      { duration: MS.base, easing: CSS_EASE.out, delay: 120 + i * 70, fill: 'backwards' },
    ),
  );
  el.querySelector<HTMLElement>('.mobile-sheet-cta')?.animate([{ opacity: 0 }, { opacity: 1 }], {
    duration: MS.short,
    delay: 470,
    fill: 'backwards',
  });
}

function leave(el: HTMLDialogElement) {
  if (typeof el.animate !== 'function') return;
  return el.animate([{ clipPath: 'inset(0 0 0 0)' }, { clipPath: 'inset(0 0 100% 0)' }], {
    duration: MS.short,
    easing: CSS_EASE.inOut,
    fill: 'forwards',
  }).finished;
}

function closeThen(action: () => void) {
  pending = action;
  emit('update:modelValue', false);
}

function onClosed() {
  const action = pending;
  pending = null;
  action?.();
}

function go(id: NavSectionId) {
  closeThen(() => {
    if (props.layout === 'home') emit('navigate', id);
    else void router.push(`/#${id}`);
  });
}
function goDocs() {
  closeThen(() => void router.push('/docs/'));
}
function acquire() {
  closeThen(() => emit('acquire'));
}

const onWide = () => {
  if (!media?.matches) return;
  const el = dialog.value?.element;
  if (el?.open) el.close();
};
onMounted(() => {
  media = window.matchMedia?.('(min-width: 1024px)');
  media?.addEventListener?.('change', onWide);
});
onBeforeUnmount(() => media?.removeEventListener?.('change', onWide));
</script>

<template>
  <BaseDialog
    id="mobile-menu"
    ref="dialog"
    class="mobile-sheet"
    variant="custom"
    labelledby="mobile-menu-title"
    :model-value="modelValue"
    :trigger="trigger"
    :enter="enter"
    :leave="leave"
    @update:model-value="emit('update:modelValue', $event)"
    @closed="onClosed"
  >
    <h2 id="mobile-menu-title" class="sr-only">导航菜单</h2>
    <div class="mobile-sheet-top">
      <span class="brand" aria-hidden="true"
        ><img class="brand-mark" :src="brandMark" alt="" width="36" height="36" /><span
          >智通数工<span class="brand-ai">AI</span></span
        ></span
      >
      <button
        type="button"
        class="menu-toggle icon-button is-open"
        aria-label="关闭导航菜单"
        @click="emit('update:modelValue', false)"
      >
        <span></span><span></span>
      </button>
    </div>
    <nav class="mobile-sheet-nav" aria-label="移动端导航">
      <a
        v-for="(link, i) in NAV_LINKS"
        :key="link.id"
        :href="layout === 'home' ? `#${link.id}` : `/#${link.id}`"
        :class="['mobile-sheet-row', { 'is-current': activeId === link.id }]"
        :aria-current="activeId === link.id ? 'location' : undefined"
        data-menu-row
        @click.prevent="go(link.id)"
        ><span class="mobile-sheet-index mono">{{ String(i + 1).padStart(2, '0') }}</span
        ><span class="mobile-sheet-label">{{ link.label }}</span><AppIcon name="arrow" /></a
      >
      <a
        href="/docs/"
        :class="['mobile-sheet-row', 'mobile-sheet-docs', { 'is-current': layout === 'docs' }]"
        :aria-current="layout === 'docs' ? 'page' : undefined"
        data-menu-row
        @click.prevent="goDocs"
        ><span class="mobile-sheet-label">文档<small>安装、配置包、12 项能力与排错</small></span
        ><AppIcon name="arrow"
      /></a>
      <slot name="extra" />
    </nav>
    <div class="mobile-sheet-cta">
      <button type="button" class="button button-primary full-width" @click="acquire">
        获取安装包<AppIcon name="arrow" />
      </button>
      <p class="mobile-sheet-foot">{{ footnote }}</p>
    </div>
  </BaseDialog>
</template>
