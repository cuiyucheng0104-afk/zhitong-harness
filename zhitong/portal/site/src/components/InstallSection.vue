<script setup lang="ts">
/**
 * 安装与交付 `#install`（05 章 §3）。深色面板，第一个子元素是 07 章的 `<DecoInstallField>`。
 * - 版本、日期、文件名、大小、SHA256 全部来自 `downloads.ts` 的 `release`（`public/downloads/releases.json`）。
 * - 平台卡复用 01 章 `PlatformCard`（`surface="dark"`、`magnetic`）；两张卡始终都显示，顺序不随识别结果变化。
 * - 水合后识别一次平台：Mac / Windows 卡加匹配标记（绝对定位，不引起位移）；手机与平板在版本行上方显示提示。
 * - “首次打开与校验”展开收起后 200 ms 防抖刷新 ScrollTrigger（本区高度变化会移动 #faq 与页脚的触发位置）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';
import AppIcon from './AppIcon.vue';
import PlatformCard from './acquire/PlatformCard.vue';
import ConfigPackageNote from './sections05/install/ConfigPackageNote.vue';
import ContactList from './sections05/ContactList.vue';
import DecoInstallField from './deco/DecoInstallField.vue';
import { release } from '../data/downloads';
import { INSTALL_COPY } from '../data/install';
import { contactChannels, siteConfig } from '../site.config';
import { detectPlatform, type VisitorPlatform } from '../lib/platform';
import { useCopy } from '../composables/useCopy';
import { refreshMotionLayout } from '../lib/motion';

defineEmits<{ acquire: [event: MouseEvent] }>();

const platform = ref<VisitorPlatform>(null);
const showContact = contactChannels(siteConfig.contact).length > 0;
const { copy } = useCopy();
let refreshTimer: ReturnType<typeof setTimeout> | undefined;

function copyPage() {
  void copy(`${location.origin}/#install`, { success: INSTALL_COPY.copiedPage });
}
function onToggle(e: Event) {
  if (!(e.target instanceof HTMLDetailsElement)) return;
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refreshMotionLayout, 200);
}

const panel = ref<HTMLElement | null>(null);
onMounted(() => {
  platform.value = detectPlatform();
  panel.value?.addEventListener('toggle', onToggle, true);
});
onBeforeUnmount(() => {
  clearTimeout(refreshTimer);
  panel.value?.removeEventListener('toggle', onToggle, true);
});
</script>

<template>
  <section id="install" class="install-section section-space" aria-labelledby="install-title">
    <div class="container">
      <div ref="panel" class="install-panel on-dark deco-navy-grid">
        <DecoInstallField />
        <div class="install-content">
          <div class="install-head">
            <p class="eyebrow">{{ INSTALL_COPY.eyebrow }}</p>
            <h2 id="install-title" tabindex="-1" data-reveal="heading">{{ INSTALL_COPY.title }}</h2>
            <p class="install-lead" data-reveal="block">{{ INSTALL_COPY.lead }}</p>
          </div>
          <div class="install-block install-package" data-reveal="block">
            <h3>{{ INSTALL_COPY.packageTitle }}</h3>
            <p>{{ INSTALL_COPY.packageBody }}</p>
          </div>
          <div class="install-release">
            <div v-if="platform === 'mobile'" class="install-mobile-note">
              <p>{{ INSTALL_COPY.mobileNote }}</p>
              <button
                type="button"
                class="button button-dark-outline button-small"
                @click="copyPage"
              >
                {{ INSTALL_COPY.copyPage }}
              </button>
            </div>
            <p class="install-version">
              <span class="mono">v{{ release.version }}</span
              ><span aria-hidden="true"> · </span
              ><span>{{ INSTALL_COPY.releaseDate(release.date) }}</span>
            </p>
            <p v-if="release.base" class="install-base">{{ INSTALL_COPY.base(release.base) }}</p>
            <ul
              class="install-platforms"
              :aria-label="INSTALL_COPY.listLabel(release.version)"
              data-reveal="stagger"
            >
              <PlatformCard
                v-for="item in release.platforms"
                :key="item.platform"
                :item="item"
                :matched="platform === item.platform"
                :base="null"
                surface="dark"
                :magnetic="item.available"
              />
            </ul>
            <RouterLink class="text-link install-help" :to="INSTALL_COPY.helpLink.href"
              >{{ INSTALL_COPY.helpLink.text }}<AppIcon name="arrow" class="icon"
            /></RouterLink>
          </div>
          <ConfigPackageNote />
          <div v-if="showContact" class="install-block install-contact" data-reveal="block">
            <h3>{{ INSTALL_COPY.contactTitle }}</h3>
            <p>{{ INSTALL_COPY.contactLead }}</p>
            <ContactList />
          </div>
          <RouterLink class="text-link install-doc" :to="INSTALL_COPY.docLink.href"
            >{{ INSTALL_COPY.docLink.text }}<AppIcon name="arrow" class="icon"
          /></RouterLink>
        </div>
      </div>
    </div>
  </section>
</template>
