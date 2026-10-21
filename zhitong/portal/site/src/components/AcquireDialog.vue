<script setup lang="ts">
/**
 * 获取安装包弹层（01 章 §7）。数据来自 `data/downloads.ts`；联系服务方区只在 `hasContact` 时渲染（§8.3）。
 */
import { computed, ref } from 'vue';
import BaseDialog from './BaseDialog.vue';
import AppIcon from './AppIcon.vue';
import PlatformCard from './acquire/PlatformCard.vue';
import ConfigPackageStrip from './acquire/ConfigPackageStrip.vue';
import { release } from '../data/downloads';
import { detectPlatform, type VisitorPlatform } from '../lib/platform';
import { contactChannels, siteConfig } from '../site.config';
import { useCopy } from '../composables/useCopy';

withDefaults(defineProps<{ modelValue: boolean; trigger?: HTMLElement | null }>(), {
  trigger: null,
});
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>();

const platform = ref<VisitorPlatform>(null);
const playing = ref(false);
const wechatEl = ref<HTMLElement | null>(null);
const { copy } = useCopy();

const ordered = computed(() => {
  const list = [...release.platforms];
  const p = platform.value;
  if (p === 'mac-arm64' || p === 'win-x64') list.sort((a, b) => Number(b.platform === p) - Number(a.platform === p));
  return list;
});
const contact = siteConfig.contact;
const channels = contactChannels(contact);
const showContact = channels.length > 0;
const phone = channels.find((c) => c.kind === 'phone');
const email = channels.find((c) => c.kind === 'email');
const wechat = channels.find((c) => c.kind === 'wechat');

function onOpened() {
  platform.value = detectPlatform();
  playing.value = false;
  setTimeout(() => (playing.value = true), 300);
}
function close() {
  emit('update:modelValue', false);
}
function copyPage() {
  void copy(`${location.origin}/`, { success: '已复制页面链接' });
}
function copyWechat() {
  if (wechat) void copy(wechat.value, { success: '已复制微信号', fallbackSelect: wechatEl.value });
}
</script>

<template>
  <BaseDialog
    id="acquire-dialog"
    class="acquire-dialog"
    variant="auto"
    :model-value="modelValue"
    :trigger="trigger"
    labelledby="acquire-title"
    @update:model-value="emit('update:modelValue', $event)"
    @opened="onOpened"
  >
    <div class="acquire-dialog-body">
      <div class="dialog-heading">
        <p class="eyebrow">安装与交付</p>
        <button class="icon-button dialog-close" aria-label="关闭获取安装包" @click="close">
          <AppIcon name="close" />
        </button>
      </div>
      <h2 id="acquire-title">获取安装包</h2>
      <p class="dialog-description">
        安装包可直接下载，内含 Python 运行时、脚本依赖库和 DWG 转换组件，无需另行安装 Python。公司专属的配置包由服务方单独交付，不随安装包公开分发。
      </p>
      <p class="release-meta" data-stagger>
        <span class="mono">v{{ release.version }}</span><span aria-hidden="true"> · </span
        ><span>{{ release.date ? `${release.date} 发布` : '发布日期待定' }}</span>
      </p>
      <section class="acquire-platforms" data-stagger aria-labelledby="acquire-platforms-title">
        <h3 id="acquire-platforms-title">选择您的电脑</h3>
        <div v-if="platform === 'mobile'" class="acquire-mobile-note">
          <p>
            您正在使用手机或平板。安装包需要在 Mac 或 Windows 电脑上安装，可以把本页链接发到电脑上打开。
          </p>
          <button type="button" class="button button-outline button-small" @click="copyPage">
            复制页面链接
          </button>
        </div>
        <ul class="platform-cards package-downloads">
          <PlatformCard
            v-for="item in ordered"
            :key="item.platform"
            :item="item"
            :matched="platform === item.platform"
            :base="release.base"
          />
        </ul>
      </section>
      <section class="acquire-config" data-stagger aria-labelledby="acquire-config-title">
        <div class="acquire-config-copy">
          <h3 id="acquire-config-title">配置包</h3>
          <p>
            配置包由服务方按贵司环境整理并交付，是一个 .zip 文件，内含
            <code class="mono">zhitong.config.json</code>：公司的火山引擎对象存储（TOS）地址、区域、桶名、目录前缀、访问密钥和公司名；需要火山引擎运维时，还可包含
            SSH 主机别名与私钥、ve 命令行的 profile 名称（不含 ve 的密钥）。
          </p>
          <p>导入时系统校验内容，把密钥写入本机凭据存储，不在对话中显示。导入后请删除下载目录里的配置包，不要转发。</p>
          <RouterLink class="text-link" to="/docs/config-package/" @click="close"
            >读文档：导入配置包<AppIcon name="arrow"
          /></RouterLink>
        </div>
        <ConfigPackageStrip :class="{ 'is-playing': playing }" />
      </section>
      <section v-if="showContact" class="acquire-contact" data-stagger aria-labelledby="acquire-contact-title">
        <h3 id="acquire-contact-title">联系服务方</h3>
        <p>配置包、安装与使用问题，请联系服务方。</p>
        <dl>
          <template v-if="contact.provider">
            <dt>服务方</dt>
            <dd>{{ contact.provider }}</dd>
          </template>
          <template v-if="contact.person">
            <dt>联系人</dt>
            <dd>{{ contact.person }}</dd>
          </template>
          <template v-if="phone && phone.kind === 'phone'">
            <dt>电话</dt>
            <dd><a class="mono" :href="phone.href">{{ phone.value }}</a></dd>
          </template>
          <template v-if="email && email.kind === 'email'">
            <dt>邮箱</dt>
            <dd><a :href="email.href">{{ email.value }}</a></dd>
          </template>
          <template v-if="wechat">
            <dt>微信</dt>
            <dd>
              <span ref="wechatEl" class="mono">{{ wechat.value }}</span>
              <button type="button" class="icon-button" aria-label="复制微信号" @click="copyWechat">
                <AppIcon name="copy" />
              </button>
            </dd>
          </template>
          <template v-if="contact.hours">
            <dt>服务时间</dt>
            <dd>{{ contact.hours }}</dd>
          </template>
        </dl>
      </section>
      <button class="button button-outline full-width acquire-close-mobile" @click="close">关闭</button>
    </div>
  </BaseDialog>
</template>
