<script setup lang="ts">
/** 7.9 报告撰写：草稿占位符〔F1〕–〔F5〕定稿时换成审核汇总表单元格原值。 */
import { A } from './anim';
import ArtChip from './parts/ArtChip.vue';
import ArtLink from './parts/ArtLink.vue';

const chapters = [
  '报告抬头与导语',
  '一、项目概况',
  '二、工程主要特征',
  '三、审核依据',
  '四、相关事项审核说明',
  '五、审核结果',
  '六、造价对比分析',
  '七、审核附件',
  '落款',
];
const base = (k: number) => 36 + 19 * k;
const draft = [
  { a: '本工程送审金额为', f: '〔F1〕', b: '，' },
  { a: '审定金额为', f: '〔F2〕', b: '，' },
  { a: '核减金额为', f: '〔F3〕', b: '，' },
  { a: '核增额为', f: '〔F4〕', b: '，' },
  { a: '净核减金额为', f: '〔F5〕', b: '[资料1]。' },
];
const final = [
  { a: '本工程送审金额为', v: '30,530,406.80', b: '元，' },
  { a: '审定金额为', v: '29,623,713.84', b: '元，' },
  { a: '核减金额为', v: '939,305.70', b: '元，' },
  { a: '核增额为', v: '32,612.74', b: '元，' },
  { a: '净核减金额为', v: '906,692.96', b: '元[资料1]。' },
];
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <g v-bind="A('cur')">
      <rect x="-2" y="116" width="268" height="21" fill="var(--blue-050)" />
      <rect x="-2" y="116" width="2" height="21" fill="var(--brand-blue)" />
    </g>
    <text v-bind="A('hdr')" class="ah" x="0" y="16">结算审核报告（房建）· 9 章</text>
    <g v-for="(c, k) in chapters" :key="c" v-bind="A(`s${k + 1}`)">
      <text class="am" x="0" :y="base(k)">{{ String((k + 1) * 10).padStart(3, '0') }}</text>
      <text class="at" x="32" :y="base(k)">{{ c }}</text>
    </g>
    <path
      v-for="k in 5"
      :key="`mk${k}`"
      v-bind="A(`mk${k}`)"
      class="art-ok"
      :d="`M250 ${base(k - 1) - 5} l3 3 l7 -7`"
      fill="none"
    />
    <path
      v-bind="A('s6-spin', true)"
      class="art-spin"
      :d="`M260 ${base(5) - 5} A5 5 0 1 1 255 ${base(5) - 10}`"
      fill="none"
    />
    <path v-bind="A('mk6')" class="art-ok" :d="`M250 ${base(5) - 5} l3 3 l7 -7`" fill="none" />
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <defs>
      <clipPath v-for="k in 5" :id="`cap-art-report-d${k}`" :key="`c${k}`">
        <rect :data-clip="`d${k}`" x="-2" :y="24 + 20 * k" width="300" height="20" />
      </clipPath>
      <clipPath id="cap-art-report-d6">
        <rect data-clip="d6" x="-2" y="128" width="300" height="20" />
      </clipPath>
    </defs>
    <text v-bind="A('o-hdr', true)" class="ah" x="0" y="16">五、审核结果 · draft.md</text>
    <text v-bind="A('o-hdr2')" class="ah" x="0" y="16">五、审核结果 · final.json</text>
    <text
      v-for="(d, k) in draft"
      :key="`d${k}`"
      v-bind="A(`d${k + 1}`, true)"
      class="at"
      x="0"
      :y="40 + 20 * k"
      :clip-path="`url(#cap-art-report-d${k + 1})`"
    >
      <tspan>{{ d.a }}</tspan>
      <tspan class="art-ph">{{ d.f }}</tspan>
      <tspan>{{ d.b }}</tspan>
    </text>
    <text
      v-for="(f, k) in final"
      :key="`f${k}`"
      v-bind="A(`f${k + 1}`)"
      class="at"
      x="0"
      :y="40 + 20 * k"
    >
      <tspan>{{ f.a }}</tspan>
      <tspan class="am">{{ f.v }}</tspan>
      <tspan>{{ f.b }}</tspan>
    </text>
    <text v-bind="A('d6')" class="at" x="0" y="144" clip-path="url(#cap-art-report-d6)">
      ……安装工程
    </text>
    <ArtChip a="d7" :top="152" text="【待补：安装工程送审与审定金额】" variant="warn" />
    <text v-bind="A('src')" class="as" x="0" y="192">〔F1〕← 审核汇总表!C10</text>
  </svg>
</template>
