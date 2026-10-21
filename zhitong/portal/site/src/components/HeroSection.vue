<script setup lang="ts">
/**
 * 首屏文案区（02 章 §1）。标题在构建期按字拆成 `span.ch`（带 `--i`），字级入场用 CSS 关键帧，不等 GSAP（§1.5）。
 * - 主按钮“获取安装包”：`acquire`，由 HomePage 打开获取弹层。
 * - 次按钮“看它怎么工作”：并排且示例可见时原地从场景 1 重播，否则先滚到 #demo 再重播（由 WorkDemo 经 demo/bus 完成）；
 *   同时发出 `watch` 事件。图标挂载后按 `(min-width: 1280px)` 在 play / down 间切换，SSR 输出 down。
 * - 平台说明里的“配置包”是说明卡触发按钮（虚线下划线）。
 * 原 `.hero-principles` 已移到 PrinciplesStrip.vue；D1 装饰（07 章）在本区块最底层。
 */
import { ref } from 'vue';
import AppIcon from './AppIcon.vue';
import ZtPopover from './ui/ZtPopover.vue';
import DecoHeroGrid from './deco/DecoHeroGrid.vue';
import { HERO } from '../data/hero';
import { demoBus } from './demo/bus';
import { useMediaQuery } from '../composables/useMediaQuery';

const emit = defineEmits<{ acquire: [event: MouseEvent]; watch: [] }>();
const titleLines = HERO.titleLines;
const split = useMediaQuery('(min-width: 1280px)');
const popover = ref<InstanceType<typeof ZtPopover> | null>(null);

function onWatch(event: MouseEvent) {
  emit('watch');
  void demoBus.watch(event.currentTarget as HTMLElement);
}
function openConfig(event: MouseEvent) {
  popover.value?.toggle(event.currentTarget as HTMLElement);
}
</script>

<template>
  <section class="hero" aria-labelledby="hero-title">
    <DecoHeroGrid />
    <div class="container hero-grid">
      <div class="hero-copy">
        <p class="eyebrow hero-enter"><span class="small-cross" aria-hidden="true"></span>{{ HERO.eyebrow }}</p>
        <h1 id="hero-title" class="hero-title">
          <span class="hero-line"
            ><span v-for="(c, i) in titleLines[0]" :key="i" class="ch" :style="{ '--i': i }">{{ c }}</span></span
          ><span class="hero-line hero-line-strong"
            ><span v-for="(c, i) in titleLines[1]" :key="i" class="ch" :style="{ '--i': i + 7 }">{{ c }}</span
            ><svg class="hero-dimline" viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true">
              <path pathLength="100" d="M0 4H100M0 1V7M100 1V7" /></svg
          ></span>
        </h1>
        <p class="hero-description hero-enter">
          {{ HERO.description[0] }}
        </p>
        <div class="hero-actions hero-enter">
          <button v-magnetic type="button" class="button button-primary hero-primary" @click="emit('acquire', $event)">
            <span data-magnetic-label class="button-label">{{ HERO.primary }}<AppIcon name="arrow" class="icon" /></span>
          </button>
          <button
            v-magnetic="'link'"
            type="button"
            class="text-link hero-watch"
            aria-controls="demo"
            :aria-label="HERO.secondaryLabel"
            @click="onWatch"
          >
            <span data-magnetic-label class="button-label">{{ HERO.secondary }}<AppIcon :name="split ? 'play' : 'down'" class="icon" /></span>
          </button>
        </div>
        <noscript data-allow-mismatch="children"
          ><p class="hero-noscript">安装包下载见页面下方<a href="#install">「安装与交付」</a></p></noscript
        >
        <p class="platform-note hero-enter">
          <span class="platform-os"><AppIcon name="apple" class="icon" /><AppIcon name="window" class="icon" />{{ HERO.platform }}</span>
          <span class="note-divider" aria-hidden="true"></span>
          <span
            ><button type="button" class="term" aria-expanded="false" aria-controls="hero-config-popover" @click="openConfig">
              {{ HERO.configTerm }}</button
            >{{ HERO.configSuffix }}</span
          >
        </p>
      </div>
      <slot />
    </div>
    <ZtPopover
      id="hero-config-popover"
      ref="popover"
      :title="HERO.configPopover.title"
      :lead="HERO.configPopover.lead"
      :rows="[...HERO.configPopover.rows]"
    />
  </section>
</template>
