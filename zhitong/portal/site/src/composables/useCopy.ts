/**
 * 复制（01 章 §14.3）：clipboard API → 屏幕外 textarea + execCommand → 失败时提示并选中 fallbackSelect 的文本。
 */
import { useToast } from './useToast';

export const COPY_FAILED = '复制失败，请手动选择文本';

function legacyCopy(text: string): boolean {
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.left = '-9999px';
  area.style.top = '0';
  document.body.append(area);
  try {
    area.select();
    return document.execCommand('copy');
  } catch {
    // execCommand 在部分环境会抛错，视为复制失败。
    return false;
  } finally {
    area.remove();
  }
}

function selectText(el: HTMLElement) {
  const range = document.createRange();
  range.selectNodeContents(el);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

/**
 * 使用复制。
 * @returns `copy(text, { success, fallbackSelect })`，成功时 resolve true。
 */
export function useCopy() {
  const toast = useToast();
  return {
    async copy(text: string, opts: { success: string; fallbackSelect?: HTMLElement | null }) {
      let ok = false;
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(text);
          ok = true;
        }
      } catch {
        // 权限被拒或非安全上下文，改用 execCommand。
        ok = false;
      }
      if (!ok) ok = legacyCopy(text);
      if (ok) toast.show(opts.success);
      else {
        toast.show(COPY_FAILED, { tone: 'error' });
        if (opts.fallbackSelect) selectText(opts.fallbackSelect);
      }
      return ok;
    },
  };
}
