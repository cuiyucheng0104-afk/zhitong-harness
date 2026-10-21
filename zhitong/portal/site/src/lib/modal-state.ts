/**
 * 全站模态状态：BaseDialog 与说明卡底部弹层打开时登记，useAutoplay 以 `dialog` 原因暂停（00 章 §6.3）。
 */
import { computed, ref } from 'vue';

const count = ref(0);

/** 是否有任一模态对话框打开。 */
export const anyModalOpen = computed(() => count.value > 0);

/** 登记一个打开的模态；返回撤销函数（重复调用无效）。 */
export function registerModal(): () => void {
  count.value += 1;
  let done = false;
  return () => {
    if (done) return;
    done = true;
    count.value = Math.max(0, count.value - 1);
  };
}
