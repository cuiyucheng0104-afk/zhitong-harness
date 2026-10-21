/**
 * D2 清单编码字符场的模型（07 章 §6.3–6.4），与绘制分离：
 * 布局、按品牌图形采样分类、字符流、透明度、内容压暗、入场锁定、待机（闪烁、扫光、指针解码），
 * 以及每格的绘制键 `key = 字形 | 行 | α（64 级）| 叠加（16 级）| 格底（8 级）`。键与上帧相同的格子不重画。
 */

export interface InstallFieldConfig {
  place: {
    wide: { size: 0.82; maxW: 0.5; dx: 0.22; dy: 0.26 };
    narrow: { size: 0.92; maxW: 0.92; dx: 0.2; dy: 0.3 };
  };
  cellsAcross: 54;
  cellAspect: 1.55;
  halo: 0.2;
  fieldAlpha: [0.07, 0.2];
  tileAlpha: [0.12, 0.3, 0.3];
  safeSelector: 'h2, h3, p, li, dt, dd, a, button, [data-deco-safe]';
  safePad: 8;
  safeCap: { field: 0.08; body: 0.22; light: 0.18; acc: 0.2; overlay: 0.05 };
  lockStart: 0.45;
  lockSpanIn: 0.95;
  lockSpanOut: 0.8;
  lockJitter: 0.25;
  flashDur: 0.55;
  twinkleRate: 0.012;
  glintPeriod: 8;
  glintDur: 1.6;
  pointerR: 40;
  drawBudgetMs: 2.2;
  codes: readonly string[]; // 24 个 12 位编码，取自 00 §8.2 的 0101/0104/0105/0108/0109/0117 章
}

/** 24 个 GB 50854 十二位清单编码（0101 土石方、0104 砌筑、0105 混凝土、0108 门窗、0109 屋面防水、0117 措施项目）。 */
export const FIELD_CODES = [
  '010101001001',
  '010101002001',
  '010101004001',
  '010103001001',
  '010401003001',
  '010401004001',
  '010402001001',
  '010403001001',
  '010502001001',
  '010502002001',
  '010503002001',
  '010505001001',
  '010507001001',
  '010515001002',
  '010802001001',
  '010802003001',
  '010807001001',
  '010902001001',
  '010904001001',
  '010904002001',
  '011701001001',
  '011702001001',
  '011703001001',
  '011705001001',
] as const;

export const INSTALL_FIELD: InstallFieldConfig = {
  place: { wide: { size: 0.82, maxW: 0.5, dx: 0.22, dy: 0.26 }, narrow: { size: 0.92, maxW: 0.92, dx: 0.2, dy: 0.3 } },
  cellsAcross: 54,
  cellAspect: 1.55,
  halo: 0.2,
  fieldAlpha: [0.07, 0.2],
  tileAlpha: [0.12, 0.3, 0.3],
  safeSelector: 'h2, h3, p, li, dt, dd, a, button, [data-deco-safe]',
  safePad: 8,
  safeCap: { field: 0.08, body: 0.22, light: 0.18, acc: 0.2, overlay: 0.05 },
  lockStart: 0.45,
  lockSpanIn: 0.95,
  lockSpanOut: 0.8,
  lockJitter: 0.25,
  flashDur: 0.55,
  twinkleRate: 0.012,
  glintPeriod: 8,
  glintDur: 1.6,
  pointerR: 40,
  drawBudgetMs: 2.2,
  codes: FIELD_CODES,
};

/** 格子类别。 */
export const CLS = { field: 0, body: 1, light: 2, acc: 3 } as const;

/** 字形列：0–9 为数字，10 为“·”，11 为格底方块；15 为空白。 */
export const GLYPH_DOT = 10;
export const GLYPH_TILE = 11;
export const GLYPH_BLANK = 15;
/** 图集行：0–11 渐变（常规），12 白（粗），13 强调（粗），14 场色（常规），15 白（常规）。 */
export const ROW_LIGHT = 12;
export const ROW_ACC = 13;
export const ROW_FIELD = 14;
export const ROW_WHITE = 15;
export const GRAD_LEVELS = 12;

export interface FieldPlacement {
  /** 品牌图形边长与中心（面板坐标）。 */
  S: number;
  cx: number;
  cy: number;
  /** 格宽、格高、字号。 */
  cw: number;
  ch: number;
  fs: number;
  /** 画布区域（面板坐标）：图形 ± 光晕与面板求交。 */
  region: { x: number; y: number; w: number; h: number };
  cols: number;
  rows: number;
}

