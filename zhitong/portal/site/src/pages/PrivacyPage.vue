<script setup lang="ts">
/**
 * 隐私说明 `/privacy/`（00 章 §3.1、§15.4；05 章 §7 第 2 项）。
 * 正文来自用户本机现有的隐私政策（出处见 `components/sections05/privacy-policy.ts`），不由开发代理撰写。
 */
import {
  PRIVACY_BLOCKS,
  PRIVACY_META,
  PRIVACY_TITLE,
} from '../components/sections05/privacy-policy';
</script>

<template>
  <main id="main" class="privacy-page" tabindex="-1">
    <div class="container privacy-container">
      <h1>隐私说明</h1>
      <p class="privacy-doc-title">{{ PRIVACY_TITLE }}</p>
      <p class="privacy-meta">
        <span v-for="m in PRIVACY_META" :key="m">{{ m }}</span>
      </p>
      <article class="privacy-body">
        <template v-for="(b, i) in PRIVACY_BLOCKS" :key="i">
          <ul v-if="b.kind === 'toc'" class="privacy-toc">
            <li v-for="item in b.items" :key="item">{{ item }}</li>
          </ul>
          <h2 v-else-if="b.kind === 'h2'">{{ b.text }}</h2>
          <h3 v-else-if="b.kind === 'h3'">{{ b.text }}</h3>
          <h4 v-else-if="b.kind === 'h4'">{{ b.text }}</h4>
          <p v-else>{{ b.text }}</p>
        </template>
      </article>
    </div>
  </main>
</template>
