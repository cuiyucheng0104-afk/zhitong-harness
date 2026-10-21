<script lang="ts">
/** 火山引擎运维（03 章 §1.5.7 `ops`）：预演命令、确认卡、选择“执行”后显示结果。约 2.2s。 */
import { defineComponent } from 'vue';
import { hold, pick, type MicroBuild } from './types';

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out', duration: 0.28 } });
  const card = pick(svg, 'card');
  const cursor = pick(svg, 'cursor');
  tl.from(pick(svg, 'term'), { opacity: 0 }, 0);
  tl.fromTo(
    pick(svg, 'l1'),
    { clipPath: 'inset(0 100% 0 0)' },
    { clipPath: 'inset(0 0% 0 0)', duration: 0.5, ease: 'steps(20)', clearProps: 'clipPath' },
    0.15,
  );
  tl.from(pick(svg, 'l2'), { opacity: 0 }, 0.7);
  hold(tl, cursor, { opacity: 0, x: 150, y: 94 });
  tl.fromTo(card, { y: 10, opacity: 0 }, { y: 0, opacity: 1 }, 0.95);
  tl.set(cursor, { opacity: 1 }, 1.3);
  tl.to(cursor, { x: 50, y: 80, duration: 0.4, ease: 'power2.inOut' }, 1.3);
  tl.to(pick(svg, 'run'), { scale: 0.94, svgOrigin: '50 79', duration: 0.12 }, 1.7);
  tl.to([...card, ...cursor], { opacity: 0, duration: 0.16 }, 1.85);
  tl.from(pick(svg, 'l3'), { opacity: 0 }, 1.95);
  return tl;
};
export default defineComponent({ name: 'MicroOps' });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <rect class="m-term" data-m="term" x="0" y="0" width="160" height="56" rx="6" />
    <text class="m-t m-mono m-term-dim" data-m="l1" x="8" y="18">sg-sync-ip --dry-run</text>
    <text class="m-t m-term-ok" data-m="l2" x="8" y="34"><tspan class="m-mono">+22/tcp</tspan> 本机公网 IP</text>
    <text class="m-t m-mono m-term-ok" data-m="l3" x="8" y="50">changed: true</text>
    <g data-m="card" opacity="0">
      <rect class="m-page" x="24" y="60" width="112" height="34" rx="4" />
      <g data-m="run">
        <rect class="m-btn-primary" x="32" y="70" width="36" height="18" rx="4" />
        <text class="m-t m-white" x="50" y="83" text-anchor="middle">执行</text>
      </g>
      <rect class="m-btn" x="76" y="70" width="48" height="18" rx="4" />
      <text class="m-t" x="100" y="83" text-anchor="middle">不执行</text>
    </g>
    <path class="m-cursor" data-m="cursor" opacity="0" d="M0 0V14L3.6 10.6L6.2 14.6L8.4 13.4L5.8 9.6H10Z" />
  </svg>
</template>