/**
 * 字符场布局（§6.1）。
 * @param W - 面板宽。
 * @param H - 面板高。
 * @param cfg - 参数。
 * @returns 布局。
 */
export function fieldPlacement(W: number, H: number, cfg: InstallFieldConfig = INSTALL_FIELD): FieldPlacement {
  const wide = W >= 900;
  const p = wide ? cfg.place.wide : cfg.place.narrow;
  const S = wide ? Math.min(p.size * H, p.maxW * W) : p.size * W;
  const cx = W - p.dx * S;
  const cy = H - p.dy * S;
  const cw = Math.max(6, Math.min(14, Math.round(S / cfg.cellsAcross)));
  const ch = Math.round(cw * cfg.cellAspect);
  const fs = Math.round(cw * (4 / 3));
  const reach = S / 2 + cfg.halo * S;
  const x0 = Math.max(0, Math.floor(cx - reach));
  const y0 = Math.max(0, Math.floor(cy - reach));
  const x1 = Math.min(W, Math.ceil(cx + reach));
  const y1 = Math.min(H, Math.ceil(cy + reach));
  const region = { x: x0, y: y0, w: Math.max(0, x1 - x0), h: Math.max(0, y1 - y0) };
  return { S, cx, cy, cw, ch, fs, region, cols: Math.floor(region.w / cw), rows: Math.floor(region.h / ch) };
}

/**
 * 第 r 行的字符流：从编码表第 `7r` 项开始按“编码 + 空格”拼接，行首错开 `(5r) mod 13` 格。
 * @param r - 行号。
 * @param cols - 列数。
 * @param codes - 编码表。
 * @returns 长度为 cols 的字符串。
 */
export function codeRow(r: number, cols: number, codes: readonly string[] = FIELD_CODES): string {
  const offset = (5 * r) % 13;
  let s = '';
  for (let n = 0; s.length < cols + offset; n++) s += codes[(7 * r + n) % codes.length] + ' ';
  return s.slice(offset, offset + cols);
}

/** 点到圆角方块（中心 c、半边长 half、圆角 rad）的有符号距离。 */
export function roundRectSdf(px: number, py: number, cx: number, cy: number, half: number, rad: number): number {
  const qx = Math.abs(px - cx) - (half - rad);
  const qy = Math.abs(py - cy) - (half - rad);
  const outside = Math.hypot(Math.max(qx, 0), Math.max(qy, 0));
  return outside + Math.min(Math.max(qx, qy), 0) - rad;
}

