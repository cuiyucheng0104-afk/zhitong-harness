<script setup lang="ts">
/** 7.3 项目与知识库问答。 */
import { A } from './anim';
import ArtChip from './parts/ArtChip.vue';
import ArtTool from './parts/ArtTool.vue';
import ArtLink from './parts/ArtLink.vue';
</script>

<template>
  <svg class="art-in" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <g v-bind="A('bubble')">
      <rect x="56" y="2" width="208" height="30" rx="12" fill="var(--blue-tint)" />
      <text class="at" x="68" y="22">合同里材料价格涨跌怎么调整？</text>
    </g>
    <ArtTool a="t1" :top="44" label="读取" name="project_doc.py" />
    <ArtTool a="t2" :top="74" label="检索" name="find_text.py" result="命中 段42" />
    <ArtTool a="t3" :top="104" label="读取" name="read_doc.py" />
    <ArtTool a="t4" :top="134" label="核对出处" name="check_answer.py" result="通过" />
    <text v-bind="A('inj')" class="as" x="0" y="186">原文含疑似对 AI 的指令，已忽略</text>
  </svg>
  <ArtLink />
  <svg class="art-out" viewBox="0 0 264 200" aria-hidden="true" focusable="false">
    <defs>
      <clipPath id="cap-art-qa-l1">
        <rect data-clip="l1" x="-2" y="26" width="300" height="22" />
      </clipPath>
      <clipPath id="cap-art-qa-l2">
        <rect data-clip="l2" x="-2" y="48" width="300" height="22" />
      </clipPath>
    </defs>
    <text v-bind="A('o-hdr')" class="ah" x="0" y="16">结论</text>
    <text v-bind="A('l1')" class="at" x="0" y="42" clip-path="url(#cap-art-qa-l1)">
      主要材料价格涨跌幅度超过基准价格
    </text>
    <text v-bind="A('l2')" class="at" x="0" y="64" clip-path="url(#cap-art-qa-l2)">
      5% 时，超过部分据实调整。
    </text>
    <g v-bind="A('cite')">
      <rect x="0" y="76" width="264" height="24" rx="4" fill="var(--blue-050)" />
      <text class="at" x="8" y="93">〔施工合同及补充协议.docx 段42〕</text>
    </g>
    <text v-bind="A('uncov-l')" class="as" x="0" y="126">没覆盖的范围</text>
    <text v-bind="A('uncov')" class="at" x="0" y="148">合同中未找到基准价格的取值时点</text>
    <ArtChip a="ok" :top="162" text="check_answer 通过" variant="ok" />
  </svg>
</template>
