<script lang="ts">
/** 送审审定核对（03 章 §1.5.7 `reconcile`）：两表描边、相向合拢、金额滚到 906,692.96。约 2.0s。 */
import { defineComponent } from 'vue';
import { formatMoney, formatPercent } from '../../../lib/format';
import { ROLE_FIGURES } from '../../../data/roles';
import { hold, pick, type MicroBuild } from './types';

export const AMOUNT = formatMoney(ROLE_FIGURES.reduction);
export const RATE = formatPercent(ROLE_FIGURES.reductionRate);

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out' } });
  tl.from(pick(svg, 'stroke'), { drawSVG: '0%', duration: 0.45 }, 0);
  const [left] = pick(svg, 'left');
  const [right] = pick(svg, 'right');
  const mid = pick(svg, 'mid');
  hold(tl, mid, { opacity: 1 });
  tl.fromTo(left!, { x: 0 }, { x: 16, duration: 0.4, ease: 'power2.inOut' }, 0.45);
  tl.fromTo(right!, { x: 0 }, { x: -16, duration: 0.4, ease: 'power2.inOut' }, 0.45);
  tl.fromTo(mid, { scaleY: 1, svgOrigin: '80 24' }, { scaleY: 0, svgOrigin: '80 24', duration: 0.4, ease: 'power2.inOut' }, 0.45);
  tl.from(pick(svg, 'hl'), { opacity: 0, duration: 0.16 }, 0.85);
  tl.from(pick(svg, 'row1'), { opacity: 0, duration: 0.16 }, 0.95);
  const [amount] = pick(svg, 'amount');
  const proxy = { v: 0 };
  tl.fromTo(
    proxy,
    { v: 0 },
    {
      v: ROLE_FIGURES.reduction,
      duration: 0.8,
      ease: 'expo.out',
      onUpdate: () => {
        if (amount) amount.textContent = formatMoney(proxy.v);
      },
      onComplete: () => {
        if (amount) amount.textContent = AMOUNT;
      },
    },
    0.95,
  );
  tl.from(pick(svg, 'row2'), { opacity: 0, duration: 0.28 }, 1.75);
  return tl;
};
export default defineComponent({ name: 'MicroReconcile', setup: () => ({ AMOUNT, RATE }) });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <g data-m="left" transform="translate(16 0)">
      <rect class="m-bg-blue" data-m="hl" x="4" y="27" width="68" height="8" />
      <rect class="m-s" data-m="stroke" x="4" y="4" width="68" height="40" />
      <path class="m-s m-thin" data-m="stroke" d="M4 19H72M4 27H72M4 35H72" />
      <text class="m-t" x="38" y="16" text-anchor="middle">送审</text>
    </g>
    <g data-m="right" transform="translate(-16 0)">
      <rect class="m-bg-blue" data-m="hl" x="88" y="27" width="68" height="8" />
      <rect class="m-s" data-m="stroke" x="88" y="4" width="68" height="40" />
      <path class="m-s m-thin" data-m="stroke" d="M88 19H156M88 27H156M88 35H156" />
      <text class="m-t" x="122" y="16" text-anchor="middle">审定</text>
    </g>
    <line class="m-s m-dash" data-m="mid" x1="80" y1="4" x2="80" y2="44" opacity="0" />
    <text class="m-t" data-m="row1" x="4" y="66">核减 <tspan class="m-mono m-reduce" data-m="amount">{{ AMOUNT }}</tspan></text>
    <text class="m-t" data-m="row2" x="4" y="86"><tspan class="m-mono">{{ RATE }}</tspan> · <tspan class="m-warn">需人工确认</tspan></text>
  </svg>
</template>