/** smoothstep。 */
export function smoothstep(a: number, b: number, x: number): number {
  const t = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

/** 确定性整数散列 → [0, 1)。 */
export function hash01(a: number, b = 0): number {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x632be5ab, 0xc2b2ae35);
  h ^= h >>> 16;
  h = Math.imul(h, 0x7feb352d);
  h ^= h >>> 15;
  h = Math.imul(h, 0x846ca68b);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

/**
 * 每格的覆盖率采样：`(R·A, G·A, B·A)` 的格内均值（0..1）。
 * @param data - 区域大小离屏画布的 RGBA 像素。
 * @param width - 像素宽。
 * @param P - 布局。
 * @returns 每格三个通道，长度 `cols × rows × 3`。
 */
export function averageCells(data: ArrayLike<number>, width: number, P: FieldPlacement): Float32Array {
  const out = new Float32Array(P.cols * P.rows * 3);
  for (let r = 0; r < P.rows; r++) {
    for (let c = 0; c < P.cols; c++) {
      let sr = 0;
      let sg = 0;
      let sb = 0;
      const x0 = c * P.cw;
      const y0 = r * P.ch;
      for (let y = y0; y < y0 + P.ch; y++) {
        let o = (y * width + x0) * 4;
        for (let x = 0; x < P.cw; x++, o += 4) {
          const a = data[o + 3];
          sr += data[o] * a;
          sg += data[o + 1] * a;
          sb += data[o + 2] * a;
        }
      }
      const n = P.cw * P.ch * 255 * 255;
      const i = (r * P.cols + c) * 3;
      out[i] = sr / n;
      out[i + 1] = sg / n;
      out[i + 2] = sb / n;
    }
  }
  return out;
}

export interface FieldShape {
  /** 方块在面板坐标中的局部系：左上角、边长与圆角（px）。 */
  S: number;
  cx: number;
  cy: number;
  radius: number;
  /** 渐变轴（方块局部 0..1 坐标）。 */
  grad: { x1: number; y1: number; x2: number; y2: number };
}

export interface FieldModel {
  readonly P: FieldPlacement;
  readonly count: number;
  readonly cls: Uint8Array;
  readonly safe: Uint8Array;
  /** 最晚一格锁定的时刻（秒）。 */
  readonly lockEnd: number;
  /** 入场结束（锁定 + 叠白褪尽）的时刻（秒）。 */
  readonly entranceEnd: number;
  /** 按面板坐标的内容盒子更新压暗标志；返回标志变化的格子数。 */
  applySafe(boxes: { x: number; y: number; w: number; h: number }[]): number;
  /** 推进待机状态（闪烁、指针解码）。 */
  update(t: number, dt: number, idle: boolean): void;
  /** 指针（面板坐标）附近 40px 的非内容格子“解码”。 */
  pointer(x: number, y: number, t: number): void;
  /** 第 i 格在时刻 t 的绘制键；`final` 为静态终帧（全部落定、无高光）。 */
  key(i: number, t: number, idle: boolean, final?: boolean): number;
  /** 是否还有需要逐帧推进的变化（入场、解码中）。 */
  busy(t: number): boolean;
}

/** 绘制键的组成。 */
export interface KeyParts {
  glyph: number;
  row: number;
  alpha: number;
  overlay: number;
  tile: number;
}

/**
 * 编码绘制键。
 * @param glyph - 字形列（0–10，15 空白）。
 * @param row - 图集行（0–15）。
 * @param alpha - 字形透明度 0..1（64 级）。
 * @param overlay - 叠白 0..1（16 级）。
 * @param tile - 格底透明度 0..0.35（8 级，每级 0.05）。
 * @returns 整数键。
 */
export function encodeKey(glyph: number, row: number, alpha: number, overlay: number, tile: number): number {
  const aq = Math.max(0, Math.min(63, Math.round(alpha * 63)));
  const oq = Math.max(0, Math.min(15, Math.round(overlay * 15)));
  const tq = Math.max(0, Math.min(7, Math.round(tile / 0.05)));
  const g = aq === 0 && oq === 0 ? GLYPH_BLANK : glyph;
  return (((((g & 15) * 32 + (row & 31)) * 64 + aq) * 16 + oq) * 8) + tq;
}

/** 解码绘制键。 */
export function decodeKey(k: number): KeyParts {
  const tile = (k % 8) * 0.05;
  k = Math.floor(k / 8);
  const overlay = (k % 16) / 15;
  k = Math.floor(k / 16);
  const alpha = (k % 64) / 63;
  k = Math.floor(k / 64);
  const row = k % 32;
  const glyph = Math.floor(k / 32);
  return { glyph, row, alpha, overlay, tile };
}

/**
 * 由采样与几何构造字符场模型。
 * @param P - 布局。
 * @param sample - `averageCells` 的结果。
 * @param shape - 方块几何与渐变轴。
 * @param cfg - 参数。
 * @returns 模型。
 */
export function createFieldModel(P: FieldPlacement, sample: Float32Array, shape: FieldShape, cfg: InstallFieldConfig = INSTALL_FIELD): FieldModel {
  const n = P.cols * P.rows;
  const cls = new Uint8Array(n);
  const level = new Uint8Array(n);
  const alpha = new Float32Array(n);
  const tileA = new Float32Array(n);
  const glyph = new Uint8Array(n);
  const lockAt = new Float32Array(n);
  const falloff = new Float32Array(n);
  const drawable = new Uint8Array(n);
  const safe = new Uint8Array(n);
  const scrUntil = new Float32Array(n);
  const half = shape.S / 2;
  const haloPx = cfg.halo * shape.S;
  const [fa0, fa1] = cfg.fieldAlpha;
  let lockEnd = 0;
  const pool: number[] = [];

  for (let r = 0; r < P.rows; r++) {
    const row = codeRow(r, P.cols, cfg.codes);
    for (let c = 0; c < P.cols; c++) {
      const i = r * P.cols + c;
      const R = sample[i * 3];
      const G = sample[i * 3 + 1];
      const B = sample[i * 3 + 2];
      // 格中心（面板坐标）
      const px = P.region.x + (c + 0.5) * P.cw;
      const py = P.region.y + (r + 0.5) * P.ch;
      const sdf = roundRectSdf(px, py, shape.cx, shape.cy, half, shape.radius);
      let k: number = CLS.field;
      if (G > 0.3) k = CLS.light;
      else if (B > 0.3) k = CLS.acc;
      else if (R + G + B > 0.12) k = CLS.body;
      cls[i] = k;
      const rnd = hash01(i, 7);
      const ch = row[c];
      const inShape = k !== CLS.field;
      glyph[i] = ch === ' ' ? (inShape ? GLYPH_DOT : GLYPH_BLANK) : ch.charCodeAt(0) - 48;
      if (k === CLS.light) {
        alpha[i] = Math.min(1, G / 0.55);
        tileA[i] = cfg.tileAlpha[1];
      } else if (k === CLS.acc) {
        alpha[i] = Math.min(1, B / 0.55);
        tileA[i] = cfg.tileAlpha[2];
      } else if (k === CLS.body) {
        alpha[i] = 0.92 * Math.pow(Math.min(1, R + G + B), 0.7);
        tileA[i] = cfg.tileAlpha[0];
        // 色阶：格中心在方块局部坐标里对渐变轴的投影
        const lx = (px - (shape.cx - half)) / shape.S;
        const ly = (py - (shape.cy - half)) / shape.S;
        const ax = shape.grad.x2 - shape.grad.x1;
        const ay = shape.grad.y2 - shape.grad.y1;
        const u = ((lx - shape.grad.x1) * ax + (ly - shape.grad.y1) * ay) / (ax * ax + ay * ay || 1);
        level[i] = Math.max(0, Math.min(GRAD_LEVELS - 1, Math.floor(u * GRAD_LEVELS)));
      } else {
        const fall = 1 - smoothstep(0, 1, Math.max(0, sdf) / haloPx);
        falloff[i] = fall;
        alpha[i] = (fa0 + (fa1 - fa0) * hash01(i, 3)) * fall;
      }
      if (k === CLS.field) falloff[i] ||= 0;
      else falloff[i] = 1;
      drawable[i] = inShape || (alpha[i] > 0.004 && glyph[i] !== GLYPH_BLANK) ? 1 : 0;
      if (drawable[i]) pool.push(i);
      const s = Math.hypot(px - shape.cx, py - shape.cy) / (0.72 * shape.S);
      const d = Math.max(0, Math.min(1, sdf / haloPx));
      lockAt[i] = cfg.lockStart + (inShape ? cfg.lockSpanIn * s : 0.52 + cfg.lockSpanOut * d) + cfg.lockJitter * rnd;
      if (drawable[i]) lockEnd = Math.max(lockEnd, lockAt[i]);
    }
  }

  let twinkleAcc = 0;
  let twinkleSeed = 1;
  const cap = cfg.safeCap;
  const capFor = (k: number) => (k === CLS.light ? cap.light : k === CLS.acc ? cap.acc : k === CLS.body ? cap.body : cap.field);
  const rowFor = (i: number) => (cls[i] === CLS.light ? ROW_LIGHT : cls[i] === CLS.acc ? ROW_ACC : cls[i] === CLS.body ? level[i] : ROW_FIELD);
  const regionDiag = P.region.w + P.region.h || 1;
  const entranceEnd = lockEnd + cfg.flashDur;

  return {
    P,
    count: n,
    cls,
    safe,
    lockEnd,
    entranceEnd,
    applySafe(boxes) {
      const next = new Uint8Array(n);
      const pad = cfg.safePad;
      for (const b of boxes) {
        const c0 = Math.max(0, Math.floor((b.x - pad - P.region.x) / P.cw));
        const c1 = Math.min(P.cols - 1, Math.floor((b.x + b.w + pad - P.region.x) / P.cw));
        const r0 = Math.max(0, Math.floor((b.y - pad - P.region.y) / P.ch));
        const r1 = Math.min(P.rows - 1, Math.floor((b.y + b.h + pad - P.region.y) / P.ch));
        for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) next[r * P.cols + c] = 1;
      }
      let changed = 0;
      for (let i = 0; i < n; i++) {
        if (next[i] !== safe[i]) changed++;
        safe[i] = next[i];
      }
      return changed;
    },
    update(t, dt, idle) {
      if (!idle || pool.length === 0) return;
      twinkleAcc += cfg.twinkleRate * pool.length * dt;
      while (twinkleAcc >= 1) {
        twinkleAcc -= 1;
        twinkleSeed++;
        const i = pool[Math.floor(hash01(twinkleSeed, 11) * pool.length)];
        if (scrUntil[i] <= t) scrUntil[i] = t + 0.25 + 0.35 * hash01(twinkleSeed, 13);
      }
    },
    pointer(x, y, t) {
      const R = cfg.pointerR;
      const c0 = Math.max(0, Math.floor((x - R - P.region.x) / P.cw));
      const c1 = Math.min(P.cols - 1, Math.floor((x + R - P.region.x) / P.cw));
      const r0 = Math.max(0, Math.floor((y - R - P.region.y) / P.ch));
      const r1 = Math.min(P.rows - 1, Math.floor((y + R - P.region.y) / P.ch));
      for (let r = r0; r <= r1; r++) {
        for (let c = c0; c <= c1; c++) {
          const i = r * P.cols + c;
          if (!drawable[i] || safe[i] || scrUntil[i] > t || t < lockAt[i]) continue;
          const px = P.region.x + (c + 0.5) * P.cw;
          const py = P.region.y + (r + 0.5) * P.ch;
          if (Math.hypot(px - x, py - y) > R) continue;
          scrUntil[i] = t + 0.3 + 0.25 * hash01(i, Math.floor(t * 10));
        }
      }
    },
    key(i, t, idle, final = false) {
      if (!drawable[i]) return encodeKey(GLYPH_BLANK, 0, 0, 0, 0);
      const isSafe = safe[i] === 1;
      const k = cls[i];
      if (!final && t < lockAt[i]) {
        // 锁定前约 15 Hz 乱码，场色，α 0.1–0.22（场格乘以光晕衰减）
        if (t <= 0) return encodeKey(GLYPH_BLANK, 0, 0, 0, 0);
        const g = Math.floor(hash01(i, Math.floor(t * 15)) * 10);
        let a = (0.1 + 0.12 * hash01(i, 5)) * falloff[i];
        if (isSafe) a = Math.min(a, cap.field);
        return encodeKey(g, ROW_FIELD, a, 0, 0);
      }
      let g = glyph[i];
      let a = alpha[i];
      let tile = k === CLS.field ? 0 : tileA[i];
      let ov = 0;
      if (!final) {
        const since = t - lockAt[i];
        if (since < cfg.flashDur) ov = Math.pow(1 - since / cfg.flashDur, 2) * (k !== CLS.field ? 0.9 : 0.45);
        if (scrUntil[i] > t) g = Math.floor(hash01(i, Math.floor(t * 15)) * 10);
        if (idle && t >= entranceEnd && k !== CLS.field) {
          const phase = (t - entranceEnd) % cfg.glintPeriod;
          if (phase < cfg.glintDur) {
            const band = 0.12;
            const pos = -band + ((1 + 2 * band) * phase) / cfg.glintDur;
            const c = i % P.cols;
            const r = (i - c) / P.cols;
            const u = ((c + 0.5) * P.cw + (r + 0.5) * P.ch) / regionDiag;
            ov = Math.max(ov, 0.42 * Math.max(0, 1 - Math.abs(u - pos) / band));
          }
        }
      }
      if (isSafe) {
        a = Math.min(a, capFor(k));
        ov = Math.min(ov, cap.overlay);
        tile = Math.min(tile, 0.05);
      }
      return encodeKey(g, rowFor(i), a, ov, tile);
    },
    busy(t) {
      if (t < entranceEnd) return true;
      for (const i of pool) if (scrUntil[i] > t) return true;
      return false;
    },
  };
}

/**
 * sRGB 相对亮度（WCAG）。
 * @param rgb - 0..255。
 * @returns 0..1。
 */
export function relativeLuminance(rgb: [number, number, number]): number {
  const lin = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
}

/**
 * 在 sRGB 空间把颜色以 α 依次叠到底色上（画布的合成方式）。
 * @param base - 底色。
 * @param layers - [颜色, α] 列表。
 * @returns 合成色。
 */
export function composite(base: [number, number, number], layers: [[number, number, number], number][]): [number, number, number] {
  let c = base;
  for (const [col, a] of layers) c = [0, 1, 2].map((j) => c[j] + (col[j] - c[j]) * a) as [number, number, number];
  return c;
}
