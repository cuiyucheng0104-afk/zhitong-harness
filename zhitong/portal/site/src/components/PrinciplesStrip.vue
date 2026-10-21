<script setup lang="ts">
/**
 * 三条原则条（02 章 §7）：把示例当前在做的事归到“对话组织任务 / 脚本完成计算 / 人工复核结果”之一并点亮。
 * 点亮值来自 WorkDemo（demo/bus 的 `currentPrinciple`）：播放中取当前步骤的 `p`，停留为 review，暂停保持，
 * 离开视口、页面隐藏、播完、减少动效、未启动时为 null（三项都不点亮）。
 * 点亮项从 i 变到 j 时，6px 圆点沿连线从 i 侧移到 j 侧（DUR.base，EASE.inOut），到达后淡出（DUR.micro）。
 * 说明直接写在每项下方的卡片里（按用户意见不再点击弹出浮层）：滚到这里时随 `data-reveal="stagger"` 依次入场；
 * “看示例”调用 showScene 并滚回示例；“读文档”去对应文档页（00 章 §14 第 9 条）。
 */
import { computed, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
import { PRINCIPLES, PRINCIPLES_LABEL, type PrincipleItem } from '../data/hero';
import { currentPrinciple, demoBus } from './demo/bus';
import { scrollToSection } from '../lib/smooth-scroll';
import { CSS_EASE, MS } from '../lib/motion-tokens';
import { prefersReducedMotion } from '../lib/motion';

const lit = computed(() => currentPrinciple.value);
const row = ref<HTMLElement | null>(null);
const dot = ref<HTMLElement | null>(null);

watch(lit, (next, prev) => {
  if (!next || !prev || next === prev) return;
  const el = dot.value;
  const box = row.value;
  if (!el || !box || typeof el.animate !== 'function' || prefersReducedMotion()) return;
  const items = [...box.querySelectorAll<HTMLElement>('.principle')];
  const i = PRINCIPLES.findIndex((p) => p.id === prev);
  const j = PRINCIPLES.findIndex((p) => p.id === next);
  const a = items[i]?.getBoundingClientRect();
  const b = items[j]?.getBoundingClientRect();
  const base = box.getBoundingClientRect();
  if (!a || !b) return;
  const from = (j > i ? a.right : a.left) - base.left;
  const to = (j > i ? b.left : b.right) - base.left;
  el.getAnimations().forEach((x) => x.cancel());
  el.animate(
    [
      { opacity: 1, transform: `translateX(${from - 3}px)` },
      { opacity: 1, transform: `translateX(${to - 3}px)`, offset: MS.base / (MS.base + MS.micro) },
      { opacity: 0, transform: `translateX(${to - 3}px)` },
    ],
    { duration: MS.base + MS.micro, easing: CSS_EASE.inOut },
  );
});

async function see(item: PrincipleItem) {
  await demoBus.showScene(item.scene);
  await scrollToSection('demo');
}
</script>

<template>
  <section id="principles" class="principles-strip" :aria-label="PRINCIPLES_LABEL">
    <div ref="row" class="container principles-row" data-reveal="stagger">
      <article
        v-for="item in PRINCIPLES"
        :key="item.id"
        class="principle-card"
        :data-lit="lit === item.id ? 'true' : 'false'"
        :aria-labelledby="`principle-${item.id}`"
      >
        <h3 :id="`principle-${item.id}`" class="principle" :data-principle="item.id" :data-lit="lit === item.id ? 'true' : 'false'">
          <AppIcon :name="item.icon" class="icon" /><span class="principle-label"
            >{{ item.label }}<i class="principle-bar" aria-hidden="true"></i
          ></span>
        </h3>
        <p class="principle-lead">{{ item.lead }}</p>
        <dl class="principle-rows">
          <div><dt>需要什么</dt><dd>{{ item.need }}</dd></div>
          <div><dt>得到什么</dt><dd>{{ item.get }}</dd></div>
        </dl>
        <p class="principle-actions">
          <button type="button" class="text-link" @click="see(item)">看示例</button>
          <RouterLink class="text-link" :to="item.doc">读文档<AppIcon name="book" class="icon" /></RouterLink>
        </p>
      </article>
      <i ref="dot" class="principle-dot" aria-hidden="true"></i>
    </div>
  </section>
</template>
