/**
 * 示例平面图的绘制清单（02 章 §5.4）：把 `data/demo-drawing.ts` 的几何展开成按图层排序、带出图时刻的图元。
 * 出图动画（cue `plot`，2.15–3.75）按图层顺序：FRAME 0.20 → AXIS 0.25 → COLUMN 0.15 → WALL 0.45 → WINDOW+DOOR 0.25
 * → STAIR+EVTR 0.10 → DIM 0.15 → 文字框 0.05；全部匀速（模拟绘图仪出线）。
 */
import {
  AXES_X,
  AXES_Y,
  COLUMN_SIZE,
  DIMS,
  DOORS,
  ELEVATOR_DOORS,
  FRAME,
  SHAFTS,
  STAIRS,
  TEXTS,
  WALLS,
  WINDOWS,
} from '../../data/demo-drawing';

export type Layer = 'FRAME' | 'AXIS' | 'COLUMN' | 'WALL' | 'WINDOW' | 'DOOR' | 'STAIR' | 'EVTR' | 'DIM' | 'TXTROOM' | 'AREA' | 'PUB_TEXT';

/** 图层颜色、线宽（§5.4 图层表）。 */
export const LAYER_STYLE: Record<Layer, { color: string; width?: number }> = {
  FRAME: { color: '#7890AB' },
  AXIS: { color: '#E06C5A', width: 0.25 },
  COLUMN: { color: '#24364F' },
  WALL: { color: '#24364F', width: 2 },
  WINDOW: { color: '#2F80ED', width: 0.3 },
  DOOR: { color: '#2F80ED', width: 0.3 },
  STAIR: { color: '#7890AB', width: 0.25 },
  EVTR: { color: '#7890AB', width: 0.3 },
  DIM: { color: '#526C8B', width: 0.25 },
  TXTROOM: { color: '#162943' },
  AREA: { color: '#526C8B' },
  PUB_TEXT: { color: '#162943' },
};

/** 各图层在出图动画里的起止（相对 cue `plot` 的秒数）。 */
export const PLOT_PHASES = {
  FRAME: [0, 0.2],
  AXIS: [0.2, 0.25],
  COLUMN: [0.45, 0.15],
  WALL: [0.6, 0.45],
  OPENING: [1.05, 0.25],
  STAIR: [1.3, 0.1],
  DIM: [1.4, 0.15],
  TEXT: [1.55, 0.05],
} as const;
/** 出图总时长 1.60 s（2.15 → 3.75）。 */
export const PLOT_TOTAL = 1.6;

export interface Prim {
  key: string;
  layer: Layer;
  /** 'line' | 'rect' | 'path' | 'circle'。 */
  tag: 'line' | 'rect' | 'path' | 'circle';
  attrs: Record<string, number | string>;
  /** 相对 plot 的开始秒数与时长。 */
  at: number;
  dur: number;
  /** 画法：描线（pathLength 1 + dashoffset）、伸展（虚线保持花纹，按方向 scale）、缩放（柱子）。 */
  anim: 'draw' | 'grow-x' | 'grow-y' | 'pop';
  width?: number;
  dash?: string;
  fill?: string;
}

const r2 = (v: number) => Math.round(v * 1000) / 1000;

function staggered<T>(items: readonly T[], start: number, total: number, amount: number) {
  const n = items.length;
  const step = n > 1 ? amount / (n - 1) : 0;
  const dur = Math.max(0.04, total - amount);
  return items.map((item, i) => ({ item, at: r2(start + i * step), dur }));
}

/** 文字宽度：中文（全角）× 字高 + 其它 × 0.6 × 字高（§5.4）。 */
export function textWidth(text: string, h: number): number {
  let w = 0;
  for (const ch of text) w += ch.charCodeAt(0) > 0x2e80 ? h : 0.6 * h;
  return w;
}

export interface TextItem {
  id: string;
  text: string;
  x: number;
  y: number;
  h: number;
  layer: Layer;
  /** 竖排尺寸文字：绕插入点逆时针转 90°。 */
  rotate?: boolean;
}

/** 全部文字（TEXTS + 9 道尺寸的数字）。 */
export const TEXT_ITEMS: TextItem[] = [
  ...TEXTS.map(([id, text, x, y, h, layer]) => ({ id, text, x, y, h, layer: layer as Layer })),
  ...DIMS.map((d, i) => {
    const horizontal = d.a[1] === d.b[1];
    const w = textWidth(d.text, 2.5);
    return horizontal
      ? { id: `D${i}`, text: d.text, x: r2((d.a[0] + d.b[0]) / 2 - w / 2), y: d.a[1] - 1, h: 2.5, layer: 'DIM' as Layer }
      : { id: `D${i}`, text: d.text, x: d.a[0] - 1, y: r2((d.a[1] + d.b[1]) / 2 + w / 2), h: 2.5, layer: 'DIM' as Layer, rotate: true };
  }),
];

