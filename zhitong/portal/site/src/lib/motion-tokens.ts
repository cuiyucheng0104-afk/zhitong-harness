/**
 * 动效变量（00 章 §5.2）。GSAP 时间线用秒；CSS 侧同名变量见 styles/tokens.css。
 */
export const DUR = { micro: 0.16, short: 0.28, base: 0.45, long: 0.8, scene: 1.2 } as const;

export const EASE = {
  /** 入场、展开 */
  out: 'power3.out',
  /** 场景切换、位移 */
  inOut: 'power2.inOut',
  /** 大标题、数字落定 */
  expo: 'expo.out',
  /** 磁吸回弹 */
  snapBack: 'elastic.out(1, 0.45)',
  /** 进度条、滚动驱动 */
  linear: 'none',
} as const;

export const STAGGER = { tight: 0.04, base: 0.07, loose: 0.12 } as const;

/** ScrollTrigger scrub 追赶秒数 */
export const SCRUB = { soft: 0.6, damp: 1, heavy: 1.6 } as const;

/** 与 CSS `--ease-out`、`--ease-in-out` 等价的贝塞尔曲线，供 Web Animations API 使用。 */
export const CSS_EASE = {
  out: 'cubic-bezier(.22,1,.36,1)',
  inOut: 'cubic-bezier(.65,0,.35,1)',
  spring: 'cubic-bezier(.34,1.56,.64,1)',
} as const;

/** 毫秒版时长，供 Web Animations API 使用。 */
export const MS = {
  micro: DUR.micro * 1000,
  short: DUR.short * 1000,
  base: DUR.base * 1000,
  long: DUR.long * 1000,
} as const;
