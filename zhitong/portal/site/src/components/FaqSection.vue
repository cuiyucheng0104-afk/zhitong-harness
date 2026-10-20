<script setup lang="ts">
import { nextTick, ref } from 'vue';
import { faqs } from '../data/content';
import { refreshMotionLayout } from '../lib/motion';
import AppIcon from './AppIcon.vue';

const openFaq = ref<string | null>(faqs[0]?.id ?? null);

function toggleFaq(id: string) {
  openFaq.value = openFaq.value === id ? null : id;
  void nextTick(refreshMotionLayout);
}
</script>

<template>
  <section id="faq" class="faq-section section-space" aria-labelledby="faq-title">
    <div class="container faq-grid">
      <div class="section-heading reveal">
        <p class="eyebrow">常见问题</p>
        <h2 id="faq-title" tabindex="-1">使用前，<br />您可能关心。</h2>
        <p>关于数据、协作与资料。</p>
      </div>
      <div class="faq-list">
        <details v-for="faq in faqs" :key="faq.id" class="faq-item" :open="openFaq === faq.id">
          <summary :aria-expanded="openFaq === faq.id" @click.prevent="toggleFaq(faq.id)">
            {{ faq.question }}<AppIcon name="plus" />
          </summary>
          <p>{{ faq.answer }}</p>
        </details>
      </div>
    </div>
  </section>
</template>
