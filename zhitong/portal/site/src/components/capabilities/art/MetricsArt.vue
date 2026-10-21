<script setup lang="ts">
/** 7.6 造价指标：数轴 x = 12 + (v − 1560) / 140 × 240。 */
import { A } from './anim';
import ArtLink from './parts/ArtLink.vue';

const shares = [
  { l: '混凝土', w: 98.4, v: '61.49%' },
  { l: '措施项目', w: 21.6, v: '13.47%' },
  { l: '门窗', w: 15.9, v: '9.95%' },
];
const ticks = [
  { x: 80.6, v: '1,600' },
  { x: 149.1, v: '1,640' },
  { x: 217.7, v: '1,680' },
];
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <text v-bind="A('hdr')" class="ah" x="0" y="16">indicator.py run</text>
    <g v-bind="A('i-t')">
      <text class="as" x="0" y="42">清单明细合计</text>
      <text data-a="i-t-v" class="am" x="264" y="42" text-anchor="end">29,623,713.84</text>
    </g>
    <g v-bind="A('i-a')">
      <text class="as" x="0" y="64">建筑面积</text>
      <text data-a="i-a-v" data-suffix=" m²" class="am" x="200" y="64" text-anchor="end">
        18,600.00 m²
      </text>
      <text class="as" x="264" y="64" text-anchor="end">项目说明</text>
    </g>
    <line
      v-bind="A('rule')"
      x1="0"
      y1="78"
      x2="264"
      y2="78"
      stroke="var(--grid-line-strong)"
      stroke-width="1"
    />
    <g v-bind="A('i-u')">
      <text data-a="i-u-v" class="ab" x="0" y="108">1,592.67</text>
      <text class="at" x="112" y="108">元/m²</text>
    </g>
    <text v-bind="A('i-ul')" class="as" x="0" y="128">清单明细合计口径，不是总造价</text>
    <g v-for="(s, k) in shares" :key="s.l">
      <text v-bind="A(`sl${k + 1}`)" class="as" x="0" :y="152 + 18 * k">{{ s.l }}</text>
      <rect
        v-bind="A(`sb${k + 1}`)"
        x="62"
        :y="142 + 18 * k"
        :width="s.w"
        height="8"
        fill="var(--brand-blue)"
      />
      <text v-bind="A(`sv${k + 1}`)" class="am" x="264" :y="152 + 18 * k" text-anchor="end">
        {{ s.v }}
      </text>
    </g>
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <text v-bind="A('o-hdr')" class="ah" x="0" y="16">同类对标 · 案例索引.md</text>
    <g v-bind="A('p1')">
      <text class="at" x="0" y="42">某科创中心一期</text>
      <text class="am" x="264" y="42" text-anchor="end">1,688.40</text>
    </g>
    <g v-bind="A('p2')">
      <text class="at" x="0" y="64">某政务服务中心</text>
      <text class="am" x="264" y="64" text-anchor="end">1,571.20</text>
    </g>
    <line
      v-bind="A('ax')"
      x1="12"
      y1="120"
      x2="252"
      y2="120"
      stroke="var(--ink)"
      stroke-width="1"
    />
    <g v-for="t in ticks" :key="t.v">
      <line
        v-bind="A('tk')"
        :x1="t.x"
        y1="117"
        :x2="t.x"
        y2="123"
        stroke="var(--ink)"
        stroke-width="1"
      />
      <text v-bind="A('tk')" class="as" text-anchor="middle" :x="t.x" y="140">{{ t.v }}</text>
    </g>
    <circle v-bind="A('d1')" cx="31.2" cy="120" r="4" fill="var(--text-muted)" />
    <circle v-bind="A('d2')" cx="232.1" cy="120" r="4" fill="var(--text-muted)" />
    <line v-bind="A('avg')" data-dashed x1="131.7" y1="104" x2="131.7" y2="128" class="art-avg" />
    <text v-bind="A('avg-l')" class="as" text-anchor="middle" x="131.7" y="98">均值 1,629.80</text>
    <circle v-bind="A('me')" cx="68" cy="120" r="6" fill="var(--brand-blue)" />
    <text v-bind="A('me-l')" class="at" text-anchor="middle" x="68" y="158">本项目</text>
    <text v-bind="A('dev')" x="0" y="184">
      <tspan class="at">偏差</tspan>
      <tspan data-a="dev-v" class="am">−2.28%</tspan>
      <tspan class="as">（同类均值，2 个项目）</tspan>
    </text>
  </svg>
</template>
