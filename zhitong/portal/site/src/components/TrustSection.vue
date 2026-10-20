<script setup lang="ts">
import AppIcon from './AppIcon.vue';
import { trustStatements } from '../data/content';
</script>

<template>
  <section class="trust-section section-space" id="trust" aria-labelledby="trust-title">
    <div class="container">
      <div class="section-heading reveal">
        <p class="eyebrow">数据与复核</p>
        <h2 id="trust-title" tabindex="-1">资料归公司，<br />结果可复核。</h2>
      </div>
      <div class="trust-grid">
        <div class="data-relationship" aria-label="公司存储、工程师电脑、模型服务与人工复核的关系">
          <div class="data-flow">
            <div class="data-node">
              <AppIcon name="cloud" class="icon" />
              <strong>公司 TOS</strong>
              <span>资料与成果</span>
            </div>
            <div class="flow-link" aria-label="双向连接">↔</div>
            <div class="data-node central-node">
              <AppIcon name="laptop" class="icon" />
              <strong>工程师电脑</strong>
              <span>工作与计算</span>
            </div>
            <div class="flow-link" aria-label="双向连接">↔</div>
            <div class="data-node">
              <AppIcon name="chat" class="icon" />
              <strong>模型服务</strong>
              <span>阅读与分析</span>
            </div>
          </div>
          <div class="vertical-flow" aria-hidden="true"></div>
          <div class="review-node">
            <AppIcon name="shield" class="icon" />
            <span>脚本计算结果<strong>人工复核与签发</strong></span>
            <AppIcon name="check" class="icon" />
          </div>
          <p class="model-disclosure">
            读取的文件内容会作为对话上下文交给配置的模型服务，具体部署方式在交付时说明。
          </p>
        </div>
        <div class="trust-statements">
          <article v-for="statement in trustStatements" :key="statement.title">
            <span class="statement-symbol"><AppIcon :name="statement.icon" /></span>
            <div>
              <h3>{{ statement.title }}</h3>
              <p>{{ statement.description }}</p>
            </div>
          </article>
        </div>
      </div>
    </div>
  </section>
</template>
