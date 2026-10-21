<script setup lang="ts">
/**
 * 服务方联系方式列表（01 章 §8.3）：按“服务方 / 联系人 / 电话 / 邮箱 / 微信 / 服务时间”顺序列出非空项。
 * 电话 `tel:`、等宽；邮箱 `mailto:`；微信为文本 + 复制按钮（提示“已复制微信号”，水合后才渲染）。
 * 只在 `contactChannels` 非空时由调用方渲染（安装区“联系服务方”、页脚“联系”栏）。
 */
import { onMounted, ref } from 'vue';
import AppIcon from '../AppIcon.vue';
import { contactChannels, siteConfig } from '../../site.config';
import { useCopy } from '../../composables/useCopy';

const contact = siteConfig.contact;
const channels = contactChannels(contact);
const phone = channels.find((c) => c.kind === 'phone');
const email = channels.find((c) => c.kind === 'email');
const wechat = channels.find((c) => c.kind === 'wechat');
const wechatEl = ref<HTMLElement | null>(null);
const hydrated = ref(false);
const { copy } = useCopy();

function copyWechat() {
  if (wechat) void copy(wechat.value, { success: '已复制微信号', fallbackSelect: wechatEl.value });
}
onMounted(() => (hydrated.value = true));
</script>

<template>
  <dl class="contact-list">
    <div v-if="contact.provider.trim()">
      <dt>服务方</dt>
      <dd>{{ contact.provider }}</dd>
    </div>
    <div v-if="contact.person.trim()">
      <dt>联系人</dt>
      <dd>{{ contact.person }}</dd>
    </div>
    <div v-if="phone && phone.kind === 'phone'">
      <dt>电话</dt>
      <dd>
        <a class="mono" :href="phone.href">{{ phone.value }}</a>
      </dd>
    </div>
    <div v-if="email && email.kind === 'email'">
      <dt>邮箱</dt>
      <dd>
        <a :href="email.href">{{ email.value }}</a>
      </dd>
    </div>
    <div v-if="wechat">
      <dt>微信</dt>
      <dd>
        <span ref="wechatEl" class="mono">{{ wechat.value }}</span>
        <button
          v-if="hydrated"
          type="button"
          class="icon-button contact-copy"
          aria-label="复制微信号"
          @click="copyWechat"
        >
          <AppIcon name="copy" />
        </button>
      </dd>
    </div>
    <div v-if="contact.hours.trim()">
      <dt>服务时间</dt>
      <dd>{{ contact.hours }}</dd>
    </div>
  </dl>
</template>
