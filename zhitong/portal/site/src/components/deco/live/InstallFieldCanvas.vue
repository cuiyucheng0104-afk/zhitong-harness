<script setup lang="ts">
/**
 * D2 清单编码字符场的画布层（07 章 §6）。懒加载块，只在客户端挂载。
 * - 画布只覆盖字符场区域（品牌图形 ± 光晕与面板求交）。
 * - 字形图集按 DPR 预渲染；每格比较绘制键，与上帧相同则跳过（稳态每帧只重画 1–3% 的格子）。
 * - 绘制预算：每画 24 格检查一次耗时，超过 2.2 ms 停下，剩余格子下一帧从中断处继续（旋转游标）。
 * - 内容压暗：进入视口 1.2 s 后在 idle 回调里重测内容盒子，只重画标志变化的格子。
 * - 待机（闪烁、扫光）只在 live 且持有同屏调度运行权时运行；指针解码只在精确指针下，监听挂在 `.install-panel` 上（被动）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { useInView } from '../../../composables/useInView';
import { createDecoLoop, sizeCanvas, type DecoLoop, type DecoMode } from '../decoLoop';
import { BRAND_RAW, accentColor, gradientColor, parseBrandMark, type BrandMark } from '../brandMark';
import {
  INSTALL_FIELD as CFG,
  GLYPH_BLANK,
  GLYPH_DOT,
  GLYPH_TILE,
  GRAD_LEVELS,
  ROW_ACC,
  ROW_FIELD,
  ROW_LIGHT,
  ROW_WHITE,
  averageCells,
  createFieldModel,
  decodeKey,
  fieldPlacement,
  type FieldModel,
  type FieldPlacement,
} from '../installField';

const props = defineProps<{ host: HTMLElement | null; mark?: string }>();

const canvas = ref<HTMLCanvasElement | null>(null);
const box = ref<HTMLElement | null>(null);
const view = useInView(box, { threshold: 0.25 });

const FIELD_COLOR = '#7fa6dd';
const FONT = (fs: number, bold: boolean) => `${bold ? 600 : 400} ${fs}px 'IBM Plex Mono', 'SFMono-Regular', Consolas, monospace`;

let loop: DecoLoop | null = null;
let ctx: CanvasRenderingContext2D | null = null;
let atlas: HTMLCanvasElement | null = null;
let model: FieldModel | null = null;
let P: FieldPlacement | null = null;
let mark: BrandMark | null = null;
let last = new Int32Array(0);
let cursor = 0;
let pending = false;
let dpr = 1;
let mode: DecoMode = 'still';
let panel: HTMLElement | null = null;
let safeTimer = 0;
let safeMeasured = false;
let finalDrawn = false;
const stats = { drawn: 0, cells: 0 };

function buildAtlas(M: BrandMark, Pl: FieldPlacement) {
  const cw = Math.round(Pl.cw * dpr);
  const ch = Math.round(Pl.ch * dpr);
  const a = document.createElement('canvas');
  a.width = cw * 12;
  a.height = ch * 16;
  const g = a.getContext('2d');
  if (!g) return null;
  const stops = M.gradient?.stops ?? [{ offset: 0, color: M.fill }];
  const colors: [string, boolean][] = [];
  for (let l = 0; l < GRAD_LEVELS; l++) colors.push([gradientColor(stops, (l + 0.5) / GRAD_LEVELS), false]);
  colors[ROW_LIGHT] = ['#ffffff', true];
  colors[ROW_ACC] = [accentColor(M), true];
  colors[ROW_FIELD] = [FIELD_COLOR, false];
  colors[ROW_WHITE] = ['#ffffff', false];
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  colors.forEach(([color, bold], row) => {
    g.fillStyle = color;
    g.font = FONT(Pl.fs * dpr, bold);
    for (let col = 0; col <= GLYPH_DOT; col++) {
      g.fillText(col === GLYPH_DOT ? '·' : String(col), col * cw + cw / 2, row * ch + ch / 2 + dpr * 0.5);
    }
    g.fillRect(GLYPH_TILE * cw + dpr * 0.5, row * ch + dpr * 0.5, cw - dpr, ch - dpr);
  });
  return a;
}

function sampleShape(M: BrandMark, Pl: FieldPlacement): Float32Array | null {
  const w = Pl.cols * Pl.cw;
  const h = Pl.rows * Pl.ch;
  if (w <= 0 || h <= 0) return null;
  const off = document.createElement('canvas');
  off.width = w;
  off.height = h;
  const g = off.getContext('2d', { willReadFrequently: true });
  if (!g) return null;
  const k = Pl.S / M.viewBox[2];
  g.translate(Pl.cx - Pl.S / 2 - Pl.region.x, Pl.cy - Pl.S / 2 - Pl.region.y);
  g.scale(k, k);
  g.translate(-M.viewBox[0], -M.viewBox[1]);
  g.fillStyle = '#f00';
  g.beginPath();
  g.roundRect(M.rect.x, M.rect.y, M.rect.width, M.rect.height, M.rect.rx);
  g.fill();
  if (M.rotate) {
    g.translate(M.rotate.cx, M.rotate.cy);
    g.rotate((M.rotate.angle * Math.PI) / 180);
    g.translate(-M.rotate.cx, -M.rotate.cy);
  }
  for (const s of M.strokes) {
    g.strokeStyle = s.kind === 'light' ? '#0f0' : '#00f';
    g.lineWidth = s.width;
    g.lineCap = s.cap;
    g.stroke(new Path2D(s.d));
  }
  return averageCells(g.getImageData(0, 0, w, h).data, w, Pl);
}

function measureSafe() {
  if (!model || !panel || !props.host) return;
  const host = props.host.getBoundingClientRect();
  const boxes = [...panel.querySelectorAll(CFG.safeSelector)]
    .filter((el) => !props.host!.contains(el))
    .map((el) => {
      const r = el.getBoundingClientRect();
      return { x: r.left - host.left, y: r.top - host.top, w: r.width, h: r.height };
    })
    .filter((b) => b.w > 0 && b.h > 0);
  model.applySafe(boxes);
}

function scheduleSafeRemeasure() {
  if (safeMeasured) return;
  safeMeasured = true;
  const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number };
  const run = () => {
    measureSafe();
    loop?.wake();
  };
  if (typeof w.requestIdleCallback === 'function') w.requestIdleCallback(run, { timeout: 500 });
  else safeTimer = window.setTimeout(run, 0);
}

function drawCell(i: number, k: number) {
  if (!ctx || !atlas || !P) return;
  const c = i % P.cols;
  const r = (i - c) / P.cols;
  const x = c * P.cw;
  const y = r * P.ch;
  const sw = Math.round(P.cw * dpr);
  const sh = Math.round(P.ch * dpr);
  ctx.clearRect(x, y, P.cw, P.ch);
  const d = decodeKey(k);
  if (d.tile > 0) {
    ctx.globalAlpha = d.tile;
    ctx.drawImage(atlas, GLYPH_TILE * sw, d.row * sh, sw, sh, x, y, P.cw, P.ch);
  }
  if (d.glyph !== GLYPH_BLANK) {
    if (d.alpha > 0) {
      ctx.globalAlpha = d.alpha;
      ctx.drawImage(atlas, d.glyph * sw, d.row * sh, sw, sh, x, y, P.cw, P.ch);
    }
    if (d.overlay > 0) {
      const bold = d.row === ROW_LIGHT || d.row === ROW_ACC;
      ctx.globalAlpha = d.overlay;
      ctx.drawImage(atlas, d.glyph * sw, (bold ? ROW_LIGHT : ROW_WHITE) * sh, sw, sh, x, y, P.cw, P.ch);
    }
  }
  ctx.globalAlpha = 1;
}

/** 按键差异重画；返回是否还有因预算中断而未画的格子。 */
function paint(t: number, idle: boolean, final: boolean): boolean {
  if (!model || !ctx) return false;
  const n = model.count;
  const start = performance.now();
  let drawn = 0;
  for (let j = 0; j < n; j++) {
    const i = (cursor + j) % n;
    const k = model.key(i, t, idle, final);
    if (k === last[i]) continue;
    drawCell(i, k);
    last[i] = k;
    drawn++;
    if (drawn % 24 === 0 && performance.now() - start > CFG.drawBudgetMs) {
      cursor = (i + 1) % n;
      stats.drawn = drawn;
      stats.cells = n;
      return true;
    }
  }
  stats.drawn = drawn;
  stats.cells = n;
  return false;
}

