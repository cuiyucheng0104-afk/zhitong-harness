<script lang="ts">
/** 资料盘点（03 章 §1.5.7 `inventory`）：4 行文件，扫描线经过时徽标弹出。约 1.0s。 */
import { defineComponent } from 'vue';
import { pick, type MicroBuild } from './types';

const ROWS = [24, 44, 64, 84];
export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out' } });
  tl.from(pick(svg, 'row'), { x: -8, opacity: 0, duration: 0.28, stagger: 0.06 }, 0);
  tl.fromTo(pick(svg, 'scan'), { y: 4 }, { y: 92, duration: 0.8, ease: 'none' }, 0.2);
  pick(svg, 'badge').forEach((badge, i) => {
    const t = 0.2 + ((ROWS[i]! - 4 - 4) / 88) * 0.8;
    tl.from(badge, { scale: 0.6, opacity: 0, duration: 0.16, transformOrigin: '50% 50%' }, t);
  });
  return tl;
};
export default defineComponent({ name: 'MicroInventory' });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <g data-m="row">
      <path class="m-s m-thin" d="M8 13h7l3 3v9H8z" />
      <text class="m-t" x="24" y="24">施工合同</text>
    </g>
    <g data-m="row">
      <path class="m-s m-thin" d="M8 33h7l3 3v9H8z" />
      <text class="m-t" x="24" y="44">结算送审书</text>
    </g>
    <g data-m="row">
      <path class="m-s m-thin" d="M8 53h7l3 3v9H8z" />
      <text class="m-t" x="24" y="64">竣工图</text>
    </g>
    <g data-m="row">
      <path class="m-s m-thin" d="M8 73h7l3 3v9H8z" />
      <text class="m-t" x="24" y="84">审核汇总表</text>
    </g>
    <g data-m="badge">
      <rect class="m-bg-ok" x="120" y="12" width="32" height="16" rx="3" />
      <text class="m-t m-ok" x="136" y="24" text-anchor="middle">已备</text>
    </g>
    <g data-m="badge">
      <rect class="m-bg-ok" x="120" y="32" width="32" height="16" rx="3" />
      <text class="m-t m-ok" x="136" y="44" text-anchor="middle">已备</text>
    </g>
    <g data-m="badge">
      <rect class="m-bg-warn" x="110" y="52" width="42" height="16" rx="3" />
      <text class="m-t m-warn" x="131" y="64" text-anchor="middle">待确认</text>
    </g>
    <g data-m="badge">
      <rect class="m-bg-danger" x="120" y="72" width="32" height="16" rx="3" />
      <text class="m-t m-danger" x="136" y="84" text-anchor="middle">缺失</text>
    </g>
    <line class="m-scan" data-m="scan" x1="0" y1="0" x2="160" y2="0" transform="translate(0 92)" />
  </svg>
</template>
