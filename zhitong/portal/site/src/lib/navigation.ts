/** 页签键盘与锚点导航。`scrollToSection` 的实现在 smooth-scroll.ts（00 章 §5.3）。 */
export { scrollToSection, scrollToTop } from './smooth-scroll';

/**
 * 页签组键盘操作：方向键、Home、End，焦点与选择同步，首尾循环（00 章 §10）。
 * @param event - tablist 上的 keydown 事件。
 */
export function onTabKeydown(event: KeyboardEvent) {
  const list = event.currentTarget as HTMLElement;
  const tabs = [...list.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  const index = tabs.indexOf(event.target as HTMLButtonElement);
  if (index < 0) return;
  let next = index;
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % tabs.length;
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp')
    next = (index - 1 + tabs.length) % tabs.length;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = tabs.length - 1;
  else return;
  event.preventDefault();
  tabs[next]?.focus();
  tabs[next]?.click();
}
