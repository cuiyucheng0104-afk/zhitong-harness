<script setup lang="ts">
/** 7.7 投控异常检测与复核（数据与 02 章 §4.2、§4.4 的 review 场景相同）。 */
import { A } from './anim';
import ArtChip from './parts/ArtChip.vue';
import ArtLink from './parts/ArtLink.vue';
import ArtPointer from './parts/ArtPointer.vue';

const rules = [
  { n: '重复计取', tier: '重点', v: 'info', c: '2' },
  { n: '整项存疑-暂估价', tier: '重点', v: 'info', c: '1' },
  { n: '整项存疑-自洽', tier: '重点', v: 'info', c: '1' },
  { n: '整项存疑-大额', tier: '粗筛', v: 'muted', c: '286' },
] as const;
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <text v-bind="A('hdr')" class="ah" x="0" y="16">tk.py detect</text>
    <text v-bind="A('src')" class="as" x="0" y="38">送审计价表.xlsx · 未给合同清单</text>
    <g v-for="(r, k) in rules" :key="r.n">
      <g v-bind="A(`rw${k + 1}`)">
        <text class="at" x="0" :y="64 + 22 * k">{{ r.n }}</text>
        <text :data-a="`rn${k + 1}`" class="am" x="264" :y="64 + 22 * k" text-anchor="end">
          {{ r.c }}
        </text>
      </g>
      <ArtChip :a="`rc${k + 1}`" :x="148" :top="49 + 22 * k" :text="r.tier" :variant="r.v" />
    </g>
    <text v-bind="A('total')" class="at" x="0" y="156">共 290 条疑似 · 重点 4 · 粗筛 286</text>
    <text v-bind="A('skip')" class="as" x="0" y="176">未运行：单价超合同、量超合同、</text>
    <text v-bind="A('skip2')" class="as" x="0" y="194">漏报、合同外新增（没有合同清单）</text>
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <rect v-bind="A('card')" x="0" y="0" width="264" height="200" rx="8" class="art-card" />
    <text v-bind="A('c-h', true)" class="ah" x="12" y="24">重复计取｜综合脚手架</text>
    <text v-bind="A('c-h2')" class="ah" x="12" y="24">已确认 1 · 待复核 289</text>
    <text v-bind="A('c-code')" x="12" y="46">
      <tspan class="am">011701001001</tspan>
      <tspan class="as">· 置信度 0.7</tspan>
    </text>
    <text v-bind="A('c-l1')" class="at" x="12" y="70">第 46 行与第 28 行同编码</text>
    <text v-bind="A('c-l2')" class="at" x="12" y="92">名称、特征、工程量相同</text>
    <text v-bind="A('c-l3')" x="12" y="114">
      <tspan class="at">送审金额各</tspan>
      <tspan class="am">125,120.00</tspan>
    </text>
    <text v-bind="A('c-loc')" class="as" x="12" y="136">施工技术措施项目清单与计价表</text>
    <g v-bind="A('b1', true)">
      <rect x="12" y="146" width="88" height="26" rx="6" fill="var(--brand-blue)" />
      <text class="at art-on-blue" text-anchor="middle" x="56" y="164">确认异常</text>
    </g>
    <g v-bind="A('b2', true)">
      <rect x="108" y="146" width="88" height="26" rx="6" class="art-btn-ghost" />
      <text class="at" text-anchor="middle" x="152" y="164">判为误报</text>
    </g>
    <ArtChip a="done" :x="12" :top="150" text="已追加 复核.jsonl · confirmed" variant="ok" />
    <text v-bind="A('reason')" class="as" x="12" y="190">理由：与第 28 行编码、名称、特征…</text>
    <ArtPointer :x="232" :y="196" />
  </svg>
</template>
