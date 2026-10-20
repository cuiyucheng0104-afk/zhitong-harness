<script setup lang="ts">
import AppIcon from './AppIcon.vue';
import brandMark from '../../assets/brand-mark.svg';

const emit = defineEmits<{
  acquire: [event: MouseEvent];
  navigate: [id: string];
}>();
</script>

<template>
  <footer class="site-footer">
    <div class="container">
      <div class="footer-main">
        <a
          class="brand"
          href="#main"
          aria-label="智通数工AI，返回首页"
          @click.prevent="emit('navigate', 'main')"
        >
          <img class="brand-mark" :src="brandMark" alt="" width="36" height="36" />
          <span>智通数工<span class="brand-ai">AI</span></span>
        </a>
        <p>用对话处理造价咨询，<br />让资料、计算和成果有据可查。</p>
        <button type="button" class="text-link" @click="emit('acquire', $event)">
          获取安装与配置包<AppIcon name="arrow" class="icon" />
        </button>
      </div>
      <div class="footer-meta">
        <span>智通数工AI · 造价咨询对话式工作台</span>
        <span>工作示例 · 示例数据</span>
      </div>
    </div>
  </footer>
</template>
