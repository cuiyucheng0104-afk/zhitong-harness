<script setup lang="ts">
import BaseDialog from './BaseDialog.vue';
import AppIcon from './AppIcon.vue';
import brandMark from '../../assets/brand-mark.svg';
import { release } from '../data/downloads';
defineProps<{ modelValue: boolean; trigger?: HTMLElement | null }>();
defineEmits<{ 'update:modelValue': [value: boolean] }>();
</script>

<template>
  <BaseDialog
    id="acquire-dialog"
    class="acquire-dialog"
    :model-value="modelValue"
    :trigger="trigger"
    labelledby="acquire-dialog-title"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div class="acquire-dialog-body">
      <div class="dialog-heading">
        <img :src="brandMark" alt="" width="40" height="40" /><button
          class="icon-button"
          aria-label="关闭获取说明"
          @click="$emit('update:modelValue', false)"
        >
          <AppIcon name="close" />
        </button>
      </div>
      <p class="eyebrow">为您的公司准备</p>
      <h2 id="acquire-dialog-title">获取安装与配置包</h2>
      <p class="dialog-description">
        安装包可直接下载。公司专属配置包由服务方单独交付，不随安装包公开分发。
      </p>
      <p class="release-meta">
        <span class="mono">v{{ release.version }}</span
        ><span>{{ release.date ? `${release.date} 发布` : '发布日期待定' }}</span>
      </p>
      <ul class="package-downloads">
        <li
          v-for="item in release.platforms"
          :key="item.platform"
          :class="['package-download', { 'is-upcoming': !item.available }]"
          :data-platform="item.platform"
        >
          <div class="package-download-head">
            <AppIcon :name="item.icon" />
            <span class="package-download-name">{{ item.name }} 安装包</span>
            <span class="mono">{{ item.arch }}</span>
          </div>
          <p v-if="item.notes" class="package-download-notes">{{ item.notes }}</p>
          <template v-if="item.available">
            <a
              class="button button-primary button-small package-download-link"
              :href="item.href"
              download
              >下载{{ item.name }}安装包<AppIcon name="down"
            /></a>
            <p class="package-download-meta">
              <span class="mono">{{ item.file }}</span
              ><span>{{ item.size }}</span
              ><a :href="item.sha256Href">SHA256 校验值</a>
            </p>
            <details class="package-download-first">
              <summary>首次打开</summary>
              <ol>
                <li v-for="step in item.firstLaunch" :key="step">{{ step }}</li>
              </ol>
              <p>
                校验下载：<code>{{ item.verify }}</code
                >，结果应为
                <code class="package-download-hash">{{ item.sha256 }}</code>
              </p>
            </details>
          </template>
          <p v-else class="package-download-upcoming">即将发布</p>
        </li>
      </ul>
      <div class="contact-placeholder">
        <span>配置包与服务</span><strong>联系方式待配置</strong>
      </div>
      <button class="button button-outline full-width" @click="$emit('update:modelValue', false)">
        知道了，关闭
      </button>
    </div>
  </BaseDialog>
</template>
