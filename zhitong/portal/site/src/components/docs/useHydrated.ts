/** 水合后为 true（预渲染与无 JS 时为 false）：复制按钮、按键提示、搜索触发器只在水合后出现（06 章 §8.1、§13）。 */
import { onMounted, ref } from 'vue';

/**
 * @returns 挂载后变为 true 的 ref。
 */
export function useHydrated() {
  const hydrated = ref(false);
  onMounted(() => (hydrated.value = true));
  return hydrated;
}
