<script setup lang="ts">
import AppIcon from './AppIcon.vue';

const emit = defineEmits<{
  acquire: [event: MouseEvent];
  navigate: [id: string];
}>();
</script>

<template>
  <section class="hero" aria-labelledby="hero-title">
    <div class="container hero-grid">
      <div class="hero-copy">
        <p class="eyebrow hero-enter">
          <span class="small-cross" aria-hidden="true"></span>为造价咨询团队而做
        </p>
        <h1 id="hero-title" class="hero-enter">造价咨询公司的<br /><span>对话式工作台</span></h1>
        <p class="hero-description hero-enter">
          用对话读资料、做核对、算指标、写报告。<br
            class="desktop-break"
          />过程与成果统一保存，数字有据可查。
        </p>
        <div class="hero-actions hero-enter">
          <button type="button" class="button button-primary" @click="emit('acquire', $event)">
            获取安装与配置包<AppIcon name="arrow" class="icon" />
          </button>
          <a class="text-link" href="#demo" @click.prevent="emit('navigate', 'demo')">
            查看工作示例<AppIcon name="down" class="icon" />
          </a>
        </div>
        <div class="platform-note hero-enter">
          <span
            ><AppIcon name="apple" class="icon" /><AppIcon name="window" class="icon" />支持 Mac 与
            Windows</span
          >
          <span class="note-divider" aria-hidden="true"></span>
          <span>配置包由服务方交付</span>
        </div>
      </div>
      <slot />
    </div>
    <div class="container hero-principles">
      <div><AppIcon name="chat" class="icon" /><span>对话组织任务</span></div>
      <span class="principle-line" aria-hidden="true"></span>
      <div><AppIcon name="calc" class="icon" /><span>脚本完成计算</span></div>
      <span class="principle-line" aria-hidden="true"></span>
      <div><AppIcon name="shield" class="icon" /><span>人工复核结果</span></div>
    </div>
  </section>
</template>