function build(): Prim[] {
  const out: Prim[] = [];
  const P = PLOT_PHASES;
  // FRAME
  const [ox1, oy1, ox2, oy2] = FRAME.outer;
  const [ix1, iy1, ix2, iy2] = FRAME.inner;
  const [tx1, ty1, tx2, ty2] = FRAME.titleBlock;
  out.push({ key: 'f-outer', layer: 'FRAME', tag: 'rect', attrs: { x: ox1, y: oy1, width: ox2 - ox1, height: oy2 - oy1 }, at: 0, dur: 0.2, anim: 'draw', width: 0.35 });
  out.push({ key: 'f-inner', layer: 'FRAME', tag: 'rect', attrs: { x: ix1, y: iy1, width: ix2 - ix1, height: iy2 - iy1 }, at: 0, dur: 0.2, anim: 'draw', width: 1 });
  out.push({ key: 'f-title', layer: 'FRAME', tag: 'rect', attrs: { x: tx1, y: ty1, width: tx2 - tx1, height: ty2 - ty1 }, at: 0.05, dur: 0.15, anim: 'draw', width: 0.5 });
  FRAME.titleLines.forEach(([x1, y1, x2, y2], i) =>
    out.push({ key: `f-tl${i}`, layer: 'FRAME', tag: 'line', attrs: { x1, y1, x2, y2 }, at: 0.1, dur: 0.1, anim: 'draw', width: 0.5 }),
  );
  // AXIS：轴线（点划线，按方向伸展）+ 轴号圆
  const [aStart, aDur] = P.AXIS;
  AXES_X.forEach(([n, x]) => {
    out.push({ key: `ax-${n}`, layer: 'AXIS', tag: 'line', attrs: { x1: x, y1: 142, x2: x, y2: 402 }, at: aStart, dur: aDur, anim: 'grow-y', dash: '8 2 1 2' });
    out.push({ key: `axc-${n}`, layer: 'AXIS', tag: 'circle', attrs: { cx: x, cy: 134, r: 8 }, at: aStart, dur: aDur, anim: 'draw' });
  });
  AXES_Y.forEach(([n, y]) => {
    out.push({ key: `ay-${n}`, layer: 'AXIS', tag: 'line', attrs: { x1: 212, y1: y, x2: 604, y2: y }, at: aStart, dur: aDur, anim: 'grow-x', dash: '8 2 1 2' });
    out.push({ key: `ayc-${n}`, layer: 'AXIS', tag: 'circle', attrs: { cx: 204, cy: y, r: 8 }, at: aStart, dur: aDur, anim: 'draw' });
  });
  // COLUMN：20 根方柱，中心为原点 scale 0 → 1，stagger 0.01
  const cols = AXES_X.flatMap(([, x]) => AXES_Y.map(([, y]) => [x, y] as const));
  const half = COLUMN_SIZE / 2;
  cols.forEach(([x, y], i) =>
    out.push({
      key: `col-${i}`,
      layer: 'COLUMN',
      tag: 'rect',
      attrs: { x: x - half, y: y - half, width: COLUMN_SIZE, height: COLUMN_SIZE },
      at: r2(P.COLUMN[0] + i * 0.005),
      dur: 0.055,
      anim: 'pop',
      fill: LAYER_STYLE.COLUMN.color,
    }),
  );
  // WALL：先上后下、先左后右，stagger amount 0.35
  const walls = [...WALLS].sort((a, b) => Math.min(a[1], a[3]) - Math.min(b[1], b[3]) || Math.min(a[0], a[2]) - Math.min(b[0], b[2]));
  for (const { item: [x1, y1, x2, y2], at, dur } of staggered(walls, P.WALL[0], P.WALL[1], 0.35))
    out.push({ key: `w-${x1}-${y1}-${x2}-${y2}`, layer: 'WALL', tag: 'line', attrs: { x1, y1, x2, y2 }, at, dur, anim: 'draw', width: 2 });
  // WINDOW + DOOR（开启弧与门扇同时画）
  const [oStart, oDur] = P.OPENING;
  WINDOWS.forEach((wd, i) => {
    const h = wd.dir === 'h';
    const rect = h ? { x: wd.x, y: wd.y - 1, width: wd.len, height: 2 } : { x: wd.x - 1, y: wd.y, width: 2, height: wd.len };
    out.push({ key: `win-${i}`, layer: 'WINDOW', tag: 'rect', attrs: rect, at: oStart, dur: oDur, anim: 'draw' });
    for (const off of [-0.35, 0.35]) {
      const line = h
        ? { x1: wd.x, y1: wd.y + off, x2: wd.x + wd.len, y2: wd.y + off }
        : { x1: wd.x + off, y1: wd.y, x2: wd.x + off, y2: wd.y + wd.len };
      out.push({ key: `win-${i}-${off}`, layer: 'WINDOW', tag: 'line', attrs: line, at: oStart, dur: oDur, anim: 'draw' });
    }
  });
  DOORS.forEach((d) => {
    const [hx, hy] = d.hinge;
    const w = d.w;
    let leaf: Record<string, number>;
    let arc: string;
    if (d.wall === 'h' && d.swing === 'N') {
      leaf = { x1: hx, y1: hy, x2: hx, y2: hy - w };
      arc = `M${hx + w} ${hy}A${w} ${w} 0 0 0 ${hx} ${hy - w}`;
    } else if (d.wall === 'h') {
      leaf = { x1: hx, y1: hy, x2: hx, y2: hy + w };
      arc = `M${hx + w} ${hy}A${w} ${w} 0 0 1 ${hx} ${hy + w}`;
    } else {
      leaf = { x1: hx, y1: hy, x2: hx + w, y2: hy };
      arc = `M${hx} ${hy + w}A${w} ${w} 0 0 0 ${hx + w} ${hy}`;
    }
    out.push({ key: `door-${d.label}`, layer: 'DOOR', tag: 'line', attrs: leaf, at: oStart, dur: oDur, anim: 'draw' });
    out.push({ key: `door-${d.label}-arc`, layer: 'DOOR', tag: 'path', attrs: { d: arc }, at: oStart, dur: oDur, anim: 'draw' });
  });
  ELEVATOR_DOORS.forEach(([x1, y1, x2, y2], i) =>
    out.push({ key: `evd-${i}`, layer: 'DOOR', tag: 'line', attrs: { x1, y1, x2, y2 }, at: oStart, dur: oDur, anim: 'draw' }),
  );
  // STAIR + EVTR
  const [sStart, sDur] = P.STAIR;
  STAIRS.forEach((s, k) => {
    for (let i = 0; i < s.n; i++) {
      const y = r2(s.y0 + i * s.step);
      out.push({ key: `st-${k}-l${i}`, layer: 'STAIR', tag: 'line', attrs: { x1: s.x1, y1: y, x2: s.rail - 1, y2: y }, at: sStart, dur: sDur, anim: 'draw' });
      out.push({ key: `st-${k}-r${i}`, layer: 'STAIR', tag: 'line', attrs: { x1: s.rail + 1, y1: y, x2: s.x2, y2: y }, at: sStart, dur: sDur, anim: 'draw' });
    }
    const yEnd = r2(s.y0 + (s.n - 1) * s.step);
    out.push({ key: `st-${k}-rail`, layer: 'STAIR', tag: 'line', attrs: { x1: s.rail, y1: s.y0, x2: s.rail, y2: yEnd }, at: sStart, dur: sDur, anim: 'draw' });
  });
  SHAFTS.forEach(([x1, y1, x2, y2], i) => {
    out.push({ key: `sh-${i}`, layer: 'EVTR', tag: 'rect', attrs: { x: x1, y: y1, width: x2 - x1, height: y2 - y1 }, at: sStart, dur: sDur, anim: 'draw' });
    out.push({ key: `sh-${i}-a`, layer: 'EVTR', tag: 'line', attrs: { x1, y1, x2, y2 }, at: sStart, dur: sDur, anim: 'draw' });
    out.push({ key: `sh-${i}-b`, layer: 'EVTR', tag: 'line', attrs: { x1, y1: y2, x2, y2: y1 }, at: sStart, dur: sDur, anim: 'draw' });
  });
  // DIM：尺寸线 + 45° 起止短线（长 3）
  const [dStart, dDur] = P.DIM;
  const t = 3 / 2 / Math.SQRT2;
  DIMS.forEach((d, i) => {
    const [x1, y1] = d.a;
    const [x2, y2] = d.b;
    out.push({ key: `dim-${i}`, layer: 'DIM', tag: 'line', attrs: { x1, y1, x2, y2 }, at: dStart, dur: dDur, anim: 'draw' });
    for (const [px, py] of [d.a, d.b]) {
      out.push({
        key: `dim-${i}-${px}-${py}`,
        layer: 'DIM',
        tag: 'line',
        attrs: { x1: r2(px - t), y1: r2(py + t), x2: r2(px + t), y2: r2(py - t) },
        at: dStart,
        dur: dDur,
        anim: 'draw',
      });
    }
  });
  return out;
}

/** 全部图元（按出图顺序）。 */
export const PRIMS: Prim[] = build();
