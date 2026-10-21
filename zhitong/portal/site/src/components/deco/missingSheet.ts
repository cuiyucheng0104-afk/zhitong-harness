/**
 * D5 404 图纸缺页的几何（07 章 §9.2–9.3）：纯函数 `missingSheetParts()`，随机数用固定种子（Park–Miller），
 * SSR 时输出静态 SVG 进入 `dist/404.html`，水合结果一致，两次构建字节相同（AC-07-33）。
 *
 * 一张 A3 横幅底稿（420 × 297，装订边 25、其余 5，GB/T 50001）：二层平面图画到接合线为止，旁注“接 A-404”；
 * 接合线另一侧是空白，修订云线圈出空白，索引符号指向“缺页：本页不在图纸目录中”，一枚“缺页”审核章落下，
 * 十字光标在空白处来回搜寻，读数 `X ?  Y ?`。动画全用 CSS：基础样式即终态，`@keyframes` 只描述“从哪里来”。
 */

export type PartTag = 'path' | 'circle' | 'text' | 'rect' | 'g';

export interface SheetPart {
  tag: PartTag;
  /** SVG 属性（数值已格式化为字符串）。 */
  attrs: Record<string, string>;
  /** 样式类：`ms-draw`（描线）、`ms-fade`（淡入）、`ms-pop`（放大）、`ms-stamp`（盖章）及颜色类。 */
  cls: string;
  /** 动画时长与延迟（秒），写进 `style="--t; --d"`。 */
  t?: number;
  d?: number;
  text?: string;
  children?: SheetPart[];
}

