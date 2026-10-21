<script setup lang="ts">
/**
 * 7.8 概算编制辅助。引文高亮矩形的 x 与宽按估算宽度预渲染；构建时由时间线用
 * `getComputedTextLength()` 量出 `tspan[data-q]` 的实际位置后改写（timelines/estimate.ts）。
 */
import { A } from './anim';
import ArtFile from './parts/ArtFile.vue';
import ArtChip from './parts/ArtChip.vue';
import ArtLink from './parts/ArtLink.vue';
import ArtPointer from './parts/ArtPointer.vue';
import { textWidth } from '../art-tokens';

/** 原文 7 行：每行若干片段，`q` 为引文标识（同一引文可跨两行）。 */
const lines: { y: number; parts: { t: string; q?: string }[] }[] = [
  { y: 46, parts: [{ t: '总用地面积 6850㎡', q: 'D4' }] },
  { y: 68, parts: [{ t: '建筑占地面积 2740㎡', q: 'D15' }, { t: '，建筑密度 40%' }] },
  { y: 90, parts: [{ t: '机动车停车位 110 辆，其中' }, { t: '地面停车位', q: 'D19a' }] },
  { y: 112, parts: [{ t: '24 辆', q: 'D19b' }, { t: '，' }, { t: '地下停车位 86 辆', q: 'D20' }] },
  { y: 134, parts: [{ t: '办公楼 地上 15 层 建筑面积 15200㎡', q: 'D10' }] },
  { y: 156, parts: [{ t: '地下室 地下 1 层 建筑面积 3400㎡', q: 'D7' }] },
  { y: 178, parts: [{ t: '总建筑面积 18600㎡', q: 'T' }, { t: ' ……' }] },
];
const highlights = lines.flatMap((line) => {
  let x = 8;
  const out: { q: string; x: number; w: number; y: number }[] = [];
  for (const p of line.parts) {
    const w = textWidth(p.t);
    if (p.q) out.push({ q: p.q, x: x - 2, w: w + 4, y: line.y - 14 });
    x += w;
  }
  return out;
});
const rows = [
  { cell: 'D4', name: '用地面积', v: '6,850.00' },
  { cell: 'D7', name: 'A区地下室', v: '3,400.00' },
  { cell: 'D10', name: '1#楼', v: '15,200.00' },
  { cell: 'D15', name: 'A区地块', v: '2,740.00' },
  { cell: 'D19', name: '地面机动车停车', v: '24' },
  { cell: 'D20', name: '地下机动车停车', v: '86' },
];
const fxPrefix = textWidth('ƒx C46 =(C5+C45)*J46 · ', true);
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <ArtFile a="hdr" :y="16" name="竣工图总说明.pdf · 经济技术指标" kind="pdf" cls="ah" />
    <rect v-bind="A('page')" x="0" y="26" width="264" height="174" rx="4" class="art-card" />
    <rect
      v-for="h in highlights"
      :key="h.q"
      v-bind="A(`hl-${h.q}`)"
      :data-hl="h.q"
      :class="h.q === 'T' ? 'art-hl-total' : 'art-hl'"
      :x="h.x"
      :y="h.y"
      :width="h.w"
      height="18"
    />
    <text
      v-for="(line, k) in lines"
      :key="line.y"
      v-bind="A(`ln${k + 1}`)"
      class="at"
      x="8"
      :y="line.y"
    >
      <tspan v-for="p in line.parts" :key="p.t" :data-q="p.q">{{ p.t }}</tspan>
    </text>
    <ArtChip a="chk" :x="196" :top="164" text="合计相符" variant="ok" />
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <text v-bind="A('o-hdr')" class="ah" x="0" y="16">经济技术指标 · 11 个必填位</text>
    <g v-for="(r, k) in rows" :key="r.cell" v-bind="A(`or${k + 1}`)">
      <rect
        v-bind="A(`ob${k + 1}`, true)"
        class="art-cand"
        :x="258 - textWidth(r.v, true)"
        :y="25 + 20 * k"
        :width="textWidth(r.v, true) + 12"
        height="20"
        rx="4"
      />
      <text class="am" x="0" :y="40 + 20 * k">{{ r.cell }}</text>
      <text class="at" x="34" :y="40 + 20 * k">{{ r.name }}</text>
      <text class="am" x="264" :y="40 + 20 * k" text-anchor="end">{{ r.v }}</text>
    </g>
    <text v-bind="A('o-rest-a', true)" class="as" x="0" y="162">其余 5 位：原文未找到</text>
    <text v-bind="A('o-rest')" class="as" x="0" y="162">其余 5 位：您确认为 0</text>
    <g v-bind="A('o-fx')">
      <rect x="0" y="172" width="264" height="26" rx="4" class="art-fx" />
      <rect
        v-bind="A('o-fx-hl', true)"
        :x="8 + fxPrefix - 2"
        y="176"
        :width="textWidth('J46 5%', true) + 4"
        height="18"
        rx="2"
        fill="var(--blue-tint)"
      />
      <text class="am" x="8" y="190">ƒx C46 =(C5+C45)*J46 · J46 5%</text>
    </g>
    <g v-bind="A('ask', true)">
      <rect x="20" y="46" width="224" height="86" rx="8" class="art-card art-shadow" />
      <text class="ah" x="34" y="72">确认这些规模量？</text>
      <text class="as" x="34" y="92">6 个候选 · 5 个未找到填 0</text>
      <rect x="34" y="102" width="64" height="22" rx="6" fill="var(--brand-blue)" />
      <text class="at art-on-blue" text-anchor="middle" x="66" y="118">确认</text>
      <rect x="106" y="102" width="64" height="22" rx="6" class="art-btn-ghost" />
      <text class="at" text-anchor="middle" x="138" y="118">修改</text>
    </g>
    <ArtPointer :x="150" :y="170" />
  </svg>
</template>
