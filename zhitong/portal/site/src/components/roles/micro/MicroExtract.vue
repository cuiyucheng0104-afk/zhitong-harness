<script lang="ts">
/** 概算编制（03 章 §1.5.7 `extract`）：原文下划线、数值沿弧线落入输入格、确认后显示 fx。约 2.0s。 */
import { defineComponent } from 'vue';
import { formatMoney } from '../../../lib/format';
import { ROLE_FIGURES } from '../../../data/roles';
import { hold, pick, type MicroBuild } from './types';

export const AREA = formatMoney(ROLE_FIGURES.aboveGround);

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out' } });
  const fly = pick(svg, 'fly');
  const st1 = pick(svg, 'st1');
  tl.from(pick(svg, 'band'), { opacity: 0, duration: 0.28 }, 0);
  tl.from(pick(svg, 'underline'), { drawSVG: '0%', duration: 0.45 }, 0.3);
  hold(tl, fly, { opacity: 0, x: 52, y: 34 });
  tl.set(fly, { opacity: 1 }, 0.75);
  tl.to(
    fly,
    {
      motionPath: { path: [{ x: 52, y: 34 }, { x: 82, y: 44 }, { x: 110, y: 72 }], curviness: 1 },
      duration: 0.6,
      ease: 'power2.inOut',
    },
    0.75,
  );
  tl.set(fly, { opacity: 0 }, 1.35);
  tl.from(pick(svg, 'value'), { opacity: 0, duration: 0.01 }, 1.35);
  tl.fromTo(st1, { opacity: 0 }, { opacity: 1, duration: 0.28 }, 1.35);
  tl.to(st1, { opacity: 0, duration: 0.28 }, 1.7);
  tl.from(pick(svg, 'st2'), { opacity: 0, duration: 0.28 }, 1.7);
  tl.from(pick(svg, 'okframe'), { opacity: 0, duration: 0.28 }, 1.7);
  tl.from(pick(svg, 'fx'), { opacity: 0, duration: 0.28 }, 1.7);
  return tl;
};
export default defineComponent({ name: 'MicroExtract', setup: () => ({ AREA }) });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <g data-m="band">
      <rect class="m-bg-canvas" x="4" y="4" width="152" height="36" rx="3" />
      <text class="m-t" x="8" y="18">地上建筑面积</text>
      <text class="m-t m-mono" x="8" y="34">{{ AREA }} m²</text>
    </g>
    <path class="m-s m-blue-s" data-m="underline" d="M8 37H96" />
    <rect class="m-cell" x="24" y="56" width="112" height="24" rx="3" />
    <rect class="m-cell m-cell-ok" data-m="okframe" x="24" y="56" width="112" height="24" rx="3" />
    <text class="m-t m-muted" x="28" y="72">地上面积</text>
    <text class="m-t m-mono" data-m="value" x="132" y="72" text-anchor="end">{{ AREA }}</text>
    <text class="m-t m-mono m-muted" data-m="fx" x="140" y="72">fx</text>
    <text class="m-t m-mono m-blue" data-m="fly" x="0" y="0" text-anchor="middle" opacity="0">{{ AREA }}</text>
    <text class="m-t m-muted" data-m="st1" x="8" y="92" opacity="0">引文已回查 · 待您确认</text>
    <text class="m-t m-ok" data-m="st2" x="8" y="92">已确认</text>
  </svg>
</template>
