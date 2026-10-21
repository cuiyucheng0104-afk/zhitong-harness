/**
 * 当前章节跟踪（01 章 §14.1）。由 ScrollTrigger（或其 IntersectionObserver 退路）调用 `toggle`；
 * 点击导航时 `lock` 乐观设置并锁定，避免滚动途经中间章节时来回跳。
 */
import { readonly, ref, type Ref } from 'vue';

export interface ScrollSpy<T extends string> {
  active: Readonly<Ref<T | ''>>;
  toggle(id: T, on: boolean): void;
  lock(id: T, ms?: number): void;
  unlock(): void;
}

/**
 * 创建章节跟踪器。
 * @param ids - 参与跟踪的章节 id。
 * @returns 跟踪器。
 */
export function useScrollSpy<T extends string>(ids: readonly T[]): ScrollSpy<T> {
  const active = ref('') as Ref<T | ''>;
  const on = new Set<T>();
  let locked = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function settle() {
    // 多个章节同时为真时（相邻章节交界），取 ids 中靠后的那个：阅读线已越过它的上沿。
    const list = ids.filter((id) => on.has(id));
    return list.at(-1) ?? '';
  }

  function toggle(id: T, value: boolean) {
    if (value) on.add(id);
    else on.delete(id);
    if (locked) return;
    if (value) active.value = id;
    else if (active.value === id) active.value = settle();
  }

  function unlock() {
    clearTimeout(timer);
    if (!locked) return;
    locked = false;
    active.value = settle();
  }

  function lock(id: T, ms = 1600) {
    clearTimeout(timer);
    locked = true;
    active.value = id;
    timer = setTimeout(unlock, ms);
  }

  return { active: readonly(active) as Readonly<Ref<T | ''>>, toggle, lock, unlock };
}
