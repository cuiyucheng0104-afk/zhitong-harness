<script setup lang="ts">
/** 7.2 开项目与资料盘点。 */
import { A } from './anim';
import ArtFile from './parts/ArtFile.vue';
import ArtChip from './parts/ArtChip.vue';
import ArtLink from './parts/ArtLink.vue';

const rows = [
  { name: '施工合同及补充协议.docx', kind: 'docx', mark: '已备', v: 'ok' },
  { name: '招标文件.pdf', kind: 'pdf', mark: '待确认', v: 'warn' },
  { name: '工程量清单.xlsx', kind: 'xlsx', mark: '已备', v: 'ok' },
  { name: '竣工图总说明.pdf', kind: 'pdf', mark: '已备', v: 'ok' },
  { name: '结算送审书.pdf', kind: 'pdf', mark: '已备', v: 'ok' },
  { name: '签证单汇总.xlsx', kind: 'xlsx', mark: '待确认', v: 'warn' },
  { name: '扫描件0001.pdf', kind: 'pdf', mark: '未判出', v: 'muted' },
] as const;
const base = (k: number) => 40 + 22 * k;
const bars = [1, 2, 3, 4, 5, 6, 7];
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <rect
      v-bind="A('scan', true)"
      x="-2"
      y="25"
      width="266"
      height="22"
      rx="4"
      fill="var(--blue-050)"
    />
    <text v-bind="A('hdr')" class="ah" x="0" y="16">2026-007-某综合办公楼/</text>
    <g v-for="(r, k) in rows" :key="r.name">
      <ArtFile :a="`r${k + 1}`" :y="base(k)" :name="r.name" :kind="r.kind" />
      <ArtChip
        :a="`m${k + 1}`"
        :x="264"
        anchor="end"
        :top="base(k) - 15"
        :text="r.mark"
        :variant="r.v"
      />
    </g>
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <text v-bind="A('o-hdr')" class="ah" x="0" y="16">资料盘点 · 结算审核 / 审定</text>
    <rect
      v-for="k in bars"
      :key="k"
      v-bind="A(`bar${k}`)"
      :class="k <= 3 ? 'art-bar-ok' : k === 4 ? 'art-bar-warn' : 'art-bar-miss'"
      :x="36 * (k - 1)"
      y="26"
      width="32"
      height="12"
      rx="2"
    />
    <text v-bind="A('o-sum')" class="at" x="0" y="60">必备 7 项：已备 3 · 待确认 1 · 缺失 3</text>
    <text v-bind="A('o-rate')" x="0" y="84">
      <tspan class="at">齐备率</tspan>
      <tspan data-a="o-rate-v" class="am">42.86%</tspan>
      <tspan class="as">（上限 57.14%）</tspan>
    </text>
    <text v-bind="A('o-miss')" class="as" x="0" y="110">缺失</text>
    <ArtChip a="c1" :x="34" :top="95" text="结算审核报告" variant="danger" />
    <ArtChip a="c2" :x="136" :top="95" text="结算审定单" variant="danger" />
    <ArtChip a="c3" :x="34" :top="119" text="审核汇总表" variant="danger" />
    <g v-bind="A('o-pend')">
      <text class="as" x="0" y="160">待确认</text>
      <text class="at" x="48" y="160">签证单汇总.xlsx（疑似）</text>
    </g>
    <text v-bind="A('o-foot')" class="as" x="0" y="188">只看文件名，不读内容 · 清单待签核</text>
  </svg>
</template>
