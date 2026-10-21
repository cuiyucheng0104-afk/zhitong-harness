<script lang="ts">
/** 接手项目问答（03 章 §1.5.7 `answer`）：提问、读取单份文件、回答与出处签。约 1.7s。 */
import { defineComponent } from 'vue';
import { pick, type MicroBuild } from './types';

export const build: MicroBuild = (svg, gsap) => {
  const tl = gsap.timeline({ paused: true, defaults: { ease: 'power3.out', duration: 0.28 } });
  tl.from(pick(svg, 'ask'), { x: 8, opacity: 0 }, 0);
  tl.from(pick(svg, 'read'), { opacity: 0 }, 0.35);
  tl.from(pick(svg, 'progress'), { scaleX: 0, transformOrigin: '0% 50%', duration: 0.6, ease: 'none' }, 0.35);
  tl.from(pick(svg, 'reply'), { opacity: 0 }, 1.0);
  tl.from(pick(svg, 'bar'), { scaleX: 0, transformOrigin: '0% 50%', stagger: 0.1 }, 1.0);
  tl.from(pick(svg, 'cite'), { scale: 0.8, opacity: 0, transformOrigin: '0% 50%' }, 1.4);
  return tl;
};
export default defineComponent({ name: 'MicroAnswer' });
</script>

<template>
  <svg class="micro" viewBox="0 0 160 96" aria-hidden="true" focusable="false">
    <g data-m="ask">
      <rect class="m-bg-blue" x="48" y="4" width="108" height="20" rx="6" />
      <text class="m-t" x="54" y="18">合同的付款节点？</text>
    </g>
    <g data-m="read">
      <path class="m-s m-thin m-muted-s" d="M6 33h6l3 3v8H6z" />
      <text class="m-t m-muted" x="20" y="43">施工合同…docx</text>
    </g>
    <rect class="m-progress" data-m="progress" x="4" y="47.5" width="116" height="1" />
    <rect class="m-page" data-m="reply" x="4" y="54" width="152" height="38" rx="6" />
    <rect class="m-bar" data-m="bar" x="10" y="62" width="120" height="4" />
    <rect class="m-bar" data-m="bar" x="10" y="72" width="88" height="4" />
    <text class="m-t m-blue" data-m="cite" x="10" y="88">〔…协议.docx 段12〕</text>
  </svg>
</template>
