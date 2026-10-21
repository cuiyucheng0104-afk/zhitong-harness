<script setup lang="ts">
/**
 * 404 页（01 章 §12；06 章 §7.16）。预渲染为 `dist/404.html`，nginx 以 404 状态返回；不加载 GSAP。
 * “请求地址”一行在水合后插入（构建时不知道地址）。装饰位由 07 章 D5 `DecoMissingSheet` 填充（00 章 §14 裁定 3）。
 */
import { onMounted, ref } from 'vue';
import DecoMissingSheet from '../components/deco/DecoMissingSheet.vue';

const path = ref('');
onMounted(() => (path.value = window.location.pathname));
</script>

<template>
  <main id="main" class="notfound-page on-dark deco-navy-grid" tabindex="-1">
    <div class="container notfound-grid">
      <div class="notfound-copy">
        <h1>页面不存在</h1>
        <p>您访问的地址没有对应的页面。可能是链接已更改，或地址有误。</p>
        <div class="notfound-actions">
          <RouterLink class="button button-white" to="/">回到首页</RouterLink>
          <RouterLink class="button button-dark-outline" to="/docs/">查看文档</RouterLink>
        </div>
        <p v-if="path" class="notfound-path">请求地址：<span class="mono">{{ path }}</span></p>
      </div>
      <div class="notfound-deco" aria-hidden="true">
        <DecoMissingSheet />
      </div>
    </div>
  </main>
</template>
