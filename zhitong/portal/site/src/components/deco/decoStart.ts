/**
 * 装饰启动闸（07 章 §3.2 第 1 步；00 章 §5.4.6）：首屏可交互之后才启动装饰。
 * 等 `requestIdleCallback(…, { timeout: 1500 })`（不支持时 `setTimeout` 1500 ms），且距页面载入 ≥ 1.5 s，
 * 再等 `document.fonts.ready`（画布文字用自托管 IBM Plex Mono）。
 * 这个文件很小，由各装饰外壳静态引用；画布实现都在懒加载块里。
 */

/** 首屏可交互的下限（毫秒，相对 performance 时间原点）。 */
export const DECO_START_FLOOR_MS = 1500;

type IdleWindow = Window & {
  requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
};

function idle(): Promise<void> {
  return new Promise((resolve) => {
    const w = window as IdleWindow;
    if (typeof w.requestIdleCallback === 'function') w.requestIdleCallback(() => resolve(), { timeout: 1500 });
    else window.setTimeout(resolve, 1500);
  });
}

function floor(): Promise<void> {
  const now = typeof performance !== 'undefined' ? performance.now() : DECO_START_FLOOR_MS;
  const wait = Math.max(0, DECO_START_FLOOR_MS - now);
  return wait > 0 ? new Promise((r) => window.setTimeout(r, wait)) : Promise.resolve();
}

let gate: Promise<void> | undefined;

/**
 * 装饰可以启动时 resolve（多次调用共享同一 Promise）。
 * @returns idle、1.5 s 下限与字体都就绪后 resolve；字体加载失败也照常 resolve。
 */
export function whenDecoReady(): Promise<void> {
  gate ??= Promise.all([idle(), floor()])
    .then(() => (document.fonts?.ready ?? Promise.resolve()).catch(() => undefined))
    .then(() => undefined);
  return gate;
}

/** 测试用：重置启动闸。 */
export function resetDecoGate() {
  gate = undefined;
}
