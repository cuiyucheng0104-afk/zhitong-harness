<script setup lang="ts">
/** 7.11 归档与案例索引：核对 → 确认 → 推送回读 → 案例索引只改本项目一行。 */
import { A } from './anim';
import ArtFile from './parts/ArtFile.vue';
import ArtChip from './parts/ArtChip.vue';
import ArtLink from './parts/ArtLink.vue';
import ArtPointer from './parts/ArtPointer.vue';
import { textWidth } from '../art-tokens';

const results = [
  { n: '审核汇总表.xlsx', k: 'xlsx' },
  { n: '…结算审核报告-初稿.docx', k: 'docx' },
  { n: '…结算审核报告.docx', k: 'docx' },
] as const;
/** 右列 x 由 136 调到 143：等宽 14 单位下左列条目宽 128.8，对勾（右侧 6）会压到右列文字。 */
const works = [
  { n: '2026-10-19-盘点/', x: 0, y: 128 },
  { n: '2026-10-19-核对/', x: 143, y: 128 },
  { n: '2026-10-19-投控/', x: 0, y: 146 },
  { n: '2026-10-20-指标/', x: 143, y: 146 },
  { n: '2026-10-20-报告/', x: 0, y: 164 },
];
const check = (x: number, y: number) => `M${x} ${y - 4} l2.4 2.4 l4.4 -4.8`;
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <text v-bind="A('hdr')" class="ah" x="0" y="16">archive.py check · 无阻断项</text>
    <text v-bind="A('g1')" class="as" x="0" y="36">成果/</text>
    <ArtFile
      v-for="(r, k) in results"
      :key="r.n"
      :a="`a${k + 1}`"
      :y="54 + 18 * k"
      :name="r.n"
      :kind="r.k"
    />
    <path
      v-for="k in 3"
      :key="`ck${k}`"
      v-bind="A(`ck${k}`)"
      class="art-ok"
      :d="check(252, 54 + 18 * (k - 1))"
      fill="none"
    />
    <text v-bind="A('g2')" class="as" x="0" y="110">工作/</text>
    <text v-for="(w, k) in works" :key="w.n" v-bind="A(`w${k + 1}`)" class="am" :x="w.x" :y="w.y">
      {{ w.n }}
    </text>
    <path
      v-for="(w, k) in works"
      :key="`cw${k}`"
      v-bind="A(`ck${k + 4}`)"
      class="art-ok"
      :d="check(w.x + textWidth(w.n, true) + 6, w.y)"
      fill="none"
    />
    <ArtChip a="warn1" transient :top="172" text="2 个待确认清单还有未勾选项" variant="warn" />
    <ArtChip a="push" :top="172" text="推送完成 · 回读 sha256 一致" variant="ok" />
    <rect v-bind="A('pbar')" x="0" y="195" width="200" height="2" fill="var(--brand-blue)" />
    <g v-bind="A('ask', true)">
      <rect x="16" y="44" width="232" height="80" rx="8" class="art-card art-shadow" />
      <text class="ah" x="28" y="70">按这样归档？</text>
      <text class="as" x="28" y="90">未勾选事项写进工作记录</text>
      <rect x="28" y="98" width="64" height="22" rx="6" fill="var(--brand-blue)" />
      <text class="at art-on-blue" text-anchor="middle" x="60" y="114">确认</text>
      <rect x="100" y="98" width="72" height="22" rx="6" class="art-btn-ghost" />
      <text class="at" text-anchor="middle" x="136" y="114">先不归档</text>
    </g>
    <ArtPointer :x="150" :y="160" />
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <rect v-bind="A('o-bg')" x="-4" y="44" width="272" height="156" rx="6" fill="var(--blue-050)" />
    <text v-bind="A('o-hdr')" class="ah" x="0" y="16">案例索引.md · 2026-007 一行</text>
    <text v-bind="A('o-note')" class="as" x="0" y="36">其他项目的行不改动</text>
    <text v-bind="A('fd')" class="as" x="0" y="62">编号</text>
    <text v-bind="A('fd')" class="am" x="34" y="62">2026-007</text>
    <text v-bind="A('fd')" class="as" x="140" y="62">状态</text>
    <text v-bind="A('fd')" class="at" x="174" y="62">已归档</text>
    <text v-bind="A('fd')" class="as" x="0" y="84">工程名</text>
    <text v-bind="A('fd')" class="at" x="48" y="84">某综合办公楼</text>
    <text v-bind="A('fd')" class="as" x="170" y="84">业态</text>
    <text v-bind="A('fd')" class="at" x="204" y="84">办公</text>
    <text v-bind="A('fd')" class="as" x="0" y="106">规模</text>
    <text v-bind="A('fd')" class="am" x="34" y="106">18,600.00 m²</text>
    <text v-bind="A('fd')" class="as" x="140" y="106">咨询类型</text>
    <text v-bind="A('fd')" class="at" x="200" y="106">结算审核</text>
    <text v-bind="A('fd')" class="as" x="0" y="128">关键指标</text>
    <text v-bind="A('fd')" class="at" x="62" y="128">审定单方 1,592.67 元/m²</text>
    <text v-bind="A('fd')" class="as" x="62" y="148">（清单明细合计口径）</text>
    <text v-bind="A('fd')" class="at" x="62" y="168">核减率 2.97%</text>
    <text v-bind="A('fd')" class="as" x="0" y="188">成果链接</text>
    <text v-bind="A('fd')" class="am" x="62" y="188">项目/2026-007-…/成果/</text>
    <line
      v-bind="A('o-link')"
      x1="62"
      y1="191"
      x2="232"
      y2="191"
      stroke="var(--brand-blue)"
      stroke-width="1"
    />
  </svg>
</template>
