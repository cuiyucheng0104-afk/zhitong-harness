<script setup lang="ts">
/** 7.12 企业知识库：依据 → 确认写入 → 新条目带来源与日期 → 校验。 */
import { A } from './anim';
import ArtFile from './parts/ArtFile.vue';
import ArtChip from './parts/ArtChip.vue';
import ArtTool from './parts/ArtTool.vue';
import ArtLink from './parts/ArtLink.vue';
import ArtPointer from './parts/ArtPointer.vue';

const entries = [
  { k: '来源:', v: '合同 专用合同条款 11.1' },
  { k: '日期:', v: '2026-10-19' },
  { k: '获取方式:', v: '工作回写' },
  { k: '适用范围:', v: '结算审核；本公司' },
  { k: '核验状态:', v: '已核（审核负责人）' },
];
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <defs>
      <clipPath id="cap-art-knowledge-q1">
        <rect data-clip="q1" x="6" y="72" width="300" height="22" />
      </clipPath>
      <clipPath id="cap-art-knowledge-q2">
        <rect data-clip="q2" x="6" y="92" width="300" height="22" />
      </clipPath>
    </defs>
    <text v-bind="A('hdr')" class="ah" x="0" y="16">依据 · 2026-007</text>
    <rect v-bind="A('src-bg')" x="0" y="26" width="264" height="94" rx="6" fill="var(--blue-050)" />
    <ArtFile a="src-file" :x="8" :y="46" name="施工合同及补充协议.docx" kind="docx" />
    <text v-bind="A('src-cl')" class="as" x="8" y="66">专用合同条款 11.1</text>
    <text v-bind="A('q1')" class="at" x="8" y="88" clip-path="url(#cap-art-knowledge-q1)">
      主要材料价格涨跌幅度超过基准价格
    </text>
    <text v-bind="A('q2')" class="at" x="8" y="108" clip-path="url(#cap-art-knowledge-q2)">
      5% 时，超过部分据实调整。
    </text>
    <rect v-bind="A('ask-bg')" x="0" y="130" width="264" height="66" rx="8" class="art-card" />
    <text v-bind="A('ask-t')" class="ah" x="12" y="150">写入公司经验？</text>
    <text v-bind="A('ask-f')" class="as" x="12" y="176">结算审核-材料调差风险幅度口径.md</text>
    <g v-bind="A('ask-y', true)">
      <rect x="150" y="136" width="48" height="22" rx="6" fill="var(--brand-blue)" />
      <text class="at art-on-blue" text-anchor="middle" x="174" y="152">确认</text>
    </g>
    <g v-bind="A('ask-n', true)">
      <rect x="206" y="136" width="48" height="22" rx="6" class="art-btn-ghost" />
      <text class="at" text-anchor="middle" x="230" y="152">修改</text>
    </g>
    <ArtChip a="ask-ok" :x="150" :top="137" text="已确认" variant="ok" />
    <ArtPointer :x="226" :y="192" />
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <text v-bind="A('o-hdr')" class="ah" x="0" y="16">知识库/</text>
    <text v-bind="A('o-dirs')" class="as" x="0" y="38">
      规范/ 定额/ 费率/ 模板/
      <tspan data-a="o-dirs-hl">公司经验/</tspan>
    </text>
    <g v-bind="A('o-new')">
      <text class="ah" x="0" y="62">+</text>
      <ArtFile :x="16" :y="62" name="结算审核-材料调差风险幅度口径.md" kind="md" />
    </g>
    <text v-for="(e, k) in entries" :key="e.k" v-bind="A(`e${k + 1}`)" x="16" :y="86 + 20 * k">
      <tspan class="am">{{ e.k }}</tspan>
      <tspan class="at">{{ e.v }}</tspan>
    </text>
    <ArtTool a="chk-t" transient :top="176" label="校验" name="check_knowledge.py" />
    <ArtChip a="chk" :top="178" text="校验：8 个目录 · 17 条 · 0 违规" variant="ok" />
  </svg>
</template>
