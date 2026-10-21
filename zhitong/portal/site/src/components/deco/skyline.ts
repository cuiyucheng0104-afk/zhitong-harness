/**
 * D3 页脚楼群（按用户意见替代 07 章 §7 的单栋透视楼：不画轴号、标高，楼房在页脚铺满一排）。
 * 纯函数生成正立面线框，供 `DecoFooterMark.vue` 在构建期直接输出 SVG；同一组参数每次输出相同。
 */

/** 画布尺寸（SVG 用户单位）与楼层、开间网格。 */
export const SKYLINE = { width: 1248, height: 168, floor: 12, bay: 12, gap: 10 } as const;

export interface Tower {
  /** 左边缘 x。 */
  x: number;
  w: number;
  /** 楼高（不含屋顶机房）。 */
  h: number;
  /** 屋顶机房：宽、高；0 表示没有。 */
  roofW: number;
  roofH: number;
  /** 进入视口时上升动画的延迟序号。 */
  order: number;
}

/** 固定种子的伪随机数（mulberry32），保证预渲染与客户端一致。 */
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * 从左到右排满整行：宽 48–120（开间整数倍），高 4–12 层（层高整数倍），约三分之一带屋顶机房；
 * 最后一栋拉宽到恰好贴住右边缘。
 * @param seed - 随机种子。
 * @returns 楼栋列表，按 x 升序。
 */
export function skyline(seed = 7): Tower[] {
  const r = rng(seed);
  const { width, floor, bay, gap } = SKYLINE;
  const towers: Tower[] = [];
  let x = 0;
  while (x < width) {
    let w = bay * (4 + Math.floor(r() * 7));
    const rest = width - x - w - gap;
    if (rest < bay * 4) w = width - x;
    const floors = 4 + Math.floor(r() * 9);
    const roof = r() < 0.35 && w >= bay * 5;
    towers.push({
      x,
      w,
      h: floors * floor,
      roofW: roof ? bay * 2 : 0,
      roofH: roof ? floor : 0,
      order: towers.length,
    });
    x += w + gap;
  }
  return towers;
}

/**
 * 一栋楼的窗格线（楼层线与开间线），不含外轮廓。
 * @param t - 楼栋。
 * @returns SVG path 的 d 字符串。
 */
export function towerGrid(t: Tower): string {
  const { height, floor, bay } = SKYLINE;
  const top = height - t.h;
  const parts: string[] = [];
  for (let y = top + floor; y < height; y += floor) parts.push(`M${t.x} ${y}H${t.x + t.w}`);
  for (let x = t.x + bay; x < t.x + t.w; x += bay) parts.push(`M${x} ${top}V${height}`);
  return parts.join('');
}
