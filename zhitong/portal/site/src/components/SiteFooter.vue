<script setup lang="ts">
/**
 * 页脚（05 章 §5；00 章 §14 裁定 4）：品牌一句话、产品 / 文档 / 联系三栏、法律行、说明行、回到顶部，末行为 07 章 `DecoFooterMark`。
 * - `context="home"`：产品链接写 `#<id>`，点击经 HomePage 的 `navigate`（Lenis 滚动并聚焦章节标题）；
 *   `context="docs"`：写 `/#<id>` 普通链接。
 * - 联系栏只在有可联系渠道时渲染（无联系栏时文档栏占 6 列）；法律行空串的项不渲染，不出现占位文字。
 * - 回到顶部：无 JS 时是 `<a href="#main">`，水合后换成按钮（`scrollToTop`，完成后聚焦 `#main`）。
 */
import { computed, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';
import AppIcon from './AppIcon.vue';
import ContactList from './sections05/ContactList.vue';
import DecoFooterMark from './deco/DecoFooterMark.vue';
import brandMark from '../../assets/brand-mark.svg';
import { DOC_ROUTES } from '../docs/routes';
import { contactChannels, siteConfig } from '../site.config';
import { scrollToTop } from '../lib/smooth-scroll';

const props = withDefaults(defineProps<{ context?: 'home' | 'docs' }>(), { context: 'home' });
const emit = defineEmits<{ acquire: [event: MouseEvent]; navigate: [id: string] }>();

interface FooterLink {
  label: string;
  href: string;
}

const PRODUCT: { id: string; label: string }[] = [
  { id: 'demo', label: '工作示例' },
  { id: 'roles', label: '适用岗位' },
  { id: 'problem', label: '它解决什么' },
  { id: 'capabilities', label: '产品能力' },
  { id: 'workflow', label: '使用流程' },
  { id: 'trust', label: '数据与复核' },
  { id: 'install', label: '安装与交付' },
  { id: 'faq', label: '常见问题' },
];

const doc = (slug: string) => {
  const r = DOC_ROUTES.find((d) => d.slug === slug);
  if (!r) throw new Error(`文档路由表缺少 ${slug}`);
  return { label: r.title, href: r.path };
};
const DOCS: FooterLink[] = [
  doc('quick-start'),
  doc('install'),
  doc('config-package'),
  { label: '12 项能力', href: '/docs/#按任务找' },
  doc('security'),
  doc('troubleshooting'),
];

const legal = siteConfig.legal;
const showContact = contactChannels(siteConfig.contact).length > 0;
const year = new Date().getFullYear();
const hydrated = ref(false);
const productHref = (id: string) => (props.context === 'home' ? `#${id}` : `/#${id}`);
const legalItems = computed(() => ({
  company: legal.company.trim(),
  icp: legal.icp.trim(),
  psb:
    legal.psbText.trim() && legal.psbHref.trim()
      ? { text: legal.psbText.trim(), href: legal.psbHref.trim() }
      : null,
  privacy: legal.privacyHref.trim(),
}));

function onProduct(e: MouseEvent, id: string) {
  if (props.context !== 'home') return;
  e.preventDefault();
  emit('navigate', id);
}
function toTop() {
  void scrollToTop();
}
onMounted(() => (hydrated.value = true));
</script>

<template>
  <footer class="site-footer" :class="{ 'has-contact': showContact }">
    <div class="container">
      <div class="footer-grid">
        <div class="footer-brand" data-reveal="block">
          <a
            class="brand"
            :href="context === 'home' ? '#main' : '/'"
            aria-label="智通数工AI，返回首页"
            ><img class="brand-mark" :src="brandMark" alt="" width="36" height="36" /><span
              >智通数工<span class="brand-ai">AI</span></span
            ></a
          >
          <p class="footer-tagline">
            智通数工AI：把造价咨询里重复的读资料、算数、核对和归档，收进一次对话。
          </p>
          <p class="footer-site">官网：<span class="mono">https://ztsgai.com</span></p>
          <button
            v-magnetic
            type="button"
            class="button button-primary footer-acquire"
            @click="emit('acquire', $event)"
          >
            <span data-magnetic-label>获取安装包</span><AppIcon name="arrow" class="icon" />
          </button>
        </div>
        <div class="footer-cols" data-reveal="stagger">
          <nav class="footer-col footer-product" aria-label="产品">
            <p class="footer-col-title" aria-hidden="true">产品</p>
            <ul>
              <li v-for="link in PRODUCT" :key="link.id">
                <a
                  class="footer-link"
                  :href="productHref(link.id)"
                  @click="onProduct($event, link.id)"
                  >{{ link.label }}</a
                >
              </li>
            </ul>
          </nav>
          <nav class="footer-col footer-docs" aria-label="文档">
            <p class="footer-col-title" aria-hidden="true">文档</p>
            <ul>
              <li v-for="link in DOCS" :key="link.href">
                <RouterLink class="footer-link" :to="link.href">{{ link.label }}</RouterLink>
              </li>
            </ul>
          </nav>
          <section v-if="showContact" class="footer-col footer-contact" aria-label="联系">
            <p class="footer-col-title" aria-hidden="true">联系</p>
            <ContactList />
          </section>
        </div>
      </div>
      <div class="footer-bottom">
        <p class="footer-legal" data-reveal="block">
          <span v-if="legalItems.company" class="footer-legal-item"
            >© {{ year }} {{ legalItems.company }}</span
          >
          <span v-if="legalItems.icp" class="footer-legal-item"
            ><a
              class="footer-link"
              href="https://beian.miit.gov.cn/"
              target="_blank"
              rel="noopener noreferrer"
              >{{ legalItems.icp }}<AppIcon name="external" class="footer-ext" /><span
                class="sr-only"
                >（在新窗口打开）</span
              ></a
            ></span
          >
          <span v-if="legalItems.psb" class="footer-legal-item"
            ><a
              class="footer-link"
              :href="legalItems.psb.href"
              target="_blank"
              rel="noopener noreferrer"
              >{{ legalItems.psb.text }}<AppIcon name="external" class="footer-ext" /><span
                class="sr-only"
                >（在新窗口打开）</span
              ></a
            ></span
          >
          <span v-if="legalItems.privacy" class="footer-legal-item"
            ><RouterLink class="footer-link" :to="legalItems.privacy">隐私说明</RouterLink></span
          >
        </p>
        <button
          v-if="hydrated"
          v-magnetic
          type="button"
          class="button button-outline footer-top"
          aria-label="回到页面顶部"
          @click="toTop"
        >
          <span data-magnetic-label>回到顶部</span
          ><AppIcon name="arrow" class="icon footer-top-icon" />
        </button>
        <a v-else class="button button-outline footer-top" href="#main" aria-label="回到页面顶部"
          ><span>回到顶部</span><AppIcon name="arrow" class="icon footer-top-icon"
        /></a>
        <p class="footer-note">页面中的项目、金额与文件均为示例数据</p>
      </div>
      <div class="footer-deco-row" aria-hidden="true">
        <DecoFooterMark />
      </div>
    </div>
  </footer>
</template>
