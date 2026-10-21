import { createWebHistory } from 'vue-router';
import { createPortalApp } from './create-app';
import { applyHead } from './lib/head';
import { hydration } from './pages/home-sections';
import './styles/index.css';

const root = document.getElementById('app')!;
let hydrated = false;
const { app, router } = createPortalApp(createWebHistory('/'), (r) => {
  if (!root.firstElementChild) return false;
  // 服务器对未知地址回退成别的页面的预渲染 HTML 时（如 vite preview 回首页），
  // 页面类型与当前路由不符：改为客户端渲染，避免水合不匹配；head 在首次导航时更新（01 章 AC-01-30）。
  const served = document.documentElement.dataset.layout;
  hydrated = served === r.resolve(window.location.href.slice(window.location.origin.length)).meta.layout;
  return hydrated;
});
router.afterEach((to, from) => {
  document.documentElement.dataset.layout = to.meta.layout;
  if (from.matched.length || !hydrated) applyHead(to.meta);
});
await router.isReady();
app.mount(root);
hydration.initial = false;
