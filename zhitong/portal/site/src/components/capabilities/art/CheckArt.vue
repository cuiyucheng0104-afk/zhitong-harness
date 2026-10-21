<script setup lang="ts">
/** 7.5 送审审定核对（数字与 00 章 §8.2、02 章 §3.4 一致）。 */
import { A } from './anim';
import ArtFile from './parts/ArtFile.vue';
import ArtChip from './parts/ArtChip.vue';
import ArtLink from './parts/ArtLink.vue';

const rows = [
  { s: '调整', sc: 'art-navy', code: '010515001002', v: '303,556.71', vc: '', ga: true, gb: true },
  {
    s: '仅送审',
    sc: 'art-warn-text',
    code: '011701001001',
    v: '125,120.00',
    vc: '',
    ga: true,
    gb: false,
  },
  { s: '调整', sc: 'art-navy', code: '010505001001', v: '56,688.78', vc: '', ga: true, gb: true },
  {
    s: '调整',
    sc: 'art-navy',
    code: '010807001001',
    v: '核增 26,408.05',
    vc: 'am art-danger-text',
    ga: true,
    gb: true,
  },
  {
    s: '待核实',
    sc: 'art-danger-text',
    code: '010507001001',
    v: '—',
    vc: 'as',
    ga: true,
    gb: true,
  },
];
const base = (k: number) => 64 + 24 * k;
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <ArtFile a="fa" :y="16" name="送审计价表.xlsx" kind="xlsx" />
    <ArtFile a="fb" :x="136" :y="16" name="审定计价表.xlsx" kind="xlsx" />
    <g v-bind="A('th')" class="as">
      <text x="0" y="40">状态</text>
      <text x="46" y="40">项目编码</text>
      <text x="264" y="40" text-anchor="end">核减额</text>
    </g>
    <g v-for="(r, k) in rows" :key="r.code">
      <rect
        v-if="r.ga"
        v-bind="A(`ga${k + 1}`, true)"
        x="46"
        :y="base(k) - 8"
        width="70"
        height="4"
        fill="var(--grid-line-strong)"
      />
      <rect
        v-if="r.gb"
        v-bind="A(`gb${k + 1}`, true)"
        x="46"
        :y="base(k) - 2"
        width="70"
        height="4"
        fill="var(--grid-line-strong)"
      />
      <text v-bind="A(`s${k + 1}`)" class="at" :class="r.sc" x="0" :y="base(k)">{{ r.s }}</text>
      <text v-bind="A(`c${k + 1}`)" class="am" x="46" :y="base(k)">{{ r.code }}</text>
      <text
        v-bind="A(`v${k + 1}`)"
        :class="r.vc || 'am'"
        :data-prefix="k === 3 ? '核增 ' : undefined"
        x="264"
        :y="base(k)"
        text-anchor="end"
      >
        {{ r.v }}
      </text>
    </g>
    <text v-bind="A('foot')" class="as" x="0" y="188">编码优先；名称、特征、单位兜底</text>
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <text v-bind="A('o-hdr')" class="ah" x="0" y="16">核对结果</text>
    <ArtChip a="o-tag" :x="64" :top="1" text="脚本取数 · 需人工复核" variant="warn" />
    <g v-bind="A('o-a')">
      <text class="as" x="0" y="44">送审合计</text>
      <text data-a="o-a-v" class="am" x="264" y="44" text-anchor="end">30,530,406.80</text>
    </g>
    <g v-bind="A('o-b')">
      <text class="as" x="0" y="66">审定合计</text>
      <text data-a="o-b-v" class="am" x="264" y="66" text-anchor="end">29,623,713.84</text>
    </g>
    <g v-bind="A('o-d')">
      <text class="as" x="0" y="88">核减额</text>
      <text data-a="o-d-v" class="am" x="264" y="88" text-anchor="end">906,692.96</text>
    </g>
    <g v-bind="A('o-r')">
      <text class="as" x="0" y="110">核减率</text>
      <text data-a="o-r-v" class="am" x="264" y="110" text-anchor="end">2.97%</text>
    </g>
    <ArtChip a="k1" :x="0" :top="122" text="一致 1,031" variant="ok" />
    <ArtChip a="k2" :x="92" :top="122" text="调整 214" variant="info" />
    <ArtChip a="k3" :x="167" :top="122" text="仅送审 23" variant="warn" />
    <ArtChip a="k4" :x="0" :top="148" text="仅审定 9" variant="warn" />
    <ArtChip a="k5" :x="72" :top="148" text="待核实 7" variant="danger" />
    <text v-bind="A('k6')" class="as" x="144" y="163">共 1,284 行</text>
    <ArtFile a="o-file" :y="188" name="核对结果.xlsx" kind="xlsx" />
    <text v-bind="A('o-file-n')" class="as" x="122" y="188">· 3 张工作表</text>
    <path v-bind="A('o-ok')" class="art-ok" d="M204 183 l2.8 2.8 l5.2 -5.6" fill="none" />
  </svg>
</template>
