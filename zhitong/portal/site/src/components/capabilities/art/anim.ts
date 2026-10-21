/**
 * SVG 动画元素的标注（04 章 §7.1「SVG 文字与通用规则」）。
 * `A('名')` → `data-a="名"`；`A('名', true)` 另加 `data-transient`（终帧不出现）。
 * §7.1 另写了 `data-anim`；它与 `data-a` 一一重合，单独输出会让 12 段 SVG 超出 60 KB 预算（AC-04-28，实测 63.8 KB），
 * 所以复位段改用 `[data-a]` 选择全部动画元素（`ART_ANIM_SELECTOR`）。
 */
export const ART_ANIM_SELECTOR = '[data-a]';

export function A(name: string, transient = false): Record<string, string> {
  const attrs: Record<string, string> = { 'data-a': name };
  if (transient) attrs['data-transient'] = '';
  return attrs;
}

/** 只标 `data-transient`（不参与复位）。 */
export const T = { 'data-transient': '' } as const;
