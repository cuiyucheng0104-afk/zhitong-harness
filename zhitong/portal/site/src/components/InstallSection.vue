<script setup lang="ts">
import AppIcon from './AppIcon.vue';
import { release } from '../data/downloads';

const emit = defineEmits<{
  acquire: [event: MouseEvent];
}>();
</script>

<template>
  <section class="acquire-section" id="install" aria-labelledby="install-title">
    <div class="container">
      <div class="acquire-panel">
        <div class="acquire-copy reveal">
          <p class="eyebrow">安装与交付</p>
          <h2 id="install-title">装好，导入，<br />开始用。</h2>
          <p>
            支持Mac与Windows，内置运行环境与DWG转换组件。<br />公司专属配置包，由服务方单独交付。
          </p>
          <ul class="install-downloads" :aria-label="`v${release.version} 安装包`">
            <li v-for="item in release.platforms" :key="item.platform">
              <a v-if="item.available" :href="item.href" download
                ><AppIcon :name="item.icon" />{{ item.name }}（{{ item.arch }}）<span
                  class="mono"
                  >{{ item.size }}</span
                ></a
              >
              <span v-else
                ><AppIcon :name="item.icon" />{{ item.name }}（{{ item.arch }}）<em
                  >即将发布</em
                ></span
              >
            </li>
          </ul>
        </div>
        <div class="acquire-action">
          <div class="platform-symbols" aria-hidden="true">
            <AppIcon name="apple" class="icon" /><span></span><AppIcon name="window" class="icon" />
          </div>
          <button type="button" class="button button-white" @click="emit('acquire', $event)">
            获取安装与配置包<AppIcon name="arrow" class="icon" />
          </button>
          <span>v{{ release.version }} · 无需另行安装 Python</span>
        </div>
        <div class="acquire-art" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      </div>
    </div>
  </section>
</template>
