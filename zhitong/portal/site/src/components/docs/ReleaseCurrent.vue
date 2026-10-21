<script setup lang="ts">
/**
 * 当前版本卡片（06 章 §7.13）：数据为 `data/downloads.ts` 的 `release`（构建期读入并校验 releases.json，与首页安装区同源）。
 * `file` 为 null 的平台显示「即将发布」，没有任何链接。首次打开与校验步骤不在卡片里重复，见 install 页。
 */
import { ref } from 'vue';
import AppIcon from '../AppIcon.vue';
import { release } from '../../data/downloads';
import { useCopy } from '../../composables/useCopy';
import { useHydrated } from './useHydrated';

const hydrated = useHydrated();
const { copy } = useCopy();
const copied = ref('');
const shaEls = ref<Record<string, HTMLElement | null>>({});
let timer: ReturnType<typeof setTimeout> | undefined;

async function copySha(platform: string, sha: string) {
  const ok = await copy(sha, { success: '已复制 SHA256 校验值', fallbackSelect: shaEls.value[platform] });
  if (!ok) return;
  copied.value = platform;
  clearTimeout(timer);
  timer = setTimeout(() => (copied.value = ''), 1600);
}
const platformName = (p: (typeof release.platforms)[number]) => `${p.name} · ${p.arch}`;
</script>

<template>
  <section class="release-current" aria-labelledby="release-current-title">
    <header class="release-head">
      <h3 id="release-current-title" class="release-version">v{{ release.version }}</h3>
      <p class="release-date">{{ release.date ? `${release.date} 发布` : '尚未发布' }}</p>
      <p v-if="release.base" class="release-base">应用内版本 <span class="mono">{{ release.base }}</span></p>
    </header>
    <ul v-if="release.notes.length" class="release-notes">
      <li v-for="(note, i) in release.notes" :key="i">{{ note }}</li>
    </ul>
    <ul class="release-platforms">
      <li v-for="p in release.platforms" :key="p.platform" class="release-platform">
        <div class="release-row">
          <p class="release-platform-name"><AppIcon :name="p.icon" class="icon" />{{ platformName(p) }}</p>
          <template v-if="p.available">
            <p class="release-file mono">{{ p.file }}</p>
            <p class="release-size num">{{ p.size }}</p>
            <div class="release-sha">
              <span class="release-sha-label">SHA256</span>
              <code :ref="(el) => (shaEls[p.platform] = el as HTMLElement | null)" class="release-sha-value" tabindex="0">{{ p.sha256 }}</code>
              <button
                v-if="hydrated"
                type="button"
                class="code-copy"
                :class="{ 'is-copied': copied === p.platform }"
                aria-label="复制 SHA256 校验值"
                @click="copySha(p.platform, p.sha256)"
              >
                <span class="copy-icons" aria-hidden="true"><AppIcon name="copy" class="i-copy" /><AppIcon name="check" class="i-check" /></span>
              </button>
            </div>
            <div class="release-actions">
              <a class="button button-primary" :href="p.href" download :aria-label="`下载 ${p.name} 安装包 ${p.file}，${p.size}`">
                <AppIcon name="down" class="icon" />下载
              </a>
              <a class="text-link" :href="p.sha256Href">SHA256 文件</a>
            </div>
          </template>
          <p v-else class="release-soon">即将发布</p>
        </div>
        <p v-if="p.notes" class="release-platform-notes">{{ p.notes }}</p>
      </li>
    </ul>
    <p class="release-more"><RouterLink to="/docs/install/#校验安装包">首次打开与校验步骤</RouterLink></p>
  </section>
</template>
