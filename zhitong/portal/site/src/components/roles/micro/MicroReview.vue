<script lang="ts">
/** 投控异常复核（03 章 §1.5.7 `review`）：疑似异常卡、光标点“确认”、印章、复核记录 +1。约 1.65s。 */
import { defineComponent } from 'vue';
import { hold, pick, type MicroBuild } from './types';

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out', duration: 0.28 } });
  const cursor = pick(svg, 'cursor');
  const confirm = pick(svg, 'confirm');
  tl.from(pick(svg, 'card'), { x: 8, opacity: 0 }, 0);
  tl.from(pick(svg, 'btn'), { opacity: 0 }, 0.25);
  hold(tl, cursor, { x: 150, y: 92 });
  tl.to(
    cursor,
    {
      motionPath: { path: [{ x: 150, y: 92 }, { x: 104, y: 88 }, { x: 58, y: 70 }], curviness: 1 },
      duration: 0.5,
      ease: 'power2.inOut',
    },
    0.45,
  );
  tl.to(confirm, { scale: 0.94, svgOrigin: '58 70', duration: 0.12 }, 0.95);
  tl.to(confirm, { scale: 1, svgOrigin: '58 70', duration: 0.12 }, 1.07);
  tl.from(pick(svg, 'confirm-bg'), { opacity: 0, duration: 0.12 }, 0.95);
  tl.from(pick(svg, 'stamp'), { scale: 1.3, opacity: 0, transformOrigin: '50% 50%' }, 1.1);
  tl.from(pick(svg, 'log'), { y: 6, opacity: 0 }, 1.35);
  return tl;
};
export default defineComponent({ name: 'MicroReview' });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <g data-m="card">
      <rect class="m-page" x="4" y="8" width="152" height="44" rx="6" />
      <path class="m-warn-s" d="M18 17L24 28H12ZM18 21.5V24.5M18 26.2V26.6" />
      <text class="m-t m-strong" x="30" y="26">疑似重复计取</text>
      <text class="m-t m-muted" x="30" y="44">送审计价表.xlsx</text>
    </g>
    <g data-m="stamp">
      <rect class="m-bg-ok" x="116" y="12" width="36" height="16" rx="3" />
      <text class="m-t m-ok" x="134" y="24" text-anchor="middle">已确认</text>
    </g>
    <g data-m="btn">
      <g data-m="confirm">
        <rect class="m-btn" x="40" y="60" width="36" height="20" rx="4" />
        <rect class="m-bg-blue" data-m="confirm-bg" x="40.5" y="60.5" width="35" height="19" rx="4" />
        <text class="m-t" x="58" y="74" text-anchor="middle">确认</text>
      </g>
      <rect class="m-btn" x="84" y="60" width="36" height="20" rx="4" />
      <text class="m-t" x="102" y="74" text-anchor="middle">误报</text>
    </g>
    <text class="m-t m-mono" data-m="log" x="4" y="94">复核.jsonl +1</text>
    <path class="m-cursor" data-m="cursor" transform="translate(58 70)" d="M0 0V14L3.6 10.6L6.2 14.6L8.4 13.4L5.8 9.6H10Z" />
  </svg>
</template>
