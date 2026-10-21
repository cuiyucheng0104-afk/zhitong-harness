<script lang="ts">
/** 看图结果核对（03 章 §1.5.7 `plan`）：平面线绘出、局部放大到会议室、轮廓与标签条。约 2.0s。 */
import { defineComponent } from 'vue';
import { pick, type MicroBuild } from './types';

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out' } });
  tl.from(pick(svg, 'wall'), { drawSVG: '0%', duration: 0.6, stagger: 0.04 }, 0);
  const labels = pick(svg, 'label');
  tl.fromTo(labels, { opacity: 0 }, { opacity: 1, duration: 0.28 }, 0.3);
  tl.fromTo(
    pick(svg, 'zoom'),
    { scale: 1, svgOrigin: '80 36' },
    { scale: 2, svgOrigin: '80 36', duration: 0.5, ease: 'power2.inOut' },
    0.8,
  );
  tl.to(labels, { opacity: 0, duration: 0.5, ease: 'power2.inOut' }, 0.8);
  tl.from(pick(svg, 'room'), { drawSVG: '0%', duration: 0.45 }, 1.3);
  tl.from(pick(svg, 'strip'), { y: 6, opacity: 0, duration: 0.28 }, 1.7);
  return tl;
};
export default defineComponent({ name: 'MicroPlan' });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <defs>
      <clipPath id="micro-plan-clip"><rect x="0" y="0" width="160" height="80" /></clipPath>
    </defs>
    <g clip-path="url(#micro-plan-clip)">
      <g data-m="zoom" transform="matrix(2 0 0 2 -80 -36)">
        <rect class="m-s" data-m="wall" vector-effect="non-scaling-stroke" x="20" y="16" width="120" height="64" />
        <path class="m-s" data-m="wall" vector-effect="non-scaling-stroke" d="M60 16V80" />
        <path class="m-s" data-m="wall" vector-effect="non-scaling-stroke" d="M100 16V56H140" />
        <g data-m="label" opacity="0">
          <text class="m-t m-muted" x="40" y="12" text-anchor="middle">A</text>
          <text class="m-t m-muted" x="80" y="12" text-anchor="middle">B</text>
          <text class="m-t m-muted" x="120" y="12" text-anchor="middle">C</text>
          <text class="m-t m-muted" x="12" y="40" text-anchor="middle">1</text>
          <text class="m-t m-muted" x="12" y="72" text-anchor="middle">2</text>
        </g>
      </g>
      <rect class="m-room" data-m="room" x="40" y="-4" width="80" height="128" />
    </g>
    <g data-m="strip">
      <rect class="m-page" x="24" y="80" width="112" height="16" />
      <text class="m-t" x="80" y="92" text-anchor="middle">会议室 · <tspan class="m-warn">需人工确认</tspan></text>
    </g>
  </svg>
</template>
