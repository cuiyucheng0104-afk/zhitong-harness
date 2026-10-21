<script lang="ts">
/** 指标偏差复核（03 章 §1.5.7 `benchmark`）：比例尺、同类区间、本项目点落定在 1,592.67。约 1.8s。 */
import { defineComponent } from 'vue';
import { formatMoney } from '../../../lib/format';
import { ROLE_FIGURES } from '../../../data/roles';
import { pick, type MicroBuild } from './types';

export const UNIT = formatMoney(ROLE_FIGURES.approvedUnit);
const TICKS = Array.from({ length: 10 }, (_, i) => 8 + i * 16);

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out', duration: 0.28 } });
  tl.from(pick(svg, 'axis'), { drawSVG: '0%', duration: 0.45 }, 0);
  tl.from(pick(svg, 'tick'), { opacity: 0, stagger: 0.02 }, 0.2);
  tl.from(pick(svg, 'band'), { scaleX: 0, transformOrigin: '50% 50%' }, 0.45);
  tl.from(pick(svg, 'peer'), { scale: 0, transformOrigin: '50% 50%', stagger: 0.06 }, 0.55);
  tl.fromTo(pick(svg, 'self'), { x: 8 }, { x: 84, duration: 0.8, ease: 'expo.out' }, 0.8);
  tl.from(pick(svg, 'top'), { opacity: 0 }, 1.3);
  tl.from(pick(svg, 'foot'), { opacity: 0 }, 1.5);
  return tl;
};
export default defineComponent({ name: 'MicroBenchmark', setup: () => ({ UNIT, TICKS }) });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <text class="m-t m-muted" data-m="top" x="84" y="24" text-anchor="middle">审定单方（土建）</text>
    <text class="m-t" data-m="top" x="84" y="40" text-anchor="middle"><tspan class="m-mono">{{ UNIT }}</tspan> 元/m²</text>
    <rect class="m-bg-blue" data-m="band" x="64" y="54" width="48" height="12" />
    <path class="m-s" data-m="axis" d="M8 60H152" />
    <line
      v-for="x in TICKS"
      :key="x"
      class="m-s m-thin"
      data-m="tick"
      :x1="x"
      :x2="x"
      y1="60"
      :y2="(x - 8) % 48 === 0 ? 66 : 63"
    />
    <circle class="m-peer" data-m="peer" cx="68" cy="60" r="3" />
    <circle class="m-peer" data-m="peer" cx="90" cy="60" r="3" />
    <circle class="m-peer" data-m="peer" cx="108" cy="60" r="3" />
    <circle class="m-self" data-m="self" cx="0" cy="60" r="4" transform="translate(84 0)" />
    <text class="m-t" data-m="foot" x="8" y="86">同类对标 · <tspan class="m-warn">需人工确认</tspan></text>
  </svg>
</template>
