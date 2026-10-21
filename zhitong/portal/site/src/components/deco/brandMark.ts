/**
 * 品牌图形几何（07 章 §6.2）：从 `assets/brand-mark.svg?raw`（品牌唯一来源）解析出
 * viewBox、圆角方块、线性渐变、`g` 的 `rotate(θ cx cy)` 与每条描边。白色描边归“白”类，其它描边归“强调”类。
 * 品牌图形换稿时 D2 字符场随之改变，无需改代码。绘制只用 Path2D 与 roundRect，不加载 <img>，画布不会被污染。
 */
import brandRaw from '../../../assets/brand-mark.svg?raw';

export interface BrandStop {
  offset: number;
  color: string;
}

export interface BrandStroke {
  d: string;
  stroke: string;
  width: number;
  cap: CanvasLineCap;
  kind: 'light' | 'accent';
}

export interface BrandMark {
  viewBox: [number, number, number, number];
  rect: { x: number; y: number; width: number; height: number; rx: number };
  /** 方块填充：渐变（objectBoundingBox 下 x1..y2 为 0..1 比例）或纯色。 */
  gradient: { x1: number; y1: number; x2: number; y2: number; userSpace: boolean; stops: BrandStop[] } | null;
  fill: string;
  rotate: { angle: number; cx: number; cy: number } | null;
  strokes: BrandStroke[];
}

