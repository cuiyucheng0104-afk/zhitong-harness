/**
 * 获取安装包弹层的全站开关。任何组件调用 `openAcquire(trigger)` 打开 App.vue 中常驻的 AcquireDialog；
 * 关闭后焦点回到 trigger（01 章 §7.7）。
 */
import { shallowReactive, shallowReadonly } from 'vue';

const state = shallowReactive<{ open: boolean; trigger: HTMLElement | null }>({ open: false, trigger: null });

/** 只读状态（App.vue 绑定到 AcquireDialog）。 */
export const acquireState = shallowReadonly(state);

/**
 * 打开获取弹层。
 * @param trigger - 触发元素或其事件；关闭后焦点回到它。
 */
export function openAcquire(trigger?: HTMLElement | Event | null) {
  const el =
    trigger instanceof Event
      ? (trigger.currentTarget as HTMLElement | null)
      : (trigger ?? (document.activeElement as HTMLElement | null));
  state.trigger = el instanceof HTMLElement ? el : null;
  state.open = true;
}

/** 关闭获取弹层。 */
export function closeAcquire() {
  state.open = false;
}

/** v-model 写回。 */
export function setAcquireOpen(value: boolean) {
  state.open = value;
}
