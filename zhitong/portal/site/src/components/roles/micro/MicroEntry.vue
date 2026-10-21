<script lang="ts">
/** 企业知识库（03 章 §1.5.7 `entry`）：条目卡逐行展开、标“待核”、收进“公司经验/”并 +1。约 1.7s。 */
import { defineComponent } from 'vue';
import { pick, type MicroBuild } from './types';

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out', duration: 0.28 } });
  const card = pick(svg, 'card');
  tl.fromTo(card, { y: 6, opacity: 0, scale: 1 }, { y: 0, opacity: 1 }, 0);
  tl.fromTo(
    pick(svg, 'line'),
    { clipPath: 'inset(0 100% 0 0)' },
    { clipPath: 'inset(0 0% 0 0)', stagger: 0.15, clearProps: 'clipPath' },
    0.25,
  );
  tl.from(pick(svg, 'badge'), { scale: 0.6, opacity: 0, transformOrigin: '50% 50%' }, 0.8);
  tl.to(card, { scale: 0.4, y: 46, opacity: 0, transformOrigin: '50% 100%', duration: 0.45, ease: 'power2.inOut' }, 1.1);
  tl.fromTo(pick(svg, 'plus'), { opacity: 0 }, { opacity: 1 }, 1.4);
  return tl;
};
export default defineComponent({ name: 'MicroEntry' });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <path class="m-s m-fill" d="M40 76H62L66 80H120V94H40Z" />
    <text class="m-t" x="80" y="90" text-anchor="middle">公司经验/</text>
    <text class="m-t m-blue" data-m="plus" x="124" y="90">+1</text>
    <g data-m="card" opacity="0">
      <rect class="m-page" x="8" y="4" width="144" height="64" rx="4" />
      <text class="m-t" data-m="line" x="14" y="22">来源：项目/<tspan class="m-mono">2026-007</tspan></text>
      <text class="m-t" data-m="line" x="14" y="40">日期：<tspan class="m-mono">2026-10-19</tspan></text>
      <text class="m-t" data-m="line" x="14" y="58">核验：</text>
      <g data-m="badge">
        <rect class="m-bg-warn" x="50" y="46" width="30" height="16" rx="3" />
        <text class="m-t m-warn" x="65" y="58" text-anchor="middle">待核</text>
      </g>
    </g>
  </svg>
</template>
