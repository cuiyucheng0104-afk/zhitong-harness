/**
 * 小动画按需加载表（03 章 §1.5.7）：首次打开对应说明卡时才请求该块（AC-03-19）。
 */
import type { MicroKind } from '../../../data/roles';
import type { MicroModule } from './types';

export const MICROS: Record<MicroKind, () => Promise<MicroModule>> = {
  inventory: () => import('./MicroInventory.vue'),
  reconcile: () => import('./MicroReconcile.vue'),
  extract: () => import('./MicroExtract.vue'),
  draft: () => import('./MicroDraft.vue'),
  review: () => import('./MicroReview.vue'),
  benchmark: () => import('./MicroBenchmark.vue'),
  codes: () => import('./MicroCodes.vue'),
  plan: () => import('./MicroPlan.vue'),
  archive: () => import('./MicroArchive.vue'),
  entry: () => import('./MicroEntry.vue'),
  answer: () => import('./MicroAnswer.vue'),
  ops: () => import('./MicroOps.vue'),
};

const cache = new Map<MicroKind, Promise<MicroModule>>();

/**
 * 加载一个小动画（同一种只请求一次）。
 * @param kind - 小动画种类。
 * @returns 模块。
 */
export function loadMicro(kind: MicroKind): Promise<MicroModule> {
  let p = cache.get(kind);
  if (!p) {
    p = MICROS[kind]();
    cache.set(kind, p);
    p.catch(() => cache.delete(kind));
  }
  return p;
}
