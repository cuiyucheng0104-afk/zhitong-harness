<script lang="ts">
/** 清单待核项（03 章 §1.5.7 `codes`）：两行编码展开，闸线扫过时“待核”与勾依次弹出；行 2 编码不变。约 1.5s。 */
import { defineComponent } from 'vue';
import { pick, type MicroBuild } from './types';

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out' } });
  tl.fromTo(
    pick(svg, 'row'),
    { clipPath: 'inset(0 100% 0 0)' },
    { clipPath: 'inset(0 0% 0 0)', duration: 0.45, stagger: 0.15, clearProps: 'clipPath' },
    0,
  );
  tl.fromTo(pick(svg, 'gate'), { x: 4 }, { x: 156, duration: 0.6, ease: 'none' }, 0.6);
  tl.from(pick(svg, 'pending'), { scale: 0.6, opacity: 0, transformOrigin: '50% 50%', duration: 0.16 }, 0.97);
  tl.from(pick(svg, 'ok'), { scale: 0.6, opacity: 0, transformOrigin: '50% 50%', duration: 0.16 }, 1.16);
  tl.from(pick(svg, 'hint'), { opacity: 0, duration: 0.28 }, 1.25);
  return tl;
};
export default defineComponent({ name: 'MicroCodes' });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <g data-m="row">
      <text class="m-t m-mono" x="8" y="24">011102003</text>
      <text class="m-t" x="80" y="24">块料楼地面</text>
    </g>
    <path class="m-ok-s" data-m="ok" d="M141 20L144.5 23.5L151 17" />
    <g data-m="row">
      <text class="m-t m-mono" x="8" y="52">Z011201001</text>
      <text class="m-t" x="84" y="52">踢脚</text>
    </g>
    <g data-m="pending">
      <rect class="m-bg-warn" x="116" y="40" width="32" height="16" rx="3" />
      <text class="m-t m-warn" x="132" y="52" text-anchor="middle">待核</text>
    </g>
    <text class="m-t m-muted" data-m="hint" x="8" y="78">建议：踢脚线</text>
    <line class="m-s m-dash m-blue-s" data-m="gate" x1="0" y1="8" x2="0" y2="64" transform="translate(156 0)" />
  </svg>
</template>
