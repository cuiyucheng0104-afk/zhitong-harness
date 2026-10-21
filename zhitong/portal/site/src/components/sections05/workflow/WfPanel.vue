<script setup lang="ts">
/** 使用流程每一步的文字栏（05 章 §1.2、§1.3）：标签、标题、正文、“写到哪里”芯片与文档链接。 */
import AppIcon from '../../AppIcon.vue';
import { WORKFLOW_COPY, type WorkflowStep } from '../../../data/workflow';

defineProps<{ step: WorkflowStep }>();
</script>

<template>
  <div class="wf-text">
    <p class="wf-label mono">{{ step.label }}</p>
    <h3 :id="`wf-step-${step.id}`" class="wf-title">{{ step.title }}</h3>
    <p class="wf-desc">{{ step.body }}</p>
    <p class="wf-writes-title">{{ WORKFLOW_COPY.writesTitle }}</p>
    <p class="wf-writes">
      <template v-for="(w, k) in step.writes" :key="k"
        ><code v-if="w.mono" class="wf-chip mono">{{ w.text }}</code
        ><span v-else>{{ w.text }}</span></template
      >
    </p>
    <RouterLink class="text-link wf-doc" :to="step.doc.href"
      >{{ step.doc.text }}<AppIcon name="arrow" class="icon"
    /></RouterLink>
  </div>
</template>