const WHITE = /^(#fff|#ffffff|white|rgb\(\s*255\s*,\s*255\s*,\s*255\s*\))$/i;

function num(v: string | null | undefined, fallback = 0): number {
  if (v == null || v === '') return fallback;
  const n = v.trim().endsWith('%') ? parseFloat(v) / 100 : parseFloat(v);
  return Number.isFinite(n) ? n : fallback;
}

function attr(el: Element | null, name: string): string | null {
  if (!el) return null;
  const direct = el.getAttribute(name);
  if (direct != null) return direct;
  const style = el.getAttribute('style');
  if (!style) return null;
  const m = new RegExp(`(?:^|;)\\s*${name}\\s*:\\s*([^;]+)`).exec(style);
  return m ? m[1].trim() : null;
}

/** 沿祖先链取可继承属性（stroke、stroke-width、stroke-linecap）。 */
function inherited(el: Element, name: string): string | null {
  for (let cur: Element | null = el; cur && cur.tagName.toLowerCase() !== 'svg'; cur = cur.parentElement) {
    const v = attr(cur, name);
    if (v != null) return v;
  }
  return null;
}

/**
 * 解析品牌 SVG。
 * @param raw - SVG 源文本。
 * @returns 品牌几何。
 */
export function parseBrandMark(raw: string): BrandMark {
  const doc = new DOMParser().parseFromString(raw, 'image/svg+xml');
  const svg = doc.documentElement;
  const vb = (svg.getAttribute('viewBox') ?? '0 0 64 64').split(/[\s,]+/).map((v) => parseFloat(v));
  const viewBox: [number, number, number, number] = [vb[0] || 0, vb[1] || 0, vb[2] || 64, vb[3] || 64];

  const rectEl = svg.querySelector('rect');
  const rect = {
    x: num(rectEl?.getAttribute('x')),
    y: num(rectEl?.getAttribute('y')),
    width: num(rectEl?.getAttribute('width'), viewBox[2]),
    height: num(rectEl?.getAttribute('height'), viewBox[3]),
    rx: num(rectEl?.getAttribute('rx') ?? rectEl?.getAttribute('ry')),
  };
  const fill = attr(rectEl, 'fill') ?? '#0666f5';
  let gradient: BrandMark['gradient'] = null;
  const ref = /url\(\s*#([^)\s]+)\s*\)/.exec(fill);
  const gradEl = ref ? ([...svg.querySelectorAll('linearGradient')].find((el) => el.id === ref[1]) ?? null) : null;
  if (gradEl) {
    const userSpace = gradEl.getAttribute('gradientUnits') === 'userSpaceOnUse';
    gradient = {
      x1: num(gradEl.getAttribute('x1'), 0),
      y1: num(gradEl.getAttribute('y1'), 0),
      x2: num(gradEl.getAttribute('x2'), userSpace ? rect.width : 1),
      y2: num(gradEl.getAttribute('y2'), 0),
      userSpace,
      stops: [...gradEl.querySelectorAll('stop')].map((s) => ({
        offset: num(s.getAttribute('offset'), 0),
        color: (attr(s, 'stop-color') ?? '#000').toLowerCase(),
      })),
    };
  }

  let rotate: BrandMark['rotate'] = null;
  const g = svg.querySelector('g[transform]');
  const rm = g ? /rotate\(\s*(-?[\d.]+)(?:[\s,]+(-?[\d.]+)[\s,]+(-?[\d.]+))?\s*\)/.exec(g.getAttribute('transform') ?? '') : null;
  if (rm) rotate = { angle: parseFloat(rm[1]), cx: num(rm[2]), cy: num(rm[3]) };

  const strokes: BrandStroke[] = [...svg.querySelectorAll('path')].flatMap((p) => {
    const stroke = inherited(p, 'stroke');
    const d = p.getAttribute('d');
    if (!stroke || stroke === 'none' || !d) return [];
    const cap = (inherited(p, 'stroke-linecap') ?? 'butt') as CanvasLineCap;
    return [
      {
        d,
        stroke: stroke.toLowerCase(),
        width: num(inherited(p, 'stroke-width'), 1),
        cap,
        kind: WHITE.test(stroke.trim()) ? ('light' as const) : ('accent' as const),
      },
    ];
  });

  return { viewBox, rect, gradient, fill, rotate, strokes };
}

/** 门户当前的品牌图形源文本。 */
export const BRAND_RAW: string = brandRaw;

/** 十六进制颜色 → [r, g, b]（0..255）。 */
export function hexRgb(hex: string): [number, number, number] {
  let h = hex.replace('#', '').trim();
  if (h.length === 3) h = [...h].map((c) => c + c).join('');
  const n = parseInt(h.slice(0, 6), 16);
  return Number.isFinite(n) ? [(n >> 16) & 255, (n >> 8) & 255, n & 255] : [255, 255, 255];
}

/**
 * 渐变上位置 u（0..1）处的颜色。
 * @param stops - 渐变色标。
 * @param u - 位置。
 * @returns `rgb(r, g, b)`。
 */
export function gradientColor(stops: BrandStop[], u: number): string {
  if (stops.length === 0) return 'rgb(6, 102, 245)';
  const sorted = [...stops].sort((a, b) => a.offset - b.offset);
  if (u <= sorted[0].offset) return rgbString(hexRgb(sorted[0].color));
  for (let i = 1; i < sorted.length; i++) {
    const a = sorted[i - 1];
    const b = sorted[i];
    if (u <= b.offset) {
      const k = b.offset === a.offset ? 0 : (u - a.offset) / (b.offset - a.offset);
      const ca = hexRgb(a.color);
      const cb = hexRgb(b.color);
      return rgbString([0, 1, 2].map((j) => ca[j] + (cb[j] - ca[j]) * k) as [number, number, number]);
    }
  }
  return rgbString(hexRgb(sorted[sorted.length - 1].color));
}

function rgbString(c: [number, number, number]): string {
  return `rgb(${Math.round(c[0])}, ${Math.round(c[1])}, ${Math.round(c[2])})`;
}

/**
 * 字符场的强调色：第一条“强调”类描边的颜色（没有时用品牌绿）。
 * @param mark - 品牌几何。
 * @returns 颜色字符串。
 */
export function accentColor(mark: BrandMark): string {
  return mark.strokes.find((s) => s.kind === 'accent')?.stroke ?? '#12d99f';
}
