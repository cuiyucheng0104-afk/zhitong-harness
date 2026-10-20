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

export function scrollToSection(id: string, focus = true, instant = false) {
  const node = document.getElementById(id);
  if (!node) return;
  const header = document.querySelector('.site-header')?.getBoundingClientRect().height ?? 72;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollTo({
    top: Math.max(0, node.getBoundingClientRect().top + window.scrollY - header - 24),
    behavior: instant || reduced ? 'instant' : 'smooth',
  });
  if (focus) node.focus({ preventScroll: true });
  history.replaceState(null, '', `#${id}`);
}
