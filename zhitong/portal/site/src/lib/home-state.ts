/**
 * 首页与常驻顶栏之间共享的状态：章节跟踪器（01 章 §3）与首页挂载标志。
 * HomePage 创建 ScrollTrigger 并调用 `navSpy.toggle`；SiteHeader 读 `navSpy.active`；HeaderRuler 在 `homeReady` 后测量章节。
 */
import { ref } from 'vue';
import { useScrollSpy } from '../composables/useScrollSpy';
import { NAV_LINKS, type NavSectionId } from '../data/nav';
import { scrollToSection } from './smooth-scroll';

export const NAV_IDS = NAV_LINKS.map((l) => l.id) as readonly NavSectionId[];

/** 首页导航四章的跟踪器（全站一个）。 */
export const navSpy = useScrollSpy(NAV_IDS);

/** HomePage 已挂载且章节测量可用（动效块加载成功或已退回 IntersectionObserver）。 */
export const homeReady = ref(false);

/**
 * 首页内跳到某章：滚到该章 h2（偏移 = 顶栏 + 24px）并聚焦，导航四章乐观更新当前项。
 * @param id - 章节根元素 id，或 'main' / 'demo' 等任意元素 id。
 * @param instant - 直接定位。
 * @returns 滚动完成时 resolve。
 */
export function goToSection(id: string, instant = false): Promise<void> {
  const node = document.getElementById(id);
  const title = id === 'main' || id === 'demo' ? null : node?.querySelector<HTMLElement>('h2[id]');
  const isNav = (NAV_IDS as readonly string[]).includes(id);
  if (isNav) navSpy.lock(id as NavSectionId);
  return scrollToSection(title?.id || id, true, instant).then(() => {
    if (isNav) navSpy.unlock();
  });
}
