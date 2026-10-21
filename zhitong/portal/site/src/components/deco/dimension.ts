/**
 * D4 尺寸线分隔的几何与进度映射（07 章 §8.2），与 DOM 分离，便于单测。
 */

/** 栏间距（00 章 §4.4）。 */
export const COL_GAP = 24;

/**
 * 千位空格：`1248` → `1 248`。
 * @param n - 整数。
 * @returns 文字。
 */
export function formatDimension(n: number): string {
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

/**
 * 栏刻度：12/8/4 栏网格每个栏间距的两缘（“连续尺寸”）。
 * @param W - 容器宽。
 * @param cols - 栏数。
 * @param gap - 栏间距。
 * @returns 刻度 x（升序）。
 */
export function columnEdges(W: number, cols: number, gap = COL_GAP): number[] {
  const colW = (W - (cols - 1) * gap) / cols;
  const xs: number[] = [];
  for (let k = 1; k < cols; k++) {
    const right = k * colW + (k - 1) * gap;
    xs.push(right, right + gap);
  }
  return xs;
}

/** 视口宽对应的栏数：≥ 1024 为 12，768–1023 为 8，≤ 767 为 4。 */
export function columnsFor(viewport: number): number {
  return viewport >= 1024 ? 12 : viewport >= 768 ? 8 : 4;
}

export interface DimensionState {
  /** 尺寸线两端（线性，`EASE.linear`）。 */
  x1: number;
  x2: number;
  /** scaleX（以中点为原点）。 */
  scale: number;
  /** 数字（四舍五入）与其透明度 `min(1, 4p)`。 */
  value: number;
  textOpacity: number;
  /** 起止符与尺寸界线伸出量（p ≥ 0.9 后在剩余进度内 0 → 1）。 */
  ext: number;
  /** 端部轴号透明度（p ≥ 0.96 后 0 → 1）。 */
  bubble: number;
}

/**
 * `set(p)` 的状态映射。
 * @param p - 滚动进度 0..1。
 * @param W - 容器宽。
 * @returns 各部件状态。
 */
export function dimensionState(p: number, W: number): DimensionState {
  const q = Math.max(0, Math.min(1, p));
  return {
    x1: W / 2 - (W * q) / 2,
    x2: W / 2 + (W * q) / 2,
    scale: q,
    value: Math.round(W * q),
    textOpacity: Math.min(1, 4 * q),
    ext: q >= 0.9 ? Math.min(1, (q - 0.9) / 0.1) : 0,
    bubble: q >= 0.96 ? Math.min(1, (q - 0.96) / 0.04) : 0,
  };
}

/** 参考实现的阻尼（无 GSAP 时等价于 scrub 0.6）：`shown += (target − shown)·(1 − e^(−3dt/0.6))`。 */
export function dampProgress(shown: number, target: number, dt: number, scrub = 0.6): number {
  return shown + (target - shown) * (1 - Math.exp((-3 * dt) / scrub));
}
