<script setup lang="ts">
/**
 * 平台卡片（01 章 §7.3–§7.5；05 章 §3.4 追加 surface、magnetic）。
 * 下载不拦截默认行为（`<a href download>`）；点击后按钮 2.4s 内显示“已开始下载”，并自动展开“首次打开与校验”。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import AppIcon from '../AppIcon.vue';
import { FIRST_LAUNCH_API_KEY, type PlatformDownload } from '../../data/downloads';
import { useCopy } from '../../composables/useCopy';
import { announce } from '../../composables/useToast';
import { prefersReducedMotion } from '../../lib/motion';
import { CSS_EASE, MS } from '../../lib/motion-tokens';

const props = withDefaults(
  defineProps<{
    item: PlatformDownload;
    matched: boolean;
    base: string | null;
    surface?: 'light' | 'dark';
    magnetic?: boolean;
    /** 卡片标题层级，弹层内为 h4。 */
    headingLevel?: 'h3' | 'h4';
  }>(),
  { surface: 'light', magnetic: false, headingLevel: 'h4' },
);

const { copy } = useCopy();
/** 复制按钮水合后才渲染（05 章 §3.6：无 JS 时不出现；按钮为绝对定位，位置已由容器内边距预留）。 */
const hydrated = ref(false);
onMounted(() => (hydrated.value = true));
const started = ref(false);
const copied = ref<'hash' | 'command' | null>(null);
const details = ref<HTMLDetailsElement | null>(null);
const hashEl = ref<HTMLElement | null>(null);
const commandEl = ref<HTMLElement | null>(null);
let startTimer: ReturnType<typeof setTimeout> | undefined;
let copyTimer: ReturnType<typeof setTimeout> | undefined;

const hashGroups = computed(() =>
  props.item.available ? (props.item.sha256.match(/.{1,16}/g) ?? []) : [],
);
const command = computed(() => (props.item.available ? props.item.verify(props.item.file) : ''));
const verifyText = computed(() =>
  props.item.verifyShell === '终端'
    ? '在“终端”中运行以下命令，输出应与上方 SHA256 校验值一致：'
    : '在 PowerShell 中运行以下命令，输出应与上方 SHA256 校验值一致（PowerShell 输出为大写字母，比对时不区分大小写）：',
);
const apiKeyParts = FIRST_LAUNCH_API_KEY.split('`');

function onDownload() {
  if (!props.item.available) return;
  started.value = true;
  clearTimeout(startTimer);
  startTimer = setTimeout(() => (started.value = false), 2400);
  announce(`已开始下载 ${props.item.file}`);
  const box = details.value;
  if (box && !box.open) {
    box.open = true;
    void nextTick(() => {
      const body = box.querySelector<HTMLElement>('.platform-first-body');
      if (body && !prefersReducedMotion() && typeof body.animate === 'function')
        body.animate(
          [
            { opacity: 0, transform: 'translateY(-4px)' },
            { opacity: 1, transform: 'none' },
          ],
          { duration: MS.short, easing: CSS_EASE.out },
        );
      box.scrollIntoView?.({ block: 'nearest', behavior: prefersReducedMotion() ? 'instant' : 'smooth' });
    });
  }
}

async function copyHash() {
  if (!props.item.available) return;
  if (await copy(props.item.sha256, { success: '已复制 SHA256 校验值', fallbackSelect: hashEl.value }))
    flash('hash');
}
async function copyCommand() {
  if (await copy(command.value, { success: '已复制校验命令', fallbackSelect: commandEl.value })) flash('command');
}
function flash(kind: 'hash' | 'command') {
  copied.value = kind;
  clearTimeout(copyTimer);
  copyTimer = setTimeout(() => (copied.value = null), 1600);
}
onBeforeUnmount(() => {
  clearTimeout(startTimer);
  clearTimeout(copyTimer);
});
</script>

<template>
  <li
    :class="[
      'platform-card',
      `on-${surface}`,
      { 'is-matched': matched, 'is-upcoming': !item.available },
    ]"
    :data-platform="item.platform"
  >
    <div class="platform-card-head">
      <AppIcon :name="item.icon" class="platform-card-icon" />
      <component :is="headingLevel" class="platform-card-name"
        >{{ item.name }}<span v-if="matched" class="platform-match"><span class="sr-only">，</span>与您的电脑匹配</span></component
      >
      <span class="platform-arch" data-deco-safe>{{ item.arch }}</span>
    </div>
    <p class="platform-fits">{{ item.fits }}</p>
    <template v-if="item.available">
      <p class="platform-file">
        <span class="mono">{{ item.file }}</span><span aria-hidden="true"> · </span
        ><span class="mono">{{ item.size }}</span>
      </p>
      <a
        v-magnetic="magnetic ? 'button' : false"
        :class="['button', surface === 'dark' ? 'button-white' : 'button-primary', 'platform-download', { 'is-started': started }]"
        :href="item.href"
        download
        @click="onDownload"
        ><span class="platform-download-label" data-magnetic-label
          ><span class="label-idle">{{ item.downloadLabel }}</span
          ><span class="label-started" aria-hidden="true">已开始下载</span></span
        ><span class="platform-download-icons" aria-hidden="true"
          ><AppIcon name="down" class="icon-down" /><AppIcon name="check" class="icon-check" /></span
        ><span v-if="started" class="sr-only">已开始下载</span></a
      >
      <div class="platform-hash">
        <span class="platform-hash-label" data-deco-safe>SHA256 校验值</span>
        <code ref="hashEl" class="platform-hash-value mono" data-deco-safe
          ><span v-for="(group, i) in hashGroups" :key="i">{{ group }}</span></code
        >
        <button
          v-if="hydrated"
          type="button"
          class="icon-button platform-copy"
          :class="{ 'is-copied': copied === 'hash' }"
          aria-label="复制 SHA256 校验值"
          @click="copyHash"
        >
          <AppIcon name="copy" class="icon-copy" /><AppIcon name="check" class="icon-check" />
        </button>
        <a class="text-link platform-sha-file" :href="item.sha256Href">下载 .sha256 文件</a>
      </div>
      <details ref="details" class="platform-first">
        <summary data-deco-safe>首次打开与校验</summary>
        <div class="platform-first-body">
          <ol>
            <li v-for="step in item.firstLaunch" :key="step">{{ step }}</li>
            <li>
              <template v-for="(part, i) in apiKeyParts" :key="i"
                ><code v-if="i % 2" class="mono">{{ part }}</code
                ><template v-else>{{ part }}</template></template
              >
            </li>
          </ol>
          <p class="platform-verify-note">{{ verifyText }}</p>
          <div class="platform-command" data-deco-safe>
            <code ref="commandEl" class="mono">{{ command }}</code>
            <button
              v-if="hydrated"
              type="button"
              class="icon-button platform-copy"
              :class="{ 'is-copied': copied === 'command' }"
              aria-label="复制校验命令"
              @click="copyCommand"
            >
              <AppIcon name="copy" class="icon-copy" /><AppIcon name="check" class="icon-check" />
            </button>
          </div>
          <p v-if="base" class="platform-base">安装后，“关于”中显示的程序版本为 {{ base }}。</p>
        </div>
      </details>
    </template>
    <template v-else>
      <span class="platform-upcoming-badge package-download-upcoming" data-deco-safe>即将发布</span>
      <p class="platform-upcoming-text">该平台的安装包尚未发布。</p>
    </template>
  </li>
</template>
