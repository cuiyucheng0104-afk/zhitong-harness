<script lang="ts">
/** 报告撰写（03 章 §1.5.7 `draft`）：初稿页、灰条逐行出现、事实编号换成金额、待核标记。约 1.9s。 */
import { defineComponent } from 'vue';
import { formatMoney } from '../../../lib/format';
import { ROLE_FIGURES } from '../../../data/roles';
import { pick, type MicroBuild } from './types';

export const TOTAL = formatMoney(ROLE_FIGURES.submittedTotal);

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out', duration: 0.28 } });
  tl.from(pick(svg, 'page'), { y: 6, opacity: 0 }, 0);
  tl.from(pick(svg, 'ai'), { opacity: 0 }, 0.2);
  tl.from(pick(svg, 'bar'), { scaleX: 0, transformOrigin: '0% 50%', stagger: 0.12 }, 0.3);
  tl.from(pick(svg, 'cite'), { scale: 0.6, opacity: 0, transformOrigin: '50% 50%' }, 0.6);
  const f1 = pick(svg, 'f1');
  tl.fromTo(f1, { opacity: 0 }, { opacity: 1 }, 0.9);
  tl.to(f1, { opacity: 0 }, 1.3);
  tl.from(pick(svg, 'amount'), { opacity: 0 }, 1.3);
  tl.from(pick(svg, 'pending'), { opacity: 0 }, 1.6);
  return tl;
};
export default defineComponent({ name: 'MicroDraft', setup: () => ({ TOTAL }) });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <rect class="m-page" data-m="page" x="28" y="2" width="104" height="92" rx="2" />
    <text class="m-t m-warn" data-m="ai" x="36" y="16">AI 初稿</text>
    <rect class="m-bar" data-m="bar" x="36" y="24" width="88" height="4" />
    <rect class="m-bar" data-m="bar" x="36" y="36" width="40" height="4" />
    <rect class="m-bar" data-m="bar" x="36" y="68" width="44" height="4" />
    <rect class="m-bar" data-m="bar" x="36" y="80" width="74" height="4" />
    <text class="m-t m-blue" data-m="cite" x="78" y="42">[资料3]</text>
    <text class="m-t m-mono" data-m="f1" x="36" y="58" opacity="0">〔F1〕</text>
    <text class="m-t m-mono" data-m="amount" x="36" y="58">{{ TOTAL }}</text>
    <text class="m-t m-warn" data-m="pending" x="82" y="74">【待核】</text>
  </svg>
</template>
