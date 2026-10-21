<script setup lang="ts">
/** 7.10 GB50854 清单框架：做法逐层判断去向，编码取自受控码表。 */
import { A } from './anim';
import ArtChip from './parts/ArtChip.vue';
import ArtLink from './parts/ArtLink.vue';

const layers = [
  { t: '10厚800×800防滑地砖…', role: '单列项', v: 'info' },
  { t: '20厚1:3干硬性水泥砂浆…', role: '并入特征', v: 'muted' },
  { t: '素水泥浆一道', role: '并入特征', v: 'muted' },
  { t: '钢筋混凝土楼板', role: '基层', v: 'muted' },
] as const;
const base = (k: number) => 44 + 26 * k;
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <text v-bind="A('hdr')" x="0" y="16">
      <tspan class="ah">楼1 地砖楼面</tspan>
      <tspan class="as">· 竣工图总说明.pdf p3</tspan>
    </text>
    <g v-for="(l, k) in layers" :key="l.t">
      <text v-bind="A(`y${k + 1}`)" class="at" x="0" :y="base(k)">{{ l.t }}</text>
      <ArtChip
        :a="`r${k + 1}`"
        :x="264"
        anchor="end"
        :top="base(k) - 15"
        :text="l.role"
        :variant="l.v"
      />
    </g>
    <path v-bind="A('mg2')" data-dashed class="art-merge" d="M196 65 C184 65 186 39 210 39" />
    <path v-bind="A('mg3')" data-dashed class="art-merge" d="M196 91 C176 91 180 39 210 39" />
    <text v-bind="A('seg2')" class="as" x="0" y="150">屋面1 不上人屋面</text>
    <text v-bind="A('y5')" class="at" x="0" y="172">40厚C20细石混凝土保护层</text>
    <ArtChip a="r5" :x="264" anchor="end" :top="157" text="单列项" variant="info" />
    <text v-bind="A('reg')" class="as" x="0" y="194">受控码表 zj2025 · 490 条</text>
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <text v-bind="A('o-hdr')" class="ah" x="0" y="16">分部分项工程量清单（框架）</text>
    <g v-bind="A('i1')">
      <text class="am" x="0" y="40">
        011102003
        <tspan data-a="ser" class="art-ser">001</tspan>
      </text>
      <text class="at" x="110" y="40">块料楼地面</text>
      <text class="at" x="264" y="40" text-anchor="end">m²</text>
    </g>
    <text v-bind="A('f1')" class="as" x="8" y="60">4.结合层厚度：〔AI摘录〕20厚</text>
    <text v-bind="A('f2')" class="as" x="8" y="78">7.面层材料厚度：〔AI摘录〕10厚</text>
    <text v-bind="A('f3')" class="as art-warn-text" x="8" y="96">2.找平层厚度：待补</text>
    <g v-bind="A('q')">
      <text class="at" x="0" y="120">工程量</text>
      <rect data-a="q-box" data-dashed x="48" y="106" width="70" height="18" class="art-dash-box" />
      <text class="as" x="126" y="120">留空，需人工计算</text>
    </g>
    <g v-bind="A('p')">
      <ArtChip :x="0" :top="134" text="待核" variant="warn" />
      <text class="at" x="42" y="149">40厚C20细石混凝土保护层</text>
    </g>
    <text v-bind="A('p2')" class="as" x="42" y="168">给了 011101002，部位是屋面</text>
    <text v-bind="A('cov')" class="as" x="0" y="192">
      覆盖核算：片段
      <tspan data-a="cov-a">148</tspan>
      = 去向
      <tspan data-a="cov-b">148</tspan>
    </text>
  </svg>
</template>