let pointerAt: { x: number; y: number } | null = null;

function tick(t: number, dt: number): boolean {
  if (!model) return false;
  if (t >= 1.2) scheduleSafeRemeasure();
  const idle = mode === 'live' && (loop?.granted ?? false);
  model.update(t, dt, idle);
  if (pointerAt) {
    model.pointer(pointerAt.x, pointerAt.y, t);
    pointerAt = null;
  }
  pending = paint(t, idle, false);
  return pending || model.busy(t) || idle;
}

function still() {
  if (!model) return;
  finalDrawn = true;
  cursor = 0;
  // 终帧不受绘制预算限制（不在 rAF 里）
  const n = model.count;
  for (let i = 0; i < n; i++) {
    const k = model.key(i, 1e6, false, true);
    if (k !== last[i]) {
      drawCell(i, k);
      last[i] = k;
    }
  }
}

function resize(W: number, H: number, d: number) {
  if (!canvas.value) return;
  dpr = d;
  mark ??= parseBrandMark(props.mark ?? BRAND_RAW);
  P = fieldPlacement(W, H);
  const w = P.cols * P.cw;
  const h = P.rows * P.ch;
  const el = canvas.value;
  el.style.left = `${P.region.x}px`;
  el.style.top = `${P.region.y}px`;
  el.style.width = `${w}px`;
  el.style.height = `${h}px`;
  ctx = sizeCanvas(el, w, h, dpr);
  if (!ctx) return;
  ctx.clearRect(0, 0, w, h);
  atlas = buildAtlas(mark, P);
  const sample = sampleShape(mark, P);
  if (!sample) {
    model = null;
    return;
  }
  const S = P.S;
  const g = mark.gradient;
  const gx = (v: number, size: number, base: number) => (g?.userSpace ? (v - base) / size : v);
  model = createFieldModel(P, sample, {
    S,
    cx: P.cx,
    cy: P.cy,
    radius: (mark.rect.rx / mark.rect.width) * S,
    grad: g
      ? { x1: gx(g.x1, mark.rect.width, mark.rect.x), y1: gx(g.y1, mark.rect.height, mark.rect.y), x2: gx(g.x2, mark.rect.width, mark.rect.x), y2: gx(g.y2, mark.rect.height, mark.rect.y) }
      : { x1: 0, y1: 0, x2: 1, y2: 1 },
  });
  last = new Int32Array(model.count).fill(-1);
  cursor = 0;
  measureSafe();
  if (finalDrawn) still();
}

function onMove(e: PointerEvent) {
  if ((e.pointerType !== 'mouse' && e.pointerType !== 'pen') || !props.host) return;
  const r = props.host.getBoundingClientRect();
  pointerAt = { x: e.clientX - r.left, y: e.clientY - r.top };
  loop?.wake();
}

onMounted(() => {
  if (!box.value || !props.host) return;
  panel = props.host.parentElement;
  loop = createDecoLoop(props.host, null, {
    id: 'D2',
    threshold: 0.25,
    view,
    tick,
    resize,
    still,
    schedule: true,
    onMode: (m) => (mode = m),
  });
  if (mode === 'live' && panel) panel.addEventListener('pointermove', onMove, { passive: true });
});

onBeforeUnmount(() => {
  loop?.destroy();
  loop = null;
  panel?.removeEventListener('pointermove', onMove);
  window.clearTimeout(safeTimer);
});

defineExpose({
  get loop() {
    return loop;
  },
  get model() {
    return model;
  },
  stats,
});
</script>

<template>
  <div ref="box" class="deco-install-box">
    <canvas ref="canvas" class="deco-install-canvas"></canvas>
  </div>
</template>
