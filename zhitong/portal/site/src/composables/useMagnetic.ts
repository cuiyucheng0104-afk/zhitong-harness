/**
 * 磁吸（00 章 §6.1）与指令 `v-magnetic`。
 *
 * - 只在 `(hover: hover) and (pointer: fine)`、未减少动效、GSAP 已加载、且 `<html data-layout="home">` 时生效；
 *   文档页不加载 GSAP，因此不生效（01 章 §3）。
 * - 感应区 = 包围盒外扩 radius；元素偏移 (dx, dy) × strength，`[data-magnetic-label]` 子元素再偏移 × labelStrength；
 *   偏移上限 max（按钮 10px，文字链接 6px）；离开回弹 0.6s `EASE.snapBack`；按下 `scale: 0.97` 0.12s。
 * - 禁用（`:disabled`、`[aria-disabled='true']`）时不偏移。
 * - 一个文档级 pointermove 监听服务全部元素，rAF 节流。
 */
import { onBeforeUnmount, onMounted, watch, type Directive, type Ref } from 'vue';
import { getMotion, hasFinePointer, loadMotion, prefersReducedMotion } from '../lib/motion';
import { EASE } from '../lib/motion-tokens';

export interface MagneticOptions {
  /** 感应区外扩像素，默认 24。 */
  radius?: number;
  /** 元素整体跟随系数，默认 0.32。 */
  strength?: number;
  /** 内部文字与图标的额外系数，默认 0.16。 */
  labelStrength?: number;
  /** 偏移上限像素，默认 10（按钮）；文字链接用 6。 */
  max?: number;
}

/** 指令值：省略为按钮档；`'link'` 为文字链接档（上限 6px）；或完整参数。 */
export type MagneticValue = MagneticOptions | 'button' | 'link' | false | undefined;

type Setter = (value: number) => void;
interface Entry {
  el: HTMLElement;
  opts: Required<MagneticOptions>;
  x?: Setter;
  y?: Setter;
  labels: { el: HTMLElement; x: Setter; y: Setter }[];
  engaged: boolean;
  pressed: boolean;
}

const entries = new Map<HTMLElement, Entry>();
let pointer: { x: number; y: number } | null = null;
let frame = 0;
let listening = false;

/** 解析指令值为完整参数。 */
export function resolveMagnetic(value: MagneticValue): Required<MagneticOptions> | null {
  if (value === false) return null;
  const base = { radius: 24, strength: 0.32, labelStrength: 0.16, max: 10 };
  if (value === 'link') return { ...base, max: 6 };
  if (!value || value === 'button') return base;
  return { ...base, ...value };
}

/**
 * 计算元素偏移（纯函数，供测试）。
 * @param rect - 元素未偏移时的包围盒。
 * @param px - 指针 x。
 * @param py - 指针 y。
 * @param opts - 参数。
 * @returns 偏移量；指针在感应区外时为 null。
 */
export function magneticOffset(
  rect: { left: number; top: number; width: number; height: number },
  px: number,
  py: number,
  opts: Required<MagneticOptions>,
): { x: number; y: number; lx: number; ly: number } | null {
  const { radius, strength, labelStrength, max } = opts;
  if (
    px < rect.left - radius ||
    px > rect.left + rect.width + radius ||
    py < rect.top - radius ||
    py > rect.top + rect.height + radius
  )
    return null;
  const dx = px - (rect.left + rect.width / 2);
  const dy = py - (rect.top + rect.height / 2);
  const clamp = (v: number, m: number) => Math.max(-m, Math.min(m, v));
  return {
    x: clamp(dx * strength, max),
    y: clamp(dy * strength, max),
    lx: clamp(dx * labelStrength, max / 2),
    ly: clamp(dy * labelStrength, max / 2),
  };
}

function enabled() {
  return (
    hasFinePointer() &&
    !prefersReducedMotion() &&
    document.documentElement.dataset.layout === 'home' &&
    getMotion() !== null
  );
}

function ensureSetters(entry: Entry) {
  const motion = getMotion();
  if (!motion || entry.x) return;
  const q = (el: HTMLElement, prop: 'x' | 'y') =>
    motion.gsap.quickTo(el, prop, { duration: 0.35, ease: 'power3.out' }) as Setter;
  entry.x = q(entry.el, 'x');
  entry.y = q(entry.el, 'y');
  entry.labels = [...entry.el.querySelectorAll<HTMLElement>('[data-magnetic-label]')].map((el) => ({
    el,
    x: q(el, 'x'),
    y: q(el, 'y'),
  }));
}

function release(entry: Entry) {
  const motion = getMotion();
  if (!entry.engaged || !motion) return;
  entry.engaged = false;
  const targets = [entry.el, ...entry.labels.map((l) => l.el)];
  motion.gsap.killTweensOf(targets, 'x,y');
  motion.gsap.to(targets, { x: 0, y: 0, duration: 0.6, ease: EASE.snapBack, overwrite: 'auto' });
  entry.x = entry.y = undefined;
  entry.labels = [];
}