/** Park–Miller 最小标准随机数（种子固定）。 */
export function parkMiller(seed = 404): () => number {
  let s = seed % 2147483647;
  if (s <= 0) s += 2147483646;
  return () => {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

const n = (v: number) => String(Math.round(v * 100) / 100);

function path(d: string, cls: string, t?: number, dl?: number, extra: Record<string, string> = {}): SheetPart {
  return { tag: 'path', attrs: { d, ...(cls.includes('ms-draw') ? { pathLength: '1' } : {}), ...extra }, cls, t, d: dl };
}

function text(x: number, y: number, s: string, cls: string, t?: number, dl?: number, extra: Record<string, string> = {}): SheetPart {
  return { tag: 'text', attrs: { x: n(x), y: n(y), ...extra }, cls, t, d: dl, text: s };
}

/** 平面图轴线位置（mm）。 */
export const SHEET = {
  axesX: [60, 122, 184, 246],
  axesY: [86, 148, 210],
  faintX: [308, 370],
  matchX: 262,
  cloud: { x0: 285, y0: 60, x1: 400, y1: 228 },
  /** 十字光标在空白区搜寻的 5 个点。 */
  roam: [
    [310, 92],
    [378, 98],
    [370, 204],
    [302, 208],
    [322, 128],
  ] as [number, number][],
};

/** 22 段墙（两端点，mm）。 */
export const WALLS: [number, number, number, number][] = [
  // 外墙（窗洞处断开）
  [60, 86, 75, 86],
  [99, 86, 137, 86],
  [161, 86, 199, 86],
  [223, 86, 262, 86],
  [60, 210, 80, 210],
  [104, 210, 142, 210],
  [166, 210, 204, 210],
  [228, 210, 262, 210],
  [60, 86, 60, 126],
  [60, 146, 60, 210],
  // 走廊墙（门洞处断开）
  [60, 136, 110, 136],
  [120, 136, 172, 136],
  [182, 136, 234, 136],
  [244, 136, 262, 136],
  [60, 160, 90, 160],
  [100, 160, 152, 160],
  [162, 160, 214, 160],
  [224, 160, 262, 160],
  // 隔墙
  [122, 86, 122, 136],
  [122, 160, 122, 210],
  [184, 86, 184, 136],
  [184, 160, 184, 210],
];

/**
 * 修订云线：沿矩形顺时针，弦长 11 mm（随机 ±25%），每段 `A r r 0 0 1`（r = 0.62 × 弦长，外凸）。
 * @param rand - 随机数源。
 * @returns path d。
 */
export function revisionCloud(rand: () => number): string {
  const { x0, y0, x1, y1 } = SHEET.cloud;
  const corners: [number, number][] = [
    [x0, y0],
    [x1, y0],
    [x1, y1],
    [x0, y1],
  ];
  let d = `M${n(x0)} ${n(y0)}`;
  for (let e = 0; e < 4; e++) {
    const [ax, ay] = corners[e];
    const [bx, by] = corners[(e + 1) % 4];
    const len = Math.hypot(bx - ax, by - ay);
    // 每条边约 len/11 段；每段弦长按 ±25% 随机加权后归一到边长，最后一段正好落在角点上
    const count = Math.max(1, Math.round(len / 11));
    const weights = Array.from({ length: count }, () => 1 + 0.25 * (2 * rand() - 1));
    const sum = weights.reduce((a, b) => a + b, 0);
    let pos = 0;
    for (const w of weights) {
      const chord = (w / sum) * len;
      pos += chord;
      const k = Math.min(1, pos / len);
      const r = 0.62 * chord;
      d += `A${n(r)} ${n(r)} 0 0 1 ${n(ax + (bx - ax) * k)} ${n(ay + (by - ay) * k)}`;
    }
  }
  return `${d}Z`;
}

/**
 * 生成整张图的部件（约 190 个元素）。
 * @param seed - 随机种子（默认 404）。
 * @returns 部件列表（按绘制顺序）。
 */
export function missingSheetParts(seed = 404): SheetPart[] {
  const rand = parkMiller(seed);
  const parts: SheetPart[] = [];
  const { axesX, axesY, faintX, matchX } = SHEET;

  // 0–0.75 图纸外缘（细）、图框（1.0）
  parts.push(path('M0 0H420V297H0Z', 'ms-draw ms-ink ms-w035', 0.75, 0));
  parts.push(path('M25 5H415V292H25Z', 'ms-draw ms-ink ms-w1', 0.75, 0));

  // 0.5–1.3 标题栏
  const tb = { x0: 255, y0: 252, x1: 415, y1: 292 };
  parts.push(path(`M${tb.x0} ${tb.y0}H${tb.x1}`, 'ms-draw ms-ink ms-w05', 0.4, 0.5));
  parts.push(path(`M${tb.x0} ${tb.y0}V${tb.y1}`, 'ms-draw ms-ink ms-w05', 0.4, 0.5));
  [262, 272, 282].forEach((y, i) => parts.push(path(`M${tb.x0} ${y}H${tb.x1}`, 'ms-draw ms-ink ms-w035', 0.4, 0.58 + 0.06 * i)));
  parts.push(path(`M280 ${tb.y0}V${tb.y1}`, 'ms-draw ms-ink ms-w035', 0.4, 0.76));
  parts.push(path('M340 272V282M360 272V282', 'ms-draw ms-ink ms-w035', 0.3, 0.82));
  const rows: [number, string, string][] = [
    [259.5, '工程名称', '智通数工AI 门户'],
    [269.5, '图名', '页面不存在'],
    [289.5, '页次', '404 / —'],
  ];
  rows.forEach(([y, label, value], i) => {
    parts.push(text(259, y, label, 'ms-fade ms-txt ms-label', 0.4, 0.85 + 0.08 * i));
    parts.push(text(284, y, value, 'ms-fade ms-txt', 0.4, 0.9 + 0.08 * i));
  });
  parts.push(text(259, 279.5, '图号', 'ms-fade ms-txt ms-label', 0.4, 1.0));
  parts.push(text(284, 279.5, 'A-404', 'ms-fade ms-txt ms-mono', 0.4, 1.02));
  parts.push(text(343, 279.5, '比例', 'ms-fade ms-txt ms-label', 0.4, 1.06));
  parts.push(text(364, 279.5, '1:100', 'ms-fade ms-txt ms-mono', 0.4, 1.1));

  // 0.7–1.1 轴线淡入（接合线以外更淡）、轴号弹出
  const axis = 'ms-fade ms-axis';
  axesX.forEach((x, i) => parts.push(path(`M${x} 24V238`, axis, 0.4, 0.7 + 0.03 * i)));
  faintX.forEach((x, i) => parts.push(path(`M${x} 24V238`, `${axis} ms-faint`, 0.4, 0.82 + 0.03 * i)));
  axesY.forEach((y, j) => {
    parts.push(path(`M38 ${y}H${matchX}`, axis, 0.4, 0.74 + 0.03 * j));
    parts.push(path(`M${matchX} ${y}H404`, `${axis} ms-faint`, 0.4, 0.84 + 0.03 * j));
  });
  [...axesX, ...faintX].forEach((x, i) => {
    const faint = i >= axesX.length ? ' ms-faint' : '';
    parts.push({ tag: 'circle', attrs: { cx: n(x), cy: '18', r: '4.2' }, cls: `ms-pop ms-bubble${faint}`, t: 0.3, d: 0.8 + 0.03 * i });
    parts.push(text(x, 19.5, String(i + 1), `ms-pop ms-txt ms-mono ms-btxt${faint}`, 0.3, 0.82 + 0.03 * i));
  });
  ['C', 'B', 'A'].forEach((label, j) => {
    const y = axesY[j];
    parts.push({ tag: 'circle', attrs: { cx: '33', cy: n(y), r: '4.2' }, cls: 'ms-pop ms-bubble', t: 0.3, d: 0.86 + 0.03 * j });
    parts.push(text(33, y + 1.5, label, 'ms-pop ms-txt ms-mono ms-btxt', 0.3, 0.88 + 0.03 * j));
  });

  // 1.0–1.5 尺寸链 6 200 × 3 与起止符
  parts.push(path(`M${axesX[0] - 4} 32H${axesX[3] + 4}`, 'ms-draw ms-ink ms-w035', 0.5, 1.0));
  axesX.forEach((x, i) => {
    parts.push(path(`M${x} 28V36`, 'ms-draw ms-ink ms-w035', 0.2, 1.05 + 0.04 * i));
    parts.push(path(`M${x - 2} 34L${x + 2} 30`, 'ms-draw ms-ink ms-w07', 0.15, 1.15 + 0.04 * i));
  });
  for (let i = 0; i < 3; i++) parts.push(text((axesX[i] + axesX[i + 1]) / 2, 29.5, '6 200', 'ms-fade ms-txt ms-mono ms-dim', 0.3, 1.2 + 0.05 * i));

  // 1.15–2.6 22 段墙，依次相隔 0.045 s（先浅色 2.6，再 #082457 1.5，得到双线墙）
  WALLS.forEach(([x1, y1, x2, y2], i) => parts.push(path(`M${x1} ${y1}L${x2} ${y2}`, 'ms-draw ms-wall-o', 0.5, 1.15 + 0.045 * i)));
  WALLS.forEach(([x1, y1, x2, y2], i) => parts.push(path(`M${x1} ${y1}L${x2} ${y2}`, 'ms-draw ms-wall-i', 0.5, 1.15 + 0.045 * i)));

  // 1.95–2.6 柱（5 × 5）、窗（三线）、门（门扇 + 1/4 圆弧）、楼梯、房间名
  let k = 0;
  for (const y of axesY)
    for (const x of axesX) {
      parts.push({ tag: 'rect', attrs: { x: n(x - 2.5), y: n(y - 2.5), width: '5', height: '5' }, cls: 'ms-pop ms-col', t: 0.2, d: 1.95 + 0.035 * k++ });
    }
  const windows: [number, number, number, number][] = [
    [75, 86, 99, 86],
    [137, 86, 161, 86],
    [199, 86, 223, 86],
    [80, 210, 104, 210],
    [142, 210, 166, 210],
    [204, 210, 228, 210],
    [60, 126, 60, 146],
  ];
  windows.forEach(([x1, y1, x2, y2], i) => {
    const vertical = x1 === x2;
    const d = [-1.1, 0, 1.1]
      .map((o) => (vertical ? `M${x1 + o} ${y1}V${y2}` : `M${x1} ${y1 + o}H${x2}`))
      .join('');
    parts.push(path(d, 'ms-draw ms-ink ms-w035', 0.3, 2.0 + 0.04 * i));
  });
  const doors: [number, number, number][] = [
    // 铰点 x、墙 y、开向（−1 向上进房间，+1 向下）
    [110, 136, -1],
    [172, 136, -1],
    [234, 136, -1],
    [90, 160, 1],
    [152, 160, 1],
    [214, 160, 1],
  ];
  doors.forEach(([x, y, dir], i) => {
    const leaf = `M${x} ${y}V${y + dir * 10}`;
    const arc = `M${x} ${y + dir * 10}A10 10 0 0 ${dir < 0 ? 1 : 0} ${x + 10} ${y}`;
    parts.push(path(leaf + arc, 'ms-draw ms-ink ms-w035', 0.3, 2.1 + 0.04 * i));
  });
  const treads = Array.from({ length: 9 }, (_, i) => `M${132 + 5 * i} 166V184M${132 + 5 * i} 186V204`).join('');
  parts.push(path(`${treads}M130 185H176`, 'ms-draw ms-ink ms-w035', 0.3, 2.25));
  const rooms: [number, number, string][] = [
    [91, 113, '会议室201'],
    [153, 113, '办公室202'],
    [223, 113, '办公室203'],
    [91, 187, '办公室204'],
    [153, 196, '楼梯间'],
    [223, 187, '卫生间'],
    [200, 150, '走廊'],
  ];
  rooms.forEach(([x, y, s], i) => parts.push(text(x, y, s, 'ms-fade ms-txt ms-room', 0.3, 2.3 + 0.04 * i, { 'text-anchor': 'middle' })));

  // 2.7–2.8 接合线、“接 A-404”
  parts.push(path(`M${matchX} 40V240`, 'ms-fade ms-match', 0.1, 2.7));
  parts.push(text(matchX + 3, 244, '接 A-404', 'ms-fade ms-txt', 0.1, 2.72));

  // 2.95–3.85 修订云线
  parts.push(path(revisionCloud(rand), 'ms-draw ms-warm ms-w07', 0.9, 2.95));

  // 3.7–4.1 引出线、索引符号 Ø10（上“1”、下“404”）、注释
  parts.push(path('M305 40H340L352 57', 'ms-draw ms-warm ms-w05', 0.25, 3.7));
  parts.push({ tag: 'circle', attrs: { cx: '300', cy: '40', r: '5' }, cls: 'ms-pop ms-warm ms-w05', t: 0.2, d: 3.78 });
  parts.push(path('M295 40H305', 'ms-draw ms-warm ms-w035', 0.15, 3.85));
  parts.push(text(300, 38.6, '1', 'ms-fade ms-warmtxt ms-mono ms-idx', 0.2, 3.9, { 'text-anchor': 'middle' }));
  parts.push(text(300, 43.9, '404', 'ms-fade ms-warmtxt ms-mono ms-idx', 0.2, 3.92, { 'text-anchor': 'middle' }));
  parts.push(text(308, 37, '缺页：本页不在图纸目录中', 'ms-fade ms-warmtxt ms-note', 0.2, 3.9));

  // 3.75–4.25 审核章
  parts.push({
    tag: 'g',
    attrs: { transform: 'rotate(-8 345 150)' },
    cls: '',
    children: [
      {
        tag: 'g',
        attrs: {},
        cls: 'ms-stamp',
        t: 0.5,
        d: 3.75,
        children: [
          { tag: 'rect', attrs: { x: '322', y: '138', width: '46', height: '24', rx: '2.5' }, cls: 'ms-warm ms-w12' },
          { tag: 'rect', attrs: { x: '324.5', y: '140.5', width: '41', height: '19', rx: '1.5' }, cls: 'ms-warm ms-w035' },
          { tag: 'text', attrs: { x: '345', y: '154', 'text-anchor': 'middle' }, cls: 'ms-warmtxt ms-stampTxt', text: '缺页' },
        ],
      },
    ],
  });

  // 4.4 起 十字光标循环（基础位置为第一个搜寻点）
  parts.push({
    tag: 'g',
    attrs: {},
    cls: 'ms-cross',
    children: [
      { tag: 'path', attrs: { d: 'M-16 0H-3M3 0H16M0 -16V-3M0 3V16' }, cls: 'ms-crossline' },
      { tag: 'rect', attrs: { x: '-2.5', y: '-2.5', width: '5', height: '5' }, cls: 'ms-crossbox' },
      { tag: 'rect', attrs: { x: '6', y: '-14', width: '27', height: '7', rx: '1' }, cls: 'ms-readbg' },
      { tag: 'text', attrs: { x: '8', y: '-9' }, cls: 'ms-readtxt ms-mono', text: 'X ?  Y ?' },
    ],
  });
  return parts;
}

/** 部件总数（含子元素），用于核对约 190 个元素。 */
export function countParts(parts: SheetPart[]): number {
  return parts.reduce((s, p) => s + 1 + (p.children ? countParts(p.children) : 0), 0);
}
