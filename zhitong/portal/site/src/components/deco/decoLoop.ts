/**
 * 装饰共享运行时（07 章 §3.1–3.2）：rAF 循环、可见性、设备像素比、尺寸、每帧预算与模式判定。
 *
 * - 模式：减少动效 → `still`；`(hover: hover) and (pointer: fine)` 且视口 ≥ 768px → `live`；否则 `once`
 *   （只播入场，结束后停在终帧，不再请求帧）。`prefers-reduced-motion` 变化时整体重建。
 * - 可见性：挂 00 章 §6.8 的 `useInView`（由组件传入 `view`）；可见比例 < 阈值或 `document.hidden` 时取消 rAF，
 *   内部时钟停止，恢复后从原处继续，不重播。未传 `view` 时自建 IntersectionObserver（测试与独立页面用）。
 * - 尺寸：ResizeObserver 观察宿主；`dpr = min(devicePixelRatio, dprCap)`；画布 `width = round(cssW × dpr)`，
 *   `setTransform(dpr, 0, 0, dpr, 0, 0)`。
 * - 预算：连续 90 帧 `tick` 超过 `budgetMs` 时 `dprCap` 降为 1 并重建一次。开发构建记录
 *   `performance.measure('deco:<id>')`，并把统计挂在 `window.__deco.stats`（只是数据，不是监听）。
 * - `live` 模式的装饰可加入同屏调度（`schedule: true`，§3.3），通过 `granted` 判断能否跑待机动画。
 * - 销毁时取消 rAF、断开所有 Observer 与监听，不在 window 上留下监听。
 */
import { watch, type Ref } from 'vue';
import { registerDeco, type DecoSlot } from './decoScheduler';

export type DecoMode = 'live' | 'once' | 'still';

export interface DecoLoopOptions {
  /** 可见比例阈值，默认 0.25；挂 00 §6.8 的 useInView */
  threshold?: number;
  /** 一帧。t 为组件内部时钟（只在运行时前进，暂停后从原处继续），dt 截到 ≤ 0.05 s。
   *  返回 false 表示画面已静止：循环休眠，直到 wake()。 */
  tick(t: number, dt: number): boolean;
  /** 尺寸或 DPR 变化后重建（cssW、cssH 为 CSS 像素，dpr 已封顶） */
  resize(cssW: number, cssH: number, dpr: number): void;
  /** 绘制静态终帧：减少动效、'once' 播放结束、调度器挂起时调用 */
  still(): void;
  dprCap?: number; // 默认 2
  budgetMs?: number; // 默认 3
  /** 统计与 performance.measure 用的编号（如 'D1'）。 */
  id?: string;
  /** useInView 的结果（active、ratio）；不传则自建 IntersectionObserver。 */
  view?: { active: Readonly<Ref<boolean>>; ratio: Readonly<Ref<number>> };
  /** 自定义模式判定（默认按 §3.2 第 2 步）。 */
  resolveMode?: () => DecoMode;
  /** 加入同屏调度（只对 live 生效）。 */
  schedule?: boolean;
  /** 模式确定或重建后调用。 */
  onMode?: (mode: DecoMode) => void;
}

export interface DecoLoop {
  readonly mode: DecoMode;
  readonly running: boolean;
  /** live 模式下是否持有待机动画运行权（未加入调度时恒为 true）。 */
  readonly granted: boolean;
  /** 当前内部时钟（秒）。 */
  readonly time: number;
  wake(): void; // 指针、滚动等输入后调用
  replay(): void; // 时钟归零重新入场
  destroy(): void; // 组件卸载时：取消 rAF，断开所有 Observer 与监听
}

/** 每个装饰的帧统计（开发构建挂在 window.__deco.stats）。 */
export interface DecoStats {
  frames: number;
  mean: number;
  peak: number;
  last: number;
  mode: DecoMode;
}

export const decoStats: Record<string, DecoStats> = {};

const OVER_BUDGET_FRAMES = 90;