function disabled(el: HTMLElement) {
  return el.matches(':disabled, [aria-disabled="true"]');
}

function update() {
  frame = 0;
  if (!pointer) return;
  const on = enabled();
  const motion = getMotion();
  for (const entry of entries.values()) {
    if (!on || !motion || !entry.el.isConnected || disabled(entry.el)) {
      release(entry);
      continue;
    }
    const rect = entry.el.getBoundingClientRect();
    const tx = Number(motion.gsap.getProperty(entry.el, 'x')) || 0;
    const ty = Number(motion.gsap.getProperty(entry.el, 'y')) || 0;
    const base = { left: rect.left - tx, top: rect.top - ty, width: rect.width, height: rect.height };
    const offset = magneticOffset(base, pointer.x, pointer.y, entry.opts);
    if (!offset) {
      release(entry);
      continue;
    }
    ensureSetters(entry);
    entry.engaged = true;
    entry.x?.(offset.x);
    entry.y?.(offset.y);
    for (const label of entry.labels) {
      label.x(offset.lx);
      label.y(offset.ly);
    }
  }
}

function onPointerMove(event: PointerEvent) {
  if (event.pointerType && event.pointerType !== 'mouse' && event.pointerType !== 'pen') return;
  pointer = { x: event.clientX, y: event.clientY };
  frame ||= requestAnimationFrame(update);
}

function onPointerDown(event: PointerEvent) {
  const motion = getMotion();
  if (!motion || !enabled()) return;
  for (const entry of entries.values()) {
    if (disabled(entry.el) || !entry.el.contains(event.target as Node)) continue;
    entry.pressed = true;
    motion.gsap.to(entry.el, { scale: 0.97, duration: 0.12, ease: 'power2.out', overwrite: 'auto' });
  }
}

function onPointerUp() {
  const motion = getMotion();
  if (!motion) return;
  for (const entry of entries.values()) {
    if (!entry.pressed) continue;
    entry.pressed = false;
    motion.gsap.to(entry.el, { scale: 1, duration: 0.12, ease: 'power2.out', overwrite: 'auto' });
  }
}

function startListening() {
  if (listening || typeof document === 'undefined') return;
  listening = true;
  document.addEventListener('pointermove', onPointerMove, { passive: true });
  document.addEventListener('pointerdown', onPointerDown, { passive: true });
  document.addEventListener('pointerup', onPointerUp, { passive: true });
  document.addEventListener('pointercancel', onPointerUp, { passive: true });
}

function stopListening() {
  if (!listening || entries.size) return;
  listening = false;
  document.removeEventListener('pointermove', onPointerMove);
  document.removeEventListener('pointerdown', onPointerDown);
  document.removeEventListener('pointerup', onPointerUp);
  document.removeEventListener('pointercancel', onPointerUp);
}

/**
 * 登记一个磁吸元素。
 * @param el - 元素。
 * @param value - 参数或档位。
 * @returns 注销函数。
 */
export function registerMagnetic(el: HTMLElement, value: MagneticValue): () => void {
  const opts = resolveMagnetic(value);
  if (!opts || typeof window === 'undefined') return () => {};
  el.classList.add('is-magnetic');
  entries.set(el, { el, opts, labels: [], engaged: false, pressed: false });
  startListening();
  if (hasFinePointer() && !prefersReducedMotion()) void loadMotionIfHome();
  return () => {
    const entry = entries.get(el);
    if (entry) release(entry);
    entries.delete(el);
    el.classList.remove('is-magnetic');
    stopListening();
  };
}

function loadMotionIfHome() {
  // 只有首页才加载 GSAP；文档页上登记的元素保持静止。
  if (document.documentElement.dataset.layout === 'home') return loadMotion();
  return Promise.resolve(null);
}

const registry = new WeakMap<HTMLElement, () => void>();

/** 指令：`v-magnetic`、`v-magnetic="'link'"`、`v-magnetic="{ max: 6 }"`、`v-magnetic="false"`。 */
export const vMagnetic: Directive<HTMLElement, MagneticValue> = {
  mounted(el, binding) {
    registry.set(el, registerMagnetic(el, binding.value));
  },
  updated(el, binding) {
    if (JSON.stringify(binding.value) === JSON.stringify(binding.oldValue)) return;
    registry.get(el)?.();
    registry.set(el, registerMagnetic(el, binding.value));
  },
  beforeUnmount(el) {
    registry.get(el)?.();
    registry.delete(el);
  },
  getSSRProps() {
    return {};
  },
};

/**
 * 组合式用法：在组件内给一个 ref 元素加磁吸。
 * @param target - 元素 ref。
 * @param value - 参数或档位。
 */
export function useMagnetic(target: Ref<HTMLElement | null | undefined>, value: MagneticValue = 'button') {
  let off: (() => void) | undefined;
  const bind = (el: HTMLElement | null | undefined) => {
    off?.();
    off = el ? registerMagnetic(el, value) : undefined;
  };
  onMounted(() => bind(target.value));
  watch(target, bind);
  onBeforeUnmount(() => off?.());
}
