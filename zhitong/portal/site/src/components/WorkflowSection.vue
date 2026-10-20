<script setup lang="ts">
import AppIcon from './AppIcon.vue';
import { workflowSteps } from '../data/content';
</script>

<template>
  <section id="workflow" class="workflow-section section-space" aria-labelledby="workflow-title">
    <div class="container">
      <div class="section-heading reveal">
        <p class="eyebrow">使用流程</p>
        <h2 id="workflow-title" tabindex="-1">四步，开始工作。</h2>
        <p>从安装到归档，沿着项目推进。</p>
      </div>
      <div class="workflow-grid">
        <div class="workflow-track" aria-hidden="true"><span></span></div>
        <article v-for="(step, index) in workflowSteps" :key="step.title" class="workflow-step">
          <div class="step-number">{{ index + 1 }}</div>
          <AppIcon :name="step.icon" class="step-icon" />
          <h3>{{ step.title }}</h3>
          <p>{{ step.description }}</p>
          <span class="step-caption">{{ step.caption }}</span>
        </article>
      </div>
    </div>
  </section>
</template>
