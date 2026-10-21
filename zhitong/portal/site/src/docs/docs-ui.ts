/**
 * 文档子站的共享界面状态与动作（06 章 §8.1、§8.5、§9.3）：
 * 搜索对话框与目录抽屉的开关、搜索块预取、锚点跳转。文档页不加载 GSAP 与 Lenis，滚动全部用原生 API。
 */
import { reactive } from 'vue';
import { prefersReducedMotion } from '../lib/motion';
import type { Searcher } from './search';

export const docsUi = reactive({
  searchOpen: false,
  searchTrigger: null as HTMLElement | null,
  drawerOpen: false,
});

let searchModule: Promise<typeof import('./search')> | undefined;

/** 预取搜索逻辑块与索引（指针移到或聚焦搜索触发器时调用，§8.5）。失败时静默，打开对话框时再显示失败文案。 */
export function prefetchSearch(): Promise<Searcher> {
  searchModule ??= import('./search');
  const ready = searchModule.then((m) => m.loadSearcher());
  ready.catch(() => {
    // 预取失败不打扰访客；对话框打开时重新载入并显示失败文案。
  });
  return ready;
}

/**
 * 打开搜索对话框。
 * @param trigger - 触发元素（关闭后焦点回到它）；省略时取当前焦点元素。
 */
export function openSearch(trigger?: HTMLElement | null) {
  if (docsUi.searchOpen) return;
  docsUi.searchTrigger =
    trigger ?? (typeof document !== 'undefined' && document.activeElement instanceof HTMLElement ? document.activeElement : null);
  docsUi.searchOpen = true;
  void prefetchSearch();
}

/**
 * 跳到本页标题（§9.3）：scrollIntoView（依赖 scroll-margin-top）+ replaceState 写 `#id` + 焦点移到标题。
 * @param id - 标题 id。
 * @returns 滚动结束（`scrollend`，不支持时 800ms 后）时 resolve。
 */
export function scrollToHeading(id: string): Promise<void> {
  const el = document.getElementById(id);
  if (!el) return Promise.resolve();
  const instant = prefersReducedMotion();
  const done = new Promise<void>((resolve) => {
    if (instant) return resolve();
    let timer = 0;
    const finish = () => {
      window.removeEventListener('scrollend', finish);
      clearTimeout(timer);
      resolve();
    };
    if ('onscrollend' in window) window.addEventListener('scrollend', finish, { once: true });
    timer = window.setTimeout(finish, 800);
  });
  el.scrollIntoView({ behavior: instant ? 'instant' : 'smooth', block: 'start' });
  history.replaceState(history.state, '', `${location.pathname}${location.search}#${encodeURIComponent(id)}`);
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
  el.focus({ preventScroll: true });
  return done;
}

/** 是否为 Apple 设备（按键提示显示 ⌘ K）。只在水合后调用。 */
export function isApple(): boolean {
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
  return /mac|iphone|ipad|ipod/i.test(nav.userAgentData?.platform || nav.platform || nav.userAgent);
}
