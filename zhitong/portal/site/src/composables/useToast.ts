/**
 * 复制提示（01 章 §11、§14.2）。全站一个 `ZtToast`（App.vue 根部）读取这里的状态。
 * 朗读写入当前最上层打开的 `<dialog>` 内的 `[data-dialog-status]`，没有打开的对话框时写入 `#page-status`。
 */
import { reactive, readonly } from 'vue';

export type ToastTone = 'ok' | 'error';

interface ToastState {
  message: string;
  tone: ToastTone;
  /** 停留毫秒数。 */
  duration: number;
  /** 每次 show 递增，ZtToast 据此重置计时。 */
  seq: number;
}

const state = reactive<ToastState>({ message: '', tone: 'ok', duration: 1600, seq: 0 });

/** 只读的提示状态（ZtToast 使用）。 */
export const toastState = readonly(state);

/**
 * 把一句话写进合适的朗读区。
 * @param message - 朗读文字。
 */
export function announce(message: string) {
  if (typeof document === 'undefined') return;
  const dialogs = [...document.querySelectorAll<HTMLDialogElement>('dialog[open]')];
  const region =
    dialogs.at(-1)?.querySelector<HTMLElement>('[data-dialog-status]') ??
    document.getElementById('page-status');
  if (!region) return;
  region.textContent = '';
  // 先清空再写入，保证相同文字也会被再次朗读。
  queueMicrotask(() => {
    region.textContent = message;
  });
}

/**
 * 使用提示条。
 * @returns `show(message, { tone, duration })`；默认停留 1600ms，错误 3200ms。
 */
export function useToast() {
  return {
    show(message: string, opts: { tone?: ToastTone; duration?: number } = {}) {
      const tone = opts.tone ?? 'ok';
      state.message = message;
      state.tone = tone;
      state.duration = opts.duration ?? (tone === 'error' ? 3200 : 1600);
      state.seq += 1;
      announce(message);
    },
  };
}
