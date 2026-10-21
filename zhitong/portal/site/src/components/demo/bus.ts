/**
 * 首屏三块之间的共享接口（02 章 §1.5、§2.5.6、§7.4）：
 * - HeroSection 的“看它怎么工作”调用 `demoBus.watch(trigger)`；
 * - PrinciplesStrip 读 `currentPrinciple`，“看示例”调用 `demoBus.showScene(id)`；
 * - WorkDemo 挂载时登记自己，卸载时注销。
 * 这样首屏三个组件互相联动而不要求 HomePage 转发事件（HomePage 归底座）。
 */
import { ref, shallowRef } from 'vue';
import type { Principle } from '../../data/demo';
import type { SceneId } from '../../types/portal';

export interface DemoHandle {
  /** 从场景 1 的 0 s 播放：清除 user（含置顶）与 done。 */
  restart(): void;
  /** 切到场景并作为响应片段从 0 s 播放；source=true 时直接到终态并打开出处弹层。 */
  showScene(id: SceneId, opts?: { source?: boolean } | boolean, trigger?: HTMLElement | null): Promise<void>;
  /** 首屏次按钮：并排且示例可见时原地重播，否则先滚到 #demo 再重播（§1.5）。 */
  watch(trigger?: HTMLElement | null): Promise<void>;
}

/** 当前登记的示例（首页只有一个）。 */
export const demoHandle = shallowRef<DemoHandle | null>(null);

/** 原则条点亮项；null = 三项都不点亮。 */
export const currentPrinciple = ref<Principle | null>(null);

export const demoBus = {
  restart: () => demoHandle.value?.restart(),
  showScene: (id: SceneId) => demoHandle.value?.showScene(id) ?? Promise.resolve(),
  watch: (trigger?: HTMLElement | null) => demoHandle.value?.watch(trigger) ?? Promise.resolve(),
};
