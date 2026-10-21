<script lang="ts">
/** 归档与案例索引（03 章 §1.5.7 `archive`）：两目录打勾、沿箭头推送回桶、回读、索引追加一行。约 1.7s。 */
import { defineComponent } from 'vue';
import { pick, type MicroBuild } from './types';

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out', duration: 0.28 } });
  const [arrow] = pick(svg, 'arrow');
  const dots = pick(svg, 'dot');
  tl.from(pick(svg, 'folder'), { opacity: 0, stagger: 0.08 }, 0);
  tl.from(pick(svg, 'tick'), { scale: 0.6, opacity: 0, transformOrigin: '50% 50%', stagger: 0.1 }, 0.3);
  tl.from(arrow!, { drawSVG: '0%', duration: 0.4 }, 0.55);
  tl.set(dots, { opacity: 1 }, 0.65);
  tl.to(
    dots,
    {
      motionPath: { path: arrow as SVGPathElement, align: arrow as SVGPathElement, alignOrigin: [0.5, 0.5] },
      duration: 0.5,
      ease: 'power2.inOut',
      stagger: 0.08,
    },
    0.65,
  );
  tl.to(dots, { opacity: 0, duration: 0.01, stagger: 0.08 }, 1.15);
  tl.from(pick(svg, 'readback'), { opacity: 0 }, 1.2);
  tl.from(pick(svg, 'index'), { y: 8, opacity: 0 }, 1.4);
  return tl;
};
export default defineComponent({ name: 'MicroArchive' });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <g data-m="folder">
      <path class="m-s m-fill" d="M8 12H24L28 16H56V34H8Z" />
      <text class="m-t" x="14" y="29">工作/</text>
    </g>
    <g data-m="folder">
      <path class="m-s m-fill" d="M8 44H24L28 48H56V66H8Z" />
      <text class="m-t" x="14" y="61">成果/</text>
    </g>
    <path class="m-ok-s" data-m="tick" d="M60 22L63 25L69 19" />
    <path class="m-ok-s" data-m="tick" d="M60 54L63 57L69 51" />
    <path class="m-s m-blue-s" data-m="arrow" d="M70 38C90 38 96 30 112 30" />
    <circle class="m-dot" data-m="dot" cx="0" cy="0" r="1.5" opacity="0" />
    <circle class="m-dot" data-m="dot" cx="0" cy="0" r="1.5" opacity="0" />
    <circle class="m-dot" data-m="dot" cx="0" cy="0" r="1.5" opacity="0" />
    <path class="m-s m-fill" d="M112 18V54A20 4 0 0 0 152 54V18Z" />
    <ellipse class="m-s m-fill" cx="132" cy="18" rx="20" ry="4" />
    <text class="m-t m-ok" data-m="readback" x="112" y="70">回读 ✓</text>
    <g data-m="index">
      <rect class="m-bg-canvas" x="4" y="78" width="152" height="16" rx="2" />
      <text class="m-t" x="8" y="90"><tspan class="m-mono">2026-007</tspan> 某综合办公楼</text>
    </g>
  </svg>
</template>