function media(query: string): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches;
}

/**
 * 默认模式判定（07 章 §3.2 第 2 步）。
 * @returns 当前环境下的装饰模式。
 */
export function resolveDecoMode(): DecoMode {
  if (media('(prefers-reduced-motion: reduce)')) return 'still';
  if (media('(hover: hover) and (pointer: fine)') && window.innerWidth >= 768) return 'live';
  return 'once';
}

/**
 * 封顶后的设备像素比。
 * @param cap - 上限（默认 2）。
 * @returns `min(devicePixelRatio, cap)`，至少 1。
 */
export function cappedDpr(cap = 2): number {
  const raw = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1;
  return Math.max(1, Math.min(raw, cap));
}

/**
 * 按 CSS 尺寸与 DPR 设置画布像素并重置变换。
 * @param canvas - 画布。
 * @param cssW - CSS 宽。
 * @param cssH - CSS 高。
 * @param dpr - 已封顶的 DPR。
 * @returns 2D 上下文（jsdom 等不支持时为 null）。
 */
export function sizeCanvas(canvas: HTMLCanvasElement, cssW: number, cssH: number, dpr: number): CanvasRenderingContext2D | null {
  const w = Math.round(cssW * dpr);
  const h = Math.round(cssH * dpr);
  if (canvas.width !== w) canvas.width = w;
  if (canvas.height !== h) canvas.height = h;
  let ctx: CanvasRenderingContext2D | null = null;
  try {
    ctx = canvas.getContext('2d');
  } catch (error) {
    // jsdom 未实现 getContext：装饰退回静态底
    void error;
    ctx = null;
  }
  ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

/** 1px 线对齐到像素中心：`round(v) + 0.5`。 */
export const crisp = (v: number) => Math.round(v) + 0.5;

function record(id: string, ms: number, mode: DecoMode) {
  const s = (decoStats[id] ??= { frames: 0, mean: 0, peak: 0, last: 0, mode });
  s.frames += 1;
  s.mean += (ms - s.mean) / s.frames;
  s.peak = Math.max(s.peak, ms);
  s.last = ms;
  s.mode = mode;
  if (import.meta.env?.DEV && typeof window !== 'undefined') {
    (window as Window & { __deco?: { stats: Record<string, DecoStats> } }).__deco = { stats: decoStats };
  }
}

/**
 * 创建装饰循环。
 * @param host - 宿主元素（ResizeObserver 观察它）。
 * @param canvas - 主画布（由循环设置像素尺寸）；没有画布时传 null。
 * @param opts - 回调与参数。
 * @returns 循环句柄。
 */
export function createDecoLoop(host: HTMLElement, canvas: HTMLCanvasElement | null, opts: DecoLoopOptions): DecoLoop {
  const threshold = opts.threshold ?? 0.25;
  const budget = opts.budgetMs ?? 3;
  const id = opts.id ?? 'deco';
  let dprCap = opts.dprCap ?? 2;
  let mode: DecoMode = (opts.resolveMode ?? resolveDecoMode)();
  let raf = 0;
  let last = -1;
  let t = 0;
  let sleeping = false;
  let done = false;
  let destroyed = false;
  let over = 0;
  let cssW = 0;
  let cssH = 0;
  let ownRatio = 0;
  let slot: DecoSlot | null = null;
  const cleanups: (() => void)[] = [];

  const ratio = () => (opts.view ? opts.view.ratio.value : ownRatio);
  const visible = () => {
    if (typeof document !== 'undefined' && document.hidden) return false;
    return opts.view ? opts.view.active.value : ownRatio >= threshold;
  };

  function cancel() {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    last = -1;
  }

  function schedule() {
    if (raf || destroyed || mode === 'still' || done || sleeping || !visible() || cssW === 0) return;
    raf = requestAnimationFrame(frame);
  }

  function frame(now: number) {
    raf = 0;
    if (destroyed || !visible()) {
      last = -1;
      return;
    }
    const dt = last < 0 ? 1 / 60 : Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    t += dt;
    const start = performance.now();
    const more = opts.tick(t, dt);
    const ms = performance.now() - start;
    record(id, ms, mode);
    if (import.meta.env?.DEV && typeof performance.measure === 'function') {
      try {
        performance.measure(`deco:${id}`, { start, duration: ms });
      } catch (error) {
        // 旧浏览器不支持带选项的 measure：只少一条开发统计
        void error;
      }
    }
    if (ms > budget) over += 1;
    else over = 0;
    if (over >= OVER_BUDGET_FRAMES && dprCap > 1) {
      over = 0;
      dprCap = 1;
      rebuildSize();
    }
    if (!more) {
      if (mode === 'once') {
        done = true;
        opts.still();
      } else sleeping = true;
      last = -1;
      return;
    }
    schedule();
  }

  function rebuildSize() {
    const dpr = cappedDpr(dprCap);
    if (canvas) sizeCanvas(canvas, cssW, cssH, dpr);
    opts.resize(cssW, cssH, dpr);
    if (mode === 'still' || done) opts.still();
  }

  function measure(w: number, h: number) {
    if (w === cssW && h === cssH) return;
    cssW = w;
    cssH = h;
    if (w === 0 || h === 0) return;
    rebuildSize();
    wake();
  }

  function wake() {
    if (destroyed) return;
    sleeping = false;
    schedule();
  }

  function onVisibility() {
    slot?.setRatio(visible() ? ratio() : 0);
    if (visible()) schedule();
    else cancel();
  }

  function setupSchedule() {
    slot?.release();
    slot = null;
    if (opts.schedule && mode === 'live') {
      slot = registerDeco(() => wake());
      slot.setRatio(visible() ? ratio() : 0);
    }
  }

  function rebuild() {
    cancel();
    mode = (opts.resolveMode ?? resolveDecoMode)();
    t = 0;
    done = false;
    sleeping = false;
    over = 0;
    setupSchedule();
    opts.onMode?.(mode);
    if (cssW && cssH) rebuildSize();
    schedule();
  }

  // 尺寸
  const rect = host.getBoundingClientRect();
  cssW = 0;
  cssH = 0;
  opts.onMode?.(mode);
  measure(Math.round(rect.width), Math.round(rect.height));
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const box = entry.contentRect;
        measure(Math.round(box.width), Math.round(box.height));
      }
    });
    ro.observe(host);
    cleanups.push(() => ro.disconnect());
  }

  // 可见性
  if (opts.view) {
    const stop = watch([opts.view.active, opts.view.ratio], onVisibility);
    cleanups.push(stop);
  } else if (typeof IntersectionObserver !== 'undefined') {
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) ownRatio = entry.isIntersecting ? entry.intersectionRatio : 0;
        onVisibility();
      },
      { threshold: Array.from({ length: 21 }, (_, i) => i / 20).concat(threshold) },
    );
    io.observe(host);
    cleanups.push(() => io.disconnect());
  }
  document.addEventListener('visibilitychange', onVisibility);
  cleanups.push(() => document.removeEventListener('visibilitychange', onVisibility));

  // 减少动效变化时整体重建
  if (typeof window.matchMedia === 'function') {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (typeof mq.addEventListener === 'function') {
      mq.addEventListener('change', rebuild);
      cleanups.push(() => mq.removeEventListener('change', rebuild));
    }
  }

  setupSchedule();
  schedule();

  return {
    get mode() {
      return mode;
    },
    get running() {
      return raf !== 0;
    },
    get granted() {
      return !opts.schedule || mode !== 'live' || (slot?.granted ?? false);
    },
    get time() {
      return t;
    },
    wake,
    replay() {
      t = 0;
      done = false;
      wake();
    },
    destroy() {
      destroyed = true;
      cancel();
      slot?.release();
      slot = null;
      for (const fn of cleanups.splice(0)) fn();
    },
  };
}
